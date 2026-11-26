#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "finalize-apt.py"
spec = importlib.util.spec_from_file_location("finalize_apt", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestFinalApt(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.apt = self.root / "etc/apt"
        self.parts = self.apt / "sources.list.d"
        self.parts.mkdir(parents=True)
        self.keep = self.parts / "retrode3.list"
        self.keep.write_text("deb [arch=mipsel signed-by=/usr/share/keyrings/retrode3-archive-keyring.gpg] https://packages.retrode.com testing main\n")
        key = self.root / "usr/share/keyrings/retrode3-archive-keyring.gpg"
        key.parent.mkdir(parents=True)
        key.write_bytes(b"fixture")
        (self.apt / "sources.list").write_text("deb https://deb.debian.org/debian bookworm main\n")
        (self.parts / "debian.sources").write_text("Types: deb\n")
    def test_only_retrode_source(self):
        mod.finalize(self.root)
        self.assertEqual(list(self.parts.iterdir()), [self.keep])
        self.assertFalse((self.apt / "sources.list").exists())
        mod.finalize(self.root)
    def test_no_removal_on_bad_source(self):
        self.keep.write_text("deb https://example.org testing main\n")
        with self.assertRaises(ValueError):
            mod.finalize(self.root)
        self.assertTrue((self.apt / "sources.list").exists())
    def test_no_removal_on_symlink(self):
        (self.parts / "other.list").symlink_to(self.keep)
        with self.assertRaises(ValueError):
            mod.finalize(self.root)
        self.assertTrue((self.apt / "sources.list").exists())

if __name__ == "__main__":
    unittest.main()
