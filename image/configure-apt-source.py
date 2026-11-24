#!/usr/bin/env python3
"""Install a verified Retrode3 APT source and public key into an offline rootfs.

This never updates packages, starts services, downloads keys or accesses disks.
The caller provides the trusted public export and an independently pinned
40-hex-character fingerprint from the release administrator.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

APT_URL = "https://packages.retrode.com"
KEY_DEST = "usr/share/keyrings/retrode3-archive-keyring.gpg"
LIST_DEST = "etc/apt/sources.list.d/retrode3.list"
HEX40 = re.compile(r"[0-9A-Fa-f]{40}\Z")


def check_key(key_file, expected_fpr):
    if not HEX40.fullmatch(expected_fpr):
        raise ValueError("expected signing key fingerprint must be exactly 40 hex characters")
    data = key_file.read_bytes()
    if not data or len(data) > 65536 or data.startswith(b"-----BEGIN"):
        raise ValueError("expected a bounded binary GPG public-key export, not an ASCII-armored key")
    with tempfile.TemporaryDirectory(prefix="retrode3-apt-key-check-") as home:
        result = subprocess.run(
            ["gpg", "--homedir", home, "--batch", "--no-options",
             "--with-colons", "--show-keys", str(key_file)],
            capture_output=True, text=True, check=True)
    pub_fingerprints = []
    expecting_pub_fpr = False
    for line in result.stdout.splitlines():
        columns = line.split(":")
        if columns[0] == "pub":
            expecting_pub_fpr = True
        elif columns[0] == "sub":
            expecting_pub_fpr = False
        elif columns[0] == "fpr" and expecting_pub_fpr:
            pub_fingerprints.append(columns[9].upper())
            expecting_pub_fpr = False
    if pub_fingerprints != [expected_fpr.upper()]:
        raise ValueError("public-key fingerprint mismatch or multiple signing keys")
    return data


def confined_target(root, relative):
    current = root
    for component in Path(relative).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("refusing symlink inside rootfs APT path: " + str(current))
    return current


def configure(root, key_file, fingerprint, suite):
    if suite not in ("testing", "stable"):
        raise ValueError("APT suite must be testing or stable")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("rootfs must be a real existing directory")
    if not (root / "etc/debian_version").is_file():
        raise ValueError("rootfs does not have Debian version metadata")
    data = check_key(key_file, fingerprint)
    key_dest = confined_target(root, KEY_DEST)
    list_dest = confined_target(root, LIST_DEST)
    if key_dest.exists() or list_dest.exists():
        raise ValueError("refusing to replace an existing Retrode3 APT key or source")
    key_dest.parent.mkdir(parents=True, exist_ok=True)
    list_dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        key_dest.write_bytes(data)
        os.chmod(key_dest, 0o644)
        list_dest.write_text(
            "deb [arch=mipsel signed-by=/usr/share/keyrings/retrode3-archive-keyring.gpg] "
            + APT_URL + " " + suite + " main\n", encoding="ascii")
        os.chmod(list_dest, 0o644)
    except BaseException:
        for target in (list_dest, key_dest):
            if target.is_file() and not target.is_symlink():
                target.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--suite", choices=("testing", "stable"), required=True)
    args = parser.parse_args()
    try:
        configure(args.rootfs, args.public_key, args.fingerprint, args.suite)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
    print("Configured verified Retrode3 APT source:", APT_URL, args.suite)


if __name__ == "__main__":
    main()
