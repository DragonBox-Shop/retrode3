#!/usr/bin/env bash
# Explicit, unpublished kernel-only build. Run as retrode on Amaterasu.
set -euo pipefail
umask 077
[[ "$#" == 1 && "$1" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Usage: bash $0 FULL_KERNEL_COMMIT_SHA" >&2; exit 2;
}
sha="$1"
[[ "$(id -un)" == retrode ]] || { echo "Run as retrode" >&2; exit 1; }
base=/srv/www/vhosts/retrode.com/buildserver
src="$(cd "$(dirname "$0")/.." && pwd -P)"
for cmd in git podman python3 dpkg-deb sha256sum flock tar; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 1; }
done
[[ -z "$(git -C "$src" status --porcelain --untracked-files=no)" ]] || {
  echo "Use a clean Git checkout" >&2; exit 1;
}
mkdir -p "$base/cache" "$base/private/kernel-tests"
exec 9>"$base/cache/package-automation.lock"
flock -n 9 || { echo "Another package build/publisher is running" >&2; exit 1; }
run="$(mktemp -d "$base/private/kernel-tests/run.XXXXXXXX")"
echo "Unpublished kernel test workspace: $run"
image=localhost/retrode3-kernel-test-builder:bookworm
podman --runtime=crun --cgroup-manager=systemd build \
  --network=slirp4netns -f "$src/buildserver/Containerfile.platform" \
  -t "$image" "$src/buildserver"
image_id="$(podman image inspect --format '{{.Id}}' "$image")"
if [[ "$image_id" =~ ^[a-f0-9]{64}$ ]]; then image_id="sha256:$image_id"; fi
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
recipe_sha="$(sha256sum "$src/buildserver/build-kernel-test.sh" | cut -d' ' -f1)"
# Deliberately sorts below release package versions; never feed into APT.
version="0~retrode3test+$(date -u +%Y%m%d%H%M%S)+git${sha:0:12}-1"
podman --runtime=crun --cgroup-manager=systemd run --rm -i \
  --network=slirp4netns --cap-drop=all \
  --cap-add=CHOWN --cap-add=FOWNER --cap-add=SETUID \
  --cap-add=SETGID --cap-add=DAC_OVERRIDE \
  --security-opt=no-new-privileges \
  --cpus "${RETRODE3_PLATFORM_CPUS:-2}" \
  --memory "${RETRODE3_PLATFORM_MEMORY:-3g}" \
  --pids-limit "${RETRODE3_PLATFORM_PIDS:-512}" \
  -v "$run:/out:rw" "$image" bash -s -- "$sha" "$version" <<'BUILD' 2>&1 | tee "$run/build.log"
set -euo pipefail
sha="$1"; version="$2"
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
mkdir -p /work/source
git -C /work/source init --quiet
git -C /work/source remote add origin https://github.com/DragonBox-Shop/retrode3-kernel.git
git -C /work/source fetch --quiet --depth 1 --no-tags origin "$sha"
git -C /work/source checkout --quiet --detach FETCH_HEAD
[[ "$(git -C /work/source rev-parse HEAD)" == "$sha" ]] || exit 1
export SOURCE_DATE_EPOCH="$(git -C /work/source show -s --format=%ct HEAD)"
bash /work/source/packaging/retrode3/build-debs.sh /out "$version"
BUILD
# Validate matching packages and construct a bundle for an OFFLINE spare SD.
img="$run/retrode3-linux-image_${version}_mipsel.deb"
mod="$run/retrode3-linux-modules_${version}_mipsel.deb"
shopt -s nullglob
debs=("$run"/*.deb)
[[ "${#debs[@]}" == 2 ]] || exit 1
for pkg in retrode3-linux-image retrode3-linux-modules; do
  file="$run/${pkg}_${version}_mipsel.deb"
  [[ -f "$file" && ! -L "$file" ]] || exit 1
  [[ "$(dpkg-deb -f "$file" Package)" == "$pkg" &&
     "$(dpkg-deb -f "$file" Version)" == "$version" &&
     "$(dpkg-deb -f "$file" Architecture)" == mipsel ]] || exit 1
done
stage="$(mktemp -d "$run/stage.XXXXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
dpkg-deb -x "$img" "$stage"
dpkg-deb -x "$mod" "$stage"
root="$stage/usr/lib/retrode3/kernel-candidates/$version"
krel="$(cat "$root/kernel-release")"
[[ "$krel" =~ ^[A-Za-z0-9.+_-]+$ ]] || exit 1
[[ -s "$root/boot/uImage" &&
   -s "$root/boot/ingenic/lx16-retrode-2.9.5.dtb" &&
   -s "$root/lib/modules/$krel/modules.dep" &&
   -s "$root/lib/modules/$krel/kernel/drivers/misc/retrode3/retrode3.ko" ]] || exit 1
if [[ -s "$root/boot/config-$krel" ]]; then
  cp "$root/boot/config-$krel" "$run/effective.config"
fi
tar --owner=0 --group=0 --numeric-owner -C "$root" -czf "$run/kernel-bundle.tar.gz" boot lib
python3 - "$run" "$sha" "$version" "$image_id" "$recipe_sha" "$krel" <<'PY'
import hashlib, json, pathlib, sys
run, commit, version, image, recipe, release = sys.argv[1:]
root = pathlib.Path(run)
files = sorted(root.glob("*.deb")) + [root / "kernel-bundle.tar.gz", root / "build.log"]
if (root / "effective.config").is_file():
    files.append(root / "effective.config")
hashes = {}
for p in files:
    with p.open("rb") as f:
        hashes[p.name] = hashlib.file_digest(f, "sha256").hexdigest()
doc = dict(schema=1, kind="kernel-test", commit=commit, version=version,
           kernel_release=release, builder_image_id=image, recipe_sha256=recipe,
           apt_published=False, hardware_accepted=False, files=hashes)
(root / "kernel-test-manifest.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
PY
(
  cd "$run"
  files=( *.deb kernel-bundle.tar.gz build.log kernel-test-manifest.json )
  [[ ! -f effective.config ]] || files+=(effective.config)
  sha256sum "${files[@]}" > SHA256SUMS
  sha256sum -c --strict SHA256SUMS
)
echo "Unpublished kernel test complete: $run"
echo "No APT publication, U-Boot build, image build or live installation performed."
