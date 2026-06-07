# Contributing

Thanks for helping improve Admiral. This guide covers every public
repository in the organization. A repository's own CONTRIBUTING.md adds how
to build and test that code.

## Where an issue goes

- **A bug in one repository's code**, such as a CLI command that crashes or
  a provider resource that plans wrong: open it in that repository.
- **Anything else**, including the web console, the API's behavior, the
  Kubernetes agent, the docs, or when you are not sure: open it in
  [admiral-community](https://github.com/admiral-io/admiral-community/issues/new/choose).
- **A question:** start a
  [discussion](https://github.com/admiral-io/admiral-community/discussions).
- **A security vulnerability:** email [security@admiral.io](mailto:security@admiral.io).
  See [SECURITY.md](SECURITY.md). Never a public issue.

An issue in the wrong place is fine. We move it.

## Filing an issue

Search existing issues first. If one matches, add a thumbs-up or a comment
with what is different about your case.

Fill in the issue form as far as you can. Versions, the exact command or
configuration, and the error output save a round of questions. Remove API
keys, tokens and anything else secret before you paste logs.

## Opening a pull request

Open an issue before you start a feature or a larger change, so the design
is agreed before you spend time on it. A typo, a broken link or a small
fix does not need one.

Keep a pull request to one change. Say what it changes and why, and link
the issue it resolves. Run the repository's tests and linters before you
push; CI runs the same checks.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/),
for example `fix(auth): refresh an expired session before retrying`.

Keep editor and machine files, such as `.idea/` and `.vscode/`, out of the
repository with a
[global .gitignore](https://docs.github.com/en/get-started/getting-started-with-git/ignoring-files#configuring-ignored-files-for-all-repositories-on-your-computer).

## License

Every public Admiral repository is licensed under Apache-2.0. By
contributing, you agree that your contribution is licensed under the same
terms.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
Report a concern to [hello@admiral.io](mailto:hello@admiral.io).

## Contact

For anything that does not fit an issue, email
[support@admiral.io](mailto:support@admiral.io).
