# AI Music Identifier (Picard Plugin)

**AI Music Identifier** ist ein Plugin für [MusicBrainz Picard](https://picard.musicbrainz.org/), das Musikdateien automatisch per AcoustID-Fingerprinting identifiziert und mit umfangreichen Metadaten aus MusicBrainz und KI-gestützten Vorschlägen anreichert.

## Features

- Automatische Identifikation von Musikdateien per AcoustID
- Ergänzt Metadaten wie Titel, Künstler, Album, Genre (mehrere), ISRC, Label, Tracknummer, Komponist, Jahr, Cover-Art-URL u.v.m.
- **KI-Genre-Vorschlag:** Erkennt fehlende Genres per lokalem Sprachmodell (Ollama, z.B. mistral, llama2, phi, gemma)
- **KI-Stimmungsvorschlag:** Erkennt die Stimmung („mood“) eines Songs per KI
- Vorschau-Dialog für KI-Vorschläge (Genre/Stimmung kann übernommen oder abgelehnt werden)
- Auswahl zwischen mehreren Treffern (mit Cover und Jahr)
- Option für vollautomatische Verarbeitung (Batch-Modus)
- Caching der Metadaten (auch zwischen Sitzungen, inkl. KI-Antworten)
- Einstellungsseite direkt im Picard-Optionendialog (API-Key, Batch-Modus, KI-Optionen, Cache leeren)
- Mehrsprachig (Deutsch/Englisch, automatische Umschaltung)

## Installation

1. Lade die Datei `ai_identifier.py` herunter und kopiere sie in dein Picard-Plugin-Verzeichnis:
   - Unter Linux: `~/.config/MusicBrainz/Picard/plugins/`
   - Unter Windows: `%APPDATA%\MusicBrainz\Picard\plugins\`
2. Starte Picard neu.
3. Aktiviere das Plugin unter „Optionen > Plugins“.

## Einrichtung

1. **AcoustID API-Key:**  
   - Erstelle einen kostenlosen API-Key auf [acoustid.org/api-key](https://acoustid.org/api-key).
   - Trage den Key in den Plugin-Einstellungen unter „Optionen > Plugins > AI Music Identifier“ ein.

2. **KI-Optionen:**  
   - **KI-Genre-Vorschlag aktivieren:** Lässt fehlende Genres per KI bestimmen.
   - **KI-Stimmungsvorschlag aktivieren:** Lässt die Stimmung per KI bestimmen.
   - **Ollama-Modell:** Wähle das gewünschte Sprachmodell (z.B. mistral, llama2, phi, gemma).
   - **Ollama-Server-URL:** Standard: `http://localhost:11434` (anpassbar für Remote-Server).
   - **KI-Timeout:** Zeitlimit für KI-Anfragen (z.B. 60 Sekunden).
   - **Cache leeren:** Löscht den gespeicherten Metadaten- und KI-Cache.

3. **Ollama installieren (für KI-Funktionen):**
   - [Ollama installieren](https://github.com/ollama/ollama) (einfacher Einzeiler für Linux/Mac/Windows)
   - Beispiel:
     ```bash
     curl -fsSL https://ollama.com/install.sh | sh
     ollama pull mistral
     ```
   - Ollama muss laufen, bevor Picard gestartet wird.

## Nutzung

- Ziehe Musikdateien in Picard und lasse sie vom Plugin identifizieren.
- Bei mehreren Treffern kannst du im Dialog den passenden auswählen (inkl. Cover und Jahr).
- Fehlt ein Genre oder eine Stimmung, schlägt die KI (nach Bestätigung) einen Wert vor.
- Die Metadaten werden automatisch ergänzt und können wie gewohnt gespeichert werden.

## Voraussetzungen

- MusicBrainz Picard 3.x (getestet mit 3.0.0+)
- Python 3.12+
- PyQt6
- Die Python-Module: `musicbrainzngs`, `pyacoustid`, `hashlib`, `json`, `requests`
- Für KI-Funktionen: [Ollama](https://github.com/ollama/ollama) (lokal oder remote)

## Hinweise

- Das Plugin funktioniert am besten mit vollständigen und gut erkennbaren Audiodateien.
- Für das Fingerprinting wird das Tool `fpcalc` benötigt (wird meist mit Picard installiert).
- Bei Problemen prüfe das Picard-Log (`--debug` starten).
- Die KI-Funktionen laufen komplett lokal (keine Cloud, keine Datenweitergabe).

## Lizenz

MIT License

---

**Fragen, Feedback oder Verbesserungen?**  
Erstelle ein Issue oder einen Pull Request auf GitHub! 