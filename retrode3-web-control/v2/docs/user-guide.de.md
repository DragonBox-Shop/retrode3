# Retrode3: Benutzeranleitung (Web Control v2)

Diese Anleitung beschreibt die Weboberfläche aus dem Retrode3-OS-Repository auf `master` (Stand November 2026). Die separate [Entwickleranleitung](developer-guide.de.md) dokumentiert die gemeinsame Kommandozeile `retrode3-cli` und ihre Schnittstellen.

## 1. Anschließen

Verbinde die Retrode3 per USB mit Deinem Computer und öffne `http://172.31.255.1/`. Diese Adresse gilt für die aktuelle USB-Netzwerkkonfiguration; sie ist keine allgemein garantierte Adresse für spätere Images.

Die Weboberfläche ist auf dem bisherigen Entwicklungsgerät standardmäßig ohne Passwort erreichbar. Ein Passwort lässt sich bei Bedarf mit `retrode3-web-v2-auth enable` einrichten. Die Oberfläche nicht ohne zusätzliche Absicherung ins öffentliche Internet stellen; Basic Auth über HTTP verschlüsselt die Anmeldung nicht.

## 2. Modul automatisch erkennen und ROM auslesen

1. Stecke ein unterstütztes Spielmodul in den passenden Slot. Die Slot-Kacheln zeigen die physische Belegung.
2. Das Web-v2-Backend reagiert auf Kernel-Ereignisse und führt bei einem eindeutig zugeordneten, unterstützten Core einen **automatischen, nur lesenden Probe** durch. Ein manuelles „Spielmodul erkennen“ ist im Normalfall nicht nötig.
3. Wähle den Slot. Prüfe den erkannten Titel, das Mapping und die ROM-Größe. Der Dateiname wird passend zum gewählten Slot vorgeschlagen und kann angepasst werden.
4. Klicke auf **ROM auslesen**. Die Fortschrittsanzeige zeigt tatsächlich verarbeitete Bytes.
5. Öffne nach Abschluss den **Dateimanager** und lade die Datei bei Bedarf herunter.

Falls mehrere Reader für denselben physischen Slot möglich sind, wählt das Backend aus Sicherheitsgründen nicht willkürlich einen aus. Der Reader muss dann passend zum angeschlossenen Adapter manuell gewählt werden. Ein bloßer `occupied`-Zustand bestimmt **weder Konsolentyp noch Adapter oder sichere Spannung**.

Beim Entfernen eines Moduls verschwindet dessen Erkennung aus der Oberfläche. Ein laufender Lesevorgang auf diesem Slot wird abgebrochen. Ein Browser-Refresh startet **keine** erneute Hardware-Erkennung: Der Browser fragt lediglich den im Backend gespeicherten Zustand ab. Aufwendige ROM-Probes werden zentral über die gemeinsame CLI serialisiert.

Modul während des Lesens nicht entfernen und keine nicht unterstützten Mapper oder Spannungen erzwingen.

## 3. Unterstützte Systeme

Die folgenden **Stage-1-Cores** wurden auf der Entwicklungs-Retrode3 über die gemeinsame CLI physisch getestet:

| System | Core-ID | Unterstützter Umfang |
| --- | --- | --- |
| Super Nintendo | `snes` | Standard-LoROM/HiROM; keine Spezialchips oder SRAM-Operationen |
| Mega Drive | `md` | Standard-Linear-ROMs; keine Spezialmapper oder Save-Schreibzugriffe |
| NES / Famicom | `nes` | NROM, Mapper 0; keine weiteren Mapper oder Save-Schreibzugriffe |

Die Verfügbarkeit in Deiner Installation hängt davon ab, welche Cores installiert, aktiviert und als `ready` gemeldet werden. Eine neue Software-Core-Datei ist nicht automatisch ein geeigneter Hardwareadapter.

Der Bereich zum **Beschreiben von Modulen** ist nur vorbereitet. SRAM-Restore, Flashen und andere Cartridge-Schreiboperationen stehen in dieser Web-v2-Version nicht zur Verfügung. Die NES-Ausgabe umfasst den von der Core-Datenbank erzeugten 16-Byte-iNES-Header.

## 4. Erweiterte Einstellungen und Plugins

Unter **Erweiterte Einstellungen** lassen sich installierte, geeignete Reader manuell auswählen. Mapper- und Größen-Overrides erscheinen nur, wenn der jeweilige Core sie tatsächlich anbietet; die aktuellen Stage-1-Cores erlauben keine beliebigen Overrides.

