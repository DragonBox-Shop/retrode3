"""Exercise the actual packaged Lighttpd rules on native Bookworm."""
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest


class Backend(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("backend:" + self.path).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class LighttpdRoutes(unittest.TestCase):
    def test_packaged_routes(self):
        repo = Path(__file__).resolve().parents[2]
        rules = (repo / "packaging/assets/99-retrode3-lighttpd.conf").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets/app.js").write_text("static-js")
            (root / "assets/test.php").write_text("must-not-be-served")
            (root / "private.txt").write_text("must-not-be-served")
            (root / "index.html").write_text("must-be-proxied")
            backend = HTTPServer(("127.0.0.1", 0), Backend)
            worker = threading.Thread(target=backend.serve_forever, daemon=True)
            worker.start()
            try:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                conf = root / "lighttpd.conf"
                conf.write_text(
                    'server.modules = ( "mod_access" )\n'
                    'server.bind = "127.0.0.1"\n'
                    'server.port = %d\n' % port +
                    'server.document-root = "%s"\n' % root +
                    rules.replace("/var/www/retrode3-lighttpd", str(root))
                         .replace('"port" => 8765',
                                  '"port" => %d' % backend.server_port))
                subprocess.run(["lighttpd", "-tt", "-f", str(conf)], check=True)
                with (root / "lighttpd.log").open("w+") as log:
                    proc = subprocess.Popen(["lighttpd", "-D", "-f", str(conf)],
                                            stdout=log, stderr=log)
                    try:
                        for _ in range(100):
                            if proc.poll() is not None:
                                log.seek(0)
                                self.fail(log.read())
                            try:
                                with socket.create_connection(("127.0.0.1", port), .1):
                                    break
                            except OSError:
                                time.sleep(.05)
                        else:
                            self.fail("Lighttpd failed to start")

                        def get(path):
                            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                            try:
                                conn.request("GET", path)
                                r = conn.getresponse()
                                return r.status, r.read()
                            finally:
                                conn.close()

                        for path in ("/", "/index.html", "/api/settings"):
                            self.assertEqual(get(path), (200, ("backend:" + path).encode()))
                        self.assertEqual(get("/assets/app.js"), (200, b"static-js"))
                        for path in ("/private.txt", "/assets/test.php", "/indexXhtml"):
                            self.assertEqual(get(path)[0], 403, path)
                    finally:
                        proc.terminate()
                        proc.wait(timeout=5)
            finally:
                backend.shutdown()
                backend.server_close()
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
