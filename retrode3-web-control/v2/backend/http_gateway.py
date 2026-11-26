"""PHP-free HTTP gateway for Debian Bookworm; loopback only.

Opt-in experiment. The old Apache/PHP entrypoint remains unchanged.
"""
import base64
import binascii
import crypt
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import socket
import stat
import subprocess
import threading
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import service

AUTH_FILE = Path("/etc/retrode3-web-control.auth")
WEB_ROOT = Path("/var/www/retrode3-lighttpd")
COOKIE = "retrode3_session"
KEY = secrets.token_bytes(32)
MAX_ROM = 4 * 1024 * 1024
CHUNK = 65536
HEX = re.compile(r"[0-9a-f]{64}\Z")
FOLDER = re.compile(r"[A-Z0-9_-]{1,48}\Z")
FILENAME = re.compile(r"[A-Za-z0-9_. -]{1,128}\Z")
CSP = ("default-src 'self'; img-src 'self'; style-src 'self'; "
       "script-src 'self'; connect-src 'self'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


def error(status, code, detail):
    return service.ApiError(status, code, detail)


def password_matches(password, stored):
    # PHP PASSWORD_DEFAULT uses bcrypt ($2y$) on Bookworm.
    if not re.fullmatch(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}", stored):
        return False
    try:
        calculated = crypt.crypt(password, stored)
        return bool(calculated) and hmac.compare_digest(calculated, stored)
    except (ValueError, OSError):
        return False


def authenticated(header, auth_file=None):
    if auth_file is None:
        auth_file = AUTH_FILE
    try:
        with open(auth_file, "r", encoding="ascii") as handle:
            stored = handle.read(256).strip()
    except FileNotFoundError:
        if os.path.lexists(auth_file):
            raise error(503, "auth_unavailable", "Invalid password file")
        return True
    except (OSError, UnicodeError):
        raise error(503, "auth_unavailable", "Password file unavailable")
    try:
        scheme, value = header.split(" ", 1)
        if scheme.lower() != "basic" or len(value) > 2048:
            return False
        raw = base64.b64decode(value, validate=True).decode("utf-8")
        user, password = raw.split(":", 1)
        return user == "admin" and password_matches(password, stored)
    except (ValueError, UnicodeError, binascii.Error):
        return False


def sign(token):
    return hmac.new(KEY, token.encode("ascii"), hashlib.sha256).hexdigest()


def session_from_cookie(header):
    if len(header) > 4096:
        return None
    try:
        cookies = SimpleCookie()
        cookies.load(header)
        token, signature = cookies[COOKIE].value.split(".", 1)
        if HEX.fullmatch(token) and HEX.fullmatch(signature) and hmac.compare_digest(sign(token), signature):
            return token
    except (CookieError, KeyError, ValueError):
        pass
    return None


def allowed_host(value):
    # Reject arbitrary DNS hostnames (including DNS rebinding). Hostnames
    # intentionally supported by the device are explicit, not suffix matches.
    if not value or len(value) > 255 or any(c in value for c in "/\\@?# \t\r\n"):
        return False
    try:
        parsed = urlsplit("http://" + value)
        host = parsed.hostname
        port = parsed.port
        if not host or parsed.netloc != value or (port is not None and not 1 <= port <= 65535):
            return False
        if host.lower() in ("retrode3", "retrode3.local", "retrode", "retrode.local", "localhost"):
            return True
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def store_rom(root, folder, filename, length, stream):
    """Stream to a hidden file; atomically publish without replacing ROMs."""
    if not FOLDER.fullmatch(folder):
        raise error(400, "folder", "Invalid ROM destination folder")
    if not FILENAME.fullmatch(filename) or filename.startswith("."):
        raise error(400, "filename", "Invalid ROM filename")
    stem, ext = os.path.splitext(filename)
    if not stem.strip() or len(stem) > 120:
        raise error(400, "filename", "Invalid ROM filename")
    if length < 512 or length > MAX_ROM or length % 2:
        raise error(400, "size", "ROM must be even-sized and at most 4 MiB")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    rootfd = os.open(root, flags)
    dirfd = None
    temp = None
    try:
        try:
            os.mkdir(folder, mode=0o755, dir_fd=rootfd)
        except FileExistsError:
            pass
        dirfd = os.open(folder, flags, dir_fd=rootfd)
        tempname = ".upload-" + secrets.token_hex(16)
        fd = os.open(tempname, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=dirfd)
        temp = tempname
        with os.fdopen(fd, "wb") as handle:
            remaining = length
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                if not block:
                    raise error(400, "upload", "Incomplete ROM upload")
                handle.write(block)
                remaining -= len(block)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        for i in range(1000):
            name = stem + ("-" + str(i) if i else "") + ext
            try:
                os.link(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
                return {"ok": True, "path": folder + "/" + name, "size": length}
            except FileExistsError:
                continue
        raise error(409, "exists", "Too many files with this name")
    finally:
        if dirfd is not None:
            try:
                if temp is not None:
                    os.unlink(temp, dir_fd=dirfd)
            finally:
                os.close(dirfd)
        os.close(rootfd)


def direct_usb_peer(headers):
    # Lighttpd mod_proxy adds the real remote address as the last element.
    # Never trust an earlier client-supplied X-Forwarded-For value.
    values = headers.get_all("X-Forwarded-For", [])
    if len(values) != 1 or len(values[0]) > 2048:
        return False
    try:
        peer = ipaddress.IPv4Address(values[0].rsplit(",", 1)[-1].strip())
        if peer.is_loopback or peer.is_multicast or peer.is_unspecified:
            return False
        result = subprocess.run(
            ["/sbin/ip", "-j", "-4", "route", "get", str(peer)],
            capture_output=True, text=True, timeout=2, check=True)
        routes = service.json.loads(result.stdout)
        return (len(routes) == 1 and routes[0].get("dev") == "usb0"
                and not routes[0].get("gateway") and routes[0].get("type", "unicast") == "unicast")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False


class Handler(service.Handler):
    def _gate(self, write=False):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or not allowed_host(hosts[0]):
            raise error(400, "host_invalid", "Invalid HTTP host")
        if not authenticated(self.headers.get("Authorization", "")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Retrode3 Administration"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if write:
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + hosts[0]:
                raise error(403, "origin_invalid", "Invalid request origin")
            token = session_from_cookie(self.headers.get("Cookie", ""))
            supplied = self.headers.get("X-CSRF-Token", "")
            if not token or not HEX.fullmatch(supplied) or not hmac.compare_digest(token, supplied):
                raise error(403, "csrf_invalid", "Invalid session token")
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise error(400, "invalid_length", "Invalid request framing")
        return True

    def _developer_ssh(self, data):
        if not isinstance(data, dict):
            raise error(400, "invalid_json", "Expected an object")
        if data.get("action") == "setup":
            if self.client_address[0] != "127.0.0.1" or not direct_usb_peer(self.headers):
                raise error(403, "developer_setup_usb", "Initial developer setup requires the direct USB network")
        try:
            result = subprocess.run(
                ["/usr/bin/sudo", "-n", "/usr/sbin/retrode3-ssh-control"],
                input=service.json.dumps(data), text=True, capture_output=True, timeout=45)
            body = service.json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise error(503, "ssh_unavailable", "SSH control unavailable")
        if result.returncode:
            raise error(403, "ssh_failed", body.get("error", "SSH control failed"))
        if data.get("action") == "status":
            body["setup_allowed"] = (body.get("setup_needed", False)
                                     and self.client_address[0] == "127.0.0.1"
                                     and direct_usb_peer(self.headers))
        self._json(200, body)

    def _update(self, data):
        if not isinstance(data, dict) or set(data) != {"action"} or data["action"] not in ("check", "install"):
            raise error(400, "invalid_update", "Only check or install is supported")
        with service.MANAGER.lock:
            if service.MANAGER.active is not None or not service.MANAGER.bus_lock.acquire(False):
                raise error(409, "busy", "Cartridge hardware busy")
            try:
                result = subprocess.run(
                    ["/usr/bin/sudo", "-n", "/usr/sbin/retrode3-update-control"],
                    input=service.json.dumps(data), text=True, capture_output=True, timeout=5)
                body = service.json.loads(result.stdout)
            except (OSError, ValueError, subprocess.SubprocessError):
                raise error(503, "update_unavailable", "Update control unavailable")
            finally:
                service.MANAGER.bus_lock.release()
            if result.returncode:
                raise error(409, "update_failed", body.get("error", "Update control failed"))
        self._json(202, body)

    def _session(self):
        token = session_from_cookie(self.headers.get("Cookie", "")) or secrets.token_hex(32)
        body = service.json.dumps({"csrf": token}).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Set-Cookie", COOKIE + "=" + token + "." + sign(token) +
                         "; Path=/; HttpOnly; SameSite=Strict")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _index(self):
        data = (WEB_ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _upload(self, url):
        if self.headers.get("Content-Type") != "application/octet-stream":
            raise error(415, "upload", "Expected raw ROM bytes")
        length = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,8}", length):
            raise error(400, "invalid_length", "Invalid upload length")
        query = parse_qs(url.query, keep_blank_values=True, max_num_fields=2)
        if set(query) != {"folder", "filename"} or any(len(x) != 1 for x in query.values()):
            raise error(400, "upload", "Expected folder and filename")
        service.ensure_storage()
        self._json(200, store_rom(service.FILES_ROOT, query["folder"][0],
                                  query["filename"][0], int(length), self.rfile))

    def do_GET(self):
        try:
            if not self._gate():
                return
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._index()
            elif path == "/api/session":
                self._session()
            elif path == "/api/update":
                self._json(200, service.update_status())
            elif path == "/api/developer/ssh":
                self._developer_ssh({"action": "status"})
            else:
                super().do_GET()
        except service.ApiError as exc:
            self._json(exc.status, {"error": exc.code, "message": exc.detail})
        except (OSError, ValueError):
            self._json(503, {"error": "request_failed"})

    def do_POST(self):
        try:
            if not self._gate(write=True):
                return
            url = urlsplit(self.path)
            if url.path == "/api/files/upload":
                self._upload(url)
            elif url.path == "/api/update":
                self._update(self._body())
            elif url.path == "/api/developer/ssh":
                self._developer_ssh(self._body())
            else:
                super().do_POST()
        except service.ApiError as exc:
            self._json(exc.status, {"error": exc.code, "message": exc.detail})
        except (OSError, ValueError):
            self._json(400, {"error": "request_failed"})

    def log_message(self, fmt, *args):
        # Avoid logging URL query parameters or credentials.
        pass


class Server(service.ThreadedServer):
    """Bound concurrency and socket timeouts on the small target."""
    request_queue_size = 8
    slots = threading.BoundedSemaphore(6)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(20)
        return sock, addr

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    server = Server(("127.0.0.1", 8765), Handler)
    service.AUTO.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
