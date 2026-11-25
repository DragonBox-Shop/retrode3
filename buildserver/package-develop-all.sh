#!/usr/bin/env bash
# DEVELOPMENT package orchestration: OS/OSCR + kernel + X1600 bootloader.
# Separate from the image builder. No SD writes, Git commits or pushes.
set -euo pipefail
[[ "$#" == 1 ]] || { echo "Usage: $0 --build-only|--publish-testing" >&2; exit 2; }
case "$1" in
  --build-only|--publish-testing) ;;
  *) echo "Unknown package action" >&2; exit 2 ;;
esac
[[ "$(id -un)" == retrode ]] || exit 1
src="$(cd "$(dirname "$0")/.." && pwd -P)"
# Existing published OS/OSCR tagged release; no code path changed here.
bash /srv/www/vhosts/retrode.com/package_develop.sh
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
bash "$src/buildserver/package-platform-develop.sh" 2>&1 | tee "$log"
candidate="$(sed -n 's/^Platform Debian candidate: //p' "$log" | tail -n 1)"
[[ "$candidate" == /* && -f "$candidate/platform-package-set.json" ]] || exit 1
if [[ "$1" == --publish-testing ]]; then
  [[ "${RETRODE3_ALLOW_EXPERIMENTAL_BOOT_PACKAGES:-0}" == 1 ]] || {
    echo "Explicit opt-in required for test-only boot packages" >&2; exit 1;
  }
  bash "$src/buildserver/publish-platform-develop.sh" "$candidate"
else
  echo "Build only. No kernel/U-Boot publication: $candidate"
fi
