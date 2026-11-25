#!/usr/bin/env python3
"""Verify exact published Retrode3 boot packages and their source provenance."""
import json
from pathlib import Path
import re
import subprocess
import sys

EXPECTED = {"retrode3-linux-image", "retrode3-linux-modules", "retrode3-uboot-x1600"}


def verify(path, suite):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or unsafe published platform snapshot")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (doc.get("schema") != 1 or doc.get("suite") != suite or
            doc.get("apt_published") is not True or
            doc.get("hardware_accepted") is not False):
        raise ValueError("Platform snapshot is not a signed testing candidate")
    source = doc.get("sources", {})
    if (set(source) != {"kernel", "uboot"} or not all(
            re.fullmatch(r"[0-9a-f]{40}", value) for value in source.values())):
        raise ValueError("Platform source SHA mismatch")
    records = doc.get("packages", [])
    if (len(records) != 3 or {p["name"] for p in records} != EXPECTED):
        raise ValueError("Incomplete platform package list")
    for p in records:
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", p["version"]):
            raise ValueError("Invalid platform package version")
        if not re.fullmatch(r"[0-9a-f]{64}", p["sha256"]):
            raise ValueError("Missing platform Debian checksum")
        if (p["filename"] != p["name"] + "_" + p["version"] + "_mipsel.deb"):
            raise ValueError("Unexpected platform Debian filename")
    versions = {p["name"]: p["version"] for p in records}
    if versions["retrode3-linux-image"] != versions["retrode3-linux-modules"]:
        raise ValueError("Kernel and modules package versions differ")
    return doc


def main():
    try:
        doc = verify(Path(sys.argv[1]), "testing")
        if len(sys.argv) == 3:
            rows = subprocess.check_output(
                ["reprepro", "--basedir", sys.argv[2], "list", "testing"],
                text=True)
            indexed = set()
            for row in rows.splitlines():
                if row.startswith("testing|") and ": " in row:
                    name, version = row.split(": ", 1)[1].rsplit(" ", 1)
                    indexed.add((name, version))
            for p in doc["packages"]:
                if (p["name"], p["version"]) not in indexed:
                    raise ValueError("Not indexed in signed testing APT: " + p["name"])
        print("Verified published platform candidate:", doc["sources"]["kernel"],
              doc["sources"]["uboot"])
    except (IndexError, OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit("Platform snapshot validation failed: " + str(exc))


if __name__ == "__main__":
    main()
