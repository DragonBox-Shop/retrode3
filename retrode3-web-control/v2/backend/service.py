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
SENSE_ROOT = os.environ.get("RETRODE3_SYSFS_ROOT", "/sys/class/retrode3")

CLI_BIN = "/usr/bin/retrode3-cli"
# Flash operations follow the same shared CLI path as regular ROM reads.
FLASH_ACTIONS = ("probe_flash", "write_flash", "verify_flash", "flash_operation")
CORECTL_BIN = "/usr/sbin/retrode3-corectl"
CORES_ENABLED_DIR = "/etc/retrode3/cores-enabled"
CORE_CONTROL_ENABLED = os.environ.get("RETRODE3_CORE_CONTROL_ENABLED", "0") == "1"
CORECTL_SUDO = os.environ.get("RETRODE3_CORECTL_SUDO", "1") == "1"
CORE_ID = re.compile(r"^[a-z0-9_-]{1,48}$")

# Cosmetic, familiar labels only. New physical kernel slots still show up.
PHYSICAL_SLOTS = (("md", "Mega Drive"), ("snes", "Super Nintendo"),
                  ("nes", "Nintendo / Famicom"))
# File format defaults are NOT a reader allowlist; unknown core IDs work
# and use .bin until the CLI reports a ROM file extension.
KNOWN_ROM_EXTENSIONS = {"snes": "sfc", "md": "md", "nes": "nes", "gba": "gba"}
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


def wifi_args():
    if not os.path.isfile(WLAN_BIN):
        raise ApiError(503, "wifi_unavailable", "WLAN helper unavailable")
    prefix = ["sudo", "-n"] if RUN_SUDO else []
    return prefix + [WLAN_BIN]


