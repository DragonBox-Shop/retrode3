#!/usr/bin/env bash
# Deprecated kernel-building image route: intentionally disabled.
# The supported image builder is build-image-from-packages.sh and only
# consumes already published signed Debian kernel/U-Boot packages.
echo "Deprecated kernel-building image route; use build-image-from-packages.sh" >&2
exit 1
