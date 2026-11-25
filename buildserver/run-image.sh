#!/usr/bin/env bash
# One-command image build on Amaterasu (retrode user), without writing SD disks.
set -euo pipefail
umask 027
branch="$1"
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
[[ -x "$vhost/package_$branch.sh" ]] || {
  echo "Missing existing package launcher: $vhost/package_$branch.sh" >&2; exit 1;
}
mkdir -p "$images"
exec 8>"$base/cache/image-$branch.lock"
flock -n 8 || { echo "An image build for $branch is running" >&2; exit 1; }
# Reuse exactly the existing automatic branch-aware package build/publisher.
# It also fast-forwards the selected OS checkout.
bash "$vhost/package_$branch.sh"
[[ "$(git -C "$checkout" symbolic-ref --short HEAD)" == "$branch" ]] || exit 1
[[ -z "$(git -C "$checkout" status --porcelain --untracked-files=no)" ]] || exit 1
os_sha="$(git -C "$checkout" rev-parse HEAD)"
published="$base/cache/last-published-$branch.json"
[[ -r "$published" ]] || {
  echo "No completed published package snapshot for $branch" >&2; exit 1;
}
published_sha="$(python3 - "$published" "$suite" <<'PY'
import json, re, sys
d=json.load(open(sys.argv[1]))
sha=d.get("os_commit","")
if d.get("release_channel")!=sys.argv[2] or not re.fullmatch(r"[0-9a-f]{40}",sha):
    sys.exit("Bad published package manifest")
print(sha)
PY
)"
# A docs-only commit may not produce .deb changes. Validate that it cannot
# affect the image's package binaries before reusing the published snapshot.
python3 "$checkout/buildserver/release-changes.py" \
    --repo "$checkout" --base "$published_sha" --head "$os_sha" || {
  echo "Published packages don't correspond to current OS checkout" >&2; exit 1;
}

[[ -r /proc/sys/fs/binfmt_misc/qemu-mipsel ]] &&
  grep -qx enabled /proc/sys/fs/binfmt_misc/qemu-mipsel || {
    echo "Host QEMU MIPSEL binfmt_misc registration is missing" >&2; exit 1;
  }
[[ -d "$private" && ! -L "$private" ]] || {
  echo "Missing private image inputs: $private" >&2; exit 1;
}
for name in FULLCONFIG retrode3-archive.gpg apt-fingerprint; do
  [[ -f "$private/$name" && ! -L "$private/$name" ]] || {
    echo "Missing private image input: $name" >&2; exit 1;
  }
done
apt_fpr="$(tr -d '[:space:]' < "$private/apt-fingerprint")"
[[ "$apt_fpr" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "Invalid trusted APT fingerprint" >&2; exit 1;
}
kernel_url=https://github.com/DragonBox-Shop/retrode3-kernel.git
kernel_ref="refs/heads/$branch"
kernel_line="$(git ls-remote --exit-code "$kernel_url" "$kernel_ref")"
kernel_sha="${kernel_line%%[[:space:]]*}"
[[ "$kernel_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
uboot_line="$(git ls-remote --exit-code \
  https://github.com/DragonBox-Shop/retrode3-uboot.git refs/heads/develop)"
uboot_sha="${uboot_line%%[[:space:]]*}"
[[ "$uboot_sha" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Cannot resolve pinned Retrode3 U-Boot develop" >&2; exit 1;
}

run="$(mktemp -d "$images/run.XXXXXXXX")"
cp "$published" "$run/published-packages.json"
printf '%s\n' "$os_sha" > "$run/image-os-commit"
echo "Image $branch ($suite); OS $os_sha; packages $published_sha; kernel $kernel_sha; U-Boot $uboot_sha"
echo "Workspace: $run"
# All source and private inputs are read-only; only /work is writable.
# No host /dev, signing secret, website, Maildir or sudo mounts.
image=localhost/retrode3-image-builder:bookworm
podman --runtime=crun --cgroup-manager=systemd build \
    --network=slirp4netns \
    -f "$checkout/buildserver/Containerfile.image" -t "$image" \
    "$checkout/buildserver"
podman --runtime=crun --cgroup-manager=systemd run --rm \
    --network=slirp4netns --cap-drop=all \
    --cap-add=CHOWN --cap-add=FOWNER --cap-add=SETUID \
    --cap-add=SETGID --cap-add=SYS_CHROOT --cap-add=MKNOD \
    --cap-add=DAC_OVERRIDE --security-opt=no-new-privileges \
    --cpus "${RETRODE3_IMAGE_CPUS:-2}" \
    --memory "${RETRODE3_IMAGE_MEMORY:-3g}" \
    --pids-limit "${RETRODE3_IMAGE_PIDS:-512}" \
    -v "$checkout:/src:ro" -v "$run:/work:rw" \
    -v /proc/sys/fs/binfmt_misc:/proc/sys/fs/binfmt_misc:ro \
    -v "$private:/private:ro" \
    -e "RETRODE3_IMAGE_BRANCH=$branch" \
    -e "RETRODE3_IMAGE_SUITE=$suite" \
    -e "RETRODE3_OS_SHA=$published_sha" \
    -e "RETRODE3_KERNEL_SHA=$kernel_sha" \
    -e "RETRODE3_APT_FINGERPRINT=$apt_fpr" \
    -e "RETRODE3_UBOOT_SHA=$uboot_sha" \
    "$image" bash /src/buildserver/build-image-container.sh
(cd "$run" && sha256sum --check --strict FULL-IMAGE-SHA256SUMS)
echo "Image build complete: $run/retrode3-$branch.img.xz"
echo "NOT RELEASED: source-built U-Boot and kernel require physical boot acceptance."
