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

Die bestehende QuantumSTEP-Paketierung und `make-all` sind weiterhin
der **Legacy-Stand**. Insbesondere kann `make-all` Pakete automatisch
installieren: nicht unkontrolliert als CI-Aufruf verwenden.
Der Release-/Image-Bau wird im `develop`-Branch ergänzt und
vor Übernahme nach `master` gegen echte Hardware getestet.

---

## Ursprüngliche Kurzbeschreibung

# Retrode3 User-Space code to extend base Debian for important functions

Add information how to compile and/or use and link more information