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
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
[[ "$commit" =~ ^[a-fA-F0-9]{40}$ && "$sanni" =~ ^[a-fA-F0-9]{40}$ ]]
work="$(mktemp -d /tmp/retrode3-build.XXXXXXXX)"
trap 'rm -rf "$work"' EXIT
git clone --quiet "https://github.com/$repo.git" "$work/oscr"
git -C "$work/oscr" checkout --quiet --detach "$commit"
git -C "$work/oscr" submodule update --init third_party/oscr-firmware
test "$(git -C "$work/oscr" rev-parse HEAD:third_party/oscr-firmware)" = "$sanni"
test "$(git -C "$work/oscr/third_party/oscr-firmware" rev-parse HEAD)" = "$sanni"
make -C "$work/oscr" -f Makefile.migration test-all-shared-cores
make -C "$work/oscr" -f Makefile.migration clean-migration
make -C "$work/oscr" -f Makefile.migration \
    CC=mipsel-linux-gnu-gcc CXX=mipsel-linux-gnu-g++ \
    AR=mipsel-linux-gnu-ar test-release-stage
# Master has three cores; develop additionally stages SMS-MD.
if grep -Eq '^stage-sms-md-module:' "$work/oscr/Makefile.migration"; then
  make -C "$work/oscr" -f Makefile.migration \
    CC=mipsel-linux-gnu-gcc CXX=mipsel-linux-gnu-g++ \
    AR=mipsel-linux-gnu-ar stage-sms-md-module
fi
stage="$work/oscr/build/migration/stage"
file "$stage/usr/bin/retrode3-cli" "$stage/usr/lib/retrode3/cores-available/"*.so
python3 "$src/packaging/build-debs.py" \
    --oscr-source "$work/oscr" --stage "$stage" --output "$out"
(cd "$out" && sha256sum ./*.deb > SHA256SUMS)
echo "Offline package candidates: $out"
