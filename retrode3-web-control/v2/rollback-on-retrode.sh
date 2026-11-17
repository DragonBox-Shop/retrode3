#!/bin/sh
# Restore the prior Retrode3 webroot, keep the v2 installation for inspection.
set -eu
[ "$(id -u)" = 0 ] || { echo "Run as root" >&2; exit 1; }
STATE=/var/backups/retrode3-web-v2/latest
[ -r "$STATE" ] || { echo "No v2 backup recorded" >&2; exit 1; }
BACKUP=$(cat "$STATE")
case "$BACKUP" in
    /var/backups/retrode3-web-v2/*) ;;
    *) echo "Invalid backup location" >&2; exit 1 ;;
esac
[ -d "$BACKUP/previous-webroot" ] ||
    { echo "Original webroot backup missing" >&2; exit 1; }
[ -f "$BACKUP/previous-webroot/index.php" ] ||
    { echo "Original index.php backup missing" >&2; exit 1; }
[ -d /var/www/html ] || { echo "Current webroot missing" >&2; exit 1; }

service retrode3-web-v2 stop || true
STAMP=$(date '+%Y%m%d-%H%M%S')
mv /var/www/html "$BACKUP/new-webroot-removed-$STAMP"
if ! cp -a "$BACKUP/previous-webroot" /var/www/html; then
    echo "ERROR: restore failed. Recover from $BACKUP/previous-webroot" >&2
    exit 1
fi
if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d -f retrode3-web-v2 remove >/dev/null 2>&1 || true
fi
echo "Old web interface restored from $BACKUP/previous-webroot"
echo "New frontend retained in $BACKUP/new-webroot-removed-$STAMP"
echo "Backend stopped; native OSCR reader unchanged."
