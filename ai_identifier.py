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

_aiid_cache = {}

# Speicherort für den Cache (z.B. im Picard-Config-Verzeichnis)
_CACHE_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_cache.json")

def _load_cache():
    global _aiid_cache
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                _aiid_cache.update(json.load(f))
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

def call_ollama(prompt, model="mistral"):
    url = str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434"
    url += "/api/generate"
    data = {"model": model, "prompt": prompt, "stream": False}
    timeout = int(config.setting["aiid_ollama_timeout"] or 60) if "aiid_ollama_timeout" in config.setting else 60
    log.info(f"AI Music Identifier: Sende Prompt an Ollama (Modell: {model}, URL: {url}, Timeout: {timeout}): {prompt}")
    try:
        response = requests.post(url, json=data, timeout=timeout)
        response.raise_for_status()
        result = response.json()["response"].strip()
        log.info(f"AI Music Identifier: Ollama-Antwort erhalten: {result}")
        return result
    except Exception as e:
        log.error(f"AI Music Identifier: Fehler bei Ollama-Anfrage: {e}")
        return f"Fehler bei Ollama-Anfrage: {e}"

def get_genre_suggestion(title, artist):
    prompt = (
        f"Welches Musikgenre hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit dem Genre, ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_genre::{model}::{title}::{artist}"
    if cache_key in _aiid_cache:
        log.debug(f"AI Music Identifier: Genre-Vorschlag aus KI-Cache für {title} - {artist}: {_aiid_cache[cache_key]}")
        return _aiid_cache[cache_key]
    genre = call_ollama(prompt, model)
    if genre and "Fehler" not in genre:
        log.info(f"AI Music Identifier: Genre-Vorschlag von KI für {title} - {artist}: {genre}")
        _aiid_cache[cache_key] = genre
        _save_cache()
    else:
        log.warning(f"AI Music Identifier: Kein gültiger Genre-Vorschlag von KI für {title} - {artist}: {genre}")
    return genre

def show_genre_suggestion_dialog(parent, genre):
    msg_box = QtWidgets.QMessageBox(parent)
    msg_box.setIcon(QtWidgets.QMessageBox.Icon.Question)
    msg_box.setWindowTitle(_msg("KI-Genre-Vorschlag", "AI Genre Suggestion"))
    msg_box.setText(_msg(f"Die KI schlägt folgendes Genre vor:\n<b>{genre}</b>\nÜbernehmen?", f"The AI suggests the following genre:\n<b>{genre}</b>\nAccept?"))
    msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
    return msg_box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

def get_mood_suggestion(title, artist):
    prompt = (
        f"Welche Stimmung hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit einem Wort (z.B. fröhlich, melancholisch, energetisch)."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_mood::{model}::{title}::{artist}"
    if cache_key in _aiid_cache:
        log.debug(f"AI Music Identifier: Stimmungsvorschlag aus KI-Cache für {title} - {artist}: {_aiid_cache[cache_key]}")
        return _aiid_cache[cache_key]
    mood = call_ollama(prompt, model)
    if mood and "Fehler" not in mood:
        log.info(f"AI Music Identifier: Stimmungsvorschlag von KI für {title} - {artist}: {mood}")
        _aiid_cache[cache_key] = mood
        _save_cache()
    else:
        log.warning(f"AI Music Identifier: Kein gültiger Stimmungsvorschlag von KI für {title} - {artist}: {mood}")
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

        # Cache leeren
        self.clear_cache_btn = QtWidgets.QPushButton(_msg("Cache leeren", "Clear cache"))
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        layout.addWidget(self.clear_cache_btn)

        layout.addStretch(1)
        self.setLayout(layout)

    def load(self):
        self.api_key_edit.setText(str(config.setting["aiid_acoustid_api_key"]) if "aiid_acoustid_api_key" in config.setting else "")
        self.auto_select_checkbox.setChecked(bool(config.setting["aiid_auto_select_first"]) if "aiid_auto_select_first" in config.setting else False)
        self.ki_genre_checkbox.setChecked(bool(config.setting["aiid_enable_ki_genre"]) if "aiid_enable_ki_genre" in config.setting else True)
        self.model_combo.setCurrentText(str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral")
        self.url_edit.setText(str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434")
        self.timeout_spin.setValue(int(config.setting["aiid_ollama_timeout"] or 60) if "aiid_ollama_timeout" in config.setting else 60)
        self.ki_mood_checkbox.setChecked(bool(config.setting["aiid_enable_ki_mood"]) if "aiid_enable_ki_mood" in config.setting else False)

    def save(self):
        config.setting["aiid_acoustid_api_key"] = self.api_key_edit.text().strip()
        config.setting["aiid_auto_select_first"] = self.auto_select_checkbox.isChecked()
        config.setting["aiid_enable_ki_genre"] = self.ki_genre_checkbox.isChecked()
        config.setting["aiid_ollama_model"] = self.model_combo.currentText()
        config.setting["aiid_ollama_url"] = self.url_edit.text().strip()
        config.setting["aiid_ollama_timeout"] = self.timeout_spin.value()
        config.setting["aiid_enable_ki_mood"] = self.ki_mood_checkbox.isChecked()

    def clear_cache(self):
        global _aiid_cache
        _aiid_cache.clear()
        _save_cache()
        QtWidgets.QMessageBox.information(self, "Info", _msg("Cache wurde geleert.", "Cache cleared."))

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
        # Cover-URL extrahieren (sofern vorhanden)
        cover_url = None
        if "releasegroups" in result and result["releasegroups"]:
            first_release = result["releasegroups"][0]
            # MusicBrainz Cover Art Archive URL
            mbid = first_release.get("id")
            if mbid:
                cover_url = f"https://coverartarchive.org/release-group/{mbid}/front-250"
        # Text für die Zeile
        item_text = f"{title} – {artists} [{album}]"
        if year:
            item_text += f" ({year})"
        item = QtWidgets.QListWidgetItem(item_text)
        # Cover als Icon laden (optional)
        if cover_url:
            try:
                response = urlopen(cover_url)
                data = response.read()
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                icon = QIcon(pixmap)
                item.setIcon(icon)
            except Exception:
                pass  # Wenn Cover nicht geladen werden kann, ignoriere es
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
    # Komponist(en)
    if "recordings" in result and result["recordings"]:
        rec = result["recordings"][0]
        if "artist-credit" in rec:
            composers = []
            for ac in rec["artist-credit"]:
                if isinstance(ac, dict) and ac.get("artist", {}).get("type") == "Composer":
                    composers.append(ac["artist"].get("name"))
            if composers:
                metadata["composer"] = "; ".join(composers)
    # Jahr (first-release-date)
    if "releasegroups" in result and result["releasegroups"]:
        first_release = result["releasegroups"][0]
        year = first_release.get("first-release-date", "")[:4] if first_release.get("first-release-date") else ""
        if year:
            metadata["date"] = year
    # Cover-Art-URL
    if "releasegroups" in result and result["releasegroups"]:
        first_release = result["releasegroups"][0]
        mbid = first_release.get("id")
        if mbid:
            cover_url = f"https://coverartarchive.org/release-group/{mbid}/front"
            metadata["coverart_url"] = cover_url
    # ISRC
    if "recordings" in result and result["recordings"]:
        rec = result["recordings"][0]
        if "isrcs" in rec and rec["isrcs"]:
            metadata["isrc"] = rec["isrcs"][0]
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
                    # Tracknummer
                    if "medium-list" in rel and rel["medium-list"]:
                        tracks = rel["medium-list"][0].get("track-list", [])
                        if tracks and not metadata.get("tracknumber"):
                            metadata["tracknumber"] = tracks[0].get("number")
            except musicbrainzngs.MusicBrainzError as e:
                log.warning("AI Music Identifier: Failed to fetch extended MusicBrainz data for MBID %s: %s", mbid, e)

def file_post_load_processor(file):
    tagger = getattr(file, 'tagger', None)
    metadata = getattr(file, 'metadata', None)
    print("AIID: process_file called for", getattr(file, "filename", file))
    log.debug("AI Music Identifier: Entering process_file for %s", file.filename)
    if not file.filename:
        log.error("AI Music Identifier: No file path provided")
        return

    api_key = _get_api_key()
    log.info(f"AI Music Identifier: Gelesener API-Key: {api_key!r}")
    if not api_key:
        msg = _msg("Bitte AcoustID API-Key in den Plugin-Einstellungen setzen.",
                   "Please set AcoustID API key in the plugin settings.")
        log.error("AI Music Identifier: No valid AcoustID API key configured")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        return

    # Caching: Hash über Dateipfad + Größe
    try:
        file_hash = hashlib.sha1((file.filename + str(file.size)).encode("utf-8")).hexdigest()
    except Exception:
        file_hash = None

    if file_hash and file_hash in _aiid_cache:
        cached = _aiid_cache[file_hash]
        if metadata:
            metadata.update(cached)
        msg = _msg("Metadaten aus Cache übernommen für %s", "Loaded metadata from cache for %s") % file.filename
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
        log.debug("AI Music Identifier: Used cached metadata for %s", file.filename)
        return

    log.debug("AI Music Identifier: Processing file %s", file.filename)
    try:
        duration, fp = pyacoustid.fingerprint_file(file.filename)
        log.debug("AI Music Identifier: Generated fingerprint for %s (duration: %s)", file.filename, duration)
        results = pyacoustid.lookup(api_key, fp, duration)

        if results and 'results' in results and len(results['results']) > 0:
            acoustid_results = results['results']
            # Wenn mehr als ein Treffer, Auswahl anzeigen
            if len(acoustid_results) > 1:
                if _get_auto_select():
                    idx = 0
                else:
                    idx = select_result_dialog(acoustid_results, tagger.window if tagger and hasattr(tagger, 'window') else None)
                if idx is None:
                    msg = _msg("Keine Auswahl getroffen für %s", "No selection made for %s") % file.filename
                    if tagger and hasattr(tagger, 'window'):
                        tagger.window.set_statusbar_message(msg)
                    return
                result = acoustid_results[idx]
            else:
                result = acoustid_results[0]
            log.debug("AI Music Identifier: Selected AcoustID match: %s", result)

            # Metadaten immer aktualisieren (auch wenn schon vorhanden)
            if metadata is not None:
                metadata["title"] = result.get("title", metadata.get("title", ""))
                artists = result.get("artists", [{}])
                metadata["artist"] = artists[0].get("name", metadata.get("artist", "")) if artists else metadata.get("artist", "")
                release_groups = result.get("releasegroups", [{}])
                metadata["album"] = release_groups[0].get("title", metadata.get("album", "")) if release_groups else metadata.get("album", "")

            # Zusätzliche Felder ergänzen
            if metadata is not None:
                fetch_additional_metadata(result, metadata)

            # Debug: Logge den Wert von metadata['genre'] vor der KI-Prüfung
            if metadata is not None:
                log.info(f"AI Music Identifier: Wert von metadata['genre'] vor KI-Prüfung: {metadata.get('genre')!r}")

            # KI-Genre-Vorschlag per Ollama, falls kein Genre gefunden wurde und Option aktiviert ist
            if metadata is not None and (bool(config.setting["aiid_enable_ki_genre"]) if "aiid_enable_ki_genre" in config.setting else True) and not metadata.get("genre"):
                log.info(f"AI Music Identifier: Starte KI-Genre-Vorschlag für Datei: {file.filename}")
                genre = get_genre_suggestion(metadata.get("title", ""), metadata.get("artist", ""))
                if genre and "Fehler" not in genre:
                    # Vorschau-Dialog anzeigen
                    if show_genre_suggestion_dialog(tagger.window if tagger and hasattr(tagger, 'window') else None, genre):
                        metadata["genre"] = genre
                        log.info("AI Music Identifier: Genre per Ollama übernommen: %s", genre)
                    else:
                        log.info("AI Music Identifier: KI-Genre-Vorschlag abgelehnt: %s", genre)
                elif genre and "Fehler" in genre:
                    msg = _msg(f"KI-Genre-Vorschlag fehlgeschlagen: {genre}", f"AI genre suggestion failed: {genre}")
                    if tagger and hasattr(tagger, 'window'):
                        tagger.window.set_statusbar_message(msg)
                    log.warning("AI Music Identifier: %s", genre)

            # KI-Stimmungsvorschlag per Ollama, falls Option aktiviert
            if metadata is not None and (bool(config.setting["aiid_enable_ki_mood"]) if "aiid_enable_ki_mood" in config.setting else False):
                log.info(f"AI Music Identifier: Starte KI-Stimmungsvorschlag für Datei: {file.filename}")
                mood = get_mood_suggestion(metadata.get("title", ""), metadata.get("artist", ""))
                if mood and "Fehler" not in mood:
                    # Vorschau-Dialog für Stimmung
                    if show_genre_suggestion_dialog(tagger.window if tagger and hasattr(tagger, 'window') else None, mood):
                        metadata["mood"] = mood
                        log.info("AI Music Identifier: Stimmung per Ollama übernommen: %s", mood)
                    else:
                        log.info("AI Music Identifier: KI-Stimmungsvorschlag abgelehnt: %s", mood)
                elif mood and "Fehler" in mood:
                    msg = _msg(f"KI-Stimmungsvorschlag fehlgeschlagen: {mood}", f"AI mood suggestion failed: {mood}")
                    if tagger and hasattr(tagger, 'window'):
                        tagger.window.set_statusbar_message(msg)
                    log.warning("AI Music Identifier: %s", mood)

            # Cache speichern
            if file_hash and metadata is not None:
                _aiid_cache[file_hash] = dict(metadata)
                _save_cache()

            msg = _msg("Metadaten aktualisiert für %s", "Updated metadata for %s") % file.filename
            if tagger and hasattr(tagger, 'window'):
                tagger.window.set_statusbar_message(msg)
            log.debug("AI Music Identifier: Updated metadata: %s", metadata)
        else:
            msg = _msg("Keine Übereinstimmung gefunden für %s", "No matches found for %s") % file.filename
            log.warning("AI Music Identifier: No AcoustID matches found for %s", file.filename)
            if tagger and hasattr(tagger, 'window'):
                tagger.window.set_statusbar_message(msg)

    except pyacoustid.NoBackendError:
        msg = _msg("Chromaprint-Backend nicht gefunden. Bitte libchromaprint installieren.",
                   "Chromaprint backend not found. Please install libchromaprint.")
        log.error("AI Music Identifier: Chromaprint backend not found.")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
    except pyacoustid.FingerprintGenerationError:
        msg = _msg("Fehler beim Fingerprinting von %s", "Failed to fingerprint %s") % file.filename
        log.error("AI Music Identifier: Failed to generate fingerprint for %s", file.filename)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
    except pyacoustid.WebServiceError as e:
        msg = _msg("AcoustID API-Fehler für %s", "AcoustID API error for %s") % file.filename
        log.error("AI Music Identifier: AcoustID API error for %s: %s", file.filename, e)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
    except Exception as e:
        msg = _msg("Fehler bei der Verarbeitung von %s", "Error processing %s") % file.filename
        log.error("AI Music Identifier: Unexpected error for %s: %s", file.filename, e)
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)

register_file_post_load_processor(file_post_load_processor)
OPTIONS_PAGE_CLASS = AIIDOptionsPage