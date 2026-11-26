"""Execute the shared credential policy against disposable dummy files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[2] / "buildserver/apt-signing-secret.sh"


class SigningSecretTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.directory = self.base / "signing"
        self.directory.mkdir(mode=0o700)
        self.secret = self.directory / "apt-signing-passphrase"
        self.secret.write_text("dummy-never-log-this\n")
        self.secret.chmod(0o600)

    def check(self, expected, directory=None, secret=None):
        result = subprocess.run(
            ["bash", "-eu", "-c",
             'source "$1"; validate_apt_signing_secret "$2" "$3"',
             "test", str(HELPER), str(directory or self.directory),
             str(secret or self.secret)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, expected, result.stderr)
        self.assertNotIn("dummy-never-log-this", result.stdout + result.stderr)

    def test_private_directory_modes(self):
        for mode in (0o700, 0o2700, 0o750, 0o2770, 0o755, 0o1700):
            with self.subTest(mode=oct(mode)):
                self.directory.chmod(mode)
                self.check(mode in (0o700, 0o2700))
        self.directory.chmod(0o700)

    def test_reject_unsafe_file_modes(self):
        for mode in (0o640, 0o644, 0o400, 0o660):
            with self.subTest(mode=oct(mode)):
                self.secret.chmod(mode)
                self.check(False)

    def test_reject_hardlinks_and_symlinks(self):
        hard = self.directory / "hard"
        os.link(self.secret, hard)
        self.check(False)
        hard.unlink()
        link = self.directory / "link"
        link.symlink_to(self.secret)
        self.check(False, secret=link)
        alias = self.base / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        self.check(False, directory=alias, secret=alias / self.secret.name)

    def test_reject_empty_and_missing_secret(self):
        self.secret.write_text("")
        self.check(False)
        self.secret.unlink()
        self.check(False)

    def test_both_publishers_use_shared_policy(self):
        for name in ("publish-debs.sh", "publish-platform-develop.sh"):
            content = (HELPER.parent / name).read_text()
            check = content.index("validate_apt_signing_secret")
            self.assertLess(check, content.index("--passphrase-file"))
            self.assertLess(check, content.index("includedeb"))


if __name__ == "__main__":
    unittest.main()
