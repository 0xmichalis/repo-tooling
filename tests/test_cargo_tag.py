"""Cover Cargo version parsing and resumable tag/release publication."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "actions/cargo-tag/tag.py"
SPEC = importlib.util.spec_from_file_location("cargo_tag", SOURCE)
tag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tag)
BEFORE = "a" * 40
CURRENT = "b" * 40


class TagTests(unittest.TestCase):
    def test_version_comes_from_package_or_workspace_not_dependencies(self):
        for manifest in [
            '[package]\nversion="1.2.3"\n[dependencies.example]\nversion="9.9.9"',
            '[workspace.package]\nversion="1.2.3"',
            '[package]\nversion.workspace=true\n[workspace.package]\nversion="1.2.3"',
        ]:
            with self.subTest(manifest=manifest):
                self.assertEqual(tag.version(manifest), "1.2.3")
        with self.assertRaises(ValueError):
            tag.version('[package]\nname="no-version"\n[dependencies.example]\nversion="9.9.9"')

    def test_unchanged_version_does_not_call_github(self):
        with patch.object(tag, "version_at", return_value="1.2.3"), patch.object(tag, "api") as api:
            self.assertEqual(tag.tag_version(BEFORE, CURRENT, "owner/app", "main"), "")
            api.assert_not_called()

    def test_new_tag_is_created_on_the_requested_sha_then_dispatched(self):
        with patch.object(tag, "version_at", side_effect=["1.2.3", "1.2.2"]):
            with patch.object(tag, "api", side_effect=[[], {}]) as api:
                with patch.object(tag.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                    self.assertEqual(tag.tag_version(BEFORE, CURRENT, "owner/app", "main"), "v1.2.3")
                    self.assertEqual(api.call_args.args[1], {"ref": "refs/tags/v1.2.3", "sha": CURRENT})
                    self.assertIn("tag=v1.2.3", run.call_args.args[0])

    def test_existing_tag_on_same_commit_resumes_dispatch(self):
        existing = [{"ref": "refs/tags/v1.2.3", "object": {"type": "commit", "sha": CURRENT}}]
        with patch.object(tag, "version_at", side_effect=["1.2.3", "1.2.2"]):
            with patch.object(tag, "api", return_value=existing) as api:
                with patch.object(tag.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                    self.assertEqual(tag.tag_version(BEFORE, CURRENT, "owner/app", "main"), "v1.2.3")
                    self.assertEqual(api.call_count, 1)

    def test_existing_annotated_tag_on_another_commit_is_not_moved_or_dispatched(self):
        existing = [{"ref": "refs/tags/v1.2.3", "object": {"type": "tag", "sha": "c" * 40}}]
        with patch.object(tag, "version_at", side_effect=["1.2.3", "1.2.2"]):
            with patch.object(tag, "api", side_effect=[existing, {"object": {"type": "commit", "sha": BEFORE}}]) as api:
                with patch.object(tag.subprocess, "run") as run:
                    self.assertEqual(tag.tag_version(BEFORE, CURRENT, "owner/app", "main"), "")
                    self.assertEqual(api.call_count, 2)
                    run.assert_not_called()

    def test_dispatch_failure_retries_and_stays_failed(self):
        with patch.object(tag, "version_at", side_effect=["1.2.3", "1.2.2"]):
            with patch.object(tag, "api", side_effect=[[], {}]):
                with patch.object(tag.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as run:
                    with patch.object(tag.time, "sleep") as sleep:
                        with self.assertRaisesRegex(RuntimeError, "rerun"):
                            tag.tag_version(BEFORE, CURRENT, "owner/app", "main")
                        self.assertEqual(run.call_count, 3)
                        self.assertEqual(sleep.call_count, 2)

    def test_first_push_can_tag_without_a_previous_commit(self):
        with patch.object(tag, "version_at", return_value="1.2.3") as version_at:
            with patch.object(tag, "api", side_effect=[[], {}]):
                with patch.object(tag.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                    self.assertEqual(tag.tag_version("0" * 40, CURRENT, "owner/app", "main"), "v1.2.3")
                    version_at.assert_called_once_with(CURRENT)

    def test_invalid_sha_does_not_reach_git(self):
        with patch.object(tag, "version_at") as version_at:
            with self.assertRaises(ValueError):
                tag.tag_version("main", CURRENT, "owner/app", "main")
            version_at.assert_not_called()


if __name__ == "__main__":
    unittest.main()
