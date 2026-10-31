"""Report cargo-audit findings without treating operational failures as clean."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


ISSUE_TITLE = "cargo audit: vulnerable dependencies"
BODY_LIMIT = 60_000


def ignore_arguments(config):
    """Cargo reads .cargo/audit.toml itself; cargo-deny ignores need argv."""
    if not config:
        return []
    with Path(config).open("rb") as source:
        entries = tomllib.load(source).get("advisories", {}).get("ignore", [])
    arguments = []
    for entry in entries:
        advisory = entry.get("id") if isinstance(entry, dict) else entry
        if not isinstance(advisory, str) or not advisory:
            raise ValueError("Each advisory ignore must be an ID or an {id, reason} table")
        arguments.extend(["--ignore", advisory])
    return arguments


def audit(config):
    result = subprocess.run(
        ["cargo", "audit", "--json", *ignore_arguments(config)],
        capture_output=True,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    # cargo-audit 0.22.0 exits 2 on operational errors and 1 on findings.
    # Validate the report before any issue API call, including a clean close.
    if result.returncode not in (0, 1):
        raise RuntimeError(f"cargo audit failed with exit code {result.returncode}")
    report = json.loads(result.stdout)
    vulnerabilities = report["vulnerabilities"]
    findings = vulnerabilities["list"]
    if (
        not isinstance(findings, list)
        or type(vulnerabilities["found"]) is not bool
        or type(vulnerabilities["count"]) is not int
        or vulnerabilities["count"] != len(findings)
        or vulnerabilities["found"] != bool(findings)
    ):
        raise ValueError("Invalid cargo-audit vulnerability report")
    if result.returncode == 1 and not findings:
        raise RuntimeError("cargo audit failed without a vulnerability finding")
    return findings


def issue_body(findings, sha, run_url, config):
    lines = [
        f"`cargo audit` found vulnerable dependencies on `{sha}` (default branch).",
        "",
    ]
    for finding in findings:
        advisory = finding["advisory"]
        package = finding["package"]
        title = " ".join(advisory["title"].splitlines())
        lines.append(
            f"- **{advisory['id']}**: `{package['name']} {package['version']}` — {title}"
        )
        patched = finding.get("versions", {}).get("patched", [])
        if patched:
            lines.append(f"  Patched versions: {', '.join(patched)}")
    footer = (
        f"\n\n[Workflow run]({run_url}) (full audit output)\n\n"
        f"Exclusions: `[advisories] ignore` in `{config or '.cargo/audit.toml'}`.\n"
    )
    body = "\n".join(lines)
    suffix = "\n\n[Findings truncated; see workflow output.]"
    budget = BODY_LIMIT - len(footer.encode())
    if len(body.encode()) > budget:
        body = body.encode()[: budget - len(suffix.encode())].decode(errors="ignore") + suffix
    return body + footer


def github_api(endpoint, method="GET", payload=None, paginate=False):
    command = ["gh", "api", "--method", method, endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def issue_title(workspace, directory):
    lockfile = (Path(directory).resolve() / "Cargo.lock").relative_to(Path(workspace).resolve())
    return ISSUE_TITLE if lockfile == Path("Cargo.lock") else f"{ISSUE_TITLE} ({lockfile.as_posix()})"


def sync_issue(findings, repository, sha, run_url, config, title=ISSUE_TITLE):
    endpoint = f"repos/{repository}/issues"
    pages = github_api(f"{endpoint}?state=open&per_page=100", paginate=True)
    matching = sorted(
        issue["number"]
        for page in pages
        for issue in page
        if issue["title"] == title and "pull_request" not in issue
    )
    number = matching[0] if matching else None
    if findings:
        body = issue_body(findings, sha, run_url, config)
        if number is None:
            github_api(endpoint, "POST", {"title": title, "body": body})
        else:
            github_api(f"{endpoint}/{number}", "PATCH", {"body": body})
    elif number is not None:
        github_api(
            f"{endpoint}/{number}/comments",
            "POST",
            {"body": f"No advisories reported by `cargo audit` on `{sha}`. [Workflow run]({run_url})."},
        )
        github_api(f"{endpoint}/{number}", "PATCH", {"state": "closed"})


def main():
    report_issues = os.environ.get("REPORT_ISSUES", "true")
    if report_issues not in ("true", "false"):
        raise ValueError("report-issues must be true or false")
    config = os.environ.get("DENY_CONFIG", "")
    findings = audit(config)
    if report_issues == "false":
        return int(bool(findings))
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    repository = os.environ["GITHUB_REPOSITORY"]
    run_url = (
        f"{os.environ['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
        f"{os.environ['GITHUB_RUN_ID']}"
    )
    title = issue_title(os.environ["GITHUB_WORKSPACE"], Path.cwd())
    sync_issue(findings, repository, sha, run_url, config, title)
    return int(bool(findings))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"::error::Rust audit/reporting failed: {error}", file=sys.stderr)
        sys.exit(2)