def call_wlan(action, **fields):
    payload = dict(fields, action=action)
    try:
        proc = subprocess.Popen(wifi_args(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate(json.dumps(payload).encode('utf-8'), timeout=18)
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
        if raw.startswith("{"):
            details = json.loads(raw)
            if not details.get("available"):
                details = {}
        elif raw == "no WLAN interface":
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
    except (ApiError, ValueError):
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
    raw = call_wlan("list")
    if raw.startswith("["):
        return json.loads(raw)
    lines = raw.splitlines()
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
        # Passive read-back only. Unknown/unsupported values must not be
        # guessed, and reading /api/slots must never change hardware voltage.
        voltage_mv = None
        try:
            with open(os.path.join(SENSE_ROOT, "slot-" + slot_id, "vcc"), "r") as handle:
                voltage = handle.read(40).strip()
            if voltage in ("3300mV", "5000mV"):
                voltage_mv = int(voltage[:-2])
        except (IOError, OSError):
            pass
        slots.append({"id": slot_id, "name": name, "status": state,
                      "voltage_mv": voltage_mv,
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
            entry = dict((key, c[key]) for key in
                         ("id", "name", "version", "slot", "status",
                          "installed", "enabled", "usable", "actions"))
            if c.get("probe_without_sense") is True:
                entry["probe_without_sense"] = True
            cores.append(entry)
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


def storage_system_slug(core):
    """Keep the console folder independent of its physical adapter route.

    For example, gba-md and gba-snes share ROMs/GBA. The core ID and slot
    remain unchanged for discovery, electrical gating and job dispatch.
    """
    core_id = core["id"]
    suffix = "-" + core["slot"]
    if core_id.endswith(suffix) and len(core_id) > len(suffix):
        return core_id[:-len(suffix)]
    return core_id


def reader_capability(core_id, registry=None):
    """Discover supported operations exclusively through the central CLI."""
    if registry is None:
        registry = core_registry()
    if not registry["available"]:
        return None
    core = next((c for c in registry["cores"] if c["id"] == core_id), None)
    if core is None:
        return None
    system_slug = storage_system_slug(core)
    result = {"id": core["id"], "name": core["name"], "slot": core["slot"],
              "available": False, "transport": "cli",
              "folder": system_slug.upper(),
              "extension": KNOWN_ROM_EXTENSIONS.get(system_slug, "bin")}
    if not (core["installed"] and core["enabled"] and
            core["status"] == "ready" and core["usable"]):
        result["reason"] = "core_not_ready"
        return result
    commands = [action for action in ("probe", "read_rom") + FLASH_ACTIONS
                if action in core["actions"]]
    if not commands:
        result["reason"] = "core_operation_unavailable"
        return result
    if core.get("probe_without_sense") is True:
        result["probe_without_sense"] = True
    result.update({"available": True,
                   "capabilities": {"system": core["id"], "core": core["id"],
                                    "slot": core["slot"], "commands": commands,
                                    "write_operations": "write_flash" in commands}})
    return result


SELECTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
SELECTION_MODES = ("auto", "candidate", "layout", "override")


def validate_generic_selection(selection, action):
    """Validate the versioned v3 envelope; the core owns hardware policy.

    This is deliberately independent of a console name or particular field.
    A v3 core must reject unsupported combinations again at plan/read time.
    """
    if action != "read_rom" or not isinstance(selection, dict):
        raise ApiError(400, "invalid_selection", "Selection is valid only for ROM reads")
    if (type(selection.get("version")) is not int or
            selection["version"] != 1 or
            not isinstance(selection.get("schema_id"), str) or
            not SELECTION_ID.match(selection["schema_id"]) or
            selection.get("mode") not in SELECTION_MODES):
        raise ApiError(400, "invalid_selection", "Invalid selection mode or schema")
    mode = selection["mode"]
    fields = {"version", "mode", "schema_id"}
    if mode == "candidate":
        fields.add("candidate_id")
        token = selection.get("candidate_id")
        if not isinstance(token, str) or not SELECTION_ID.match(token):
            raise ApiError(400, "invalid_selection", "Invalid candidate ID")
    elif mode == "layout":
        fields.add("layout_id")
        token = selection.get("layout_id")
        if not isinstance(token, str) or not SELECTION_ID.match(token):
            raise ApiError(400, "invalid_selection", "Invalid layout ID")
    elif mode == "override":
        fields.add("parameters")
        params = selection.get("parameters")
        if not isinstance(params, dict) or not 1 <= len(params) <= 32:
            raise ApiError(400, "invalid_selection", "Override parameters required")
        for key, value in params.items():
            if not isinstance(key, str) or not re.match(r"^[A-Za-z0-9_-]{1,47}$", key):
                raise ApiError(400, "invalid_selection", "Invalid parameter ID")
            if type(value) is int:
                if value < 0 or value > 4294967295:
                    raise ApiError(400, "invalid_selection", "Parameter integer out of range")
            elif type(value) is bool:
                pass
            elif isinstance(value, str):
                if len(value) > 127 or any(ord(c) < 32 for c in value):
                    raise ApiError(400, "invalid_selection", "Invalid string parameter")
            else:
                raise ApiError(400, "invalid_selection", "Invalid parameter type")
    if set(selection) != fields:
        raise ApiError(400, "invalid_selection", "Unexpected fields for selection mode")
    # CLI accepts input commands of at most 8192 bytes; fail before spawning it.
    if len(json.dumps(selection, ensure_ascii=True)) > 4096:
        raise ApiError(400, "invalid_selection", "Selection too large")
    return selection


def native_reader_options(core_id):
    """Query capabilities from the actual shared CLI only on explicit UI request."""
    cap = reader_capability(core_id)
    if cap is None or not cap["available"]:
        raise ApiError(503, "native_protocol_unavailable", "Core not ready")
    command = {"command": "get_capabilities", "core": core_id,
               "request_id": "web-options"}
    try:
        process = subprocess.Popen(
            [CLI_BIN, "--protocol", "ndjson-v1", "--interactive"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        try:
            stdout, _ = process.communicate(
                (json.dumps(command) + "\n").encode("ascii"), timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ApiError(504, "operation_timeout", "CLI capabilities timed out")
        if process.returncode != 0:
            raise ApiError(502, "native_protocol_unavailable", "CLI capabilities unavailable")
        for line in stdout.decode("utf-8").splitlines():
            event = json.loads(line)
            if (event.get("event") == "capabilities" and
                    event.get("request_id") == "web-options" and
                    event.get("system") == core_id and
                    event.get("protocol") == PROTOCOL and
                    event.get("version") == 1):
                reported_slot = event.get("slot")
                if reported_slot != cap["slot"]:
                    raise ApiError(502, "native_protocol_unavailable",
                                   "CLI capability slot differs from registry")
                schema = event.get("selection_schema")
                if (not isinstance(schema, dict) or
                        type(schema.get("schema_version")) is not int or
                        schema["schema_version"] != 1 or
                        not isinstance(schema.get("schema_id"), str) or
                        not SELECTION_ID.match(schema["schema_id"]) or
                        not isinstance(schema.get("fields"), list) or
                        len(schema["fields"]) > 32 or
                        not isinstance(schema.get("selection_modes"), list) or
                        not schema["selection_modes"] or
                        any(mode not in SELECTION_MODES for mode in
                            schema["selection_modes"])):
                    raise ApiError(409, "selection_schema_unavailable",
                                   "Core must implement generic v3 selection")
                return {"system": core_id, "slot": cap["slot"],
                        "selection_schema": schema}
    except (OSError, ValueError, UnicodeError) as error:
        raise ApiError(502, "native_protocol_unavailable", str(error))
    raise ApiError(502, "native_protocol_unavailable",
                   "No CLI capability event for reader")


def capability_probe():
    """List only registered shared-CLI cores, never legacy readers."""
    registry = core_registry()
    if not registry["available"]:
        return {"systems": []}
    return {"systems": [reader_capability(c["id"], registry)
                        for c in registry["cores"]]}



class Job(object):
    def __init__(self, manager, reader_id, action, label,
                 reader, automatic=False, selection=None, source=None,
                 flash_options=None):
        self.manager = manager
        self.reader_id = reader_id
        self.reader = reader
        self.selection = selection
        self.source = source
        self.flash_options = flash_options
        self.automatic = automatic
        self.id = uuid.uuid4().hex
        self.action = action
        self.label = label
        self.output = None
        self.presence_generation = None
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
                    "automatic": self.automatic, "slot": self.reader.get("slot"),
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
                argv = [CLI_BIN, "--protocol", "ndjson-v1", "--interactive"]
                process = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, bufsize=0)
                with self.lock:
                    self.process = process
                deadline = time.time() + (max(3600, (self.flash_options or {}).get(
                    "verify_passes", 0) * 900) if self.action in
                    ("write_flash", "verify_flash", "flash_operation") else 900)
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
                            event.get("system") == "multi"):
                        with self.lock:
                            if self.cancel_requested:
                                self.status = "cancelled"
                                return
                            command = {"command": self.action, "request_id": self.id}
                            if self.action == "probe_slot":
                                command["slot"] = self.reader_id
                            else:
                                command["core"] = self.reader_id
                            if self.action == "read_rom":
                                command["output"] = self.output
                                command["selection"] = self.selection
                            elif self.action in ("write_flash", "verify_flash"):
                                command["source"] = self.source
                            elif self.action == "flash_operation":
                                command.update(self.flash_options)
                                if self.source:
                                    command["source"] = self.source
                            self._send(command)
                            sent = True
                        continue
                    if not sent:
                        continue
                    if kind not in ("error", "progress", "probe_result", "slot_probe_result",
                                    "flash_probe_result", "result"):
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
                        elif kind == "slot_probe_result" and self.action == "probe_slot":
                            if event.get("slot") != self.reader_id:
                                raise ApiError(502, "invalid_result", "Wrong slot probe result")
                            self.result = event
                            self.status = "done"
                        elif kind == "probe_result" and self.action == "probe":
                            self.result = event
                            self.status = "done"
                        elif kind == "flash_probe_result" and self.action == "probe_flash":
                            if (event.get("system") != self.reader_id or
                                    not event.get("write_supported")):
                                raise ApiError(502, "invalid_result", "Unexpected Flash identity")
                            self.result = event
                            self.status = "done"
                        elif kind == "result" and self.action in (
                                "write_flash", "verify_flash", "flash_operation"):
                            verification = event.get("flash_verification") or {}
                            requested = (self.flash_options or {}).get(
                                "verify", self.action != "flash_operation")
                            expected_status = "verified" if requested else "not_checked"
                            if (event.get("ok") is not True or
                                    event.get("command") != self.action or
                                    verification.get("status") != expected_status or
                                    verification.get("verified") is not requested):
                                raise ApiError(502, "invalid_result",
                                               "Flash operation status inconsistent")
                            if self.action == "flash_operation":
                                operations = event.get("operations") or {}
                                if any(operations.get(name) is not self.flash_options[name]
                                       for name in ("erase", "write", "verify")):
                                    raise ApiError(502, "invalid_result",
                                                   "Flash operation stages inconsistent")
                                if requested and verification.get("passes_completed") != (
                                        self.flash_options["verify_passes"]):
                                    raise ApiError(502, "invalid_result",
                                                   "Not all Verify passes completed")
                            self.result = event
                            self.status = "done"
                        elif kind == "result" and self.action == "read_rom":
                            if not event.get("ok") or event.get("output") != self.output:
                                raise ApiError(502, "invalid_result", "Unexpected native output")
                            self.result = event
                            self.status = "done"
                        elif kind == "error":
                            self.error = {"code": event.get("code", "operation_failed"),
                                          "message": event.get("message", "Cartridge operation failed")}
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
                    try:
                        if self.action == "read_rom" and self.status == "done":
                            self.manager.remember_read(self)
                    finally:
                        if self.manager.active is self:
                            self.manager.active = None


class JobManager(object):
    def __init__(self):
        self.jobs = {}
        self.active = None
        self.lock = threading.RLock()
        self.bus_lock = threading.Lock()
        self.slot_presence = {}
        self.read_results = {}

    def observe_slot(self, slot_id, presence):
        """Invalidate a result on every confirmed physical presence transition."""
        with self.lock:
            previous = self.slot_presence.get(slot_id)
            if previous is None or previous[0] != presence:
                self.slot_presence[slot_id] = (presence, uuid.uuid4().hex)
                self.read_results.pop(slot_id, None)
            return self.slot_presence[slot_id][1]

    def remember_read(self, job):
        # Only a physically occupied slot can retain a cartridge-specific
        # result. A sense-independent header cannot prove continuous presence.
        slot = job.reader["slot"]
        current = next((s for s in slot_snapshot()["slots"] if s["id"] == slot), None)
        with self.lock:
            generation = self.observe_slot(slot, current["status"] if current else "unknown")
            if not current or current["status"] != "occupied" or generation != job.presence_generation:
                return
            result = job.result or {}
            identity = result.get("identity") or {}
            verification = result.get("verification") or {}
            if not isinstance(identity, dict):
                identity = {}
            if not isinstance(verification, dict):
                verification = {}
            self.read_results[slot] = {
                "system": job.reader_id, "job_id": job.id,
                "title": identity.get("title") or result.get("title"),
                "filename": os.path.basename(job.output or ""),
                "size_bytes": result.get("size_bytes", result.get("bytes_written",
                    result.get("bytes", (job.progress or {}).get("bytes_total")))),
                "crc32": result.get("crc32"), "layout_id": result.get("layout_id"),
                "read_configuration": result.get("read_configuration"),
                "verification": {k: verification.get(k) for k in
                    ("status", "actual", "expected", "verified")},
            }

    def slot_job_state(self):
        with self.lock:
            job = self.active
            if job is None:
                return None
            with job.lock:
                return {"id": job.id, "system": job.reader_id, "slot": job.reader.get("slot"),
                        "command": job.action, "status": job.status, "automatic": job.automatic,
                        "progress": {"percent": (job.progress or {}).get("percent")}}

    def submit(self, data, automatic=False):
        reader_id = data.get("system")
        action = data.get("command")
        if (not isinstance(reader_id, str) or not CORE_ID.match(reader_id) or
                action not in ("probe", "read_rom") + FLASH_ACTIONS):
            raise ApiError(400, "unsupported", "Unknown reader or unsupported command")
        if automatic and action in FLASH_ACTIONS:
            raise ApiError(400, "unsupported", "Flash operations are never automatic")
        selection = None
        source = None
        flash_options = None
        if action == "read_rom":
            if set(data) != {"system", "command", "filename", "selection"}:
                raise ApiError(400, "invalid_selection",
                               "ROM reads require the generic v3 selection envelope")
            selection = validate_generic_selection(data["selection"], action)
        elif action in ("probe", "probe_flash"):
            if set(data) != {"system", "command"}:
                raise ApiError(400, "invalid_command", "Probe takes no extra options")
        elif action == "flash_operation":
            required = {"system", "command", "erase", "write", "verify", "verify_passes"}
            if set(data) not in (required, required | {"source"}):
                raise ApiError(400, "invalid_command", "Invalid Flash operation fields")
            if (type(data["erase"]) is not bool or
                    type(data["write"]) is not bool or
                    type(data["verify"]) is not bool or
                    type(data["verify_passes"]) is not int):
                raise ApiError(400, "invalid_command", "Invalid Flash stage value")
            count = data["verify_passes"]
            if (not any((data["erase"], data["write"], data["verify"])) or
                    (data["verify"] and not 1 <= count <= 99) or
                    (not data["verify"] and count != 0)):
                raise ApiError(400, "invalid_command", "Invalid Flash stage selection")
            source = data.get("source")
            if (data["write"] or data["verify"]) and not source:
                raise ApiError(400, "invalid_path", "Upload a ROM for Write or Verify")
            flash_options = {key: data[key] for key in
                             ("erase", "write", "verify", "verify_passes")}
        else:
            fields = {"system", "command", "source"}
            if set(data) != fields:
                raise ApiError(400, "invalid_command", "Invalid Flash job fields")
            source = data.get("source")
            if not isinstance(source, str) or not source:
                raise ApiError(400, "invalid_path", "Select a ROM from shared storage")
        cap = reader_capability(reader_id)
        if cap is None:
            raise ApiError(400, "unsupported", "Core not registered by CLI")
        if not cap["available"]:
            raise ApiError(503, "native_protocol_unavailable",
                           "The requested shared CLI core is not available")
        features = cap["capabilities"]
        if action not in features["commands"]:
            raise ApiError(400, "unsupported", "Command unavailable for this reader")
        if source is not None:
            if not isinstance(source, str):
                raise ApiError(400, "invalid_path", "ROM path must be a string")
            # A Flash source must be a regular ROM in this *logical* system
            # directory, not a user-supplied /dev path or a different core's ROM.
            if not source.startswith(cap["folder"] + "/"):
                raise ApiError(400, "invalid_path", "ROM belongs to a different system folder")
            source = safe_path(source)
            if not os.path.isfile(source):
                raise ApiError(400, "invalid_path", "Flash source is not a regular ROM")
            length = os.path.getsize(source)
            if length < 512 or length > 4194304 or length % 2:
                raise ApiError(400, "invalid_size", "Unsupported Flash ROM size")
        if selection is not None:
            opts = native_reader_options(reader_id)
            schema = opts.get("selection_schema")
            if (schema is None or selection["schema_id"] != schema["schema_id"] or
                    selection["mode"] not in schema["selection_modes"]):
                raise ApiError(409, "selection_schema_mismatch",
                               "Reader selection capabilities changed; reload options")
        job = Job(self, reader_id, action,
                  sanitized_filename(data.get("filename")),
                  cap, automatic=automatic, selection=selection,
                  source=source, flash_options=flash_options)
        with self.lock:
            if self.active is not None:
                raise ApiError(409, "busy", "Cartridge reader already busy")
            if len(self.jobs) >= 50:
                old = sorted((j for j in self.jobs.values() if j is not self.active),
                             key=lambda j: j.created)
                if old:
                    del self.jobs[old[0].id]
            if action == "read_rom" or action in ("write_flash", "flash_operation"):
                slot_id = cap["slot"]
                current = next((s for s in slot_snapshot()["slots"] if s["id"] == slot_id), None)
                job.presence_generation = self.observe_slot(
                    slot_id, current["status"] if current else "unknown")
                # A new dump or potentially destructive flash operation makes
                # the previous completion marker no longer authoritative.
                self.read_results.pop(slot_id, None)
            self.jobs[job.id] = job
            self.active = job
        thread = threading.Thread(target=job.run)
        thread.daemon = True
        thread.start()
        return job.snapshot()

    def submit_slot_probe(self, slot_id):
        """Internal-only, serialized slot identification. Never exposed by POST /api/jobs."""
        if not isinstance(slot_id, str) or not CORE_ID.match(slot_id):
            raise ApiError(400, "invalid_slot", "Invalid physical slot")
        job = Job(self, slot_id, "probe_slot", "", {"slot": slot_id},
                  automatic=True)
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

    Linux slot uevents wake the worker; their text never selects a core.
    Passive sense is the ordinary trigger. Cores explicitly declaring
    sense-independent probes may also be checked at a bounded interval.
    A periodic reconciliation handles lost events or absent netlink.
    All probes are submitted through the same serialized JobManager as
    manually requested ROM reads; no second raw device reader exists.
    """
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.RLock()
        self.records = {}
        self.fallback_slots = None
        self.running = False
        self.registry_stamp = self._registry_stamp()
        self.registry_revision = 0

    def start(self):
        if self.running:
            return
        self.running = True
        worker = threading.Thread(target=self._watch)
        worker.daemon = True
        worker.start()

    @staticmethod
    def _registry_stamp():
        # corectl creates/removes enablement symlinks atomically. One stat
        # per reconciliation tick suffices; never poll the CLI for this.
        try:
            info = os.stat(CORES_ENABLED_DIR)
            return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        except OSError:
            return None

    def refresh_registry(self):
        """Observe enable/disable via both the HTTP API and shell corectl."""
        with self.lock:
            stamp = self._registry_stamp()
            if stamp != self.registry_stamp:
                self.registry_stamp = stamp
                self.reset()

    def reset(self):
        """Re-evaluate occupied slots after a registry change."""
        with self.lock:
            self.registry_revision += 1
            self.fallback_slots = None
            with self.manager.lock:
                self.manager.read_results.clear()
                self.manager.slot_presence.clear()
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
            # A sense-independent reader must validate cartridge identity
            # itself. Empty sense is not proof of removal for that reader.
            if active.reader.get("probe_without_sense") is True:
                return
            record = self.records.get(slot_id) or {}
            if active.action == "probe_slot" and record.get("fallback"):
                return
            active.cancel()

    def _event_changed(self, payload):
        """Wake auto detection only for an actual, confirmed sense transition.

        Repeated KOBJ_CHANGE notifications for an unchanged occupied slot
        must not discard a completed probe or cancel an ongoing one.
        Sysfs sense is authoritative; stale uevents do not choose a core.
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
        expected = "occupied" if sense == "active" else "empty"
        current = next((s for s in slot_snapshot()["slots"] if s["id"] == slot_id), None)
        if current is None or current["status"] != expected:
            return
        self.manager.observe_slot(slot_id, expected)
        if sense == "empty":
            self._cancel_removed_slot(slot_id)
        with self.lock:
            previous = self.records.get(slot_id)
            if previous is not None and previous["presence"] == expected:
                return
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
            self.refresh_registry()
            for slot in slots:
                slot_id = slot["id"]
                status = slot["status"]
                self.manager.observe_slot(slot_id, status)
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
                        "ready_at": now + (0.35 if status == "occupied" else 3.0),
                        "fallback": False,
                        "job_id": None,
                        "core_id": None,
                        "slot_probe": False,
                        "result": None,
                        "error": None}
                    continue
                if status != "occupied":
                    if status != "empty":
                        continue
                    # No probing on browser refresh. Only the backend worker
                    # schedules bounded, opt-in header probes while idle.
                    if record["state"] != "detecting":
                        if now < record["ready_at"]:
                            continue
                        with self.manager.lock:
                            if self.manager.active is not None:
                                continue
                        if self.fallback_slots is None:
                            try:
                                self.fallback_slots = set(
                                    reader["slot"] for reader in capability_probe()["systems"]
                                    if reader and reader["available"] and
                                    reader.get("probe_without_sense") is True)
                            except ApiError:
                                record["ready_at"] = now + 5.0
                                continue
                        if slot_id not in self.fallback_slots:
                            continue
                        record["fallback"] = True
                        try:
                            job = self.manager.submit_slot_probe(slot_id)
                        except ApiError as error:
                            if error.status != 409:
                                record["ready_at"] = now + 5.0
                            continue
                        record["job_id"] = job["id"]
                        record["slot_probe"] = True
                        record["state"] = "detecting"
                        continue
                    if not record.get("fallback"):
                        continue
                if record["state"] == "detecting":
                    job = self.manager.get(record["job_id"]).snapshot()
                    if job["status"] == "done":
                        result = job.get("result") or {}
                        if record.get("slot_probe"):
                            if result.get("event") != "slot_probe_result" or result.get("slot") != slot_id:
                                record["state"] = "failed"
                                record["error"] = "invalid_slot_probe_result"
                            elif result.get("detection") == "detected" and result.get("core"):
                                probe = result.get("probe_result") or {}
                                if probe.get("system") != result["core"] or probe.get("slot") != slot_id:
                                    record["state"] = "failed"
                                    record["error"] = "invalid_slot_probe_result"
                                else:
                                    record["core_id"] = result["core"]
                                    record["result"] = dict((key, probe.get(key)) for key in
                                                            ("title", "mapping", "size_bytes", "checksum",
                                                             "slot", "selection_schema_id", "ambiguity",
                                                             "identification_status", "selection_required",
                                                             "candidate_lookup", "candidates", "read_layouts")
                                                            if key in probe)
                                    record["result"]["voltage_status"] = result.get("voltage_status")
                                    # Read voltage is supplied by the selected core's
                                    # capability schema, through the common CLI.
                                    if type(probe.get("read_voltage_mv")) is int and \
                                            probe["read_voltage_mv"] in (3300, 5000):
                                        record["result"]["read_voltage_mv"] = probe["read_voltage_mv"]
                                    record["state"] = "detected"
                                    record["error"] = None
                                    if record.get("fallback"):
                                        record["ready_at"] = now + 5.0
                            elif record.get("fallback"):
                                # No valid header on a slot without sense:
                                # remove cached identity, then wait to retry.
                                record["state"] = "idle"
                                record["result"] = None
                                record["core_id"] = None
                                record["error"] = None
                                record["ready_at"] = now + 5.0
                            elif result.get("detection") == "empty":
                                record["state"] = "pending"
                                record["ready_at"] = now + 0.35
                            else:
                                record["state"] = "choose_reader"
                                record["error"] = result.get("reason")
                        elif (result.get("event") == "probe_result" and
                              result.get("system") == record["core_id"]):
                            record["result"] = dict((key, result.get(key)) for key in
                                                    ("title", "mapping", "size_bytes", "checksum",
                                                     "slot", "selection_schema_id", "ambiguity",
                                                     "identification_status", "selection_required",
                                                     "candidate_lookup", "candidates", "read_layouts")
                                                    if key in result)
                            record["state"] = "detected"
                            record["error"] = None
                        else:
                            record["state"] = "failed"
                            record["error"] = "invalid_probe_result"
                    elif job["status"] in ("failed", "cancelled"):
                        record["state"] = "failed"
                        record["error"] = (job.get("error") or {}).get("code", "probe_failed")
                        if record.get("fallback"):
                            record["ready_at"] = now + 5.0
                            record["result"] = None
                            record["core_id"] = None
                elif record["state"] == "pending" and now >= record["ready_at"]:
                    # Waiting must be passive. Do not spawn repeated CLI
                    # inventory processes every 300 ms while another slot's
                    # probe or a manual ROM dump owns the shared bus.
                    with self.manager.lock:
                        if self.manager.active is not None:
                            continue
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
                        try:
                            job = self.manager.submit_slot_probe(slot_id)
                        except ApiError as error:
                            if error.status == 409:
                                continue
                            record["state"] = "failed"
                            record["error"] = error.code
                        else:
                            record["job_id"] = job["id"]
                            record["slot_probe"] = True
                            record["state"] = "detecting"
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
            result["registry_revision"] = self.registry_revision
            result["busy_job"] = self.manager.slot_job_state()
            for slot in result["slots"]:
                self.manager.observe_slot(slot["id"], slot["status"])
                with self.manager.lock:
                    slot["read_result"] = self.manager.read_results.get(slot["id"])
                record = self.records.get(slot["id"])
                if record is not None and record["presence"] == slot["status"]:
                    # Keep passive sense separately; a confirmed header is
                    # sufficient presence evidence for an opt-in core.
                    detected_by_header = (record.get("fallback") and
                                          record["result"] is not None and
                                          record["core_id"] is not None)
                    if detected_by_header:
                        slot["sense_status"] = slot["status"]
                        slot["status"] = "occupied"
                        slot["presence_source"] = "header"
                    slot["detection"] = {
                        "state": "detected" if detected_by_header else record["state"],
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
            elif path.startswith("/api/reader-options/") and re.match(
                    r"^/api/reader-options/[a-z][a-z0-9_-]{0,31}$", path):
                self._json(200, native_reader_options(path.rsplit("/", 1)[-1]))
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
                AUTO.refresh_registry()
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
                if not isinstance(ssid, str) or not (1 <= len(ssid.encode("utf-8")) <= 32) or "\x00" in ssid:
                    raise ApiError(400, "invalid_ssid", "SSID must contain 1-32 characters")
                if not isinstance(password, str) or len(password) > 128 or "\x00" in password:
                    raise ApiError(400, "invalid_password", "Invalid password")
                self._json(200, {"message": call_wlan("connect", ssid=ssid, password=password)})
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
