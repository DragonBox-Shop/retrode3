#!/bin/sh
# Read-only snapshot of the *running* development Retrode3 kernel and modules.
# The only write is the requested tar.gz output archive.
set -eu
[ "$#" -eq 1 ] || { echo "Usage: $0 /absolute/output.tar.gz" >&2; exit 2; }
case "$1" in
    /*.tar.gz) ;;
    *) echo "Output must be an absolute .tar.gz path" >&2; exit 2 ;;
esac
out="$1"
[ ! -e "$out" ] || { echo "Refusing to overwrite $out" >&2; exit 1; }
release="$(uname -r)"
case "$release" in
    *[!a-zA-Z0-9.+_-]*|'') echo "Invalid kernel release" >&2; exit 1 ;;
esac
[ -r /boot/uImage ] || { echo "Missing /boot/uImage" >&2; exit 1; }
[ -r /boot/bootargs.scr ] || { echo "Missing /boot/bootargs.scr" >&2; exit 1; }
[ -r /boot/ingenic/lx16-retrode-2.9.5.dtb ] || {
    echo "Missing Retrode3 2.9.5 DTB" >&2; exit 1;
}
[ -r "/lib/modules/$release/modules.dep" ] || {
    echo "Missing modules.dep for running kernel $release" >&2; exit 1;
}
tar -C / \
  --exclude="lib/modules/$release/build" \
  --exclude="lib/modules/$release/source" \
  -czf "$out" \
  boot/uImage boot/bootargs.scr \
  boot/ingenic/lx16-retrode-2.9.5.dtb \
  "lib/modules/$release"
sha256sum "$out"
echo "Boot bundle captured for running kernel: $release"
echo "This is a development reference, NOT a source-built kernel package."
