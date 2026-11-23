#!/usr/bin/env bash
# Build and publish the requested branch after a fast-forward-only Git update.
# Entry points are installed in /srv/www/vhosts/retrode.com.
set -euo pipefail
umask 027
branch="${1:-}"
phase="${2:-update}"
base=/srv/www/vhosts/retrode.com/buildserver
case "$branch" in
  develop) suite=testing; checkout="$base/src/retrode3-testing-pr" ;;
  master)  suite=stable;  checkout="$base/src/retrode3-stable-pr" ;;
  *) echo "Usage: $0 develop|master" >&2; exit 2 ;;
esac
if [[ "$(id -un)" != retrode ]]; then
  echo "ERROR: run as the unprivileged retrode user, never root" >&2
  exit 1
fi
for executable in flock git python3 podman reprepro sha256sum; do
  command -v "$executable" >/dev/null || {
    echo "Missing program: $executable" >&2; exit 1;
  }
done
[[ -d "$checkout/.git" ]] || {
  echo "Missing Git checkout: $checkout" >&2; exit 1;
}
mkdir -p "$base/cache" "$base/artifacts/candidates/$suite" "$base/artifacts/logs"
# One lock protects both suites and reprepro's shared package pool.
exec 9>"$base/cache/package-automation.lock"
if ! flock -n 9; then
  echo "ERROR: another Retrode3 package run is active" >&2
  exit 1
fi
current_branch="$(git -C "$checkout" symbolic-ref --quiet --short HEAD)" || {
  echo "ERROR: checkout is detached: $checkout" >&2; exit 1;
}
[[ "$current_branch" == "$branch" ]] || {
  echo "ERROR: checkout is on $current_branch; expected $branch" >&2; exit 1;
}
[[ -z "$(git -C "$checkout" status --porcelain --untracked-files=no)" ]] || {
  echo "ERROR: tracked files have local modifications; not updating" >&2; exit 1;
}
if [[ "$phase" == update ]]; then
  echo "Updating $branch from origin (fast-forward only)..."
  git -C "$checkout" fetch origin "$branch"
  git -C "$checkout" merge --ff-only FETCH_HEAD
  # Execute the updated automation code, not the version read before fetch.
  exec bash "$checkout/buildserver/auto-package.sh" "$branch" updated
elif [[ "$phase" != updated ]]; then
  echo "ERROR: invalid automation stage" >&2; exit 2
fi
sha="$(git -C "$checkout" rev-parse HEAD)"
echo "OS Git $branch: $sha; APT: $suite"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$sha" <<'PY'
import json
import subprocess
import sys

manifest_path, base, suite, sha = sys.argv[1:]
try:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if (manifest.get("os_commit") != sha or
        manifest.get("release_channel") != suite or
        not manifest.get("auto_versioned")):
        sys.exit(1)
    existing = subprocess.check_output(
        ["reprepro", "--basedir", base, "list", suite], text=True)
    indexed = set()
    for line in existing.splitlines():
        prefix, separator, content = line.partition(": ")
        if separator and prefix.startswith(suite + "|"):
            name, version = content.rsplit(" ", 1)
            indexed.add((name, version))
    records = manifest.get("packages", [])
    if not records:
        sys.exit(1)
    for record in records:
        pkg = record["package"]
        version = (manifest["web_version"] if pkg == "retrode3-web-control"
                   else manifest["native_version"])
        if (pkg, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
sys.exit(0)
PY
then
  echo "Already published: $branch commit $sha. Nothing to do."
  exit 0
fi

export RETRODE3_AUTO_VERSION=1
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:12}.log"
echo "Building packages. Log: $log"
# Keep a durable log of both stages. Pipefail preserves the build's exit code.
bash "$checkout/buildserver/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
if [[ -z "$run" || ! -f "$run/build-manifest.json" ]]; then
  echo "ERROR: build did not produce a valid run directory" >&2
  exit 1
fi
echo "Publishing $branch -> $suite ..."
bash "$checkout/buildserver/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
# Save a state cache only after the publisher has returned success.
tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
cp "$run/build-manifest.json" "$tmp"
chmod 640 "$tmp"
mv -f "$tmp" "$state"
echo "DONE: $branch -> $suite (Git $sha); log: $log"
