"""Keep failed or stale images away from latest."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "actions/publish-image/publish.py"
SPEC = importlib.util.spec_from_file_location("publish_image", SOURCE)
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)
DIGEST = "sha256:" + "a" * 64
SHA = "b" * 40


class PublishTests(unittest.TestCase):
    def outputs(self, arguments):
        if arguments[:2] == ["docker", "push"]:
            return f"sha-test: digest: {DIGEST} size: 123\n"
        if arguments[:2] == ["git", "rev-parse"] or arguments[:2] == ["gh", "api"]:
            return SHA + "\n"
        return "public key\n" if arguments[:2] == ["cosign", "public-key"] else ""

    def test_only_promotes_the_verified_digest(self):
        with patch.object(publish, "command", side_effect=self.outputs) as command:
            self.assertEqual(publish.publish("ghcr.io/owner/app:sha-test", True, True, "owner/app", "main"), DIGEST)
            commands = [call.args[0] for call in command.call_args_list]
            verify = next(i for i, args in enumerate(commands) if args[:2] == ["cosign", "verify"])
            promote = next(i for i, args in enumerate(commands) if args[:3] == ["docker", "buildx", "imagetools"])
            self.assertLess(verify, promote)
            self.assertEqual(commands[promote][-1], "ghcr.io/owner/app@" + DIGEST)

    def test_signing_or_verification_failure_never_promotes(self):
        for failed in ["sign", "verify"]:
            def execute(arguments):
                if arguments[:2] == ["cosign", failed]:
                    raise subprocess.CalledProcessError(1, arguments)
                return self.outputs(arguments)
            with self.subTest(step=failed), patch.object(publish, "command", side_effect=execute) as command, patch.object(publish.time, "sleep"):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish.publish("ghcr.io/owner/app:sha-test", True, True, "owner/app", "main")
                self.assertFalse(any(call.args[0][:2] == ["docker", "buildx"] for call in command.call_args_list))

    def test_ambiguous_push_digest_is_rejected(self):
        with patch.object(publish, "command", return_value=f"digest: {DIGEST}\ndigest: sha256:{'c' * 64}") as command:
            with self.assertRaises(ValueError):
                publish.publish("ghcr.io/owner/app:sha-test", True, True, "owner/app", "main")
            self.assertEqual(command.call_count, 1)

    def test_stale_head_or_api_failure_never_promotes(self):
        for head in ["c" * 40, "", subprocess.CalledProcessError(1, "gh")]:
            def execute(arguments):
                if arguments[:2] == ["gh", "api"]:
                    if isinstance(head, Exception):
                        raise head
                    return head
                return self.outputs(arguments)
            with self.subTest(head=head), patch.object(publish, "command", side_effect=execute) as command:
                try:
                    publish.publish("ghcr.io/owner/app:sha-test", True, True, "owner/app", "main")
                except (ValueError, subprocess.CalledProcessError):
                    pass
                self.assertFalse(any(call.args[0][:2] == ["docker", "buildx"] for call in command.call_args_list))

    def test_release_policy_can_skip_promotion_or_head_check(self):
        for promote, require_head in [(False, True), (True, False)]:
            with self.subTest(promote=promote), patch.object(publish, "command", side_effect=self.outputs) as command:
                publish.publish("localhost:5000/app:v1.0.0", promote, require_head, "owner/app", "main")
                self.assertFalse(any(call.args[0][0] == "gh" for call in command.call_args_list))
                self.assertEqual(any(call.args[0][:2] == ["docker", "buildx"] for call in command.call_args_list), promote)

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            publish.boolean("yes")
        for image in ["--help", "ghcr.io/owner/app", "ghcr.io/owner/app@" + DIGEST]:
            with self.subTest(image=image), patch.object(publish, "command") as command:
                with self.assertRaises(ValueError):
                    publish.publish(image, True, True, "owner/app", "main")
                command.assert_not_called()

    def test_transparency_log_is_required_by_default_and_optional_for_offline_registries(self):
        for required in [True, False]:
            with self.subTest(required=required), patch.object(publish, "command", side_effect=self.outputs) as command:
                publish.publish("localhost:5000/app:test", False, True, "owner/app", "main", required)
                sign = next(call.args[0] for call in command.call_args_list if call.args[0][:2] == ["cosign", "sign"])
                verify = next(call.args[0] for call in command.call_args_list if call.args[0][:2] == ["cosign", "verify"])
                self.assertIn(f"--tlog-upload={'true' if required else 'false'}", sign)
                self.assertEqual("--insecure-ignore-tlog=true" in verify, not required)


if __name__ == "__main__":
    unittest.main()
