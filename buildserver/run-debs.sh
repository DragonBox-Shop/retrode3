#!/usr/bin/env bash
# Rootless host wrapper. Explicit limits, no repository publication.
set -euo pipefail
umask 027
root="${RETRODE3_PACKAGE_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ -d "$root/.git" || -f "$root/.git" ]] || {
  echo "Missing source Git checkout: $root" >&2; exit 1;
}
if [[ -n "${RETRODE3_RELEASE_COMMIT:-}" ]]; then
  [[ "$(git -C "$root" rev-parse HEAD)" == "$RETRODE3_RELEASE_COMMIT" ]] || exit 1
fi
if [[ -n "${RETRODE3_RELEASE_TAG:-}" ]]; then
  [[ "$(git -C "$root" rev-parse "refs/tags/$RETRODE3_RELEASE_TAG^{commit}")" == \
     "${RETRODE3_RELEASE_COMMIT:-}" ]] || {
    echo "Selected source tag/commit mismatch" >&2; exit 1;
  }
  [[ "$(git -C "$root" rev-parse HEAD)" == "$RETRODE3_RELEASE_COMMIT" ]] || exit 1
fi
test -f "$root/packaging/native-source-lock.json"
test -z "$(git -C "$root" status --porcelain --untracked-files=no)" || {
  echo "Refusing build with modified tracked files" >&2; exit 1;
}
epoch="$(git -C "$root" show -s --format=%ct HEAD)"
outbase="${RETRODE3_OUTPUT_BASE:-$root/build/candidates}"
mkdir -p "$outbase"
out="$(mktemp -d "$outbase/run.XXXXXXXX")"
image=localhost/retrode3-deb-builder:bookworm
podman --runtime=crun --cgroup-manager=systemd build \
    --network=slirp4netns -f "$root/buildserver/Containerfile" \
    -t "$image" "$root/buildserver"
# Only mount the immutable candidate matching the last published manifest.
# Never expose APT signing material or the public website to Podman.
previous_mount=()
previous_dir=
if [[ -f "${RETRODE3_PREVIOUS_MANIFEST:-}" && ! -L "$RETRODE3_PREVIOUS_MANIFEST" ]]; then
    for prior in "$outbase"/run.*; do
        [[ -d "$prior" && ! -L "$prior" && -f "$prior/build-manifest.json" &&
           ! -L "$prior/build-manifest.json" ]] || continue
        if cmp -s "$prior/build-manifest.json" "$RETRODE3_PREVIOUS_MANIFEST"; then
            previous_dir="$prior"
            previous_mount=(-v "$prior:/previous:ro")
            break
        fi
    done
fi
podman --runtime=crun --cgroup-manager=systemd run --rm \
    --network=slirp4netns --userns=keep-id \
    --user "$(id -u):$(id -g)" --cap-drop=all \
    --security-opt=no-new-privileges \
    --cpus "${RETRODE3_BUILD_CPUS:-2}" \
    --memory "${RETRODE3_BUILD_MEMORY:-2g}" \
    --pids-limit "${RETRODE3_BUILD_PIDS:-256}" \
    -v "$root:/src:ro" -v "$out:/out:rw" \
    "${previous_mount[@]}" \
    -e "SOURCE_DATE_EPOCH=$epoch" \
    -e "RETRODE3_AUTO_VERSION=${RETRODE3_AUTO_VERSION:-0}" \
    -e "RETRODE3_FOLLOW_OSCR_BRANCH=${RETRODE3_FOLLOW_OSCR_BRANCH:-0}" \
    -e "RETRODE3_OSCR_BRANCH=${RETRODE3_OSCR_BRANCH:-}" \
    -e "RETRODE3_OSCR_COMMIT=${RETRODE3_OSCR_COMMIT:-}" \
    -e "RETRODE3_VERSION_STAMP=${RETRODE3_VERSION_STAMP:-}" \
    -e "RETRODE3_RELEASE_TAG=${RETRODE3_RELEASE_TAG:-}" \
    -e "RETRODE3_RELEASE_COMMIT=${RETRODE3_RELEASE_COMMIT:-}" \
    -e "RETRODE3_OSCR_TAG=${RETRODE3_OSCR_TAG:-}" \
    "$image" bash /src/buildserver/build-debs.sh
# The complete candidate remains self-contained for offline verification.
# Hard-link already verified immutable archives on the host filesystem
# instead of retaining a separate physical copy in every build directory.
if [[ -n "$previous_dir" ]]; then
    python3 - "$previous_dir" "$out" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

previous, current = map(Path, sys.argv[1:])
manifest = json.loads((current / "build-manifest.json").read_text())
for record in manifest.get("packages", []):
    if not record.get("reused"):
        continue
    name = record["filename"]
    if not re.fullmatch(r"[a-z0-9-]+_[0-9][A-Za-z0-9.+:~_-]*_(?:all|mipsel)\.deb", name):
        sys.exit("Unsafe reused archive filename")
    old, new = previous / name, current / name
    for file in (old, new):
        if file.is_symlink() or not file.is_file() or (
                hashlib.sha256(file.read_bytes()).hexdigest() != record["sha256"]):
            sys.exit("Reused archive changed: " + name)
    # Both files are immutable candidates. If the filesystem cannot link
    # them, the already-verified copy remains a valid complete candidate.
    with tempfile.TemporaryDirectory(prefix=".reuse-", dir=current) as temp:
        target = Path(temp) / name
        try:
            os.link(old, target)
        except OSError:
            continue
        os.replace(target, new)
PY
fi
echo "Unpublished packages: $out"
