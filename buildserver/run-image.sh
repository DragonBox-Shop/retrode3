#!/usr/bin/env bash
# One-command image build on Amaterasu (retrode user), without writing SD disks.
set -euo pipefail
umask 027
branch="${1:-}"
# Optional INTERNAL resume: caller must identify an existing run directory.
# The four public entrypoints and their regular build behavior are unchanged.
[[ "$#" == 1 || ( "$#" == 3 && "$2" == --resume && "$3" == /* ) ]] || {
  echo "Usage: $0 develop [--resume /absolute/previous-run]" >&2; exit 2;
}
resume=0
resume_dir=
if [[ "$#" == 3 ]]; then resume=1; resume_dir="$3"; fi
# U-Boot/master still contains an unrelated historical upstream default.
# Never publish a master image until a separate source/board acceptance.
[[ "$branch" == develop ]] || {
  echo "Source-built U-Boot is only wired for develop hardware candidates" >&2
  exit 1
}
case "$branch" in
  develop) suite=testing; checkout_name=retrode3-testing-pr ;;
  master) suite=stable; checkout_name=retrode3-stable-pr ;;
  *) echo "Usage: run-image.sh develop|master" >&2; exit 2 ;;
esac
base=/srv/www/vhosts/retrode.com/buildserver
vhost=/srv/www/vhosts/retrode.com
checkout="$base/src/$checkout_name"
# Image tooling is tested separately from moving OS develop; userland binaries
# come exclusively from the published, immutable tagged APT snapshot.
image_checkout="$(cd "$(dirname "$0")/.." && pwd)"
private="$base/private/image/$branch"
images="$base/artifacts/images/$branch"
[[ "$(id -un)" == retrode ]] || {
  echo "Run as the unprivileged retrode user" >&2; exit 1;
}
for cmd in git python3 podman sha256sum flock; do
  command -v "$cmd" >/dev/null || {
    echo "Missing host tool: $cmd" >&2; exit 1;
  }
done
[[ -d "$checkout/.git" ]] || {
  echo "Missing branch checkout: $checkout" >&2; exit 1;
}
[[ -e "$image_checkout/.git" && ! -L "$image_checkout/.git" && "$image_checkout" != "$checkout" ]] &&\
  git -C "$image_checkout" rev-parse --is-inside-work-tree | grep -qx true || {
  echo "Image builder requires its own dedicated Git checkout, separate from the APT automation checkout" >&2
  exit 1
}
[[ -z "$(git -C "$image_checkout" status --porcelain --untracked-files=no)" ]] || {
  echo "Image builder checkout has modified tracked files" >&2; exit 1;
}
image_builder_sha="$(git -C "$image_checkout" rev-parse HEAD)"
[[ "$image_builder_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
[[ -x "$vhost/package_$branch.sh" ]] || {
  echo "Missing package publisher; prepare the package server first" >&2; exit 1;
}
mkdir -p "$images"
exec 8>"$base/cache/image-$branch.lock"
flock -n 8 || { echo "An image build for $branch is running" >&2; exit 1; }
# The public image launcher first refreshes all package sources through
# the matching package launcher. Compilation belongs there, NEVER in the
# image container. The package launcher returns only after signed APT export.
if [[ "$resume" == 0 ]]; then
  echo "=== Updating ${branch} packages (OS, OSCR, kernel, U-Boot) ==="
  bash "$vhost/package_$branch.sh"
else
  echo "=== RESUME: no package rebuild or APT publication; checking existing signed snapshots ==="
fi
[[ "$(git -C "$checkout" symbolic-ref --short HEAD)" == "$branch" ]] || exit 1
[[ -z "$(git -C "$checkout" status --porcelain --untracked-files=no)" ]] || exit 1
published="$base/cache/last-published-$branch.json"
[[ -r "$published" && ! -L "$published" ]] || {
  echo "No completed published package snapshot for $branch" >&2; exit 1;
}
selector="$base/automation/select-release-tag.py"
[[ -r "$selector" ]] || {
  echo "Missing installed APT tag selector: $selector" >&2; exit 1;
}
# The package launcher just fetched and published (or found) these exact tags.
# Do not reuse an older published snapshot for a newer tag pair.
selection="$(python3 "$selector" "$checkout" "$branch")"
IFS=$'\t' read -r os_tag os_sha <<< "$selection"
oscr_history="$base/cache/oscr-git-history.git"
[[ -d "$oscr_history" ]] || { echo "Missing OSCR Git history cache" >&2; exit 1; }
selection="$(python3 "$selector" "$oscr_history" "$branch")"
IFS=$'\t' read -r oscr_tag oscr_sha <<< "$selection"
[[ "$os_sha" =~ ^[a-f0-9]{40}$ && "$oscr_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
python3 "$image_checkout/buildserver/verify-image-snapshot.py" \
  "$published" "$suite" "$branch" "$os_tag" "$os_sha" "$oscr_tag" "$oscr_sha"
[[ -r /proc/sys/fs/binfmt_misc/qemu-mipsel ]] &&
  grep -qx enabled /proc/sys/fs/binfmt_misc/qemu-mipsel || {
    echo "Host QEMU MIPSEL binfmt_misc registration is missing" >&2; exit 1;
  }
[[ -d "$private" && ! -L "$private" ]] || {
  echo "Missing private image inputs: $private" >&2; exit 1;
}
for name in retrode3-archive.gpg apt-fingerprint; do
  [[ -f "$private/$name" && ! -L "$private/$name" ]] || {
    echo "Missing private image input: $name" >&2; exit 1;
  }
done
apt_fpr="$(tr -d '[:space:]' < "$private/apt-fingerprint")"
[[ "$apt_fpr" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "Invalid trusted APT fingerprint" >&2; exit 1;
}
# Kernel and U-Boot must already be present as published signed testing .debs.
platform="$base/cache/last-published-platform-develop.json"
[[ -s "$platform" && -f "$platform" && ! -L "$platform" ]] || {
  echo "Missing published platform packages. Run package-develop-all first." >&2
  exit 1
}
python3 "$image_checkout/buildserver/verify-platform-snapshot.py" \
  "$platform" "$base/repository"
kernel_sha="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sources"]["kernel"])' "$platform")"
uboot_sha="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sources"]["uboot"])' "$platform")"
[[ "$kernel_sha" =~ ^[a-f0-9]{40}$ && "$uboot_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1

# Mount only the public APT trust material.
# Do not expose the whole private image input directory to Podman.
private_mounts=(
  -v "$private/retrode3-archive.gpg:/private/retrode3-archive.gpg:ro"
  -v "$private/apt-fingerprint:/private/apt-fingerprint:ro"
)
if [[ "$resume" == 1 ]]; then
  run="$(realpath -e -- "$resume_dir")"
  [[ -d "$run" && ! -L "$resume_dir" &&
     "$(dirname -- "$run")" == "$images" &&
     "$(basename -- "$run")" == run.* ]] || {
    echo "Refusing unsafe/outside image resume workspace: $resume_dir" >&2; exit 1;
  }
  for item in published-packages.json published-platform.json image-os-commit image-builder-commit; do
    [[ -s "$run/$item" && -f "$run/$item" && ! -L "$run/$item" ]] || {
      echo "Incomplete or unsafe resume metadata: $item" >&2; exit 1;
    }
  done
  cmp -s "$run/published-packages.json" "$published" &&
    cmp -s "$run/published-platform.json" "$platform" &&
    [[ "$(cat "$run/image-os-commit")" == "$os_sha" ]] || {
      echo "RESUME REFUSED: published package set or OS source changed; use a clean build" >&2
      exit 1
    }
  [[ -s "$run/rootfs/var/lib/dpkg/status" &&
     -s "$run/base-rootfs/SHA256SUMS" ]] || {
    echo "RESUME REFUSED: prior rootfs or bootstrap checksum missing" >&2; exit 1;
  }
  echo "Resuming existing signed package image workspace: $run"
else
  run="$(mktemp -d "$images/run.XXXXXXXX")"
fi
# A foreign-arch chroot running APT needs /dev/null and /dev/urandom.
# Rootless Podman cannot mknod in its writable bind-mounted /work tree.
# Prepare harmless regular-file mountpoints in the new, private run dir,
# then let Podman's OCI runtime bind ONLY these host character devices.
# No block devices, no host /dev directory mount and no host chmod/mknod.
device_mounts=()
mkdir -p "$run/rootfs/dev"
for device in null zero random urandom tty; do
  [[ -c "/dev/$device" && ! -L "/dev/$device" ]] || {
    echo "Missing safe host character device: /dev/$device" >&2; exit 1;
  }
  if [[ "$resume" == 1 ]]; then
    [[ -f "$run/rootfs/dev/$device" && ! -L "$run/rootfs/dev/$device" ]] || {
      echo "Missing or unsafe previous device mountpoint: $device" >&2; exit 1;
    }
  else
    : > "$run/rootfs/dev/$device"
  fi
  device_mounts+=( -v "/dev/$device:/work/rootfs/dev/$device:rw" )
done
if [[ "$resume" == 0 ]]; then
  cp "$published" "$run/published-packages.json"
  cp "$platform" "$run/published-platform.json"
  printf '%s\n' "$os_sha" > "$run/image-os-commit"
  printf '%s\n' "$image_builder_sha" > "$run/image-builder-commit"
fi
echo "Image $branch ($suite); OS $os_tag $os_sha; OSCR $oscr_tag $oscr_sha; kernel $kernel_sha; U-Boot $uboot_sha; image tooling $image_builder_sha"
echo "Workspace: $run"
# All source and private inputs are read-only; only /work is writable.
# Only the five minimal character devices above are bind-mounted into the
# disposable foreign-arch chroot. No host /dev DIRECTORY, block devices,
# signing secret, website, Maildir or sudo mounts.
image=localhost/retrode3-image-builder:bookworm
podman --runtime=crun --cgroup-manager=systemd build \
    --network=slirp4netns \
    -f "$image_checkout/buildserver/Containerfile.image" -t "$image" \
    "$image_checkout/buildserver"
podman --runtime=crun --cgroup-manager=systemd run --rm \
    --network=slirp4netns --cap-drop=all \
    --cap-add=CHOWN --cap-add=FOWNER --cap-add=SETUID \
    --cap-add=SETGID --cap-add=SYS_CHROOT --cap-add=MKNOD \
    --cap-add=DAC_OVERRIDE --security-opt=no-new-privileges \
    --cpus "${RETRODE3_IMAGE_CPUS:-2}" \
    --memory "${RETRODE3_IMAGE_MEMORY:-3g}" \
    --pids-limit "${RETRODE3_IMAGE_PIDS:-512}" \
    -v "$image_checkout:/src:ro" -v "$run:/work:rw" \
    -v /proc/sys/fs/binfmt_misc:/proc/sys/fs/binfmt_misc:ro \
    "${device_mounts[@]}" "${private_mounts[@]}" \
    -e "RETRODE3_IMAGE_BRANCH=$branch" \
    -e "RETRODE3_IMAGE_RESUME=$resume" \
    -e "RETRODE3_IMAGE_SUITE=$suite" \
    -e "RETRODE3_OS_SHA=$os_sha" \
    -e "RETRODE3_OS_TAG=$os_tag" \
    -e "RETRODE3_OSCR_TAG=$oscr_tag" \
    -e "RETRODE3_OSCR_SHA=$oscr_sha" \
    -e "RETRODE3_IMAGE_BUILDER_SHA=$image_builder_sha" \
    -e "RETRODE3_KERNEL_SHA=$kernel_sha" \
    -e "RETRODE3_APT_FINGERPRINT=$apt_fpr" \
    -e "RETRODE3_UBOOT_SHA=$uboot_sha" \
    "$image" bash /src/buildserver/build-image-from-packages.sh
(cd "$run" && sha256sum --check --strict FULL-IMAGE-SHA256SUMS)
echo "Image build complete: $run/retrode3-$branch.img.xz"
echo "NOT RELEASED: source-built U-Boot and kernel require physical boot acceptance."
