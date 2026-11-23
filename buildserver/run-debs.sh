#!/usr/bin/env bash
# Rootless host wrapper. Explicit limits, no repository publication.
set -euo pipefail
umask 027
root="$(cd "$(dirname "$0")/.." && pwd)"
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
podman --runtime=crun --cgroup-manager=systemd run --rm \
    --network=slirp4netns --userns=keep-id \
    --user "$(id -u):$(id -g)" --cap-drop=all \
    --security-opt=no-new-privileges \
    --cpus "${RETRODE3_BUILD_CPUS:-2}" \
    --memory "${RETRODE3_BUILD_MEMORY:-2g}" \
    --pids-limit "${RETRODE3_BUILD_PIDS:-256}" \
    -v "$root:/src:ro" -v "$out:/out:rw" \
    -e "SOURCE_DATE_EPOCH=$epoch" \
    "$image" bash /src/buildserver/build-debs.sh
echo "Unpublished packages: $out"
