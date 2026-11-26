#!/usr/bin/env bash
# Run the full OS test suite using the target's Debian release, not host Python.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd -P)"
image=localhost/retrode3-preflight:bookworm
podman build -f "$root/buildserver/Containerfile.preflight" -t "$image" "$root/buildserver"
podman run --rm --network=none --userns=keep-id \
    --security-opt=no-new-privileges \
    -e PYTHONPYCACHEPREFIX=/tmp/retrode3-pycache \
    -v "$root:/src:ro" -w /src "$image" \
    /bin/sh -c 'umask 022; exec ./tools/preflight-ci.sh'
