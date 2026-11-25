#!/usr/bin/env bash
# Build a Debian 12 MIPSEL SysV rootfs candidate. NEVER writes any disk/image.
set -euo pipefail
umask 022
[[ "$#" == 1 && "$1" == /* ]] || {
  echo "Usage: $0 /absolute/output/directory" >&2
  exit 2
}
for executable in mmdebstrap arch-test chroot qemu-mipsel-static tar sha256sum python3; do
  command -v "$executable" >/dev/null || { echo "Missing $executable" >&2; exit 1; }
done
[[ "$(id -u)" == 0 ]] || {
  echo "Run only as root inside an isolated CI runner/build container." >&2
  exit 1
}
[[ -r /proc/sys/fs/binfmt_misc/qemu-mipsel ]] &&
  grep -xq enabled /proc/sys/fs/binfmt_misc/qemu-mipsel || {
    echo "qemu-mipsel binfmt_misc registration is required" >&2
    exit 1
  }
outdir="$1"
mkdir -p "$outdir"
outdir="$(cd "$outdir" && pwd -P)"
case "$outdir" in
  /|/boot|/mnt|/media|/root|/home|/srv|/var|/usr|/etc)
    echo "Refusing unsafe output: $outdir" >&2; exit 1 ;;
esac
archive="$outdir/retrode3-bookworm-mipsel-rootfs.tar.xz"
manifest="$outdir/retrode3-bookworm-mipsel-manifest.json"
checksums="$outdir/SHA256SUMS"
for path in "$archive" "$manifest" "$checksums"; do
  [[ ! -e "$path" ]] || { echo "Refusing overwrite: $path" >&2; exit 1; }
done
scratch="$(mktemp -d "$outdir/.bookworm-build.XXXXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
root="$scratch/rootfs"
mkdir -p "$root"
export DEBIAN_FRONTEND=noninteractive
# mmdebstrap root mode is verified on the rootless Amaterasu Podman setup.
# It does not require mknod or mount in the nested container, unlike
# debootstrap's initial device-node test. Install the entire minimal SysV
# package set INSIDE mmdebstrap while it manages the foreign QEMU chroot.
# Debian Bookworm mmdebstrap 1.3.5 does NOT support --skip=output/mknod.
echo "=== Creating Bookworm MIPSEL SysV base with mmdebstrap (rootless Podman) ==="
mmdebstrap \
  --mode=root \
  --skip=check/canmount,chroot/mount \
  --architectures=mipsel \
  --variant=minbase \
  --include=sysvinit-core,sysv-rc,initscripts,udev,kmod,ifupdown,iproute2,isc-dhcp-client,e2fsprogs,dosfstools,ca-certificates,dropbear-bin,dnsmasq-base \
  --aptopt='APT::Install-Recommends "false"' \
  --format=tar \
  bookworm "$scratch/mmdebstrap-rootfs.tar" https://deb.debian.org/debian
# Never try mknod when expanding an archive into the rootless bind-mounted
# workspace. Linux DEVTMPFS_MOUNT populates /dev on a real Retrode3 boot.
# We keep an empty /dev directory in the offline image candidate.
tar --numeric-owner --exclude='./dev/*' --exclude='dev/*' \
    -xf "$scratch/mmdebstrap-rootfs.tar" -C "$root"
mkdir -p "$root/dev"
[[ -f "$root/etc/debian_version" && -f "$root/var/lib/dpkg/status" ]] || {
  echo "Incomplete mmdebstrap rootfs" >&2; exit 1;
}
# No second-stage needed: mmdebstrap has already configured the base packages.
cat > "$root/etc/apt/sources.list" <<'EOF'
deb https://deb.debian.org/debian bookworm main
EOF
cat > "$root/etc/apt/apt.conf.d/99retrode3-minimal" <<'EOF'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
EOF
# Signed Retrode3 APT source is opt-in for the image pipeline, never a
# trustworthy-on-first-use download. All three inputs must be provided.
if [[ -n "${RETRODE3_APT_PUBLIC_KEY:-}" || -n "${RETRODE3_APT_FINGERPRINT:-}" ||
      -n "${RETRODE3_APT_SUITE:-}" ]]; then
  [[ -f "${RETRODE3_APT_PUBLIC_KEY:-}" && -n "${RETRODE3_APT_FINGERPRINT:-}" &&
      "${RETRODE3_APT_SUITE:-}" =~ ^(testing|stable)$ ]] || {
    echo "Require RETRODE3_APT_PUBLIC_KEY, RETRODE3_APT_FINGERPRINT and testing|stable suite" >&2
    exit 1
  }
  python3 "$(dirname "$0")/configure-apt-source.py" \
    --rootfs "$root" --public-key "$RETRODE3_APT_PUBLIC_KEY" \
    --fingerprint "$RETRODE3_APT_FINGERPRINT" --suite "$RETRODE3_APT_SUITE"
fi
# Never start services inside the foreign chroot.
cat > "$root/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 "$root/usr/sbin/policy-rc.d"
# The SysV base set was installed and configured by mmdebstrap above.
cat > "$root/etc/fstab" <<'EOF'
# Planned Retrode3 SD partition layout, validated later with a test card.
/dev/mmcblk0p2 / ext4 defaults,noatime,errors=remount-ro 0 1
/dev/mmcblk0p1 /boot vfat noauto,defaults 0 0
EOF
printf 'retrode3\n' > "$root/etc/hostname"
cat > "$root/etc/hosts" <<'EOF'
127.0.0.1 localhost
127.0.1.1 retrode3
::1 localhost ip6-localhost ip6-loopback
EOF
cat > "$root/etc/network/interfaces" <<'EOF'
auto lo
iface lo inet loopback
# USB gadget networking is added in a later reviewed stage.
EOF
cat > "$root/etc/inittab" <<'EOF'
id:2:initdefault:
si::sysinit:/etc/init.d/rcS
l2:2:wait:/etc/init.d/rc 2
ca:12345:ctrlaltdel:/sbin/shutdown -r now
s2:2345:respawn:/sbin/getty -L 115200 ttyS2 vt102
EOF
# Preserve the numeric SysV ordering checked on the original Bookworm test SD.
: > "$root/etc/init.d/.legacy-bootordering"
rm -f "$root/usr/sbin/policy-rc.d" "$root/usr/bin/qemu-mipsel-static"
rm -f "$root/etc/resolv.conf"
rm -rf "$root/var/lib/apt/lists/"*
mkdir -p "$root/var/lib/apt/lists" "$root/boot"
python3 "$(dirname "$0")/verify-rootfs.py" "$root"
python3 "$(dirname "$0")/manifest-rootfs.py" "$root" > "$scratch/manifest.json"
source_epoch="${SOURCE_DATE_EPOCH:-$(date -u +%s)}"
[[ "$source_epoch" =~ ^[0-9]+$ ]] || { echo "Invalid SOURCE_DATE_EPOCH" >&2; exit 1; }
tar --sort=name --numeric-owner --owner=0 --group=0 \
  --mtime="@$source_epoch" --acls --xattrs --one-file-system \
  -C "$root" -cJf "$scratch/rootfs.tar.xz" .
cp "$scratch/rootfs.tar.xz" "$archive"
cp "$scratch/manifest.json" "$manifest"
(cd "$outdir" && sha256sum "$(basename "$archive")" "$(basename "$manifest")" > "$checksums")
printf 'Rootfs: %s\nManifest: %s\nChecksums: %s\n' "$archive" "$manifest" "$checksums"
echo "NOT BOOTABLE: kernel, DTB, gadget services, image layout and secure provisioning still missing."
