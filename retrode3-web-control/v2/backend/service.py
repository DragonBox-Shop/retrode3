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
import socket
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
MD_BIN = os.environ.get("RETRODE3_MD_BINARY", "/usr/local/bin/oscr-md-native")
SENSE_ROOT = os.environ.get("RETRODE3_SYSFS_ROOT", "/sys/class/retrode3")

CLI_BIN = os.environ.get("RETRODE3_CLI_BINARY", "/usr/local/bin/retrode3-cli")
CORECTL_BIN = os.environ.get("RETRODE3_CORECTL_BINARY", "/usr/sbin/retrode3-corectl")
CORE_CONTROL_ENABLED = os.environ.get("RETRODE3_CORE_CONTROL_ENABLED", "0") == "1"
CORECTL_SUDO = os.environ.get("RETRODE3_CORECTL_SUDO", "1") == "1"
CORE_ID = re.compile(r"^[a-z0-9_-]{1,48}$")

# Compatibility for old *standalone* acceptance readers when the central
# CLI has not been installed. This is NEVER an allowlist for CLI plugins.
LEGACY_READERS = {
    "snes": {"name": "Super Nintendo (SNES)", "slot": "snes",
             "binary": SNES_BIN, "folder": "SNES", "extension": "sfc"},
    "md": {"name": "Mega Drive / Genesis", "slot": "md",
           "binary": MD_BIN, "folder": "MD", "extension": "md"},
}
# Cosmetic, familiar labels only. New physical kernel slots still show up.
PHYSICAL_SLOTS = (("md", "Mega Drive"), ("snes", "Super Nintendo"),
                  ("nes", "Nintendo / Famicom"))
# File format defaults are NOT a reader allowlist; unknown core IDs work
# and use .bin until the CLI reports a ROM file extension.
KNOWN_ROM_EXTENSIONS = {"snes": "sfc", "md": "md", "nes": "nes"}
WLAN_BIN = os.environ.get("RETRODE3_WLAN_BINARY", "/usr/local/bin/retrode3-wlan")
NET_SYSFS_ROOT = os.environ.get("RETRODE3_NET_SYSFS_ROOT", "/sys/class/net")
RUN_SUDO = os.environ.get("RETRODE3_WLAN_SUDO", "1") == "1"
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


