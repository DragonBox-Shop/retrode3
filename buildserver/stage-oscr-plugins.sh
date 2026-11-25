#!/usr/bin/env bash
# Stage new plugins from pinned OSCR Git source, never from hard-coded IDs.
set -euo pipefail
[[ "$#" == 1 ]] || { echo "Usage: $0 /path/to/oscr" >&2; exit 2; }
oscr="$1"
recipes="$oscr/packaging/cores"
stage="$oscr/build/migration/stage/usr/lib/retrode3/cores-available"
[[ -d "$recipes" && ! -L "$recipes" ]] || exit 1
ids=()
for recipe in "$recipes"/*.core; do
  [[ -f "$recipe" && ! -L "$recipe" ]] || {
    echo "Missing or unsafe OSCR core metadata: $recipe" >&2; exit 1;
  }
  id="$(basename "$recipe" .core)"
  [[ "$id" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ && "$id" != runtime && "${#id}" -le 48 ]] || exit 1
  ids+=( "$id" )
done
[[ "${#ids[@]}" -gt 0 ]] || { echo "No core recipes" >&2; exit 1; }
for id in "${ids[@]}"; do
  if [[ ! -e "$stage/$id.so" && ! -L "$stage/$id.so" &&
        ! -e "$stage/$id.core" && ! -L "$stage/$id.core" ]]; then
    make -C "$oscr" -f Makefile.migration \
        CC=mipsel-linux-gnu-gcc CXX=mipsel-linux-gnu-g++ \
        AR=mipsel-linux-gnu-ar "stage-$id-module"
  fi
  [[ -s "$stage/$id.so" && -f "$stage/$id.so" && ! -L "$stage/$id.so" &&
     -s "$stage/$id.core" && -f "$stage/$id.core" && ! -L "$stage/$id.core" ]] &&
    cmp -s "$stage/$id.core" "$recipes/$id.core" || {
    echo "OSCR recipe missing staged files: $id" >&2; exit 1
  }
done
