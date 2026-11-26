#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "verify-lighttpd-offline.py"
spec = importlib.util.spec_from_file_location("verify_lighttpd", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestLighttpd(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in ("usr/sbin/lighttpd", "usr/lib/lighttpd/mod_proxy.so"):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x7fELF\x01\x01" + b"\0"*12 + b"\x08\x00")
        self.conf = self.root / "etc/lighttpd/conf-available/99-retrode3-lighttpd.conf"
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('server.document-root := "/var/www/retrode3-lighttpd"\nserver.modules += ( "mod_proxy" )\n127.0.0.1 8765\n')
        self.link = self.root / "etc/lighttpd/conf-enabled/99-retrode3-lighttpd.conf"
        self.link.parent.mkdir()
        self.link.symlink_to("../conf-available/99-retrode3-lighttpd.conf")
        for name in ("var/www/retrode3-lighttpd/index.html", "var/www/retrode3-lighttpd/assets/app.js",
                     "opt/retrode3-web-v2/backend/http_gateway.py"):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture")
    def test_complete(self):
        mod.verify(self.root)
    def test_bad_proxy(self):
        (self.root / "usr/lib/lighttpd/mod_proxy.so").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "MIPSEL"):
            mod.verify(self.root)
    def test_disabled_config(self):
        self.link.unlink()
        with self.assertRaisesRegex(ValueError, "not enabled"):
            mod.verify(self.root)

if __name__ == "__main__":
    unittest.main()
