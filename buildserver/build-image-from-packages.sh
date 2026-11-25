#!/usr/bin/env bash
# Test SD image: only APT-installed Debian packages, NEVER kernel/U-Boot make.
set -euo pipefail
umask 022
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
: "${RETRODE3_IMAGE_BRANCH:?}" "${RETRODE3_IMAGE_SUITE:?}"
: "${RETRODE3_OS_SHA:?}" "${RETRODE3_OS_TAG:?}"
: "${RETRODE3_OSCR_SHA:?}" "${RETRODE3_OSCR_TAG:?}"
: "${RETRODE3_APT_FINGERPRINT:?}"
[[ "$RETRODE3_IMAGE_BRANCH:$RETRODE3_IMAGE_SUITE" == develop:testing ]] || exit 1
[[ "$(id -u)" == 0 ]] || { echo "Rootless namespaced container root required" >&2; exit 1; }
for file in /private/retrode3-archive.gpg /private/apt-fingerprint \
            /work/published-packages.json /work/published-platform.json; do
  [[ -s "$file" && -f "$file" && ! -L "$file" ]] || exit 1
done
python3 /src/buildserver/verify-image-snapshot.py \
  /work/published-packages.json testing develop \
  "$RETRODE3_OS_TAG" "$RETRODE3_OS_SHA" \
  "$RETRODE3_OSCR_TAG" "$RETRODE3_OSCR_SHA"
python3 /src/buildserver/verify-platform-snapshot.py /work/published-platform.json
export RETRODE3_APT_PUBLIC_KEY=/private/retrode3-archive.gpg
export RETRODE3_APT_SUITE=testing
# Validate OCI bind-mounted devices BEFORE the multi-minute Debian
# bootstrap, so a Podman host limitation fails immediately.
for device in null zero random urandom tty; do
  [[ -c "/work/rootfs/dev/$device" ]] || {
    echo "Missing Podman-bound chroot device before mmdebstrap: /dev/$device" >&2
    exit 1
  }
done
# Resume is explicit, never inferred from an old workspace. The host
# validates both published snapshots and the original OS commit before
# accepting the previous package installation.
resume="${RETRODE3_IMAGE_RESUME:-0}"
[[ "$resume" == 0 || "$resume" == 1 ]] || {
  echo "Invalid RETRODE3_IMAGE_RESUME flag" >&2; exit 1;
}
if [[ "$resume" == 1 ]]; then
  [[ -s /work/base-rootfs/retrode3-bookworm-mipsel-rootfs.tar.xz &&
     -s /work/base-rootfs/SHA256SUMS &&
     -s /work/rootfs/var/lib/dpkg/status &&
     -x /work/rootfs/usr/bin/qemu-mipsel-static &&
     -x /work/rootfs/usr/sbin/policy-rc.d ]] || {
    echo "Cannot resume: incomplete prior Bookworm build" >&2; exit 1;
  }
  (cd /work/base-rootfs && sha256sum --check --strict SHA256SUMS)
  echo "=== RESUME: existing Bookworm rootfs retained, skipping mmdebstrap and APT bootstrap ==="
else
  mkdir -p /work/base-rootfs
  bash /src/image/build-bookworm-rootfs.sh /work/base-rootfs
  echo "Chroot APT devices ready (OCI bind mounts, no mknod)."
  tar --numeric-owner -xJf /work/base-rootfs/retrode3-bookworm-mipsel-rootfs.tar.xz \
    -C /work/rootfs
  cp /usr/bin/qemu-mipsel-static /work/rootfs/usr/bin/qemu-mipsel-static
  cp /etc/resolv.conf /work/rootfs/etc/resolv.conf
  cat > /work/rootfs/usr/sbin/policy-rc.d <<'EOF'
#!/bin/sh
exit 101
EOF
  chmod 0755 /work/rootfs/usr/sbin/policy-rc.d
fi
# The host launcher bind-mounts only five simple character devices into
# this disposable foreign-architecture chroot. Never ship these nodes.
for device in null zero random urandom tty; do
  [[ -c "/work/rootfs/dev/$device" ]] || {
    echo "Missing Podman-bound chroot device: /dev/$device" >&2; exit 1;
  }
