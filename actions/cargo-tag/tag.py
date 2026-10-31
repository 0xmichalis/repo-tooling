"""Tag changed package/workspace versions and make failed dispatches retryable."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib


SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?")


def version(manifest):
    document = tomllib.loads(manifest)
    value = document.get("package", {}).get("version")
    if value is None or isinstance(value, dict):
        value = document.get("workspace", {}).get("package", {}).get("version")
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError("Cargo.toml must define a package or workspace.package version")
    return value


def version_at(sha, optional=False):
    result = subprocess.run(["git", "show", f"{sha}:Cargo.toml"], capture_output=True, text=True)
    if result.returncode:
        if optional:
            # A newly added manifest has no previous version. Other git errors
            # must not silently turn into a release.
            subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], check=True, capture_output=True)
            return None
        result.check_returncode()
    return version(result.stdout)


def api(arguments, payload=None):
    command = ["gh", "api", *arguments]
    if payload is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def tag_version(before, current, repository, branch):
    if not re.fullmatch(r"[a-f0-9]{40}", before) or not re.fullmatch(r"[a-f0-9]{40}", current):
        raise ValueError("before-sha and sha must be full commit SHAs")
    current_version = version_at(current)
    previous_version = None if before == "0" * 40 else version_at(before, optional=True)
    if current_version == previous_version:
        print("Cargo version is unchanged.")
        return ""
    tag = f"v{current_version}"
    refs = api([f"repos/{repository}/git/matching-refs/tags/{tag}"])
    existing = next((ref for ref in refs if ref["ref"] == f"refs/tags/{tag}"), None)
    if existing is None:
        api(["--method", "POST", f"repos/{repository}/git/refs"], {"ref": f"refs/tags/{tag}", "sha": current})
    else:
        target = existing["object"]
        while target["type"] == "tag":
            target = api([f"repos/{repository}/git/tags/{target['sha']}"])["object"]
        if target["type"] != "commit" or target["sha"] != current:
            print(f"{tag} already exists on another commit; leaving it unchanged.")
            return ""
    # GITHUB_TOKEN tag creation does not trigger a push workflow. Dispatching
    # explicitly also resumes a release after a previous dispatch failure.
    for attempt in range(3):
        result = subprocess.run([
            "gh", "workflow", "run", "release.yml", "--repo", repository,
            "--ref", branch, "--field", f"tag={tag}",
        ], check=False)
        if result.returncode == 0:
            return tag
        if attempt < 2:
            time.sleep((attempt + 1) * 5)
    raise RuntimeError(f"{tag} exists but release dispatch failed; rerun this workflow to retry")


def main():
    tag = tag_version(
        os.environ["BEFORE_SHA"], os.environ["CURRENT_SHA"],
        os.environ["GITHUB_REPOSITORY"], os.environ["DEFAULT_BRANCH"],
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"tag={tag}\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"::error::Cargo tagging failed: {error}", file=sys.stderr)
        sys.exit(1)
