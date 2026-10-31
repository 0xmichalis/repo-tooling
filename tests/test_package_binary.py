"""Check release archive contents, permissions and checksums."""

import contextlib
import hashlib
import importlib.util
import os
from pathlib import Path
import tarfile
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "actions/package-rust-binary/package.py"
SPEC = importlib.util.spec_from_file_location("package_binary", SOURCE)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


@contextlib.contextmanager
def workspace():
    original = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield
        finally:
            os.chdir(original)


class PackageTests(unittest.TestCase):
    def test_archive_layout_and_executable_mode_and_checksum(self):
        for target in ["x86_64-unknown-linux-musl", "aarch64-apple-darwin", "x86_64-apple-darwin"]:
            with self.subTest(target=target), workspace():
                binary = Path("target") / target / "release/app"
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"built binary")
                binary.chmod(0o755)
                Path("README.md").write_text("readme")
                Path("LICENSE").write_text("license")
                name = package.package("app", "v1.2.3", target)
                staging = f"app-v1.2.3-{target}"
                with tarfile.open(name) as archive:
                    self.assertEqual(archive.getnames(), [f"{staging}/app", f"{staging}/README.md", f"{staging}/LICENSE"])
                    self.assertEqual(archive.extractfile(f"{staging}/app").read(), b"built binary")
                    self.assertEqual(archive.getmember(f"{staging}/app").mode, 0o755)
                expected = f"{hashlib.sha256(Path(name).read_bytes()).hexdigest()}  {name}\n"
                self.assertEqual(Path(name + ".sha256").read_text(), expected)

    def test_missing_build_or_invalid_names_create_no_archive(self):
        cases = [("app", "v1.2.3", "x86_64-unknown-linux-musl"), ("../app", "v1.2.3", "target"), ("app", "main", "target")]
        for arguments in cases:
            with self.subTest(arguments=arguments), workspace():
                with self.assertRaises((FileNotFoundError, ValueError)):
                    package.package(*arguments)
                self.assertEqual(list(Path.cwd().glob("*.tar.gz")), [])


if __name__ == "__main__":
    unittest.main()