Unter **Plugins** werden installierte Cores, Aktivierung, ABI-Status und unterstützte Aktionen angezeigt. Die reine Anzeige ist möglich; die Web-Schalter zum Aktivieren/Deaktivieren sind standardmäßig gesperrt und erfordern eine eigens abgesicherte Administrationsfreigabe.

## 5. Dateien und Netzwerk

ROMs liegen unter `/usr/local/games/ROMs/`, etwa `ROMs/MD/`, `ROMs/SNES/` oder `ROMs/NES/`. Der Dateimanager kann Dateien herunterladen, verschieben, umbenennen und löschen. Die Samba-Freigabe `retrode` stellt `/usr/local/games` zur Verfügung.

**Achtung:** Das USB-Massenspeicher-Image ist aktuell ein eigenständiger Datenträger. Web-/Samba-Dateien werden nicht automatisch dorthin gespiegelt. Dasselbe Dateisystem nie gleichzeitig auf Host und Retrode3 beschreibbar einhängen.

In **Allgemeine Einstellungen** findest Du WLAN-Status und Verbindungsmöglichkeiten. Die WLAN-Funktionen setzen ein erkanntes Gerät sowie den installierten `retrode3-wlan`-Helper voraus; ein nicht verfügbarer ESP/WLAN-Treiber lässt sich nicht durch die Oberfläche ersetzen.

## 6. Fehlerbehebung

Zur Diagnose auf der Retrode3 (SSH oder serielle Konsole):

```sh
service retrode3-core-runtime status
service retrode3-web-v2 status
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1
wget -qO- http://127.0.0.1:8765/api/slots
tail -n 50 /var/log/retrode3-web-v2.log
iw dev
```

Ein als `occupied` gemeldeter Slot garantiert **keine** erfolgreiche ROM-Erkennung. Fehlende oder inkompatible Cores werden nicht durch alte Reader-Programme ersetzt. Für reproduzierbare CLI-Probes und ROM-Dumps siehe die Entwickleranleitung.

## 7. Für Entwickler: neue gemeinsame CLI

Alle Cartridge-Operationen verwenden **`/usr/bin/retrode3-cli`** und die aktivierten dynamischen Cores. Beispiele für eine **freie Hardware-Bus-Sperre** und ein bekanntes, unterstütztes Spiel:

```sh
# Cores und ihre tatsächlichen Aktionen anzeigen
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1

# Nur lesender Probe, beispielsweise für Mega Drive
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md --action probe

# Komplettes ROM in eine NEUE Datei schreiben
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md \
  --action read-rom --output /tmp/retrode3-test.md
```

Diese Befehle nicht parallel zu einem Web-ROM-Dump ausführen. Die CLI verwendet `/run/lock/retrode3/bus.lock`; der Webserver startet für Hardwarejobs dieselbe CLI. Der Ausgabepfad muss absolut sein, und eine vorhandene Datei darf nicht überschrieben werden. Bei direkter CLI-Nutzung bist Du selbst für einen sicheren Zielordner verantwortlich.

Die [ausführliche Entwickleranleitung](developer-guide.de.md) beschreibt den interaktiven NDJSON-v1-Modus (`ready`, `probe_result`, `progress`, `result`, `error`), Core-Verzeichnisstruktur, `retrode3-corectl`, SysV-Init, die Web-API und das Hinzufügen weiterer Cores. Es gibt **keine separaten SNES-, MegaDrive- oder NES-Reader-Programme mehr im regulären Laufzeitpfad**.

## 8. Quellcode und Dokumentation

- [Retrode3 OS, Web v2 und Debian-Paketierung](https://github.com/DragonBox-Shop/retrode3)
- [Gemeinsame CLI und OSCR-Cores](https://github.com/DragonBox-Shop/retrode3-oscr)
- [Kernel und Slot-Treiber](https://github.com/DragonBox-Shop/retrode3-kernel)
- [Hardware und Adapter](https://github.com/DragonBox-Shop/retrode3-hardware)
- [Technischer Web-v2-/CLI-Vertrag](cli-integration.md)

Der neue Web-v2-Quellstand liegt auf `master`. Debian-Paketkandidaten werden getrennt auf `develop` getestet; ein freigegebener Quellstand ist noch kein vollständig geprüftes Kunden-SD-Image.
