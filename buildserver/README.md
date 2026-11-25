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

Once, as the `retrode` user, install the two launchers:

```sh
bash /srv/www/vhosts/retrode.com/buildserver/src/retrode3-testing-pr/buildserver/install-launchers.sh
```

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

The first invocation follows `develop` and `retrode3-oscr/develop`,
compiles only if package-affecting changes exist, and retains the exact
candidate and manifest. A valid existing candidate is reused even in
build-only mode. The second invocation uses the ordinary
`candidate-resume` path: it verifies exact source commits and checksums,
then imports the candidate and makes one signed `reprepro export`.
If either selected release tag changes in between, the new tag pair must
be built; an old candidate is never silently published as a different tag.
New untagged development commits alone do not invalidate the candidate.
The GPG passphrase must **not** be stored in Git, shell scripts, or public
images. Build-only does not modify APT or the last-published marker.

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
ordering. There are not yet any release tags in the OS/OSCR repositories;
the first automated tagged build will fail safely until both are tagged.

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


## Full Debian SD image candidates (one command per branch)

**Transition note:** The existing `build_image_develop.sh` still checks the
moving OS branch HEAD against the published package snapshot. The APT
build is now strictly tag-based, so an image build with newer untagged
package-affecting OS changes can fail until the image orchestrator is
updated to consume the same selected release snapshot. Do not bypass
this check or silently rebuild untagged packages.



The image builder **reuses** the existing package launchers and their
published manifests. It then builds Linux + DTB + modules from
DragonBox-Shop/retrode3-kernel, bootstraps Bookworm MIPSEL, installs the
exact published Retrode3 packages from signed packages.retrode.com, and
assembles a FAT32/ext4 .img.xz regular file.

Install launchers once as the existing unprivileged retrode user:

    bash /srv/www/vhosts/retrode.com/buildserver/src/retrode3-testing-pr/buildserver/install-launchers.sh

Then invoke either:

    /srv/www/vhosts/retrode.com/build_image_develop.sh
    /srv/www/vhosts/retrode.com/build_image_master.sh

Each command calls the matching package_develop.sh/package_master.sh first.
The existing automation updates the selected checkout, builds/publishes
missing .debs and records the package manifest. The image build checks
its relationship to the OS tree and pins the current kernel branch head.
It never writes directly to an SD or changes the other Git branch.

### Private one-time inputs, separate per channel

Provision these **non-DocumentRoot** directories:

    /srv/www/vhosts/retrode.com/buildserver/private/image/develop/
    /srv/www/vhosts/retrode.com/buildserver/private/image/master/

Each directory must contain:

- FULLCONFIG: approved, matching Retrode3 kernel config. The channels
  can require different configs if master/develop kernel sources differ.
- toolchain/bin/mipsel-linux-gcc: the full pinned Bootlin MIPS32EL GCC 8.2
  toolchain including its libraries, mounted read-only, not just gcc.
- sd-preboot-1MiB.bin: the original donor SD bootloader dump. PRIVATE!
  This is an explicit temporary fallback until board U-Boot source
  and raw-sector placement have been verified.
- preboot.sha256: lowercase 64-character hash of the donor, no filename.
- retrode3-archive.gpg: public-only GPG export of the APT archive signing key.
- apt-fingerprint: full 40-character primary signing-key fingerprint.
- Optional ssh.pub: a PUBLIC developer SSH key for temporary USB NCM access.

For example:

    cd /srv/www/vhosts/retrode.com/buildserver/private/image/develop
    sha256sum sd-preboot-1MiB.bin | cut -d' ' -f1 > preboot.sha256

The APT administrator can export the PUBLIC archive key using:

    gpg --homedir /srv/www/vhosts/retrode.com/buildserver/repository/gnupg --export YOUR_SIGNING_FINGERPRINT > retrode3-archive.gpg

Copy the public key and its independently verified fingerprint to
each channel. **Never** mount the signing secret or full repo keyring.

### Host prerequisites and outputs

Rootless Podman with crun/slirp4netns, QEMU MIPSEL binfmt registered
on the host by the administrator, sufficient disk space and HTTPS to
GitHub, Debian and the signed Retrode3 APT suites are required.
The image container has the build programs; the host must provide
binfmt and the pinned compiler. The container never mounts /dev,
Maildir, public website or the APT secret keyring; it does not
request --privileged. The rootless chroot/binfmt interactions still
require a real Amaterasu integration test.

Every run generates a new output directory, for example:

    buildserver/artifacts/images/develop/run.XXXXXXXX/retrode3-develop.img.xz
    buildserver/artifacts/images/master/run.XXXXXXXX/retrode3-master.img.xz

It also contains full-image-manifest.json, FULL-IMAGE-SHA256SUMS, the
published package snapshot and kernel/rootfs bundles.
The three native cores snes/md/nes are enabled explicitly with the approved
offline retrode3-corectl during image construction; optional adapter cores
such as sms-md remain installed but disabled. While donor U-Boot
is used, the manifests mark bootloader_source_built=false,
hardware_accepted=false and customer_releasable=false.

**Expected blockers:** The Web .deb currently depends on letux-httpd,
retrode3-tools, retrode3-udev-rules and PHP/Python. Their full Debian 12
dependency chain must be present in trusted signed APT sources; if not,
the image build fails visibly. Similarly, stable cannot be claimed
successful if the master kernel source/config is not yet approved.
Kernel/USB/regression hardware tests and customer release authorization
remain separate gates.