done
# Resolve exact versions from the signed published snapshots, not from
# mutable develop branches or floating APT 'latest' packages.
mapfile -t packages < <(python3 - <<'PY'
import json
base=json.load(open("/work/published-packages.json"))
platform=json.load(open("/work/published-platform.json"))
names=set()
for p in base["packages"]:
    name=p["package"]
    version=(base["web_version"] if name in
             ("retrode3-web-control","retrode3-tools","retrode3-udev-rules")
             else base["native_version"])
    if name in names:
        raise ValueError("Duplicate OS package")
    names.add(name)
    print(name+"="+version)
for p in platform["packages"]:
    if p["name"] in names:
        raise ValueError("Duplicate platform package")
    names.add(p["name"])
    print(p["name"]+"="+p["version"])
PY
)
if [[ "$resume" == 0 ]]; then
  echo "=== Installing OS/OSCR and platform boot packages from signed APT ==="
  chroot /work/rootfs /usr/bin/apt-get update
  chroot /work/rootfs /usr/bin/apt-get -y --no-install-recommends install \
    "${packages[@]}"
else
  echo "=== RESUME: checking already-installed package versions against signed APT snapshot ==="
fi
for spec in "${packages[@]}"; do
  pkg="${spec%%=*}"
  ver="${spec#*=}"
  got="$(chroot /work/rootfs dpkg-query -W -f='${Version}' "$pkg")"
  state="$(chroot /work/rootfs dpkg-query -W -f='${Status}' "$pkg")"
  [[ "$got" == "$ver" && "$state" == "install ok installed" ]] || {
    echo "Wrong or unconfigured APT package: $pkg actual=$got state=<$state> expected=$ver" >&2; exit 1;
  }
done
# Debian's libapache2-mod-php8.2 may print transient "No MPM loaded"
# warnings while switching from mpm_event to mpm_prefork. The finished
# offline image must nevertheless have a consistent Apache configuration.
for module in mpm_prefork.load php8.2.load; do
  [[ -L "/work/rootfs/etc/apache2/mods-enabled/$module" &&
     -e "/work/rootfs/etc/apache2/mods-enabled/$module" ]] || {
    echo "Missing final Apache module: $module" >&2; exit 1;
  }
done
if [[ -e /work/rootfs/etc/apache2/mods-enabled/mpm_event.load ||
      -e /work/rootfs/etc/apache2/mods-enabled/mpm_worker.load ]]; then
  echo "Apache has an unexpected conflicting MPM enabled" >&2; exit 1;
fi
# Apache's own configtest is not reliable inside the unmounted foreign
# QEMU image chroot: even Debian's mod_php maintainer scripts emitted
# "No MPM loaded" during installation, while the final symlink is present.
# Validate the exact MIPS module binaries, LoadModule lines and Include path
# offline. The *runtime* configtest is still required on real hardware.
python3 /src/image/verify-apache-offline.py /work/rootfs
# APT installs boot candidates into *staging*, never directly over a live
# kernel/bootloader. The offline assembler selects the exact package versions.
mapfile -t platform_versions < <(python3 - <<'PY'
import json
d=json.load(open("/work/published-platform.json"))
byname={p["name"]:p["version"] for p in d["packages"]}
for name in ("retrode3-linux-image","retrode3-linux-modules","retrode3-uboot-x1600"):
    print(byname[name])
PY
)
kver="${platform_versions[0]}"
[[ "$kver" == "${platform_versions[1]}" ]] || exit 1
uver="${platform_versions[2]}"
kernel_root="/work/rootfs/usr/lib/retrode3/kernel-candidates/$kver"
uboot_root="/work/rootfs/usr/lib/retrode3/bootloader-candidates/x1600/$uver"
krel="$(cat "$kernel_root/kernel-release")"
[[ "$krel" =~ ^[A-Za-z0-9.+_-]+$ ]] || exit 1
module_root="$kernel_root/lib/modules/$krel"
ko="$module_root/kernel/drivers/misc/retrode3/retrode3.ko"
[[ -s "$kernel_root/boot/uImage" &&
   -s "$kernel_root/boot/ingenic/lx16-retrode-2.9.5.dtb" &&
   -f "$module_root/modules.dep" && -s "$ko" ]] || {
  echo "Incomplete kernel/module Debian payload" >&2; exit 1;
}
actual="$(modinfo -F vermagic "$ko" | sed 's/[[:space:]]*$//')"
expected="$krel preempt mod_unload modversions MIPS32_R2 32BIT"
[[ "$actual" == "$expected" ]] || { echo "Kernel ABI mismatch: <$actual>" >&2; exit 1; }
for path in u-boot-with-spl-mbr-gpt.bin spl/u-boot-spl.bin u-boot.bin; do
  [[ -s "$uboot_root/$path" ]] || {
    echo "Missing packaged U-Boot $path" >&2; exit 1;
  }
