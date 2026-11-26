#!/usr/bin/env bash
# Build and publish immutable snapshots of branch tips or explicit image tags.
set -euo pipefail
umask 027
branch="${1:-}"
phase="${2:-update}"
source_mode="${RETRODE3_SOURCE_MODE:-branch}"
case "$source_mode" in branch|tag) ;; *) echo "Invalid RETRODE3_SOURCE_MODE" >&2; exit 2 ;; esac
export RETRODE3_SOURCE_MODE="$source_mode"
build_only="${RETRODE3_BUILD_ONLY:-0}"
case "$build_only" in
  0|1) ;;
  *) echo "ERROR: RETRODE3_BUILD_ONLY must be 0 or 1" >&2; exit 2 ;;
esac
base=/srv/www/vhosts/retrode.com/buildserver
# Deployed launchers use an independently installed, tested automation copy.
# Never execute untagged develop automation files just because HEAD advanced.
script_dir="$(cd "$(dirname "$0")" && pwd)"
case "$branch" in
  develop) suite=testing; checkout="$base/src/retrode3-testing-pr" ;;
  master)  suite=stable;  checkout="$base/src/retrode3-stable-pr" ;;
  *) echo "Usage: $0 develop|master" >&2; exit 2 ;;
esac

failure_stage=startup
tag_worktree=
tag_workspace=
log=
on_exit() {
  local code=$?
  trap - EXIT
  if [[ -n "$tag_worktree" && -d "$tag_worktree" ]]; then
    rm -rf -- "$tag_worktree" ||
      echo "WARNING: could not remove temporary release checkout $tag_worktree" >&2
  fi
  if [[ -n "$tag_workspace" ]]; then
    rmdir "$tag_workspace" 2>/dev/null || true
  fi
  if (( code != 0 )); then
    local reporter="$script_dir/package-failure-alert.sh"
    if [[ -f "$reporter" ]]; then
      bash "$reporter" "$branch" "$code" "$failure_stage" "$log" ||
        echo "WARNING: could not save Retrode3 package failure report" >&2
    else
      echo "FAILED: Retrode3 package run $branch, stage $failure_stage, exit $code" >&2
    fi
  fi
  exit "$code"
}
trap on_exit EXIT

[[ "$(id -un)" == retrode ]] || {
  echo "ERROR: run as the unprivileged retrode user, never root" >&2; exit 1;
}
for executable in flock git python3 podman reprepro sha256sum; do
  command -v "$executable" >/dev/null || {
    echo "Missing program: $executable" >&2; exit 1;
  }
done
[[ -d "$checkout/.git" ]] || {
  echo "Missing Git checkout: $checkout" >&2; exit 1;
}
mkdir -p "$base/cache" "$base/artifacts/candidates/$suite" "$base/artifacts/logs"
# Shared lock serializes both APT suites and the published package pool.
if [[ "$phase" != updated || "${RETRODE3_AUTOMATION_LOCK_HELD:-0}" != 1 ]]; then
  exec 9>"$base/cache/package-automation.lock"
  flock -n 9 || { echo "ERROR: another package run is active" >&2; exit 1; }
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
  failure_stage=git-update
  echo "Fetching source branch $branch..."
  git -C "$checkout" fetch --tags --prune --prune-tags origin "$branch"
  git -C "$checkout" merge --ff-only FETCH_HEAD
  [[ "$(git -C "$checkout" rev-parse HEAD)" == "$(git -C "$checkout" rev-parse FETCH_HEAD)" ]] || {
    echo "Local branch contains unpublished commits" >&2; exit 1;
  }
  # Use the updated automation implementation while holding the same lock.
  exec bash "$script_dir/auto-package.sh" "$branch" updated
elif [[ "$phase" != updated ]]; then
  echo "ERROR: invalid automation stage" >&2; exit 2
fi

failure_stage=source-selection
selector="$script_dir/select-release-tag.py"
os_tag=; oscr_tag=
if [[ "$source_mode" == tag ]]; then
  selection="$(python3 "$selector" "$checkout" "$branch")"
  IFS=
oscr_url=https://github.com/DragonBox-Shop/retrode3-oscr.git
oscr_history="$base/cache/oscr-git-history.git"
if [[ ! -d "$oscr_history" ]]; then
  git init --quiet --bare "$oscr_history"
