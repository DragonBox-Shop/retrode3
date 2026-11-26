# Retrode3 MIPSEL package build server

The `package_master.sh` and `package_develop.sh` launchers update
their own automation checkout but build **only the newest reachable Git tag**
of the matching OS branch and the matching `retrode3-oscr` branch.
`develop` can be broken between tags; untagged HEAD changes are never
packaged. A tag is a completed checkpoint, not yet a hardware approval.
The selected OS/OSCR tag names, their exact commits and the Sanni gitlink
are recorded in the build manifest. Missing tags mean a clear failure,
**never a fallback to branch HEAD**.
The tracked `packaging/native-source-lock.json` remains a deliberate
fallback for offline, pinned/manual candidate builds and tests, **not**
the source selector for automated APT releases.
No rootfs or SD images are created.
The source stays in Git; this directory is usable on any Linux host with
Podman, crun and rootless user namespaces.

| OS Git ref | lock release_channel | APT suite |
| --- | --- | --- |
| `develop` | `testing` | `testing` |
| `master` | `stable` | `stable` |

Use separate checkouts/worktrees to avoid publishing one branch's binary
under the other's label. `run-debs.sh` does not publish or install
anything. It stages only the cartridge cores supported by its pinned OSCR
source and produces `.deb` files, `build-manifest.json` and
`SHA256SUMS` under a unique run directory.

On amaterasu, as the existing unprivileged `retrode` user:

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
export RETRODE3_OUTPUT_BASE="$BASE/artifacts/candidates"
export RETRODE3_BUILD_CPUS=2 RETRODE3_BUILD_MEMORY=2g RETRODE3_BUILD_PIDS=256
cd "$BASE/src/retrode3"
bash buildserver/run-debs.sh
```

The Podman invocation uses `crun`, systemd cgroups and `slirp4netns`,
as verified on the host. The container build step itself is not resource
limited, only the subsequent cross-build run.

`stable` versions must not contain `~dev`. `testing` versions must
contain `~dev`; use a version whose Debian ordering is suitable for
upgrades from the current stable release.

Publishing is a separate explicit operation, for example:

```sh
bash buildserver/publish-debs.sh develop /absolute/path/to/run.XXXXXXXX
bash buildserver/publish-debs.sh master /absolute/path/to/run.YYYYYYYY
```

It verifies package hashes, versions and channels before the first import.
This is not an atomic multi-package release: only publish a complete,
previously tested candidate set and preserve rollback copies. It neither
installs on device nor changes Git branches.

The public repository is owned by the existing `retrode` account and
is served from `packages.retrode.com`, independently from the retrode.com
website. Never mount the website, Maildir, SSL keys or entire vhost into
the container. This isolation does **not** prevent same-UID host accesses
outside the container; a separate builder UID would be stronger.

The target device libc/GLIBCXX versions still need a hardware/sysroot
compatibility check before deploying any of these packages.

## One-command build and publish on amaterasu

Once, as the `retrode` user, install **only** the APT launchers, keeping any ongoing SD-image launcher untouched:

```sh
bash /srv/www/vhosts/retrode.com/buildserver/src/retrode3-testing-pr/buildserver/install-launchers.sh --packages-only
```

The default `--all` mode additionally installs both image launchers, but should only be used once the image pipeline is synchronized with tag-based package selection. For the current image-building work, use `--packages-only`.

This creates two executable files **outside** the public DocumentRoot:

- `/srv/www/vhosts/retrode.com/package_develop.sh` (Git `develop` -> APT `testing`)
- `/srv/www/vhosts/retrode.com/package_master.sh` (Git `master` -> APT `stable`)

Each invocation takes a shared nonblocking `flock`, verifies the branch and
clean tracked files, fetches and fast-forwards its dedicated automation
checkout, selects the latest **existing, branch-reachable** source tags,
and builds from a temporary self-contained OS-tag checkout. Package compilation
uses the exact tagged OSCR commit, not a moving branch HEAD. It checks
whether that specific tag pair is already published, then performs
the constrained rootless Podman crossbuild. After the build it verifies
the manifest, all SHA256 sums, source commit, expected package versions and
the pool/installed-suite versions, publishes explicitly with `reprepro`,
and saves an idempotency marker. Build/publish logs are kept in
`buildserver/artifacts/logs`.

### Build first, sign later (recommended for long MIPS builds)

The normal `package_develop.sh` builds and publishes in one invocation. For
long crossbuilds, the GPG-agent passphrase cache can expire before publication.
To avoid unlocking the signing key before building, split the two phases:

```sh
# As retrode on Amaterasu. No APT import or signing occurs.
RETRODE3_BUILD_ONLY=1 /srv/www/vhosts/retrode.com/package_develop.sh

