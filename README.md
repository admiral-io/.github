# .github

> Admiral's template for open source community resources

This repo contains shared community resources that will propagate to all public
repositories in the Admiral organization that don't already have their own
resource that fills this purpose.

## What's included

- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): community behavior expectations, based on Contributor Covenant 3.0
- [CONTRIBUTING.md](CONTRIBUTING.md): how to file issues and open pull requests
- [SECURITY.md](SECURITY.md): how to report security vulnerabilities
- [default.json](default.json): Renovate preset (see below)

The cross-org release runbook lives in
[admiral-protos/RELEASE.md](https://github.com/admiral-io/admiral-protos/blob/master/RELEASE.md)
— next to the release engine it documents.

## Overriding for a specific repo

GitHub automatically surfaces these files in any Admiral repository that
doesn't define its own copy. To override for a specific repo, add the file
to that repo's root or `.github/` directory.

## Renovate preset

`default.json` is the org-wide [Renovate](https://docs.renovatebot.com/)
configuration preset. Once the Renovate GitHub App is installed on the
admiral-io organization, each repo can extend it via a minimal
`renovate.json` at the repo root:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["local>admiral-io/.github"]
}
```

Renovate's onboarding PRs reference this preset automatically, so most
repos only need to merge the onboarding PR.

To override behavior for a specific repo (e.g., disable a packageRule
or change schedule), add the override after the `extends` entry.
