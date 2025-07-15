PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "bumblei3"
PLUGIN_DESCRIPTION = "Identifiziert Musikdateien per AcoustID und ergänzt Metadaten (inkl. Genre, ISRC, Label, Tracknummer)."
PLUGIN_VERSION = "0.9.1"
PLUGIN_API_VERSIONS = ["3.0"]

from picard import config, log
from picard.metadata import Metadata
import musicbrainzngs
import pyacoustid
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QPixmap, QIcon
from urllib.request import urlopen
from io import BytesIO
import hashlib
import os
import json
from picard.ui.options import OptionsPage
import requests
from picard.file import File
from picard.extension_points.event_hooks import register_file_post_load_processor
import time
from PyQt6.QtCore import QThreadPool, QRunnable, QObject, pyqtSignal, QUrl
from collections import deque
import threading
import glob
from PyQt6.QtGui import QDropEvent, QDragEnterEvent
from PyQt6.QtCore import QMimeData, QPointF
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# Globale Thread-Limitierung für KI-Worker
_MAX_KI_THREADS = 2
_active_ki_threads = 0
_ki_worker_queue = deque()

# Semaphore für parallele AcoustID-Lookups
_ACOUSTID_MAX_PARALLEL = 2
_acoustid_semaphore = threading.Semaphore(_ACOUSTID_MAX_PARALLEL)

# Chunk-Größe für Batch-Import (wie viele Dateien pro Block an Picard übergeben werden)
_CHUNK_SIZE = 20

def _on_ki_worker_finished(worker):
    global _active_ki_threads
    _active_ki_threads = max(0, _active_ki_threads - 1)
    if is_debug_logging():
        log.debug(f"AI Music Identifier: [Thread] KI-Worker beendet (aktiv: {_active_ki_threads})")
    # Starte nächsten Worker aus der Queue, falls vorhanden
    if _ki_worker_queue:
        next_worker = _ki_worker_queue.popleft()
        _start_ki_worker(next_worker)

def _start_ki_worker(worker):
    global _active_ki_threads
    if _active_ki_threads < _MAX_KI_THREADS:
        _active_ki_threads += 1
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [Thread] Starte KI-Worker (aktiv: {_active_ki_threads})")
        worker.finished.connect(lambda: _on_ki_worker_finished(worker))
        worker.start()
    else:
        _ki_worker_queue.append(worker)
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [Thread] KI-Worker in Warteschlange (Queue-Länge: {len(_ki_worker_queue)})")

_aiid_cache = {}

# Speicherort für den Cache (z.B. im Picard-Config-Verzeichnis)
_CACHE_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_cache.json")

# Standard-Ablaufzeit für Cache (in Tagen)
_DEFAULT_CACHE_EXPIRY_DAYS = 7

# Debug-Logging-Option
_DEBUG_LOGGING_KEY = "aiid_debug_logging"

def is_debug_logging():
    return bool(config.setting[_DEBUG_LOGGING_KEY]) if _DEBUG_LOGGING_KEY in config.setting else False

def _load_cache():
    global _aiid_cache
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                now = time.time()
                expiry_days = int(config.setting["aiid_cache_expiry_days"] or _DEFAULT_CACHE_EXPIRY_DAYS) if "aiid_cache_expiry_days" in config.setting else _DEFAULT_CACHE_EXPIRY_DAYS
                expiry_sec = expiry_days * 86400
                # Entferne abgelaufene Einträge
                for k, v in list(raw.items()):
                    if isinstance(v, dict) and "ts" in v:
                        if now - v["ts"] > expiry_sec:
                            continue  # abgelaufen
                        _aiid_cache[k] = v
                    else:
                        # Für alte Einträge ohne Zeitstempel: sofort ablaufen lassen
                        continue
    except Exception as e:
        log.warning("AI Music Identifier: Konnte Cache nicht laden: %s", e)

def _save_cache():
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_aiid_cache, f)
    except Exception as e:
        log.warning("AI Music Identifier: Konnte Cache nicht speichern: %s", e)

# Cache beim Laden des Plugins initialisieren
_load_cache()

# Globale Fehlerliste für Batch-Fehlerübersicht
_batch_errors = []

# Hole die Einstellung für automatische Auswahl
_DEF_AUTO_SELECT = False

def _get_auto_select():
    return config.setting["aiid_auto_select_first"] if "aiid_auto_select_first" in config.setting else _DEF_AUTO_SELECT

def _msg(de, en):
    # Einfache Sprachumschaltung
    import locale
    lang = locale.getdefaultlocale()[0]
    return de if lang and lang.startswith("de") else en

def _get_api_key():
    # Hole zuerst den Plugin-Key, dann den globalen Key
    if "aiid_acoustid_api_key" in config.setting and config.setting["aiid_acoustid_api_key"]:
        return config.setting["aiid_acoustid_api_key"]
    elif "acoustid_apikey" in config.setting and config.setting["acoustid_apikey"]:
        return config.setting["acoustid_apikey"]
    return ""