# Later, unlock the APT signing key interactively in the same user's agent.
# Once unlocked, publish the matching completed candidate with:
unset RETRODE3_BUILD_ONLY
/srv/www/vhosts/retrode.com/package_develop.sh
```

The first invocation selects the latest tagged snapshots reachable from
`develop` and `retrode3-oscr/develop`, compiles only if that exact pair
has no already-built candidate, and retains the manifest. A valid existing candidate is reused even in
build-only mode. The second invocation uses the ordinary
`candidate-resume` path: it verifies exact source commits and checksums,
then imports the candidate and makes one signed `reprepro export`.
If either selected release tag changes in between, the new tag pair must
be built; an old candidate is never silently published as a different tag.
New untagged development commits alone do not invalidate the candidate.
The GPG passphrase must **not** be stored in Git, shell scripts, or public
images. Build-only does not modify APT or the last-published marker.

### Optional unattended signing with a private local passphrase

For a single-admin buildserver, it is possible to have the publisher unlock
the APT signing key automatically **only at publication time**, using a local
plaintext secret file outside Git and outside the HTTP DocumentRoot.
This makes unattended publishing possible, but **any attacker who gains
the `retrode` user's privileges can use the signing key**. The key encryption
does not defend against same-user compromise; harden the host, services and
backups accordingly. For stronger isolation use a dedicated signing service
with a separate Unix identity and allowlisted release requests.

Opt in as `retrode` on Amaterasu (do not type the secret as a shell command
argument or put it in Git):

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
umask 077
install -d -m 700 "$BASE/private/signing"
read -rs -p "APT GPG signing passphrase: " apt_passphrase
printf '\n'
printf '%s\n' "$apt_passphrase" > "$BASE/private/signing/apt-signing-passphrase"
unset apt_passphrase
chmod 600 "$BASE/private/signing/apt-signing-passphrase"
```

The directory must be owned by `retrode` with mode `0700` or `2700`
(setgid inheritance, no group/other access), and the
non-symlink, single-link secret file owned by `retrode` with mode `0600`.
The file is a **local administrator-managed secret**, not a tracked
project file or CI artifact. Exclude it from shared/web backups,
synchronization, shell debug traces, and the Podman source mounts.

Once configured, the normal `package_develop.sh` (or explicitly approved
`package_master.sh`) reuses/builds the tag-pinned candidate, validates it,
warms the GPG agent using `--pinentry-mode loopback --passphrase-file`, then
verifies the existing **noninteractive signing preflight** before importing
any .debs. If the file is missing, the previous manual SSH-unlock method
continues to work; if permissions or the passphrase are wrong, publication
fails *before the first package import*. No passphrase appears in process
arguments, the environment, log output or version manifests.

The secret remains on disk between boots so automated package publication
is a deliberate security tradeoff. To return to interactive operation, move
the secret **out of the signing directory** to secured offline storage and
use `unlock-apt-signing.sh` as described below. Both package publishers use the same credential validation helper. After
reviewing and testing an automation-only fix, install it using
`bash buildserver/install-launchers.sh --automation-only` from the updated
testing checkout. This preserves all four deployed launchers and does not
require moving or creating package source tags. Re-run the normal launcher
to resume an exact existing candidate. No changes to the tag policy,
packaging, GPG keys or public APT endpoints are required.

### Unlocking the APT signing key over SSH

