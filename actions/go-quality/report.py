#!/usr/bin/env python3
"""Collects what the Go quality tools found into one report, and holds the ratchet.

Reads whichever of these exist in the output directory and skips the rest, so the same
script serves the per-push run and the weekly one:

  golangci.json      golangci-lint with this action's golangci.yml
  metrics.json       gometrics: package fan-in and fan-out, type cohesion, file size, comments
  coverage.txt       go tool cover -func output

Always writes quality-report.json (an agent reads this to find gaps) and summary.md (CI
appends it to the job summary). The report and baseline formats match the Java services'.

A finding is identified by tool, rule, file and message with the numbers taken out, so
moving code or changing a count does not make it new.

  report.py --out DIR                          report only
  report.py --out DIR --check BASELINE         fail on a new finding, on a fixed one still in
             [--base FILE] [--renames FILE]    the baseline, or (with --base, the base
                                               branch's baseline) on a baseline that grew
  report.py --out DIR --write-baseline BASELINE   accept what is there now
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

RATCHETED = {"golangci", "gometrics"}

# A package, type or file past any of these is a hotspot, and a new hotspot is a finding.
HOTSPOT = {"fanout": 15, "lcom4": 2, "file_code_lines": 500}

findings = []
metrics = {}
tools = {}


def add(tool, rule, file, line, message, category):
    findings.append({
        "tool": tool,
        "rule": rule,
        "category": category,
        "file": file,
        "line": int(line) if line else None,
        "message": " ".join((message or "").split()),
    })


def fingerprint(f):
    return canonical("%s|%s|%s|%s" % (f["tool"], f["rule"], f["file"], re.sub(r"\d+", "#", f["message"])))


def canonical(fp):
    """A duplication is identified by the files that share it, once per set of files.

    dupl reports each copy against each other, and splits overlapping copies into blocks
    whose line ranges move with every edit. Keyed by its files, the ratchet still fails
    when two files that shared nothing start to.
    """
    parts = fp.split("|", 3)
    if len(parts) < 4 or parts[:2] != ["golangci", "dupl"]:
        return fp
    _, _, file, message = parts
    others = re.findall(r"([\w/#.-]+\.go):#-#", message)
    return "golangci|dupl|" + ";".join(sorted({file} | set(others)))


def renamed(fp, renames):
    parts = fp.split("|", 3)
    if len(parts) == 4:
        tool, rule, file, message = parts
        return canonical("|".join((tool, rule, renames.get(file, file), message)))
    tool, rule, files = parts
    return "|".join((tool, rule, ";".join(sorted({renames.get(f, f) for f in files.split(";")}))))


def once_per_duplication(counter):
    return Counter({fp: (1 if fp.startswith("golangci|dupl|") else n) for fp, n in counter.items()})


CATEGORY = {
    "dupl": "duplication",
    "funlen": "size",
    "gocognit": "complexity",
    "gocyclo": "complexity",
    "maintidx": "complexity",
    "nestif": "complexity",
    "gosec": "security",
}


def golangci(out):
    path = os.path.join(out, "golangci.json")
    if not os.path.exists(path):
        return
    data = json.load(open(path))
    count = 0
    for issue in data.get("Issues") or []:
        linter = issue.get("FromLinter", "")
        text = issue.get("Text", "")
        rule = linter
        m = re.match(r"^(G\d{3}):?\s*(.*)$", text) if linter == "gosec" else None
        if m:
            rule, text = "gosec:" + m.group(1), m.group(2)
        pos = issue.get("Pos") or {}
        add("golangci", rule, pos.get("Filename", ""), pos.get("Line"), text, CATEGORY.get(linter, "correctness"))
        count += 1
    tools["golangci"] = {"findings": count}


def gometrics(out):
    path = os.path.join(out, "metrics.json")
    if not os.path.exists(path):
        return
    data = json.load(open(path))
    hotspots = []
    for p in data.get("packages", []):
        if p["fanout"] > HOTSPOT["fanout"]:
            add("gometrics", "Hotspot-fanout", p["dir"] + "/", None,
                "%s: fanout is %d, past %d" % (p["dir"], p["fanout"], HOTSPOT["fanout"]), "design")
            hotspots.append({"kind": "package", "name": p["dir"], "value": p["fanout"], "over": "fanout"})
    for t in data.get("types", []):
        if t["lcom4"] > HOTSPOT["lcom4"]:
            add("gometrics", "Hotspot-lcom4", t["file"], t["line"],
                "%s: lcom4 is %d over %d methods, past %d" % (t["name"], t["lcom4"], t["methods"], HOTSPOT["lcom4"]),
                "design")
            hotspots.append({"kind": "type", "name": t["file"] + ":" + t["name"], "value": t["lcom4"], "over": "lcom4"})
    files = data.get("files", [])
    for f in files:
        if f["code_lines"] > HOTSPOT["file_code_lines"]:
            add("gometrics", "Hotspot-loc", f["file"], None,
                "%d code lines, past %d" % (f["code_lines"], HOTSPOT["file_code_lines"]), "size")
            hotspots.append({"kind": "file", "name": f["file"], "value": f["code_lines"], "over": "loc"})
    code = sum(f["code_lines"] for f in files)
    comments = sum(f["comment_lines"] for f in files)
    metrics["size"] = {
        "packages": len(data.get("packages", [])),
        "types": len(data.get("types", [])),
        "files": len(files),
        "code_lines": code,
        "comment_lines": comments,
        "comment_percent": round(100 * comments / (code + comments), 1) if code + comments else None,
    }
    metrics["most_commented"] = [
        {"file": f["file"], "comment_lines": f["comment_lines"], "code_lines": f["code_lines"]}
        for f in sorted(files, key=lambda f: -f["comment_lines"])[:10]
    ]
    metrics["packages"] = data.get("packages", [])
    metrics["hotspots"] = sorted(hotspots, key=lambda h: (h["over"], -h["value"]))
    tools["gometrics"] = {"packages": len(data.get("packages", [])), "hotspots": len(hotspots)}


def coverage(out):
    path = os.path.join(out, "coverage.txt")
    if not os.path.exists(path):
        return
    total = None
    for line in open(path):
        if line.startswith("total:"):
            total = float(line.split()[-1].rstrip("%"))
    metrics["coverage"] = {"statement_percent": total}
    tools["coverage"] = {"statement_percent": total}


def ratchet(baseline_path, base_path, renames):
    """Compares with the baseline. Returns (new, fixed, grown) as lists of fingerprints."""
    ran = RATCHETED & set(tools)
    current = once_per_duplication(Counter(fingerprint(f) for f in findings if f["tool"] in ran))
    accepted = Counter()
    if os.path.exists(baseline_path):
        accepted = Counter(canonical(fp) for fp in json.load(open(baseline_path))["accepted"])
    accepted = once_per_duplication(Counter({fp: n for fp, n in accepted.items() if fp.split("|", 1)[0] in ran}))
    new = list((current - accepted).elements())
    fixed = list((accepted - current).elements())
    grown = []
    if base_path and os.path.exists(base_path):
        on_base = Counter()
        for fp, n in Counter(json.load(open(base_path))["accepted"]).items():
            on_base[renamed(fp, renames)] += n
        grown = list((accepted - once_per_duplication(on_base)).elements())
    return sorted(new), sorted(fixed), sorted(grown)


def summary(outcome, baseline):
    lines = ["## Quality report", ""]
    if outcome is None:
        lines.append("Report only; no baseline was checked.")
    else:
        new, fixed, grown = outcome
        lines.append("**Ratchet: passed.** No new findings." if not (new or fixed or grown) else "**Ratchet: failed.**")
        lines.append("")
        if new:
            lines += ["### New findings (%d)" % len(new), "",
                      "Fix each one. Where the finding is wrong, suppress it where it stands with the reason "
                      "(`//nolint:linter // reason`). Do not add it to the baseline.", ""]
            by_fp = {}
            for f in findings:
                by_fp.setdefault(fingerprint(f), []).append(f)
            for fp in sorted(set(new)):
                for f in by_fp.get(fp, [])[: new.count(fp)]:
                    where = f["file"] + (":%d" % f["line"] if f["line"] else "")
                    lines.append("- `%s` %s/%s: %s" % (where, f["tool"], f["rule"], f["message"][:300]))
            lines.append("")
        if fixed:
            lines += ["### Fixed, still in the baseline (%d)" % len(fixed), "",
                      "Good. Run `make quality-baseline` and commit `%s` so the ratchet holds the "
                      "improvement." % baseline, ""]
            lines += ["- `%s`" % fp for fp in fixed[:20]]
            lines.append("")
        if grown:
            lines += ["### Baseline grew (%d)" % len(grown), "",
                      "This pull request added entries to `%s`, which accepts new findings instead of "
                      "fixing them. Remove them and fix or suppress the findings. A tool upgrade that "
                      "rewords its messages is the exception: label the pull request "
                      "`quality-baseline-reset`." % baseline, ""]
            lines += ["- `%s`" % fp for fp in grown[:20]]
            lines.append("")

    by_tool = Counter(f["tool"] for f in findings)
    lines += ["### All findings", "", "| Tool | Findings | Notes |", "|---|---|---|"]
    for tool in tools:
        note = ""
        if tool == "golangci":
            rules = Counter(f["rule"].split(":")[0] for f in findings if f["tool"] == "golangci")
            note = ", ".join("%s %d" % r for r in rules.most_common(6))
        if tool == "gometrics":
            s = metrics["size"]
            note = "%d packages, %d hotspots, %d code lines, comments %s%%" % (
                s["packages"], tools["gometrics"]["hotspots"], s["code_lines"], s["comment_percent"])
        if tool == "coverage":
            note = "statements %s%%" % metrics["coverage"]["statement_percent"]
        count = "" if tool == "coverage" else by_tool.get(tool, 0)
        lines.append("| %s | %s | %s |" % (tool, count, note))
    lines.append("")

    if metrics.get("hotspots"):
        lines += ["### Hotspots", "", "| Over | Where | Value |", "|---|---|---|"]
        for h in metrics["hotspots"][:15]:
            lines.append("| %s | `%s` | %s |" % (h["over"], h["name"], h["value"]))
        lines.append("")

    per_file = Counter(f["file"] for f in findings)
    if per_file:
        lines += ["### Files with the most findings", ""]
        for file, n in per_file.most_common(8):
            rules = Counter(f["rule"] for f in findings if f["file"] == file)
            lines.append("- `%s`: %d (%s)" % (file, n, ", ".join("%s %d" % r for r in rules.most_common(4))))
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--check", metavar="BASELINE")
    parser.add_argument("--base", metavar="FILE")
    parser.add_argument("--renames", metavar="FILE")
    parser.add_argument("--write-baseline", metavar="BASELINE")
    args = parser.parse_args()

    for collect in (golangci, gometrics, coverage):
        collect(args.out)

    if args.write_baseline:
        accepted = sorted(once_per_duplication(
            Counter(fingerprint(f) for f in findings if f["tool"] in RATCHETED)).elements())
        with open(args.write_baseline, "w") as f:
            json.dump({"schema": 1, "accepted": accepted}, f, indent=2, allow_nan=False)
            f.write("\n")
        print("Accepted %d findings into %s" % (len(accepted), args.write_baseline), file=sys.stderr)

    renames = {}
    if args.renames and os.path.exists(args.renames):
        for line in open(args.renames):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 2:
                renames[parts[0]] = parts[1]
    outcome = ratchet(args.check, args.base, renames) if args.check else None

    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = "%s/%s/actions/runs/%s" % (
            os.environ["GITHUB_SERVER_URL"], os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])
    report = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA"),
        "run_url": run_url,
        "ratchet": None if outcome is None else {"new": outcome[0], "fixed": outcome[1], "baseline_grew": outcome[2]},
        "tools": tools,
        "metrics": metrics,
        "findings": sorted(findings, key=lambda f: (f["file"], f["line"] or 0, f["tool"])),
    }
    with open(os.path.join(args.out, "quality-report.json"), "w") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    text = summary(outcome, args.check or args.write_baseline or "")
    with open(os.path.join(args.out, "summary.md"), "w") as f:
        f.write(text + "\n")
    print(text)

    if outcome and any(outcome):
        sys.exit(1)


if __name__ == "__main__":
    main()
