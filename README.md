# AI Identifier Plugin für Picard

Dieses Plugin ergänzt MusicBrainz Picard um eine KI-basierte Genre-Erkennung für Musikdateien.

## Features
- Automatische Genre-Bestimmung per KI (Ollama/Mistral)
- Integration in den Picard-Workflow: Analyse nach Metadaten-Update
- Logging aller KI-Events und Ergebnisse

## Voraussetzungen
- MusicBrainz Picard (getestet mit 3.x)
- Python 3.12
- Lokaler KI-Worker (z. B. Ollama mit Mistral-Modell, erreichbar unter http://127.0.0.1:11435)
- Python-Paket: `requests`

## Installation
1. Plugin-Ordner `ai_identifier` in Picard-Plugins-Verzeichnis kopieren:
   ```
   ~/.config/MusicBrainz/Picard/plugins/ai_identifier
   ```
2. KI-Worker starten (siehe `aiid_ollama_worker.py` für Beispiel).
3. Picard neu starten und Plugin aktivieren.

## Funktionsweise
- Nach jedem Metadaten-Update eines Tracks wird automatisch eine Genre-Analyse per KI durchgeführt.
- Die Ergebnisse werden im Picard-Log und in der Plugin-Logdatei dokumentiert.

## Konfiguration
- KI-Worker-Adresse und Modell können im Plugin-Code angepasst werden.
- Logging erfolgt über `picard_logging.py`.

## Lizenz
MIT

## Autor
AI Assistant & bumblei3

---

**Hinweis:** Dieses Plugin befindet sich im experimentellen Status. Rückmeldungen und Verbesserungen sind willkommen!
