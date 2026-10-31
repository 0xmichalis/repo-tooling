# Repository tooling

Reusable GitHub workflows and composite actions for personal projects.
Callers own their triggers, schedules, runtime versions, permissions and
project-specific checks. Shared implementations own their tool versions.

## Components

| Component | Contract |
| --- | --- |
| `.github/workflows/rust-ci.yml` | Format, cargo-sort, clippy, check, tests and cargo-deny for a standard Rust crate/workspace. |
| `.github/workflows/rust-audit.yml` | Audit the caller's default branch and maintain one rolling vulnerability issue. |
| `.github/workflows/node-ci.yml` | Locked pnpm install, `format:check`, `lint`, `type-check` and `build`. |
| `actions/setup-node` | Set up a caller-selected Node version and locked npm or pnpm dependencies inside a custom job. |
| `actions/rust-audit` | Run cargo-audit and report its findings for an already checked-out working directory. |

All workflows accept `working-directory`, defaulting to `.`. Node CI requires
`node-version`. The Node setup action reads the pnpm version from the caller's
`packageManager` field; it accepts `package-manager: npm`,
`install-dependencies: "false"` and `ignore-scripts: "true"` where needed.

Rust CI uses the caller's Rust toolchain configuration when present, otherwise
the runner's active toolchain. Specialized database, coverage, code generation,
browser and release checks belong in caller workflows.

## Adoption

Copy the appropriate wrapper from `examples/` and replace its reference with a
full commit SHA from a tested release. Keep the release tag in an adjacent
comment. Enable the `github-actions` ecosystem in the caller's own
`.github/dependabot.yml` to receive updates through pull requests.

Read-only CI needs `contents: read`. Scheduled audits additionally need
`issues: write`; the implicit caller `GITHUB_TOKEN` is sufficient. Configure
the cron schedule in the caller. Workflow calls do not need inherited secrets.

Public and private repositories can call this public repository. Keep private
configuration and credentials in the caller. Check any required status-check
names when replacing jobs with reusable workflow calls.

## Scheduled Rust audits

The reusable audit workflow always checks out the caller's default branch,
including when dispatched from a feature branch. It queues concurrent runs so
they do not race over the rolling issue. Findings fail the run and create or
update `cargo audit: vulnerable dependencies`; a clean audit closes that issue.
Malformed reports, command failures and GitHub API failures fail the run and
never report an audit as clean.

Cargo reads `.cargo/audit.toml` directly. If a caller already keeps advisory
exceptions in cargo-deny's configuration, pass `deny-config: deny.toml` instead
of copying its ignores into a second file. Bare advisory IDs and `{id, reason}`
tables are supported. Issue bodies are bounded below GitHub's size limit, and
the workflow log retains the full JSON audit report.

## Development and releases

Use Python 3.11 or newer, Go and ShellCheck. Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

```sh
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 -color
```

CI exercises both shared CI workflows with fixtures, Node 22 and 26, npm with
lifecycle scripts disabled, rejected stale pnpm lockfiles and a real
cargo-audit report. Unit tests cover advisory exceptions, issue pagination,
create/update/close behavior, oversized reports and operational failures.

Reusable workflows pin this repository's composite actions as dependencies,
just like third-party actions. When editing an action, commit it first, update
the workflow references to that commit, and run CI against the resulting head.
This keeps every workflow revision independent of moving branches or tags.

Publish a version tag only after checks and representative caller runs pass.
Tags identify releases; consumers pin their commit SHAs. Breaking changes to
inputs, permissions or expected scripts require a new major release.

Licensed under [MIT](LICENSE).
