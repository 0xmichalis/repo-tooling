"""Exercise audit failures and the rolling issue lifecycle without API writes."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "actions/rust-audit/audit.py"
SPEC = importlib.util.spec_from_file_location("rust_audit", SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def finding(title="Memory safety issue"):
    return {
        "advisory": {"id": "RUSTSEC-2026-0001", "title": title},
        "package": {"name": "example", "version": "1.0.0"},
        "versions": {"patched": [">=1.0.1"]},
    }


def completed(code=0, findings=None):
    findings = [] if findings is None else findings
    report = {"vulnerabilities": {"found": bool(findings), "count": len(findings), "list": findings}}
    return subprocess.CompletedProcess([], code, json.dumps(report), "")


class AuditTests(unittest.TestCase):
    def run_audit(self, result):
        with patch.object(audit.subprocess, "run", return_value=result):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return audit.audit("")

    def test_clean_and_vulnerable_reports(self):
        self.assertEqual(self.run_audit(completed()), [])
        self.assertEqual(self.run_audit(completed(1, [finding()])), [finding()])

    def test_operational_failure_is_not_clean_even_with_json(self):
        for result in [completed(2), completed(1), subprocess.CompletedProcess([], 0, "", "")]:
            with self.subTest(result=result), self.assertRaises((RuntimeError, ValueError)):
                self.run_audit(result)

    def test_inconsistent_report_is_rejected(self):
        result = completed()
        result.stdout = '{"vulnerabilities":{"found":false,"count":1,"list":[]}}'
        with self.assertRaises(ValueError):
            self.run_audit(result)

    def test_default_config_is_left_to_cargo(self):
        self.assertEqual(audit.ignore_arguments(""), [])

    def test_deny_ids_and_reason_tables_are_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "deny.toml"
            config.write_text(
                '[advisories]\nignore = ["RUSTSEC-2026-0001", '
                '{id="RUSTSEC-2026-0002", reason="accepted"}]\n'
            )
            self.assertEqual(
                audit.ignore_arguments(config),
                ["--ignore", "RUSTSEC-2026-0001", "--ignore", "RUSTSEC-2026-0002"],
            )
            config.write_text('[advisories]\nignore = [{reason="missing id"}]\n')
            with self.assertRaises(ValueError):
                audit.ignore_arguments(config)

    def test_issue_body_is_bounded_for_large_unicode_reports(self):
        body = audit.issue_body([finding("界" * 30_000)] * 3, "abc123", "https://example.test/run", "")
        self.assertLessEqual(len(body.encode()), audit.BODY_LIMIT)
        self.assertIn("truncated", body)
        self.assertIn("https://example.test/run", body)
        self.assertIn(".cargo/audit.toml", body)

    def test_findings_create_or_update_one_issue_across_pages(self):
        existing = {"number": 12, "title": audit.ISSUE_TITLE}
        pull = {"number": 1, "title": audit.ISSUE_TITLE, "pull_request": {}}
        for pages, endpoint, method in [
            ([[]], "repos/owner/project/issues", "POST"),
            ([[pull], [existing]], "repos/owner/project/issues/12", "PATCH"),
        ]:
            with self.subTest(pages=pages), patch.object(audit, "github_api", side_effect=[pages, {}]) as api:
                audit.sync_issue([finding()], "owner/project", "abc123", "https://example.test/run", "deny.toml")
                self.assertEqual(api.call_count, 2)
                self.assertEqual(api.call_args.args[:2], (endpoint, method))
                self.assertIn("deny.toml", api.call_args.args[2]["body"])

    def test_clean_audit_closes_existing_issue_after_comment(self):
        with patch.object(audit, "github_api", side_effect=[[[{"number": 12, "title": audit.ISSUE_TITLE}]], {}, {}]) as api:
            audit.sync_issue([], "owner/project", "abc123", "https://example.test/run", "")
            self.assertEqual(api.call_args_list[1].args[0], "repos/owner/project/issues/12/comments")
            self.assertEqual(api.call_args.args, ("repos/owner/project/issues/12", "PATCH", {"state": "closed"}))

    def test_clean_audit_without_issue_does_not_write(self):
        with patch.object(audit, "github_api", return_value=[[]]) as api:
            audit.sync_issue([], "owner/project", "abc123", "https://example.test/run", "")
            self.assertEqual(api.call_count, 1)

    def test_api_failure_does_not_continue_to_close(self):
        with patch.object(audit, "github_api", side_effect=[[[{"number": 12, "title": audit.ISSUE_TITLE}]], subprocess.CalledProcessError(1, "gh")]) as api:
            with self.assertRaises(subprocess.CalledProcessError):
                audit.sync_issue([], "owner/project", "abc123", "https://example.test/run", "")
            self.assertEqual(api.call_count, 2)

    def test_main_never_calls_github_after_audit_failure(self):
        with patch.object(audit, "audit", side_effect=RuntimeError("database unavailable")):
            with patch.object(audit, "github_api") as api, self.assertRaises(RuntimeError):
                audit.main()
            api.assert_not_called()

    def test_api_payload_uses_json_stdin(self):
        body = "First line\nLiteral $(example) and `code`\n界"
        with patch.object(audit.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            audit.github_api("repos/owner/project/issues", "POST", {"body": body})
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"body": body})
            self.assertEqual(run.call_args.args[0][-2:], ["--input", "-"])

    def test_lockfile_identity_is_canonical_and_preserves_root_issue(self):
        self.assertEqual(audit.issue_title("/workspace", "/workspace"), audit.ISSUE_TITLE)
        self.assertEqual(
            audit.issue_title("/workspace", "/workspace/service/../api"),
            audit.ISSUE_TITLE + " (api/Cargo.lock)",
        )
        self.assertNotEqual(
            audit.issue_title("/workspace", "/workspace/api"),
            audit.issue_title("/workspace", "/workspace/worker"),
        )

    def test_clean_nested_audit_does_not_close_root_issue(self):
        with patch.object(audit, "github_api", return_value=[[{"number": 12, "title": audit.ISSUE_TITLE}]]) as api:
            audit.sync_issue([], "owner/project", "abc123", "https://example.test/run", "", audit.ISSUE_TITLE + " (api/Cargo.lock)")
            self.assertEqual(api.call_count, 1)

    def test_read_only_audit_never_calls_github_or_git(self):
        with patch.dict(audit.os.environ, {"REPORT_ISSUES": "false"}):
            with patch.object(audit, "audit", return_value=[]) as run:
                with patch.object(audit, "github_api") as api, patch.object(audit.subprocess, "check_output") as git:
                    self.assertEqual(audit.main(), 0)
                    run.assert_called_once()
                    api.assert_not_called()
                    git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