The publisher deliberately calls GPG with `--batch --no-tty --pinentry-mode error` before importing anything. It must **not** prompt
during publication. Instead, unlock the existing key interactively in the
same `retrode` account's GPG agent shortly **after** the MIPS build, and
then resume the previously built candidate.

One-time setup on Amaterasu:

1. Install `pinentry-curses` on the **build server** (not in a Retrode3
   image), e.g. as root: `apt-get install pinentry-curses`.
2. As `retrode`, edit
   `/srv/www/vhosts/retrode.com/buildserver/repository/gnupg/gpg-agent.conf`.
   Configure the line `pinentry-program /usr/bin/pinentry-curses` and
   ensure there is no conflicting later `pinentry-program` directive.
   Protect the file with mode 0600. Never store the passphrase in it.
3. Install the verified APT helper and package launchers from the current
   development checkout, without touching image launchers:

```sh
bash /srv/www/vhosts/retrode.com/buildserver/src/retrode3-testing-pr/buildserver/install-launchers.sh --packages-only
```

For each **manual** publication, connect with an interactive SSH terminal
(`ssh -t` if required) as `retrode` and run:

```sh
/srv/www/vhosts/retrode.com/buildserver/automation/unlock-apt-signing.sh testing
unset RETRODE3_BUILD_ONLY
/srv/www/vhosts/retrode.com/package_develop.sh
```

For an explicitly approved stable release, use the helper with `stable`
and then `package_master.sh` instead. The helper reads the configured
40-digit `SignWith` fingerprint from the correct `reprepro` suite,
selects its existing secret key, binds `GPG_TTY` and `updatestartuptty`
to the SSH terminal, reloads `gpg-agent`'s pinentry configuration, and
performs one interactive signature to cache the authorization. It then
performs the **same no-prompt signing preflight as the publisher**.
The helper changes no APT index, package, Git ref or release manifest.

The cache is temporary (typically 10 minutes by default). If it has
expired, rerun the helper; do not switch the unattended publisher to
`--pinentry-mode loopback`, store plaintext passphrases, or disable its
early signing preflight. If terminal pinentry fails, inspect the
`gpg-agent.conf`, installed `pinentry-curses`, `TERM`, account and
`GNUPGHOME`. The publisher will continue to refuse publication safely.

### Package failure reporting

If a `package_develop.sh` or `package_master.sh` run exits nonzero,
the wrapper prints a prominent `FAILED` message with its stage, exit
code and log path. It also saves a private failure marker under
`buildserver/artifacts/logs/last-failed-develop.txt` or
`last-failed-master.txt`. The original nonzero exit status is preserved.
Failure markers describe the **last failure**, not the current health of
the suite: verify the signed published index and the
`cache/last-published-<branch>.json` manifest separately.

To receive an optional email **via an already configured local
`sendmail` transport**, export
`RETRODE3_BUILD_ALERT_EMAIL=recipient@example.org` before invoking
`package_*.sh`. No address is hardcoded and no key material or full
build log is included in the alert. The script reports unavailable or
failing mail delivery on stderr; the failure marker is still written.

The publisher stages all verified packages using
`reprepro --export=never --keepunreferencedfiles includedeb`, then
performs exactly one `reprepro export <suite>` to sign and publish the
complete index. Old pool files referenced by the currently public index
are preserved during staging. On a retry, previously staged versions
are skipped but the final export is still run. This minimizes the
partial-publication window; index export itself is not atomic.

The publisher now runs an unattended signing preflight with the suite's
configured `SignWith` fingerprint **before importing the first package**.
If the GPG agent has no cached authorization, it fails quickly instead of
starting a partial import. This check reduces the risk of a partial
publication but cannot make multiple `reprepro includedeb` calls atomic.

**Important:** A signing error such as `gpgme: Pinentry Timeout` during
`reprepro includedeb` can leave some newly imported packages in the
repository database while the signed index still represents an older
state. Do not interpret a nonzero exit or a single newer package in
`reprepro list` as a successful release. Repair signing and reconcile
the complete candidate/suite before retrying; neither the failure
reporter nor the automatic wrapper silently rolls back or republishes.

