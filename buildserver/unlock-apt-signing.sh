#!/usr/bin/env bash
# Interactively unlock the existing Retrode3 APT signing key for its GPG agent.
# No APT mutation, no password in environment/argv/files, no package build.
set -euo pipefail
umask 077
suite="${1:-}"
case "$suite" in
  testing|stable) ;;
  *) echo "Usage: $0 testing|stable" >&2; exit 2 ;;
esac
[[ "$(id -un)" == retrode ]] || {
  echo "ERROR: run as retrode, never as root" >&2; exit 1;
}
[[ -t 0 && -t 1 ]] || {
  echo "ERROR: interactive SSH terminal required (ssh -t); no redirected stdin" >&2
  exit 1
}
for cmd in gpg gpgconf gpg-connect-agent python3 timeout tty; do
  command -v "$cmd" >/dev/null || {
    echo "ERROR: required command missing: $cmd" >&2; exit 1;
  }
done
[[ -x /usr/bin/pinentry-curses ]] || {
  echo "ERROR: pinentry-curses missing; install the Debian pinentry-curses package" >&2
  exit 1
}
base="${RETRODE3_APT_BASE:-/srv/www/vhosts/retrode.com/buildserver/repository}"
export GNUPGHOME="$base/gnupg"
[[ -d "$GNUPGHOME" && ! -L "$GNUPGHOME" ]] || {
  echo "ERROR: signing GnuPG home missing or symlinked: $GNUPGHOME" >&2
  exit 1
}
[[ -r "$base/conf/distributions" ]] || {
  echo "ERROR: missing reprepro distributions configuration" >&2; exit 1;
}
# Explicit pinentry configuration avoids GUI/system default surprises on SSH.
if ! grep -Eq '^[[:space:]]*pinentry-program[[:space:]]+/usr/bin/pinentry-curses([[:space:]]|$)' "$GNUPGHOME/gpg-agent.conf" 2>/dev/null; then
  echo "ERROR: configure pinentry-program /usr/bin/pinentry-curses in $GNUPGHOME/gpg-agent.conf" >&2
  exit 1
fi
[[ -n "${TERM:-}" && "$TERM" != dumb ]] || {
  echo "ERROR: terminal TERM is missing or dumb" >&2; exit 1;
}
export GPG_TTY="$(tty)"
fingerprint="$(python3 - "$base/conf/distributions" "$suite" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
for paragraph in re.split(r"\n\s*\n", text):
    fields = {}
    for line in paragraph.splitlines():
        if ":" in line and not line[0].isspace():
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    if fields.get("Codename") == sys.argv[2]:
        fingerprint = fields.get("SignWith", "")
        if not re.fullmatch(r"[a-fA-F0-9]{40}", fingerprint):
            sys.exit("ERROR: expected full 40-digit SignWith fingerprint")
        print(fingerprint)
        break
else:
    sys.exit("ERROR: APT suite not found in distributions")
PY
)"
# The GPG agent may be alive from an older SSH session. Retarget its pinentry
# terminal, without killing the agent or losing unrelated cached credentials.
gpgconf --homedir "$GNUPGHOME" --launch gpg-agent
gpg-connect-agent --homedir "$GNUPGHOME" updatestartuptty /bye >/dev/null
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
printf 'Retrode3 %s signing authorization test\n' "$suite" > "$work/test.txt"
echo "Unlocking existing APT signer for $suite via terminal pinentry..."
gpg --homedir "$GNUPGHOME" --local-user "$fingerprint" \
    --detach-sign --output "$work/interactive.sig" "$work/test.txt"
# Match the publisher's intentionally noninteractive fail-closed preflight.
if ! timeout 20s gpg --homedir "$GNUPGHOME" \
    --batch --no-tty --pinentry-mode error \
    --local-user "$fingerprint" --detach-sign \
    --output "$work/unattended.sig" "$work/test.txt"; then
  echo "ERROR: interactive signing worked but unattended GPG cache is unavailable" >&2
  exit 1
fi
echo "APT signing key unlocked in the GPG agent for $suite."
echo "Run /srv/www/vhosts/retrode.com/package_develop.sh (testing) or package_master.sh (stable) promptly."
echo "No packages were published by this unlocking helper."
