# Admiral Release Runbook

This document defines how releases flow across the Admiral org. It exists so
any maintainer (or LLM agent) can pick a use case, follow the steps, and ship
without having to reason from first principles about what cascades to what.

## Repos in scope

| Repo | Role |
|---|---|
| [`admiral-protos`](https://github.com/admiral-io/admiral-protos) | Proto contracts + generator. Source of truth for the schema. |
| [`admiral-sdk-go`](https://github.com/admiral-io/admiral-sdk-go) | Generated Go client. Consumed by every Go service. |
| [`admiral-openapi`](https://github.com/admiral-io/admiral-openapi) | Generated OpenAPI spec. Consumed by `admiral-site` and external integrations. |
| [`admiral`](https://github.com/admiral-io/admiral) | Server. Implements the proto contract; talked to by every client. |
| [`admiral-cli`](https://github.com/admiral-io/admiral-cli) | CLI client. Releases fan out to homebrew + scoop. |
| [`admiral-k8s-agent`](https://github.com/admiral-io/admiral-k8s-agent) | Kubernetes cluster connector. |
| [`admiral-infra-agent`](https://github.com/admiral-io/admiral-infra-agent) | Infrastructure provider connector. |
| [`terraform-provider-admiral`](https://github.com/admiral-io/terraform-provider-admiral) | Terraform provider. |
| [`admiral-helm`](https://github.com/admiral-io/admiral-helm) | Official Helm charts. The user-facing release artifact for self-hosted users. |
| [`admiral-site`](https://github.com/admiral-io/admiral-site) | Marketing/docs site. Consumes OpenAPI spec. |
| [`homebrew-tap`](https://github.com/admiral-io/homebrew-tap) | Homebrew distribution. Updated by `admiral-cli` releases. |
| [`scoop-bucket`](https://github.com/admiral-io/scoop-bucket) | Scoop distribution. Updated by `admiral-cli` releases. |

## Conceptual model: three cascades

Releases flow through three independent cascades. A given change touches one
or more.

| Cascade | Direction | Compat surface |
|---|---|---|
| **A. Compile-time** | `admiral-protos` → SDKs → consumers | Type/symbol availability at build time |
| **B. Runtime** | `admiral` → CLI / agents / terraform | gRPC wire compat + advertised capabilities |
| **C. Deployment** | `admiral`, agents → `admiral-helm` | Image tag pinning in Chart values |

**Key property: cascades are independent.** A protos tag does not force a
server release. A server release does not force a helm chart bump. Each step
is human-gated unless explicitly automated.

## Versioning conventions

### Two distinct version namespaces

Admiral has **two separate version concepts**, and conflating them is the most
common source of confusion:

| Namespace | Lives on | Bumps when | Used for |
|---|---|---|---|
| **Schema version** | `admiral-protos` git tag | The proto contract changes (additive or breaking) | Capabilities/skew enforcement; "what proto contract does this binary speak" |
| **SDK package version** | Each SDK repo's git tag (auto-cut by `go-semantic-release`) | That SDK's content actually changes (incl. template-only) | `go get` / module resolution / language-package distribution |

These evolve at different rates and **may diverge over time**. Examples:

- Schema `v1.24.0` (added a new field) → admiral-sdk-go content changes →
  go-semantic-release tags admiral-sdk-go `v1.24.0` (matches by coincidence,
  not by contract).
- Go template-only typo fix → no schema bump → admiral-sdk-go content changes
  → admiral-sdk-go bumps to e.g. `v1.24.1`. Schema stays at `v1.24.0`.
- Doc-only proto change → schema may stay (no code-relevant change) →
  admiral-sdk-go has no Go diff → no SDK tag. admiral-openapi *does* see a
  description change → tags `v1.24.1` independently.

The schema version is **stickier** than any SDK version. It only moves when
the proto contract moves.

### Tag-as-release model on admiral-protos

`admiral-protos` follows a **rolling-RC + manual-tag-as-release** model:

- **Master is the rolling release candidate.** Every merge advances the
  schema state. Optionally, the merge gets an `-rc.N` tag for reference.
- **A tag (e.g., `v1.24.0`) on protos is the release event.** This is the
  trigger that propagates the new schema to SDK repos. The user controls
  when this happens.
- **The bump type is encoded in the tag itself.** Tagging `v1.23.0 → v1.24.0`
  implies a minor (additive). `v1.23.0 → v2.0.0` implies a major (breaking).
  CI validates this matches what `buf breaking` thinks.

When a tag is pushed, CI runs the generator with `--schema-version=<tag>`,
embedding that string into a `const SchemaVersion` in each generated SDK.
The SDK content is then pushed with a synthesized conventional commit, and
each SDK's `go-semantic-release` workflow auto-tags its package version
independently.

### Rolling RC via the `next` branch

`admiral-protos` master is the rolling release candidate. Every commit to
master is regenerated and pushed to the **`next` branch** on each SDK repo
(`admiral-sdk-go`, `admiral-openapi`). Each SDK's `go-semantic-release`
workflow on `next` cuts pre-release tags (`vX.Y.Z-rc.N`).

External testers can track the rolling RC with:

```
go get github.com/admiral-io/admiral-sdk-go@v1.24.0-rc.5
go get github.com/admiral-io/admiral-sdk-go@next         # floating
```

These tags do not resolve under `@latest` — they're explicit opt-in.

For local iteration without involving CI at all, use the workspace flow:

1. Edit protos locally
2. `protorepo generate --output-root=..` regenerates sibling clones
3. `go.work` routes consumers to the regenerated SDKs
4. Iterate without commits or tags

### Skew policy

See [`admiral-protos/docs/features/SERVER-CAPABILITIES.md`](https://github.com/admiral-io/admiral-protos/blob/main/docs/features/SERVER-CAPABILITIES.md).
Summary: the server supports clients within N-2 minor versions. The
`SystemService.GetServerInfo` RPC is how clients discover and enforce skew.

The skew window is on the **schema version** (the `SchemaVersion` const
embedded into each SDK at generate time), not the SDK package version.

Until the Capabilities endpoint is implemented, skew is **observational only** —
clients log warnings but do not refuse to connect.

## Use case index

| # | Use case | Cascades | RC? |
|---|---|---|---|
| [1](#uc1-proto-doc-only-change) | Proto doc-only change | A | no |
| [2](#uc2-proto-additive-change) | Proto additive change | A | sometimes |
| [3](#uc3-proto-breaking-change) | Proto breaking change | A | yes |
| [4](#uc4-generator--buf-config-change) | Generator / buf-config change | A | no |
| [5](#uc5-single-language-template-fix) | Single-language template fix | A | no |
| [6](#uc6-coordinated-platform-pre-release) | Coordinated platform pre-release | A+B+C | yes (by definition) |
| [7](#uc7-pre-release-promotion) | Pre-release → final promotion | A+B+C | n/a |
| [8](#uc8-server-only-change) | Server-only behavioral change | B+C | no |
| [9](#uc9-server-adopts-new-sdk-version) | Server adopts new SDK version | B+C | sometimes |
| [10](#uc10-cli-release) | CLI release | — | no |
| [11](#uc11-agent-release) | Agent release (k8s or infra) | B+C | no |
| [12](#uc12-terraform-provider-release) | Terraform provider release | — | no |
| [13](#uc13-helm-image-bump) | Helm bumps container image references | C | no |
| [14](#uc14-helm-chart-only-change) | Helm chart-only change | C | no |
| [15](#uc15-site-update) | Site update | — | no |
| [16](#uc16-emergency-hotfix) | Emergency hotfix on a release line | varies | no |

---

## Use case playbooks

### UC1 — Proto doc-only change

**Trigger.** Editing comments / descriptions in a `.proto` file. No schema
impact.

**Cascades.** A only.

**Behavior.**

- Optional: tag `admiral-protos` with a patch bump (e.g., `v1.23.4` →
  `v1.23.5`) if you want the description change reflected in a schema
  version. Often skippable.
- `admiral-sdk-go` regen produces byte-identical Go code → empty diff →
  no commit pushed → no SDK tag.
- `admiral-openapi` regen updates descriptions in the spec → diff exists →
  commit pushed → go-semantic-release auto-tags a patch bump.

**Steps.**

1. PR in `admiral-protos`, merge to master.
2. (Optional) Tag `admiral-protos vX.Y.Z+1` if the change warrants a schema
   bump.
3. The tag (or workflow_dispatch) triggers the generator. Generator pushes
   regen commits to `admiral-sdk-go` and `admiral-openapi` mains. Empty
   diffs are skipped (`github.go:261-264`).
4. `admiral-openapi` go-semantic-release auto-tags. `admiral-sdk-go` does
   not (no content change).
5. `admiral-site` Renovate picks up the new openapi tag on its own time.

**Recovery.** If a tag is wrong, retag and re-trigger. Generated SDKs follow.

---

### UC2 — Proto additive change

**Trigger.** Adding a new field, message, RPC, or service. Forward-compatible
at the wire level.

**Cascades.** A.

**Behavior.**

- Edit, merge to master. `next.yml` runs automatically:
  - Generator regenerates SDK content
  - Pushes to `next` branch on `admiral-sdk-go` + `admiral-openapi`
  - SDK repos cut pre-release tags (`vX.Y.Z-rc.N`)
- External testers can pull `@vX.Y.Z-rc.N` or `@next`.
- For deeper local testing, use the workspace flow.
- When ready to release: tag `admiral-protos v1.24.0`. `release.yml` runs:
  - Validates tag bump matches `buf breaking`
  - Generator pushes sync commits to SDK master branches with `feat:` prefix
  - SDK repos cut release tags (`v1.24.0`)
- Renovate opens "bump SDK" PRs across consumer repos.
- Server (`admiral`) is a consumer like any other — adopting the new field
  is a deliberate code change in admiral, not automatic. See
  [UC9](#uc9-server-adopts-new-sdk-version).

**Steps.**

1. PR in `admiral-protos`, merge to master. `buf breaking` must pass on PR.
2. `next.yml` runs automatically; SDK pre-release tags appear within minutes.
3. (Optional) verify locally via workspace:
   ```
   cd admiral-protos
   protorepo generate --output-root=..
   cd ../admiral && go test ./...
   ```
4. Tag `admiral-protos v1.24.0` and push. `release.yml` runs.
5. Generator embeds `SchemaVersion = "v1.24.0"` into SDKs.
6. SDKs auto-tag stable via go-semantic-release on master.
7. Renovate cascades to consumers.

**Recovery.** If the addition is wrong (field name, type), the next change is
itself a breaking change ([UC3](#uc3-proto-breaking-change)) — don't try to
"fix" the field shape in a patch.

---

### UC3 — Proto breaking change

**Trigger.** Renaming a field, removing a field, changing a type, changing
RPC signatures, or anything `buf breaking` flags.

**Cascades.** A primarily; will eventually trigger B and C as the server
adopts.

**Behavior.**

- **Strongly preferred: package-version-bump pattern.** Add `admiral.foo.v2`
  alongside existing `admiral.foo.v1`. Server implements both for a
  deprecation window (recommended: ≥2 minor versions of overlap). This
  preserves wire compat for older clients indefinitely.
- If a hard cutover is unavoidable: bump `admiral-protos` to a new major
  (`v2.0.0`). All consumers must explicitly opt in via `go get` to a v2
  module path.
- **Validate locally first** via the workspace flow before tagging — breaking
  changes have higher cost if rolled back.

**Steps.**

1. PR in `admiral-protos` introducing v2 of the affected package (recommended)
   or a major bump (only if necessary).
2. `buf breaking` will flag the change; if package-version-bump pattern,
   wrap with appropriate config to scope the breaking-check to the new
   package only.
3. Merge to master.
4. **Validate locally.** Run the generator with `--output-root=..`,
   regenerate the sibling SDK clones, and exercise the change end-to-end via
   go.work-routed consumers.
5. Tag `admiral-protos v2.0.0` (or `v1.24.0` if package-version-bumping
   inside an existing major). Tag-triggered CI:
   - Validates the tag matches what `buf breaking` saw (fails if you tagged
     minor when there's a real break).
   - Generator embeds `SchemaVersion = "v2.0.0"` into SDKs.
   - Pushes sync commits with `feat!:` conventional message.
6. SDKs auto-tag at major.
7. Server bumps SDK + implements v2 endpoints alongside v1.
8. Helm chart bumps when ready.

**Deprecation window.** Document the v1 deprecation in admiral release notes
and announce. Do not remove the v1 implementation until at least 2 minor
versions later.

---

### UC4 — Generator / buf-config change

**Trigger.** Editing `tool/`, `buf.gen.yaml`, lint rules, or any other
generator-side concern.

**Cascades.** A indirectly (next regen may produce different output).

**Behavior.**

- `admiral-protos` itself: tag a patch on the protos repo if you want a
  human-facing marker, but **no SDK regen is forced** by a generator-only
  change. The next proto change picks up the new generator behavior.
- If the generator change *itself* materially changes SDK output (e.g.,
  switching protoc plugin versions), that's effectively a generator-driven
  schema change — treat it as [UC2](#uc2-proto-additive-change) or
  [UC3](#uc3-proto-breaking-change) depending on impact.

**Steps.**

1. PR in `admiral-protos` modifying generator code.
2. PR description must state whether SDK output is expected to change. If
   yes, include a generated-output diff in the PR.
3. Merge.
4. If output changed materially: continue as UC2/UC3 above.
5. If output is unchanged: nothing else to do — no tag required.

---

### UC5 — Single-language template fix

**Trigger.** Bug in `templates/<lang>/` for a single language. E.g., a typo
in `templates/go/client/client.go.tmpl`.

**Cascades.** A, but only the affected language.

**Behavior.**

- Generator should support `--lang <name>` filter so CI can regenerate only
  the affected SDK.
- Tag a patch on the affected SDK only (`admiral-sdk-go v1.23.5`).
- Other-language SDKs and `admiral-protos` itself **do not get bumped**.

**Steps.**

1. PR in `admiral-protos` modifying only `templates/<lang>/`.
2. Merge.
3. CI runs `protorepo generate --lang <lang>` and pushes regen commit to
   only that SDK.
4. Tag `admiral-sdk-<lang> v1.23.5` directly (no protos retag).
5. Renovate opens bump PR in consumers of that SDK.

> **Today's gap.** The generator currently regenerates all languages declared
> in `protorepo.yaml`. Adding `--lang` filter is tracked under the CI gaps
> work in `RELEASE.md` follow-ups.

---

### UC6 — Coordinated platform pre-release

**Trigger.** A change that crosses multiple repos and you want to validate
end-to-end before final cut. Examples: adopting a new auth mechanism,
introducing a new resource type that requires server + agent + CLI work.

**Cascades.** A, B, C all.

**Steps.**

1. Plan: identify which repos participate, what schema version label the
   cycle uses (`v1.24.0`).
2. Land protos changes in `admiral-protos`, merge.
3. Tag `admiral-protos v1.24.0-rc.1`. Cascade tags SDKs at
   `v1.24.0-rc.1`.
4. In `admiral`: bump SDK to `v1.24.0-rc.1`, implement new endpoints,
   merge to main, tag `admiral v1.24.0-rc.1`. Container pushed as
   `ghcr.io/admiral-io/admiral:v1.24.0-rc.1`.
5. In each affected agent: bump SDK to `v1.24.0-rc.1`, implement client
   side, tag `admiral-<agent> v1.24.0-rc.1`. Containers pushed.
6. In CLI / terraform-provider: bump SDK, implement, tag `v1.24.0-rc.1`.
7. In `admiral-helm`: pin all image tags to `v1.24.0-rc.1` in a values
   file (e.g., `values-rc.yaml`). Run integration tests.
8. Validate end-to-end against the rc image set.
9. If green: proceed to [UC7](#uc7-pre-release-promotion).
10. If broken: identify which repo needs the fix, land it, tag the
    affected repo's `v1.24.0-rc.2`. Other repos can stay at `-rc.1` if
    unaffected — only re-cut what changed.

**Coordination tip.** Track the cycle in a single GitHub issue (in
`admiral-protos` or `.github`) with checkboxes for each repo's rc tag.

---

### UC7 — Pre-release promotion

**Trigger.** A coordinated rc set has passed validation and is ready to ship.

**Cascades.** A+B+C, all promoting from `-rc.N` to non-rc.

**Behavior.** Promotion is a re-tagging exercise: each rc tag's commit gets a
new non-prerelease tag pointing to the same SHA. **No code changes happen
between rc and final.** If something needs to change, it's a new rc.

**Steps.**

1. Confirm validation is complete.
2. In `admiral-protos`: tag `v1.24.0` on the same commit as `v1.24.0-rc.N`.
3. CI cascades: SDKs get `v1.24.0` tags on the same commits as their rc
   tags.
4. In each consumer (admiral, agents, cli, terraform-provider): tag
   `v1.24.0` on the rc commit. Containers re-pushed with non-rc tags
   (and `latest`).
5. In `admiral-helm`: bump container image tag references in `values.yaml`
   from `v1.24.0-rc.N` to `v1.24.0`, bump chart version, tag chart
   release.

**Recovery.** Promotion shouldn't fail — there are no new code changes. If
something is wrong post-promotion, treat as [UC16](#uc16-emergency-hotfix).

---

### UC8 — Server-only change

**Trigger.** Bug fix or behavior change in `admiral` that doesn't touch the
proto contract or SDK version.

**Cascades.** B (server is updated; clients see new behavior on existing
endpoints), C (new image tag flows to helm).

**Behavior.**

- Tag `admiral` directly with a patch or minor bump.
- No SDK changes.
- Helm gets a Renovate PR to bump image reference.

**Steps.**

1. PR in `admiral`, merge.
2. CI on tag push runs GoReleaser and publishes container image.
3. Tag `admiral v1.23.5`.
4. Renovate opens PR in `admiral-helm` to bump
   `image.tag` for admiral.
5. Helm maintainer merges → bumps chart version → tags chart.

---

### UC9 — Server adopts new SDK version

**Trigger.** Bumping `go.admiral.io/sdk` in `admiral`'s go.mod to a newer
version (e.g., to expose a new field in an endpoint).

**Cascades.** B, C.

**Behavior.**

- The SDK version bump is just a normal dependency update PR.
- Server tagging that *exposes* new schema features is the user-facing event;
  document the new feature in the admiral release notes.
- **RC required** if exposing the feature is part of a coordinated platform
  release (then it's [UC6](#uc6-coordinated-platform-pre-release)). Otherwise
  no rc.

**Steps.**

1. Renovate (or manual) PR in `admiral` bumping
   `go.admiral.io/sdk` to vX.Y.Z.
2. Implement code that uses new SDK features.
3. Merge.
4. Tag `admiral v1.A.B+1`.
5. Helm Renovate PR follows. Same as [UC8](#uc8-server-only-change) from
   step 4 onward.

---

### UC10 — CLI release

**Trigger.** Tagging `admiral-cli`. May or may not include an SDK version
bump; from the runbook's perspective, mechanically the same.

**Cascades.** None (CLI is a leaf in cascades A/B/C).

**Behavior.**

- GoReleaser runs on tag, publishes Linux/macOS/Windows binaries to GitHub
  Releases.
- GoReleaser updates `homebrew-tap` and `scoop-bucket` automatically.
- Container image (if applicable) pushed.

**Steps.**

1. PR in `admiral-cli`, merge.
2. Tag `admiral-cli v1.23.5`.
3. CI does the rest. No manual fan-out.

**Recovery.** If a release is bad: `gh release delete vX.Y.Z`, retag, re-run
release workflow. Tap and bucket entries get rewritten on the retag.

---

### UC11 — Agent release (k8s or infra)

**Trigger.** Tagging `admiral-k8s-agent` or `admiral-infra-agent`.

**Cascades.** B (clients-of-server, but agent is itself a client; this
mostly means new agent talks to existing server), C (image flows to helm).

Mechanically identical to [UC8](#uc8-server-only-change) — the agent is just
another consumer of the server's gRPC contract. Treat the runbook for both
the same way.

---

### UC12 — Terraform provider release

**Trigger.** Tagging `terraform-provider-admiral`.

**Cascades.** None for the rest of the org. Terraform Registry handles
distribution.

**Behavior.**

- GoReleaser publishes signed binaries.
- GitHub release triggers Terraform Registry to ingest.

**Steps.**

1. PR, merge.
2. Tag `terraform-provider-admiral v1.23.5`.
3. CI runs GoReleaser with provider-specific config (signing required).
4. Verify ingestion at registry.terraform.io.

---

### UC13 — Helm image bump

**Trigger.** Renovate PR in `admiral-helm` that updates one or more container
image tags in `values.yaml` because admiral / k8s-agent / infra-agent shipped
a new release.

**Cascades.** C only.

**Behavior.**

- Renovate opens the PR automatically (configured to watch container
  registries).
- Reviewer decides whether to merge now or wait for additional bumps to
  bundle into a single chart release.
- Merging triggers a chart version bump (patch by default) and a chart
  release.

**Steps.**

1. Renovate PR appears.
2. Maintainer reviews; may hold for additional image bumps to land first.
3. Merge.
4. Tag `admiral-helm v1.23.X+1` for the chart.
5. CI publishes chart to OCI registry / GitHub Pages helm repo.

**Bundling guidance.** Bundle multiple image bumps into one chart release if
they're part of the same platform cycle. Cut individual chart releases for
isolated patches.

---

### UC14 — Helm chart-only change

**Trigger.** Editing chart templates, default values, or chart metadata
without changing image references.

**Cascades.** C only.

**Behavior.** Same shape as UC13 but the trigger is a hand-written PR, not a
Renovate bump. Chart version increments per change.

---

### UC15 — Site update

**Trigger.** Editing `admiral-site` content. May or may not be in response to
an `admiral-openapi` update.

**Cascades.** None.

**Behavior.** Site has its own release cycle (likely auto-deploy on push to
main). Not coupled to other repos except via openapi consumption.

**Steps.**

1. PR in `admiral-site`, merge.
2. Auto-deploy.

---

### UC16 — Emergency hotfix

**Trigger.** Critical bug in a released version that needs immediate patch
without going through rc.

**Behavior.**

- Branch off the release tag (`release/v1.23` or similar maintenance branch).
- Land minimal fix.
- Tag a patch (`v1.23.4` → `v1.23.5`) on that branch.
- Cherry-pick the fix to main.
- If the fix has cascade impact, follow the corresponding UC for cascading
  the patch downstream — but accept the loss of rc safety.

**Branching.** Maintain a `release/vX.Y` branch on each repo where you need
to support old release lines. By default, run only main. Create the release
branch when the first hotfix is needed.

**Steps.**

1. Identify the affected repo(s) and the release tag to fix.
2. `git checkout -b release/vX.Y vX.Y.0` (if the branch doesn't exist).
3. Land the fix on the release branch.
4. Tag `vX.Y.Z+1` on the release branch.
5. Cherry-pick to main: `git cherry-pick <sha>`. Resolve conflicts.
6. If the fix caused downstream impact, follow the relevant UC.
7. Document the hotfix in release notes with the rationale for skipping rc.

---

## CI workflow expectations

This section describes what CI must do to support each use case. Where the
current state diverges, it's noted. Migration to centralized reusable
workflows in `.github` is a separate effort.

### admiral-protos

Three workflows, each with one job:

| Workflow | Trigger | What it does |
|---|---|---|
| `validate.yml` | PR / push to non-master | `buf lint`, `buf breaking` against master, generator unit tests |
| `next.yml` | Push to master | Generator runs, pushes sync commit to **`next` branch** on each SDK repo. Conventional commit prefix derived from `buf breaking` against `HEAD~1` (`feat:` for clean, `feat!:` for breaking). |
| `release.yml` | Tag `v*.*.*` push **or** `workflow_dispatch` | Tag-triggered: validates tag matches `buf breaking` (lenient by default — see strict mode below), runs generator with `--schema-version=<tag>`, pushes sync commits to **SDK master branches**. Manual: same flow but skips bump validation, takes `release_type` and optional `schema_version` inputs as escape hatch. |

**Note.** No tags on `admiral-protos` until you want to release. Master is
the rolling RC; tag = release.

### admiral-sdk-go and admiral-openapi

Each has one workflow:

| Workflow | Trigger | What it does |
|---|---|---|
| `release.yml` | Push to `master` or `next` | go-semantic-release reads incoming conventional commit. On `master`: cuts a stable tag (`vX.Y.Z`). On `next`: cuts a pre-release tag (`vX.Y.Z-rc.N`). The branch determines whether `prerelease: true` is set on the action. |

**Strict bump validation** is controlled by the repo variable
`RELEASE_STRICT_BREAKING`:

- **Unset / `false` (default — lenient mode)**: `buf breaking` mismatches on
  minor/patch tags emit a warning but the release proceeds. Appropriate during
  the early phase of schema design when the contract is in flux.
- **`true` (strict mode)**: `buf breaking` mismatch on minor/patch tags
  fails the release. Set this once the schema stabilizes and you're ready to
  enforce semver compatibility for downstream consumers.

Flip via `gh variable set RELEASE_STRICT_BREAKING --body true` (or repo
Settings → Secrets and variables → Actions → Variables).

### admiral-sdk-go / admiral-openapi

| Trigger | What CI does |
|---|---|
| Push to main | Test the generated output (compile in case of Go SDK) |
| Tag `v*` | Run release notes generation; create GitHub release |

These repos are downstream of admiral-protos and should not contain
hand-written code beyond what's in templates. Both are 100% generated.

### admiral / agents / cli / terraform-provider

| Trigger | What CI does |
|---|---|
| PR | Lint, test, build (per repo's Makefile) |
| Tag `v*` | GoReleaser: build binaries, build container, push to ghcr.io, create GitHub release |

CLI additionally fans out to homebrew-tap and scoop-bucket via GoReleaser
config. Terraform-provider additionally signs binaries for Registry ingest.

### admiral-helm

| Trigger | What CI does |
|---|---|
| PR | `helm lint`, schema validation |
| Tag `v*` | Package chart, push to OCI registry / helm repo |

Renovate is configured (or should be) to watch ghcr.io image tags for
admiral, k8s-agent, infra-agent and open PRs to bump references in
values.yaml.

---

## Quick reference: which repo to tag for which change?

| You changed... | Tag this | Then... |
|---|---|---|
| Proto comments only | optional `admiral-protos` patch | merge to master → next.yml pushes to SDK next (rc tag if openapi diff); release.yml on tag pushes to SDK master |
| Proto field/method (additive) | `admiral-protos` minor | merge → SDK rc tag on next; tag → SDK release tag on master; Renovate to consumers |
| Proto schema (breaking) | `admiral-protos` major (or v2 package + minor) | merge → SDK rc tag on next (`feat!:`); tag → SDK release tag; consumers opt in |
| Generator code | nothing | next proto tag picks up new generator behavior |
| Go template only | trigger generator manually OR commit to protos master + manual workflow_dispatch | only `admiral-sdk-go` content changes; only it auto-tags |
| OpenAPI template only | same | only `admiral-openapi` auto-tags |
| Server logic | `admiral` patch/minor | Renovate cascades to helm |
| Server adopts new SDK | `admiral` minor | Renovate cascades to helm |
| Agent logic | `admiral-<agent>` patch/minor | Renovate cascades to helm |
| CLI logic | `admiral-cli` patch/minor | GoReleaser fans to homebrew/scoop |
| Terraform provider | `terraform-provider-admiral` patch/minor | Registry ingests automatically |
| Helm chart logic | `admiral-helm` patch/minor | end of line — users see this |
| Helm image bump (Renovate PR) | `admiral-helm` patch | end of line — users see this |
| Site content | `admiral-site` (auto-deploy) | nothing else |
| Critical fix on old release | branch + patch tag | UC16 |

---

## Glossary

- **Cascade**: a chain of dependent releases triggered by a single change.
  This doc identifies three: compile-time (A), runtime (B), deployment (C).
- **Schema version**: the version of the proto contract, surfaced via the
  Capabilities endpoint as `Schema.version`. Embedded into each generated
  SDK as `const SchemaVersion` at generate time, derived from `git describe`
  on `admiral-protos`. Distinct from the SDK package version — only moves
  when the contract moves.
- **SDK package version**: each SDK's own semver tag (e.g., `admiral-sdk-go
  v1.24.1`). Auto-cut by `go-semantic-release` when the SDK's content
  actually changes. Used for `go get`. Drifts from schema version over
  time.
- **Skew window**: the range of client schema versions a given server
  supports. Currently N-2 minor (see [`SERVER-CAPABILITIES.md`](https://github.com/admiral-io/admiral-protos/blob/main/docs/features/SERVER-CAPABILITIES.md)).
- **Pre-release**: a tag with `-rc.N` suffix that participates in the
  cascade but is not picked up by `@latest` resolvers.
- **Promotion**: re-tagging a `-rc.N` commit with the non-prerelease tag,
  finalizing the release without code changes.
