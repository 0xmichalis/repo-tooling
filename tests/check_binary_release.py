"""Validate the artifacts produced by the reusable release workflow in CI."""

import hashlib
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile


targets = {
    "x86_64-unknown-linux-musl": None,
    "aarch64-apple-darwin": 0x0100000C,
    "x86_64-apple-darwin": 0x01000007,
}
artifacts = Path("artifacts")
expected = set()
for target, cpu in targets.items():
    name = f"workflow-fixture-v0.1.0-{target}"
    archive = artifacts / f"{name}.tar.gz"
    checksum = artifacts / f"{name}.tar.gz.sha256"
    expected.update([archive.name, checksum.name])
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text() == f"{digest}  {archive.name}\n"
    with tarfile.open(archive) as contents:
        assert contents.getnames() == [
            f"{name}/workflow-fixture", f"{name}/README.md", f"{name}/LICENSE"
        ]
        assert contents.getmember(f"{name}/workflow-fixture").mode & 0o111
        binary = contents.extractfile(f"{name}/workflow-fixture").read()
    if cpu is None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "workflow-fixture"
            executable.write_bytes(binary)
            executable.chmod(0o755)
            result = subprocess.run([str(executable)], check=True, text=True, capture_output=True)
            assert result.stdout == "Rust workflow fixture\n"
    else:
        assert struct.unpack("<II", binary[:8]) == (0xFEEDFACF, cpu)
    print(f"Verified {target}")
assert {path.name for path in artifacts.iterdir()} == expected
