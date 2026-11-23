#!/usr/bin/python3
"""Root-owned, single-job Flash bridge for the unprivileged Retrode3 Web service.

sudoers may allow exactly this program (without arguments), NEVER the CLI.
It forwards one validated Flash NDJSON command, optional cancel, and events.
No ROM-read commands, output paths, shell, arbitrary GPIO access or raw writes.
"""
from __future__ import print_function

import json
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile

CLI = "/usr/bin/retrode3-cli"
ROMS = "/usr/local/games/ROMs"
PRIVATE = "/run/lock/retrode3"
ACTIONS = ("probe_flash", "write_flash", "verify_flash")
TOKEN = re.compile(r"^[a-z0-9_-]{1,48}$")
REQUEST = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FlashRequestError(Exception):
    pass


def snapshot_rom(source):
    """Copy a bounded regular ROM to an inaccessible root-owned private path."""
    root = os.path.realpath(ROMS)
    if not isinstance(source, str) or not source.startswith(root + os.sep):
        raise FlashRequestError("Flash source must be in ROMs")
    rel = source[len(root) + 1:]
    parts = rel.split(os.sep)
    if any(not x or x in (".", "..") or x.startswith(".") for x in parts):
        raise FlashRequestError("Invalid ROM path")
    walk = root
    for part in parts:
        walk = os.path.join(walk, part)
        if os.path.islink(walk):
            raise FlashRequestError("Symlink in ROM path")
    if os.path.realpath(source) != source:
        raise FlashRequestError("ROM path is not canonical")
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size < 512 or
                info.st_size > 4194304 or info.st_size % 2):
            raise FlashRequestError("Unsupported ROM source size")
        tmpdir = tempfile.mkdtemp(prefix="flash-job-", dir=PRIVATE)
        os.chmod(tmpdir, 0o700)
        target = os.path.join(tmpdir, "source.rom")
        try:
            with os.fdopen(os.dup(fd), "rb") as source_file:
                with open(target, "xb") as copy:
                    remaining = info.st_size
                    while remaining:
                        chunk = source_file.read(min(65536, remaining))
                        if not chunk:
                            raise FlashRequestError("ROM changed during snapshot")
                        copy.write(chunk)
                        remaining -= len(chunk)
                    if source_file.read(1):
                        raise FlashRequestError("ROM changed during snapshot")
                    copy.flush()
                    os.fsync(copy.fileno())
            os.chmod(target, 0o400)
            return tmpdir, target
        except Exception:
            shutil.rmtree(tmpdir)
            raise
    finally:
        os.close(fd)


def authorize(value):
    if not isinstance(value, dict):
        raise FlashRequestError("Flash command must be an object")
    command = value.get("command")
    if command not in ACTIONS:
        raise FlashRequestError("Not an allowed Flash operation")
    if not isinstance(value.get("core"), str) or not TOKEN.match(value["core"]):
        raise FlashRequestError("Invalid core")
    if not isinstance(value.get("request_id"), str) or not REQUEST.match(value["request_id"]):
        raise FlashRequestError("Invalid request ID")
    allowed = {"core", "command", "request_id"}
    if command != "probe_flash":
        allowed.add("source")
        if not isinstance(value.get("source"), str):
            raise FlashRequestError("ROM source required")
    if command == "write_flash":
        allowed.add("confirm_erase")
        if value.get("confirm_erase") is not True:
            raise FlashRequestError("Destructive erase not confirmed")
    if set(value) != allowed:
        raise FlashRequestError("Unexpected privileged command fields")
    return value


def run():
    # Do not trust shell or inherited command-line flags from www-data.
    if len(sys.argv) != 1 or os.geteuid() != 0:
        raise FlashRequestError("Root-only Flash bridge accepts no arguments")
    proc = subprocess.Popen(
        [CLI, "--protocol", "ndjson-v1", "--interactive"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, bufsize=0)
    tmpdir = None
    authorized = None
    try:
        while True:
            readable, _, _ = select.select([proc.stdout, sys.stdin.buffer], [], [], 0.4)
            if proc.poll() is not None and not readable:
                raise FlashRequestError("Flash CLI exited unexpectedly")
            for handle in readable:
                if handle is sys.stdin.buffer:
                    line = handle.readline(8193)
                    if not line or len(line) > 8192:
                        raise FlashRequestError("Flash command stream closed or oversized")
                    try:
                        value = json.loads(line.decode("utf-8"))
                    except (UnicodeError, ValueError):
                        raise FlashRequestError("Invalid Flash command JSON")
                    if authorized is None:
                        authorized = authorize(value)
                        if authorized["command"] != "probe_flash":
                            tmpdir, path = snapshot_rom(authorized["source"])
                            value["source"] = path
                        proc.stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode("ascii"))
                        proc.stdin.flush()
                    elif (set(value) == {"command", "request_id"} and
                          value.get("command") == "cancel" and
                          value.get("request_id") == authorized["request_id"]):
                        proc.stdin.write((json.dumps(value) + "\n").encode("ascii"))
                        proc.stdin.flush()
                    else:
                        raise FlashRequestError("Only cancellation is permitted after Flash start")
                else:
                    line = handle.readline(65537)
                    if not line or len(line) > 65536:
                        raise FlashRequestError("Flash CLI output ended or exceeded limit")
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                    if authorized is None:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeError):
                        raise FlashRequestError("Invalid Flash event")
                    if (event.get("request_id") == authorized["request_id"] and
                            event.get("event") in ("error", "result", "flash_probe_result")):
                        return 0
    finally:
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        if tmpdir is not None:
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (FlashRequestError, OSError, ValueError) as error:
        print("Flash bridge: %s" % error, file=sys.stderr)
        sys.exit(2)