def wireless_interfaces():
    """Find WLAN devices without relying on the legacy iwconfig grep.

    This does not change interface state and works when WLAN is down.
    /sys/class/net/wlan*/phy80211 and iw dev are intentionally read-only.
    """
    found = set()
    if os.path.isdir(NET_SYSFS_ROOT):
        try:
            for name in os.listdir(NET_SYSFS_ROOT):
                if (os.path.exists(os.path.join(NET_SYSFS_ROOT, name, "phy80211"))
                        or os.path.isdir(os.path.join(NET_SYSFS_ROOT, name, "wireless"))):
                    found.add(name)
        except OSError:
            pass
    proc = None
    try:
        proc = subprocess.Popen(["iw", "dev"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, _ = proc.communicate(timeout=5)
        if proc.returncode == 0:
            for match in re.findall(r"^\s*Interface\s+(\S+)\s*$",
                                    out.decode("utf-8", "replace"), re.MULTILINE):
                if re.match(r"^[A-Za-z0-9_.-]{1,32}$", match):
                    found.add(match)
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            proc.communicate()
    except OSError:
        pass
    return sorted(found)


def wireless_link(interface):
    """Optional association and SSID hints; failures remain unknown, not absent."""
    proc = None
    try:
        proc = subprocess.Popen(["iw", "dev", interface, "link"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = proc.communicate(timeout=5)
        if proc.returncode != 0:
            return {}
        raw = out.decode("utf-8", "replace")
        connected = "Connected to " in raw
        match = re.search(r"^\s*SSID:\s*(.*)$", raw, re.MULTILINE)
        return {"associated": connected, "ssid": match.group(1) if match else ""}
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            proc.communicate()
    except OSError:
        pass
    return {}


def interface_ipv4(interface):
    """Read IPv4 via old Debian iproute2 or net-tools, without extra privileges."""
    for argv in (["ip", "-4", "addr", "show", "dev", interface],
                 ["ifconfig", interface]):
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = proc.communicate(timeout=4)
            if proc.returncode:
                continue
            raw = out.decode("utf-8", "replace")
            match = re.search(r"\binet(?: addr:|\s+)(\d{1,3}(?:\.\d{1,3}){3})\b", raw)
            if match:
                return match.group(1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        except OSError:
            continue
    return ""


def wifi_status():
    """Detect hardware independently of the legacy helper's iwconfig grep."""
    interfaces = wireless_interfaces()
    details = {}
    helper_missing_interface = False
    helper_failed = False
    try:
        raw = call_wlan("status")
        if raw == "no WLAN interface":
            helper_missing_interface = True
        else:
            # Legacy format: connected,ssid,ap,mac,ipv4,ipv6
            fields = (raw.split(",", 5) + [""] * 6)[:6]
            if fields[0] in ("connected", "disconnected"):
                details = {"connected": fields[0] == "connected",
                           "ssid": fields[1], "access_point": fields[2],
                           "mac": fields[3], "ipv4": fields[4],
                           "ipv6": fields[5]}
            else:
                helper_failed = True
    except ApiError:
        helper_failed = True
    available = bool(interfaces) or bool(details)
    interface = interfaces[0] if interfaces else None
    link = wireless_link(interface) if interface else {}
    if not details.get("ssid") and link.get("ssid"):
        details["ssid"] = link["ssid"]
    if interface and not details.get("ipv4"):
        details["ipv4"] = interface_ipv4(interface)
    if interface and details.get("ipv4") and link.get("associated"):
        details["connected"] = True
    details.update({"available": available, "interface": interface,
                    "interfaces": interfaces,
                    "connected": bool(details.get("connected", False)),
                    "associated": link.get("associated")})
    if not available:
        details["reason"] = "no_wireless_interface_detected"
    elif helper_missing_interface:
        details["warning"] = "legacy_helper_does_not_detect_interface"
    elif helper_failed:
        details["warning"] = "legacy_helper_unavailable"
    return details


def wifi_scan():
    lines = call_wlan("list").splitlines()
    networks = []
    for line in lines:
        match = re.match(r"^\s*([0-9a-fA-F:]{17})\s+(.+?)\s+(\d{4})\s+(-?\d+(?:\.\d+)?)", line)
        if match:
            networks.append({"bssid": match.group(1), "ssid": match.group(2),
                             "mhz": int(match.group(3)), "dbm": float(match.group(4))})
    return sorted(networks, key=lambda n: n["dbm"], reverse=True)


def slot_snapshot():
    """Passive, safe inspection: never touch cartridge data or switch voltage.

    'occupied' is a kernel sense indication, NOT a system/adapter identity.
    An adapter may not expose a working sense line; unknown stays unknown.
    """
    slots = []
    # Known names are presentation labels, not plugin admission rules.
    names = dict(PHYSICAL_SLOTS)
    try:
        for entry in os.listdir(SENSE_ROOT):
            if entry.startswith("slot-") and CORE_ID.match(entry[5:]):
                names.setdefault(entry[5:], entry[5:].replace("_", " ").upper())
    except OSError:
        pass
    labels = dict(PHYSICAL_SLOTS)
    ordered = list(PHYSICAL_SLOTS) + sorted((slot_id, name) for slot_id, name in names.items()
                                            if slot_id not in labels)
    for slot_id, name in ordered:
        sense_file = os.path.join(SENSE_ROOT, "slot-" + slot_id, "sense")
        state = "unavailable" if not os.path.exists(sense_file) else "unknown"
        if state != "unavailable":
            try:
                with open(sense_file, "r") as handle:
                    raw = handle.read(40).strip().lower()
                if raw == "active":
                    state = "occupied"
                elif raw == "empty":
                    state = "empty"
            except (IOError, OSError):
                state = "unknown"
        slots.append({"id": slot_id, "name": name, "status": state,
                      "detected_system": None, "adapter_id": None,
                      "detection": "kernel_sense_only"})
    return {"slots": slots}



def core_registry():
    """Obtain inventory from the central CLI; do not inspect plugin files."""
    missing = {"available": False, "control_enabled": False, "cores": [],
               "reason": "cli_missing"}
    if not os.path.isfile(CLI_BIN):
        return missing
    if not os.access(CLI_BIN, os.X_OK):
        missing["reason"] = "cli_not_executable"
        return missing
    try:
        proc = subprocess.Popen([CLI_BIN, "--list-cores", "--protocol", "ndjson-v1"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        try:
            out, unused = proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ApiError(504, "core_timeout", "CLI discovery timed out")
    except OSError:
        raise ApiError(503, "cli_unavailable", "CLI cannot start")
    if proc.returncode != 0 or len(out) > 262144:
        raise ApiError(502, "core_discovery_failed", "CLI discovery failed")
    try:
        lines = out.decode("utf-8").splitlines()
        if len(lines) != 1:
            raise ValueError("Expected one event")
        event = json.loads(lines[0])
        if (not isinstance(event, dict) or event.get("protocol") != PROTOCOL or
                type(event.get("version")) is not int or event["version"] != 1 or
                event.get("event") != "cores" or event.get("discovery_abi") != 1 or
                not isinstance(event.get("cores"), list) or len(event["cores"]) > 128):
            raise ValueError("Unexpected CLI protocol")
        cores = []
        seen = set()
        for c in event["cores"]:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not CORE_ID.match(c["id"]) or c["id"] in seen:
                raise ValueError("Invalid core ID")
            seen.add(c["id"])
            for field in ("name", "version", "slot", "status"):
                val = c.get(field)
                if (not isinstance(val, str) or not val or len(val) > 128 or
                        any(ord(ch) < 32 or ord(ch) == 127 for ch in val)):
                    raise ValueError("Invalid core metadata")
            if not CORE_ID.match(c["slot"]):
                raise ValueError("Invalid core slot")
            if any(type(c.get(k)) is not bool for k in ("installed", "enabled", "usable")):
                raise ValueError("Invalid core flags")
            actions = c.get("actions")
            if not isinstance(actions, list) or any(not isinstance(a, str) or not CORE_ID.match(a) for a in actions):
                raise ValueError("Invalid core actions")
            cores.append(dict((key, c[key]) for key in
                              ("id", "name", "version", "slot", "status",
                               "installed", "enabled", "usable", "actions")))
    except (ValueError, KeyError, UnicodeError, TypeError):
        raise ApiError(502, "core_protocol_invalid", "CLI inventory protocol mismatch")
    return {"available": True, "source": "retrode3-cli",
            "control_enabled": CORE_CONTROL_ENABLED and
                               os.path.isfile(CORECTL_BIN) and os.access(CORECTL_BIN, os.X_OK),
            "cores": cores}


def toggle_core(data):
    """Allow only a known installed core ID; no arbitrary shell or path input."""
    if not CORE_CONTROL_ENABLED:
        raise ApiError(403, "core_control_disabled", "Core control not enabled")
    if (set(data.keys()) != set(("id", "enabled")) or
            not isinstance(data.get("id"), str) or not CORE_ID.match(data["id"]) or
            type(data.get("enabled")) is not bool):
        raise ApiError(400, "invalid_core_request", "Invalid core toggle request")
    with MANAGER.lock:
        if MANAGER.active is not None or not MANAGER.bus_lock.acquire(False):
            raise ApiError(409, "busy", "Hardware job or core change running")
    try:
        inv = core_registry()
        if not inv["available"] or not inv["control_enabled"]:
            raise ApiError(503, "core_control_unavailable", "CLI/helper missing")
        found = [c for c in inv["cores"] if c["id"] == data["id"] and c["installed"]]
        if not found:
            raise ApiError(404, "core_not_found", "Core is not installed")
        current = found[0]
        enabled = data["enabled"]
        if current["enabled"] == enabled:
            return {"ok": True, "core": current}
        if enabled and current["status"] != "disabled":
            raise ApiError(409, "core_invalid_state", "Core cannot be enabled")
        if not enabled and current["status"] not in ("ready", "discovered", "incompatible"):
            raise ApiError(409, "core_invalid_state", "Core link requires repair")
        cmd = [CORECTL_BIN, "enable" if enabled else "disable", data["id"]]
        if CORECTL_SUDO:
            cmd = ["sudo", "-n"] + cmd
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise ApiError(504, "core_control_timeout", "Core helper timed out")
        except OSError:
            raise ApiError(503, "core_control_unavailable", "Cannot start core helper")
        if proc.returncode != 0:
            raise ApiError(502, "core_control_failed", "Core helper rejected request")
        updated = core_registry()
        after = [c for c in updated["cores"] if c["id"] == data["id"]]
        if not after or after[0]["enabled"] != enabled:
            raise ApiError(409, "core_state_mismatch", "CLI did not confirm the new state")
        return {"ok": True, "core": after[0]}
    finally:
        MANAGER.bus_lock.release()


def reader_capability(core_id, registry=None):
    """Derive any reader from CLI metadata without an ID allowlist.

    In particular, neither a recognized device slot nor an installed .so
    implies an executable ROM operation. Only `ready`, usable, enabled
    and explicit CLI actions can open a cartridge.
    """
    if registry is None:
        registry = core_registry()
    if registry["available"]:
        core = next((item for item in registry["cores"]
                     if item["id"] == core_id), None)
        if core is None:
            return None
        result = {"id": core["id"], "name": core["name"], "slot": core["slot"],
                  "available": False, "transport": "cli",
                  "folder": core["id"].upper(),
                  "extension": KNOWN_ROM_EXTENSIONS.get(core["id"], "bin")}
        if not (core["installed"] and core["enabled"] and
                core["status"] == "ready" and core["usable"]):
            result["reason"] = "core_not_ready"
            return result
        commands = [action for action in ("probe", "read_rom")
                    if action in core["actions"]]
        if not commands:
            result["reason"] = "core_operation_unavailable"
            return result
        result.update({"available": True,
                       "capabilities": {
                           "system": core["id"], "core": core["id"],
                           "slot": core["slot"], "commands": commands,
                           "mappings": [], "size_override": False,
                           "database_lookup": False,
                           "write_operations": False}})
        return result
    # Only while the central CLI is absent: old proven native NDJSON runner.
    spec = LEGACY_READERS.get(core_id)
    if spec is None:
        return None
    result = {"id": core_id, "name": spec["name"], "slot": spec["slot"],
              "folder": spec["folder"], "extension": spec["extension"],
              "binary": spec["binary"], "transport": "legacy",
              "available": False}
    binary = spec["binary"]
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        result["reason"] = "native_binary_missing"
        return result
    proc = None
    try:
        proc = subprocess.Popen([binary, "--protocol", "ndjson-v1", "--interactive"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)
        deadline = time.time() + 3.0
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
            if (event.get("event") == "ready" and
                    event.get("protocol") == PROTOCOL and
                    event.get("version") == 1 and
                    event.get("system") == core_id):
                ready = True
                break
        if not ready:
            raise ValueError("no compatible ready event")
        proc.stdin.write(b'{"command":"get_capabilities","request_id":"webcap"}\n')
        proc.stdin.flush()
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if not select.select([proc.stdout], [], [], 0.2)[0]:
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            event = json.loads(line.decode("utf-8"))
            commands = event.get("commands")
            if (event.get("protocol") == PROTOCOL and
                    event.get("version") == 1 and
                    event.get("event") == "capabilities" and
                    event.get("request_id") == "webcap" and
                    event.get("system") == core_id and
                    isinstance(commands, list) and
                    all(x in commands for x in (
                        "get_capabilities", "probe", "read_rom", "cancel"))):
                result.update({"available": True, "capabilities": event})
                return result
    except (OSError, ValueError, KeyError, IOError):
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
    result["reason"] = "native_protocol_unavailable"
    return result


def capability_probe():
    """Every CLI-listed core, including unknown future systems and plugins."""
    registry = core_registry()
    ids = ([item["id"] for item in registry["cores"]]
           if registry["available"] else list(LEGACY_READERS))
    return {"systems": [reader_capability(core_id, registry) for core_id in ids]}




class Job(object):
    def __init__(self, manager, reader_id, action, mapping, size, label,
                 reader, automatic=False):
        self.manager = manager
        self.reader_id = reader_id
        self.reader = reader
        self.transport = reader["transport"]
        self.automatic = automatic
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
            return {"id": self.id, "command": self.action, "system": self.reader_id,
                    "automatic": self.automatic,
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
                    system_folder = safe_path(self.reader["folder"], must_exist=False)
                    if not os.path.exists(system_folder):
                        os.mkdir(system_folder)
                    filename = "%s-%s.%s" % (self.label, self.id[:8], self.reader["extension"])
                    self.output = os.path.join(system_folder, filename)
                argv = ([CLI_BIN, "--protocol", "ndjson-v1", "--interactive"]
                        if self.transport == "cli" else
                        [self.reader["binary"], "--protocol", "ndjson-v1", "--interactive"])
                process = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, bufsize=0)
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
                    if (kind == "ready" and not sent and
                            event.get("protocol") == PROTOCOL and
                            event.get("version") == 1 and
                            event.get("system") == (
                                "multi" if self.transport == "cli" else self.reader_id)):
                        with self.lock:
                            if self.cancel_requested:
                                self.status = "cancelled"
                                return
                            command = {"command": self.action, "request_id": self.id}
                            if self.transport == "cli":
                                command["core"] = self.reader_id
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

    def submit(self, data, automatic=False):
        reader_id = data.get("system")
        if (not isinstance(reader_id, str) or not CORE_ID.match(reader_id) or
                data.get("command") not in ("probe", "read_rom")):
            raise ApiError(400, "unsupported", "Unknown reader or unsupported command")
        mapping = data.get("mapping")
        size = data.get("size_bytes")
        # Validate input before invoking any process or touching hardware.
        if mapping is not None and (not isinstance(mapping, str) or len(mapping) > 32):
            raise ApiError(400, "invalid_mapping", "Invalid mapping")
        if size is not None:
            if type(size) is not int or size < 131072 or size > 4194304:
                raise ApiError(400, "invalid_size", "Invalid ROM size")
            if reader_id == "snes" and size % (65536 if mapping == "hi" else 32768):
                raise ApiError(400, "invalid_size", "SNES ROM size incompatible with mapping")
            if reader_id == "md" and size % 2:
                raise ApiError(400, "invalid_size", "MegaDrive ROM size must be even")
        if data["command"] == "probe" and (mapping is not None or size is not None):
            raise ApiError(400, "invalid_command", "Probe does not accept overrides")
        cap = reader_capability(reader_id)
        if cap is None:
            raise ApiError(400, "unsupported", "Core not registered by CLI")
        if not cap["available"]:
            raise ApiError(503, "native_protocol_unavailable",
                           "A compatible native reader is not installed")
        features = cap["capabilities"]
        if data["command"] not in features["commands"]:
            raise ApiError(400, "unsupported", "Command unavailable for this reader")
        if mapping is not None and mapping not in features.get("mappings", []):
            raise ApiError(400, "invalid_mapping", "Mapping not offered by this reader")
        if size is not None and not features.get("size_override", False):
            raise ApiError(400, "invalid_size", "ROM size override unavailable")
        if size is not None and size > features.get("max_rom_bytes", 4194304):
            raise ApiError(400, "invalid_size", "ROM size exceeds reader capabilities")
        job = Job(self, reader_id, data["command"], mapping, size,
                  sanitized_filename(data.get("filename")),
                  cap, automatic=automatic)
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

    def current(self):
        with self.lock:
            job = self.active
            if job is None and self.jobs:
                job = max(self.jobs.values(), key=lambda j: j.created)
        return job.snapshot() if job else {"status": "idle"}

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "not_found", "Job not found")
        return job


MANAGER = JobManager()

class AutomaticDetection(object):
    """Keep cartridge identity in the backend, independent of browser sessions.

    Linux slot uevents wake the worker, but every decision is verified
    against passive kernel sense sysfs, never against untrusted event text.
    A periodic reconciliation also handles lost events or absent netlink.
    All probes are submitted through the same serialized JobManager as
    manually requested ROM reads; no second raw device reader exists.
    """
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.RLock()
        self.records = {}
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        worker = threading.Thread(target=self._watch)
        worker.daemon = True
        worker.start()

    def reset(self):
        """Re-evaluate installed/disabled cores after a registry change."""
        with self.lock:
            for slot_id, record in list(self.records.items()):
                if record["state"] == "detecting":
                    try:
                        self.manager.get(record["job_id"]).cancel()
                    except ApiError:
                        pass
                del self.records[slot_id]

    def _cancel_removed_slot(self, slot_id):
        # Only a confirmed physical removal may interrupt a manual read.
        sense = next((s for s in slot_snapshot()["slots"] if s["id"] == slot_id), None)
        if not sense or sense["status"] != "empty":
            return
        with self.manager.lock:
            active = self.manager.active
        if active is not None and active.reader["slot"] == slot_id:
            active.cancel()

    def _event_changed(self, payload):
        """Invalidate cached identity on KOBJ_CHANGE even for rapid swaps.

        The event only invalidates. The sysfs sense must be reread
        before probing, so no event can choose a voltage or core.
        """
        if len(payload) > 16384:
            return
        values = {}
        for part in payload.split(b"\x00"):
            if b"=" in part:
                key, value = part.split(b"=", 1)
                if key in (b"SLOT", b"SENSE"):
                    values[key] = value
        name = values.get(b"SLOT", b"").decode("ascii", "ignore")
        sense = values.get(b"SENSE", b"").decode("ascii", "ignore")
        slot_id = name[5:] if name.startswith("slot-") else ""
        if not CORE_ID.match(slot_id) or sense not in ("active", "empty"):
            return
        if sense == "empty":
            self._cancel_removed_slot(slot_id)
        with self.lock:
            previous = self.records.pop(slot_id, None)
            if previous and previous["state"] == "detecting":
                try:
                    self.manager.get(previous["job_id"]).cancel()
                except ApiError:
                    pass

    def _watch(self):
        netlink = None
        try:
            # NETLINK_KOBJECT_UEVENT = 15; listen only for wakeups.
            # Some kernels restrict group joins; polling remains available.
            netlink = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15)
            netlink.bind((os.getpid(), 1))
            netlink.setblocking(False)
        except (OSError, AttributeError):
            if netlink is not None:
                netlink.close()
            netlink = None
        while self.running:
            try:
                self.tick()
            except Exception as error:
                sys.stderr.write("Retrode3 auto detect: %s\n" % error)
            if netlink is None:
                time.sleep(0.3)
            else:
                try:
                    ready, _, _ = select.select([netlink], [], [], 0.3)
                    if ready:
                        # Event only invalidates cached title, never selects a core.
                        self._event_changed(netlink.recv(16384))
                except (OSError, ValueError):
                    netlink.close()
                    netlink = None
        if netlink is not None:
            netlink.close()

    def tick(self, now=None):
        """One deterministic reconciliation tick; safe to unit-test."""
        now = time.time() if now is None else now
        slots = slot_snapshot()["slots"]
        with self.lock:
            for slot in slots:
                slot_id = slot["id"]
                status = slot["status"]
                record = self.records.get(slot_id)
                if record is None or record["presence"] != status:
                    if status == "empty" and record and record["presence"] == "occupied":
                        self._cancel_removed_slot(slot_id)
                    if record and record["state"] == "detecting":
                        try:
                            self.manager.get(record["job_id"]).cancel()
                        except ApiError:
                            pass
                    # A cartridge should be seated before any bus operation.
                    self.records[slot_id] = {
                        "presence": status,
                        "state": "pending" if status == "occupied" else "idle",
                        "ready_at": now + 0.35,
                        "job_id": None,
                        "core_id": None,
                        "result": None,
                        "error": None}
                    continue
                if status != "occupied":
                    continue
                if record["state"] == "detecting":
                    job = self.manager.get(record["job_id"]).snapshot()
                    if job["status"] == "done":
                        result = job.get("result") or {}
                        if (result.get("event") == "probe_result" and
                                result.get("system") == record["core_id"]):
                            record["result"] = dict((key, result.get(key)) for key in
                                                    ("title", "mapping", "size_bytes", "checksum")
                                                    if key in result)
                            record["state"] = "detected"
                            record["error"] = None
                        else:
                            record["state"] = "failed"
                            record["error"] = "invalid_probe_result"
                    elif job["status"] in ("failed", "cancelled"):
                        record["state"] = "failed"
                        record["error"] = (job.get("error") or {}).get("code", "probe_failed")
                elif record["state"] == "pending" and now >= record["ready_at"]:
                    try:
                        matches = [reader for reader in capability_probe()["systems"]
                                   if reader and reader["slot"] == slot_id and reader["available"]
                                   and "probe" in reader.get("capabilities", {}).get("commands", [])]
                    except ApiError as error:
                        record["state"] = "failed"
                        record["error"] = error.code
                        continue
                    if not matches:
                        record["state"] = "unavailable"
                        record["error"] = "no_available_core"
                        continue
                    if len(matches) > 1:
                        # GPIO sense does not identify an adapter. Do not
                        # guess which electrical protocol is present.
                        record["state"] = "choose_reader"
                        record["error"] = None
                        continue
                    core_id = matches[0]["id"]
                    try:
                        job = self.manager.submit(
                            {"system": core_id, "command": "probe"}, automatic=True)
                    except ApiError as error:
                        if error.status == 409:
                            # A manual or prior automatic job owns the bus.
                            continue
                        record["state"] = "unavailable" if error.status in (400, 503) else "failed"
                        record["error"] = error.code
                    else:
                        record["core_id"] = core_id
                        record["job_id"] = job["id"]
                        record["state"] = "detecting"

    def snapshot(self):
        # Always show the current kernel sense, even before the background
        # watcher processes a removal. Never show a title for a stale sense.
        result = slot_snapshot()
        with self.lock:
            for slot in result["slots"]:
                record = self.records.get(slot["id"])
                if record is not None and record["presence"] == slot["status"]:
                    slot["detection"] = {
                        "state": record["state"],
                        "core_id": record["core_id"],
                        "result": record["result"],
                        "error": record["error"]}
                else:
                    slot["detection"] = {
                        "state": "pending" if slot["status"] == "occupied" else "idle",
                        "core_id": None,
                        "result": None, "error": None}
        return result


AUTO = AutomaticDetection(MANAGER)



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
            elif path == "/api/cores":
                self._json(200, core_registry())
            elif path == "/api/slots":
                self._json(200, AUTO.snapshot())
            elif path == "/api/settings":
                self._json(200, {"time": datetime.datetime.now().isoformat(),
                                 "timezone": time.tzname[time.daylight and time.localtime().tm_isdst > 0]})
            elif path == "/api/wifi/status":
                self._json(200, wifi_status())
            elif path == "/api/wifi/scan":
                self._json(200, {"networks": wifi_scan()})
            elif path == "/api/jobs/active":
                self._json(200, MANAGER.current())
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
            elif path == "/api/cores/toggle":
                changed = toggle_core(data)
                AUTO.reset()
                self._json(200, changed)
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
    AUTO.start()
    print("Retrode3 v2 backend listening on %s:%s" % (HOST, server.server_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
