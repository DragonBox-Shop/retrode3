#!/bin/sh
# Read ONLY first 1 MiB of the active SD card. Does not write to /dev/mmcblk0.
set -eu
[ "$#" -eq 1 ] || { echo "Usage: $0 /absolute/output.bin" >&2; exit 2; }
case "$1" in
    /*.bin) ;;
    *) echo "Output must be an absolute .bin path" >&2; exit 2 ;;
esac
[ ! -e "$1" ] || { echo "Refusing to overwrite $1" >&2; exit 1; }
rootdev="$(awk '$2 == "/" { print $1; exit }' /proc/mounts)"
[ "$rootdev" = /dev/mmcblk0p2 ] || {
    echo "Unexpected running root device: $rootdev; refusing SD capture" >&2
    exit 1
}
dd if=/dev/mmcblk0 of="$1" bs=512 count=2048
[ "$(wc -c < "$1")" -eq 1048576 ] || {
    echo "SD raw preboot dump is incomplete" >&2; exit 1;
}
signature="$(od -An -tx1 -j510 -N2 "$1" | tr -d ' \n')"
[ "$signature" = 55aa ] || {
    echo "No MBR signature, do not assemble image from this dump" >&2
    exit 1
}
sha256sum "$1"
echo "Captured original raw SD boot region. KEEP PRIVATE; do not commit to Git."
