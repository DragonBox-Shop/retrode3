#!/usr/bin/env python3
"""Retrode3 web control v2 backend. Python 3.4-compatible, loopback only.

The browser speaks to api.php. Only this service owns the NDJSON process,
filesystem access under ROMs, and privileged WLAN helper invocations.
"""
from __future__ import print_function

import argparse
import datetime
import json
import os
import re
import select
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse, quote

HOST = "127.0.0.1"
ROOT = os.path.realpath(os.environ.get("RETRODE3_GAMES_ROOT", "/usr/local/games"))
FILES_ROOT = os.path.join(ROOT, "ROMs")
SNES_BIN = os.environ.get("RETRODE3_SNES_BINARY", "/usr/local/bin/oscr-snes-native")
WLAN_BIN = os.environ.get("RETRODE3_WLAN_BINARY", "/usr/local/bin/retrode3-wlan")
RUN_SUDO = os.environ.get("RETRODE3_WLAN_SUDO", "1") == "1"
SYSTEMS = ("SNES",)
SEGMENT = re.compile(r"^[^/\\\x00-\x1f\x7f]+$")
FILE_STEM = re.compile(r"[^A-Za-z0-9_. -]+")
PROTOCOL = "retrode3-ndjson"
MAX_BODY = 16384


class ApiError(Exception):
    def __init__(self, status, code, detail):
        Exception.__init__(self, detail)
        self.status, self.code, self.detail = status, code, detail


def ensure_storage():
    if not os.path.isdir(ROOT):
        raise ApiError(503, "storage_unavailable", "Shared games directory unavailable")
    if os.path.islink(FILES_ROOT):
        raise ApiError(503, "storage_unavailable", "ROMs folder must not be a symlink")
    if not os.path.exists(FILES_ROOT):
        os.mkdir(FILES_ROOT)
    if not os.path.isdir(FILES_ROOT):
        raise ApiError(503, "storage_unavailable", "ROMs folder unavailable")


def safe_path(value, must_exist=True):
    """Only ROMs paths, no traversal, hidden files, or symlink components."""
    if not isinstance(value, str) or len(value) > 512:
        raise ApiError(400, "invalid_path", "Invalid path")
    parts = value.split("/") if value else []
    for part in parts:
        if part in ("", ".", "..") or part.startswith(".") or not SEGMENT.match(part):
            raise ApiError(400, "invalid_path", "Invalid path component")
    ensure_storage()
    path = FILES_ROOT
    for part in parts:
        path = os.path.join(path, part)
        if os.path.islink(path):
            raise ApiError(400, "invalid_path", "Symbolic links are not supported")
    actual = os.path.realpath(path)
    if actual != FILES_ROOT and not actual.startswith(FILES_ROOT + os.sep):
        raise ApiError(400, "invalid_path", "Path escapes ROM storage")
    if must_exist and not os.path.exists(path):
        raise ApiError(404, "not_found", "File or directory not found")
    return path


def sanitized_filename(value):
    if not isinstance(value, str):
        value = ""
    value = os.path.splitext(value.strip())[0]
    value = FILE_STEM.sub("_", value).strip(" ._")
    return (value or "SNES-Dump")[:64]


def wifi_args(*args):
    if not os.path.isfile(WLAN_BIN):
        raise ApiError(503, "wifi_unavailable", "WLAN helper unavailable")
    prefix = ["sudo", "-n"] if RUN_SUDO else []
    return prefix + [WLAN_BIN] + list(args)


