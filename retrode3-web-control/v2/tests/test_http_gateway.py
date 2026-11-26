#!/usr/bin/env python3
"""Hardware-independent tests for the experimental HTTP gateway."""
import base64
import crypt
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import http_gateway as gateway
import service


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.saved = (gateway.AUTH_FILE, gateway.WEB_ROOT, service.ROOT, service.FILES_ROOT)
        gateway.AUTH_FILE = self.root / "auth"
        gateway.WEB_ROOT = self.root
        service.ROOT = str(self.root)
        service.FILES_ROOT = str(self.root / "ROMs")
        service.ensure_storage()
        (self.root / "index.html").write_text("<html>test</html>", encoding="utf-8")
        self.server = gateway.Server(("127.0.0.1", 0), gateway.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = "127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        gateway.AUTH_FILE, gateway.WEB_ROOT, service.ROOT, service.FILES_ROOT = self.saved
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def session(self):
        status, headers, body = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return {"Cookie": headers["Set-Cookie"].split(";", 1)[0],
                "X-CSRF-Token": json.loads(body)["csrf"],
                "Origin": "http://" + self.host,
                "Content-Type": "application/octet-stream"}

    def test_auth_preserves_php_bcrypt(self):
        stored = crypt.crypt("example-secret", "$2y$05$abcdefghijklmnopqrstuu")
        self.assertTrue(stored.startswith("$2y$"))
        gateway.AUTH_FILE.write_text(stored + "\n", encoding="ascii")
        self.assertEqual(self.request("GET", "/")[0], 401)
        self.assertEqual(self.request("GET", "/api/session")[0], 401)
        auth = "Basic " + base64.b64encode(b"admin:example-secret").decode("ascii")
        status, headers, _ = self.request("GET", "/", headers={"Authorization": auth})
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/api/health", headers={"Authorization": auth})[0], 200)
        self.assertEqual(self.request("GET", "/api/health", headers={"Authorization": auth + "x"})[0], 401)

    def test_untrusted_host_and_csrf(self):
        self.assertEqual(self.request("GET", "/api/health", headers={"Host": "attacker.example"})[0], 400)
        url = "/api/files/upload?folder=MD&filename=game.md"
        self.assertEqual(self.request("POST", url, b"a" * 512)[0], 403)
        h = self.session()
        h["Origin"] = "http://attacker.example"
        self.assertEqual(self.request("POST", url, b"a" * 512, h)[0], 403)
        h = self.session()
        h["X-CSRF-Token"] = "0" * 64
        self.assertEqual(self.request("POST", url, b"a" * 512, h)[0], 403)

    def test_upload_and_no_overwrite(self):
        h = self.session()
        url = "/api/files/upload?folder=MD&filename=game.md"
        for value, name in ((b"a", "game.md"), (b"b", "game-1.md")):
            status, _, body = self.request("POST", url, value * 512, h)
            self.assertEqual(status, 200, body)
            self.assertEqual(json.loads(body)["path"], "MD/" + name)
            self.assertEqual((Path(service.FILES_ROOT) / "MD" / name).read_bytes(), value * 512)

    def test_invalid_paths_and_short_stream(self):
        root = service.FILES_ROOT
        os.symlink(self.root, Path(root) / "LINK")
        for folder, name in (("../", "a.md"), ("MD", "../a.md"), ("MD", ".hidden")):
            with self.assertRaises(service.ApiError):
                gateway.store_rom(root, folder, name, 512, io.BytesIO(b"x" * 512))
        with self.assertRaises(OSError):
            gateway.store_rom(root, "LINK", "a.md", 512, io.BytesIO(b"x" * 512))
        with self.assertRaises(service.ApiError):
            gateway.store_rom(root, "MD", "a.md", 512, io.BytesIO(b"short"))
        self.assertEqual(list((Path(root) / "MD").iterdir()), [])
        with self.assertRaises(service.ApiError):
            gateway.store_rom(root, "MD", "a.md", gateway.MAX_ROM + 2, io.BytesIO(b""))

    def test_existing_api_remains_available(self):
        self.assertEqual(self.request("GET", "/api/health")[0], 200)
        h = self.session()
        h["Content-Type"] = "application/json"
        self.assertEqual(self.request("POST", "/api/files/mkdir", b'{"path":"MD"}', h)[0], 200)
        self.assertTrue((Path(service.FILES_ROOT) / "MD").is_dir())


if __name__ == "__main__":
    unittest.main()