fi
# Fetch the branch *and* tags into a history-only cache. Tag moves are
# rejected by Git unless explicitly forced; never force-update release tags.
git --git-dir="$oscr_history" fetch --quiet --tags --prune --prune-tags \
    "$oscr_url" "+refs/heads/$branch:refs/heads/$branch"
if [[ "$source_mode" == tag ]]; then
  selection="$(python3 "$selector" "$oscr_history" "$branch")"
  IFS=
failure_stage=release-worktree
tag_workspace="$(mktemp -d "$base/cache/.apt-tag-$branch.XXXXXXXX")"
tag_worktree="$tag_workspace/source"
# A linked Git worktree has a .git pointer outside the Podman source mount.
# Use a self-contained local clone so Git provenance checks work inside /src.
git clone --quiet --no-local "$checkout" "$tag_worktree"
git -C "$tag_worktree" checkout --quiet --detach "$os_sha"
[[ "$(git -C "$tag_worktree" rev-parse HEAD)" == "$os_sha" ]] || exit 1
# The automation runs from the updated branch, but ALL package source files
# are mounted from the immutable detached tag checkout.
export RETRODE3_PACKAGE_SOURCE_ROOT="$tag_worktree"
export RETRODE3_RELEASE_TAG="$os_tag"
export RETRODE3_RELEASE_COMMIT="$os_sha"
export RETRODE3_OSCR_TAG="$oscr_tag"
export RETRODE3_OSCR_HISTORY="$oscr_history"
export RETRODE3_FOLLOW_OSCR_BRANCH=1
export RETRODE3_OSCR_BRANCH="$branch"
export RETRODE3_OSCR_COMMIT="$oscr_sha"
export RETRODE3_AUTO_VERSION=1
export RETRODE3_VERSION_STAMP="$(date -u +%Y%m%d%H%M%S%N)"
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"

failure_stage=release-state-check
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" "$branch" <<'PY'
import json
import subprocess
import sys