done
# A resumed run may already have generated this temporary bundle.
# Rebuild staging from the same validated APT candidate, never nest copied
# module directories inside one another.
[[ ! -L /work/stage ]] || { echo "Refusing symlink staging" >&2; exit 1; }
if [[ "$resume" == 1 && -d /work/stage ]]; then
  rm -rf -- /work/stage
fi
mkdir -p /work/stage/boot/ingenic /work/stage/lib/modules
cp "$kernel_root/boot/uImage" /work/stage/boot/uImage
cp "$kernel_root/boot/ingenic/lx16-retrode-2.9.5.dtb" \
  /work/stage/boot/ingenic/lx16-retrode-2.9.5.dtb
mkimage -A mips -O linux -T script -C none \
  -n "Retrode3 Bookworm bootargs" \
  -d /src/image/assets/retrode3-bootargs.txt /work/stage/boot/bootargs.scr
cp -a "$module_root" "/work/stage/lib/modules/$krel"
# The SD assembler installs the matching module tree exactly once into
# the final disk rootfs. Do not pre-populate /lib/modules here.
tar -C /work/stage --numeric-owner -czf /work/kernel-bundle.tar.gz boot lib
# Native packages deliberately do not ship mutable /etc runtime state.
# The privileged corectl fails closed unless the enablement directory
# exists, is root-owned, non-symlink, and not group/other writable.
# Create it once for this fresh offline image, before enabling any cores.
core_parent=/work/rootfs/etc/retrode3
core_enabled="$core_parent/cores-enabled"
[[ ! -L "$core_parent" && ! -L "$core_enabled" ]] || {
  echo "Refusing symlinked cartridge core runtime state" >&2; exit 1;
}
install -d -o 0 -g 0 -m 0755 "$core_enabled"
[[ -d "$core_enabled" && ! -L "$core_enabled" &&
   "$(stat -c '%u:%g:%a' "$core_enabled")" == 0:0:755 ]] || {
  echo "Untrusted cartridge core enablement directory" >&2; exit 1;
}
for core in snes md nes; do
  chroot /work/rootfs /usr/sbin/retrode3-corectl enable "$core"
  [[ -L "/work/rootfs/etc/retrode3/cores-enabled/$core.so" ]] || exit 1
done
rm -f /work/rootfs/usr/bin/qemu-mipsel-static \
      /work/rootfs/usr/sbin/policy-rc.d /work/rootfs/etc/resolv.conf
rm -rf /work/rootfs/var/lib/apt/lists/*
python3 /src/image/verify-rootfs.py --with-retrode3 /work/rootfs
# These are OCI bind mounts for build-time APT only. Never put the
# host's character devices into the SD image; the target kernel mounts
# devtmpfs itself on boot.
tar --sort=name --numeric-owner --exclude='./dev/*' --exclude='dev/*' \
  -C /work/rootfs -cJf /work/retrode3-rootfs.tar.xz .
args=(--rootfs /work/retrode3-rootfs.tar.xz
      --kernel-bundle /work/kernel-bundle.tar.gz
      --kernel-release "$krel"
      --uboot-combined "$uboot_root/u-boot-with-spl-mbr-gpt.bin"
      --uboot-spl "$uboot_root/spl/u-boot-spl.bin"
      --uboot-binary "$uboot_root/u-boot.bin"
      --with-retrode3
      --output "/work/retrode3-develop.img.xz")
[[ ! -f /private/ssh.pub ]] || args+=(--ssh-authorized-key /private/ssh.pub)
python3 /src/image/assemble-sd-image.py "${args[@]}"
python3 /src/buildserver/write-package-image-manifest.py "$krel" "$uboot_root"
(cd /work && sha256sum -c --strict FULL-IMAGE-SHA256SUMS)
echo "Image from signed OSCR/OS/kernel/U-Boot packages ready: /work/retrode3-develop.img.xz"
