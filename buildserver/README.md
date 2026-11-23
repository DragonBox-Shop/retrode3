# Retrode3 MIPSEL package build server

Builds are driven by each `retrode3` Git branch's pinned
`packaging/native-source-lock.json`. No rootfs or SD images are created.
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
