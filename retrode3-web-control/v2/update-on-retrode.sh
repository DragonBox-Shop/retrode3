#!/bin/sh
# Pull the development branch directly on the Retrode and deploy it.
# The checkout remains private; the webroot only receives deployable assets.
set -eu

fail() { echo "ERROR: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "Run as root."
command -v git >/dev/null 2>&1 || fail "Git is not installed."
[ -x /usr/bin/retrode3-cli ] || fail "OS shared CLI missing at /usr/bin/retrode3-cli"
[ -x /usr/sbin/retrode3-corectl ] || fail "OS core helper missing at /usr/sbin/retrode3-corectl"
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
[ -d "$SOURCE/.git" ] || fail "No Git checkout at $SOURCE."
BRANCH=$(git -C "$SOURCE" symbolic-ref --quiet --short HEAD) ||
    fail "Detached Git HEAD. Check out master (release) or develop first."
# Update the checked-out development branch, including temporary feature
# branches. No separate build/approval mode for customer-facing Web features.
case "$BRANCH" in
    master|develop|feature/*) ;;
    *) fail "Unsupported branch name $BRANCH." ;;
esac
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=no)" ] ||
    fail "Local tracked changes exist. Commit or revert them before updating."

# Never interrupt an active native read. A backend restart does not
# necessarily terminate a child process that is accessing the slot.
if [ -f /etc/init.d/retrode3-web-v2 ]; then
    if python3 -c '
import json, sys, http.client
try:
    conn = http.client.HTTPConnection("127.0.0.1", 8765, timeout=3)
    conn.request("GET", "/api/jobs/active")
    response = conn.getresponse()
    if response.status != 200:
        sys.exit(2)
    state = json.loads(response.read().decode("utf-8")).get("status", "unknown")
    conn.close()
except Exception:
    sys.exit(2)
if state in ("queued", "running", "cancelling"):
    sys.exit(1)
sys.exit(0 if state in ("idle", "done", "failed", "cancelled") else 2)
'; then
        :
    else
        CODE=$?
        [ "$CODE" -eq 1 ] && fail "A cartridge job is active. Let it finish or cancel it before updating."
        fail "Cannot verify idle backend; refusing to restart it. Check the backend service."
    fi
fi

echo "==> Pulling $BRANCH from GitHub"
git -C "$SOURCE" pull --ff-only origin "$BRANCH"

SCRIPT="$SOURCE/retrode3-web-control/v2/install-on-retrode.sh"
[ -f "$SCRIPT" ] || fail "Installer missing after Git pull."
sh -n "$SCRIPT" || fail "Installer shell syntax check failed."
echo "==> Deploying and health-checking the new version"
sh "$SCRIPT"
