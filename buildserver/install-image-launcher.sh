#!/usr/bin/env bash
# Install coordinated DEVELOPMENT package + image launchers.
# Reuse verified OS/OSCR release automation; never alter master/stable.
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
# A linked worktree cannot check out develop twice. Use a detached,
# explicitly selected revision already contained in origin/develop.
git -C "$image_checkout" merge-base --is-ancestor HEAD refs/remotes/origin/develop || {
  echo "Image tooling must be a revision integrated into origin/develop" >&2; exit 1;
}
[[ -z "$(git -C "$image_checkout" status --porcelain --untracked-files=no)" ]] || {
  echo "Modified image source checkout; refusing" >&2; exit 1;
}
[[ -f "$image_checkout/image/source_uboot_layout.py" ]] || {
  echo "Missing source-built U-Boot image assembly code" >&2; exit 1;
}
# Check both launchers and every new package/image entrypoint first.
for script in run-image.sh build-image-from-packages.sh package-develop-all.sh \
    package-platform-develop.sh build-platform-component.sh \
    publish-platform-develop.sh; do
  bash -n "$image_checkout/buildserver/$script"
done
[[ -f "$base/automation/auto-package.sh" && \
   ! -L "$base/automation/auto-package.sh" ]] || {
  echo "Missing tested OS/OSCR package automation" >&2; exit 1;
}
package_target="$vhost/package_develop.sh"
[[ -f "$package_target" && ! -L "$package_target" ]] || {
  echo "Missing or unsafe existing package develop launcher" >&2; exit 1;
}
if ! grep -Fqx '# Managed by Retrode3 buildserver/install-launchers.sh' "$package_target" &&
   ! grep -Fqx '# Managed by Retrode3 buildserver/install-image-launcher.sh' "$package_target"; then
  echo "Refusing to replace unmanaged package develop launcher" >&2; exit 1;
fi
target="$vhost/build_image_develop.sh"
[[ ! -L "$target" ]] || { echo "Refusing image launcher symlink" >&2; exit 1; }
if [[ -e "$target" ]] &&
    ! grep -Fqx '# Managed by Retrode3 buildserver/install-launchers.sh' "$target" &&
    ! grep -Fqx '# Managed by Retrode3 buildserver/install-image-launcher.sh' "$target"; then
  echo "Refusing to overwrite unmanaged image launcher" >&2; exit 1;
fi
# Preserve the original managed launcher for fast rollback if needed.
# No source checkout, Git remote or APT signing material is modified here.
mkdir -p "$base/cache/launcher-backups"
backup="$base/cache/launcher-backups/package_develop.before-platform.$(date -u +%Y%m%dT%H%M%SZ).sh"
cp -p -- "$package_target" "$backup"
temp_pkg="$(mktemp "$vhost/.retrode3-package-XXXXXXXX")"
temp_img="$(mktemp "$vhost/.retrode3-image-XXXXXXXX")"
trap 'rm -f -- "$temp_pkg" "$temp_img"' EXIT
cat > "$temp_pkg" <<EOF
#!/bin/sh
# Managed by Retrode3 buildserver/install-image-launcher.sh
set -eu
if [ "\${RETRODE3_BUILD_ONLY:-0}" = 1 ]; then
  exec bash "$image_checkout/buildserver/package-develop-all.sh" --build-only
fi
exec bash "$image_checkout/buildserver/package-develop-all.sh" --publish-testing
EOF
cat > "$temp_img" <<EOF
#!/usr/bin/env bash
# Managed by Retrode3 buildserver/install-image-launcher.sh
set -euo pipefail
exec bash "$image_checkout/buildserver/run-image.sh" develop
EOF
sh -n "$temp_pkg"
install -m 750 "$temp_pkg" "$package_target"
install -m 750 "$temp_img" "$target"
echo "Installed: $package_target (OS, OSCR, kernel, U-Boot -> signed testing)"
echo "Installed: $target (refresh packages, then assemble from signed APT)"
echo "Original package launcher backup: $backup"
echo "Unchanged: package_master.sh, build_image_master.sh, OS/OSCR automation"
