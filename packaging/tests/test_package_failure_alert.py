"""Offline regression tests for actionable package failure reports."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "buildserver/package-failure-alert.sh"


class PackageFailureAlertTests(unittest.TestCase):
    def test_persists_failure_and_prints_actionable_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, RETRODE3_FAILURE_REPORT_BASE=tmp)
            env.pop("RETRODE3_BUILD_ALERT_EMAIL", None)
            result = subprocess.run(
                ["bash", str(SCRIPT), "develop", "1", "apt-publication",
                 "/private/build.log"],
                env=env, capture_output=True, text=True, check=True,
            )
            marker = Path(tmp) / "artifacts/logs/last-failed-develop.txt"
            self.assertTrue(marker.is_file())
            content = marker.read_text()
            self.assertIn("apt-publication", content)
            self.assertIn("partial", content.lower())
            self.assertIn("/private/build.log", content)
            self.assertIn("FAILED:", result.stderr)
            self.assertIn("partially imported", result.stderr)

    def test_rejects_invalid_branch_and_zero_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, RETRODE3_FAILURE_REPORT_BASE=tmp)
            for branch, code in (("prod", "1"), ("develop", "0")):
                result = subprocess.run(
                    ["bash", str(SCRIPT), branch, code, "test"],
                    env=env, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(tmp) / "artifacts").exists())

    def test_optional_mail_uses_local_sendmail_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bin_dir = base / "bin"
            bin_dir.mkdir()
            capture = base / "mail.txt"
            sendmail = bin_dir / "sendmail"
            sendmail.write_text('#!/bin/sh\ncat > "$RETRODE3_MAIL_CAPTURE"\n')
            sendmail.chmod(0o755)
            env = dict(
                os.environ,
                RETRODE3_FAILURE_REPORT_BASE=tmp,
                RETRODE3_BUILD_ALERT_EMAIL="alerts@example.org",
                RETRODE3_MAIL_CAPTURE=str(capture),
                PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
            )
            subprocess.run(
                ["bash", str(SCRIPT), "master", "3", "apt-publication"],
                env=env, capture_output=True, text=True, check=True,
            )
            mail = capture.read_text()
            self.assertIn("To: alerts@example.org", mail)
            self.assertIn("FAILED", mail)
            self.assertIn("partial", mail.lower())

    def test_invalid_recipient_never_invokes_sendmail(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(
                os.environ,
                RETRODE3_FAILURE_REPORT_BASE=tmp,
                RETRODE3_BUILD_ALERT_EMAIL="bad\nBcc: injected@example.org",
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), "develop", "2", "apt-publication"],
                env=env, capture_output=True, text=True, check=True,
            )
            self.assertIn("invalid RETRODE3_BUILD_ALERT_EMAIL", result.stderr)


if __name__ == "__main__":
    unittest.main()
