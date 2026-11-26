#!/usr/bin/env python3
"""Publish only completed, verified development image files to the public website."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

IMAGE = "retrode3-develop.img.xz"
TAG = re.compile(r"apt-(\d{4}\.\d{2}\.\d{2}-rc[1-9][0-9]*)")
SHA = re.compile(r"[0-9a-f]{40}")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    return path.is_file() and not path.is_symlink()


def directory(path):
    path.mkdir(mode=0o755, exist_ok=True)
    require(path.is_dir() and not path.is_symlink(), "Unsafe directory: " + str(path))
    return path


def publish(repo, run, web, tag, commit):
    match = TAG.fullmatch(tag)
    require(match and SHA.fullmatch(commit), "Expected immutable apt-YYYY.MM.DD-rcN tag")
    version = match.group(1)
    require(web.is_dir() and not web.is_symlink() and (web / "wp-admin").is_dir(),
            "WordPress document root not found")
    require(run.is_dir() and not run.is_symlink(), "Invalid build directory")
    actual = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", "refs/tags/" + tag + "^{commit}"],
        text=True).strip()
    require(actual == commit, "Release tag does not match build commit")
    changelog = subprocess.check_output(
        ["git", "-C", str(repo), "show", commit + ":CHANGELOG.md"])
    require(("## " + version) in changelog.decode("utf-8").splitlines(),
            "Changelog must contain the exact release heading")
    manifest_path = run / "full-image-manifest.json"
    image = run / IMAGE
    require(regular(manifest_path) and regular(image), "Missing image or manifest")
    manifest = json.loads(manifest_path.read_text())
    require(manifest["branch"] == "develop" and manifest["apt_suite"] == "testing"
            and manifest["os_tag"] == tag and manifest["os_commit"] == commit
            and manifest["hardware_accepted"] is False and manifest["customer_releasable"] is False,
            "Not the expected unreleased development image")
    expected = manifest["files"][IMAGE]
    require(re.fullmatch(r"[0-9a-f]{64}", expected) and digest(image) == expected,
            "Image checksum mismatch")
    downloads = directory(web / "downloads")
    parent = directory(downloads / "develop")
    destination = parent / version
    if os.path.lexists(destination):
        require(destination.is_dir() and not destination.is_symlink(),
                "Unsafe existing release destination")
        require(regular(destination / IMAGE) and digest(destination / IMAGE) == expected
                and regular(destination / "CHANGELOG.md")
                and (destination / "CHANGELOG.md").read_bytes() == changelog
                and regular(destination / "SHA256SUMS")
                and regular(destination / "README.txt")
                and (destination / "SHA256SUMS").read_text() ==
                    expected + "  " + IMAGE + "\n",
                "Release already exists with different or incomplete files; never overwrite")
        return destination
    # Stage privately on the same filesystem, then expose the complete set
    # in a single rename. The caller holds the image-channel build lock.
    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=parent))
    try:
        shutil.copyfile(image, stage / IMAGE)
        require(digest(stage / IMAGE) == expected, "Copied image checksum mismatch")
        (stage / "CHANGELOG.md").write_bytes(changelog)
        (stage / "SHA256SUMS").write_text(expected + "  " + IMAGE + "\n", encoding="ascii")
        (stage / "README.txt").write_text(
            "Retrode3 Debian 12 - Development " + version + "\n\n"
            "Experimental image; hardware acceptance pending. Not a stable release.\n"
            "Write the decompressed image to an SD card. This erases all existing data on that card.\n"
            "Verify SHA256SUMS before use. See CHANGELOG.md for user-visible changes.\n",
            encoding="utf-8")
        for path in stage.iterdir():
            path.chmod(0o644)
        require(not os.path.lexists(destination), "Release destination appeared during copy")
        stage.chmod(0o755)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("web", type=Path)
    parser.add_argument("tag")
    parser.add_argument("commit")
    args = parser.parse_args()
    os.umask(0o022)
    try:
        destination = publish(args.repo, args.run, args.web, args.tag, args.commit)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "Development download publication failed: " + str(exc) + "\n")
    print("Public test download: https://retrode.com/downloads/develop/" +
          destination.name + "/" + IMAGE)


if __name__ == "__main__":
    main()
