# Retrode3 OS, Debian-Pakete und Bootimages

Der stabile Quellstand liegt auf `master`, die gemeinsame laufende
Entwicklung von Kernelschnittstellen, Weboberfläche,
Core-Paketen und SD-Karten-Images auf `develop`.

Für die neue, real hardwaregetestete zentrale OSCR-Architektur
(SNES, MegaDrive und NES) gilt der verbindliche
[Build- und Paketlayout-Vertrag](docs/build-and-release-layout.md).
Der neue zentrale Host kommt aus
[`DragonBox-Shop/retrode3-oscr`](https://github.com/DragonBox-Shop/retrode3-oscr).
Neue Cores haben getrennte Debian-Pakete, **aber keine
separaten permanenten Entwicklungsbranches**.

## Offizielle Weboberfläche: Web Control v2

Der getestete Web-v2-Quellstand liegt in
[`retrode3-web-control/v2/`](retrode3-web-control/v2/).
Die Weboberfläche verwendet ausschließlich die gemeinsame
`/usr/bin/retrode3-cli` (SNES, MegaDrive, NES), das separate
`retrode3-corectl` und die OS-verwaltete Bus-Sperre.
Der Browser liest gespeicherte Erkennungsdaten des Backends und löst
**beim Aktualisieren keine Cartridge-Probes** aus.

**Aktuelle Dokumentation:** [Benutzeranleitung (DE)](retrode3-web-control/v2/docs/user-guide.de.md),
[Benutzeranleitung (EN)](retrode3-web-control/v2/docs/user-guide.en.md),
[Entwickleranleitung für das neue CLI (DE)](retrode3-web-control/v2/docs/developer-guide.de.md)
und [Developer Guide (EN)](retrode3-web-control/v2/docs/developer-guide.en.md).
Der Hilfe-Tab der Weboberfläche verweist auf diese Dokumente in `master`.

**Web v1 ist außer Betrieb:** Die historische PHP-Oberfläche in
`retrode3-web-control/var/www/html/` bleibt nur zur Nachvollziehbarkeit
im Git erhalten. Ihr QuantumSTEP-Bauziel ist deaktiviert. Weder das
`retrode3`-Metapaket noch `make-all` sollen das alte Web-Paket weiter
bauen oder installieren.

**Freigabegrenze:** Die Aufnahme von Web v2 in `master` ist eine
Quellcode-Freigabe, **noch kein fertiges Kunden-SD-Image**.
Die neuen nativen Debian-Pakete, die Web-v2-Paketintegration und ein
getesteter Image-Upgrade-Pfad fehlen weiterhin. Der bestehende
`make-all`-Build ist der Legacy-Bauweg; er ersetzt Web v1 ausdrücklich
nicht automatisch durch ein Web-v2-Paket.
Bis dahin gilt die auf echter Hardware getestete
[Web-v2-Installationsanleitung](retrode3-web-control/v2/README.md)
für Entwicklungsgeräte mit bereits installiertem CLI und Cores.
Ein späteres Kundenimage darf nicht auf die alte Weboberfläche
zurückfallen.

Die übrige QuantumSTEP-Paketierung und `make-all` können weiterhin
Pakete automatisch installieren: nicht unkontrolliert in CI ausführen.
Weitere Details stehen im [Paket-Bauplan](docs/build-and-release-layout.md).

---

## Ursprüngliche Kurzbeschreibung

# Retrode3 User-Space code to extend base Debian for important functions

Add information how to compile and/or use and link more information