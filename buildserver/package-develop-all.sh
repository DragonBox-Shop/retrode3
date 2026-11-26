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
# Use the already-installed, tested source-selection automation directly.
# RETRODE3_SOURCE_MODE=tag is inherited only for an explicit image build.
# DO NOT call the public package_develop.sh here: that public launcher
# delegates to this very script, so doing so would recurse forever.
base=/srv/www/vhosts/retrode.com/buildserver
automation="$base/automation/auto-package.sh"
[[ -f "$automation" && ! -L "$automation" ]] || {
  echo "Missing pinned APT automation: $automation" >&2; exit 1;
}
if [[ "$1" == --build-only ]]; then
  RETRODE3_BUILD_ONLY=1 bash "$automation" develop
else
  bash "$automation" develop
fi
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
bash "$src/buildserver/package-platform-develop.sh" 2>&1 | tee "$log"
candidate="$(sed -n 's/^Platform Debian candidate: //p' "$log" | tail -n 1)"
[[ "$candidate" == /* && -f "$candidate/platform-package-set.json" ]] || exit 1
if [[ "$1" == --publish-testing ]]; then
  # A published, verified identical source/package set is a strict no-op.
  # No recompilation, GPG unlock or repeated reprepro export is needed.
  previous="$base/cache/last-published-platform-develop.json"
  if [[ -f "$previous" && ! -L "$previous" ]] &&
     python3 "$src/buildserver/verify-platform-snapshot.py" \
       "$previous" "$base/repository" >/dev/null &&
     python3 - "$candidate/platform-package-set.json" "$previous" <<'PY'
import json, sys
new, old = (json.load(open(p)) for p in sys.argv[1:])
if (new.get("sources") == old.get("sources") and
    sorted(new.get("packages", []), key=lambda x: x["name"]) ==
    sorted(old.get("packages", []), key=lambda x: x["name"])):
    sys.exit(0)
sys.exit(1)
PY
  then
    echo "Nothing to publish: identical kernel/U-Boot package set already in signed testing."
    exit 0
  fi
  # The public package_develop.sh is the explicit operator request
  # to refresh the signed TESTING suite, including staged (not activated)
  # kernel and U-Boot candidates. This never touches a live /boot.
  RETRODE3_ALLOW_EXPERIMENTAL_BOOT_PACKAGES=1 \
    bash "$src/buildserver/publish-platform-develop.sh" "$candidate"
else
  echo "Build only. No kernel/U-Boot publication: $candidate"
fi
