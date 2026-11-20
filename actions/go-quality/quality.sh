#!/usr/bin/env bash
# Runs the Go quality tools in the module in the working directory and holds the ratchet:
# a change may not add a finding.
#
#   quality.sh            measure, then check (what to run before opening a pull request)
#   quality.sh measure    run golangci-lint with golangci.yml beside this script, and gometrics
#   quality.sh check      report and compare with the baseline; with QUALITY_BASE_REF set, also
#                         refuse a baseline that grew relative to that ref
#   quality.sh baseline   measure, then accept what is there now, for a change that fixed
#                         findings (the baseline may only shrink)
#   quality.sh report     measure, then report without the ratchet; fails only on a fuzz crash
#
# QUALITY_BASELINE   the committed baseline, default .github/quality-baseline.json
# QUALITY_OUT        where reports go, default .quality
# QUALITY_COVERAGE   a coverprofile to read coverage from, optional
# QUALITY_BASE_REF   the ref to compare the baseline with, optional
# QUALITY_MUTATION   true to run gremlins mutation testing over the unit tests
# QUALITY_FUZZ_TIME  how long to fuzz each Fuzz target (a go test -fuzztime), optional
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GOLANGCI_LINT_VERSION="v2.15.0"
GREMLINS_VERSION="v0.6.0"
BASELINE="${QUALITY_BASELINE:-.github/quality-baseline.json}"
OUT="${QUALITY_OUT:-.quality}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/admiral-go-quality/$(go env GOVERSION)"

tool() {
    mkdir -p "$CACHE/bin"
    local lint="$CACHE/bin/golangci-lint-${GOLANGCI_LINT_VERSION}"
    if [ ! -x "$lint" ]; then
        echo "Installing golangci-lint ${GOLANGCI_LINT_VERSION}..." >&2
        GOBIN="$CACHE/tmp" go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}"
        mv "$CACHE/tmp/golangci-lint" "$lint"
    fi
    go build -C "$HERE/gometrics" -o "$CACHE/bin/gometrics" .
}

mutate() {
    local gremlins="$CACHE/bin/gremlins-${GREMLINS_VERSION}"
    if [ ! -x "$gremlins" ]; then
        echo "Installing gremlins ${GREMLINS_VERSION}..." >&2
        GOBIN="$CACHE/tmp" go install "github.com/go-gremlins/gremlins/cmd/gremlins@${GREMLINS_VERSION}"
        mv "$CACHE/tmp/gremlins" "$gremlins"
    fi
    local excludes=() f
    while IFS= read -r f; do
        excludes+=(-E "^$(printf '%s' "${f#./}" | sed 's/[.[\*^$()+?{|]/\\&/g')\$")
    done < <(grep -rlE --include='*.go' '^// Code generated .* DO NOT EDIT\.$' . || true)
    # The default coefficient times out every mutant in a small package, whose coverage run
    # is shorter than building it once mutated.
    "$gremlins" unleash --timeout-coefficient 30 ${excludes[@]+"${excludes[@]}"} \
        --output "$OUT/mutation.json" . > "$OUT/mutation.log" 2>&1 \
        || { tail -40 "$OUT/mutation.log" >&2; return 1; }
}

fuzz() {
    mkdir -p "$OUT/fuzz"
    : > "$OUT/fuzz.tsv"
    go test -run '^$' -list '^Fuzz' ./... | awk '
        /^Fuzz/ { names[n++] = $1; next }
        /^ok/ { for (i = 0; i < n; i++) print $2 "\t" names[i]; n = 0 }
    ' | while IFS=$'\t' read -r pkg name; do
        local dir log status=ok
        dir=$(go list -f '{{.Dir}}' "$pkg")
        dir=${dir#"$PWD/"}
        log="$OUT/fuzz/$(echo "$dir" | tr / _).$name.log"
        echo "Fuzzing $dir $name for $QUALITY_FUZZ_TIME..." >&2
        go test -run '^$' -fuzz "^${name}\$" -fuzztime "$QUALITY_FUZZ_TIME" "$pkg" > "$log" 2>&1 || status=crash
        printf '%s\t%s\t%s\n' "$dir" "$name" "$status" >> "$OUT/fuzz.tsv"
    done
}

measure() {
    mkdir -p "$OUT"
    tool
    "$CACHE/bin/golangci-lint-${GOLANGCI_LINT_VERSION}" run --config "$HERE/golangci.yml" \
        --issues-exit-code 0 --show-stats=false --timeout 10m \
        --output.json.path "$OUT/golangci.json" --output.text.path stderr ./... 2> "$OUT/golangci.log" \
        || { cat "$OUT/golangci.log" >&2; return 1; }
    "$CACHE/bin/gometrics" > "$OUT/metrics.json"
    if [ -n "${QUALITY_COVERAGE:-}" ] && [ -f "$QUALITY_COVERAGE" ]; then
        go tool cover -func="$QUALITY_COVERAGE" > "$OUT/coverage.txt"
    fi
    if [ "${QUALITY_MUTATION:-}" = "true" ]; then
        mutate
    fi
    if [ -n "${QUALITY_FUZZ_TIME:-}" ]; then
        fuzz
    fi
}

check() {
    local base_args=()
    if [ -n "${QUALITY_BASE_REF:-}" ]; then
        local base_file
        base_file=$(mktemp)
        if git show "${QUALITY_BASE_REF}:${BASELINE}" > "$base_file" 2>/dev/null; then
            base_args=(--base "$base_file")
            local renames_file
            renames_file=$(mktemp)
            git diff --name-status -M "$QUALITY_BASE_REF" | awk -F '\t' '$1 ~ /^R/ {print $2 "\t" $3}' > "$renames_file"
            base_args+=(--renames "$renames_file")
        fi
    fi
    python3 "$HERE/report.py" --out "$OUT" --check "$BASELINE" ${base_args[@]+"${base_args[@]}"}
}

case "${1:-all}" in
    measure) measure ;;
    check) check ;;
    baseline)
        measure
        mkdir -p "$(dirname "$BASELINE")"
        python3 "$HERE/report.py" --out "$OUT" --write-baseline "$BASELINE" > /dev/null
        echo "Updated $BASELINE. Commit it; CI refuses it growing."
        ;;
    report)
        measure
        python3 "$HERE/report.py" --out "$OUT"
        ;;
    all)
        measure
        check
        ;;
    *)
        echo "usage: $0 [measure|check|baseline|report]" >&2
        exit 2
        ;;
esac
