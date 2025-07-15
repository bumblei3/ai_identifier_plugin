# AI Music Identifier (Picard-Plugin)

**AI Music Identifier** ist ein Plugin für [MusicBrainz Picard](https://picard.musicbrainz.org/), das Musikdateien per AcoustID automatisch identifiziert und Metadaten (inkl. Genre, ISRC, Label, Tracknummer, Jahr, Cover, Komponist, u.v.m.) ergänzt. Zusätzlich nutzt es eine lokale KI (Ollama), um Genre- und Stimmungs-Vorschläge zu generieren. Das Plugin ist robust, performant und bietet viele Komfort- und Profi-Optionen.

---

## Features

- **Automatische Identifikation** von Musikdateien per AcoustID (Fingerprinting)
- **Metadaten-Ergänzung**: Genre, ISRC, Label, Tracknummer, Jahr, Cover-URL, Komponist, u.v.m.
- **KI-gestützte Genre- und Mood-Erkennung** (lokal, via Ollama)
- **Mehrsprachigkeit**: Alle Nutzertexte und Statusmeldungen auf Deutsch & Englisch
- **Cache** für KI-Ergebnisse (Ablaufzeit einstellbar, Cache kann geleert/deaktiviert werden)
- **Threading**: Alle zeitintensiven Aufgaben laufen im Hintergrund, Picard bleibt immer reaktionsfähig
- **Optionale Bestätigung** von KI-Vorschlägen (Dialog)
- **Automatische Auswahl** des ersten AcoustID-Treffers (Batch-Modus)
- **Ausführliches Logging** (inkl. Debug-Option)
- **Fehlerrobust**: Umfangreiche Fehlerbehandlung und Statusmeldungen

---

## Installation

1. **Voraussetzungen:**
   - MusicBrainz Picard 3.x
   - Python 3.12
   - [Ollama](https://ollama.com/) lokal installiert und laufend (für KI-Funktionen)
   - AcoustID-API-Key (kostenlos auf https://acoustid.org/)

2. **Plugin-Installation:**
   - Lege die Datei `ai_identifier.py` im Picard-Plugin-Ordner ab:
     - Linux: `~/.config/MusicBrainz/Picard/plugins/`
     - Windows: `%APPDATA%\MusicBrainz\Picard\plugins\`
   - Starte Picard neu und aktiviere das Plugin in den Einstellungen.

---

## Konfiguration

Im Picard-Optionsdialog findest du unter „Plugins → AI Music Identifier“ folgende Optionen:

- **AcoustID API-Key:** Dein persönlicher AcoustID-Schlüssel
- **Ersten Treffer automatisch wählen:** Aktiviert den Batch-Modus (keine manuelle Auswahl)
- **KI-Genre-Vorschlag aktivieren:** Nutzt die KI für Genre-Erkennung
- **KI-Stimmungsvorschlag aktivieren:** Nutzt die KI für Mood-Erkennung
- **KI-Cache verwenden:** Speichert KI-Ergebnisse für schnellere Verarbeitung
- **Cache-Ablaufzeit (Tage):** Wie lange KI-Ergebnisse gespeichert werden
- **KI-Vorschläge immer bestätigen lassen:** Zeigt immer einen Dialog zur Bestätigung
- **Ollama-Modell:** Wähle das gewünschte KI-Modell (z.B. mistral, llama2, phi, gemma)
- **Ollama-Server-URL:** Adresse deines lokalen Ollama-Servers (Standard: http://localhost:11434)
- **KI-Timeout (Sekunden):** Zeitlimit für KI-Anfragen
- **Ausführliches Debug-Logging aktivieren:** Schaltet detaillierte Log-Ausgaben ein
- **Cache leeren:** Löscht alle gespeicherten KI-Ergebnisse

---

## Hinweise zu KI & AcoustID

- **KI-Funktionen** benötigen einen laufenden Ollama-Server und ein geladenes Modell.
- **AcoustID** benötigt einen gültigen API-Key und eine Internetverbindung.
- **Nicht alle Dateien** können erkannt werden (z.B. seltene, neue oder stark bearbeitete Tracks).
- **KI-Genre/Mood** werden als zusätzliche Felder (`genre_ai`, `mood_ai`) gespeichert.

---

## Fehlerbehandlung & Logging

- Alle Fehler (z.B. Netzwerk, Timeout, keine Übereinstimmung) werden klar in der Statusleiste und im Log angezeigt.
- Bei KI-Timeouts oder Serverproblemen gibt es Tipps zur Behebung.
- Mit aktiviertem Debug-Logging werden alle Abläufe, Cache-Treffer und Thread-Status ausführlich geloggt.

---

## Bekannte Probleme & Tipps

- **Keine Übereinstimmung gefunden:**
  - Die Datei ist nicht in der AcoustID-Datenbank oder zu stark verändert.
  - Prüfe die Datei, verwende ggf. eine längere/bessere Version oder trage sie selbst bei AcoustID ein.
- **KI-Timeouts:**
  - Erhöhe das Timeout in den Optionen oder prüfe, ob Ollama korrekt läuft.
- **Abstürze durch QThread:**
  - In der aktuellen Version werden alle Worker korrekt verwaltet, sodass keine Abstürze mehr auftreten sollten.
- **Performance:**
  - Die Anzahl gleichzeitiger KI-Anfragen ist limitiert, um Ollama und das System zu schonen.

---

## Support & Weiterentwicklung

- Für Fragen, Fehlerberichte oder Feature-Wünsche: Bitte im GitHub-Repository ein Issue eröffnen oder direkt Kontakt aufnehmen.
- Die Entwicklung ist iterativ und nutzerzentriert – Feedback ist willkommen!

---

Viel Spaß beim automatisierten Tagging mit KI-Unterstützung! 🎶🤖 