Automatic runs set `RETRODE3_AUTO_VERSION=1` and
`RETRODE3_FOLLOW_OSCR_BRANCH=1`, but the latter now refers to the
branch used to **validate the selected OSCR tag's ancestry**, not to a
floating HEAD source. Every package revision includes the
UTC build timestamp (with nanoseconds) and the exact OS plus OSCR
commit prefixes. This avoids reusing a version when only OSCR changes.
The build manifest keeps the full Git revision IDs, exact Sanni submodule
commit and immutable package hashes. A retry reuses already-built
candidate packages instead of renumbering them; the publisher refuses
downgrades and any conflicting binary at an existing version.
The `release-changes.py` classifier also recognizes docs-only OSCR
changes, using a cached bare Git history under
`buildserver/cache/oscr-git-history.git`. Any source, generator, core
metadata, makefile or Sanni gitlink change triggers a new build.

This is a **manual trigger** (no cron or hook) with fully automatic steps
after invocation. It does not update firmware, kernel modules, rootfs images
or customer devices. The build is deliberately cross-compiled against
Debian Bookworm, not a verified legacy-device sysroot.

## Skipping repeated tagged releases

The wrapper uses `buildserver/select-release-tag.py` to select the
newest tag by creation date (annotated tagger date; lightweight tags
inherit commit date). Tags must point to commits contained in the
channel's `develop` or `master` history. Archive/upstream tracking
tags are ignored. Use annotated, immutable release tags for predictable
ordering. The first automated tagged build fails safely unless both repositories have suitable release tags.

If the exact OS tag, OSCR tag and both source commits are already in the
last published manifest *and* all expected package versions still exist
in the target APT suite, nothing is built or published. An untagged
`develop` change alone never triggers new Debian packages. A genuinely
new tag triggers a new candidate even if only documentation changed;
the tag represents a new checkpoint.

`RETRODE3_BUILD_ONLY=1` builds without publishing. A later normal
invocation reuses a candidate only when both tags and commits match.
Publisher preflight independently verifies that the OS checkout is the
selected exact tagged commit, that the tag belongs to the selected
branch, and that both tag names match the package manifest.

The selected tags must be handled as immutable Git references; never
force-move or reuse a release tag. For a changed build, create a
new tag with a different name.

## Upstream firmware handling

Sanni's upstream is monitored separately by the source repository's
`sanni-upstream-review.yml` workflow. It proposes a **review-only**
submodule PR against `retrode3-oscr/develop`. No upstream changes are
automatically merged into the stable hardware-tested branch. Once a new
Sanni gitlink is reviewed and integrated into the relevant OSCR branch,
the next `package_*.sh` invocation automatically builds it.


## Full Debian SD image candidates

The supported develop pipeline builds and publishes OS/OSCR packages from
the selected tags and caches the exact kernel/U-Boot packages. The image
builder installs those signed APT package snapshots; it does not compile
kernel or bootloader inside the image container. See
[IMAGE-PIPELINE.md](IMAGE-PIPELINE.md) and
[the launcher and migration instructions](BOOTABLE-BOOKWORM-FIRST-TEST.md).

The existing dedicated image worktree can be switched to a detached
origin/develop commit once the merge is accepted. Refresh it only between
builds. No new full clone is needed. Do not reinstall or overwrite the
master launchers; stable platform activation remains a separate gate.

The package image does not accept developer SSH keys. USB networking,
serial and the read-only welcome disk are independent of SSH.

## Reproducible Bookworm preflight

Run `bash buildserver/run-preflight.sh` from the selected OS checkout before
creating a release tag. The dedicated native-architecture Debian 12 container
runs the complete existing `tools/preflight-ci.sh` suite, including bcrypt
and SysV packaging tests. The source is mounted read-only, Python bytecode
is written to container temporary storage and the test run has no network.
Host Python 3.13 no longer includes the target's crypt/spwd modules; do not
skip authentication tests or change the target authentication scheme to
accommodate host Python. This is separate from MIPS builds and hardware tests.
