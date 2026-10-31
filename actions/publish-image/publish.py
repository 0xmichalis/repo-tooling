"""Keep latest behind successful digest signing, verification and freshness checks."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote


def command(arguments):
    result = subprocess.run(arguments, text=True, capture_output=True, check=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def boolean(value):
    if value not in ("true", "false"):
        raise ValueError("Boolean inputs must be true or false")
    return value == "true"


def publish(image, promote, require_head, repository, branch):
    if (
        image.startswith("-")
        or "@" in image
        or ":" not in image.rsplit("/", 1)[-1]
        or any(character.isspace() for character in image)
    ):
        raise ValueError("image must be an already built image tag")
    output = command(["docker", "push", image])
    digests = set(re.findall(r"\bdigest: (sha256:[a-f0-9]{64})\b", output))
    if len(digests) != 1:
        raise ValueError("docker push did not return exactly one image digest")
    digest = digests.pop()
    name = image.rsplit(":", 1)[0]
    reference = f"{name}@{digest}"
    command([
        "cosign", "sign", "--yes", "--recursive", "--tlog-upload=false",
        "--key", "env://COSIGN_PRIVATE_KEY", reference,
    ])
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as directory:
        public_key = Path(directory) / "cosign.pub"
        public_key.write_text(command(["cosign", "public-key", "--key", "env://COSIGN_PRIVATE_KEY"]))
        command([
            "cosign", "verify", "--insecure-ignore-tlog=true", "--key", str(public_key), reference,
        ])
    if promote:
        if require_head:
            if not branch:
                raise ValueError("The caller's default branch is required for promotion")
            source = command(["git", "rev-parse", "HEAD"]).strip()
            current = command([
                "gh", "api", f"repos/{repository}/git/ref/heads/{quote(branch, safe='')}",
                "--jq", ".object.sha",
            ]).strip()
            if not re.fullmatch(r"[a-f0-9]{40}", current):
                raise ValueError("GitHub did not return a default branch commit SHA")
            if source != current:
                print(f"::notice::Default branch advanced past {source}; leaving latest unchanged.")
                return digest
        command([
            "docker", "buildx", "imagetools", "create", "--prefer-index=false",
            "--tag", f"{name}:latest", reference,
        ])
    return digest


def main():
    digest = publish(
        os.environ["IMAGE_TAG"],
        boolean(os.environ["PROMOTE_LATEST"]),
        boolean(os.environ["REQUIRE_CURRENT_HEAD"]),
        os.environ["GITHUB_REPOSITORY"],
        os.environ.get("DEFAULT_BRANCH", ""),
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"digest={digest}\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"::error::Signed image publication failed: {error}", file=sys.stderr)
        sys.exit(1)
