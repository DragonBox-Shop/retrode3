# Retrode3: verbindlicher Paket- und SD-Image-Bauplan

## Entwicklungszweige

Dieses OS-Repository hat die gleichen **gemeinsamen** Branches wie
[retrode3-oscr](https://github.com/DragonBox-Shop/retrode3-oscr):
`develop` für die laufende gemeinsame Entwicklung aller Plugins,
Web-/Systemintegration, Debian-Pakete und SD-Image-Pipeline;
`master` ausschließlich für geprüfte Freigaben.
**Kein dauerhafter Git-Branch je Konsole.** Die getrennte
Veröffentlichbarkeit bleibt auf **Debian-Paketebene**, nicht
durch duplizierte Entwicklungs-Branches.

Die vorhandenen QuantumSTEP/`.qcodeproj`-Pakete, die
`make-all`-Routine und das Paket `oscr` sind der **Legacy-Stand**
und bleiben zunächst erhalten. Der alte Build ist nicht die neue
Release-Pipeline: `make-all` kann Pakete automatisch auf ein Gerät
installieren und darf deswegen nicht unkontrolliert in der CI laufen.

## Verbindlicher Datei- und Paketvertrag

`retrode3-oscr` baut mit:

```sh
make -f Makefile.migration test-all-shared-cores
make -f Makefile.migration test-release-stage
```

Nach dem eigentlichen **MIPS/mipsel-Build** liegt ein Root-Dateibaum
unter `build/migration/stage/`. Die Maschinendefinition dieses
Vertrages liegt im OS-Repository unter
[`packaging/retrode3-core-layout.json`](../packaging/retrode3-core-layout.json).

| Debian-Paket (geplant) | Produzierte Dateien unter `/` |
| --- | --- |
| `retrode3-core-runtime` | `usr/bin/retrode3-cli`, `usr/sbin/retrode3-corectl` |
| `retrode3-core-snes` | `usr/lib/retrode3/cores-available/snes.so`, `snes.core` |
| `retrode3-core-md` | `usr/lib/retrode3/cores-available/md.so`, `md.core` |
| `retrode3-core-nes` | `usr/lib/retrode3/cores-available/nes.so`, `nes.core` |

Diese vier Pakete sollen sich unabhängig aktualisieren lassen,
aber gegen eine versionierte, kompatible Core-ABI gebaut werden.
Paket-Buildrezepte, Dependency-Metadaten, Signaturen und das
Debian-Repository müssen noch real implementiert und getestet werden.
**Die obige Tabelle ist die feste Zielstruktur, kein bereits
veröffentlichtes Paket.**

### Mutable Pfade und Sicherheit

- `/etc/retrode3/cores-enabled/` enthält nur kontrolliert gesetzte
  Symlinks auf **installierte, vertrauenswürdige** Cores. Installation
  eines neuen Core-Pakets soll es nicht automatisch aktivieren.
- `/run/lock/retrode3/` wird bei jedem Boot mit passenden
  Eigentümern/Rechten angelegt (init/tmpfiles, auf der tatsächlichen
  Debian-Version der Retrode3 prüfen). Das Verzeichnis darf **nicht**
  als dauerhaftes Paket-Payload vorausgesetzt werden.
- `/usr/sbin/retrode3-corectl` bleibt rootprivilegiert.
  Der Webdienst soll nur eng erlaubte `enable`- und
  `disable`-Operationen nach eigener Benutzerautorisierung
  auslösen; nie die ganze Weboberfläche als root starten.
- `/usr/local/bin/oscr`, die bestehenden Retrode-Skripte und die
  installierten alten Debian-Pakete bleiben bis zu einem gesondert
  geprüften Upgrade und Rückfallverfahren unberührt.
- ROM-Dumps gehören **nicht** in `/usr/lib`; der Webdienst wählt
  einen geprüften Schreibbereich und gibt keine frei manipulierbaren
  Ausgabepfade ungefiltert an das CLI weiter.

## Ziel-Pipeline und Freigabestufen

1. Eine fixierte Version von `retrode3-oscr` (Commit + Sanni-Revision)
   und des `retrode3-kernel` wird als Buildinput gewählt.
2. Auf der Zielarchitektur oder einem geprüften Cross-Toolchain-Build
   die gemeinsamen Host- und Core-Binaries erstellen.
3. Den verbindlichen Staging-Baum prüfen und in die vier
   separaten, versionierten **mipsel**-Debian-Pakete aufteilen.
4. Paketinstallation, Upgrade, Core-ABI, Berechtigungen, Neustart,
   Legacy-Rollback und tatsächliches Cartridge-Lesen testen.
5. Das vollständige flashbare SD-Karten-Image aus Debian-RootFS,
   Kernel/Device-Tree/Bootloader sowie **fixierten Paketversionen**
   erstellen und Artefakt-Checksummen/Build-Manifest veröffentlichen.
6. Image auf realer Hardware booten, USB-Netzwerk, Weboberfläche und
   mindestens die freigegebenen Console-Cores verifizieren.
7. Erst den getesteten `develop`-Stand nach `master` promoten
   und ein Release-Tag für Pakete und Images setzen.

Das Hardware-Board, Kernel-Treiber und Adapter-Pinouts werden
gegebenenfalls mit Versionen aus `retrode3-hardware` abgeglichen.
Der OSCR-Upstream wird nicht automatisch in ein Nutzerimage
übernommen: nur ein geprüfter Konverter-PR mit Mapper/HAL-Review,
CI und passendem Hardwaretest darf die gepinnte Revision erhöhen.

## Was noch fehlt

Die tatsächlichen `.qcodeproj`-/Debian-Buildrezepte für die neuen
Pakete, ein reproduzierbarer RootFS-/Kernel-/Image-Builder, signierte
Paketveröffentlichung, Upgrade/Rollback-Tests und die sichere
Webprivilegienbrücke sind **noch nicht fertig**. Das Verzeichnislayout
wurde jetzt absichtlich vor dem Implementieren fixiert, damit diese
Schritte nicht mehrfach umgebaut werden müssen.
