#!/usr/bin/env python3
"""Check immutable Retrode3 platform Debian artifacts (never publish here)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
IMGID = re.compile(r"sha256:[0-9a-f]{64}\Z")
PACKAGES = {
    "kernel": ("retrode3-linux-image", "retrode3-linux-modules"),
    "uboot": ("retrode3-uboot-x1600",),
}


def key(kind, commit, image_id):
    if kind not in PACKAGES or not SHA40.fullmatch(commit) or not IMGID.fullmatch(image_id):
        raise ValueError("Invalid platform package cache inputs")
    return hashlib.sha256(("platform-deb-v1\n" + kind + "\n" +
                           commit + "\n" + image_id + "\n").encode()).hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(directory, kind, commit, image_id):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Missing or unsafe platform cache directory")
    expected_key = key(kind, commit, image_id)
    if directory.name != expected_key:
        raise ValueError("Wrong platform cache path")
    mpath = directory / "platform-manifest.json"
    if mpath.is_symlink() or not mpath.is_file():
        raise ValueError("Missing platform manifest")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    for field, expected in {
        "schema": 1, "kind": kind, "commit": commit,
        "builder_image_id": image_id, "cache_key": expected_key,
        "hardware_accepted": False,
    }.items():
        if manifest.get(field) != expected:
            raise ValueError("Wrong platform manifest: " + field)
    files = manifest.get("files")
    if not isinstance(files, dict) or len(files) != len(PACKAGES[kind]):
        raise ValueError("Wrong platform package set")
    names = set()
    versions = set()
    for filename, expected_sha in files.items():
        if not re.fullmatch(r"[A-Za-z0-9.+:~_-]+_mipsel\.deb", filename):
            raise ValueError("Unsafe package filename")
        fpath = directory / filename
        if (not fpath.is_file() or fpath.is_symlink() or
                not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or
                sha256(fpath) != expected_sha):
            raise ValueError("Missing/changed Debian package: " + filename)
        field = lambda name: subprocess.check_output(
            ["dpkg-deb", "-f", str(fpath), name], text=True).strip()
        package = field("Package")
        version = field("Version")
        if field("Architecture") != "mipsel" or not filename.startswith(package + "_" + version + "_"):
            raise ValueError("Debian package identity mismatch: " + filename)
        names.add(package)
        versions.add(version)
    if names != set(PACKAGES[kind]) or len(versions) != 1:
        raise ValueError("Incomplete platform package set or version mismatch")
    version = next(iter(versions))
    if manifest.get("version") != version:
        raise ValueError("Platform version changed")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("key", "verify"))
    parser.add_argument("kind", choices=tuple(PACKAGES))
    parser.add_argument("commit")
    parser.add_argument("image_id")
    parser.add_argument("directory", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        if args.command == "key":
            print(key(args.kind, args.commit, args.image_id))
        else:
            if args.directory is None:
                raise ValueError("Missing cache directory")
            doc = verify(args.directory, args.kind, args.commit, args.image_id)
            print(doc["version"])
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "Invalid platform cache: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
