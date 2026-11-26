#!/bin/sh
# Explicit isolated package build; no installation, publishing or flash.
set -eu
cd "$(dirname "$0")"
cd firmware; sha256sum -c SHA256SUMS; cd ..
# Refuse host test binaries or wrong target byte order.
LC_ALL=C readelf -h retrode3-esp-flasher | grep -q 'Class:.*ELF32'
LC_ALL=C readelf -h retrode3-esp-flasher | grep -q 'Data:.*little endian'
LC_ALL=C readelf -h retrode3-esp-flasher | grep -q 'Machine:.*MIPS'
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
chmod 0755 "$work"
install -d "$work/DEBIAN" "$work/usr/sbin" "$work/usr/share/retrode3/esp32c6" "$work/usr/share/doc/retrode3-esp-firmware"
install -m0755 retrode3-esp-flasher "$work/usr/sbin/retrode3-esp-flasher"
install -m0644 firmware/* "$work/usr/share/retrode3/esp32c6/"
install -m0644 README.md vendor/LICENSE "$work/usr/share/doc/retrode3-esp-firmware/"
cat > "$work/DEBIAN/control" <<'CTRL'
Package: retrode3-esp-firmware
Version: 0~test1+ng1.0.6.0.1-1
Architecture: mipsel
Maintainer: Retrode3 development
Depends: libc6 (>= 2.36), coreutils
Section: misc
Priority: optional
Description: Experimental Retrode3 ESP32-C6 firmware and manual flasher
 Unpublished maintenance candidate; no automatic flashing.
CTRL
dpkg-deb --root-owner-group --build "$work" retrode3-esp-firmware_0~test1+ng1.0.6.0.1-1_mipsel.deb
