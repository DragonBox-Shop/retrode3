#!/usr/bin/env python3
"""Reject image builds without the exact signed-repository package tag pair."""
import argparse
import json
from pathlib import Path
import re


SHA = re.compile(r"[0-9a-f]{40}\Z")
TAG = re.compile(r"[A-Za-z0-9._-]+\Z")
REQUIRED = frozenset({
    "retrode3-core-runtime", "retrode3-web-control",
    "retrode3-tools", "retrode3-udev-rules",
})


def verify(snapshot, suite, branch, os_tag, os_sha, oscr_tag, oscr_sha):
    if (suite, branch) not in {("testing", "develop"), ("stable", "master")}:
        raise ValueError("Unsupported APT suite/branch pairing")
    for name, value in (("OS tag", os_tag), ("OSCR tag", oscr_tag)):
        if not TAG.fullmatch(value):
            raise ValueError("Invalid " + name)
    for name, value in (("OS SHA", os_sha), ("OSCR SHA", oscr_sha)):
        if not SHA.fullmatch(value):
            raise ValueError("Invalid " + name)
    expected = {
        "release_channel": suite,
        "oscr_branch": branch,
        "os_tag": os_tag,
        "os_commit": os_sha,
        "oscr_tag": oscr_tag,
        "oscr_commit": oscr_sha,
    }
    for key, value in expected.items():
        if snapshot.get(key) != value:
            raise ValueError("Published package manifest does not match selected tag pair: " + key)
    if snapshot.get("auto_versioned") is not True:
        raise ValueError("Unsigned/unversioned candidate is not an automatic tagged release")
    if not SHA.fullmatch(snapshot.get("sanni_commit", "")):
        raise ValueError("Missing pinned Sanni Git submodule commit")
    for key in ("native_version", "web_version"):
        if not snapshot.get(key):
            raise ValueError("Missing package version: " + key)
    packages = snapshot.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Empty published package manifest")
    names = [item.get("package") for item in packages if isinstance(item, dict)]
    if len(names) != len(packages) or len(set(names)) != len(names):
        raise ValueError("Malformed or duplicate packages in manifest")
    if not REQUIRED.issubset(names):
        raise ValueError("Required Retrode3 packages missing from snapshot")
    if any(not isinstance(name, str) or
           not re.fullmatch(r"retrode3-[a-z0-9-]+", name) for name in names):
        raise ValueError("Unsafe package name")
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("suite")
    parser.add_argument("branch")
    parser.add_argument("os_tag")
    parser.add_argument("os_sha")
    parser.add_argument("oscr_tag")
    parser.add_argument("oscr_sha")
    args = parser.parse_args()
    try:
        doc = json.loads(args.manifest.read_text(encoding="utf-8"))
        verify(doc, args.suite, args.branch, args.os_tag, args.os_sha,
               args.oscr_tag, args.oscr_sha)
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(1, "Image source snapshot rejected: " + str(exc) + "\n")
    print("Image source locked to published OS/OSCR tags:",
          args.os_tag, args.oscr_tag)


if __name__ == "__main__":
    main()