def call_ollama(prompt, model="mistral", tagger=None, file_name=None):
    url = str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434"
    url += "/api/generate"
    data = {"model": model, "prompt": prompt, "stream": False}
    timeout = int(config.setting["aiid_ollama_timeout"] or 60) if "aiid_ollama_timeout" in config.setting else 60
    if is_debug_logging():
        log.debug(f"AI Music Identifier: [KI-Request] Datei: {file_name}, Modell: {model}, URL: {url}, Timeout: {timeout}, Prompt: {prompt}")
    import time as _time
    start = _time.time()
    try:
        response = requests.post(url, json=data, timeout=timeout)
        elapsed = _time.time() - start
        if elapsed > 10:
            log.warning(_msg(f"AI Music Identifier: KI-Request dauerte ungewöhnlich lange: {elapsed:.1f}s (Datei: {file_name})", f"AI Music Identifier: AI request took unusually long: {elapsed:.1f}s (file: {file_name})"))
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [KI-Response] Datei: {file_name}, Dauer: {elapsed:.2f}s, Status: {response.status_code}")
        response.raise_for_status()
        result = response.json()["response"].strip()
        log.info(f"AI Music Identifier: Ollama-Antwort erhalten für Datei {file_name}: {result}")
        return result
    except requests.Timeout as e:
        msg = _msg(f"[Netzwerkfehler] KI-Timeout bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI timeout on Ollama request for file {file_name}: {e}")
        log.error(msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        return msg
    except requests.ConnectionError as e:
        msg = _msg(f"[Netzwerkfehler] KI-Netzwerkfehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI network error on Ollama request for file {file_name}: {e}")
        log.error(msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        return msg
    except requests.HTTPError as e:
        msg = _msg(f"[API-Fehler] HTTP-Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[API error] HTTP error on Ollama request for file {file_name}: {e}")
        log.error(msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        return msg
    except Exception as e:
        msg = _msg(f"[Lokaler Fehler] Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Local error] Error on Ollama request for file {file_name}: {e}")
        log.error(msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        return msg

class AIKIRunnable(QRunnable):
    def __init__(self, prompt, model, field, tagger=None):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.field = field  # "genre" oder "mood"
        self.tagger = tagger
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.field == "genre":
                result = call_ollama(self.prompt, self.model, self.tagger)
            elif self.field == "mood":
                result = call_ollama(self.prompt, self.model, self.tagger)
            else:
                result = None
            if result and "Fehler" not in result:
                self.signals.result_ready.emit(self.field, result)
            else:
                self.signals.error.emit(result or "Unbekannter Fehler", None)
        except Exception as e:
            self.signals.error.emit(str(e), None)

def get_genre_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"Welches Musikgenre hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit dem Genre, ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_genre::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Genre-Vorschlag aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Genre suggestion from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Genre, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Genre-Vorschlag wird berechnet...", "AI genre suggestion in progress..."))
    genre = call_ollama(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if genre and "Fehler" not in genre:
        log.info(f"AI Music Identifier: Genre-Vorschlag von KI für {title} - {artist}: {genre}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": genre, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Genre, Datei: {file_name}, Key: {cache_key}, Wert: {genre}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Genre-Vorschlag von KI für {title} - {artist}: {genre}", f"AI Music Identifier: No valid genre suggestion from AI for {title} - {artist}: {genre}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Genre-Fehler: {genre}", f"AI genre error: {genre}"))
    return genre

def show_genre_suggestion_dialog(parent, genre):
    # Prüfe, ob Bestätigung immer gewünscht ist
    confirm = bool(config.setting["aiid_confirm_ai"]) if "aiid_confirm_ai" in config.setting else False
    if not confirm:
        # Nur anzeigen, wenn mehrere Genres/Moods oder explizit gewünscht
        # (Hier: immer anzeigen, wenn confirm aktiv, sonst wie bisher)
        return True
    msg_box = QtWidgets.QMessageBox(parent)
    msg_box.setIcon(QtWidgets.QMessageBox.Icon.Question)
    msg_box.setWindowTitle(_msg("KI-Genre-Vorschlag", "AI Genre Suggestion"))
    msg_box.setText(_msg(f"Die KI schlägt folgendes Genre vor:\n<b>{genre}</b>\nÜbernehmen?", f"The AI suggests the following genre:\n<b>{genre}</b>\nAccept?"))
    msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
    return msg_box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

def get_mood_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"Welche Stimmung hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit einem Wort (z.B. fröhlich, melancholisch, energetisch)."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_mood::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Stimmungsvorschlag aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Mood suggestion from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Mood, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Stimmungsvorschlag wird berechnet...", "AI mood suggestion in progress..."))
    mood = call_ollama(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if mood and "Fehler" not in mood:
        log.info(f"AI Music Identifier: Stimmungsvorschlag von KI für {title} - {artist}: {mood}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": mood, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Mood, Datei: {file_name}, Key: {cache_key}, Wert: {mood}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Stimmungsvorschlag von KI für {title} - {artist}: {mood}", f"AI Music Identifier: No valid mood suggestion from AI for {title} - {artist}: {mood}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Stimmungs-Fehler: {mood}", f"AI mood error: {mood}"))
    return mood

def get_language_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"In welcher Sprache ist der Song '{title}' von '{artist}' gesungen? "
        "Antworte nur mit der Sprache (z.B. Deutsch, Englisch, Spanisch), ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_language::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    language = call_ollama(prompt, model, tagger, file_name)
    if language and "Fehler" not in language:
        if use_cache:
            _aiid_cache[cache_key] = {"value": language, "ts": time.time()}
            _save_cache()
    return language

def get_instruments_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"Welche Hauptinstrumente sind im Song '{title}' von '{artist}' zu hören? "
        "Antworte nur mit einer kommagetrennten Liste (z.B. Gitarre, Schlagzeug, Bass), ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_instruments::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    instruments = call_ollama(prompt, model, tagger, file_name)
    if instruments and "Fehler" not in instruments:
        if use_cache:
            _aiid_cache[cache_key] = {"value": instruments, "ts": time.time()}
            _save_cache()
    return instruments

def get_mood_emoji_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"Welches Emoji passt am besten zur Stimmung des Songs '{title}' von '{artist}'? "
        "Antworte nur mit einem Emoji, ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_mood_emoji::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    emoji = call_ollama(prompt, model, tagger, file_name)
    if emoji and "Fehler" not in emoji:
        if use_cache:
            _aiid_cache[cache_key] = {"value": emoji, "ts": time.time()}
            _save_cache()
    return emoji

class AIIDOptionsPage(OptionsPage):
    NAME = "ai_identifier"
    TITLE = "AI Music Identifier"
    PARENT = "plugins"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIIDOptionsPage")
        layout = QtWidgets.QVBoxLayout(self)

        # API-Key
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setToolTip(_msg(
            "Dein persönlicher Schlüssel für die Abfrage von AcoustID. Kostenlos auf acoustid.org erhältlich.",
            "Your personal key for querying AcoustID. Free at acoustid.org."
        ))
        layout.addWidget(QtWidgets.QLabel("AcoustID API-Key:"))
        layout.addWidget(self.api_key_edit)

        # Automatische Auswahl
        self.auto_select_checkbox = QtWidgets.QCheckBox(_msg("Ersten Treffer automatisch wählen (Batch-Modus)", "Automatically select first match (batch mode)"))
        self.auto_select_checkbox.setToolTip(_msg(
            "Wählt bei mehreren Treffern automatisch den ersten aus. Praktisch für große Mengen (Batch-Verarbeitung).",
            "Automatically selects the first match if multiple are found. Useful for batch processing."
        ))
        layout.addWidget(self.auto_select_checkbox)

        # KI-Genre-Vorschlag aktivieren
        self.ki_genre_checkbox = QtWidgets.QCheckBox(_msg("KI-Genre-Vorschlag aktivieren", "Enable AI genre suggestion"))
        self.ki_genre_checkbox.setToolTip(_msg(
            "Lässt die KI automatisch ein Genre vorschlagen und eintragen.",
            "Lets the AI automatically suggest and set a genre."
        ))
        layout.addWidget(self.ki_genre_checkbox)

        # KI-Cache verwenden
        self.cache_enable_checkbox = QtWidgets.QCheckBox(_msg("KI-Cache verwenden (empfohlen)", "Use AI cache (recommended)"))
        self.cache_enable_checkbox.setToolTip(_msg(
            "Speichert KI-Vorschläge für schnellere Verarbeitung und weniger Anfragen.",
            "Stores AI suggestions for faster processing and fewer requests."
        ))
        layout.addWidget(self.cache_enable_checkbox)

        # Ollama-Modell für KI-Vorschläge
        self.model_label = QtWidgets.QLabel(_msg("Ollama-Modell für KI-Vorschläge:", "Ollama model for AI suggestions:"))
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.addItems(["mistral", "llama2", "phi", "gemma"])
        self.model_combo.setToolTip(_msg(
            "Welches KI-Modell für Genre/Stimmung verwendet wird. 'mistral' ist meist ein guter Standard.",
            "Which AI model to use for genre/mood. 'mistral' is usually a good default."
        ))
        layout.addWidget(self.model_label)
        layout.addWidget(self.model_combo)

        # Ollama-Server-URL
        self.url_label = QtWidgets.QLabel(_msg("Ollama-Server-URL:", "Ollama server URL:"))
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setToolTip(_msg(
            "Adresse deines lokalen Ollama-Servers (z.B. http://localhost:11434)",
            "Address of your local Ollama server (e.g. http://localhost:11434)"
        ))
        layout.addWidget(self.url_label)
        layout.addWidget(self.url_edit)
        # Timeout
        self.timeout_label = QtWidgets.QLabel(_msg("KI-Timeout (Sekunden):", "AI timeout (seconds):"))
        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setToolTip(_msg(
            "Wie lange auf eine Antwort der KI gewartet wird, bevor abgebrochen wird.",
            "How long to wait for an AI response before timing out."
        ))
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.timeout_spin)
        # KI-Stimmung aktivieren
        self.ki_mood_checkbox = QtWidgets.QCheckBox(_msg("KI-Stimmungsvorschlag aktivieren", "Enable AI mood suggestion"))
        self.ki_mood_checkbox.setToolTip(_msg(
            "Lässt die KI eine Stimmung (Mood) vorschlagen und eintragen.",
            "Lets the AI suggest and set a mood."
        ))
        layout.addWidget(self.ki_mood_checkbox)

        # Cache-Ablaufzeit
        self.cache_expiry_label = QtWidgets.QLabel(_msg("Cache-Ablaufzeit (Tage):", "Cache expiry (days):"))
        self.cache_expiry_spin = QtWidgets.QSpinBox()
        self.cache_expiry_spin.setRange(1, 365)
        self.cache_expiry_spin.setToolTip(_msg(
            "Wie viele Tage KI-Vorschläge im Cache gespeichert werden.",
            "How many days AI suggestions are kept in the cache."
        ))
        layout.addWidget(self.cache_expiry_label)
        layout.addWidget(self.cache_expiry_spin)

        # Cache leeren
        self.clear_cache_btn = QtWidgets.QPushButton(_msg("Cache leeren", "Clear cache"))
        self.clear_cache_btn.setToolTip(_msg(
            "Löscht alle gespeicherten KI-Vorschläge aus dem Cache.",
            "Deletes all stored AI suggestions from the cache."
        ))
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        layout.addWidget(self.clear_cache_btn)

        # Fortschritt zurücksetzen
        self.reset_progress_btn = QtWidgets.QPushButton(_msg("Fortschritt zurücksetzen", "Reset progress"))
        self.reset_progress_btn.setToolTip(_msg(
            "Setzt alle Fortschrittszähler (Dateien verarbeitet, Fehler etc.) auf 0.",
            "Resets all progress counters (files processed, errors etc.) to 0."
        ))
        self.reset_progress_btn.clicked.connect(self.reset_progress)
        layout.addWidget(self.reset_progress_btn)

        # KI-Vorschläge immer bestätigen lassen
        self.ki_confirm_checkbox = QtWidgets.QCheckBox(_msg("KI-Vorschläge immer bestätigen lassen", "Always confirm AI suggestions"))
        self.ki_confirm_checkbox.setToolTip(_msg(
            "Zeigt jeden KI-Vorschlag zur Bestätigung an, bevor er übernommen wird.",
            "Shows every AI suggestion for confirmation before applying."
        ))
        layout.addWidget(self.ki_confirm_checkbox)

        # Debug-Logging aktivieren
        self.debug_logging_checkbox = QtWidgets.QCheckBox(_msg("Ausführliches Debug-Logging aktivieren", "Enable verbose debug logging"))
        self.debug_logging_checkbox.setToolTip(_msg(
            "Schreibt zusätzliche Debug-Informationen ins Log. Nur für Fehlersuche empfohlen!",
            "Writes additional debug information to the log. Recommended for troubleshooting only!"
        ))
        layout.addWidget(self.debug_logging_checkbox)

        # Ordner-Button für Automatisierung
        self.folder_btn = QtWidgets.QPushButton(_msg("Ordner verarbeiten...", "Process folder..."))
        self.folder_btn.setToolTip(_msg(
            "Wählt einen Ordner aus und fügt alle Musikdateien automatisch zur Verarbeitung hinzu.",
            "Selects a folder and adds all music files for processing automatically."
        ))
        self.folder_btn.clicked.connect(self.process_folder)
        layout.addWidget(self.folder_btn)

        # KI-Sprache erkennen
        self.ki_language_checkbox = QtWidgets.QCheckBox(_msg("KI-Sprache erkennen", "Enable AI language detection"))
        self.ki_language_checkbox.setToolTip(_msg(
            "Lässt die KI die Sprache des Songs erkennen und eintragen.",
            "Lets the AI detect and set the language of the song."
        ))
        layout.addWidget(self.ki_language_checkbox)
        # KI-Instrumente erkennen
        self.ki_instruments_checkbox = QtWidgets.QCheckBox(_msg("KI-Instrumente erkennen", "Enable AI instrument detection"))
        self.ki_instruments_checkbox.setToolTip(_msg(
            "Lässt die KI die wichtigsten Instrumente im Song erkennen und eintragen.",
            "Lets the AI detect and set the main instruments in the song."
        ))
        layout.addWidget(self.ki_instruments_checkbox)

        # KI-Stimmungs-Emoji erkennen
        self.ki_mood_emoji_checkbox = QtWidgets.QCheckBox(_msg("KI-Stimmungs-Emoji erkennen", "Enable AI mood emoji"))
        self.ki_mood_emoji_checkbox.setToolTip(_msg(
            "Lässt die KI ein passendes Emoji zur Stimmung des Songs erkennen und eintragen.",
            "Lets the AI detect and set a fitting emoji for the song's mood."
        ))
        layout.addWidget(self.ki_mood_emoji_checkbox)

        # Selbsttest-Button
        self.selftest_btn = QtWidgets.QPushButton(_msg("Selbsttest starten", "Run self-test"))
        self.selftest_btn.setToolTip(_msg(
            "Prüft, ob alle Abhängigkeiten, Server und KI-Modelle funktionieren.",
            "Checks if all dependencies, servers and AI models are working."
        ))
        self.selftest_btn.clicked.connect(self.run_selftest)
        layout.addWidget(self.selftest_btn)

        # Ressourcenmonitor
        if _HAS_PSUTIL:
            self.resource_label = QtWidgets.QLabel()
            self.resource_label.setToolTip(_msg(
                "Zeigt die aktuelle CPU- und RAM-Auslastung des Systems und des Picard-Prozesses.",
                "Shows current CPU and RAM usage of the system and the Picard process."
            ))
            layout.addWidget(self.resource_label)
            self._resource_timer = QtCore.QTimer(self)
            self._resource_timer.timeout.connect(self.update_resource_label)
            self._resource_timer.start(2000)
            self.update_resource_label()
        else:
            self.resource_label = QtWidgets.QLabel(_msg(
                "Hinweis: Für die Ressourcenanzeige muss das Python-Modul 'psutil' installiert sein.",
                "Note: For resource monitoring, the Python module 'psutil' must be installed."
            ))
            layout.addWidget(self.resource_label)

        layout.addStretch(1)
        self.setLayout(layout)

    def update_resource_label(self):
        if not _HAS_PSUTIL:
            return
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        proc = psutil.Process()
        cpu_count = psutil.cpu_count() or 1
        proc_cpu = proc.cpu_percent(interval=None) / cpu_count
        proc_mem = proc.memory_info().rss / (1024*1024)
        txt = _msg(
            f"System: CPU {cpu:.1f}%  RAM {ram:.1f}%\nPicard: CPU {proc_cpu:.1f}%  RAM {proc_mem:.1f} MB",
            f"System: CPU {cpu:.1f}%  RAM {ram:.1f}%\nPicard: CPU {proc_cpu:.1f}%  RAM {proc_mem:.1f} MB"
        )
        self.resource_label.setText(txt)

    def load(self):
        self.api_key_edit.setText(str(config.setting["aiid_acoustid_api_key"]) if "aiid_acoustid_api_key" in config.setting else "")
        self.auto_select_checkbox.setChecked(bool(config.setting["aiid_auto_select_first"]) if "aiid_auto_select_first" in config.setting else False)
        self.ki_genre_checkbox.setChecked(bool(config.setting["aiid_enable_ki_genre"]) if "aiid_enable_ki_genre" in config.setting else True)
        self.cache_enable_checkbox.setChecked(bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True)
        self.model_combo.setCurrentText(str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral")
        self.url_edit.setText(str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434")
        self.timeout_spin.setValue(int(config.setting["aiid_ollama_timeout"] or 60) if "aiid_ollama_timeout" in config.setting else 60)
        self.ki_mood_checkbox.setChecked(bool(config.setting["aiid_enable_ki_mood"]) if "aiid_enable_ki_mood" in config.setting else False)
        self.ki_confirm_checkbox.setChecked(bool(config.setting["aiid_confirm_ai"])
            if "aiid_confirm_ai" in config.setting else False)
        self.cache_expiry_spin.setValue(int(config.setting["aiid_cache_expiry_days"] or _DEFAULT_CACHE_EXPIRY_DAYS) if "aiid_cache_expiry_days" in config.setting else _DEFAULT_CACHE_EXPIRY_DAYS)
        self.debug_logging_checkbox.setChecked(bool(config.setting[_DEBUG_LOGGING_KEY]) if _DEBUG_LOGGING_KEY in config.setting else False)
        self.ki_language_checkbox.setChecked(bool("aiid_enable_ki_language" in config.setting and config.setting["aiid_enable_ki_language"]))
        self.ki_instruments_checkbox.setChecked(bool("aiid_enable_ki_instruments" in config.setting and config.setting["aiid_enable_ki_instruments"]))
        self.ki_mood_emoji_checkbox.setChecked(bool("aiid_enable_ki_mood_emoji" in config.setting and config.setting["aiid_enable_ki_mood_emoji"]))

    def save(self):
        config.setting["aiid_acoustid_api_key"] = self.api_key_edit.text().strip()
        config.setting["aiid_auto_select_first"] = self.auto_select_checkbox.isChecked()
        config.setting["aiid_enable_ki_genre"] = self.ki_genre_checkbox.isChecked()
        config.setting["aiid_enable_cache"] = self.cache_enable_checkbox.isChecked()
        config.setting["aiid_ollama_model"] = self.model_combo.currentText()
        config.setting["aiid_ollama_url"] = self.url_edit.text().strip()
        config.setting["aiid_ollama_timeout"] = self.timeout_spin.value()
        config.setting["aiid_enable_ki_mood"] = self.ki_mood_checkbox.isChecked()
        config.setting["aiid_confirm_ai"] = self.ki_confirm_checkbox.isChecked()
        config.setting["aiid_cache_expiry_days"] = self.cache_expiry_spin.value()
        config.setting[_DEBUG_LOGGING_KEY] = self.debug_logging_checkbox.isChecked()
        config.setting["aiid_enable_ki_language"] = self.ki_language_checkbox.isChecked()
        config.setting["aiid_enable_ki_instruments"] = self.ki_instruments_checkbox.isChecked()
        config.setting["aiid_enable_ki_mood_emoji"] = self.ki_mood_emoji_checkbox.isChecked()

    def clear_cache(self):
        global _aiid_cache
        _aiid_cache.clear()
        _save_cache()
        QtWidgets.QMessageBox.information(self, _msg("Info", "Info"), _msg("Cache wurde geleert.", "Cache cleared."))

    def reset_progress(self):
        global _total_files, _finished_files, _success_files, _error_files
        _total_files = 0
        _finished_files = 0
        _success_files = 0
        _error_files = 0
        QtWidgets.QMessageBox.information(self, _msg("Info", "Info"), _msg("Fortschrittszähler wurden zurückgesetzt.", "Progress counters have been reset."))

    def process_folder(self):
        # Verzeichnisauswahl
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, _msg("Ordner auswählen", "Select folder"))
        if not folder:
            return
        # Unterstützte Dateitypen
        exts = ["mp3", "flac", "ogg", "wav"]
        files = []
        for ext in exts:
            files.extend(glob.glob(os.path.join(folder, f"**/*.{ext}"), recursive=True))
        if not files:
            QtWidgets.QMessageBox.information(self, _msg("Keine Musikdateien gefunden", "No music files found"), _msg("Im gewählten Ordner wurden keine unterstützten Musikdateien gefunden.", "No supported music files found in the selected folder."))
            return
        # Fortschrittsdialog mit Abbrechen
        progress = QtWidgets.QProgressDialog(_msg("Dateien werden hinzugefügt...", "Adding files..."), _msg("Abbrechen", "Cancel"), 0, len(files), self)
        progress.setWindowTitle(_msg("Fortschritt", "Progress"))
        progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        # Dateien wie Drag&Drop an Picard übergeben, aber in Blöcken (Chunks)
        from picard.ui.mainwindow import MainWindow
        mw = None
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                mw = widget
                break
        added = 0
        if mw:
            for chunk_start in range(0, len(files), _CHUNK_SIZE):
                if progress.wasCanceled():
                    break
                chunk = files[chunk_start:chunk_start+_CHUNK_SIZE]
                mime = QMimeData()
                urls = [QUrl.fromLocalFile(f) for f in chunk]
                mime.setUrls(urls)
                drop_event = QDropEvent(QPointF(mw.mapToGlobal(mw.rect().center())), QtCore.Qt.DropAction.CopyAction, mime, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
                QtWidgets.QApplication.sendEvent(mw, drop_event)
                added += len(chunk)
                progress.setValue(added)
                QtWidgets.QApplication.processEvents()
                # Kurze Pause, damit Picard die Dateien laden kann (z.B. 0.5s)
                QtCore.QThread.msleep(500)
            if added < len(files):
                QtWidgets.QMessageBox.information(self, _msg("Abgebrochen", "Cancelled"), _msg(f"Vorgang abgebrochen. {added} von {len(files)} Dateien wurden hinzugefügt.", f"Operation cancelled. {added} of {len(files)} files were added."))
            else:
                QtWidgets.QMessageBox.information(self, _msg("Dateien hinzugefügt", "Files added"), _msg(f"{added} Musikdateien wurden zur Verarbeitung hinzugefügt.", f"{added} music files have been added for processing."))
        else:
            QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), _msg("Konnte das Hauptfenster nicht finden. Bitte Dateien manuell hinzufügen.", "Could not find main window. Please add files manually."))

    def show_error_dialog(self, title, short_msg, details=None):
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(short_msg)
        if details:
            msg_box.setDetailedText(details)
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def run_selftest(self):
        import sys
        results = []
        # Python-Version
        results.append(("Python-Version", sys.version, sys.version_info >= (3, 7)))
        # PyQt-Version
        try:
            from PyQt6.QtCore import QT_VERSION_STR
            pyqt_version = QT_VERSION_STR
            results.append(("PyQt-Version", pyqt_version, True))
        except Exception as e:
            results.append(("PyQt-Version", str(e), False))
        # Abhängigkeiten
        for mod, name in [("pyacoustid", "pyacoustid"), ("musicbrainzngs", "musicbrainzngs"), ("requests", "requests")]:
            try:
                __import__(mod)
                results.append((f"{name} installiert", "OK", True))
            except Exception as e:
                results.append((f"{name} installiert", str(e), False))
        # Chromaprint-Backend
        try:
            fp_version = getattr(pyacoustid, '__version__', 'unbekannt')
            results.append(("pyacoustid-Version", fp_version, True))
        except Exception as e:
            results.append(("pyacoustid-Version", str(e), False))
        # AcoustID-API-Key
        api_key = config.setting["aiid_acoustid_api_key"] if "aiid_acoustid_api_key" in config.setting else ""
        if api_key:
            results.append(("AcoustID API-Key", "OK", True))
            # Test-Request
            try:
                # Dummy-Fingerprint (wird Fehler geben, aber API erreichbar?)
                r = requests.get("https://api.acoustid.org/v2/userinfo", params={"client": api_key}, timeout=5)
                if r.status_code == 200:
                    results.append(("AcoustID API erreichbar", "OK", True))
                else:
                    results.append(("AcoustID API erreichbar", f"Status {r.status_code}", False))
            except Exception as e:
                results.append(("AcoustID API erreichbar", str(e), False))
        else:
            results.append(("AcoustID API-Key", _msg("Nicht gesetzt", "Not set"), False))
        # Ollama-Server
        ollama_url = str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434"
        try:
            r = requests.get(ollama_url + "/api/tags", timeout=5)
            if r.status_code == 200:
                results.append(("Ollama-Server erreichbar", "OK", True))
                # Modelle prüfen
                try:
                    tags = r.json().get("models") or r.json().get("tags") or []
                    if tags:
                        results.append(("Ollama-Modelle gefunden", ", ".join([str(t) for t in tags]), True))
                    else:
                        results.append(("Ollama-Modelle gefunden", _msg("Keine Modelle gefunden", "No models found"), False))
                except Exception as e:
                    results.append(("Ollama-Modelle gefunden", str(e), False))
            else:
                results.append(("Ollama-Server erreichbar", f"Status {r.status_code}", False))
        except Exception as e:
            results.append(("Ollama-Server erreichbar", str(e), False))
        # Cache-Schreibrechte
        try:
            test_path = _CACHE_PATH + ".test"
            with open(test_path, "w", encoding="utf-8") as f:
                f.write("test")
            os.remove(test_path)
            results.append(("Cache-Schreibrechte", "OK", True))
        except Exception as e:
            results.append(("Cache-Schreibrechte", str(e), False))
        # ThreadPool-Status
        try:
            from PyQt6.QtCore import QThreadPool
            pool = QThreadPool.globalInstance()
            if pool is not None:
                results.append(("ThreadPool aktiv", f"maxThreadCount={pool.maxThreadCount()}", True))
            else:
                results.append(("ThreadPool aktiv", "None", False))
        except Exception as e:
            results.append(("ThreadPool aktiv", str(e), False))
        # Ergebnis anzeigen
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(_msg("Selbsttest-Ergebnis", "Self-test result"))
        layout = QtWidgets.QVBoxLayout(dlg)
        for label, value, ok in results:
            l = QtWidgets.QLabel()
            l.setText(f"<b>{label}:</b> {value}")
            l.setStyleSheet(f"color: {'green' if ok else 'red'};")
            layout.addWidget(l)
        btn = QtWidgets.QPushButton(_msg("Schließen", "Close"))
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.setLayout(layout)
        dlg.exec()

OPTIONS_PAGE_CLASS = AIIDOptionsPage

def select_result_dialog(results, parent=None):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(_msg("AcoustID-Treffer auswählen", "Select AcoustID Match"))
    layout = QtWidgets.QVBoxLayout(dialog)
    label = QtWidgets.QLabel(_msg("Mehrere Treffer gefunden. Bitte wählen:", "Multiple matches found. Please select:"))
    layout.addWidget(label)
    list_widget = QtWidgets.QListWidget()
    for result in results:
        title = result.get("title", "–")
        artists = ", ".join([a.get("name", "") for a in result.get("artists", [])]) if "artists" in result else ""
        album = result.get("releasegroups", [{}])[0].get("title", "") if "releasegroups" in result and result["releasegroups"] else ""
        # Jahr extrahieren
        year = ""
        if "releasegroups" in result and result["releasegroups"]:
            first_release = result["releasegroups"][0]
            year = first_release.get("first-release-date", "")[:4] if first_release.get("first-release-date") else ""
        # Label extrahieren
        label = ""
        if "recordings" in result and result["recordings"]:
            rec = result["recordings"][0]
            if "release-list" in rec and rec["release-list"]:
                rel = rec["release-list"][0]
                if "label-info-list" in rel and rel["label-info-list"]:
                    label = rel["label-info-list"][0].get("label", {}).get("name", "")
        # ISRC extrahieren
        isrc = ""
        if "recordings" in result and result["recordings"]:
            rec = result["recordings"][0]
            if "isrcs" in rec and rec["isrcs"]:
                isrc = rec["isrcs"][0]
        # Cover-URL extrahieren (sofern vorhanden)
        cover_url = None
        if "releasegroups" in result and result["releasegroups"]:
            first_release = result["releasegroups"][0]
            mbid = first_release.get("id")
            if mbid:
                cover_url = f"https://coverartarchive.org/release-group/{mbid}/front-250"
        # Text für die Zeile
        item_text = f"{title} – {artists} [{album}]"
        if year:
            item_text += f" ({year})"
        if label:
            item_text += f" | Label: {label}"
        item = QtWidgets.QListWidgetItem(item_text)
        # Cover als Icon laden (optional)
        style = QtWidgets.QApplication.style()
        if cover_url:
            try:
                response = urlopen(cover_url)
                data = response.read()
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                icon = QIcon(pixmap)
                item.setIcon(icon)
            except Exception:
                # Platzhalter-Icon bei Fehler
                if style:
                    item.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
        else:
            # Platzhalter-Icon, wenn kein Cover
            if style:
                item.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
        # ISRC als Tooltip
        if isrc:
            item.setToolTip(f"ISRC: {isrc}")
        list_widget.addItem(item)
    layout.addWidget(list_widget)
    button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(button_box)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    dialog.setLayout(layout)
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and list_widget.currentRow() >= 0:
        return list_widget.currentRow()
    return None

def fetch_additional_metadata(result, metadata, on_mb_details=None):
    # Genre
    if "tags" in result and not metadata.get("genre"):
        tags = result["tags"]
        genres = []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict) and "name" in tag:
                    genres.append(tag["name"])
                elif isinstance(tag, str):
                    genres.append(tag)
        elif isinstance(tags, dict) and "name" in tags:
            genres.append(tags["name"])
        if genres:
            metadata["genre"] = "; ".join(genres)
            log.info(_msg(f"AI Music Identifier: Genre ergänzt: {metadata['genre']}", f"AI Music Identifier: Genre added: {metadata['genre']}"))
    # Komponist(en)
    if "recordings" in result and result["recordings"]:
        rec = result["recordings"][0]
        if "artist-credit" in rec:
            composers = []
            for ac in rec["artist-credit"]:
                if isinstance(ac, dict) and ac.get("artist", {}).get("type") == "Composer":
                    composers.append(ac["artist"].get("name"))
            if composers and not metadata.get("composer"):
                metadata["composer"] = "; ".join(composers)
                log.info(_msg(f"AI Music Identifier: Komponist ergänzt: {metadata['composer']}", f"AI Music Identifier: Composer added: {metadata['composer']}"))
    # Jahr (first-release-date)
    if "releasegroups" in result and result["releasegroups"]:
        first_release = result["releasegroups"][0]
        year = first_release.get("first-release-date", "")[:4] if first_release.get("first-release-date") else ""
        if year and not metadata.get("date"):
            metadata["date"] = year
            log.info(_msg(f"AI Music Identifier: Jahr ergänzt: {metadata['date']}", f"AI Music Identifier: Year added: {metadata['date']}"))
    # Cover-Art-URL
    if "releasegroups" in result and result["releasegroups"]:
        first_release = result["releasegroups"][0]
        mbid = first_release.get("id")
        if mbid and not metadata.get("coverart_url"):
            cover_url = f"https://coverartarchive.org/release-group/{mbid}/front"
            metadata["coverart_url"] = cover_url
            log.info(_msg(f"AI Music Identifier: Cover-Art-URL ergänzt: {cover_url}", f"AI Music Identifier: Cover art URL added: {cover_url}"))
    # ISRC
    if "recordings" in result and result["recordings"]:
        rec = result["recordings"][0]
        if "isrcs" in rec and rec["isrcs"] and not metadata.get("isrc"):
            metadata["isrc"] = rec["isrcs"][0]
            log.info(_msg(f"AI Music Identifier: ISRC ergänzt: {metadata['isrc']}", f"AI Music Identifier: ISRC added: {metadata['isrc']}"))
    # Label, Tracknummer asynchron holen
    if "recordings" in result and result["recordings"]:
        mbid = result["recordings"][0].get("id")
        if mbid and on_mb_details:
            worker = MBDetailWorker(mbid, metadata, on_mb_details)
            _threadpool.start(worker)

class WorkerSignals(QObject):
    result_ready = pyqtSignal(dict, object)  # (Metadaten, File-Objekt)
    error = pyqtSignal(str, object)  # (Fehlermeldung, File-Objekt)

class AIIDFullRunnable(QRunnable):
    def __init__(self, file, tagger=None):
        super().__init__()
        self.file = file
        self.tagger = tagger
        self.signals = WorkerSignals()

    def run(self):
        try:
            file = self.file
            tagger = self.tagger
            metadata = getattr(file, 'metadata', None)
            api_key = _get_api_key()
            if not api_key:
                msg = _msg("Bitte AcoustID API-Key in den Plugin-Einstellungen setzen.", "Please set AcoustID API key in the plugin settings.")
                self.signals.error.emit(msg, file)
                return
            # Caching: Hash über Dateipfad + Größe
            try:
                file_hash = hashlib.sha1((file.filename + str(file.size)).encode("utf-8")).hexdigest()
            except Exception:
                file_hash = None
            use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
            if use_cache and file_hash and file_hash in _aiid_cache:
                cached = _aiid_cache[file_hash]
                if metadata:
                    metadata.update(cached)
                    self.signals.result_ready.emit(dict(metadata), file)
                else:
                    self.signals.result_ready.emit({}, file)
                return
            # AcoustID-Lookup limitiert per Semaphore
            with _acoustid_semaphore:
                try:
                    duration, fp = pyacoustid.fingerprint_file(file.filename)
                    results = pyacoustid.lookup(api_key, fp, duration)
                except pyacoustid.WebServiceError as e:
                    msg = _msg(f"[API-Fehler] AcoustID API-Fehler für {file.filename}: {e}", f"[API error] AcoustID API error for {file.filename}: {e}")
                    self.signals.error.emit(msg, file)
                    return
                except pyacoustid.NoBackendError:
                    msg = _msg("[Lokaler Fehler] Chromaprint-Backend nicht gefunden. Bitte libchromaprint installieren.", "[Local error] Chromaprint backend not found. Please install libchromaprint.")
                    self.signals.error.emit(msg, file)
                    return
                except pyacoustid.FingerprintGenerationError:
                    msg = _msg(f"[Lokaler Fehler] Fehler beim Fingerprinting von {file.filename}", f"[Local error] Failed to fingerprint {file.filename}")
                    self.signals.error.emit(msg, file)
                    return
                except Exception as e:
                    msg = _msg(f"[Netzwerkfehler] Fehler beim AcoustID-Lookup für {file.filename}: {e}", f"[Network error] Error during AcoustID lookup for {file.filename}: {e}")
                    self.signals.error.emit(msg, file)
                    return
            if results and 'results' in results and len(results['results']) > 0:
                acoustid_results = results['results']
                idx = 0
                if len(acoustid_results) > 1 and not _get_auto_select():
                    idx = 0
                result = acoustid_results[idx]
                if metadata is not None:
                    metadata["title"] = result.get("title", metadata.get("title", ""))
                    artists = result.get("artists", [{}])
                    metadata["artist"] = artists[0].get("name", metadata.get("artist", "")) if artists else metadata.get("artist", "")
                    release_groups = result.get("releasegroups", [{}])
                    metadata["album"] = release_groups[0].get("title", metadata.get("album", "")) if release_groups else metadata.get("album", "")
                    def on_mb_details(label, tracknumber, meta):
                        if label and not meta.get("label"):
                            meta["label"] = label
                            log.info(_msg(f"AI Music Identifier: Label ergänzt: {label}", f"AI Music Identifier: Label added: {label}"))
                        if tracknumber and not meta.get("tracknumber"):
                            meta["tracknumber"] = tracknumber
                            log.info(_msg(f"AI Music Identifier: Tracknummer ergänzt: {tracknumber}", f"AI Music Identifier: Track number added: {tracknumber}"))
                        self.signals.result_ready.emit(dict(meta), file)
                    fetch_additional_metadata(result, metadata, on_mb_details=on_mb_details)
                    # Ergebnis wird jetzt erst im Callback weitergegeben!
                    return
            else:
                # Fallback: Prüfe, ob im File-Tag eine AcoustID vorhanden ist
                acoustid_id = None
                if metadata and "acoustid_id" in metadata:
                    acoustid_id = metadata["acoustid_id"]
                elif hasattr(file, 'metadata') and file.metadata and "acoustid_id" in file.metadata:
                    acoustid_id = file.metadata["acoustid_id"]
                if isinstance(acoustid_id, list) and acoustid_id:
                    acoustid_id = acoustid_id[0]
                if isinstance(acoustid_id, str) and acoustid_id:
                    try:
                        # Hole Recording-Infos von MusicBrainz
                        mb_url = f"https://musicbrainz.org/ws/2/recording?query=acoustidid:{acoustid_id}&inc=releases+artists+isrcs+tags&fmt=json"
                        resp = requests.get(mb_url, timeout=10)
                        resp.raise_for_status()
                    except requests.Timeout as e:
                        msg = _msg(f"[Netzwerkfehler] Timeout bei MusicBrainz-Request für {file.filename}: {e}", f"[Network error] Timeout on MusicBrainz request for {file.filename}: {e}")
                        self.signals.error.emit(msg, file)
                        return
                    except requests.ConnectionError as e:
                        msg = _msg(f"[Netzwerkfehler] Netzwerkfehler bei MusicBrainz-Request für {file.filename}: {e}", f"[Network error] Network error on MusicBrainz request for {file.filename}: {e}")
                        self.signals.error.emit(msg, file)
                        return
                    except requests.HTTPError as e:
                        msg = _msg(f"[API-Fehler] HTTP-Fehler bei MusicBrainz-Request für {file.filename}: {e}", f"[API error] HTTP error on MusicBrainz request for {file.filename}: {e}")
                        self.signals.error.emit(msg, file)
                        return
                    except Exception as e:
                        msg = _msg(f"[Lokaler Fehler] Fehler bei MusicBrainz-Request für {file.filename}: {e}", f"[Local error] Error on MusicBrainz request for {file.filename}: {e}")
                        self.signals.error.emit(msg, file)
                        return
        except pyacoustid.NoBackendError:
            msg = _msg("Chromaprint-Backend nicht gefunden. Bitte libchromaprint installieren.", "Chromaprint backend not found. Please install libchromaprint.")
            self.signals.error.emit(msg, self.file)
        except pyacoustid.FingerprintGenerationError:
            msg = _msg("Fehler beim Fingerprinting von %s", "Failed to fingerprint %s") % self.file.filename
            self.signals.error.emit(msg, self.file)
        except pyacoustid.WebServiceError as e:
            msg = _msg("AcoustID API-Fehler für %s", "AcoustID API error for %s") % self.file.filename
            self.signals.error.emit(msg, self.file)
        except Exception as e:
            msg = _msg("Fehler bei der Verarbeitung von %s", "Error processing %s") % self.file.filename
            self.signals.error.emit(f"{msg}: {e}", self.file)

# Zentraler ThreadPool für alle Aufgaben
# Dynamische Thread-Anzahl: mindestens 2, maximal 8 oder so viele Kerne wie vorhanden
_THREADPOOL_MAX = min(max(os.cpu_count() or 2, 2), 8)
_threadpool = QThreadPool()
_threadpool.setMaxThreadCount(_THREADPOOL_MAX)
log.info(f"AI Music Identifier: ThreadPool verwendet {_THREADPOOL_MAX} Threads (CPU-Kerne: {os.cpu_count()})")

_active_workers = []  # Referenzen auf laufende Worker, damit sie nicht vorzeitig zerstört werden

# Fortschrittszähler für Batch-Verarbeitung
_total_files = 0
_finished_files = 0
_success_files = 0
_error_files = 0

# Für Status-Update-Throttling
_last_status_update = 0
_STATUS_UPDATE_INTERVAL = 0.2  # Sekunden

# Adaptive Parallelität: Fehler-Tracking
_ADAPTIVE_PARALLEL_WINDOW = 30  # Sekunden
_ADAPTIVE_PARALLEL_ERROR_THRESHOLD = 5  # Fehler im Zeitfenster, ab dann reduzieren
_ADAPTIVE_PARALLEL_MIN = 2
_ADAPTIVE_PARALLEL_MAX = _THREADPOOL_MAX
_error_timestamps = []
_last_parallel_increase = 0

def _adaptive_parallel_check():
    global _error_timestamps, _threadpool, _THREADPOOL_MAX, _last_parallel_increase
    import time as _time
    now = _time.time()
    # Entferne alte Fehler
    _error_timestamps = [t for t in _error_timestamps if now - t < _ADAPTIVE_PARALLEL_WINDOW]
    # Zu viele Fehler? Reduziere Parallelität
    if len(_error_timestamps) >= _ADAPTIVE_PARALLEL_ERROR_THRESHOLD and _threadpool.maxThreadCount() > _ADAPTIVE_PARALLEL_MIN:
        new_count = max(_ADAPTIVE_PARALLEL_MIN, _threadpool.maxThreadCount() - 1)
        _threadpool.setMaxThreadCount(new_count)
        log.warning(f"AI Music Identifier: Zu viele Fehler/Timeouts ({len(_error_timestamps)} in {_ADAPTIVE_PARALLEL_WINDOW}s) – Parallelität reduziert auf {new_count}.")
    # Wenn längere Zeit keine Fehler, erhöhe langsam wieder
    elif len(_error_timestamps) == 0 and _threadpool.maxThreadCount() < _ADAPTIVE_PARALLEL_MAX and now - _last_parallel_increase > _ADAPTIVE_PARALLEL_WINDOW:
        new_count = min(_ADAPTIVE_PARALLEL_MAX, _threadpool.maxThreadCount() + 1)
        _threadpool.setMaxThreadCount(new_count)
        log.info(f"AI Music Identifier: Parallelität wieder erhöht auf {new_count}.")
        _last_parallel_increase = now

def _show_batch_error_dialog(parent=None):
    if not _batch_errors:
        return
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(_msg("Fehlerübersicht (Batch)", "Batch Error Summary"))
    layout = QtWidgets.QVBoxLayout(dlg)
    total = _total_files if '_total_files' in globals() else len(_batch_errors)
    label = QtWidgets.QLabel(_msg(f"{len(_batch_errors)} Fehler bei {total} Dateien:", f"{len(_batch_errors)} errors for {total} files:"))
    layout.addWidget(label)
    search_layout = QtWidgets.QHBoxLayout()
    search_edit = QtWidgets.QLineEdit()
    search_edit.setPlaceholderText(_msg("Fehler filtern...", "Filter errors..."))
    search_edit.setToolTip(_msg("Gib einen Suchbegriff ein, um die Fehlerliste zu filtern (Dateiname, Emoji oder Fehlertext).", "Enter a search term to filter the error list (filename, emoji or error text)."))
    search_layout.addWidget(search_edit)
    layout.addLayout(search_layout)
    # Prüfe, ob mindestens ein Fehler ein Emoji enthält
    has_emoji = any(len(e) == 3 and e[2] for e in _batch_errors)
    col_count = 3 if has_emoji else 2
    table = QtWidgets.QTableWidget(len(_batch_errors), col_count)
    headers = [_msg("Datei", "File")]
    if has_emoji:
        headers.append(_msg("Emoji", "Emoji"))
    headers.append(_msg("Fehler", "Error"))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    if header is not None:
        header.setStretchLastSection(True)
        table.setSortingEnabled(True)
    for row, entry in enumerate(_batch_errors):
        filename = entry[0]
        errmsg = entry[1]
        emoji = entry[2] if len(entry) > 2 else ""
        table.setItem(row, 0, QtWidgets.QTableWidgetItem(filename))
        col = 1
        if has_emoji:
            table.setItem(row, col, QtWidgets.QTableWidgetItem(emoji))
            col += 1
        table.setItem(row, col, QtWidgets.QTableWidgetItem(errmsg))
    layout.addWidget(table)
    def filter_table():
        term = search_edit.text().lower()
        for row in range(table.rowCount()):
            texts = []
            for c in range(table.columnCount()):
                item = table.item(row, c)
                texts.append(item.text().lower() if item is not None else "")
            show = any(term in t for t in texts)
            table.setRowHidden(row, not show)
    search_edit.textChanged.connect(filter_table)
    btn_layout = QtWidgets.QHBoxLayout()
    copy_btn = QtWidgets.QPushButton(_msg("Fehler als Text kopieren", "Copy errors as text"))
    copy_btn.setToolTip(_msg("Kopiert alle Fehler als Text in die Zwischenablage.", "Copy all errors as text to clipboard."))
    def copy_errors():
        lines = []
        for entry in _batch_errors:
            if len(entry) == 3:
                lines.append(f"{entry[0]} {entry[2]}: {entry[1]}")
            else:
                lines.append(f"{entry[0]}: {entry[1]}")
        text = "\n".join(lines)
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
    copy_btn.clicked.connect(copy_errors)
    btn_layout.addWidget(copy_btn)
    save_btn = QtWidgets.QPushButton(_msg("Fehler als Datei speichern", "Save errors as file"))
    save_btn.setToolTip(_msg("Speichert alle Fehler als Textdatei (TXT).", "Save all errors as a text file (TXT)."))
    def save_errors():
        lines = []
        for entry in _batch_errors:
            if len(entry) == 3:
                lines.append(f"{entry[0]} {entry[2]}: {entry[1]}")
            else:
                lines.append(f"{entry[0]}: {entry[1]}")
        text = "\n".join(lines)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(dlg, _msg("Fehler speichern", "Save errors"), "errors.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    save_btn.clicked.connect(save_errors)
    btn_layout.addWidget(save_btn)
    close_btn = QtWidgets.QPushButton(_msg("Schließen", "Close"))
    close_btn.setToolTip(_msg("Schließt die Fehlerübersicht.", "Close the error summary."))
    close_btn.clicked.connect(dlg.accept)
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)
    dlg.setLayout(layout)
    dlg.exec()
    _batch_errors.clear()

def _update_progress_status(tagger=None):
    global _last_status_update
    import time as _time
    now = _time.time()
    # Immer sofort aktualisieren, wenn fertig
    if _total_files > 0 and (_finished_files == _total_files or now - _last_status_update > _STATUS_UPDATE_INTERVAL):
        msg = f"AI Music Identifier: {_finished_files}/{_total_files} Dateien verarbeitet ({_success_files} erfolgreich, {_error_files} Fehler/Timeouts)"
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            # Batch-Fehlerübersicht am Ende anzeigen
            if _finished_files == _total_files and _total_files > 1 and _batch_errors:
                _show_batch_error_dialog(tagger.window)
        else:
            log.info(msg)
        _last_status_update = now

def file_post_load_processor(file):
    global _total_files, _finished_files, _success_files, _error_files
    tagger = getattr(file, 'tagger', None)
    metadata = getattr(file, 'metadata', None)
    # Zähler zurücksetzen, wenn ein neuer Batch gestartet wird
    if _finished_files == _total_files and _total_files > 0:
        _total_files = 0
        _finished_files = 0
        _success_files = 0
        _error_files = 0
    _total_files += 1
    _update_progress_status(tagger)
    def on_worker_result(new_metadata, file_obj):
        global _finished_files, _success_files
        _finished_files += 1
        _success_files += 1
        _update_progress_status(tagger)
        _adaptive_parallel_check()
        if metadata is not None:
            metadata.update(new_metadata)
        # KI-Genre/Mood wie gehabt (im Hauptthread, inkl. Dialoge und Thread-Limitierung)
        def after_genre(field, genre):
            if metadata is None:
                log.error(_msg("AI Music Identifier: Metadaten-Objekt fehlt beim Speichern des KI-Genres!", "AI Music Identifier: Metadata object missing when saving AI genre!"))
                if tagger and hasattr(tagger, 'window'):
                    tagger.window.set_statusbar_message(_msg("Fehler: Metadaten konnten nicht gespeichert werden.", "Error: Could not save metadata."))
                return
            genres = []
            if metadata.get("genre"):
                genres = [g.strip() for g in metadata["genre"].split(";") if g.strip()]
            if genre and genre not in genres:
                genres.append(genre)
                metadata["genre_ai"] = genre
                log.info(_msg(f"AI Music Identifier: KI-Genre als 'genre_ai' gespeichert: {genre}", f"AI Music Identifier: KI genre saved as 'genre_ai': {genre}"))
                log.info(_msg("AI Music Identifier: Genre per Ollama übernommen: %s", "AI Music Identifier: Genre from Ollama accepted: %s") % genre)
            # Speichere alle Genres (ohne Duplikate, sauber getrennt)
            if genres:
                metadata["genre"] = "; ".join(sorted(set(genres), key=genres.index))
            # Jetzt ggf. Mood-Worker starten
            start_mood_worker()
        def after_mood(field, mood):
            if metadata is None:
                log.error(_msg("AI Music Identifier: Metadaten-Objekt fehlt beim Speichern der KI-Stimmung!", "AI Music Identifier: Metadata object missing when saving AI mood!"))
                if tagger and hasattr(tagger, 'window'):
                    tagger.window.set_statusbar_message(_msg("Fehler: Metadaten konnten nicht gespeichert werden.", "Error: Could not save metadata."))
                return
            metadata["mood_ai"] = mood
            metadata["mood"] = mood
            log.info(_msg(f"AI Music Identifier: KI-Stimmung als 'mood_ai' gespeichert: {mood}", f"AI Music Identifier: KI mood saved as 'mood_ai': {mood}"))
            log.info(_msg("AI Music Identifier: Stimmung per Ollama übernommen: %s", "AI Music Identifier: Mood from Ollama accepted: %s") % mood)
            # Jetzt ggf. Language-Worker starten
            start_language_worker()
        def after_language():
            if metadata is not None and ("aiid_enable_ki_language" in config.setting and config.setting["aiid_enable_ki_language"]):
                language = get_language_suggestion(metadata.get('title', ''), metadata.get('artist', ''), tagger, file.filename)
                if language and "Fehler" not in language:
                    metadata["language_ai"] = language
                    log.info(_msg(f"AI Music Identifier: KI-Sprache als 'language_ai' gespeichert: {language}", f"AI Music Identifier: AI language saved as 'language_ai': {language}"))
            # Jetzt ggf. Instruments-Worker starten
            start_instruments_worker()
        def after_instruments():
            if metadata is not None and ("aiid_enable_ki_instruments" in config.setting and config.setting["aiid_enable_ki_instruments"]):
                instruments = get_instruments_suggestion(metadata.get('title', ''), metadata.get('artist', ''), tagger, file.filename)
                if instruments and "Fehler" not in instruments:
                    metadata["instruments_ai"] = instruments
                    log.info(_msg(f"AI Music Identifier: KI-Instrumente als 'instruments_ai' gespeichert: {instruments}", f"AI Music Identifier: AI instruments saved as 'instruments_ai': {instruments}"))
            # Cache speichern
            file_hash = hashlib.sha1((file.filename + str(file.size)).encode("utf-8")).hexdigest() if file.filename and hasattr(file, 'size') else None
            use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
            if use_cache and file_hash and metadata is not None:
                _aiid_cache[file_hash] = dict(metadata)
                _save_cache()
            msg = _msg("Metadaten aktualisiert für %s", "Updated metadata for %s") % file.filename
            if tagger and hasattr(tagger, 'window'):
                tagger.window.set_statusbar_message(msg)
            log.debug("AI Music Identifier: Updated metadata: %s", metadata)
        def on_error(msg, file_obj):
            log.warning("AI Music Identifier: Fehler bei KI-Anfrage für Datei %s: %s", getattr(file_obj, 'filename', 'unbekannt'), msg)
            if tagger and hasattr(tagger, 'window'):
                tagger.window.set_statusbar_message(msg)
        def start_genre_worker():
            if metadata is not None and (bool(config.setting["aiid_enable_ki_genre"]) if "aiid_enable_ki_genre" in config.setting else True):
                genres = []
                if metadata.get("genre"):
                    genres = [g.strip() for g in metadata["genre"].split(";") if g.strip()]
                if not genres:
                    log.info(_msg("AI Music Identifier: Starte KI-Genre-Vorschlag für Datei: %s", "AI Music Identifier: Starting AI genre suggestion for file: %s") % file.filename)
                    prompt = (
                        f"Welches Musikgenre hat der Song '{metadata.get('title', '')}' von '{metadata.get('artist', '')}'? "
                        "Antworte nur mit dem Genre, ohne weitere Erklärungen."
                    )
                    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
                    runnable = AIKIRunnable(prompt, model, "genre", tagger)
                    runnable.signals.result_ready.connect(after_genre)
                    runnable.signals.error.connect(on_error)
                    _threadpool.start(runnable)
                    return
            # Wenn kein Genre-Worker nötig, direkt Mood-Worker starten
            start_mood_worker()
        def start_mood_worker():
            if metadata is not None and (bool(config.setting["aiid_enable_ki_mood"]) if "aiid_enable_ki_mood" in config.setting else False):
                log.info(_msg("AI Music Identifier: Starte KI-Stimmungsvorschlag für Datei: %s", "AI Music Identifier: Starting AI mood suggestion for file: %s") % file.filename)
                prompt = (
                    f"Welche Stimmung hat der Song '{metadata.get('title', '')}' von '{metadata.get('artist', '')}'? "
                    "Antworte nur mit einem Wort (z.B. fröhlich, melancholisch, energetisch)."
                )
                model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
                runnable = AIKIRunnable(prompt, model, "mood", tagger)
                runnable.signals.result_ready.connect(after_mood)
                runnable.signals.error.connect(on_error)
                _threadpool.start(runnable)
                return
            # Wenn kein Mood-Worker nötig, Language-Worker starten
            start_language_worker()
        def start_language_worker():
            if metadata is not None and ("aiid_enable_ki_language" in config.setting and config.setting["aiid_enable_ki_language"]):
                after_language()
            else:
                start_instruments_worker()
        def start_instruments_worker():
            if metadata is not None and ("aiid_enable_ki_instruments" in config.setting and config.setting["aiid_enable_ki_instruments"]):
                after_instruments()
            else:
                # Cache speichern
                file_hash = hashlib.sha1((file.filename + str(file.size)).encode("utf-8")).hexdigest() if file.filename and hasattr(file, 'size') else None
                use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
                if use_cache and file_hash and metadata is not None:
                    _aiid_cache[file_hash] = dict(metadata)
                    _save_cache()
                msg = _msg("Metadaten aktualisiert für %s", "Updated metadata for %s") % file.filename
                if tagger and hasattr(tagger, 'window'):
                    tagger.window.set_statusbar_message(msg)
                log.debug("AI Music Identifier: Updated metadata: %s", metadata)
        # Starte KI-Worker-Kette
        start_genre_worker()
    def on_worker_error(msg, file_obj):
        global _finished_files, _error_files, _error_timestamps, _batch_errors
        _finished_files += 1
        _error_files += 1
        import time as _time
        _error_timestamps.append(_time.time())
        filename = getattr(file_obj, 'filename', 'unbekannt')
        # Emoji aus Metadaten, falls vorhanden
        emoji = ""
        if hasattr(file_obj, 'metadata') and file_obj.metadata and "mood_emoji_ai" in file_obj.metadata:
            emoji = file_obj.metadata["mood_emoji_ai"]
        _batch_errors.append((filename, str(msg), emoji))
        _update_progress_status(tagger)
        _adaptive_parallel_check()
        # Benutzerfreundliche Fehlerausgabe
        if "AcoustID" in msg or "keine Übereinstimmung" in msg or "No match" in msg:
            user_msg = msg + _msg(
                "\nDu kannst die Datei über Picard und MusicBrainz als neuen Release eintragen. Nach dem Speichern wird der Fingerprint automatisch an AcoustID übertragen. Mehr Infos: https://acoustid.org/ und https://musicbrainz.org/doc/How_to_Add_a_Release",
                "\nYou can add the file as a new release via Picard and MusicBrainz. After saving, the fingerprint will be automatically submitted to AcoustID. More info: https://acoustid.org/ and https://musicbrainz.org/doc/How_to_Add_a_Release"
            )
        elif "Timeout" in msg or "timeout" in msg:
            user_msg = _msg(
                f"KI-Timeout: Die Anfrage an den Ollama-Server hat zu lange gedauert. Tipp: Timeout in den Plugin-Optionen erhöhen oder Server prüfen. ({msg})",
                f"AI timeout: The request to the Ollama server took too long. Tip: Increase timeout in plugin options or check server. ({msg})"
            )
        elif "Netzwerk" in msg or "network" in msg:
            user_msg = _msg(
                f"KI-Netzwerkfehler: Keine Verbindung zum Ollama-Server. Läuft der Server? ({msg})",
                f"AI network error: Could not connect to Ollama server. Is the server running? ({msg})"
            )
        else:
            user_msg = msg
        log.warning("AI Music Identifier: Fehler im Hintergrund-Worker für Datei %s: %s", getattr(file_obj, 'filename', 'unbekannt'), user_msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(user_msg)
        # Erweiterte Fehleranzeige als Dialog
        parent = getattr(tagger, 'window', None)
        title = _msg("Fehler", "Error")
        short_msg = user_msg.split("\n")[0] if "\n" in user_msg else user_msg
        details = user_msg if short_msg != user_msg else None
        # Nur Dialog anzeigen, wenn Einzeldatei oder explizit gewünscht
        if _total_files <= 1:
            if parent and hasattr(parent, "show_error_dialog"):
                parent.show_error_dialog(title, short_msg, details)
            else:
                # Fallback: Standard-Fehlerdialog anzeigen
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
                msg_box.setWindowTitle(title)
                msg_box.setText(short_msg)
                if details:
                    msg_box.setDetailedText(details)
                msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
                msg_box.exec()
        # Bei Batch-Verarbeitung (mehrere Dateien): kein Popup, nur Status/Log
    # Starte den FullRunnable im ThreadPool
    runnable = AIIDFullRunnable(file, tagger)
    runnable.signals.result_ready.connect(on_worker_result)
    runnable.signals.error.connect(on_worker_error)
    _threadpool.start(runnable)

register_file_post_load_processor(file_post_load_processor)
OPTIONS_PAGE_CLASS = AIIDOptionsPage

# Worker für MusicBrainz-Detailabfrage (Label, Tracknummer)
class MBDetailWorker(QRunnable):
    def __init__(self, mbid, metadata, callback):
        super().__init__()
        self.mbid = mbid
        self.metadata = metadata
        self.callback = callback  # Funktion, die das Ergebnis verarbeitet
    def run(self):
        try:
            release = musicbrainzngs.get_recording_by_id(self.mbid, includes=["releases", "isrcs", "artist-credits", "tags"])
            release_list = release["recording"].get("release-list", [])
            label = None
            tracknumber = None
            if release_list:
                rel = release_list[0]
                # Label
                if "label-info-list" in rel and rel["label-info-list"]:
                    label = rel["label-info-list"][0].get("label", {}).get("name")
                # Tracknummer
                if "medium-list" in rel and rel["medium-list"]:
                    tracks = rel["medium-list"][0].get("track-list", [])
                    if tracks:
                        tracknumber = tracks[0].get("number")
            self.callback(label, tracknumber, self.metadata)
        except musicbrainzngs.MusicBrainzError as e:
            self.callback(None, None, self.metadata)

