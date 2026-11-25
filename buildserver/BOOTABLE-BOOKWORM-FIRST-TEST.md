# Retrode3: erstes Debian-12-MIPSEL-Testimage

**Nur Entwicklungszweig, nicht hardwarefreigegeben.** Weder `master`
noch die eingesetzte SD-Karte werden hiermit aktualisiert.

## Vier öffentliche Launcher, zwei Aufgaben

| Paketbau | SD-Image |
| --- | --- |
| `package_develop.sh` -> alle Git-Quellen -> signed APT `testing` | `build_image_develop.sh` -> Paketlauf -> signierte APT-Pakete -> SD-Image |
| `package_master.sh` -> freigegebenes `stable` | `build_image_master.sh` -> freigegebenes `stable`-Image |

Der Paketlauf lädt die neuesten **freigegebenen Release-Tags** aus
`retrode3` und `retrode3-oscr` samt Sanni-Submodul und pinnt
Kernel sowie U-Boot auf je einen exakten Commit ihres `develop`-Branches.
Im Kernel-Git liegen neben den Quellen auch
`arch/mips/configs/retrode3_full.config` und das eigene
`packaging/retrode3/build-debs.sh`-Rezept. U-Boot besitzt sein
entsprechendes Build-Rezept ebenfalls im eigenen `develop`-Git.

Nur geänderte Kernel-/U-Boot-Commits, Toolchains oder Rezepte lösen
einen neuen Plattform-Crossbuild aus. Ein erfolgreicher Build erzeugt
`retrode3-linux-image`, `retrode3-linux-modules` und
`retrode3-uboot-x1600`. Unveränderte Pakete werden aus dem geprüften
Cache wiederverwendet. Bereits signiert und unverändert veröffentlichte
Pakete werden nicht erneut signiert oder exportiert.

**Installierte** Kernel-/U-Boot-Pakete überschreiben keinen aktiven
Bootbereich oder rohe MMC-Sektoren. Sie legen lediglich versionierte
Kandidaten unter `/usr/lib/retrode3` ab. Die Offline-Image-Montage
wählt daraus die passenden Dateien aus.

## Einmalig auf Amaterasu einrichten

Als unprivilegierter Benutzer `retrode`, mit dem vorhandenen Worktree
`$BASE/src/retrode3-image-dev`, ohne einen neuen Git-Clone:

```sh
BASE=/srv/www/vhosts/retrode.com/buildserver
IMG="$BASE/src/retrode3-image-dev"
git -C "$IMG" fetch origin develop
# Nur bei sauberem Worktree und ohne laufende Builds:
git -C "$IMG" switch --detach origin/develop
bash "$IMG/buildserver/install-image-launcher.sh"
```

Der Installer ersetzt ausschließlich die beiden **verwalteten
Entwicklungs-Launcher** und sichert den vorherigen Paket-Launcher.
Die vorhandene OS-/OSCR-Automatik unter `$BASE/automation`, sämtliche
APT-Daten und beide `master`-Launcher bleiben unverändert.

## Reguläre Bedienung

Nur Debian-Pakete aktualisieren und ggf. erstellen:

```sh
/srv/www/vhosts/retrode.com/package_develop.sh
```

Oder das komplette Testimage bauen (Paketaktualisierung inklusive):

```sh
/srv/www/vhosts/retrode.com/build_image_develop.sh
```

**Keine zusätzlichen manuellen Kernel-/U-Boot-Buildbefehle.**
Der Image-Assembler selbst kompiliert nichts und verwendet nur
die exakt im signierten APT `testing` veröffentlichten Versionen.
Er erzeugt `$BASE/artifacts/images/develop/run.*/retrode3-develop.img.xz`
mit SHA256-Prüfsummen und Manifest. Es werden keine echten
Blockgeräte beschrieben.

Das reguläre Paketimage richtet USB-NCM, USB-ACM und ein schreibgeschütztes
HTML-Begrüßungslaufwerk unabhängig von SSH ein. Es übernimmt keine Entwickler-
SSH-Schlüssel. HID-Controller und die spätere optionale SSH-Konfiguration
sind noch nicht integriert. Der serielle Anschluss `ttyS2` bleibt verfügbar.
Der USB VID/PID und die Geräteidentität sind vor Endkundenfreigabe zu prüfen.

## master bleibt gesperrt, bis die Hardware getestet wurde

`retrode3-uboot/master` enthält noch keinen freigegebenen
Retrode3-X1600-Bootloader. Daher wird der neue Plattform-Build
**noch nicht** an `package_master.sh` oder
`build_image_master.sh` angeschlossen. Ihre bestehenden Funktionen
bleiben erhalten. Nach einem erfolgreichen Kaltstart mit einer
Ersatz-SD, geprüfter Modul-ABI und einem sicheren Boot-Update-/Rollback-
Konzept können wir dieselbe automatische Pipeline für `stable`
freigeben. Ein bloßer Build oder CI-Test ist keine Hardwarefreigabe.
