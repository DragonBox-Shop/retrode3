# Retrode3 Web v2: Entwickleranleitung


> **Aktueller Entwicklerstand auf `develop`:** NES, MegaDrive und
> SNES implementieren die generische Core-ABI v3. Web Control v2
> verwendet für alle ROM-Leseaufträge nur noch das versionierte
> `selection`-Objekt (`auto`, `candidate`, `layout`, `override`).
> Das alte NES-v2-Auswahlformular und die SNES-/MegaDrive-Sonderparameter
> sind aus dem Web entfernt. `get_capabilities.selection_schema` und
> `slot` kommen aus dem CLI. Für neue Plugins sind keine
> systemspezifischen Web-Anpassungen nötig.
> [Details zum generischen Web-Vertrag](generic-selection-v3.md).
> Der gemeinsame CLI kann ABI v1/v2 weiterhin für andere Clients
> unterstützen. Web v3-Integration und Debian-Pakete sind noch nicht
> als neue Kunden-Images hardwareabgenommen.

**Stand: November 2026.** Dies ist die technische Dokumentation des **gemeinsamen CLI-Systems** und seiner Web-v2-Anbindung. Die [Benutzeranleitung](user-guide.de.md) beschreibt die Bedienung im Browser. Maßgeblich sind die tatsächlich installierten CLI-Versionen und die `--list-cores`-Ausgabe; Funktionen, die eine Core-Version nicht meldet, dürfen nicht vorausgesetzt werden.

## 1. Architektur und Zuständigkeiten

```text
Browser (PHP/JavaScript)
  -> PHP-API / Python-Backend (127.0.0.1:8765)
     -> JobManager / Auto-Detect / Bus-Serialisierung
        -> /usr/bin/retrode3-cli (NDJSON v1)
           -> dynamischer Core: snes.so | md.so | nes.so
              -> Retrode3-HAL und Linux-Kernel-Slot-Treiber
```

