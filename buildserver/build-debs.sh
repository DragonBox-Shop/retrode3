#!/usr/bin/env bash
# Runs inside Podman. Builds only, never deploys to APT or a Retrode3.
set -euo pipefail
export LC_ALL=C
src=/src
out=/out
lock="$src/packaging/native-source-lock.json"
test -f "$lock"
readarray -t pins < <(python3 - "$lock" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as f:
    d=json.load(f)
for k in ("oscr_repository","oscr_commit","sanni_commit"):
    print(d[k])
PY
)
repo="${pins[0]}"
commit="${pins[1]}"
sanni="${pins[2]}"
follow="${RETRODE3_FOLLOW_OSCR_BRANCH:-0}"
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
if [[ "$follow" == 1 ]]; then
  [[ "$repo" == DragonBox-Shop/retrode3-oscr ]] || {
    echo "Unexpected source repo for live OSCR release" >&2; exit 1;
  }
  [[ "${RETRODE3_OSCR_BRANCH:-}" == master ||
     "${RETRODE3_OSCR_BRANCH:-}" == develop ]] || {
    echo "Invalid OSCR branch" >&2; exit 1;
  }
  commit="${RETRODE3_OSCR_COMMIT:-}"
fi
[[ "$commit" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Invalid OSCR source SHA" >&2; exit 1;
}
work="$(mktemp -d /tmp/retrode3-build.XXXXXXXX)"
trap 'rm -rf "$work"' EXIT
git clone --quiet "https://github.com/$repo.git" "$work/oscr"
git -C "$work/oscr" checkout --quiet --detach "$commit"
if [[ -n "${RETRODE3_OSCR_TAG:-}" ]]; then
  git -C "$work/oscr" check-ref-format "refs/tags/$RETRODE3_OSCR_TAG" || exit 1
  [[ "$(git -C "$work/oscr" rev-parse --verify "refs/tags/$RETRODE3_OSCR_TAG^{commit}")" == "$commit" ]] || {
    echo "OSCR selected tag does not resolve to the pinned commit" >&2
    exit 1
  }
fi
if [[ "$follow" == 1 ]]; then
  # Re-check that the requested commit belongs to the selected branch.
  git -C "$work/oscr" merge-base --is-ancestor "$commit" \
      "origin/$RETRODE3_OSCR_BRANCH" || {
    echo "OSCR commit no longer belongs to branch $RETRODE3_OSCR_BRANCH" >&2
    exit 1
  }
  sanni="$(git -C "$work/oscr" rev-parse HEAD:third_party/oscr-firmware)"
  [[ "$sanni" =~ ^[a-f0-9]{40}$ ]] || exit 1
  resolved="$work/source-lock.json"
  python3 - "$lock" "$resolved" "$commit" "$sanni" <<'PY'
import json
import sys
source, target, oscr, sanni = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    cfg = json.load(stream)
cfg["oscr_commit"] = oscr
cfg["sanni_commit"] = sanni
with open(target, "w", encoding="utf-8") as stream:
    json.dump(cfg, stream, sort_keys=True)
    stream.write("\n")
PY
  lock="$resolved"
fi
git -C "$work/oscr" submodule update --init third_party/oscr-firmware
test "$(git -C "$work/oscr" rev-parse HEAD:third_party/oscr-firmware)" = "$sanni"
test "$(git -C "$work/oscr/third_party/oscr-firmware" rev-parse HEAD)" = "$sanni"
make -C "$work/oscr" -f Makefile.migration test-all-shared-cores
make -C "$work/oscr" -f Makefile.migration clean-migration
make -C "$work/oscr" -f Makefile.migration \
    CC=mipsel-linux-gnu-gcc CXX=mipsel-linux-gnu-g++ \
    AR=mipsel-linux-gnu-ar test-release-stage
bash "$src/buildserver/stage-oscr-plugins.sh" "$work/oscr"
stage="$work/oscr/build/migration/stage"
file "$stage/usr/bin/retrode3-cli" "$stage/usr/lib/retrode3/cores-available/"*.so
previous_args=()
if [[ -f /previous/build-manifest.json ]]; then
    previous_args=(--previous /previous)
fi
python3 "$src/packaging/build-debs.py" \
    "${previous_args[@]}" \
    --source-lock "$lock" \
    --oscr-source "$work/oscr" --stage "$stage" --output "$out"
(cd "$out" && sha256sum ./*.deb > SHA256SUMS)
echo "Offline package candidates: $out"
