#!/usr/bin/env bash
# Build pinned kernel + U-Boot .debs only on cache miss, never publish implicitly.
set -euo pipefail
umask 027
[[ "$#" == 0 ]] || { echo "Usage: $0" >&2; exit 2; }
[[ "$(id -un)" == retrode ]] || { echo "Run as retrode" >&2; exit 1; }
base=/srv/www/vhosts/retrode.com/buildserver
src="$(cd "$(dirname "$0")/.." && pwd -P)"
cache="$base/artifacts/platform/cache"
runs="$base/artifacts/platform/candidates"
mkdir -p "$cache/kernel" "$cache/uboot" "$runs" "$base/cache"
exec 9>"$base/cache/package-automation.lock"
flock -n 9 || { echo "Package publisher/build already running" >&2; exit 1; }
for cmd in git podman python3 dpkg-deb sha256sum; do command -v "$cmd" >/dev/null || exit 1; done
image=localhost/retrode3-platform-builder:bookworm
podman --runtime=crun --cgroup-manager=systemd build \
  --network=slirp4netns -f "$src/buildserver/Containerfile.platform" \
  -t "$image" "$src/buildserver"
image_id="$(podman image inspect --format '{{.Id}}' "$image")"
# Podman reports image .Id as 64 hex characters (without "sha256:"),
# while other runtimes include the digest prefix. Normalize before the
# content-addressed cache key and before handing the ID to the container.
if [[ "$image_id" =~ ^[a-f0-9]{64}$ ]]; then
  image_id="sha256:$image_id"
fi
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  echo "Invalid Podman builder image ID: <$image_id>" >&2
  exit 1
}
recipe_sha="$(sha256sum "$src/buildserver/build-platform-component.sh" | cut -d' ' -f1)"
run="$(mktemp -d "$runs/run.XXXXXXXX")"
for kind in kernel uboot; do
  case "$kind" in
    kernel)
      url=https://github.com/DragonBox-Shop/retrode3-kernel.git
      ref=refs/heads/develop ;;
    uboot)
      url=https://github.com/DragonBox-Shop/retrode3-uboot.git
      ref=refs/heads/develop ;;
  esac
  line="$(git ls-remote --exit-code "$url" "$ref")"
  sha="${line%%[[:space:]]*}"
  [[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
  key="$(python3 "$src/buildserver/platform-cache.py" key "$kind" "$sha" "$image_id" "$recipe_sha")"
  entry="$cache/$kind/$key"
  if [[ -e "$entry" || -L "$entry" ]]; then
    python3 "$src/buildserver/platform-cache.py" verify "$kind" "$sha" "$image_id" "$recipe_sha" "$entry"
    echo "$kind: CACHE HIT $sha"
  else
    echo "$kind: CACHE MISS $sha, building .debs"
    temp="$(mktemp -d "$cache/$kind/.build.XXXXXXXX")"
    podman --runtime=crun --cgroup-manager=systemd run --rm \
      --network=slirp4netns --cap-drop=all \
      --cap-add=CHOWN --cap-add=FOWNER --cap-add=SETUID \
      --cap-add=SETGID --cap-add=DAC_OVERRIDE \
      --security-opt=no-new-privileges \
      --cpus "${RETRODE3_PLATFORM_CPUS:-2}" \
      --memory "${RETRODE3_PLATFORM_MEMORY:-3g}" \
      --pids-limit "${RETRODE3_PLATFORM_PIDS:-512}" \
      -v "$src:/src:ro" -v "$temp:/out:rw" \
      -e "RETRODE3_COMPONENT=$kind" -e "RETRODE3_COMPONENT_SHA=$sha" \
      -e "RETRODE3_BUILDER_IMAGE_ID=$image_id" \
      -e "RETRODE3_PLATFORM_KEY=$key" \
      -e "RETRODE3_PLATFORM_RECIPE_SHA=$recipe_sha" \
      "$image" bash /src/buildserver/build-platform-component.sh
    [[ ! -e "$entry" ]] || exit 1
    mv -T "$temp" "$entry"
    python3 "$src/buildserver/platform-cache.py" verify "$kind" "$sha" "$image_id" "$recipe_sha" "$entry"
  fi
  cp "$entry"/*.deb "$run/"
  cp "$entry/platform-manifest.json" "$run/$kind-manifest.json"
done
python3 - "$run" "$image_id" <<'PY'
import hashlib, json, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
manifests=[json.loads((root / (kind+"-manifest.json")).read_text())
           for kind in ("kernel","uboot")]
records=[]
for m in manifests:
    for file,sha in sorted(m["files"].items()):
        path=root/file
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            sys.exit("Copied platform .deb hash mismatch")
        name=subprocess.check_output(["dpkg-deb","-f",str(path),"Package"], text=True).strip()
        records.append({"name":name,"filename":file,"sha256":sha,
                        "version":m["version"],"kind":m["kind"]})
doc={"schema":1, "suite":"testing", "builder_image_id":sys.argv[2],
     "sources":{m["kind"]:m["commit"] for m in manifests},
     "packages":records, "hardware_accepted":False,"apt_published":False}
(root/"platform-package-set.json").write_text(json.dumps(doc,sort_keys=True,indent=2)+"\n")
PY
echo "Platform Debian candidate: $run"
echo "NOT PUBLISHED: run an explicit signed release gate after review."
