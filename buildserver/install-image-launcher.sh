#!/usr/bin/env bash
# Install the isolated, source-built DEVELOPMENT image launcher only.
# Never rewrite the tested APT launchers or the stable image launcher.
set -euo pipefail
umask 027
[[ "$#" == 0 ]] || { echo "Usage: $0" >&2; exit 2; }
[[ "$(id -un)" == retrode ]] || { echo "Run as retrode" >&2; exit 1; }
base=/srv/www/vhosts/retrode.com/buildserver
vhost=/srv/www/vhosts/retrode.com
image_checkout="$base/src/retrode3-image-dev"
[[ -e "$image_checkout/.git" && ! -L "$image_checkout/.git" ]] &&\
  git -C "$image_checkout" rev-parse --is-inside-work-tree | grep -qx true || {
  echo "Missing dedicated source-built image Git worktree: $image_checkout" >&2; exit 1;
}
[[ "$(git -C "$image_checkout" symbolic-ref --short HEAD)" == feature/source-built-x1600-uboot-image ]] || {
  echo "Wrong image checkout branch, require feature/source-built-x1600-uboot-image" >&2; exit 1;
}
[[ -z "$(git -C "$image_checkout" status --porcelain --untracked-files=no)" ]] || {
  echo "Modified image source checkout; refusing" >&2; exit 1;
}
[[ -f "$image_checkout/image/source_uboot_layout.py" ]] || {
  echo "Missing source-built U-Boot image assembly code" >&2; exit 1;
}
bash -n "$image_checkout/buildserver/run-image.sh"
bash -n "$image_checkout/buildserver/build-image-container.sh"
[[ -x "$vhost/package_develop.sh" ]] || {
  echo "Missing installed tagged APT package launcher" >&2; exit 1;
}
target="$vhost/build_image_develop.sh"
[[ ! -L "$target" ]] || { echo "Refusing image launcher symlink" >&2; exit 1; }
if [[ -e "$target" ]] &&
    ! grep -Fqx '# Managed by Retrode3 buildserver/install-launchers.sh' "$target" &&
    ! grep -Fqx '# Managed by Retrode3 buildserver/install-image-launcher.sh' "$target"; then
  echo "Refusing to overwrite unmanaged image launcher" >&2; exit 1;
fi
temp="$(mktemp "$vhost/.retrode3-image-XXXXXXXX")"
trap 'rm -f "$temp"' EXIT
cat > "$temp" <<EOF
#!/usr/bin/env bash
# Managed by Retrode3 buildserver/install-image-launcher.sh
set -euo pipefail
exec bash "$image_checkout/buildserver/run-image.sh" develop
EOF
install -m 750 "$temp" "$target"
echo "Installed source-built development image launcher: $target"
echo "Unchanged: package_develop.sh, package_master.sh, build_image_master.sh"
