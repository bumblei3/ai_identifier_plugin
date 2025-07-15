PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "Dein Name"
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
from PyQt6.QtCore import QThread, pyqtSignal
from collections import deque

# Globale Thread-Limitierung für KI-Worker
_MAX_KI_THREADS = 2
_active_ki_threads = 0
_ki_worker_queue = deque()

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
        log.error(_msg(f"AI Music Identifier: Timeout bei Ollama-Anfrage für Datei {file_name}: {e}", f"AI Music Identifier: Timeout on Ollama request for file {file_name}: {e}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Timeout: {e}", f"AI timeout: {e}"))
        return f"Fehler bei Ollama-Anfrage (Timeout): {e}"
    except requests.ConnectionError as e:
        log.error(_msg(f"AI Music Identifier: Netzwerkfehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"AI Music Identifier: Network error on Ollama request for file {file_name}: {e}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Netzwerkfehler: {e}", f"AI network error: {e}"))
        return f"Fehler bei Ollama-Anfrage (Netzwerk): {e}"
    except Exception as e:
        log.error(_msg(f"AI Music Identifier: Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"AI Music Identifier: Error on Ollama request for file {file_name}: {e}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Fehler: {e}", f"AI error: {e}"))
        return f"Fehler bei Ollama-Anfrage: {e}"

class AIWorker(QThread):
    result_ready = pyqtSignal(str, str)  # (Feldname, Wert)
    error = pyqtSignal(str)

    def __init__(self, prompt, model, field, tagger=None):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.field = field  # "genre" oder "mood"
        self.tagger = tagger

    def run(self):
        try:
            if self.field == "genre":
                result = call_ollama(self.prompt, self.model, self.tagger)
            elif self.field == "mood":
                result = call_ollama(self.prompt, self.model, self.tagger)
            else:
                result = None
            if result and "Fehler" not in result:
                self.result_ready.emit(self.field, result)
            else:
                self.error.emit(result or "Unbekannter Fehler")
        except Exception as e:
            self.error.emit(str(e))

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
        layout.addWidget(QtWidgets.QLabel("AcoustID API-Key:"))
        layout.addWidget(self.api_key_edit)

        # Automatische Auswahl
        self.auto_select_checkbox = QtWidgets.QCheckBox(_msg("Ersten Treffer automatisch wählen (Batch-Modus)", "Automatically select first match (batch mode)"))
        layout.addWidget(self.auto_select_checkbox)

        # KI-Genre-Vorschlag aktivieren
        self.ki_genre_checkbox = QtWidgets.QCheckBox(_msg("KI-Genre-Vorschlag aktivieren", "Enable AI genre suggestion"))
        layout.addWidget(self.ki_genre_checkbox)

        # KI-Cache verwenden
        self.cache_enable_checkbox = QtWidgets.QCheckBox(_msg("KI-Cache verwenden (empfohlen)", "Use AI cache (recommended)"))
        layout.addWidget(self.cache_enable_checkbox)

        # Ollama-Modell für KI-Vorschläge
        self.model_label = QtWidgets.QLabel(_msg("Ollama-Modell für KI-Vorschläge:", "Ollama model for AI suggestions:"))
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.addItems(["mistral", "llama2", "phi", "gemma"])
        layout.addWidget(self.model_label)
        layout.addWidget(self.model_combo)

        # Ollama-Server-URL
        self.url_label = QtWidgets.QLabel(_msg("Ollama-Server-URL:", "Ollama server URL:"))
        self.url_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.url_label)
        layout.addWidget(self.url_edit)
        # Timeout
        self.timeout_label = QtWidgets.QLabel(_msg("KI-Timeout (Sekunden):", "AI timeout (seconds):"))
        self.timeout_spin = QtWidgets.QSpinBox()
        self.timeout_spin.setRange(5, 300)
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.timeout_spin)
        # KI-Stimmung aktivieren
        self.ki_mood_checkbox = QtWidgets.QCheckBox(_msg("KI-Stimmungsvorschlag aktivieren", "Enable AI mood suggestion"))
        layout.addWidget(self.ki_mood_checkbox)

        # Cache-Ablaufzeit
        self.cache_expiry_label = QtWidgets.QLabel(_msg("Cache-Ablaufzeit (Tage):", "Cache expiry (days):"))
        self.cache_expiry_spin = QtWidgets.QSpinBox()
        self.cache_expiry_spin.setRange(1, 365)
        layout.addWidget(self.cache_expiry_label)
        layout.addWidget(self.cache_expiry_spin)

        # Cache leeren
        self.clear_cache_btn = QtWidgets.QPushButton(_msg("Cache leeren", "Clear cache"))
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        layout.addWidget(self.clear_cache_btn)

        # KI-Vorschläge immer bestätigen lassen
        self.ki_confirm_checkbox = QtWidgets.QCheckBox(_msg("KI-Vorschläge immer bestätigen lassen", "Always confirm AI suggestions"))
        layout.addWidget(self.ki_confirm_checkbox)

        # Debug-Logging aktivieren
        self.debug_logging_checkbox = QtWidgets.QCheckBox(_msg("Ausführliches Debug-Logging aktivieren", "Enable verbose debug logging"))
        layout.addWidget(self.debug_logging_checkbox)

        layout.addStretch(1)
        self.setLayout(layout)

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

    def clear_cache(self):
        global _aiid_cache
        _aiid_cache.clear()
        _save_cache()
        QtWidgets.QMessageBox.information(self, _msg("Info", "Info"), _msg("Cache wurde geleert.", "Cache cleared."))

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

def fetch_additional_metadata(result, metadata):
    # Genre
    if "tags" in result and not metadata.get("genre"):
        tags = result["tags"]
        genres = []
        if isinstance(tags, list):
            # Liste von Tags (z.B. [{'name': 'Rock'}, {'name': 'Pop'}] oder ['Rock', 'Pop'])
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
    # Label, Tracknummer
    if "recordings" in result and result["recordings"]:
        mbid = result["recordings"][0].get("id")
        if mbid:
            try:
                release = musicbrainzngs.get_recording_by_id(mbid, includes=["releases", "isrcs", "artist-credits", "tags"])
                release_list = release["recording"].get("release-list", [])
                if release_list:
                    rel = release_list[0]
                    # Label
                    if "label-info-list" in rel and rel["label-info-list"]:
                        label = rel["label-info-list"][0].get("label", {}).get("name")
                        if label and not metadata.get("label"):
                            metadata["label"] = label
                            log.info(_msg(f"AI Music Identifier: Label ergänzt: {label}", f"AI Music Identifier: Label added: {label}"))
                    # Tracknummer
                    if "medium-list" in rel and rel["medium-list"]:
                        tracks = rel["medium-list"][0].get("track-list", [])
                        if tracks and not metadata.get("tracknumber"):
                            metadata["tracknumber"] = tracks[0].get("number")
                            log.info(_msg(f"AI Music Identifier: Tracknummer ergänzt: {metadata['tracknumber']}", f"AI Music Identifier: Track number added: {metadata['tracknumber']}"))
            except musicbrainzngs.MusicBrainzError as e:
                log.warning("AI Music Identifier: Failed to fetch extended MusicBrainz data for MBID %s: %s", mbid, e)

class AIIDFullWorker(QThread):
    result_ready = pyqtSignal(dict, object)  # (Metadaten, File-Objekt)
    error = pyqtSignal(str, object)  # (Fehlermeldung, File-Objekt)

    def __init__(self, file, tagger=None):
        super().__init__()
        self.file = file
        self.tagger = tagger

    def run(self):
        try:
            file = self.file
            tagger = self.tagger
            metadata = getattr(file, 'metadata', None)
            api_key = _get_api_key()
            if not api_key:
                msg = _msg("Bitte AcoustID API-Key in den Plugin-Einstellungen setzen.", "Please set AcoustID API key in the plugin settings.")
                self.error.emit(msg, file)
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
                    self.result_ready.emit(dict(metadata), file)
                else:
                    self.result_ready.emit({}, file)
                return
            # Fingerprint & Lookup
            duration, fp = pyacoustid.fingerprint_file(file.filename)
            results = pyacoustid.lookup(api_key, fp, duration)
            if results and 'results' in results and len(results['results']) > 0:
                acoustid_results = results['results']
                # Automatische Auswahl oder Dialog (nur im Hauptthread möglich!)
                idx = 0
                if len(acoustid_results) > 1 and not _get_auto_select():
                    # Dialog kann nicht im Worker-Thread angezeigt werden, daher immer ersten nehmen
                    idx = 0
                result = acoustid_results[idx]
                # Metadaten übernehmen
                if metadata is not None:
                    metadata["title"] = result.get("title", metadata.get("title", ""))
                    artists = result.get("artists", [{}])
                    metadata["artist"] = artists[0].get("name", metadata.get("artist", "")) if artists else metadata.get("artist", "")
                    release_groups = result.get("releasegroups", [{}])
                    metadata["album"] = release_groups[0].get("title", metadata.get("album", "")) if release_groups else metadata.get("album", "")
                    fetch_additional_metadata(result, metadata)
                    self.result_ready.emit(dict(metadata), file)
                else:
                    self.result_ready.emit({}, file)
            else:
                msg = _msg("Keine Übereinstimmung gefunden für %s", "No matches found for %s") % file.filename
                self.error.emit(msg, file)
        except pyacoustid.NoBackendError:
            msg = _msg("Chromaprint-Backend nicht gefunden. Bitte libchromaprint installieren.", "Chromaprint backend not found. Please install libchromaprint.")
            self.error.emit(msg, self.file)
        except pyacoustid.FingerprintGenerationError:
            msg = _msg("Fehler beim Fingerprinting von %s", "Failed to fingerprint %s") % self.file.filename
            self.error.emit(msg, self.file)
        except pyacoustid.WebServiceError as e:
            msg = _msg("AcoustID API-Fehler für %s", "AcoustID API error for %s") % self.file.filename
            self.error.emit(msg, self.file)
        except Exception as e:
            msg = _msg("Fehler bei der Verarbeitung von %s", "Error processing %s") % self.file.filename
            self.error.emit(f"{msg}: {e}", self.file)

_active_workers = []  # Referenzen auf laufende Worker, damit sie nicht vorzeitig zerstört werden

def file_post_load_processor(file):
    tagger = getattr(file, 'tagger', None)
    metadata = getattr(file, 'metadata', None)
    def on_worker_result(new_metadata, file_obj):
        if worker in _active_workers:
            _active_workers.remove(worker)
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
                    worker = AIWorker(prompt, model, "genre", tagger)
                    worker.result_ready.connect(after_genre)
                    worker.error.connect(on_error)
                    worker.finished.connect(_on_ki_worker_finished)
                    worker.start()
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
                worker = AIWorker(prompt, model, "mood", tagger)
                worker.result_ready.connect(after_mood)
                worker.error.connect(on_error)
                worker.finished.connect(_on_ki_worker_finished)
                worker.start()
                return
            # Wenn kein Mood-Worker nötig, Metadaten/Cache speichern
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
        if worker in _active_workers:
            _active_workers.remove(worker)
        log.warning("AI Music Identifier: Fehler im Hintergrund-Worker für Datei %s: %s", getattr(file_obj, 'filename', 'unbekannt'), msg)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
    # Starte den FullWorker
    worker = AIIDFullWorker(file, tagger)
    _active_workers.append(worker)
    worker.result_ready.connect(on_worker_result)
    worker.error.connect(on_worker_error)
    worker.finished.connect(lambda: _active_workers.remove(worker) if worker in _active_workers else None)
    worker.start()

register_file_post_load_processor(file_post_load_processor)
OPTIONS_PAGE_CLASS = AIIDOptionsPage