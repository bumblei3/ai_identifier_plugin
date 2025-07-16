[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/dein-repo)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

# AI Music Identifier (Picard-Plugin)

**KI-gestütztes Tagging für MusicBrainz Picard – lokal, schnell, datenschutzfreundlich.**

---

## 🚀 Features (Überblick)
- **Automatische Musik-Erkennung** (AcoustID, Fingerprinting)
- **KI-Analyse (Ollama lokal):** Genre, Mood, Stil, Sprache, Subgenre, Emojis
- **Batch- & Parallelverarbeitung:** Asynchron, performant, dynamische Batch-Größe
- **Mehrsprachigkeit:** Deutsch & Englisch, adaptive Fehlermeldungen
- **Intelligentes Caching** & Undo/Redo
- **Workflow-Engine:** Automatisierung & Personalisierung
- **Robustes Logging & Fehlerhandling**
- **100% lokal, keine Cloud-Provider**

---

## ⚡️ Schnellstart

1. **Voraussetzungen:**
   - MusicBrainz Picard 3.x
   - Python 3.12+
   - [Ollama](https://ollama.com/) installiert & Modell geladen (z.B. `mistral`)
2. **Installation:**
   ```bash
   # Plugin kopieren
   cp -r ai_identifier ~/.config/MusicBrainz/Picard/plugins/
   # Optional: Abhängigkeiten für Audioanalyse
   pip install librosa soundfile
   ```
3. **Plugin aktivieren:**
   - Picard starten → Einstellungen → Plugins → AI Music Identifier aktivieren
4. **Ollama-Modell prüfen:**
   - Im Plugin-Menü Modell wählen (z.B. `mistral`)
   - Statusanzeige zeigt verfügbare Modelle

---

## 📝 Nutzung

- **Dateien/Alben in Picard laden**
- **"Batch Intelligence"-Button**: KI-Analyse für alle Songs
- **Vorschläge prüfen & übernehmen**
- **Workflows & Automatisierung**: Eigene Regeln im Workflow-Manager

---

## 🛠️ Troubleshooting

- **Ollama nicht gefunden?** → Prüfe, ob Ollama läuft (`ollama serve`)
- **Modell nicht installiert?** → `ollama pull mistral` (oder anderes Modell)
- **Fehlermeldung/Timeout?** → Batch-Größe reduzieren, Logs prüfen
- **Logs & Support:**
  - Logdatei: `~/.config/MusicBrainz/Picard/aiid_plugin.log`
  - Detaillierte Fehlerausgabe im Debug-Modus

---

## 👩‍💻 Für Entwickler

- **Tests:**
  - Asynchron, pytest + pytest-asyncio
  - Mocking für aiohttp, Picard, Qt
  - Ausführen: `pytest -v tests/`
- **Linter/Typisierung:**
  - pyright/mypy, keine Fehler im Hauptzweig
- **Konfiguration:**
  - Zentral in `ai_identifier/config.py`, alle Provider nutzen diese
- **Logging:**
  - Kontextbasiert, robust, mehrsprachig

---

## 📄 Lizenz & Beitrag

MIT-Lizenz. Beiträge willkommen! Siehe [CONTRIBUTING.md] und Issues.

---

**Viel Spaß beim intelligenten Musik-Tagging!** 🎶🤖 