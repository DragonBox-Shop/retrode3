# Web Control v2: generische Cartridge-Auswahl (CLI-ABI v3)

**Entwicklungsstand auf `retrode3/develop`.** Vertrag: [`retrode3-oscr/docs/generic-cartridge-selection-v3.md`](https://github.com/DragonBox-Shop/retrode3-oscr/blob/develop/docs/generic-cartridge-selection-v3.md). Noch keine hardwarevalidierte Freigabe oder Übernahme nach `master`.

## Grundsatz

Die Weboberfläche **kennt keinen Mapper und keine Konsole**. Sie verwendet ausschließlich die gemeinsame CLI für Reader-/Slot-Zuordnung, Cartridge-Probes, zulässige Operationen, Auswahlmöglichkeiten, Formularbeschreibung und finale Sicherheitsprüfung.

- `GET /api/capabilities`: CLI-Core-Registry mit `id`, `slot` und zulässigen `commands`. Ein Core mit physischem `slot=snes` erscheint auf diesem Slot, auch wenn sein logisches System anders heißt. Der Browser schließt nicht aus dem Core-Namen auf die Hardware.
- `GET /api/reader-options/<core-id>`: Ein **metadatenbasierter** `get_capabilities`-Aufruf an das CLI. Liefert `selection_schema` mit `schema_version`, `schema_id`, `selection_modes`, `fields` und optionalen `rules`. Bei alten Cores ist `selection_schema:null`.
- `GET /api/slots`: Kernel-Sense plus vom Backend zwischengespeichertes `probe_result`; nur passive Anzeige, **kein Hardware-Read beim Browser-Refresh**.
- `POST /api/jobs` für `read_rom`: Ein einziges `selection`-Objekt gemäß NDJSON v1 Selection Version 1, ohne parallele alte Mapper-/Größenfelder.
- Backend und CLI prüfen Schema-ID, Mode und Struktur. Die **endgültige** Freigabe einzelner Werte und Kombinationen obliegt dem Core. Browserhinweise sind keine Sicherheitsgarantie.

## UI-Ablauf

1. Eingestecktes Cartridge wird durch Kernel-Event erkannt, Backend führt read-only Probe mit der zentralen CLI aus.
2. Wenn mehrere mögliche **Titel** vorhanden sind, erscheint eine optionale Auswahl. Gleicher sicherer Leseraufbau lässt weiterhin `auto` zu.
3. Bei mehreren erforderlichen **Layouts** ist `selection_required:true`; ohne explizite verfügbare Kandidaten-/Layout-ID bleibt `Read ROM` deaktiviert.
4. Kandidaten mit `read_supported:false` sind sichtbar, aber nicht auswählbar. Ihre `reason` wird angezeigt.
5. Ein separater Haken **Override** schaltet alle vom Core angebotenen Felder frei, auch bei unbekannten oder vermeintlich eindeutig erkannten Spielen. Er ist beim Reader-/Modulwechsel wieder **ausgeschaltet**.
6. Das Formular unterstützt `enum`, `integer`, `boolean`, `string`; `default`, `required`, `visible_when`, `required_when`, deklarative `rules.when`, `rules.allow`, `read_supported`. Kein Code/Eval aus Core-Metadaten.
7. Die im `result` gelieferten Angaben `identity`, `read_configuration` und `verification.status` werden unabhängig vom Benutzer gewählten Dateinamen angezeigt. Ein erfolgreicher Dump ist nicht automatisch verifiziert.

Beispiel für ein Web-Job-Payload, unabhängig von einem konkreten System:

```json
{
  "system": "example-adapter",
  "command": "read_rom",
  "filename": "my-backup",
  "selection": {
    "version": 1,
    "mode": "override",
    "schema_id": "adapter-layout-v1",
    "parameters": {"bank_count": 1, "safe": true}
  }
}
```

Der Backend-Job ergänzt ausschließlich seinen **serverseitig kontrollierten** absoluten Ausgabepfad, die Request-ID und den CLI-Core-ID-Schlüssel. Der Browser legt niemals selbst den Ausgabepfad oder elektrische Signale fest.

## Migration / offene Grenzen

- Der alte **NES-v2**-Sonderrenderer und die vorhandenen Backend-Validatoren bleiben vorübergehend als Kompatibilitätsweg für noch nicht auf ABI v3 migrierte NES-Cores. **Neue** Cores verwenden ausschließlich v3; ihre Parameter benötigen keine HTML-/JavaScript-/Python-Sonderfälle.
- Sobald SNES/MD/NES auf v3 umgestellt und auf Hardware getestet wurden, kann die alte NES-v2-Bedienlogik entfernt werden. Das ist ein separater Cleanup.
- Die CLI muss `get_capabilities.selection_schema` ohne Cartridge-Hardwarezugriff bereitstellen; `probe_result.selection_schema_id` muss zur aktiven Revision passen. Ist sie veraltet, bleibt der Read-Button gesperrt.
- Web-Fehlerbehandlung verweigert ein fehlerhaftes oder nicht erreichbares CLI-Schema. Ein unbekannter Core wird nicht als freigegebener Leser geraten.
- Nach dem Wechsel auf v3 den gesamten Weg auf echter Retrode3 testen: Einlegen/Entfernen, mehrere Titel, unterschiedliche Layouts, unbekannter Probe mit Override, unerlaubte Kombination, unveränderte Mapper-/Save-Sperren, parallele Leser, Neustart und Debian-Paket-Upgrade.
- `packaging/build-debs.py` installiert die zusätzliche Web-JavaScript-Datei `assets/selection-ui.js`. Ein manuelles `retrode3-web-v2-update` kopiert sie über den bestehenden Installer. Ein Git-Pull allein aktualisiert nicht die aktive Weboberfläche.
