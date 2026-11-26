#!/usr/bin/env bash
# Private firmware package build. No APT publication, target install or flashing.
set -euo pipefail
umask 027
root="$(cd "$(dirname "$0")/.." && pwd)"
sha="$(git -C "$root" rev-parse HEAD)"
[[ -z "$(git -C "$root" status --porcelain --untracked-files=no)" ]] ||
  { echo "Refusing modified tracked sources" >&2; exit 1; }
base="${RETRODE3_ESP_TEST_OUTPUT:-$root/build/esp-tests}"
mkdir -p "$base"
out="$(mktemp -d "$base/run.XXXXXXXX")"
out="$(cd "$out" && pwd)"
image=localhost/retrode3-deb-builder:bookworm
podman image exists "$image" ||
  podman build --network=slirp4netns -f "$root/buildserver/Containerfile" \
    -t "$image" "$root/buildserver"
podman run --rm --network=none --userns=keep-id \
  --user "$(id -u):$(id -g)" --cap-drop=all --security-opt=no-new-privileges \
  -v "$root/firmware/esp32c6:/src:ro" -v "$out:/out:rw" \
  -e "SOURCE_DATE_EPOCH=$(git -C "$root" show -s --format=%ct HEAD)" \
  "$image" bash -eu -c '
    work=$(mktemp -d)
    cp -a /src/. "$work/"
    cd "$work"
    sh -n autorepair.sh
    sh -n autorepair.init
    sh -n build-deb.sh
    make clean
    make check
    make CROSS_COMPILE=mipsel-linux-gnu-
    sh build-deb.sh
    cp ./*.deb /out/
    (cd /out && sha256sum ./*.deb > SHA256SUMS)
  '
printf '%s\n' "$sha" > "$out/source-commit"
echo "Private untested ESP firmware candidate: $out"
