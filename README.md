# AI Music Identifier (Picard-Plugin)

**AI Music Identifier** ist ein fortschrittliches Plugin für [MusicBrainz Picard](https://picard.musicbrainz.org/), das Musikdateien per AcoustID automatisch identifiziert und umfangreiche Metadaten ergänzt. Das Plugin nutzt moderne KI-Technologien für intelligente Musikanalyse, personalisierte Vorschläge und automatisierte Workflows.

---

## 🚀 Features

### **Kern-Funktionen**
- **Automatische Identifikation** von Musikdateien per AcoustID (Fingerprinting)
- **Umfassende Metadaten-Ergänzung**: Genre, ISRC, Label, Tracknummer, Jahr, Cover, Komponist, u.v.m.
- **Mehrsprachigkeit**: Vollständige Lokalisierung (Deutsch, Englisch, Französisch, Spanisch)

### **KI-gestützte Analyse**
- **Multi-Provider-KI-System**: OpenAI, HuggingFace, Ollama, Google, DeepL, AWS, Azure
- **Erweiterte KI-Felder**: Genre, Mood, Epoche, Stil, Instrumente, Emojis, Sprache
- **Audioanalyse**: Automatische BPM- und Tonart-Erkennung mit librosa
- **Lyrics-Generierung**: KI-basierte Lyrics-Erstellung mit API-Fallback
- **Cover-Art-Analyse**: KI-gestützte Beschreibung und Analyse von Album-Covern
- **Mood-Timeline**: Dynamische Stimmungsanalyse über die Songdauer mit Visualisierung
- **Genre-Hierarchie**: Intelligente Subgenre-Erkennung und hierarchische Strukturierung

### **Intelligente Workflows**
- **Smart Tagging**: KI-basierte Vorschläge basierend auf ähnlichen Songs
- **Batch-Intelligenz**: Analyse ganzer Batches mit Gruppierung ähnlicher Songs
- **Konfliktlösung**: Automatische Erkennung und KI-gestützte Lösung von Metadaten-Konflikten
- **Workflow-Engine**: Regelbasierte Automatisierung mit Bedingungen und Aktionen
- **Personalisierung**: Lernende Systeme, die sich an Nutzerpräferenzen anpassen

### **Erweiterte Funktionen**
- **Dubletten-Erkennung**: Intelligente Erkennung ähnlicher oder identischer Tracks
- **Cover-Erkennung**: Automatische Identifikation von Cover-Versionen
- **Filter- und Suchfunktionen**: Erweiterte Batch-Verarbeitung mit Filtern
- **Playlist-Vorschläge**: KI-generierte Playlist-Empfehlungen
- **Übersetzungsfunktionen**: Automatische Übersetzung von Metadaten
- **Feedback-System**: Lernende KI mit Nutzer-Feedback-Loop

### **Performance & Komfort**
- **Cache-Management**: Intelligentes Caching mit Ablaufzeiten und Statistiken
- **Threading**: Alle Aufgaben laufen im Hintergrund, Picard bleibt reaktionsfähig
- **Batch-Verarbeitung**: Optimierte Verarbeitung großer Dateimengen
- **Undo/Redo**: Rückgängig- und Wiederholen-Funktionen für Batch-Aktionen
- **Scheduler**: Automatische Aufgaben und geplante Analysen
- **Statistiken**: Detaillierte Auswertungen und Export-Funktionen

---

## 📋 Voraussetzungen

### **System-Anforderungen**
- MusicBrainz Picard 3.x
- Python 3.12+
- Mindestens 4GB RAM (für KI-Analysen)
- Internetverbindung (für AcoustID und KI-APIs)

### **KI-Provider (mindestens einer erforderlich)**
- **Ollama** (lokal, kostenlos): [ollama.com](https://ollama.com/)
- **OpenAI** (cloud): API-Key von [openai.com](https://openai.com/)
- **HuggingFace** (cloud): API-Key von [huggingface.co](https://huggingface.co/)
- **Google AI** (cloud): API-Key von Google Cloud
- **DeepL** (Übersetzungen): API-Key von [deepl.com](https://deepl.com/)

### **Zusätzliche APIs**
- **AcoustID-API-Key**: Kostenlos auf [acoustid.org](https://acoustid.org/)
- **Lyrics-APIs** (optional): Genius, Musixmatch, etc.

---

## 🔧 Installation

### **1. Plugin-Installation**
```bash
# Linux/macOS
cp ai_identifier.py ~/.config/MusicBrainz/Picard/plugins/

# Windows
copy ai_identifier.py "%APPDATA%\MusicBrainz\Picard\plugins\"
```

### **2. Abhängigkeiten installieren**
```bash
# Für Audioanalyse (optional, aber empfohlen)
pip install librosa soundfile

# Für erweiterte KI-Funktionen
pip install openai transformers torch
```

### **3. Plugin aktivieren**
- Picard neu starten
- Einstellungen → Plugins → AI Music Identifier aktivieren

---

## ⚙️ Konfiguration

### **Haupt-Einstellungen**
- **AcoustID API-Key**: Dein persönlicher AcoustID-Schlüssel
- **KI-Provider**: Auswahl und Konfiguration der bevorzugten KI-Services
- **Cache-Einstellungen**: Ablaufzeiten, Größenlimits, automatisches Leeren
- **Personalisierung**: Lernschwellenwerte, Feedback-Einstellungen

### **KI-Konfiguration**
- **Provider-Priorität**: Reihenfolge der KI-Services bei Ausfällen
- **Modell-Auswahl**: Spezifische Modelle pro Provider
- **Timeout-Einstellungen**: Zeitlimits für verschiedene Operationen
- **Confidence-Schwellenwerte**: Ab wann Feedback abgefragt wird

### **Workflow-Einstellungen**
- **Automatische Workflows**: Vordefinierte Regeln aktivieren/deaktivieren
- **Batch-Intelligenz**: Gruppierung und Konsistenzprüfung
- **Konfliktlösung**: Automatische vs. interaktive Konfliktbehandlung

---

## 🎯 Verwendung

### **Grundlegende Nutzung**
1. **Dateien laden**: Musikdateien in Picard ziehen
2. **Automatische Analyse**: Plugin analysiert automatisch alle Dateien
3. **Vorschläge prüfen**: KI-Vorschläge in Dialogen überprüfen
4. **Metadaten anwenden**: Gewünschte Tags übernehmen

### **Erweiterte Funktionen**
- **Batch-Intelligenz**: Nutze den "Batch Intelligence"-Button für Gruppenanalyse
- **Smart Tagging**: "Smart Tagging"-Button für KI-basierte Vorschläge
- **Konfliktlösung**: "Conflict Resolution"-Button bei Widersprüchen
- **Workflow-Manager**: Eigene Automatisierungsregeln erstellen

### **Feedback geben**
- Bei niedriger Confidence oder Ablehnung von Vorschlägen
- Über "Feedback geben"-Button für detailliertes Feedback
- Automatisches Lernen des Systems aus Nutzerverhalten

---

## 🔍 Fehlerbehandlung

### **Häufige Probleme**
- **Keine KI-Verbindung**: Provider-Status prüfen, API-Keys validieren
- **AcoustID-Fehler**: Internetverbindung und API-Key prüfen
- **Performance-Probleme**: Cache leeren, Thread-Anzahl anpassen
- **Memory-Fehler**: Batch-Größe reduzieren, weniger gleichzeitige Analysen

### **Debug-Modus**
- Aktiviert ausführliches Logging für detaillierte Fehleranalyse
- Cache-Statistiken und Performance-Metriken
- Provider-Status und Verbindungsdiagnose

---

## 🚀 Erweiterte Features

### **Personalisierung**
- **Lernende Systeme**: Das Plugin passt sich an deine Präferenzen an
- **Nutzerprofile**: Verschiedene Profile für unterschiedliche Musikrichtungen
- **Adaptive Vorschläge**: KI berücksichtigt dein Feedback bei neuen Analysen

### **Automatisierung**
- **Workflow-Engine**: Regelbasierte Automatisierung komplexer Aufgaben
- **Scheduler**: Geplante Analysen und Backups
- **Batch-Intelligenz**: Intelligente Verarbeitung großer Dateimengen

### **Community & Sharing**
- **Feedback-Export**: Teilen von Verbesserungsvorschlägen
- **Workflow-Sharing**: Austausch von Automatisierungsregeln
- **Statistik-Export**: Detaillierte Auswertungen für Berichte

---

## 📊 Statistiken & Monitoring

### **Performance-Metriken**
- Cache-Trefferquoten und Ladezeiten
- KI-Provider-Auslastung und Erfolgsraten
- Batch-Verarbeitungszeiten und Durchsatz

### **Qualitäts-Metriken**
- Feedback-Statistiken und Lernfortschritt
- Konfliktlösungs-Erfolgsraten
- Automatisierungs-Effektivität

---

## 🔮 Roadmap

### **Geplante Features**
- **Cloud-Synchronisation**: Einstellungen und Profile in der Cloud
- **Community-Features**: Austausch von Workflows und Feedback
- **Erweiterte Audioanalyse**: Stimm- und Instrumentenerkennung
- **Mobile Integration**: Companion-App für Remote-Steuerung

### **KI-Verbesserungen**
- **Lokale Modelle**: Optimierte lokale KI-Modelle
- **Ensemble-Methoden**: Kombination mehrerer KI-Systeme
- **Real-time Learning**: Kontinuierliche Verbesserung während der Nutzung

---

## 🤝 Support & Community

### **Hilfe & Dokumentation**
- **Detaillierte Dokumentation**: Alle Features und Einstellungen
- **Video-Tutorials**: Schritt-für-Schritt-Anleitungen
- **FAQ**: Häufige Fragen und Antworten

### **Feedback & Entwicklung**
- **Feature-Requests**: Neue Funktionen vorschlagen
- **Bug-Reports**: Probleme melden und beheben
- **Community-Forum**: Austausch mit anderen Nutzern

---

## 📄 Lizenz

Dieses Plugin steht unter der MIT-Lizenz und kann frei verwendet, modifiziert und weiterverbreitet werden.

---

**Viel Spaß beim intelligenten Musik-Tagging mit KI-Unterstützung! 🎶🤖✨** 

## Fehlerberichte & Logdatei

Falls es zu Problemen mit dem Plugin kommt, kannst du die Logdatei ganz einfach exportieren oder öffnen:

- **Logdatei exportieren:**  
  Öffne die Plugin-Einstellungen und klicke auf „Logdatei exportieren“. Du kannst die Datei dann an einen beliebigen Ort speichern und z. B. für Support-Anfragen anhängen.

- **Logdatei öffnen:**  
  Mit „Logdatei öffnen“ wird die Logdatei direkt im Standard-Editor deines Systems angezeigt.

Die Logdatei enthält alle wichtigen Informationen zur Fehlerdiagnose und hilft bei der schnellen Problemlösung. 