# Offene Aufgabe: neue Debian-Pakete für Retrode3 bauen

**Status 2026-11-22:** Paketrezepte vorhanden; Upgrade, Rollback,
Hardware-Abnahme und APT-Publikation stehen weiterhin aus. Der ältere
CI-Lauf hat fünf MIPS-Entwicklungspakete gebaut. Die dynamische
Core-Paketierung mit SMS-MD muss als neuer Sechser-Satz gebaut und
auf der Retrode3 geprüft werden.

## Implementierungsstand auf `develop` (2026-11-20)

Die ersten Paketrezepte sind jetzt unter `packaging/` vorhanden:
`build-debs.py` trennt den gepinnten OSCR-MIPS-Staging-Baum in
`retrode3-core-runtime`, automatisch erkannte `.so`/`.core`-Paare
(derzeit SNES, MD, NES und SMS-MD) und `retrode3-web-control` (Web v2).
SMS-MD verwendet `slot=md`; es wird im OSCR-Build über
`stage-sms-md-module` ausdrücklich gestaged, aber nicht automatisch
auf dem Gerät aktiviert. Maintainer-Skripte für SysV-Init,
privilegierte Core-Schaltung, ROM-Datenpersistenz und Bootrechte
sind enthalten. `retrode3.qcodeproj`, `retrode3-tools.qcodeproj`,
`make-all` und die vorhandenen udev-Regeln wurden migriert.

`debian-packaging.yml` prüft **nur Mock-MIPS-Paketdateien**.
`debian-mipsel-candidates.yml` baut die tatsächlichen MIPS-Binaries
mit gepinnter Toolchain und stellt Entwicklungs-.debs als
GitHub-Artefakt bereit, falls der Build erfolgreich ist. Diese
Artefakte werden weder automatisch installiert noch in APT
veröffentlicht. Der Status eines laufenden oder fehlgeschlagenen
CI-Builds ist im GitHub Actions-Lauf nachzusehen, nicht aus dem
Vorhandensein der Workflow-Datei abzuleiten.

**Weiter offen:** neuer MIPS-CI-Kandidatenlauf mit SMS, Paket-Upgrade und
Rollback auf der Retrode3, Laufzeitrechte nach Reboot, Tests aller drei
bekannten ROMs, signierte Entwicklungs-/Release-APT-Suites und
spätere SD-Image-Erzeugung. `master` ist unberührt.
Testbefehle und die Rückfall-Checkliste stehen in
[`packaging/README.md`](../packaging/README.md).

## Eingangsdokumente

Vor Änderungen lesen:
- Repository-Wurzel [`AGENTS.md`](../AGENTS.md)
- [`docs/build-and-release-layout.md`](build-and-release-layout.md)
- [`packaging/retrode3-core-layout.json`](../packaging/retrode3-core-layout.json)
- `retrode3-oscr/Makefile.migration`, `tests/test_release_stage.py`,
  `docs/branching-and-builds.md`
- Bestehende Nikolaus-Pakete: `retrode3.qcodeproj`,
  `retrode3-tools/retrode3-tools.qcodeproj`,
  `retrode3-tools/oscr.qcodeproj`, `make-all`.
- Neue Webquellen `retrode3-web-control/v2/` einschließlich
  `install-on-retrode.sh`, `service/retrode3-web-v2.init`.

**Repository-Verantwortung nicht ändern:**
`DragonBox-Shop/retrode3-oscr` entwickelt und baut den gemeinsamen
CLI-/Core-Quellcode; `DragonBox-Shop/retrode3` ist das vorhandene
Debian-OS-/Packaging-Repository. Keine zweite CLI-Codekopie im
OS-Repo anlegen. Nikolaus' QuantumSTEP/`.qcodeproj`-Infrastruktur
besteht bereits; ihre konkreten Fähigkeiten und Grenzen vor einer
Build-Migration prüfen und wiederverwenden, soweit technisch sinnvoll.

## Gewünschte installierbare Pakete

