# Retrode3 OS: verbindliche Entwicklungs- und Release-Regeln

Dieses Repository enthaelt Debian-OS, Web Control v2, SysV-Dienste,
Paketrezepte, APT-Veröffentlichung und SD-Image-Bau. Native CLI-/Core-Quellen
liegen in [retrode3-oscr](https://github.com/DragonBox-Shop/retrode3-oscr),
Kernel/Treiber/DTB/Config in `retrode3-kernel`, SPL/U-Boot in
`retrode3-uboot`, Schaltplaene in `retrode3-hardware`.
Keine zweite native Reader-Implementierung in diesem Repo anlegen.

## Branches, Tags und Freigaben (verbindlich)

- **`develop` ist die gemeinsame Werkstatt.** Hier werden neue und
  experimentelle Funktionen direkt entwickelt, auch wenn sie unfertig sind,
  Tests scheitern oder der aktuelle HEAD nicht funktioniert. Niemand darf
  annehmen, dass ein beliebiger `develop`-Commit lauffaehig ist.
- **Ein feststehender, moeglichst annotierter Git-Tag auf `develop` markiert
  einen bewusst abgeschlossenen, grundlegend geprueften Gesamtstand.**
  Ein Tag bezeichnet den *gesamten* Repository-Snapshot, nicht nur eine
  einzelne Funktion. Bei diesem Stand sollen die vorgesehenen Funktionen
  laufen; noch moegliche Bugs und fehlende Langzeittests sind erlaubt.
  Nicht fertiggestellte Risiken muessen nachweislich deaktiviert/abgesichert
  sein. Tags niemals verschieben oder wiederverwenden.
- **Erst aus genau einem solchen Tag bzw. dessen unveraenderlichem Commit**
  werden vollstaendige SD-Image-Releases gebaut. Debian-Paketkandidaten
  entstehen beim expliziten Paketlauf aus den aktuellen, exakt fixierten
  Branch-Commits (`develop` -> testing, `master` -> stable), ohne Tag-Pflicht.
  Das Build-Manifest fixiert OS-, OSCR-, Sanni- und Plattform-Revisionen
  sowie Paketpruefsummen. Image-Builds verlangen weiterhin beide Release-Tags.
- Danach folgen Paketinstallation, Updates, Rollback und Hardwaretests.
  **Erst nach ausfuehrlicher Abnahme kommt genau der getaggte Stand in
  `master`**, nicht der inzwischen weitergewanderte `develop`-HEAD.
  `master` muss stets ein funktionsfaehiger, getesteter Release-Stand sein.
  Wenn der Tag in der Master-Historie vorwaerts integrierbar ist,
  Fast-Forward bevorzugen, damit Master-Commit und Tag identisch bleiben.
  Bei abweichender Historie zuerst explizit aufloesen, niemals blind
  zusammenfuehren, squaschen oder force-pushen.
- **Keine dauerhaften Feature-/Plugin-Branches.** Kurzlebige Branches nur
  fuer technisch notwendige Isolation (z. B. grosse Kernel-Upgrades,
  riskante Hardwareversuche, fremde PRs), anschliessend in `develop`
  integrieren und aufraeumen. Vor Branch-Loeschungen einzigartige Commits
  und offene PRs pruefen.
- Keine automatische Promotion `develop` -> `master`. Ein Git-Tag,
  ein erzeugtes .deb, ein signierter APT-Index, ein erfolgreiches Boot und
  ein freigegebenes Kundenimage sind **verschiedene** Meilensteine.

**Buildserver:** Die OS-/OSCR-Paketautomatik fixiert Branch-Commits; nur
Image-Builds verwenden immutable Release-Tags.
Kernel und U-Boot werden als getrennte Plattformpakete aus exakt
fixierten Commits gebaut. Der Image-Bau konsumiert die signierten
Paket-Snapshots. Keine Rueckstufung bereits publizierter Quell-Commits;
`master`/`stable` nicht mit laufender Image-Entwicklung aktualisieren.
Plugin-Pakete werden aus den validierten OSCR-Core-Rezepten entdeckt.
`retrode3-cores` zieht saemtliche freigegebenen Core-Pakete nach, ohne
sie automatisch zu aktivieren. Keine Labor-Plugins als Release-Rezepte.

## Tests und sichere Entwicklung

- Unfertiger Code darf auf `develop` liegen; ein Release-Tag darf nur
  bewusst nach fuer den Umfang angemessenen Build-/CI-/Smoke-Tests gesetzt
  werden. Bei fehlgeschlagenen Tests niemals eine Freigabe vortaeuschen.
- Fuer Aenderungen an Web, Debian-Paketierung, Init oder Build-Metadaten
  vor einem **Release-/Tag-Kandidaten** im vollstaendigen lokalen Checkout
  `./tools/preflight-ci.sh` ausfuehren. Hardwareunabhaengige CI ist nicht
  gleichbedeutend mit MIPS-Hardwaretests. Bei direkten Experimenten auf
  `develop` sind rote Checks zulaessig und als unfertig zu kennzeichnen;
  CI-Pruefungen nicht durch `continue-on-error` oder Deaktivieren kaschieren.
- Kein unkontrolliertes `make-all` auf der Retrode: Legacy-Bausteine
  koennen Pakete installieren. Keine Produktiv-SD oder installierte Kernel-/
  Modulkopie ohne Backup ueberschreiben. Image-Builder schreiben nur
  normale Image-Dateien, niemals direkt Blockgeraete.
- ROMs, Spielstaende, Core-Aktivierung, USB-Services und bestehende
  `/run/lock/retrode3/bus.lock`-Inode nicht beschaedigen. Fuer Hardware-
  IO, Cartridge-Writes, Spannung und Timing gelten eigene Freigabe-Gates.

## Laufzeitvertraege

- Gemeinsame CLI: `/usr/bin/retrode3-cli`; administrativer Schalter:
  `/usr/sbin/retrode3-corectl`.
- Core-Paare: `/usr/lib/retrode3/cores-available/<id>.{so,core}`;
  Aktivierung: `/etc/retrode3/cores-enabled/<id>.so`.
- Bus-Lock: `/run/lock/retrode3/bus.lock`; Bootsystem: **SysV init**
  (nicht systemd oder systemd-tmpfiles).
- Die Weboberflaeche nutzt nur das gemeinsame CLI und dynamisch gemeldete
  Core-Capabilities; keine systemspezifischen Reader oder Hardcoded-Mapper-
  Logik im Frontend. Ein Browser-Refresh darf keine Cartridge-Operation
  ausloesen. Privilegierte Aktionen nur ueber streng begrenzte Helfer,
  niemals den gesamten Webserver als root starten.
- Entfernte Legacy-Binaries unter `/usr/local/bin/oscr`,
  `retrode3-read`, `retrode3-dump`, `retrode3-info` nicht wiederbeleben.

## Aktueller technischer Stand: nicht in AGENTS.md einfrieren

- [Buildserver und Image-Bau](buildserver/README.md) und
  [Image-Release-Gates](buildserver/IMAGE-PIPELINE.md)
- [Paketlayout und Testanleitung](packaging/README.md)
- [Web-v2-Entwickleranleitung](retrode3-web-control/v2/docs/developer-guide.de.md)
  und [CLI-Integration](retrode3-web-control/v2/docs/cli-integration.md)
- Historische Arbeits- und Testberichte bleiben in den jeweiligen
  `docs/`-Dateien; deren alte TODO-Abschnitte nicht mit dem aktuellen
  HEAD verwechseln. Vor Aenderungen stets aktuelle Git-Quellen,
  CI-Ergebnisse und Hardware-Abnahmestand pruefen.

## Redaktionelles Changelog

`CHANGELOG.md` ist fuer Anwender, keine Git-Commit-Liste. Sichtbare neue
Funktionen, Fehlerkorrekturen und relevante Einschraenkungen unter der
naechsten Release-Ueberschrift sammeln. Vor dem Tag muss die Ueberschrift
exakt zur Versionskennung (ohne `apt-`) passen. Historische Eintraege
nicht nachtraeglich umdeuten. Der Image-Publisher exportiert ausschliesslich
das Changelog des tatsaechlich gebauten OS-Tags. Keine Aussagen ueber
Hardwarefreigabe ohne Testnachweis.
