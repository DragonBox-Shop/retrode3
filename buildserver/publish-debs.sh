#!/usr/bin/env bash
# Explicit publish only; never invoked from the cross-build automatically.
set -euo pipefail
umask 027
if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 develop|master /absolute/path/to/run.XXXXXXXX" >&2
  exit 2
fi
branch="$1"
run="$2"
case "$branch" in
  develop) suite=testing ;;
  master) suite=stable ;;
  *) echo "error: unknown Git branch: $branch" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
actual_branch="$(git -C "$root" symbolic-ref --quiet --short HEAD)" || {
  echo "error: publish from a named Git branch, not a detached worktree" >&2
  exit 1
}
if [[ "$actual_branch" != "$branch" ]]; then
  echo "error: checkout branch $actual_branch does not match $branch" >&2
  exit 1
fi
test -z "$(git -C "$root" status --porcelain --untracked-files=no)" || {
  echo "error: checkout contains modified tracked files" >&2; exit 1
}
[[ "$run" = /* && -f "$run/build-manifest.json" && -f "$run/SHA256SUMS" ]] || {
  echo "error: use an absolute build run directory with manifest and checksums" >&2
  exit 1
}
base="${RETRODE3_APT_BASE:-/srv/www/vhosts/retrode.com/buildserver/repository}"
public="${RETRODE3_APT_PUBLIC:-/srv/www/vhosts/retrode.com/domains/packages.retrode.com/httpdocs}"
export GNUPGHOME="${GNUPGHOME:-$base/gnupg}"
test -r "$base/conf/distributions"
test -d "$public"
(cd "$run" && sha256sum --check --strict SHA256SUMS)
# Verify the complete set before the FIRST reprepro import.
python3 - "$run" "$suite" "$root" "$public" "$base" <<'PY'
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

run, suite, root = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
pool = pathlib.Path(sys.argv[4]) / "pool"
repo_base = pathlib.Path(sys.argv[5])
manifest = json.loads((run / "build-manifest.json").read_text())
lock = json.loads((root / "packaging/native-source-lock.json").read_text())
if manifest.get("release_channel") != suite or lock.get("release_channel") != suite:
    sys.exit("error: manifest/source release channel differs from requested suite")
head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                               text=True).strip()
candidate_commit = manifest.get("os_commit", "")
if not isinstance(candidate_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", candidate_commit):
    sys.exit("error: missing or invalid source Git commit in build manifest")
if candidate_commit != head:
    # A publish-script-only fix does not change the package payload.
    if subprocess.call(["git", "-C", str(root), "merge-base", "--is-ancestor",
                        candidate_commit, head]) != 0:
        sys.exit("error: candidate source is not an ancestor of current branch")
    changed = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--name-only",
         candidate_commit, head, "--"], text=True).splitlines()
    if not set(changed).issubset({"buildserver/publish-debs.sh",
                                   "buildserver/auto-package.sh"}):
        sys.exit("error: source changed since build; rebuild required: " +
                 ", ".join(changed))
    print("Validated publish-only change since candidate commit", candidate_commit)
auto = os.environ.get("RETRODE3_AUTO_VERSION", "0") == "1"
if bool(manifest.get("auto_versioned", False)) != auto:
    sys.exit("error: automatic-version mode differs from build manifest")
if auto:
    spec = importlib.util.spec_from_file_location(
        "retrode3_package_builder", str(root / "packaging/build-debs.py"))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    commit_epoch = int(subprocess.check_output(
        ["git", "-C", str(root), "show", "-s", "--format=%ct",
         candidate_commit], text=True).strip())
    lock = builder.auto_version_lock(lock, candidate_commit, commit_epoch)
for key in ("oscr_commit", "sanni_commit", "native_version", "web_version"):
    if manifest.get(key) != lock.get(key):
        sys.exit("error: manifest/source lock mismatch: " + key)
files = sorted(run.glob("*.deb"))
records = manifest.get("packages", [])
if not files or len(files) != len(records):
    sys.exit("error: manifest package count does not match files")
expected = {x["filename"]: x for x in records}
if len(expected) != len(records) or set(expected) != {x.name for x in files}:
    sys.exit("error: manifest package file set differs from build output")
# Refuse a downgrade or same-version rewrite before importing any packages.
indexed = subprocess.check_output(
    ["reprepro", "--basedir", str(repo_base), "list", suite],
    text=True)
previous = {}
for line in indexed.splitlines():
    prefix, sep, payload = line.partition(": ")
    if not sep or not prefix.startswith(suite + "|"):
        continue
    name, version = payload.rsplit(" ", 1)
    old = previous.get(name)
    if old is None or subprocess.call(
            ["dpkg", "--compare-versions", version, "gt", old]) == 0:
        previous[name] = version
for file in files:
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    if digest != expected[file.name]["sha256"]:
        sys.exit("error: package hash differs from manifest: " + file.name)
    # All suites share one pool: reject same-name/different-bytes conflicts
    # for the WHOLE candidate set before importing its first package.
    for existing in pool.rglob(file.name):
        if existing.is_symlink() or not existing.is_file():
            sys.exit("error: unsafe APT pool entry: " + str(existing))
        if hashlib.sha256(existing.read_bytes()).hexdigest() != digest:
            sys.exit("error: same package filename with different contents "
                     "already exists in APT pool: " + str(existing) +
                     "; bump Debian revision and rebuild")
    info = [
        subprocess.check_output(["dpkg-deb", "-f", str(file), field],
                                text=True).strip()
        for field in ("Package", "Version", "Architecture")
    ]
    if len(info) != 3 or info[0] != expected[file.name]["package"]:
        sys.exit("error: package metadata mismatch: " + file.name)
    if info[1] != (lock["web_version"] if info[0] == "retrode3-web-control"
                   else lock["native_version"]):
        sys.exit("error: version mismatch: " + file.name)
    if info[2] != ("all" if info[0] == "retrode3-web-control" else "mipsel"):
        sys.exit("error: architecture mismatch: " + file.name)
    old = previous.get(info[0])
    if old == info[1]:
        matches = list(pool.rglob(file.name))
        if len(matches) != 1 or not matches[0].is_file() or (
                hashlib.sha256(matches[0].read_bytes()).hexdigest() != digest):
            sys.exit("error: suite package is already registered but its "
                     "pool archive is missing or differs: " + file.name)
    elif old is not None and subprocess.call(
            ["dpkg", "--compare-versions", info[1], "gt", old]) != 0:
        sys.exit("error: published " + suite + " version " + old +
                 " of " + info[0] + " is newer than " + info[1] +
                 "; refusing downgrade")
print("Preflight OK:", suite, len(files), "packages, OS", head)
PY
for deb in "$run"/*.deb; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  version="$(dpkg-deb -f "$deb" Version)"
  if reprepro --basedir "$base" list "$suite" |
      grep -Fqx "$suite|main|mipsel: $pkg $version"; then
    echo "Already published, verified in preflight: $pkg $version"
    continue
  fi
  reprepro --basedir "$base" --outdir "$public" includedeb "$suite" "$deb"
done
reprepro --basedir "$base" --outdir "$public" list "$suite"
echo "Published to APT $suite. Run: $run"
