#!/usr/bin/env bash
# Build and publish the requested branch after a fast-forward-only Git update.
# Entry points are installed in /srv/www/vhosts/retrode.com.
set -euo pipefail
umask 027
branch="${1:-}"
phase="${2:-update}"
# Build candidate packages first, without touching public APT. Set this to 1
# for a long MIPS build; unlock GPG only for the later publish invocation.
build_only="${RETRODE3_BUILD_ONLY:-0}"
case "$build_only" in
  0|1) ;;
  *) echo "ERROR: RETRODE3_BUILD_ONLY must be 0 or 1" >&2; exit 2 ;;
esac
base=/srv/www/vhosts/retrode.com/buildserver
case "$branch" in
  develop) suite=testing; checkout="$base/src/retrode3-testing-pr" ;;
  master)  suite=stable;  checkout="$base/src/retrode3-stable-pr" ;;
  *) echo "Usage: $0 develop|master" >&2; exit 2 ;;
esac

# Report failures even when the normal build log is not being watched.
# The EXIT trap preserves the original exit status and never retries publishing.
failure_stage="startup"
on_failure_exit() {
  local code=$?
  (( code != 0 )) || return 0
  local reporter="$checkout/buildserver/package-failure-alert.sh"
  if [[ -f "$reporter" ]]; then
    bash "$reporter" "$branch" "$code" "$failure_stage" "${log:-}" ||
      printf 'WARNING: could not save Retrode3 package failure report\n' >&2
  else
    printf 'FAILED: Retrode3 package run %s, stage %s, exit %s\n' \
      "$branch" "$failure_stage" "$code" >&2
  fi
}
trap on_failure_exit EXIT

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
# Preserve the same open file descriptor across the update/re-exec.
if [[ "$phase" != updated || "${RETRODE3_AUTOMATION_LOCK_HELD:-0}" != 1 ]]; then
  exec 9>"$base/cache/package-automation.lock"
  if ! flock -n 9; then
    echo "ERROR: another Retrode3 package run is active" >&2
    exit 1
  fi
  export RETRODE3_AUTOMATION_LOCK_HELD=1
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
  failure_stage="git-update"
  echo "Updating $branch from origin (fast-forward only)..."
  git -C "$checkout" fetch origin "$branch"
  git -C "$checkout" merge --ff-only FETCH_HEAD
  # Execute the updated automation code, not the version read before fetch.
  exec bash "$checkout/buildserver/auto-package.sh" "$branch" updated
elif [[ "$phase" != updated ]]; then
  echo "ERROR: invalid automation stage" >&2; exit 2
fi
failure_stage="source-resolution"
sha="$(git -C "$checkout" rev-parse HEAD)"
# Resolve exactly one OSCR branch head for the entire build; no floating checkout.
oscr_ref="refs/heads/$branch"
oscr_url="https://github.com/DragonBox-Shop/retrode3-oscr.git"
oscr_line="$(git ls-remote --exit-code "$oscr_url" "$oscr_ref")"
oscr_sha="${oscr_line%%[[:space:]]*}"
if [[ ! "$oscr_sha" =~ ^[a-f0-9]{40}$ ]]; then
  echo "ERROR: unable to resolve $oscr_ref from OSCR origin" >&2; exit 1
fi
export RETRODE3_FOLLOW_OSCR_BRANCH=1
export RETRODE3_OSCR_BRANCH="$branch"
export RETRODE3_OSCR_COMMIT="$oscr_sha"
# Fetch Git history only; do not check out or modify the OSCR project here.
# Needed to ignore documentation-only OSCR commits without new .deb files.
oscr_history="$base/cache/oscr-git-history.git"
if [[ ! -d "$oscr_history" ]]; then
  git init --quiet --bare "$oscr_history"
fi
git --git-dir="$oscr_history" fetch --quiet --no-tags "$oscr_url" \
    "+refs/heads/$branch:refs/heads/$branch"
if [[ "$(git --git-dir="$oscr_history" rev-parse "refs/heads/$branch")" != "$oscr_sha" ]]; then
  echo "ERROR: OSCR moved while selecting the build snapshot; retry" >&2
  exit 1
fi
echo "OS Git $branch: $sha; OSCR $branch: $oscr_sha; APT: $suite"
failure_stage="release-state-check"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$sha" "$checkout" "$oscr_sha" "$oscr_history" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

