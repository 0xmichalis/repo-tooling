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
| `actions/publish-image` | Push a built image, sign and verify its digest, then promote the current default branch head to `latest`. |
| `actions/cargo-tag` | Tag a root Cargo version bump and dispatch `release.yml`, with retryable dispatch failures. |
| `actions/package-rust-binary` | Archive a built target binary, README and license with a SHA-256 checksum on Linux or macOS. |

All workflows accept `working-directory`, defaulting to `.`. Node CI requires
`node-version`. The Node setup action reads the pnpm version from the caller's
`packageManager` field; it accepts `package-manager: npm`,
`install-dependencies: "false"` and `ignore-scripts: "true"` where needed.
Custom Node jobs may pass `node-version-file` instead of `node-version` to
preserve an existing `.nvmrc` as the runtime source of truth.

Rust CI uses the caller's Rust toolchain configuration when present, otherwise
the runner's active toolchain. It requires a committed `Cargo.lock` and a
caller-owned `deny.toml` with an explicit license allowlist; see
[`examples/deny.toml`](examples/deny.toml). Cargo-deny is installed with its
required Rust 1.88 toolchain without changing the project's selected compiler.
Specialized database, coverage, code generation,
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
Nested working directories include their lockfile path in the issue title, so
one directory's clean result cannot close another directory's findings. Set
`report-issues: "false"` on the composite action for read-only CI audits.
Malformed reports, command failures and GitHub API failures fail the run and
never report an audit as clean.

Cargo reads `.cargo/audit.toml` directly. If a caller already keeps advisory
exceptions in cargo-deny's configuration, pass `deny-config: deny.toml` instead
of copying its ignores into a second file. Bare advisory IDs and `{id, reason}`
tables are supported. Issue bodies are bounded below GitHub's size limit, and
the workflow log retains the full JSON audit report.

## Development and releases

Container callers retain their build, vulnerability scan, registry login,
triggers and publication concurrency. Pass the built `image` tag, existing
`signing-key` and `signing-password` secrets, and caller `token` to
`actions/publish-image`. It keeps cosign v2.6.5 signatures compatible with
existing key-based verifiers. A failed push, signature, verification or branch
lookup cannot promote `latest`. Use `promote-latest: "false"` for release-only
tags; `require-current-head: "false"` supports an explicitly different caller
promotion policy.
Transparency-log signing and verification are required by default, and signing
is retried three times. `transparency-log: "false"` supports offline registries;
the ephemeral local-registry fixture uses that mode.

The Cargo tagging action requires full history, `before-sha` from the push
event, and a token with `contents: write` and `actions: write`. It reads the
root `package.version` or `workspace.package.version`, creates the tag on the
requested commit, and dispatches the caller's `release.yml` on its default
branch. It never moves existing tags. Rerunning a failed dispatch resumes the
same tag when it already points to that commit. Callers retain their existing
CI/release gates and artifact build matrices.

After building a binary, pass its `binary`, `tag` and `target` to
`actions/package-rust-binary`. It reads `target/<target>/release/<binary>`,
`README.md` and `LICENSE`, and creates
`<binary>-<tag>-<target>.tar.gz` plus `.tar.gz.sha256`. Upload and release
publication stay in the caller.

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
An ephemeral registry test builds, signs, verifies and promotes an image with
a temporary test key. Publication unit tests cover stale commits and failed
signing/verification; tagging and archive tests cover recovery and artifact
integrity.

Reusable workflows pin this repository's composite actions as dependencies,
just like third-party actions. When editing an action, commit it first, update
the workflow references to that commit, and run CI against the resulting head.
This keeps every workflow revision independent of moving branches or tags.

Publish a version tag only after checks and representative caller runs pass.
Tags identify releases; consumers pin their commit SHAs. Breaking changes to
inputs, permissions or expected scripts require a new major release.

Licensed under [MIT](LICENSE).
