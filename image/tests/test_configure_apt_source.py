#!/usr/bin/env python3
"""Offline checks for the explicit, fingerprint-pinned APT source."""
import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "configure-apt-source.py"
spec = importlib.util.spec_from_file_location("retrode3_apt_source", MODULE)
apt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apt)


class AptSourceSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        home = Path(cls.temp.name) / "gnupg"
        home.mkdir(mode=0o700)
        env = dict(os.environ, GNUPGHOME=str(home))
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-generate-key",
                        "Retrode3 CI Test <ci@example.invalid>", "ed25519", "sign", "0"],
                       check=True, env=env, capture_output=True)
        keys = subprocess.check_output(["gpg", "--batch", "--with-colons",
                                        "--list-keys"], env=env, text=True)
        cls.fingerprint = next(line.split(":")[9] for line in keys.splitlines()
                               if line.startswith("fpr:"))
        cls.key = Path(cls.temp.name) / "key.gpg"
        cls.key.write_bytes(subprocess.check_output(
            ["gpg", "--batch", "--export", cls.fingerprint], env=env))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "root"
        (self.root / "etc").mkdir(parents=True)
        (self.root / "etc/debian_version").write_text("12.15\n")

    def test_testing_source_and_pinned_key(self):
        apt.configure(self.root, self.key, self.fingerprint, "testing")
        self.assertEqual((self.root / apt.KEY_DEST).read_bytes(), self.key.read_bytes())
        self.assertEqual((self.root / apt.LIST_DEST).read_text(),
                         "deb [arch=mipsel signed-by=/usr/share/keyrings/retrode3-archive-keyring.gpg] "
                         "https://packages.retrode.com testing main\n")
        self.assertEqual((self.root / apt.KEY_DEST).stat().st_mode & 0o777, 0o644)
        with self.assertRaisesRegex(ValueError, "existing"):
            apt.configure(self.root, self.key, self.fingerprint, "testing")

    def test_stable_source(self):
        apt.configure(self.root, self.key, self.fingerprint, "stable")
        self.assertIn(" stable main\n", (self.root / apt.LIST_DEST).read_text())

    def test_reject_unverified_fingerprint(self):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            apt.configure(self.root, self.key, "0" * 40, "testing")
        self.assertFalse((self.root / apt.LIST_DEST).exists())

    def test_reject_untrusted_suite(self):
        with self.assertRaisesRegex(ValueError, "suite"):
            apt.configure(self.root, self.key, self.fingerprint, "sid")

    def test_reject_symlink_keyring_directory(self):
        (self.root / "usr/share").mkdir(parents=True)
        (self.root / "usr/share/keyrings").symlink_to(Path(self.tmp.name))
        with self.assertRaisesRegex(ValueError, "symlink"):
            apt.configure(self.root, self.key, self.fingerprint, "testing")


if __name__ == "__main__":
    unittest.main()