manifest_path, base, suite, sha, checkout, oscr_sha, oscr_history = sys.argv[1:]
try:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    previous = manifest.get("os_commit", "")
    if (not isinstance(previous, str) or
        not re.fullmatch(r"[0-9a-f]{40}", previous) or
        manifest.get("release_channel") != suite or
        manifest.get("oscr_branch") != ("master" if suite == "stable" else "develop") or
        not manifest.get("auto_versioned")):
        sys.exit(1)
    classifier = Path(checkout) / "buildserver/release-changes.py"
    if previous != sha:
        # Documentation, CI and publisher-only changes do not change .debs.
        result = subprocess.run(
            [sys.executable, str(classifier), "--repo", checkout,
             "--base", previous, "--head", sha],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            sys.exit(1)
    old_oscr = manifest.get("oscr_commit", "")
    if not isinstance(old_oscr, str) or not re.fullmatch(r"[0-9a-f]{40}", old_oscr):
        sys.exit(1)
    if old_oscr != oscr_sha:
        result = subprocess.run(
            [sys.executable, str(classifier), "--scope", "oscr",
             "--repo", oscr_history, "--base", old_oscr, "--head", oscr_sha],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
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
        version = (manifest["web_version"] if pkg in
                   ("retrode3-web-control", "retrode3-tools", "retrode3-udev-rules")
                   else manifest["native_version"])
        if (pkg, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
sys.exit(0)
PY
then
  echo "Already published: no package-affecting changes since the last release."
  echo "Nothing to build or publish for $branch ($sha)."
  exit 0
fi

export RETRODE3_AUTO_VERSION=1
export RETRODE3_VERSION_STAMP="$(date -u +%Y%m%d%H%M%S%N)"
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
save_published_manifest() {
  local source_manifest="$1" tmp
  tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
  cp "$source_manifest" "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$state"
}
# Resume a fully built candidate if the only source changes since building
# were fixes to this publisher. The publisher revalidates every archive.
failure_stage="candidate-resume"
for manifest in "$RETRODE3_OUTPUT_BASE"/run.*/build-manifest.json; do
  [[ -f "$manifest" ]] || continue
  candidate_commit="$(python3 - "$manifest" "$suite" "$oscr_sha" <<'PY'
import json
import re
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        m = json.load(stream)
    sha = m.get("os_commit", "")
    if (m.get("release_channel") != sys.argv[2] or
        m.get("oscr_commit") != sys.argv[3] or
        m.get("oscr_branch") != ("master" if sys.argv[2] == "stable" else "develop") or
        not m.get("auto_versioned") or
        not isinstance(sha, str) or
        not re.fullmatch(r"[0-9a-f]{40}", sha)):
        sys.exit(1)
    print(sha)
except (OSError, ValueError):
    sys.exit(1)
PY
  )" || continue
  # Resume only if all intervening changes are guaranteed non-shipping.
  if ! python3 "$checkout/buildserver/release-changes.py" \
      --repo "$checkout" --base "$candidate_commit" --head "$sha"; then
    continue
  fi
  run="${manifest%/build-manifest.json}"
  echo "Resuming already built candidate: $run"
  if [[ "$build_only" == 1 ]]; then
    echo "BUILD ONLY: verified candidate already exists at $run"
    echo "No APT packages were published by this invocation."
    exit 0
  fi
  bash "$checkout/buildserver/publish-debs.sh" "$branch" "$run"
  save_published_manifest "$manifest"
  echo "DONE: resumed $branch -> $suite from candidate $candidate_commit"
  exit 0
done
log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:12}.log"
failure_stage="package-build"
echo "Building packages. Log: $log"
# Keep a durable log of both stages. Pipefail preserves the build's exit code.
bash "$checkout/buildserver/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
if [[ -z "$run" || ! -f "$run/build-manifest.json" ]]; then
  echo "ERROR: build did not produce a valid run directory" >&2
  exit 1
fi
if [[ "$build_only" == 1 ]]; then
  echo "BUILD ONLY: candidate ready at $run"
  echo "No APT packages were published by this invocation."
  echo "To publish later, unlock the GPG key and run package_$branch.sh again."
  exit 0
fi
failure_stage="apt-publication"
echo "Publishing $branch -> $suite ..."
bash "$checkout/buildserver/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
# Save a state cache only after the publisher has returned success.
save_published_manifest "$run/build-manifest.json"
echo "DONE: $branch -> $suite (Git $sha); log: $log"
