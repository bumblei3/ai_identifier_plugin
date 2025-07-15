# AI Music Identifier (Picard Plugin)

**AI Music Identifier** ist ein Plugin für [MusicBrainz Picard](https://picard.musicbrainz.org/), das Musikdateien automatisch per AcoustID-Fingerprinting identifiziert und mit umfangreichen Metadaten aus MusicBrainz anreichert.

## Features

- Automatische Identifikation von Musikdateien per AcoustID
- Ergänzt Metadaten wie Titel, Künstler, Album, Genre (mehrere), ISRC, Label, Tracknummer, Komponist, Jahr, Cover-Art-URL u.v.m.
- Auswahl zwischen mehreren Treffern (mit Cover und Jahr)
- Option für vollautomatische Verarbeitung (Batch-Modus)
- Caching der Metadaten (auch zwischen Sitzungen)
- Einstellungsseite direkt im Picard-Optionendialog (API-Key, Batch-Modus, Cache leeren)
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

2. **Optionen:**  
   - „Ersten Treffer automatisch wählen (Batch-Modus)“: Aktiviert die vollautomatische Verarbeitung ohne Dialoge.
   - „Cache leeren“: Löscht den gespeicherten Metadaten-Cache.

## Nutzung

- Ziehe Musikdateien in Picard und lasse sie vom Plugin identifizieren.
- Bei mehreren Treffern kannst du im Dialog den passenden auswählen (inkl. Cover und Jahr).
- Die Metadaten werden automatisch ergänzt und können wie gewohnt gespeichert werden.

## Voraussetzungen

- MusicBrainz Picard 3.x (getestet mit 3.0.0+)
- Python 3.12+
- PyQt6
- Die Python-Module: `musicbrainzngs`, `pyacoustid`, `hashlib`, `json`

## Hinweise

- Das Plugin funktioniert am besten mit vollständigen und gut erkennbaren Audiodateien.
- Für das Fingerprinting wird das Tool `fpcalc` benötigt (wird meist mit Picard installiert).
- Bei Problemen prüfe das Picard-Log (`--debug` starten).

## Lizenz

MIT License

---

**Fragen, Feedback oder Verbesserungen?**  
Erstelle ein Issue oder einen Pull Request auf GitHub! 