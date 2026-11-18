# Retrode3: Benutzeranleitung

*Entwicklungsstand der neuen Weboberfläche (November 2026). Dieses Dokument lässt sich später unverändert als Grundlage für das Retrode3-Wiki verwenden.*

## 1. Anschließen und starten

Verbinde die Retrode3 per USB mit Deinem Computer. Über die eingerichtete USB-Netzwerkverbindung ist die Weboberfläche auf dem Entwicklungsgerät unter `http://192.168.0.202/` erreichbar. Die IP-Adresse kann sich bei späteren Softwareversionen ändern.

Die Weboberfläche ist standardmäßig **ohne Passwort** nutzbar. Optional kann der Gerätebesitzer über die Kommandozeile ein Passwort aktivieren. Die Retrode3 sollte nicht ohne zusätzliche Absicherung aus dem öffentlichen Internet erreichbar sein.

## 2. Spiel auslesen

1. Stecke das Spielmodul in den passenden Cartridge-Slot oder kompatiblen Adapter.
2. Öffne **Modul auslesen**. Die Slot-Kacheln zeigen die vom Kernel gemeldete Belegung.
3. Falls genau ein unterstützter Ausleser zum belegten Slot passt, wird er vorgeschlagen. Beachte: Die Slot-Belegung allein identifiziert **nicht** das Cartridge-System oder den Adapter.
4. Klicke auf **Spielmodul erkennen**. Prüfe die erkannten Informationen.
5. Wähle **ROM auslesen**. Die Fortschrittsanzeige basiert auf tatsächlich geschriebenen Daten.
6. Warte auf die Erfolgsmeldung und öffne den **Dateimanager**.

**Wichtig:** Ziehe ein Modul während des Auslesens nicht heraus. Bei Lesefehlern oder ungewöhnlichen Modulen nicht blind andere Mapper oder Spannungen ausprobieren.

## 3. Erweiterte Einstellungen

Wenn das Modul nicht automatisch erkannt wird, kannst Du die erweiterten Einstellungen öffnen. Dort erscheinen nur Ausleser und Optionen, die vom installierten Backend tatsächlich unterstützt werden. Die manuelle Auswahl erkennt keine Adapter-ID und ist keine Aufforderung zu einem elektrischen Experiment. Noch nicht unterstützte Cartridge-Systeme können nicht durch bloßes Umschalten in der Weboberfläche aktiviert werden.

Die Ausleselogik wird künftig zentral über `retrode3-cli` mit den jeweiligen OSCR-Cores und Adaptern verbunden. Funktionen und unterstützte Systeme ändern sich daher im Verlauf der Entwicklung.

## 4. Dateien verwalten

Unter **Dateimanager** kannst Du ausgelesene ROMs ansehen, herunterladen, umbenennen, verschieben und löschen. Die neue Webablage befindet sich auf dem Gerät unter `/usr/local/games/ROMs/`, beispielsweise `ROMs/SNES/`.

Die Samba-Freigabe **retrode** gibt `/usr/local/games` frei. **Achtung:** Das derzeitige USB-Mass-Storage-Image ist davon noch getrennt. Dateien auf der Web-/Samba-Ablage erscheinen deshalb noch nicht automatisch im USB-Mass-Storage-Laufwerk. Niemals ein und dasselbe Dateisystem gleichzeitig auf Gerät und Host schreibend verwenden.

## 5. WLAN einrichten

Öffne **Allgemeine Einstellungen**. Dort findest Du WLAN-Status, den erkannten Interfacenamen, die IP-Adresse sowie Netzwerk-Suche und Verbindung.

- **Netzwerke suchen:** Zeigt verfügbare WLANs an, wenn der WLAN-Helper und das Gerät den Scan unterstützen.
- **Verbinden:** SSID auswählen beziehungsweise eintragen und gegebenenfalls das WLAN-Passwort angeben.
- **Trennen:** Beendet die vorhandene WLAN-Verbindung. Das kann die Netzwerkverbindung zum Browser unterbrechen.

Wenn die Seite **Kein WLAN-Adapter** meldet, prüfe auf dem Gerät zunächst `iw dev` und `ls /sys/class/net`. Die alte WLAN-Verwaltung benutzte ausschließlich `iwconfig` und kann ein vorhandenes Interface übersehen. Die neue Statusanzeige prüft zusätzlich `iw dev` und die Kernel-Schnittstellen. Wenn das Gerät erkannt wird, die Verbindung aber scheitert, prüfe die ausführliche Fehlermeldung und den installierten `retrode3-wlan`-Helper.

Für Fehlersuche per SSH:

```sh
iw dev
ls /sys/class/net
/usr/local/bin/retrode3-wlan status
service retrode3-web-v2 status
tail -n 50 /var/log/retrode3-web-v2.log
```

## 6. Unterstützte Funktionen und Einschränkungen

- **SNES:** Standard-LoROM/HiROM: Der aktuelle Web-Prototyp wurde bereits auf echter Hardware mit Fortschrittsanzeige erfolgreich getestet.
- **MegaDrive:** Ein nativer Standard-Linear-ROM-Leser wurde separat hardwaregetestet. Der Übergang zum gemeinsamen `retrode3-cli`-Protokoll läuft noch. Deshalb sind GUI-Unterstützung und automatisches Erkennen noch nicht vollständig.
- **NES und Adapter:** Je nach Core und Hardwarestand noch nicht über die neue Oberfläche verfügbar.
- **Schreiben:** Das Tab zum Beschreiben von Modulen ist nur vorbereitet. Cartridge-/SRAM-/Flash-Schreibzugriffe sind derzeit nicht über diesen Web-Prototyp freigeschaltet.
- **Spielerkennung:** Nicht jedes Spiel oder Spezialmodul lässt sich automatisch identifizieren. Ein angezeigter ROM-Header ist noch keine Datenbank-Verifizierung.

## 7. Quellcode, Updates und weitere Informationen

- [Retrode3-System und Weboberfläche](https://github.com/DragonBox-Shop/retrode3)
- [Ausleselogik und OSCR-Integration](https://github.com/DragonBox-Shop/retrode3-oscr)
- [Kernel-Treiber](https://github.com/DragonBox-Shop/retrode3-kernel)
- [Hardware und Adapter](https://github.com/DragonBox-Shop/retrode3-hardware)

Die vollständige Benutzeranleitung soll später im öffentlichen Retrode3-Wiki gepflegt werden. Der Online-Link in der Weboberfläche verweist bis dahin auf dieses Markdown-Dokument.
