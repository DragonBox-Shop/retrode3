#!/usr/bin/env bash
# Shared policy for local unattended APT signing credentials.
# Never read, print, copy or change the contents of the secret here.
validate_apt_signing_secret() {
  local dir="$1" secret="$2" owner_uid dir_access file_access
  owner_uid="$(id -u)"
  if [[ -L "$dir" || ! -d "$dir" || -L "$secret" ||
        ! -f "$secret" || ! -s "$secret" || ! -r "$secret" ]]; then
    echo "ERROR: APT signing credentials missing, empty, unreadable or symlinked; no packages imported" >&2
    return 1
  fi
  dir_access="$(stat -c '%a:%u' -- "$dir")" || return 1
  file_access="$(stat -c '%a:%u:%h' -- "$secret")" || return 1
  # Setgid inherits the group, not additional access.
  if [[ ( "$dir_access" != "700:$owner_uid" &&
          "$dir_access" != "2700:$owner_uid" ) ||
        "$file_access" != "600:$owner_uid:1" ]]; then
    printf 'ERROR: APT signing credentials: directory mode:uid=%s, file mode:uid:links=%s; expected directory 0700 or 2700 and single-link 0600 file, both owned by uid %s; no packages imported\n' \
      "$dir_access" "$file_access" "$owner_uid" >&2
    return 1
  fi
}
