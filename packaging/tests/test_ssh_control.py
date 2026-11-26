"""Offline tests: never touch the real shadow or authorized_keys."""
import base64
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "assets/retrode3-ssh-control"
spec = spec_from_loader("ssh_control_test", SourceFileLoader("ssh_control_test", str(path)))
ssh = module_from_spec(spec)
spec.loader.exec_module(ssh)


def key(byte):
    fields = (b"ssh-ed25519", bytes([byte]) * 32)
    blob = b"".join(len(part).to_bytes(4, "big") + part for part in fields)
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii") + " test"


class SSHControlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / ".ssh/authorized_keys"
        patcher = patch.object(ssh, "KEY_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        marker = patch.object(ssh, "KEY_ONLY", Path(tmp.name) / "ssh-key-only")
        marker.start()
        self.addCleanup(marker.stop)

    def test_short_password(self):
        saved = {}
        def apply(args, **kwargs):
            self.assertEqual(args, ["/usr/sbin/chpasswd", "-e"])
            hashed = kwargs["input"].strip().split(":", 1)[1]
            self.assertTrue(hashed.startswith("$6$"))
            self.assertEqual(ssh.crypt.crypt("x", hashed), hashed)
            saved["hash"] = hashed
            return ssh.subprocess.CompletedProcess(args, 0)
        with patch.object(ssh, "root_hash", side_effect=lambda: saved["hash"]), \
             patch.object(ssh.subprocess, "run", side_effect=apply) as run:
            ssh.set_password({"new_password": "x", "repeat_password": "x"})
            for value in ("", "a\nb", "a\x00b"):
                with self.assertRaises(ValueError):
                    ssh.set_password({"new_password": value, "repeat_password": value})
            self.assertEqual(run.call_count, 1)

    def test_password_update_failure(self):
        with patch.object(ssh.subprocess, "run",
                          return_value=ssh.subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "chpasswd exit code 1"):
                ssh.set_password({"new_password": "x", "repeat_password": "x"})

    def test_password_update_readback_mismatch(self):
        with patch.object(ssh.subprocess, "run",
                          return_value=ssh.subprocess.CompletedProcess([], 0)), \
             patch.object(ssh, "root_hash", return_value="!"):
            with self.assertRaisesRegex(ValueError, "could not be verified"):
                ssh.set_password({"new_password": "x", "repeat_password": "x"})

    def test_keys_add_deduplicate_remove_preserve_other_entries(self):
        first, second = key(1), key(2)
        ssh.update_keys({"action": "add_key", "public_key": first})
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.file.parent.stat().st_mode & 0o777, 0o700)
        with self.file.open("ab") as f:
            f.write(b"# local note\n")
            f.write(('no-pty ' + key(3) + '\n').encode())
        ssh.update_keys({"action": "add_key", "public_key": first})
        ssh.update_keys({"action": "add_key", "public_key": second})
        keys = ssh.list_keys()
        self.assertEqual(len(keys), 2)
        ssh.update_keys({"action": "remove_key", "fingerprint": keys[0]["fingerprint"]})
        self.assertEqual(len(ssh.list_keys()), 1)
        self.assertIn(b"# local note\n", self.file.read_bytes())
        self.assertIn(b"no-pty ", self.file.read_bytes())

    def test_reject_injection_and_private_keys(self):
        for value in (key(1) + "\n" + key(2), "no-pty " + key(1),
                      "-----BEGIN OPENSSH PRIVATE KEY-----",
                      "ssh-ed25519 AAAA", key(1).replace("ssh-ed25519", "ssh-rsa")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ssh.parse_key(value)

    def test_reject_symlink(self):
        self.file.parent.mkdir(mode=0o700)
        self.file.symlink_to("/dev/null")
        with self.assertRaises(ValueError):
            ssh.update_keys({"action": "add_key", "public_key": key(1)})

    def test_password_login_independent_of_keys(self):
        with patch.object(ssh, "run", return_value=1), patch.object(ssh, "set_password") as password:
            ssh.set_password_login(False)
            self.assertTrue(ssh.KEY_ONLY.is_file())
            self.assertEqual(ssh.list_keys(), [])
            ssh.update_keys({"action": "add_key", "public_key": key(1)})
            fingerprint = ssh.list_keys()[0]["fingerprint"]
            ssh.update_keys({"action": "remove_key", "fingerprint": fingerprint})
            self.assertEqual(ssh.list_keys(), [])
            self.assertTrue(ssh.KEY_ONLY.is_file())
            ssh.set_password_login(True)
            self.assertFalse(ssh.KEY_ONLY.exists())
            password.assert_not_called()

    def test_running_ssh_restart_failure_rolls_back(self):
        ssh.update_keys({"action": "add_key", "public_key": key(1)})
        with patch.object(ssh, "run", side_effect=[0, 1, 0, 0]):
            with self.assertRaisesRegex(ValueError, "previous setting restored"):
                ssh.set_password_login(False)
        self.assertFalse(ssh.KEY_ONLY.exists())

    def test_password_login_setting_requires_authentication(self):
        with patch.object(ssh, "authenticate", side_effect=ValueError("wrong")), \
             patch.object(ssh, "set_password_login") as change:
            with self.assertRaises(ValueError):
                ssh.dispatch({"action": "set_password_login", "enabled": False}, self.file.parent)
            change.assert_not_called()

    def test_mutations_require_password(self):
        for action in ("add_key", "remove_key"):
            with patch.object(ssh, "authenticate", side_effect=ValueError("wrong")), \
                 patch.object(ssh, "update_keys") as update:
                with self.assertRaises(ValueError):
                    ssh.dispatch({"action": action}, self.file.parent)
                update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
