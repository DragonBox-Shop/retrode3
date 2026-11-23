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
exec bash "$base/src/$checkout/buildserver/auto-package.sh" "$branch"
EOF
  install -m 750 "$tmp" "$target"
  rm -f "$tmp"
  echo "Installed: $target"
done
echo "Run either $vhost/package_master.sh or $vhost/package_develop.sh"
