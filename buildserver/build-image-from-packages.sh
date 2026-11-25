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
mkdir -p /work/base-rootfs
bash /src/image/build-bookworm-rootfs.sh /work/base-rootfs
mkdir -p /work/rootfs
tar --numeric-owner -xJf /work/base-rootfs/retrode3-bookworm-mipsel-rootfs.tar.xz \
  -C /work/rootfs
cp /usr/bin/qemu-mipsel-static /work/rootfs/usr/bin/qemu-mipsel-static
cp /etc/resolv.conf /work/rootfs/etc/resolv.conf
cat > /work/rootfs/usr/sbin/policy-rc.d <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 /work/rootfs/usr/sbin/policy-rc.d
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
echo "=== Installing OS/OSCR and platform boot packages from signed APT ==="
chroot /work/rootfs /usr/bin/apt-get update
chroot /work/rootfs /usr/bin/apt-get -y --no-install-recommends install \
  "${packages[@]}"
for spec in "${packages[@]}"; do
  pkg="${spec%%=*}"
  ver="${spec#*=}"
  got="$(chroot /work/rootfs dpkg-query -W -f='${Version}' "$pkg")"
  [[ "$got" == "$ver" ]] || {
    echo "Wrong APT package version: $pkg actual=$got expected=$ver" >&2; exit 1;
  }
done
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
mkdir -p /work/stage/boot/ingenic /work/stage/lib/modules
cp "$kernel_root/boot/uImage" /work/stage/boot/uImage
cp "$kernel_root/boot/ingenic/lx16-retrode-2.9.5.dtb" \
  /work/stage/boot/ingenic/lx16-retrode-2.9.5.dtb
mkimage -A mips -O linux -T script -C none \
  -n "Retrode3 Bookworm bootargs" \
  -d /src/image/assets/retrode3-bootargs.txt /work/stage/boot/bootargs.scr
cp -a "$module_root" "/work/stage/lib/modules/$krel"
# The new image's rootfs receives the selected module version.
mkdir -p /work/rootfs/lib/modules
[[ ! -e "/work/rootfs/lib/modules/$krel" ]] || exit 1
cp -a "$module_root" "/work/rootfs/lib/modules/$krel"
tar -C /work/stage --numeric-owner -czf /work/kernel-bundle.tar.gz boot lib
for core in snes md nes; do
  chroot /work/rootfs /usr/sbin/retrode3-corectl enable "$core"
  [[ -L "/work/rootfs/etc/retrode3/cores-enabled/$core.so" ]] || exit 1
done
rm -f /work/rootfs/usr/bin/qemu-mipsel-static \
      /work/rootfs/usr/sbin/policy-rc.d /work/rootfs/etc/resolv.conf
rm -rf /work/rootfs/var/lib/apt/lists/*
python3 /src/image/verify-rootfs.py --with-retrode3 /work/rootfs
tar --sort=name --numeric-owner -C /work/rootfs -cJf \
  /work/retrode3-rootfs.tar.xz .
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
