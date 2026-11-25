#!/usr/bin/env python3
"""Fail-closed platform APT publication preflight. No APT writes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

EXPECTED = {"retrode3-linux-image", "retrode3-linux-modules", "retrode3-uboot-x1600"}


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def verify(run, repo):
    if run.is_symlink() or not run.is_dir():
        raise ValueError("Unsafe candidate directory")
    manifest = json.loads((run / "platform-package-set.json").read_text())
    if (manifest.get("schema") != 1 or manifest.get("suite") != "testing" or
            manifest.get("hardware_accepted") is not False or
            set(manifest.get("sources", {})) != {"kernel", "uboot"}):
        raise ValueError("Invalid source/suite candidate manifest")
    records = manifest.get("packages", [])
    if len(records) != 3:
        raise ValueError("Expected three platform Debian packages")
    seen = set()
    versions = {}
    for record in records:
        name = record["name"]
        filename = record["filename"]
        version = record["version"]
        if name not in EXPECTED or name in seen:
            raise ValueError("Unknown or duplicate platform package " + name)
        seen.add(name)
        if (not re.fullmatch(r"[A-Za-z0-9.+:~_-]+_mipsel\.deb", filename)
                or filename != name + "_" + version + "_mipsel.deb"):
            raise ValueError("Unsafe platform Debian filename")
        file = run / filename
        if file.is_symlink() or not file.is_file():
            raise ValueError("Missing platform Debian archive")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError("Changed platform Debian archive")
        for field, expected in (("Package", name), ("Version", version),
                                ("Architecture", "mipsel")):
            if command("dpkg-deb", "-f", str(file), field) != expected:
                raise ValueError("Platform package metadata mismatch")
        versions[name] = version
    if seen != EXPECTED or versions["retrode3-linux-image"] != versions["retrode3-linux-modules"]:
        raise ValueError("Mismatched kernel image and modules")
    current = {}
    rows = command("reprepro", "--basedir", str(repo), "list", "testing")
    for row in rows.splitlines():
        if row.startswith("testing|") and ": " in row:
            payload = row.split(": ", 1)[1]
            name, version = payload.rsplit(" ", 1)
            current[name] = version
    for name, version in versions.items():
        old = current.get(name)
        if old is not None and old != version and subprocess.call(
                ["dpkg", "--compare-versions", version, "gt", old]) != 0:
            raise ValueError("Would downgrade platform package " + name)
        file = run / (name + "_" + version + "_mipsel.deb")
        for existing in (repo / "pool").rglob(file.name):
            if existing.is_symlink() or not existing.is_file() or hashlib.sha256(
                    existing.read_bytes()).hexdigest() != hashlib.sha256(file.read_bytes()).hexdigest():
                raise ValueError("Conflicting existing platform archive " + file.name)
    return manifest


if __name__ == "__main__":
    try:
        assert len(sys.argv) == 3
        d = verify(Path(sys.argv[1]), Path(sys.argv[2]))
        print("Platform APT preflight OK:", len(d["packages"]), "packages")
    except (AssertionError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        sys.exit("Platform APT publication refused: " + str(exc))
