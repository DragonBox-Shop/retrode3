#!/usr/bin/env python3
"""Offline Apache validator unit tests; no QEMU, root privileges, or APT."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "verify-apache-offline.py"
spec = importlib.util.spec_from_file_location("verify_apache_offline", SCRIPT)
apache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apache)


class TestOfflineApache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        def write(name, content):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        write("etc/apache2/apache2.conf",
              "IncludeOptional mods-enabled/*.load\n")
        modules = self.root / "etc/apache2"
        (modules / "mods-available").mkdir(parents=True)
        (modules / "mods-enabled").mkdir(parents=True)
        for name, module, filename in (
            ("mpm_prefork", "mpm_prefork_module", "mod_mpm_prefork.so"),
            ("php8.2", "php_module", "libphp8.2.so"),
        ):
            write("etc/apache2/mods-available/" + name + ".load",
                  "LoadModule " + module +
                  " /usr/lib/apache2/modules/" + filename + "\n")
            (modules / "mods-enabled" / (name + ".load")).symlink_to(
                "../mods-available/" + name + ".load")
            binary = self.root / "usr/lib/apache2/modules" / filename
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(
                b"\x7fELF\x01\x01" + b"\0" * 12 + b"\x08\x00" + b"\0" * 40)

    def test_valid_mipsel_prefork_php(self):
        apache.verify(self.root)

    def test_conflicting_mpm(self):
        (self.root / "etc/apache2/mods-enabled/mpm_event.load").write_text(
            "conflict")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            apache.verify(self.root)

    def test_missing_include(self):
        (self.root / "etc/apache2/apache2.conf").write_text(
            "#IncludeOptional mods-enabled/*.load\n")
        with self.assertRaisesRegex(ValueError, "include"):
            apache.verify(self.root)

    def test_inactive_loadmodule(self):
        path = self.root / "etc/apache2/mods-available/mpm_prefork.load"
        path.write_text("#LoadModule mpm_prefork_module foo\n")
        with self.assertRaisesRegex(ValueError, "LoadModule"):
            apache.verify(self.root)

    def test_wrong_binary_arch(self):
        path = self.root / "usr/lib/apache2/modules/mod_mpm_prefork.so"
        bad = bytearray(path.read_bytes())
        bad[5] = 2
        path.write_bytes(bad)
        with self.assertRaisesRegex(ValueError, "MIPSEL"):
            apache.verify(self.root)


if __name__ == "__main__":
    unittest.main()
