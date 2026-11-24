#!/usr/bin/env bash
# Runs only inside disposable rootless Podman. Writes to /work, never /dev disks.
set -euo pipefail
umask 022
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C

: "$RETRODE3_IMAGE_BRANCH" "$RETRODE3_IMAGE_SUITE" "$RETRODE3_KERNEL_SHA"
: "$RETRODE3_OS_SHA" "$RETRODE3_APT_FINGERPRINT" "$RETRODE3_PREBOOT_SHA256"
case "$RETRODE3_IMAGE_BRANCH:$RETRODE3_IMAGE_SUITE" in
  develop:testing|master:stable) ;;
  *) echo "Invalid Git branch/APT suite pairing" >&2; exit 1 ;;
esac
[[ "$RETRODE3_KERNEL_SHA" =~ ^[a-f0-9]{40}$ &&
   "$RETRODE3_OS_SHA" =~ ^[a-f0-9]{40}$ &&
   "$RETRODE3_PREBOOT_SHA256" =~ ^[a-f0-9]{64}$ &&
   "$RETRODE3_APT_FINGERPRINT" =~ ^[A-Fa-f0-9]{40}$ ]] || {
  echo "Missing or invalid pinned inputs" >&2; exit 1;
}
[[ "$(id -u)" = 0 ]] || { echo "Container must run as namespaced root" >&2; exit 1; }
for file in /private/FULLCONFIG /private/retrode3-archive.gpg \
            /private/sd-preboot-1MiB.bin /work/published-packages.json; do
  [[ -f "$file" && ! -L "$file" ]] || {
    echo "Missing regular private input: $file" >&2; exit 1;
  }
done
[[ -x /toolchain/bin/mipsel-linux-gcc ]] || {
  echo "Missing pinned Bootlin MIPS32EL toolchain at /toolchain" >&2; exit 1;
}
printf '%s  %s\n' "$RETRODE3_PREBOOT_SHA256" \
  /private/sd-preboot-1MiB.bin | sha256sum --strict --check -

# Validate the package snapshot before even downloading a kernel.
python3 - "$RETRODE3_IMAGE_SUITE" "$RETRODE3_OS_SHA" <<'PY'
import json, re, sys
d=json.load(open("/work/published-packages.json"))
if d.get("release_channel") != sys.argv[1] or d.get("os_commit") != sys.argv[2]:
    sys.exit("Published package manifest does not match requested OS revision/suite")
records=d.get("packages")
if not isinstance(records,list) or not records:
    sys.exit("No published packages")
names={x["package"] for x in records}
if len(names)!=len(records) or not {"retrode3-core-runtime","retrode3-web-control"}.issubset(names):
    sys.exit("Required Retrode3 packages missing from snapshot")
for x in records:
    if not re.fullmatch(r"retrode3-[a-z0-9-]+", x["package"]):
        sys.exit("Unsafe package name")
for key in ("native_version","web_version","oscr_commit","sanni_commit"):
    if not d.get(key):
        sys.exit("Unpinned package input: "+key)
PY

mkdir -p /work/kernel-build /work/modules-root /work/stage/boot/ingenic
echo "=== Linux $RETRODE3_KERNEL_SHA from Retrode3 kernel repository ==="
git clone --quiet --depth 1 --single-branch --branch "$RETRODE3_IMAGE_BRANCH" \
  https://github.com/DragonBox-Shop/retrode3-kernel.git /work/kernel-src
actual="$(git -C /work/kernel-src rev-parse HEAD)"
[[ "$actual" == "$RETRODE3_KERNEL_SHA" ]] || {
  echo "Kernel branch moved during build: $actual" >&2; exit 1;
}
cp /private/FULLCONFIG /work/kernel-build/.config
cross=/toolchain/bin/mipsel-linux-
kernel_make() {
  make -C /work/kernel-src O=/work/kernel-build ARCH=mips \
    CROSS_COMPILE="$cross" LOCALVERSION=+ "$@"
}
kernel_make olddefconfig
grep -qx 'CONFIG_MODVERSIONS=y' /work/kernel-build/.config || {
  echo "FULLCONFIG lost CONFIG_MODVERSIONS" >&2; exit 1;
}
krel="$(kernel_make -s --no-print-directory kernelrelease | tail -n 1)"
[[ "$krel" =~ ^[a-zA-Z0-9.+_-]+$ ]] || exit 1
printf '%s\n' "$krel" > /work/kernel.release
echo "Compiling full MIPS kernel, modules and Retrode3 2.9.5 DTB: $krel"
kernel_make -j2 uImage modules dtbs
kernel_make INSTALL_MOD_PATH=/work/modules-root modules_install
moddir="/work/modules-root/lib/modules/$krel"
[[ -d "$moddir" && -f "$moddir/modules.dep" ]] || {
  echo "Kernel modules_install did not create matching modules.dep" >&2; exit 1;
}
rm -f "$moddir/build" "$moddir/source"
ko="$moddir/kernel/drivers/misc/retrode3/retrode3.ko"
[[ -f "$ko" ]] || { echo "Missing built Retrode3 module" >&2; exit 1; }
modinfo -F vermagic "$ko" | grep -Fqx "$krel preempt mod_unload modversions MIPS32_R2 32BIT" || {
  echo "Retrode3 vermagic not validated against expected target" >&2; exit 1;
}
cp -L /work/kernel-build/arch/mips/boot/uImage /work/stage/boot/uImage
cp /work/kernel-build/arch/mips/boot/dts/ingenic/lx16-retrode-2.9.5.dtb \
   /work/stage/boot/ingenic/lx16-retrode-2.9.5.dtb
mkimage -A mips -O linux -T script -C none \
  -n "Retrode3 Bookworm bootargs" \
  -d /src/image/assets/retrode3-bootargs.txt /work/stage/boot/bootargs.scr