def call_wlan(*args):
    try:
        proc = subprocess.Popen(wifi_args(*args), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise ApiError(504, "wifi_timeout", "WLAN helper timed out")
    except OSError:
        raise ApiError(503, "wifi_unavailable", "WLAN helper cannot be started")
    if proc.returncode:
        raise ApiError(502, "wifi_failed", (err or out).decode("utf-8", "replace")[:200])
    return out.decode("utf-8", "replace").strip()


def wifi_status():
    raw = call_wlan("status")
    if raw == "no WLAN interface":
        return {"available": False, "connected": False}
    # Legacy retrode3-wlan output: status,ssid,ap,mac,ipv4,ipv6
    fields = (raw.split(",", 5) + [""] * 6)[:6]
    return {"available": True, "connected": fields[0] == "connected",
            "ssid": fields[1], "access_point": fields[2], "mac": fields[3],
            "ipv4": fields[4], "ipv6": fields[5]}


def wifi_scan():
    lines = call_wlan("list").splitlines()
    networks = []
    for line in lines:
        match = re.match(r"^\s*([0-9a-fA-F:]{17})\s+(.+?)\s+(\d{4})\s+(-?\d+(?:\.\d+)?)", line)
        if match:
            networks.append({"bssid": match.group(1), "ssid": match.group(2),
                             "mhz": int(match.group(3)), "dbm": float(match.group(4))})
    return sorted(networks, key=lambda n: n["dbm"], reverse=True)


def capability_probe():
    """Ask the real executable. Do not advertise hypothetical cores."""
    if not os.path.isfile(SNES_BIN) or not os.access(SNES_BIN, os.X_OK):
        return {"systems": [{"id": "snes", "available": False,
                              "reason": "native_binary_missing"}]}
    proc = None
    try:
        proc = subprocess.Popen([SNES_BIN, "--protocol", "ndjson-v1", "--interactive"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        deadline = time.time() + 5.0
        ready = False
        while time.time() < deadline:
            if not select.select([proc.stdout], [], [], 0.2)[0]:
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            event = json.loads(line.decode("utf-8"))
            if event.get("event") == "ready":
                ready = True
                break
        if not ready:
            raise ValueError("no ready event")
        proc.stdin.write(b'{"command":"get_capabilities","request_id":"webcap"}\n')
        proc.stdin.flush()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not select.select([proc.stdout], [], [], 0.2)[0]:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            event = json.loads(line.decode("utf-8"))
            if event.get("event") == "capabilities" and event.get("request_id") == "webcap":
                return {"systems": [{"id": "snes", "available": True,
                                     "capabilities": event}]}
    except (OSError, ValueError, KeyError):
        pass
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait()
                except OSError:
                    pass
            proc.stdout.close()
    return {"systems": [{"id": "snes", "available": False,
                          "reason": "native_protocol_unavailable"}]}


class Job(object):
    def __init__(self, manager, action, mapping, size, label):
        self.manager = manager
        self.id = uuid.uuid4().hex
        self.action = action
        self.mapping = mapping
        self.size = size
        self.label = label
        self.output = None
        self.status = "queued"
        self.events = []
        self.progress = None
        self.result = None
        self.error = None
        self.created = time.time()
        self.process = None
        self.cancel_requested = False
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "command": self.action, "system": "snes",
                    "status": self.status, "events": self.events[-32:],
                    "progress": self.progress, "result": self.result,
                    "error": self.error, "output": self.output, "created": self.created}

    def cancel(self):
        with self.lock:
            if self.status in ("done", "cancelled", "failed"):
                return
            self.cancel_requested = True
            if self.process is not None and self.status == "running":
                self._send({"command": "cancel", "request_id": self.id})
                self.status = "cancelling"

    def _send(self, obj):
        try:
            self.process.stdin.write((json.dumps(obj, separators=(",", ":")) + "\n").encode("ascii"))
            self.process.stdin.flush()
        except (OSError, ValueError, IOError) as error:
            raise ApiError(502, "process_io", str(error))

    def run(self):
        with self.manager.bus_lock:
            process = None
            try:
                with self.lock:
                    if self.cancel_requested:
                        self.status = "cancelled"
                        return
                    self.status = "running"
                if self.action == "read_rom":
                    ensure_storage()
                    system_folder = safe_path("SNES", must_exist=False)
                    if not os.path.exists(system_folder):
                        os.mkdir(system_folder)
                    filename = "%s-%s.sfc" % (self.label, self.id[:8])
                    self.output = os.path.join(system_folder, filename)
                process = subprocess.Popen([SNES_BIN, "--protocol", "ndjson-v1", "--interactive"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL)
                with self.lock:
                    self.process = process
                deadline = time.time() + 900
                sent = False
                while time.time() < deadline:
                    if process.poll() is not None and not select.select([process.stdout], [], [], 0)[0]:
                        raise ApiError(502, "process_exited", "Native reader exited unexpectedly")
                    if not select.select([process.stdout], [], [], 0.3)[0]:
                        continue
                    line = process.stdout.readline()
                    if not line:
                        raise ApiError(502, "process_exited", "Native reader closed stdout")
                    if len(line) > 65536:
                        raise ApiError(502, "protocol_failure", "Oversized native event")
                    event = json.loads(line.decode("utf-8"))
                    kind = event.get("event")
                    if kind == "ready" and not sent:
                        with self.lock:
                            if self.cancel_requested:
                                self.status = "cancelled"
                                return
                            command = {"command": self.action, "request_id": self.id}
                            if self.action == "read_rom":
                                command["output"] = self.output
                                if self.mapping:
                                    command["mapping"] = self.mapping
                                if self.size:
                                    command["size_bytes"] = self.size
                            self._send(command)
                            sent = True
                        continue
                    if not sent:
                        continue
                    if kind not in ("error", "progress", "probe_result", "result"):
                        continue
                    # Some parser errors have no request_id; do not associate
                    # unrelated valid IDs with our running operation.
                    event_id = event.get("request_id")
                    if event_id and event_id != self.id:
                        continue
                    with self.lock:
                        self.events.append(event)
                        self.events = self.events[-32:]
                        if kind == "progress":
                            self.progress = event
                        elif kind == "probe_result" and self.action == "probe":
                            self.result = event
                            self.status = "done"
                        elif kind == "result" and self.action == "read_rom":
                            if not event.get("ok") or event.get("output") != self.output:
                                raise ApiError(502, "invalid_result", "Unexpected native output")
                            self.result = event
                            self.status = "done"
                        elif kind == "error":
                            self.error = {"code": event.get("code", "operation_failed")}
                            self.status = "cancelled" if event.get("code") == "cancelled" else "failed"
                        if self.status in ("done", "cancelled", "failed"):
                            return
                raise ApiError(504, "operation_timeout", "Reader did not finish in 15 minutes")
            except ApiError as error:
                with self.lock:
                    self.error = {"code": error.code, "message": error.detail}
                    self.status = "failed"
            except (OSError, ValueError, KeyError, IOError) as error:
                with self.lock:
                    self.error = {"code": "operation_failed", "message": str(error)}
                    self.status = "failed"
            finally:
                if process is not None:
                    with self.lock:
                        self.process = None
                    try:
                        process.stdin.close()
                        process.terminate()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            process.kill()
                            process.wait()
                        except OSError:
                            pass
                    process.stdout.close()
                with self.manager.lock:
                    if self.manager.active is self:
                        self.manager.active = None


class JobManager(object):
    def __init__(self):
        self.jobs = {}
        self.active = None
        self.lock = threading.RLock()
        self.bus_lock = threading.Lock()

    def submit(self, data):
        if data.get("system") != "snes" or data.get("command") not in ("probe", "read_rom"):
            raise ApiError(400, "unsupported", "Only SNES probe/read_rom supported")
        mapping = data.get("mapping")
        size = data.get("size_bytes")
        if mapping is not None and mapping not in ("lo", "hi"):
            raise ApiError(400, "invalid_mapping", "Mapping must be lo or hi")
        if size is not None:
            if type(size) is not int or size < 131072 or size > 4194304:
                raise ApiError(400, "invalid_size", "Size must be 128 KiB to 4 MiB")
            if size % (65536 if mapping == "hi" else 32768):
                raise ApiError(400, "invalid_size", "Size incompatible with mapping")
        if data["command"] == "probe" and (mapping is not None or size is not None):
            raise ApiError(400, "invalid_command", "Probe does not accept overrides")
        if not os.path.isfile(SNES_BIN) or not os.access(SNES_BIN, os.X_OK):
            raise ApiError(503, "native_binary_missing", "Native SNES reader unavailable")
        job = Job(self, data["command"], mapping, size, sanitized_filename(data.get("filename")))
        with self.lock:
            if self.active is not None:
                raise ApiError(409, "busy", "Cartridge reader already busy")
            if len(self.jobs) >= 50:
                old = sorted((j for j in self.jobs.values() if j is not self.active),
                             key=lambda j: j.created)
                if old:
                    del self.jobs[old[0].id]
            self.jobs[job.id] = job
            self.active = job
        thread = threading.Thread(target=job.run)
        thread.daemon = True
        thread.start()
        return job.snapshot()

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "not_found", "Job not found")
        return job


MANAGER = JobManager()


class ThreadedServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "Retrode3-WebBackend/0.1"

    def _json(self, status, data):
        encoded = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "invalid_json", "Invalid content length")
        if length <= 0 or length > MAX_BODY:
            raise ApiError(413, "invalid_json", "Invalid JSON body size")
        try:
            result = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "invalid_json", "Invalid JSON")
        if not isinstance(result, dict):
            raise ApiError(400, "invalid_json", "JSON object required")
        return result

    def _query(self, url, key):
        return parse_qs(url.query).get(key, [""])[0]

    def _files(self, folder):
        base = safe_path(folder)
        if not os.path.isdir(base):
            raise ApiError(400, "not_directory", "Not a directory")
        result = []
        for name in os.listdir(base):
            if name.startswith(".") or not SEGMENT.match(name):
                continue
            rel = (folder + "/" if folder else "") + name
            try:
                path = safe_path(rel)
                st = os.stat(path)
            except (ApiError, OSError):
                continue
            if not (os.path.isdir(path) or os.path.isfile(path)):
                continue
            result.append({"name": name, "path": rel, "directory": os.path.isdir(path),
                           "size": st.st_size if os.path.isfile(path) else None,
                           "modified": int(st.st_mtime)})
        result.sort(key=lambda x: (not x["directory"], x["name"].lower()))
        return {"path": folder, "items": result}

    def _download(self, rel):
        path = safe_path(rel)
        if not os.path.isfile(path):
            raise ApiError(400, "not_file", "Not a regular file")
        # Refuse symlinks and only open read-only file descriptors.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            st = os.fstat(fd)
            import stat
            if not stat.S_ISREG(st.st_mode):
                raise ApiError(400, "not_file", "Not a regular file")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("X-Content-Type-Options", "nosniff")
            filename = os.path.basename(path).replace('"', "_")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" +
                             quote(filename, safe=""))
            self.end_headers()
            with os.fdopen(fd, "rb") as fh:
                fd = None
                while True:
                    block = fh.read(65536)
                    if not block:
                        break
                    self.wfile.write(block)
        finally:
            if fd is not None:
                os.close(fd)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            path = url.path
            if path == "/api/health":
                self._json(200, {"ok": True, "service": "retrode3-web-v2"})
            elif path == "/api/capabilities":
                self._json(200, capability_probe())
            elif path == "/api/settings":
                self._json(200, {"time": datetime.datetime.now().isoformat(),
                                 "timezone": time.tzname[time.daylight and time.localtime().tm_isdst > 0]})
            elif path == "/api/wifi/status":
                self._json(200, wifi_status())
            elif path == "/api/wifi/scan":
                self._json(200, {"networks": wifi_scan()})
            elif path.startswith("/api/jobs/") and re.match(r"^/api/jobs/[0-9a-f]{32}$", path):
                self._json(200, MANAGER.get(path.split("/")[-1]).snapshot())
            elif path == "/api/files":
                self._json(200, self._files(self._query(url, "path")))
            elif path == "/api/files/download":
                self._download(self._query(url, "path"))
            else:
                raise ApiError(404, "not_found", "Unknown endpoint")
        except ApiError as error:
            self._json(error.status, {"error": error.code, "message": error.detail})
        except OSError as error:
            self._json(503, {"error": "io_error", "message": str(error)})

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            data = self._body()
            if path == "/api/jobs":
                self._json(202, MANAGER.submit(data))
            elif re.match(r"^/api/jobs/[0-9a-f]{32}/cancel$", path):
                job = MANAGER.get(path.split("/")[-2])
                job.cancel()
                self._json(200, job.snapshot())
            elif path == "/api/files/mkdir":
                rel = data.get("path", "")
                if not rel:
                    raise ApiError(400, "invalid_path", "Root already exists")
                dest = safe_path(rel, must_exist=False)
                if not os.path.isdir(os.path.dirname(dest)):
                    raise ApiError(400, "invalid_path", "Parent must exist")
                os.mkdir(dest)
                self._json(200, {"ok": True})
            elif path == "/api/files/move":
                src = data.get("source", "")
                dest = data.get("destination", "")
                if not src or not dest:
                    raise ApiError(400, "invalid_path", "Source and destination required")
                source = safe_path(src)
                destination = safe_path(dest, must_exist=False)
                if os.path.exists(destination):
                    raise ApiError(409, "exists", "Destination exists")
                if not os.path.isdir(os.path.dirname(destination)):
                    raise ApiError(400, "invalid_path", "Destination folder missing")
                if destination.startswith(source + os.sep):
                    raise ApiError(400, "invalid_path", "Cannot move folder into itself")
                os.rename(source, destination)
                self._json(200, {"ok": True})
            elif path == "/api/files/delete":
                rel = data.get("path", "")
                if not rel:
                    raise ApiError(400, "invalid_path", "Cannot remove storage root")
                target = safe_path(rel)
                if os.path.isdir(target):
                    os.rmdir(target)  # Only empty folders. Never recursive.
                else:
                    os.unlink(target)
                self._json(200, {"ok": True})
            elif path == "/api/wifi/connect":
                ssid = data.get("ssid", "")
                password = data.get("password", "")
                if not isinstance(ssid, str) or not (1 <= len(ssid) <= 32) or "\x00" in ssid:
                    raise ApiError(400, "invalid_ssid", "SSID must contain 1-32 characters")
                if not isinstance(password, str) or len(password) > 128 or "\x00" in password:
                    raise ApiError(400, "invalid_password", "Invalid password")
                args = ["connect"]
                if password:
                    args += ["-p", password]
                args.append(ssid)
                self._json(200, {"message": call_wlan(*args)})
            elif path == "/api/wifi/disconnect":
                self._json(200, {"message": call_wlan("disconnect")})
            else:
                raise ApiError(404, "not_found", "Unknown endpoint")
        except ApiError as error:
            self._json(error.status, {"error": error.code, "message": error.detail})
        except (OSError, ValueError, TypeError) as error:
            self._json(400, {"error": "operation_failed", "message": str(error)})

    def log_message(self, fmt, *args):
        # Never log POST bodies: WLAN passwords may be present.
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadedServer((HOST, args.port), Handler)
    print("Retrode3 v2 backend listening on %s:%s" % (HOST, server.server_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
