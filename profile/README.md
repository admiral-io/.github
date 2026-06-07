![Admiral](https://raw.githubusercontent.com/admiral-io/.github/master/profile/admiral-logo.svg)

[Admiral](https://admiral.io/?utm_source=github&utm_medium=referral&utm_campaign=org_profile)
is a control plane for coordinating infrastructure and application delivery
across environments.

Your infrastructure as code provisions the infrastructure and your manifests
deploy the applications, and the wiring between the two is usually done by
hand. Admiral holds the dependency graph across both. An output flows to the
input that needs it, each component's change is planned and reviewed before
it applies, and an environment is promoted rather than rebuilt.

Admiral orchestrates Terraform or OpenTofu, Helm and Kubernetes manifests
without replacing them. The control plane is hosted. What runs in your
accounts and clusters is a self-hosted agent that connects out to Admiral, so
there is no inbound networking to set up.

Admiral is in active development. See the
[documentation](https://admiral.io/docs?utm_source=github&utm_medium=referral&utm_campaign=org_profile)
for where it stands.

### Open-source tools

| Repository | What it is |
| --- | --- |
| [admiral-cli](https://github.com/admiral-io/admiral-cli) | The `admiral` command-line interface |
| [terraform-provider-admiral](https://github.com/admiral-io/terraform-provider-admiral) | Manage Admiral resources with Terraform |
| [admiral-helm](https://github.com/admiral-io/admiral-helm) | Helm charts, including the Kubernetes agent |
| [admiral-sdk-go](https://github.com/admiral-io/admiral-sdk-go) | Go client library for the Admiral API |
| [admiral-sdk-ts](https://github.com/admiral-io/admiral-sdk-ts) | TypeScript client library for the Admiral API |
| [admiral-openapi](https://github.com/admiral-io/admiral-openapi) | OpenAPI specifications for the Admiral API |
| [admiral-bundle](https://github.com/admiral-io/admiral-bundle) | The packaging format behind the component registry |

Install the CLI with `brew install admiral-io/tap/admiral` or from the
[Scoop bucket](https://github.com/admiral-io/scoop-bucket) on Windows.

Every public repository is licensed under Apache-2.0.

### Get help

- **Bugs, feature requests, questions:** [admiral-community](https://github.com/admiral-io/admiral-community)
- **Security vulnerabilities:** email [security@admiral.io](mailto:security@admiral.io), never a public issue
- **Contributing:** read the [contributing guide](https://github.com/admiral-io/.github/blob/master/CONTRIBUTING.md)

Follow along on [LinkedIn](https://www.linkedin.com/company/admiral-io).