mkdir -p "/work/stage/lib/modules"
cp -a "$moddir" "/work/stage/lib/modules/$krel"
tar -C /work/stage --numeric-owner -czf /work/kernel-bundle.tar.gz boot lib
echo "Kernel bundle ready: $krel"

echo "=== Debian Bookworm MIPSEL base with signed Retrode3 APT ==="
export RETRODE3_APT_PUBLIC_KEY=/private/retrode3-archive.gpg
export RETRODE3_APT_SUITE="$RETRODE3_IMAGE_SUITE"
mkdir -p /work/base-rootfs
bash /src/image/build-bookworm-rootfs.sh /work/base-rootfs
mkdir -p /work/rootfs
tar --numeric-owner -xJf /work/base-rootfs/retrode3-bookworm-mipsel-rootfs.tar.xz \
    -C /work/rootfs

# Install a complete, EXACT published package set with a temporary chroot
# emulator. The archive has no emulators, host DNS or policy-rc helpers.
cp /usr/bin/qemu-mipsel-static /work/rootfs/usr/bin/qemu-mipsel-static
cp /etc/resolv.conf /work/rootfs/etc/resolv.conf
cat > /work/rootfs/usr/sbin/policy-rc.d <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 /work/rootfs/usr/sbin/policy-rc.d
mapfile -t packages < <(python3 - <<'PY'
import json
d=json.load(open("/work/published-packages.json"))
for rec in sorted(d["packages"],key=lambda x:x["package"]):
    name=rec["package"]
    version=d["web_version"] if name=="retrode3-web-control" else d["native_version"]
    print(name+"="+version)
PY
)
echo "=== Installing pinned Retrode3 Debian packages and dependencies ==="
chroot /work/rootfs /usr/bin/apt-get update
chroot /work/rootfs /usr/bin/apt-get -y --no-install-recommends install \
  "${packages[@]}"
# Read back exact versions; fail if any meta-package was silently replaced.
for spec in "${packages[@]}"; do
  pkg="${spec%%=*}"
  ver="${spec#*=}"
  actual="$(chroot /work/rootfs dpkg-query -W -f='${Version}' "$pkg")"
  [[ "$actual" == "$ver" ]] || {
    echo "Wrong installed package version for $pkg" >&2; exit 1;
  }
done
# Final image contains neither QEMU, build-only service policy nor DNS leak.
rm -f /work/rootfs/usr/bin/qemu-mipsel-static \
      /work/rootfs/usr/sbin/policy-rc.d /work/rootfs/etc/resolv.conf
mkdir -p /work/rootfs/etc/init.d
touch /work/rootfs/etc/init.d/.legacy-bootordering
rm -rf /work/rootfs/var/lib/apt/lists/*
python3 /src/image/verify-rootfs.py --with-retrode3 /work/rootfs
tar -C /work/rootfs --numeric-owner --sort=name -cJf \
    /work/retrode3-rootfs.tar.xz .

echo "=== Build regular-file SD image (temporary verified donor SPL) ==="
args=(--rootfs /work/retrode3-rootfs.tar.xz
      --kernel-bundle /work/kernel-bundle.tar.gz
      --kernel-release "$krel"
      --sd-preboot /private/sd-preboot-1MiB.bin
      --migrate-stale-gpt --with-retrode3
      --output "/work/retrode3-$RETRODE3_IMAGE_BRANCH.img.xz")
if [[ -f /private/ssh.pub ]]; then
  args+=(--ssh-authorized-key /private/ssh.pub)
fi
python3 /src/image/assemble-sd-image.py "${args[@]}"

python3 - "$RETRODE3_IMAGE_BRANCH" "$RETRODE3_IMAGE_SUITE" \
          "$RETRODE3_OS_SHA" "$RETRODE3_KERNEL_SHA" "$krel" <<'PY'
import hashlib, json, pathlib, sys
work=pathlib.Path("/work")
branch,suite,ossha,ksha,krel=sys.argv[1:]
def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()
files=["kernel-bundle.tar.gz","retrode3-rootfs.tar.xz",
       "retrode3-"+branch+".img.xz"]
manifest={
 "schema":1,"branch":branch,"apt_suite":suite,
 "os_commit":ossha,"kernel_commit":ksha,"kernel_release":krel,
 "image_build_os_commit":open("/work/image-os-commit").read().strip(),
 "kernel_config_sha256":sha("/private/FULLCONFIG"),
 "kernel_effective_config_sha256":sha("/work/kernel-build/.config"),
 "kernel_cross_compiler_sha256":sha("/toolchain/bin/mipsel-linux-gcc"),
 "apt_public_key_sha256":sha("/private/retrode3-archive.gpg"),
 "apt_public_fingerprint":open("/private/apt-fingerprint").read().strip(),
 "donor_preboot_sha256":sha("/private/sd-preboot-1MiB.bin"),
 "donor_preboot_source":"private, SHA256-pinned temporary bootloader dump",
 "bootloader_source_built":False,
 "hardware_accepted":False,"customer_releasable":False,
 "package_snapshot":json.load(open("/work/published-packages.json")),
 "files":{name:sha(work/name) for name in files},
}
(work/"full-image-manifest.json").write_text(
    json.dumps(manifest,sort_keys=True,indent=2)+"\n")
files.append("full-image-manifest.json")
(work/"FULL-IMAGE-SHA256SUMS").write_text(
    "".join(sha(work/name)+"  "+name+"\n" for name in files))
PY
(cd /work && sha256sum -c FULL-IMAGE-SHA256SUMS)
echo "DONE: /work/retrode3-$RETRODE3_IMAGE_BRANCH.img.xz"