| Paket | Eigentümer der installierten Pfade |
| --- | --- |
| `retrode3-core-runtime` (mipsel) | `/usr/bin/retrode3-cli`, `/usr/sbin/retrode3-corectl`, `/etc/init.d/retrode3-core-runtime` |
| `retrode3-core-snes` (mipsel) | `/usr/lib/retrode3/cores-available/snes.so`, `snes.core` |
| `retrode3-core-md` (mipsel) | `/usr/lib/retrode3/cores-available/md.so`, `md.core` |
| `retrode3-core-nes` (mipsel) | `/usr/lib/retrode3/cores-available/nes.so`, `nes.core` |
| `retrode3-core-sms-md` (mipsel) | `/usr/lib/retrode3/cores-available/sms-md.so`, `sms-md.core` mit physischem Slot `md` |
| Web-v2-Paket (Name noch festzulegen) | geprüfte PHP/JS-Webassets, Python-3.4-Backend, SysV-Dienst und nötige Konfiguration; **keine** native CLI-/Core-Kopie |

Vorhandene Tools `retrode3-admin` und `retrode3-wlan` bleiben
erhalten, solange sie verwendet werden. Den alten ROM-Reader
`/usr/local/bin/oscr` und `retrode3-read/dump/info` **nicht**
automatisch neu installieren. Originale Source-Dateien dürfen im Git
bleiben. Die Web-v1-Paketierung wurde bereits absichtlich stillgelegt,
aber ein echtes Web-v2-Debian-Paket existiert noch nicht.

## Konkrete Implementierungsaufgaben

1. **Reproduzierbarer MIPS-Build:** den geprüften gemeinsamen
   `retrode3-oscr`-Commit inklusive Sanni-Submodulrevision pinnen;
   auf mipsel oder mit verifizierter Cross-Toolchain bauen. CLI und
   `.so` müssen auf dem realen Debian/MIPS-Gerät laufen. Verwende
   `make -f Makefile.migration test-all-shared-cores` und
   `test-release-stage` als Staging-Vertrag.
2. **Dynamisch erzeugte native Debian-Pakete:** echte Paketrezepte mit Version,
   Architekturen, Dependencies, `preinst/postinst/prerm/postrm`
   soweit erforderlich und prüfbarer `dpkg-deb`-Dateiliste
   implementieren. `.so` und passende `.core`-Metadaten müssen
   als Paar ausgeliefert werden; passende Core-ABI und Runtime-Version
   absichern. Installierte Programme gehören nur in ihre finalen
   `/usr`-Pfade, nicht `/usr/local`.
3. **Core-Aktivierung:** `/etc/retrode3/cores-enabled` als
   Konfiguration behandeln. Bereits bewusst aktivierte Cores beim
   Upgrade nicht abschalten, neue Module aber gemäß bestehender Policy
   nicht stillschweigend aktivieren. `retrode3-corectl` bleibt
   der rootprivilegierte Schalter, keine editierbaren DLL-Pfade aus
   dem Web akzeptieren.
4. **SysV-Init für Bus-Lock:** die vorhandene geprüfte Vorlage
   `retrode3-core-runtime/etc/init.d/retrode3-core-runtime`
   installieren und via `update-rc.d` registrieren. Kein systemd,
   kein `systemd-tmpfiles`. `/run/lock/retrode3` ist zur Bootzeit
   `root:root 0755`; `bus.lock` ist `root:www-data 0660`
   (bei www-data-Web-Backend). Nie eine gesperrte Lock-Inode im
   laufenden Betrieb löschen/ersetzen. Reboot auf Hardware prüfen.
5. **Web-v2-Paket:** Backend nach festem Pfad installieren und
   per bestehendem SysV-Dienst starten; Web-Frontend über den
   bestehenden HTTP-Server ausliefern. CLI fest
   `/usr/bin/retrode3-cli`, Core-Schalter
   `/usr/sbin/retrode3-corectl`. Webupdate/Installer darf
   keine alternativen Leser, Symlinks oder eigenen CLI-Binaries
   schaffen. Abhängigkeiten, Python 3.4, PHP, Aufrufrechte
   und Service-Reihenfolge prüfen.
6. **Hardware- und Rechteintegration:** Cartridge-Device-Rechte
   unter `/dev/slot-*` rebootfest über vorhandene udev/Init-Policy
   sicherstellen. Den Backendprozess nicht als root starten.
   Falls `corectl` aus Web aktiviert werden darf, nur eine streng
   begrenzte root-Rechtebrücke verwenden, niemals allgemeines sudo.
   Vor Paket-Release Probe/ROM-Dump und Auto-Detect für die drei
   bisherigen Cores erneut testen.
