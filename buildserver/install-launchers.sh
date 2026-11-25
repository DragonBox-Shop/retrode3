#!/usr/bin/env bash
# Install exactly two small launchers outside the web DocumentRoot.
set -euo pipefail
umask 027
vhost=/srv/www/vhosts/retrode.com
base="$vhost/buildserver"
[[ "$(id -un)" == retrode ]] || {
  echo "Install as retrode, not root" >&2; exit 1;
}
[[ -d "$base/src/retrode3-testing-pr/.git" ]] || {
  echo "Missing testing Git checkout" >&2; exit 1;
}
[[ -d "$base/src/retrode3-stable-pr/.git" ]] || {
  echo "Missing stable Git checkout" >&2; exit 1;
}
# Keep the release orchestrator independent of the moving develop HEAD.
# The developer intentionally allows broken scripts between release tags.
# Install/reinstall this verified copy explicitly; never auto-run a new HEAD.
mkdir -p "$base/cache" "$base/automation"
exec 9>"$base/cache/package-automation.lock"
flock -n 9 || { echo "Package build active; reinstall later" >&2; exit 1; }
source_dir="$base/src/retrode3-testing-pr/buildserver"
for name in auto-package.sh run-debs.sh publish-debs.sh package-failure-alert.sh; do
  bash -n "$source_dir/$name"
done
python3 "$source_dir/select-release-tag.py" --help >/dev/null
for name in auto-package.sh run-debs.sh publish-debs.sh package-failure-alert.sh select-release-tag.py; do
  target="$base/automation/$name"
  [[ ! -L "$target" ]] || { echo "Refusing automation symlink: $target" >&2; exit 1; }
  tmp="$(mktemp "$base/automation/.install.XXXXXXXX")"
  if [[ "$name" == *.sh ]]; then mode=750; else mode=640; fi
  install -m "$mode" "$source_dir/$name" "$tmp"
  mv -f "$tmp" "$target"
done
echo "Installed pinned-release APT automation in $base/automation"
for spec in "master:retrode3-stable-pr" "develop:retrode3-testing-pr"; do
  branch="${spec%%:*}"
  checkout="${spec#*:}"
  target="$vhost/package_$branch.sh"
  if [[ -L "$target" ]]; then
    echo "Refusing to replace symbolic link: $target" >&2
    exit 1
  fi
  if [[ -e "$target" ]] && ! grep -Fqx '# Managed by Retrode3 buildserver/install-launchers.sh' "$target"; then
    echo "Refusing to overwrite unmanaged file: $target" >&2
    exit 1
  fi
  tmp="$(mktemp "$vhost/.package-$branch.XXXXXXXX")"
  cat > "$tmp" <<EOF
#!/usr/bin/env bash
# Managed by Retrode3 buildserver/install-launchers.sh
set -euo pipefail
exec bash "$base/automation/auto-package.sh" "$branch"
EOF
  install -m 750 "$tmp" "$target"
  rm -f "$tmp"
  echo "Installed: $target"
done
echo "Run either $vhost/package_master.sh or $vhost/package_develop.sh"
# The image launchers run the matching package_* launcher first, then build
# the full SD image into private candidate artifacts. No SD writing.
for spec in "master:retrode3-stable-pr" "develop:retrode3-testing-pr"; do
  branch="${spec%%:*}"
  checkout="${spec#*:}"
  target="$vhost/build_image_$branch.sh"
  if [[ -L "$target" ]]; then
    echo "Refusing image launcher symlink: $target" >&2
    exit 1
  fi
  if [[ -e "$target" ]] &&
      ! grep -Fqx '# Managed by Retrode3 buildserver/install-launchers.sh' "$target"; then
    echo "Refusing unmanaged image launcher: $target" >&2
    exit 1
  fi
  tmp="$(mktemp "$vhost/.image-$branch.XXXXXXXX")"
  cat > "$tmp" <<EOF
#!/usr/bin/env bash
# Managed by Retrode3 buildserver/install-launchers.sh
set -euo pipefail
exec bash "$base/src/$checkout/buildserver/run-image.sh" "$branch"
EOF
  install -m 750 "$tmp" "$target"
  rm -f "$tmp"
  echo "Installed: $target"
done
echo "Images: $vhost/build_image_master.sh or $vhost/build_image_develop.sh"
