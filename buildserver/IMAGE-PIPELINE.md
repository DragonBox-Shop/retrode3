# Retrode3 Debian-12-Image-Build aus signierten Debian-Paketen

Aktueller Stand: Der paketbasierte Debian-12-Entwicklungsstand hat auf
realer Hardware gebootet. Neue Image-Kandidaten (insbesondere USB-Gadget)
muessen erneut auf einer Ersatz-SD getestet werden; keine Freigabe fuer
`master` oder Endkunden.

Die vollstaendige Schritt-fuer-Schritt-Anleitung steht in
[BOOTABLE-BOOKWORM-FIRST-TEST.md](BOOTABLE-BOOKWORM-FIRST-TEST.md).

## Vier Launcher, zwei Aufgaben

- `package_develop.sh`: OS + OSCR aus den letzten branch-erreichbaren,
  unveraenderlichen `develop`-Release-Tags; Kernel + U-Boot aus ihren
  jeweiligen `develop`-Git-Commits und den dort eingecheckten
  `packaging/retrode3/build-debs.sh`-Rezepten. Wenn Quellen,
  Paketrezepte und Compiler-Container unveraendert sind, werden
  vorhandene validierte `.deb`-Pakete wiederverwendet. Neue Pakete
  werden nach allen Checks durch die bestehende GPG-Signatur nach
  APT `testing` veroeffentlicht.
- `build_image_develop.sh`: Ruft **zuerst**
  `package_develop.sh` auf, verifiziert die signierten Paket-Snapshots,
  erstellt Debian 12 MIPSEL mit SysVinit und installiert die exakten
  Paketversionen aus dem signierten APT `testing`. Dann erzeugt es eine
  FAT32/ext4-SD-Image-Datei mit dem in `.deb` gelieferten
  Ingenic-X1600-SPL/U-Boot, uImage, DTB und Modulen.
- `package_master.sh` / `build_image_master.sh`: Bleiben bisher
  unangetastet, bis der korrekte X1600-U-Boot-Stand auf einer realen
  Retrode3 hardwaregetestet und nach `master` freigegeben ist. Der
  bestehende U-Boot-`master` ist keine akzeptierte Retrode3-Konfiguration.

Der Image-Assembler selbst fuehrt weder Kernel- noch U-Boot-Compiler
aus. Das veraltete `build-image-container.sh`-Entrypoint wird
absichtlich sofort mit Fehler verlassen.

## Autoritative Quellen und Kernelkonfiguration

| Git | Quelle | Paket-Output |
| --- | --- | --- |
| `retrode3` | getaggte OS/Web/Tools-Quellen | OS- und Verwaltungs-Pakete |
| `retrode3-oscr` | getaggte OSCR/Sanni-Quellen | Runtime und dynamische Core-Pakete |
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

Ein frisch aus dem Paket installiertes Kernel-/Bootloader-Kandidat
ueberschreibt **weder** den aktiven `/boot`-Inhalt noch rohe
MMC-Sektoren. Das Ausrollen auf laufende Geraete erfordert einen
separat getesteten, stromausfallsicheren Aktivierungs- und
Rollback-Prozess. Der Offline-Assembler darf dagegen ein Image als
normale Datei bauen. Er schreibt niemals direkt nach `/dev/mmcblk*`,
`/dev/sd*` oder auf irgendeine eingesteckte SD-Karte.

Das Image-Manifest nennt alle Source-Commits, Release-Tags,
Paketversionen, SHA256-Werte und den Bootloaderstatus. **Bootfaehig
ist eine Hypothese, bis der kalte Hardwarestart bewiesen ist.**
