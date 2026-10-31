# Repository tooling

Reusable GitHub workflows and composite actions for personal projects.
Callers own their triggers, schedules, runtime versions, permissions and
project-specific checks. Shared implementations own their tool versions.

## Components

| Component | Contract |
| --- | --- |
| `.github/workflows/rust-ci.yml` | Format, cargo-sort, clippy, check, tests and cargo-deny for a standard Rust crate/workspace. |
| `.github/workflows/rust-binary-release.yml` | Build a caller-selected target matrix, package binaries and checksums, and publish a GitHub Release. |
| `.github/workflows/rust-audit.yml` | Audit the caller's default branch and maintain one rolling vulnerability issue. |
| `.github/workflows/node-ci.yml` | Locked pnpm install, formatting, lint, type checks, optional tests and build. |
| `.github/workflows/markdownlint.yml` | Markdown lint with caller-selected file globs and configuration. |
| `.github/workflows/dockerfile-lint.yml` | Hadolint checks for a caller-selected Dockerfile. |
| `actions/setup-node` | Set up a caller-selected Node version and locked npm or pnpm dependencies inside a custom job. |
| `actions/rust-audit` | Run cargo-audit and report its findings for an already checked-out working directory. |
| `actions/publish-image` | Optionally build an image and log in to GHCR, push it, sign and verify its digest, then promote the current default branch head to `latest`. |
| `actions/cargo-tag` | Tag a root Cargo version bump and dispatch `release.yml`, with retryable dispatch failures. |
| `actions/package-rust-binary` | Archive a built target binary, README and license with a SHA-256 checksum on Linux or macOS. |

Rust and Node workflows accept `working-directory`, defaulting to `.`. Node CI requires
`node-version`. The Node setup action reads the pnpm version from the caller's
`packageManager` field; it accepts `package-manager: npm`,
`install-dependencies: "false"` and `ignore-scripts: "true"` where needed.
Custom Node jobs may pass `node-version-file` instead of `node-version` to
preserve an existing `.nvmrc` as the runtime source of truth.

Node CI defaults to the `format:check`, `lint`, `type-check` and `build` package
scripts. Set `format-script` or `typecheck-script` to use the caller's existing
names, and `test-script` to run tests. Set `build-script: ""` when another
caller job owns the build, such as a browser test job. These inputs name package
scripts; they do not contain shell commands. For example:

```yaml
jobs:
  checks:
    uses: 0xmichalis/repo-tooling/.github/workflows/node-ci.yml@v1.1.0
    with:
      node-version: "22"
      format-script: format
      typecheck-script: typecheck
      test-script: test:ci
      build-script: ""
```

Markdown lint accepts newline-delimited `globs` and an optional `config` path.
It uses the caller's Markdown configuration and fails on lint errors; it does
not rewrite files. See [`examples/markdownlint.yml`](examples/markdownlint.yml).
Dockerfile lint accepts `dockerfile`, defaulting to `Dockerfile`, and uses the
caller's Hadolint configuration.

Rust CI uses the caller's Rust toolchain configuration when present, otherwise
the runner's active toolchain. It requires a committed `Cargo.lock`. Cargo-deny
is enabled by default and requires a caller-owned `deny.toml` with an explicit
license allowlist; see
[`examples/deny.toml`](examples/deny.toml). Cargo-deny is installed with its
required Rust 1.88 toolchain without changing the project's selected compiler.
Set `run-tests: false` when a caller job already runs coverage or specialized
tests. Format, Clippy, check and cargo-deny still run. Specialized database,
coverage, code generation and browser checks belong in caller workflows.
Callers without a cargo-deny policy can set `run-deny: false`.
Cargo-sort uses its upstream release binary with a pinned SHA-256 checksum.

## Adoption

Copy the appropriate wrapper from `examples/` and replace its reference with a
full commit SHA from a tested release. Keep the release tag in an adjacent
comment. Enable the `github-actions` ecosystem in the caller's own
`.github/dependabot.yml` to receive updates through pull requests. This
repository schedules those updates on Saturday.

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

Container callers retain their vulnerability scan, triggers and publication
concurrency. Pass the `image` tag, existing
`signing-key` and `signing-password` secrets, and caller `token` to
`actions/publish-image`. Set `build-context: .` to share GHCR login and the Docker
build with `--pull` and a `GIT_COMMIT` build argument from the checked-out commit.
GHCR login uses the caller token and actor; other registries require caller-owned
authentication. Omit `build-context` to publish an already built and authenticated
image. The action keeps cosign v2.6.5 signatures compatible with
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
CI/release gates and target selection.
Serialize tagging with `queue: max`, as in [`examples/cargo-tag.yml`](examples/cargo-tag.yml),
so a newer push cannot replace a pending version-bump run. The shared CI pins
actionlint v1.7.12, which does not yet recognize that GitHub concurrency key;
the example is validated by the consumer workflow runs.

For standard Rust binary releases, call `rust-binary-release.yml` with the
`binary` name and explicit `tag`. It defaults to a static x86_64 Linux build
with cross. The optional `targets` input is a JSON array of `target`, `os` and
`builder` (`cargo` or `cross`) objects; native and cross-compiled Mac targets
use cargo. See [`examples/rust-binary-release.yml`](examples/rust-binary-release.yml).
Keep tag-push and manual triggers in the caller and grant the calling job
`contents: write`; only the shared publication job receives that permission.
Build jobs use read-only tokens and always check out the release tag.
Version tags may include prerelease and build-metadata suffixes. Prereleases
are marked explicitly and cannot replace the latest stable release.
For build validation, `publish-release: false` checks out the caller commit,
uploads the same archives and skips release creation without requiring a tag.

Custom release pipelines can instead pass a built binary's `binary`, `tag` and
`target` to `actions/package-rust-binary`. It reads
`target/<target>/release/<binary>`,
`README.md` and `LICENSE`, and creates
`<binary>-<tag>-<target>.tar.gz` plus `.tar.gz.sha256`. Both the release workflow
and packaging action accept `working-directory` for nested Rust projects.
Custom callers retain upload and release publication.

Use Python 3.11 or newer, Go and ShellCheck. Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

```sh
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 -color
```

CI exercises shared CI workflows with fixtures, caller-owned Rust tests,
Node 22 and 26, custom package scripts and tests, a skipped build, Markdown and
Dockerfile lint, npm with
lifecycle scripts disabled, rejected stale pnpm lockfiles and a real
cargo-audit report. Unit tests cover advisory exceptions, issue pagination,
create/update/close behavior, oversized reports and operational failures.
An ephemeral registry test builds, signs, verifies and promotes an image with
a temporary test key. Publication unit tests cover stale commits and failed
signing/verification; tagging and archive tests cover recovery and artifact
integrity. A build-only release fixture checks Linux and both Mac architectures,
archive contents, executable permissions and checksums, and runs the Linux binary.

Reusable workflows pin this repository's composite actions as dependencies,
just like third-party actions. When editing an action, commit it first, update
the workflow references to that commit, and run CI against the resulting head.
This keeps every workflow revision independent of moving branches or tags.

Publish a version tag only after checks and representative caller runs pass.
Tags identify releases; consumers pin their commit SHAs. Breaking changes to
inputs, permissions or expected scripts require a new major release.

Licensed under [MIT](LICENSE).
