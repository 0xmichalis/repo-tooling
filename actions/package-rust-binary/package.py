"""Preserve the MCP binary release archive layout on Linux and macOS."""

import hashlib
import os
from pathlib import Path
import re
import sys
import tarfile


def package(binary, tag, target):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", binary) or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise ValueError("binary and target must be plain names")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?", tag):
        raise ValueError("tag must be vMAJOR.MINOR.PATCH")
    staging = f"{binary}-{tag}-{target}"
    files = [Path("target") / target / "release" / binary, Path("README.md"), Path("LICENSE")]
    for source in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    archive = Path(f"{staging}.tar.gz")
    with tarfile.open(archive, "w:gz") as output:
        for source in files:
            output.add(source, arcname=f"{staging}/{source.name}", recursive=False)
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    Path(f"{archive}.sha256").write_text(f"{digest.hexdigest()}  {archive.name}\n")
    return archive.name


if __name__ == "__main__":
    try:
        name = package(os.environ["BINARY"], os.environ["RELEASE_TAG"], os.environ["TARGET"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"archive={name}\n")
    except (OSError, ValueError, KeyError) as error:
        print(f"::error::Binary packaging failed: {error}", file=sys.stderr)
        sys.exit(1)
