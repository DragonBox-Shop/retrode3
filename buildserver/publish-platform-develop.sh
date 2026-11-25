#!/usr/bin/env bash
# Explicitly publish TESTING kernel/U-Boot candidates. No Git pushes or live boot changes.
set -euo pipefail
umask 027
[[ "$#" == 1 && "$1" == /* ]] || { echo "Usage: $0 /absolute/platform-candidate-run" >&2; exit 2; }
[[ "$(id -un)" == retrode ]] || exit 1
[[ "${RETRODE3_ALLOW_EXPERIMENTAL_BOOT_PACKAGES:-0}" == 1 ]] || {
  echo "Explicit opt-in required for hardware-unaccepted testing boot packages" >&2
  exit 1
}
buildbase=/srv/www/vhosts/retrode.com/buildserver
repo="$buildbase/repository"
public=/srv/www/vhosts/retrode.com/domains/packages.retrode.com/httpdocs
src="$(cd "$(dirname "$0")/.." && pwd -P)"
run="$(realpath -- "$1")"
[[ "$run" == "$buildbase"/artifacts/platform/candidates/run.* ]] || {
  echo "Candidate must be inside buildserver artifacts" >&2; exit 1;
}
[[ ! -L "$1" && -f "$run/platform-package-set.json" ]] || exit 1
exec 9>"$buildbase/cache/package-automation.lock"
flock -n 9 || { echo "Another package operation is active" >&2; exit 1; }
python3 "$src/buildserver/verify-platform-publication.py" "$run" "$repo"
# Do not publish source bytes from a moving untagged feature branch after its
# selected exact commit has changed. These are explicitly test-only candidates.
python3 - "$run/platform-package-set.json" <<'PY'
import json, subprocess, sys
d=json.load(open(sys.argv[1]))
refs={
"kernel":("https://github.com/DragonBox-Shop/retrode3-kernel.git",
          "refs/heads/feature/retrode3-mipsel-deb-packaging-20261125"),
"uboot":("https://github.com/DragonBox-Shop/retrode3-uboot.git",
         "refs/heads/feature/retrode3-uboot-deb-packaging-20261125")}
for kind,(url,ref) in refs.items():
    row=subprocess.check_output(["git","ls-remote","--exit-code",url,ref],text=True).strip()
    if row.split()[0]!=d["sources"][kind]:
        sys.exit("Platform source branch moved since build: "+kind)
PY
export GNUPGHOME="$repo/gnupg"
[[ -d "$GNUPGHOME" && ! -L "$GNUPGHOME" ]] || exit 1
fpr="$(python3 - "$repo/conf/distributions" <<'PY'
from pathlib import Path
import re, sys
parts=re.split(r"\n\s*\n",Path(sys.argv[1]).read_text())
for part in parts:
    kv={}
    for line in part.splitlines():
        if ":" in line and not line[0].isspace():
            k,v=line.split(":",1);kv[k.strip()]=v.strip()
    if kv.get("Codename")=="testing":
        f=kv.get("SignWith","")
        if not re.fullmatch("[A-Fa-f0-9]{40}",f):
            sys.exit("Missing 40-character signing fingerprint")
        print(f);break
else:
    sys.exit("No testing APT suite")
PY
)"
secret_dir="$buildbase/private/signing"
secret="$secret_dir/apt-signing-passphrase"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
printf 'Retrode3 platform APT signature test\n' > "$tmp/probe.txt"
if [[ -e "$secret" || -L "$secret" ]]; then
  [[ ! -L "$secret_dir" && -d "$secret_dir" &&
     "$(stat -c '%a:%u' -- "$secret_dir")" == "700:$(id -u)" &&
     -f "$secret" && ! -L "$secret" && -s "$secret" &&
     "$(stat -c '%a:%u:%h' -- "$secret")" == "600:$(id -u):1" ]] || exit 1
  timeout 20s gpg --homedir "$GNUPGHOME" --batch --no-tty \
    --pinentry-mode loopback --passphrase-file "$secret" \
    --local-user "$fpr" --detach-sign \
    --output "$tmp/warm.sig" "$tmp/probe.txt"
fi
timeout 20s gpg --homedir "$GNUPGHOME" --batch --no-tty \
  --pinentry-mode error --local-user "$fpr" --detach-sign \
  --output "$tmp/check.sig" "$tmp/probe.txt" || {
    echo "GPG preflight failed: no package imported" >&2; exit 1;
  }
for deb in "$run"/*.deb; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  version="$(dpkg-deb -f "$deb" Version)"
  if reprepro --basedir "$repo" list testing |
      grep -Fqx "testing|main|mipsel: $pkg $version"; then
    echo "Indexed already: $pkg $version"; continue
  fi
  reprepro --basedir "$repo" --outdir "$public" \
    --export=never --keepunreferencedfiles includedeb testing "$deb"
done
reprepro --basedir "$repo" --outdir "$public" export testing
for deb in "$run"/*.deb; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  version="$(dpkg-deb -f "$deb" Version)"
  reprepro --basedir "$repo" list testing |
    grep -Fqx "testing|main|mipsel: $pkg $version" || exit 1
done
python3 - "$run/platform-package-set.json" "$buildbase/cache/last-published-platform-develop.json" <<'PY'
import json,os,pathlib,sys,tempfile
source,target=map(pathlib.Path,sys.argv[1:])
doc=json.loads(source.read_text())
doc["apt_published"]=True
with tempfile.NamedTemporaryFile("w",dir=str(target.parent),delete=False) as temp:
    json.dump(doc,temp,sort_keys=True,indent=2);temp.write("\n")
    name=temp.name
os.chmod(name,0o640)
os.replace(name,target)
PY
echo "Platform candidates published to signed APT testing (NOT hardware accepted)"
