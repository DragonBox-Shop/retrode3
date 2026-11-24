# Retrode3 MIPSEL package build server

The manual `package_master.sh` and `package_develop.sh` launchers follow
**both** the current OS branch and the matching current `retrode3-oscr`
branch. No fixed OSCR commit must be edited before a routine release.
Each run resolves and freezes one exact OSCR commit and the exact Sanni
gitlink recorded in that commit; all are written to the build manifest.
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
clean tracked files, fetches and fast-forwards its dedicated Git checkout,
checks whether the exact source commit is already published, then performs
the constrained rootless Podman crossbuild. After the build it verifies
the manifest, all SHA256 sums, source commit, expected package versions and
the pool/installed-suite versions, publishes explicitly with `reprepro`,
and saves an idempotency marker. Build/publish logs are kept in
`buildserver/artifacts/logs`.

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
`RETRODE3_FOLLOW_OSCR_BRANCH=1`. Every package revision includes the
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

## Avoiding empty package updates

The launchers compare the last successfully published build-manifest commit
with the freshly fetched Git HEAD, but **only after confirming** every package
listed in that manifest is still present in the APT suite. The conservative
`buildserver/release-changes.py` classifier then ignores changes solely in:

- Markdown documentation, `docs/`, `AGENTS.md`, GitHub workflows
- local unit tests, and publisher/launcher implementation files
- `tools/preflight-ci.sh` (a host-only test runner)

For these changes the scripts print **"Nothing to build or publish"**;
no Podman run, no new package version, and no APT publication occur.

The source lock, `packaging/` recipes and maintainer scripts, Web
source/assets, SysV runtime init files, `buildserver/build-debs.sh`,
`buildserver/run-debs.sh`, `buildserver/Containerfile` and all unknown
new files remain **build-affecting**. Multiple documentation-only commits
are compared against the original published commit: a later genuine source
change cannot be hidden by an intervening docs-only update.

The classifier also gates resume/publication of already built candidates.
If the cache manifest is missing, incomplete or the published suite does
not contain the expected versions, the normal safe build path is used.
To extend the non-package allowlist, add regression cases to
`packaging/tests/test_release_changes.py` and verify the file never ships
in a Debian package before doing so.

## Upstream firmware handling

Sanni's upstream is monitored separately by the source repository's
`sanni-upstream-review.yml` workflow. It proposes a **review-only**
submodule PR against `retrode3-oscr/develop`. No upstream changes are
automatically merged into the stable hardware-tested branch. Once a new
Sanni gitlink is reviewed and integrated into the relevant OSCR branch,
the next `package_*.sh` invocation automatically builds it.
