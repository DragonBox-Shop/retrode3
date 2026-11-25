#!/usr/bin/env bash
# One-command image build on Amaterasu (retrode user), without writing SD disks.
set -euo pipefail
umask 027
branch="${1:-}"
[[ "$#" == 1 ]] || { echo "Usage: $0 develop" >&2; exit 2; }
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
[[ -d "$image_checkout/.git" && "$image_checkout" != "$checkout" ]] || {
  echo "Image builder requires its own dedicated Git checkout, separate from the APT automation checkout" >&2
  exit 1
}
[[ -z "$(git -C "$image_checkout" status --porcelain --untracked-files=no)" ]] || {
  echo "Image builder checkout has modified tracked files" >&2; exit 1;
}
image_builder_sha="$(git -C "$image_checkout" rev-parse HEAD)"
[[ "$image_builder_sha" =~ ^[a-f0-9]{40}$ ]] || exit 1
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
python3 - "$published" "$suite" "$branch" "$os_tag" "$os_sha" "$oscr_tag" "$oscr_sha" <<'PY'
import json, re, sys
manifest, suite, branch, os_tag, os_sha, oscr_tag, oscr_sha = sys.argv[1:]
with open(manifest, encoding="utf-8") as stream:
    data = json.load(stream)
expected = {
    "release_channel": suite, "oscr_branch": branch,
    "os_tag": os_tag, "os_commit": os_sha,
    "oscr_tag": oscr_tag, "oscr_commit": oscr_sha,
}
for key, value in expected.items():
    if data.get(key) != value:
        sys.exit("Published APT snapshot does not match latest selected tag: " + key)
if not data.get("auto_versioned") or not data.get("packages"):
    sys.exit("Published APT snapshot is not a verified tagged release")
if not re.fullmatch(r"[0-9a-f]{40}", data.get("sanni_commit", "")):
    sys.exit("Missing pinned Sanni gitlink")
print("Image source locked to published OS/OSCR tags:", os_tag, oscr_tag)
PY

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

# Mount only the public APT trust material and optional public test SSH key.
# Do not expose the whole private image input directory to Podman.
private_mounts=(
  -v "$private/retrode3-archive.gpg:/private/retrode3-archive.gpg:ro"
  -v "$private/apt-fingerprint:/private/apt-fingerprint:ro"
)
if [[ -e "$private/ssh.pub" || -L "$private/ssh.pub" ]]; then
  [[ -f "$private/ssh.pub" && ! -L "$private/ssh.pub" ]] || {
    echo "Unsafe optional SSH public key path" >&2; exit 1;
  }
  private_mounts+=( -v "$private/ssh.pub:/private/ssh.pub:ro" )
fi
run="$(mktemp -d "$images/run.XXXXXXXX")"
cp "$published" "$run/published-packages.json"
printf '%s\n' "$os_sha" > "$run/image-os-commit"
printf '%s\n' "$image_builder_sha" > "$run/image-builder-commit"
echo "Image $branch ($suite); OS $os_tag $os_sha; OSCR $oscr_tag $oscr_sha; kernel $kernel_sha; U-Boot $uboot_sha; image tooling $image_builder_sha"
echo "Workspace: $run"
# All source and private inputs are read-only; only /work is writable.
# No host /dev, signing secret, website, Maildir or sudo mounts.
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
    "${private_mounts[@]}" \
    -e "RETRODE3_IMAGE_BRANCH=$branch" \
    -e "RETRODE3_IMAGE_SUITE=$suite" \
    -e "RETRODE3_OS_SHA=$os_sha" \
    -e "RETRODE3_OS_TAG=$os_tag" \
    -e "RETRODE3_OSCR_TAG=$oscr_tag" \
    -e "RETRODE3_OSCR_SHA=$oscr_sha" \
    -e "RETRODE3_IMAGE_BUILDER_SHA=$image_builder_sha" \
    -e "RETRODE3_KERNEL_SHA=$kernel_sha" \
    -e "RETRODE3_APT_FINGERPRINT=$apt_fpr" \
    -e "RETRODE3_UBOOT_SHA=$uboot_sha" \
    "$image" bash /src/buildserver/build-image-container.sh
(cd "$run" && sha256sum --check --strict FULL-IMAGE-SHA256SUMS)
echo "Image build complete: $run/retrode3-$branch.img.xz"
echo "NOT RELEASED: source-built U-Boot and kernel require physical boot acceptance."