- **Ein einziges CLI** veröffentlicht Events, Fortschritt, Fehler und fertige Ergebnisse. Die Cores implementieren die versionsgebundene Core-ABI; sie sind **keine eigenständigen Reader-Programme** und benötigen keine eigene JSON-/HTTP-Schnittstelle.
- Das Python-Backend empfängt Kernel-`KOBJ_CHANGE`-Events und prüft passiv den `sense`-Wert. Erst bei eindeutiger Zuordnung zu einem aktiven Core initiiert es einen sicheren `probe`. Das Ergebnis wird im Backend zwischengespeichert.
- Der Browser liest `GET /api/slots` derzeit alle 1,5 Sekunden, **ohne** dabei einen neuen ROM-Probe anzustoßen. Hardwarejobs laufen nur über die zentrale Jobverwaltung; parallele Cartridge-Zugriffe sind gesperrt.
- Die generische CLI-Implementierung und die OSCR-Adapter liegen im Repository [`retrode3-oscr`](https://github.com/DragonBox-Shop/retrode3-oscr). Dieses OS-Repository enthält Web v2, Systemdienste und Debian-Paketierung. Kernel- und Hardwareentwicklungen sind getrennt.

## 2. Installierte Programme und Core-Verzeichnisse

| Zweck | Pfad |
| --- | --- |
| Gemeinsame CLI | `/usr/bin/retrode3-cli` |
| Privilegierter Core-Schalter | `/usr/sbin/retrode3-corectl` |
| Installierte Core-Module + Manifeste | `/usr/lib/retrode3/cores-available/<id>.so` und `<id>.core` |
| Aktivierte Cores | `/etc/retrode3/cores-enabled/<id>.so` (kontrollierter Symlink) |
| Gemeinsame Hardware-Sperre | `/run/lock/retrode3/bus.lock` |
| Slot-Zustand | `/sys/class/retrode3/slot-<slot>/sense` |
| Web-Backend | `/opt/retrode3-web-v2/backend/service.py` |
| Web-API | `http://127.0.0.1:8765/api/...` (nur lokal) |
| ROM-Ablage der Weboberfläche | `/usr/local/games/ROMs/` |

Auf der Entwicklungs-Retrode3 wurden die Core-IDs `snes`, `md` und `nes` getestet. Sie unterstützen nur **SNES Standard-LoROM/HiROM**, **MegaDrive Linear-ROM** und **NES Mapper 0 (NROM)**. Keine Save-, Flash- oder sonstigen Cartridge-Schreiboperationen. Eine anwesende Cartridge ist keine sichere Hardware-/Adapter-Identifikation.

## 3. Cores erkennen

Auf der Retrode3 über eine Shell oder USB-Seriell:

```sh
/usr/bin/retrode3-cli --list-cores --protocol ndjson-v1
```

Die CLI liefert einen NDJSON-`cores`-Event mit `protocol:"retrode3-ndjson"`, `version:1` und einer `cores`-Liste. Pro Core sind unter anderem `id`, `slot`, `installed`, `enabled`, `status`, `usable` und `actions` zu prüfen. Ein Core ist nur verwendbar, wenn er installiert, aktiviert, ABI-kompatibel und `ready` ist und die gewünschte Aktion anbietet.

**Wichtig:** Core-Auflistung ist keine Hardwareaktion und benötigt kein eingelegtes Modul. Inkompatible oder deaktivierte Module sollen nicht durch spontane direkte `dlopen`-Aufrufe im Webserver untersucht werden.

## 4. Einmalige Hardwareoperationen (One-shot)

Die folgenden Beispiele setzen ein **bekanntes, kompatibles Modul** und einen **freien Bus** voraus. Sie gehören auf die Retrode3, nicht auf den PC:

```sh
# SNES probe, kein ROM-Dump
/usr/bin/retrode3-cli --protocol ndjson-v1 --core snes --action probe

# Mega Drive probe
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md --action probe

# NES probe (aktueller Core nur NROM)
/usr/bin/retrode3-cli --protocol ndjson-v1 --core nes --action probe

# ROM-Lesevorgang: Ziel muss absolut und noch nicht vorhanden sein
/usr/bin/retrode3-cli --protocol ndjson-v1 --core md \
  --action read-rom --output /tmp/retrode3-md-test.md
```

`probe` liefert bei Erfolg `probe_result` mit System, Titel, Mapping, Größe und Core-spezifischer Prüfsumme. `read-rom` gibt `progress`- und abschließend einen `result`-Event (mit `bytes_written`, `crc32` und Ausgabepfad) oder einen `error`-Event zurück.

Das CLI verlangt einen absoluten Ausgabepfad und verweigert das Überschreiben vorhandener Dateien. **Es beschränkt den Zielpfad nicht auf die Web-ROM-Ablage**; wer die CLI direkt aufruft, muss selbst den sicheren Zielordner und die erforderlichen Dateirechte sicherstellen. Für den hier gezeigten Befehl nur einen frischen Dateinamen wählen.

Ein einmaliger CLI-Aufruf ist nicht über den interaktiven `cancel`-Befehl abbrechbar. Nicht gleichzeitig mit Web-Lesejobs oder anderen direkten CLI-Probes starten: die gemeinsame Bus-Sperre verhindert gleichzeitige Hardwarezugriffe.

## 5. Interaktives NDJSON-v1-Protokoll

Das Webbackend verwendet die interaktive CLI und schreibt **eine JSON-Anweisung je Zeile** auf stdin:

```sh
/usr/bin/retrode3-cli --protocol ndjson-v1 --interactive
```

Beispielhafte, voneinander unabhängige Befehlszeilen:

```json
{"command":"list_cores","request_id":"list1"}
{"command":"get_capabilities","core":"md","request_id":"caps1"}
{"command":"probe","core":"md","request_id":"probe1"}
{"command":"read_rom","core":"md","request_id":"rom1","output":"/tmp/retrode3-interactive.md"}
```

**Nicht als JSON-Array senden.** Nach dem Start sendet die CLI einen `ready`-Event mit `system:"multi"`. Sie antwortet mit korrelierten Events wie `cores`, `capabilities`, `probe_result`, `progress`, `result` und `error`. Für einen während des Lesens aktiven Job lässt sich zusätzlich eine Zeile `{"command":"cancel","request_id":"rom1"}` senden. Die `request_id` muss zur laufenden Anweisung passen.

`read_rom` und `read-rom` bezeichnen dieselbe Aktion nur in ihren jeweils dokumentierten Kontexten: JSON verwendet `read_rom`, die One-shot-CLI akzeptiert `--action read-rom`. Ein CLI-Event mit `verified:null` sagt, dass keine generische hostweite Datenbankprüfung integriert ist; die NES-NROM-Core-Erkennung führt ihre eigene Datenbank-/CRC-Prüfung durch.

## 6. Core-Verwaltung und Boot-Sperre

```sh
# Als root: bewusst aktivieren/deaktivieren
/usr/sbin/retrode3-corectl enable md
/usr/sbin/retrode3-corectl disable md

# Laufzeit- und Webdienste auf SysV-Systemen kontrollieren
service retrode3-core-runtime status
service retrode3-web-v2 status

# Nur passiven Zustand lesen, ohne Cartridge-Probe
cat /sys/class/retrode3/slot-md/sense
wget -qO- http://127.0.0.1:8765/api/slots
```

Die Retrode3 verwendet **SysV init**, nicht systemd. `retrode3-core-runtime` bereitet `/run/lock/retrode3/bus.lock` vor; das CLI sperrt diese Datei mit `flock`. Die Datei **niemals während des Betriebs löschen oder austauschen**. Der Webdienst läuft unter `www-data`, für Cartridge-Devices mit eingeschränkten Gruppenrechten. Core-Aktivierung ist privilegiert und im Web standardmäßig deaktiviert; niemals dem Webserver pauschalen root-/sudo-Zugriff geben.

Web v2 startet keine eigene CLI-Kopie und installiert keine Core-Binaries. Eine Core-Aktivierung erfordert ein installierbares, vertrauenswürdiges Modul samt passendem Manifest; sie ändert keine physische Adapterkompatibilität.

## 7. Web-API und automatische Slot-Verarbeitung

Das Python-Backend ist auf `127.0.0.1:8765` gebunden. Der Browser verwendet den PHP-Gateway `api.php` (Same-Origin, CSRF für Änderungen). Wichtige Backend-Routen:

| Methode | Route | Zweck |
| --- | --- | --- |
| GET | `/api/health` | Backend-Liveness |
| GET | `/api/cores` | Core-Registry via gemeinsamer CLI |
| GET | `/api/capabilities` | Für die UI angebotene Aktionen |
| GET | `/api/slots` | Passive Slots + gespeicherte Erkennung |
| GET | `/api/jobs/active` | Aktiver/letzter Job |
| POST | `/api/jobs` | `{"system":"md","command":"probe"}` oder `read_rom` |
| POST | `/api/jobs/<job-id>/cancel` | Abbruch anfordern |
| POST | `/api/cores/toggle` | Nur mit freigegebener Admin-Rechtebrücke |

Die automatische Erkennung wartet kurz auf einen stabilen Sense-Zustand, behandelt wiederholte identische Events ohne erneuten Probe und führt mehrere notwendige Probes **nacheinander** durch. Ein laufender manueller ROM-Dump hat Vorrang; das Backend startet dann keine zusätzlichen CLI-Inventarisierungen für einen wartenden automatischen Probe. Die Browser-Abfrage des Slots ist **kein** Auslöser eines Hardwarejobs.

Die lokale Python-HTTP-API nicht ungeschützt ins Netz binden. Browser-Anfragen müssen über den vorgesehenen PHP-Gateway laufen.

## 8. Einen zusätzlichen Core entwickeln

1. Im [`retrode3-oscr`](https://github.com/DragonBox-Shop/retrode3-oscr)-Repository unter `src/retrode3/` die bestehende Core-ABI (`include/retrode3/core_descriptor_v1.h`, `core_operations_v1.h`) und den typisierten Lese-HAL verwenden.
2. Core-Descriptor (`id`, `name`, `version`, `slot`) und unterstützte read-only Operationen bereitstellen. Das passende, root-eigene `<id>.core`-Manifest muss mit dem Descriptor übereinstimmen.
3. Zugriffs-/Mapper-/Spannungssicherheit und echte Hardwaretests nachweisen. Neue Mapper oder RAM-/Flash-Schreiboperationen **nicht** allein aus einer Slot-Belegung ableiten.
4. Den Core in die zentrale Build-/Staging- und anschließend die OS-Debian-Paketpipeline integrieren. Ein neues Paket wird nicht automatisch aktiviert; `retrode3-corectl` verwaltet die Aktivierung.
5. Web v2 liest die Core-Registry dynamisch. Solange der Core korrekt `ready` und `usable` mit `probe`/`read_rom` meldet, benötigt die Weboberfläche kein neues pro-Konsole-CLI und kein separates JSON-Protokoll.

## 9. Quellstände und Release-Grenzen

- **`retrode3/master`**: freigegebene Web-v2-Quellen.
- **`retrode3/develop`**: laufende Integration, einschließlich neuer Debian-Paketkandidaten unter `packaging/`. Deren Hardware-/Upgrade-Abnahme ist getrennt von dieser Anleitung.
- **`retrode3-oscr`**: zentrale CLI-/Core-Quellen und deren Test-/Staging-Ziele.
- **Web-v2-Vertragsdokument:** [`cli-integration.md`](cli-integration.md).
- **Paketdokumentation auf `develop`:** [`packaging/README.md`](https://github.com/DragonBox-Shop/retrode3/blob/develop/packaging/README.md).

Ein grüner CI-Lauf oder die Quellcode-Freigabe in `master` bedeutet nicht automatisch, dass die aktuellen Debian-Pakete und das Kunden-SD-Image auf der realen Retrode3 geprüft sind.
