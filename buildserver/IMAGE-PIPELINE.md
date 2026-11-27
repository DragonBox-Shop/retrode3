# Retrode3 Debian-12-Image-Build aus signierten Debian-Paketen

Aktueller Stand: Der paketbasierte Debian-12-Entwicklungsstand hat auf
realer Hardware gebootet. Neue Image-Kandidaten (insbesondere USB-Gadget)
muessen erneut auf einer Ersatz-SD getestet werden; keine Freigabe fuer
`master` oder Endkunden.

Die vollstaendige Schritt-fuer-Schritt-Anleitung steht in
[BOOTABLE-BOOKWORM-FIRST-TEST.md](BOOTABLE-BOOKWORM-FIRST-TEST.md).

## Vier Launcher, zwei Aufgaben

- `package_develop.sh`: OS + OSCR aus den aktuellen exakt fixierten
  `develop`-Commits, ohne Tag-Pflicht; Kernel + U-Boot aus ihren
  jeweiligen `develop`-Git-Commits und den dort eingecheckten
  `packaging/retrode3/build-debs.sh`-Rezepten. Wenn Quellen,
  Paketrezepte und Compiler-Container unveraendert sind, werden
  vorhandene validierte `.deb`-Pakete wiederverwendet. Neue Pakete
  werden nach allen Checks durch die bestehende GPG-Signatur nach
  APT `testing` veroeffentlicht.
- `build_image_develop.sh`: Ruft **zuerst**
  `package_develop.sh` mit `RETRODE3_SOURCE_MODE=tag` auf (beide Release-Tags erforderlich), verifiziert die signierten Paket-Snapshots,
  erstellt Debian 12 MIPSEL mit SysVinit und installiert die exakten
  Paketversionen aus dem signierten APT `testing`. Dann erzeugt es eine
  FAT32/ext4-SD-Image-Datei mit dem in `.deb` gelieferten
  Ingenic-X1600-SPL/U-Boot, uImage, DTB und Modulen.
- `package_master.sh`: baut die freigegebenen Master-Commits ohne Tag.
  `build_image_master.sh` und Master-Plattformpakete bleiben gesperrt, bis der korrekte X1600-U-Boot-Stand auf einer realen
  Retrode3 hardwaregetestet und nach `master` freigegeben ist. Der
  bestehende U-Boot-`master` ist keine akzeptierte Retrode3-Konfiguration.

Der Image-Assembler selbst fuehrt weder Kernel- noch U-Boot-Compiler
aus. Das veraltete `build-image-container.sh`-Entrypoint wird
absichtlich sofort mit Fehler verlassen.

## Autoritative Quellen und Kernelkonfiguration

| Git | Quelle | Paket-Output |
| --- | --- | --- |
| `retrode3` | fixierte OS/Web/Tools-Commits; Image: Tag | OS- und Verwaltungs-Pakete |
| `retrode3-oscr` | fixierte OSCR/Sanni-Commits; Image: Tag | Runtime und dynamische Core-Pakete |
| `retrode3-kernel` | exakter `develop`-Commit | `retrode3-linux-image`, `retrode3-linux-modules` |
| `retrode3-uboot` | exakter `develop`-Commit | `retrode3-uboot-x1600` |

Die `FULLCONFIG` liegt ausschliesslich im Kernel-Git unter
`arch/mips/configs/retrode3_full.config` und wird mit Kernel,
Treiber und Device Tree versioniert. Es wird keine separate Konfiguration
auf Amaterasu gepflegt. Kernel- und U-Boot-Buildrezepte werden aus
den jeweiligen Repositories ausgefuehrt, nicht als Kopien im OS-Git.

## Isolierte Kernel-Experimente (kein APT-Release)

