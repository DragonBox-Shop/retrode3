#!/usr/bin/env bash
# Inside disposable rootless Podman, build ONE candidate component to /out.
set -euo pipefail
: "${RETRODE3_COMPONENT:?}" "${RETRODE3_COMPONENT_SHA:?}"
: "${RETRODE3_BUILDER_IMAGE_ID:?}" "${RETRODE3_PLATFORM_KEY:?}"
[[ "${RETRODE3_COMPONENT_SHA}" =~ ^[a-f0-9]{40}$ ]] || exit 1
case "$RETRODE3_COMPONENT" in
  kernel)
    url=https://github.com/DragonBox-Shop/retrode3-kernel.git
    ref=feature/retrode3-mipsel-deb-packaging-20261125
    base=7.3.0~rc5
    ;;
  uboot)
    url=https://github.com/DragonBox-Shop/retrode3-uboot.git
    ref=feature/retrode3-uboot-deb-packaging-20261125
    base=2013.07
    ;;
  *) echo "Unsupported build component" >&2; exit 1 ;;
esac
key="$(python3 /src/buildserver/platform-cache.py key \
  "$RETRODE3_COMPONENT" "$RETRODE3_COMPONENT_SHA" "$RETRODE3_BUILDER_IMAGE_ID")"
[[ "$key" == "$RETRODE3_PLATFORM_KEY" ]] || exit 1
[[ -d /out && -z "$(ls -A /out)" ]] || {
  echo "Output directory must be empty" >&2; exit 1;
}
git clone --quiet --depth 1 --single-branch --branch "$ref" "$url" /work/source
sha="$(git -C /work/source rev-parse HEAD)"
[[ "$sha" == "$RETRODE3_COMPONENT_SHA" ]] || {
  echo "Git ref moved during candidate build; refusing mixed sources" >&2; exit 1;
}
epoch="$(git -C /work/source show -s --format=%ct HEAD)"
[[ "$epoch" =~ ^[0-9]{10,12}$ ]] || exit 1
stamp="$(date -u -d "@$epoch" +%Y%m%d%H%M%S)"
version="${base}+git${stamp}.${sha:0:12}+b${key:0:12}-1"
export SOURCE_DATE_EPOCH="$epoch"
bash /work/source/packaging/retrode3/build-debs.sh /out "$version"
python3 - "$RETRODE3_COMPONENT" "$sha" "$RETRODE3_BUILDER_IMAGE_ID" \
  "$key" "$version" <<'PY'
import hashlib, json, pathlib, sys
kind, commit, image_id, key, version = sys.argv[1:]
directory = pathlib.Path("/out")
files = {}
for path in sorted(directory.glob("*.deb")):
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    files[path.name] = h
expected = 2 if kind == "kernel" else 1
if len(files) != expected:
    sys.exit("Wrong number of built platform Debian packages")
manifest = dict(schema=1, kind=kind, commit=commit, version=version,
                builder_image_id=image_id, cache_key=key,
                hardware_accepted=False, apt_published=False, files=files)
(directory / "platform-manifest.json").write_text(
    json.dumps(manifest, sort_keys=True, indent=2) + "\n")
PY
echo "Platform candidate built: $RETRODE3_COMPONENT $version"