7. **Legacy-Pakete und Upgrade:** in `retrode3.qcodeproj` ist
   `DEBIAN_RECOMMENDS="oscr"` **noch vorhanden**; `make-all`
   hat weiterhin den alten OSCR-Buildpfad und listet `oscr`
   zur Installation. In `retrode3-tools.qcodeproj` sind
   `retrode3-read/dump/info` noch Bestandteil des Pakets.
   Diese Stellen nachvollziehbar migrieren, ohne
   `retrode3-admin/wlan`, USB-Gadgets oder andere Funktionen
   zu beschädigen. Paketdateien via `dpkg -S` abgleichen und
   notwendige `Breaks/Replaces/Conflicts` nur aus echten
   Paket-Dateikollisionen/Upgradepfaden ableiten. **Nie**
   `/usr/local/games` oder Benutzer-ROMs/Spielstände löschen,
   wenn `oscr` entfernt/aktualisiert wird.
8. **APT-Veröffentlichung:** Paketnamen, semantisch nachvollziehbare
   Versionsstrategie, verifizierbare Metadaten, Repository,
   Release-Signaturen und Updates für Entwicklungs- versus
   Kunden-Release festlegen. Ein Package-`apt upgrade` darf alte
   Reader oder alte Web-v1-Assets nicht zurückbringen.
9. **Tests/Rollback:** Paketdateilisten, Install/Upgrade/Remove,
   Dateirechte, Besitzer, enabled-Symlinks, Abhängigkeiten,
   Startreihenfolge, Neustart, rollbackfähige Konfiguration,
   Datenpersistenz, aktive Read-Jobs und API/ROM-Dump auf echter
   Retrode3 testen. Auf dem Gerät ist ein altes Git,
   Python 3.4 und SysV init im Einsatz; keine modernen
   `git switch`-/systemd-Voraussetzungen machen.
10. **Image-Build separat:** vorbereitetes Paketlayout
    mit reproduzierbarem RootFS/Kernel/DTB/Bootloader und
    fest gepinnten Versionen in die spätere flashbare SD-Karte
    integrieren. Diese Image-Pipeline ist **noch eine weitere
    offene Aufgabe**, nicht automatisch Bestandteil erfolgreicher
    `.deb`-Erstellung.

## Sicherheits- und Freigabegates

- **Niemals `make-all` unbesehen auf dem Entwicklungsgerät
  ausführen**: der Legacy-Ablauf baut alte Reader und kann via
  `dl-deb` automatisch Pakete installieren. Erst den Build- und
  Installationspfad kontrolliert modernisieren.
- Pakete erst offline erzeugen und `dpkg-deb --contents`,
  `dpkg-deb --info` und Abhängigkeiten prüfen; anschließend
  auf Test-Retrode mit klarer Rückrollmöglichkeit testen.
- Keine Schreiboperation an Modulen, SRAM, Flash oder Mappersignalen
  als bloßen Paket-Selbsttest einsetzen. Sichere bekannte
  ROMs für die Read-only-Abnahme verwenden.
- Arbeit auf **`retrode3/develop`**, dort die neuen Pakete und
  Update-Pfade testen. `master` bleibt bis zur ausdrücklichen
  Abnahme unverändert. Dann geprüfte Änderungen per Squash-PR
  nach `master` übernehmen und `develop` nachziehen.
- Festhalten, was wirklich fertig ist: `source/staging`,
  `built .deb`, `MIPS physical acceptance`,
  `APT published` und `SD-image verified` sind
  unterschiedliche Meilensteine.

## Bekannte physisch geprüfte Referenzen

`/usr/bin/retrode3-cli --list-cores` meldete auf Retrode3 2.9.5
alle drei installierten/aktivierten Cores als `ready`. Physisch
gelesene Stage-1-ROM-CRCs: SNES Terranigma `6FB8A4DF`,
MegaDrive Snake Rattle n Roll `543BED30`,
NES Excitebike (Europe) `F749E780` inklusive iNES-Header.
Keine Behauptung, dass Sonderchips/andere NES-Mapper oder SRAM
unterstützt werden.

**Ergebnis des anderen Chats:** prüfbare Debian-Pakete, dokumentierte
Upgrade-/Rückrolltests und ein sauberer PR nach `develop`;
keine automatische Freigabe nach `master`.