`buildserver/build-kernel-test.sh FULL_KERNEL_COMMIT_SHA` baut genau
einen ausgewählten Kernel-Git-Commit in einem separaten rootless Podman
Container. Als Benutzer `retrode` auf Amaterasu aus dem sauberen
vorhandenen Image-Worktree aufrufen:

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
IMG="$BASE/src/retrode3-image-dev"
git -C "$IMG" fetch origin develop
# Nur wenn kein Image-Build läuft und der Worktree sauber ist:
git -C "$IMG" switch --detach origin/develop
bash "$IMG/buildserver/build-kernel-test.sh" FULL_KERNEL_COMMIT_SHA
```

Der vollständige SHA (40 hexadezimale Zeichen) muss im Kernel-Git
erreichbar sein. Branch-Namen werden nicht als Input akzeptiert. Der
Container führt das Paket-Rezept dieses Commits aus. Der Test-Builder
verwendet die gemeinsame Paket-Build-Sperre, aber einen separaten
Container-Tag und private, nicht vom normalen Publisher verwendete
Ausgaben unter `$BASE/private/kernel-tests/run.*`. Es werden weder
U-Boot noch OS/OSCR neu gebaut, weder APT-Snapshots noch Signaturen
geändert und keine aktiven Bootdateien oder SD-Karten beschrieben.

Ausgaben: zwei zusammengehörige Kernel-.debs (Version beginnt mit
`0~retrode3test`), `kernel-bundle.tar.gz` mit Bootdateien und
passendem Modulbaum, `build.log`, `kernel-test-manifest.json`,
`SHA256SUMS` und, sofern das Kernel-Rezept sie bereitstellt,
`effective.config`. Der Testkernel ist ausdrücklich nicht
hardwarefreigegeben und darf nicht in APT importiert werden.
Vor Hardwaretests Prüfsummen und effektive Kconfig prüfen. Kernel,
DTB und Modulbaum nur gemeinsam auf eine separate Test-SD übernehmen;
bei gleicher Kernel-Release darf der alte Modulbaum nicht mit dem
neuen vermischt werden. Der reguläre Image-Assembler behält seinen
Vertrag, ausschließlich signierte APT-Pakete zu konsumieren.

## Reproduzierbarkeit und Sicherheit

Der Buildserver ist ein **Git-Consumer**, kein Git-Publisher.
Aenderungen, Commits und Pushes werden auf dem ArchLinux-
Entwicklungsrechner vorgenommen. Auf Amaterasu werden vorhandene
Git-Checkouts verwendet; fuer das experimentelle Image gibt es nur
den bestehenden verlinkten Worktree
`buildserver/src/retrode3-image-dev`. Kein vierter voller OS-Clone.
Der Worktree verwendet einen explizit ausgewählten detached Commit aus
`origin/develop`; keine Abhängigkeit von einem temporären Feature-Branch.


Die neue Paket-Cache-ID umfasst Git-Commit, Buildcontainer-Image-ID
und Paket-Orchestrierungsrezept; ein echter Inputwechsel fuehrt zu
einer neuen Paketversion. Kandidaten haben Manifeste, Checksums und
Debian-Metadatentests. Die Signatur-Passphrase verbleibt im privaten
0600-Serverfile und wird niemals in einen Container gemountet.

Installierbare Kernelpakete (live-v1) besitzen ihre Module unter
/lib/modules/<eindeutige Kernelrelease>. Das Image-Paket aktualisiert
bei einer normalen APT-Installation die FAT-Bootpartition per postinst
und verlangt einen Neustart. Es gibt keine dauerhafte Rollback-Kopie;
bei einem fehlgeschlagenen Boot kann die SD-Karte neu geflasht werden.
U-Boot und Bootargumente bleiben bei diesem Update unveraendert.
Der Offline-Assembler setzt RETRODE3_OFFLINE_IMAGE=1, um die Live-Mounts
zu unterbinden, und verwendet die identischen Paketdateien zum Bau
eines normalen Image-Files. Er schreibt niemals direkt nach
/dev/mmcblk*, /dev/sd* oder auf eine eingesteckte SD-Karte.

Das Image-Manifest nennt alle Source-Commits, Release-Tags,
Paketversionen, SHA256-Werte und den Bootloaderstatus. **Bootfaehig
ist eine Hypothese, bis der kalte Hardwarestart bewiesen ist.**

## Public development downloads

After full-image checksum verification, `build_image_develop.sh` exports
only the image, SHA256SUMS, README.txt and curated CHANGELOG.md to
`httpdocs/downloads/develop/YYYY.MM.DD-rcN/` on retrode.com. The changelog
is read with git show from the exact OS release commit, never moving HEAD.
Every new apt-YYYY.MM.DD-rcN release must contain its matching changelog
heading. The image is marked experimental, not hardware accepted.
Existing versions are immutable: identical complete downloads are reused;
different or incomplete files cause an error without overwrite. The private
build remains available if publication fails. No container sees the website.
There is no automatic stable publication.
