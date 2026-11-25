# Retrode3 Buildserver: Debian 12 MIPSEL, from Git

This is the intended **reproducible deployment contract**, not yet a
fully automated fresh-host installer. Current APT production supports
`retrode3` (OS/web/tools/udev) and `retrode3-oscr` (CLI/cores).
`retrode3-kernel` and `retrode3-uboot` still need MIPSEL .deb
recipes and integration into the package orchestrator.

## Two strictly separate launchers

- `package_develop.sh` / `package_master.sh`: fetch exact matching
  release tags, build any missing packages, verify and sign the APT suite
  `testing` / `stable`. Same tag pair already published = no build.
- `build_image_develop.sh` / `build_image_master.sh`: **only consume**
  approved published Debian packages and prebuilt bootloader artifacts,
  assemble an image. They must not compile a kernel or cartridge plugin.
  The historical image-feature code does not yet meet this contract.

Development work is pushed from the developer's Arch Linux PC. The
buildserver fetches Git but never commits or pushes.

## Source ownership and extensibility

| Git | Owns |
| --- | --- |
| `retrode3` | OS/web/tools/udev package definitions and publisher |
| `retrode3-oscr` | Core source and `packaging/cores/<id>.core` recipes |
| `retrode3-kernel` | Kernel, DTS, FULLCONFIG, future MIPS32EL deb recipes |
| `retrode3-uboot` | SPL/U-Boot, future board-specific deb recipe |

Plugin packages are discovered from validated OSCR metadata and staged
`.so`/`.core` pairs. `retrode3-cores` is the meta-package for all
discovered published plugins. Its `Depends` must be regenerated from
the actual package set, not from a fixed list of SNES/MD/NES/GBA names.
Install this meta-package on devices that should receive new plugins
automatically. All plugins remain disabled until explicitly enabled.

An entirely new **repository** needs an approved entry in the source
registry with its Git URL, release branch/tag rule and build recipe.
Discovery of arbitrary scripts from the Internet must never lead to
unreviewed code execution on the buildserver.

## Initial host requirements

Use Debian 12 with an unprivileged dedicated `retrode` builder:

```sh
apt-get update
apt-get install -y git python3 ca-certificates podman crun \
  gcc-mipsel-linux-gnu g++-mipsel-linux-gnu \
  binutils-mipsel-linux-gnu make dpkg-dev reprepro gnupg \
  pinentry-curses qemu-user-static binfmt-support debootstrap \
  xz-utils file rsync util-linux
```

Configure rootless Podman user namespaces, `crun`, cgroups and outbound
network; do not use a privileged build container. For target-rootfs
tests, register `qemu-mipsel` with binfmt_misc. Confirm the crosscompiler
target with `mipsel-linux-gnu-gcc -dumpmachine` = `mipsel-linux-gnu`.

Provision separate `develop` and `master` Git automation checkouts,
the `buildserver/automation` scripts using
`buildserver/install-launchers.sh --packages-only`, and the signed
reprepro repository described in `buildserver/README.md`.
Do not run the launcher installer in `--all` mode until the separate
image pipeline has been accepted. No host block devices are required
for the package build.

## GPG

The publisher can use a local 0700 `private/signing` directory and
0600 `apt-signing-passphrase` file (owned by the builder) to unlock its
GPG signing key automatically immediately before publication. This
file must never be committed to Git, included in a Podman source mount
or exposed through HTTPS. A key/account compromise permits malicious
signing. `buildserver/publish-debs.sh` verifies ownership and mode,
performs fail-closed GPG preflight, then exports the signed APT suite.

## Release gate and smoke tests

Run offline packaging tests, MIPS crosscompile, exact source/tag and
Sanni submodule verification, package metadata validation, and APT
dependency installation under a fresh Bookworm MIPSEL rootfs.
Check that newly added `packaging/cores/<id>.core` files produce
`retrode3-core-<id>` plus updated meta dependencies.

Only after those tests should a reviewed new release tag cause
publication. Kernel images and modules must have identical release and
`CONFIG_MODVERSIONS` ABI. Their on-device boot switch requires a
separate, power-loss-safe rollback procedure and physical testing.