state, base, suite, os_sha, os_tag, oscr_sha, oscr_tag, branch = sys.argv[1:]
try:
    with open(state, encoding="utf-8") as stream:
        data = json.load(stream)
    if (data.get("release_channel") != suite or
            data.get("os_commit") != os_sha or
            (os_tag and data.get("os_tag") != os_tag) or
            data.get("oscr_commit") != oscr_sha or
            (oscr_tag and data.get("oscr_tag") != oscr_tag) or
            data.get("oscr_branch") != branch or
            not data.get("auto_versioned") or not data.get("packages")):
        sys.exit(1)
    indexed = set()
    text = subprocess.check_output(
        ["reprepro", "--basedir", base, "list", suite], text=True)
    for line in text.splitlines():
        prefix, separator, payload = line.partition(": ")
        if separator and prefix.startswith(suite + "|"):
            indexed.add(tuple(payload.rsplit(" ", 1)))
    for record in data["packages"]:
        name = record["package"]
        version = (data["web_version"] if name in
                   ("retrode3-web-control", "retrode3-tools", "retrode3-udev-rules")
                   else data["native_version"])
        if (name, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
PY
then
  echo "Nothing to build or publish: selected source commits already indexed."
  exit 0
fi
save_published_manifest() {
  local candidate="$1" tmp
  tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
  cp "$candidate" "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$state"
}

# Reuse only a candidate built from the exact SAME TWO TAGS/COMMITS.
failure_stage=candidate-resume
for manifest in "$RETRODE3_OUTPUT_BASE"/run.*/build-manifest.json; do
  [[ -f "$manifest" ]] || continue
  if ! python3 - "$manifest" "$suite" "$branch" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" "$state" <<'PY'
import json
import os
import subprocess
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        m = json.load(stream)
    expected = {
        "release_channel": sys.argv[2], "oscr_branch": sys.argv[3],
        "os_commit": sys.argv[4], "os_tag": sys.argv[5] or None,
        "oscr_commit": sys.argv[6], "oscr_tag": sys.argv[7] or None}
    if any(m.get(key) != value for key, value in expected.items()):
        sys.exit(1)
    if not m.get("auto_versioned") or not m.get("packages"):
        sys.exit(1)
    if os.path.isfile(sys.argv[8]):
        with open(sys.argv[8]) as stream:
            old = json.load(stream)
        for key in ("native_version", "web_version"):
            if subprocess.call(["dpkg", "--compare-versions", m[key], "ge", old[key]]):
                sys.exit(1)
except (OSError, ValueError, KeyError):
    sys.exit(1)
PY
  then
    continue
  fi
  run="${manifest%/build-manifest.json}"
  echo "Resuming exact source candidate: $run"
  if [[ "$build_only" == 1 ]]; then
    echo "BUILD ONLY: existing candidate $run; APT unchanged."
    exit 0
  fi
  failure_stage=apt-publication
  log="$base/artifacts/logs/$branch-resume-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
  bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee "$log"
  save_published_manifest "$manifest"
  echo "DONE: resumed $branch -> $suite from $os_sha / $oscr_sha"
  exit 0
done

log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
failure_stage=package-build
echo "Building selected source packages. Log: $log"
bash "$script_dir/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
[[ -n "$run" && -f "$run/build-manifest.json" ]] || {
  echo "ERROR: package build did not produce a valid manifest" >&2; exit 1;
}
if [[ "$build_only" == 1 ]]; then
  echo "BUILD ONLY: source candidate ready at $run; no APT changes."
  echo "To publish, unlock GPG and run package_$branch.sh again."
  exit 0
fi
failure_stage="apt-publication"
bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
save_published_manifest "$run/build-manifest.json"
echo "DONE: $branch -> $suite from $os_sha / $oscr_sha; log: $log"
\t' read -r os_tag os_sha <<< "$selection"
  [[ -n "$os_tag" ]] || exit 1
else
  os_sha="$(git -C "$checkout" rev-parse "refs/heads/$branch")"
fi
[[ "$os_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
oscr_url=https://github.com/DragonBox-Shop/retrode3-oscr.git
oscr_history="$base/cache/oscr-git-history.git"
if [[ ! -d "$oscr_history" ]]; then
  git init --quiet --bare "$oscr_history"
fi
# Fetch the branch *and* tags into a history-only cache. Tag moves are
# rejected by Git unless explicitly forced; never force-update release tags.
git --git-dir="$oscr_history" fetch --quiet --tags --prune --prune-tags \
    "$oscr_url" "+refs/heads/$branch:refs/heads/$branch"
selection="$(python3 "$selector" "$oscr_history" "$branch")"
IFS=$'\t' read -r oscr_tag oscr_sha <<< "$selection"
[[ "$oscr_sha" =~ ^[a-f0-9]{40}$ && -n "$oscr_tag" ]] || exit 1

echo "Tagged APT snapshot: OS $os_tag ($os_sha); OSCR $oscr_tag ($oscr_sha); $suite"
failure_stage=release-worktree
tag_workspace="$(mktemp -d "$base/cache/.apt-tag-$branch.XXXXXXXX")"
tag_worktree="$tag_workspace/source"
# A linked Git worktree has a .git pointer outside the Podman source mount.
# Use a self-contained local clone so Git provenance checks work inside /src.
git clone --quiet --no-local "$checkout" "$tag_worktree"
git -C "$tag_worktree" checkout --quiet --detach "$os_sha"
[[ "$(git -C "$tag_worktree" rev-parse HEAD)" == "$os_sha" ]] || exit 1
# The automation runs from the updated branch, but ALL package source files
# are mounted from the immutable detached tag checkout.
export RETRODE3_PACKAGE_SOURCE_ROOT="$tag_worktree"
export RETRODE3_RELEASE_TAG="$os_tag"
export RETRODE3_RELEASE_COMMIT="$os_sha"
export RETRODE3_OSCR_TAG="$oscr_tag"
export RETRODE3_FOLLOW_OSCR_BRANCH=1
export RETRODE3_OSCR_BRANCH="$branch"
export RETRODE3_OSCR_COMMIT="$oscr_sha"
export RETRODE3_AUTO_VERSION=1
export RETRODE3_VERSION_STAMP="$(date -u +%Y%m%d%H%M%S%N)"
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"

failure_stage=release-state-check
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" "$branch" <<'PY'
import json
import subprocess
import sys

state, base, suite, os_sha, os_tag, oscr_sha, oscr_tag, branch = sys.argv[1:]
try:
    with open(state, encoding="utf-8") as stream:
        data = json.load(stream)
    if (data.get("release_channel") != suite or
            data.get("os_commit") != os_sha or
            data.get("os_tag") != os_tag or
            data.get("oscr_commit") != oscr_sha or
            data.get("oscr_tag") != oscr_tag or
            data.get("oscr_branch") != branch or
            not data.get("auto_versioned") or not data.get("packages")):
        sys.exit(1)
    indexed = set()
    text = subprocess.check_output(
        ["reprepro", "--basedir", base, "list", suite], text=True)
    for line in text.splitlines():
        prefix, separator, payload = line.partition(": ")
        if separator and prefix.startswith(suite + "|"):
            indexed.add(tuple(payload.rsplit(" ", 1)))
    for record in data["packages"]:
        name = record["package"]
        version = (data["web_version"] if name in
                   ("retrode3-web-control", "retrode3-tools", "retrode3-udev-rules")
                   else data["native_version"])
        if (name, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
PY
then
  echo "Nothing to build or publish: tags $os_tag / $oscr_tag already indexed."
  exit 0
fi
save_published_manifest() {
  local candidate="$1" tmp
  tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
  cp "$candidate" "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$state"
}

# Reuse only a candidate built from the exact SAME TWO TAGS/COMMITS.
failure_stage=candidate-resume
for manifest in "$RETRODE3_OUTPUT_BASE"/run.*/build-manifest.json; do
  [[ -f "$manifest" ]] || continue
  if ! python3 - "$manifest" "$suite" "$branch" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        m = json.load(stream)
    expected = {
        "release_channel": sys.argv[2], "oscr_branch": sys.argv[3],
        "os_commit": sys.argv[4], "os_tag": sys.argv[5],
        "oscr_commit": sys.argv[6], "oscr_tag": sys.argv[7]}
    if any(m.get(key) != value for key, value in expected.items()):
        sys.exit(1)
    if not m.get("auto_versioned") or not m.get("packages"):
        sys.exit(1)
except (OSError, ValueError):
    sys.exit(1)
PY
  then
    continue
  fi
  run="${manifest%/build-manifest.json}"
  echo "Resuming exact source candidate: $run"
  if [[ "$build_only" == 1 ]]; then
    echo "BUILD ONLY: existing candidate $run; APT unchanged."
    exit 0
  fi
  failure_stage=apt-publication
  log="$base/artifacts/logs/$branch-resume-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
  bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee "$log"
  save_published_manifest "$manifest"
  echo "DONE: resumed $branch -> $suite from $os_tag / $oscr_tag"
  exit 0
done

log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
failure_stage=package-build
echo "Building tagged packages. Log: $log"
bash "$script_dir/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
[[ -n "$run" && -f "$run/build-manifest.json" ]] || {
  echo "ERROR: package build did not produce a valid manifest" >&2; exit 1;
}
if [[ "$build_only" == 1 ]]; then
  echo "BUILD ONLY: source candidate ready at $run; no APT changes."
  echo "To publish, unlock GPG and run package_$branch.sh again."
  exit 0
fi
failure_stage="apt-publication"
bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
save_published_manifest "$run/build-manifest.json"
echo "DONE: $branch -> $suite from tags $os_tag / $oscr_tag; log: $log"
\t' read -r oscr_tag oscr_sha <<< "$selection"
  [[ -n "$oscr_tag" ]] || exit 1
else
  oscr_sha="$(git --git-dir="$oscr_history" rev-parse "refs/heads/$branch")"
fi
[[ "$oscr_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1

state="$base/cache/last-published-$branch.json"
# A tagged image must not replace newer branch packages with older source,
# even if a fresh Debian timestamp would make that look like an upgrade.
if [[ -f "$state" ]]; then
  python3 - "$state" "$checkout" "$oscr_history" "$os_sha" "$oscr_sha" <<'PY'
import json, re, subprocess, sys
state, os_repo, oscr_repo, os_sha, oscr_sha = sys.argv[1:]
old = json.load(open(state))
for key, repo, sha in (("os_commit", ["git", "-C", os_repo], os_sha),
                       ("oscr_commit", ["git", "--git-dir=" + oscr_repo], oscr_sha)):
    previous = old.get(key, "")
    if not re.fullmatch(r"[0-9a-f]{40}", previous) or subprocess.call(
            repo + ["merge-base", "--is-ancestor", previous, sha]):
        sys.exit("Refusing source rollback/non-descendant for " + key + "; select a newer tested image tag or reconcile history.")
PY
fi
echo "APT snapshot ($source_mode): OS ${os_tag:-$branch} ($os_sha); OSCR ${oscr_tag:-$branch} ($oscr_sha); $suite"
failure_stage=release-worktree
tag_workspace="$(mktemp -d "$base/cache/.apt-tag-$branch.XXXXXXXX")"
tag_worktree="$tag_workspace/source"
# A linked Git worktree has a .git pointer outside the Podman source mount.
# Use a self-contained local clone so Git provenance checks work inside /src.
git clone --quiet --no-local "$checkout" "$tag_worktree"
git -C "$tag_worktree" checkout --quiet --detach "$os_sha"
[[ "$(git -C "$tag_worktree" rev-parse HEAD)" == "$os_sha" ]] || exit 1
# The automation runs from the updated branch, but ALL package source files
# are mounted from the immutable detached tag checkout.
export RETRODE3_PACKAGE_SOURCE_ROOT="$tag_worktree"
export RETRODE3_RELEASE_TAG="$os_tag"
export RETRODE3_RELEASE_COMMIT="$os_sha"
export RETRODE3_OSCR_TAG="$oscr_tag"
export RETRODE3_FOLLOW_OSCR_BRANCH=1
export RETRODE3_OSCR_BRANCH="$branch"
export RETRODE3_OSCR_COMMIT="$oscr_sha"
export RETRODE3_AUTO_VERSION=1
export RETRODE3_VERSION_STAMP="$(date -u +%Y%m%d%H%M%S%N)"
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"

failure_stage=release-state-check
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" "$branch" <<'PY'
import json
import subprocess
import sys

state, base, suite, os_sha, os_tag, oscr_sha, oscr_tag, branch = sys.argv[1:]
try:
    with open(state, encoding="utf-8") as stream:
        data = json.load(stream)
    if (data.get("release_channel") != suite or
            data.get("os_commit") != os_sha or
            data.get("os_tag") != os_tag or
            data.get("oscr_commit") != oscr_sha or
            data.get("oscr_tag") != oscr_tag or
            data.get("oscr_branch") != branch or
            not data.get("auto_versioned") or not data.get("packages")):
        sys.exit(1)
    indexed = set()
    text = subprocess.check_output(
        ["reprepro", "--basedir", base, "list", suite], text=True)
    for line in text.splitlines():
        prefix, separator, payload = line.partition(": ")
        if separator and prefix.startswith(suite + "|"):
            indexed.add(tuple(payload.rsplit(" ", 1)))
    for record in data["packages"]:
        name = record["package"]
        version = (data["web_version"] if name in
                   ("retrode3-web-control", "retrode3-tools", "retrode3-udev-rules")
                   else data["native_version"])
        if (name, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
PY
then
  echo "Nothing to build or publish: tags $os_tag / $oscr_tag already indexed."
  exit 0
fi
save_published_manifest() {
  local candidate="$1" tmp
  tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
  cp "$candidate" "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$state"
}

# Reuse only a candidate built from the exact SAME TWO TAGS/COMMITS.
failure_stage=candidate-resume
for manifest in "$RETRODE3_OUTPUT_BASE"/run.*/build-manifest.json; do
  [[ -f "$manifest" ]] || continue
  if ! python3 - "$manifest" "$suite" "$branch" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        m = json.load(stream)
    expected = {
        "release_channel": sys.argv[2], "oscr_branch": sys.argv[3],
        "os_commit": sys.argv[4], "os_tag": sys.argv[5],
        "oscr_commit": sys.argv[6], "oscr_tag": sys.argv[7]}
    if any(m.get(key) != value for key, value in expected.items()):
        sys.exit(1)
    if not m.get("auto_versioned") or not m.get("packages"):
        sys.exit(1)
except (OSError, ValueError):
    sys.exit(1)
PY
  then
    continue
  fi
  run="${manifest%/build-manifest.json}"
  echo "Resuming exact source candidate: $run"
  if [[ "$build_only" == 1 ]]; then
    echo "BUILD ONLY: existing candidate $run; APT unchanged."
    exit 0
  fi
  failure_stage=apt-publication
  log="$base/artifacts/logs/$branch-resume-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
  bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee "$log"
  save_published_manifest "$manifest"
  echo "DONE: resumed $branch -> $suite from $os_tag / $oscr_tag"
  exit 0
done

log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
failure_stage=package-build
echo "Building tagged packages. Log: $log"
bash "$script_dir/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
[[ -n "$run" && -f "$run/build-manifest.json" ]] || {
  echo "ERROR: package build did not produce a valid manifest" >&2; exit 1;
}
if [[ "$build_only" == 1 ]]; then
  echo "BUILD ONLY: source candidate ready at $run; no APT changes."
  echo "To publish, unlock GPG and run package_$branch.sh again."
  exit 0
fi
failure_stage="apt-publication"
bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
save_published_manifest "$run/build-manifest.json"
echo "DONE: $branch -> $suite from tags $os_tag / $oscr_tag; log: $log"
\t' read -r os_tag os_sha <<< "$selection"
  [[ -n "$os_tag" ]] || exit 1
else
  os_sha="$(git -C "$checkout" rev-parse "refs/heads/$branch")"
fi
[[ "$os_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
oscr_url=https://github.com/DragonBox-Shop/retrode3-oscr.git
oscr_history="$base/cache/oscr-git-history.git"
if [[ ! -d "$oscr_history" ]]; then
  git init --quiet --bare "$oscr_history"
fi
# Fetch the branch *and* tags into a history-only cache. Tag moves are
# rejected by Git unless explicitly forced; never force-update release tags.
git --git-dir="$oscr_history" fetch --quiet --tags --prune --prune-tags \
    "$oscr_url" "+refs/heads/$branch:refs/heads/$branch"
selection="$(python3 "$selector" "$oscr_history" "$branch")"
IFS=$'\t' read -r oscr_tag oscr_sha <<< "$selection"
[[ "$oscr_sha" =~ ^[a-f0-9]{40}$ && -n "$oscr_tag" ]] || exit 1

echo "Tagged APT snapshot: OS $os_tag ($os_sha); OSCR $oscr_tag ($oscr_sha); $suite"
failure_stage=release-worktree
tag_workspace="$(mktemp -d "$base/cache/.apt-tag-$branch.XXXXXXXX")"
tag_worktree="$tag_workspace/source"
# A linked Git worktree has a .git pointer outside the Podman source mount.
# Use a self-contained local clone so Git provenance checks work inside /src.
git clone --quiet --no-local "$checkout" "$tag_worktree"
git -C "$tag_worktree" checkout --quiet --detach "$os_sha"
[[ "$(git -C "$tag_worktree" rev-parse HEAD)" == "$os_sha" ]] || exit 1
# The automation runs from the updated branch, but ALL package source files
# are mounted from the immutable detached tag checkout.
export RETRODE3_PACKAGE_SOURCE_ROOT="$tag_worktree"
export RETRODE3_RELEASE_TAG="$os_tag"
export RETRODE3_RELEASE_COMMIT="$os_sha"
export RETRODE3_OSCR_TAG="$oscr_tag"
export RETRODE3_FOLLOW_OSCR_BRANCH=1
export RETRODE3_OSCR_BRANCH="$branch"
export RETRODE3_OSCR_COMMIT="$oscr_sha"
export RETRODE3_AUTO_VERSION=1
export RETRODE3_VERSION_STAMP="$(date -u +%Y%m%d%H%M%S%N)"
export RETRODE3_BUILD_CPUS="${RETRODE3_BUILD_CPUS:-2}"
export RETRODE3_BUILD_MEMORY="${RETRODE3_BUILD_MEMORY:-2g}"
export RETRODE3_BUILD_PIDS="${RETRODE3_BUILD_PIDS:-256}"
export RETRODE3_OUTPUT_BASE="$base/artifacts/candidates/$suite"
export GNUPGHOME="$base/repository/gnupg"
state="$base/cache/last-published-$branch.json"
repo_base="$base/repository"

failure_stage=release-state-check
if [[ -f "$state" ]] && python3 - "$state" "$repo_base" "$suite" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" "$branch" <<'PY'
import json
import subprocess
import sys

state, base, suite, os_sha, os_tag, oscr_sha, oscr_tag, branch = sys.argv[1:]
try:
    with open(state, encoding="utf-8") as stream:
        data = json.load(stream)
    if (data.get("release_channel") != suite or
            data.get("os_commit") != os_sha or
            data.get("os_tag") != os_tag or
            data.get("oscr_commit") != oscr_sha or
            data.get("oscr_tag") != oscr_tag or
            data.get("oscr_branch") != branch or
            not data.get("auto_versioned") or not data.get("packages")):
        sys.exit(1)
    indexed = set()
    text = subprocess.check_output(
        ["reprepro", "--basedir", base, "list", suite], text=True)
    for line in text.splitlines():
        prefix, separator, payload = line.partition(": ")
        if separator and prefix.startswith(suite + "|"):
            indexed.add(tuple(payload.rsplit(" ", 1)))
    for record in data["packages"]:
        name = record["package"]
        version = (data["web_version"] if name in
                   ("retrode3-web-control", "retrode3-tools", "retrode3-udev-rules")
                   else data["native_version"])
        if (name, version) not in indexed:
            sys.exit(1)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    sys.exit(1)
PY
then
  echo "Nothing to build or publish: tags $os_tag / $oscr_tag already indexed."
  exit 0
fi
save_published_manifest() {
  local candidate="$1" tmp
  tmp="$(mktemp "$base/cache/.last-published-XXXXXXXX")"
  cp "$candidate" "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$state"
}

# Reuse only a candidate built from the exact SAME TWO TAGS/COMMITS.
failure_stage=candidate-resume
for manifest in "$RETRODE3_OUTPUT_BASE"/run.*/build-manifest.json; do
  [[ -f "$manifest" ]] || continue
  if ! python3 - "$manifest" "$suite" "$branch" "$os_sha" "$os_tag" "$oscr_sha" "$oscr_tag" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        m = json.load(stream)
    expected = {
        "release_channel": sys.argv[2], "oscr_branch": sys.argv[3],
        "os_commit": sys.argv[4], "os_tag": sys.argv[5],
        "oscr_commit": sys.argv[6], "oscr_tag": sys.argv[7]}
    if any(m.get(key) != value for key, value in expected.items()):
        sys.exit(1)
    if not m.get("auto_versioned") or not m.get("packages"):
        sys.exit(1)
except (OSError, ValueError):
    sys.exit(1)
PY
  then
    continue
  fi
  run="${manifest%/build-manifest.json}"
  echo "Resuming exact source candidate: $run"
  if [[ "$build_only" == 1 ]]; then
    echo "BUILD ONLY: existing candidate $run; APT unchanged."
    exit 0
  fi
  failure_stage=apt-publication
  log="$base/artifacts/logs/$branch-resume-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
  bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee "$log"
  save_published_manifest "$manifest"
  echo "DONE: resumed $branch -> $suite from $os_tag / $oscr_tag"
  exit 0
done

log="$base/artifacts/logs/$branch-$(date -u +%Y%m%dT%H%M%SZ)-${os_sha:0:12}.log"
failure_stage=package-build
echo "Building tagged packages. Log: $log"
bash "$script_dir/run-debs.sh" 2>&1 | tee "$log"
run="$(sed -n 's/^Unpublished packages: //p' "$log" | tail -n 1)"
[[ -n "$run" && -f "$run/build-manifest.json" ]] || {
  echo "ERROR: package build did not produce a valid manifest" >&2; exit 1;
}
if [[ "$build_only" == 1 ]]; then
  echo "BUILD ONLY: source candidate ready at $run; no APT changes."
  echo "To publish, unlock GPG and run package_$branch.sh again."
  exit 0
fi
failure_stage="apt-publication"
bash "$script_dir/publish-debs.sh" "$branch" "$run" 2>&1 | tee -a "$log"
save_published_manifest "$run/build-manifest.json"
echo "DONE: $branch -> $suite from tags $os_tag / $oscr_tag; log: $log"
