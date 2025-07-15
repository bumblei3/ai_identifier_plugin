# pyright: reportMissingImports=false
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

from picard.extension_points.options_pages import register_options_page
import logging
import logging.handlers
import shutil

LOG_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_plugin.log")
log_handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1024*1024, backupCount=3, encoding='utf-8')
log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
if not any(isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, 'baseFilename', None) == LOG_PATH for h in logging.getLogger().handlers):
    logging.getLogger().addHandler(log_handler)

def set_log_level_from_config():
    level = config.setting["aiid_log_level"] if "aiid_log_level" in config.setting else "WARNING"
    if not isinstance(level, str) or level not in ("WARNING", "INFO", "DEBUG"):
        level = "WARNING"
    logging.getLogger().setLevel(getattr(logging, level, logging.WARNING))

class AIMusicIdentifierOptionsPage(OptionsPage):
    NAME = "ai_identifier"
    TITLE = "AI Music Identifier"
    PARENT = "plugins"

    KI_FIELDS = [
        ("genre", "genre"),
        ("mood", "mood"),
        ("epoch", "decade"),
        ("style", "style"),
        ("instruments", "instruments"),
        ("mood_emojis", "mood_emoji"),
        ("language_code", "language")
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIMusicIdentifierOptionsPage")
        layout = QtWidgets.QVBoxLayout(self)
        # Sprachwahl
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems([_msg("Automatisch", "Automatic"), _msg("Deutsch", "German"), _msg("Englisch", "English")])
        layout.addWidget(QtWidgets.QLabel(_msg("Sprache der Oberfläche:", "UI language:")))
        layout.addWidget(self.lang_combo)
        # Anbieter-Auswahl
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.addItems(["Ollama", "OpenAI", "HuggingFace"])
        layout.addWidget(QtWidgets.QLabel(_msg("KI-Anbieter wählen:", "Select AI provider:")))
        layout.addWidget(self.provider_combo)
        # OpenAI API-Key
        self.openai_key_edit = QtWidgets.QLineEdit()
        self.openai_key_edit.setPlaceholderText(_msg("OpenAI API-Key", "OpenAI API key"))
        layout.addWidget(self.openai_key_edit)
        # HuggingFace API-Key
        self.hf_key_edit = QtWidgets.QLineEdit()
        self.hf_key_edit.setPlaceholderText(_msg("HuggingFace API-Key", "HuggingFace API key"))
        layout.addWidget(self.hf_key_edit)
        # Debug-Checkbox
        debug_value = False
        if "aiid_debug_logging" in config.setting:
            debug_value = bool(config.setting["aiid_debug_logging"])
        self.debug_checkbox = QtWidgets.QCheckBox(_msg("Debug-Logging aktivieren", "Enable debug logging"))
        self.debug_checkbox.setChecked(debug_value)
        layout.addWidget(self.debug_checkbox)
        # Cache-Buttons
        self.clear_cache_button = QtWidgets.QPushButton(_msg("Cache leeren", "Clear cache"))
        layout.addWidget(self.clear_cache_button)
        self.clear_cache_button.clicked.connect(self.clear_cache)
        self.cache_stats_button = QtWidgets.QPushButton(_msg("Cache-Statistiken anzeigen", "Show cache statistics"))
        layout.addWidget(self.cache_stats_button)
        self.cache_stats_button.clicked.connect(self.show_cache_stats)
        self.cache_entries_button = QtWidgets.QPushButton(_msg("Cache-Einträge anzeigen und verwalten", "Show and manage cache entries"))
        layout.addWidget(self.cache_entries_button)
        self.cache_entries_button.clicked.connect(self.show_cache_entries)
        self.feedback_stats_button = QtWidgets.QPushButton(_msg("Feedback-Statistik anzeigen", "Show feedback statistics"))
        layout.addWidget(self.feedback_stats_button)
        self.feedback_stats_button.clicked.connect(self.show_feedback_stats)
        self.feedback_export_button = QtWidgets.QPushButton(_msg("Feedback exportieren", "Export feedback"))
        layout.addWidget(self.feedback_export_button)
        self.feedback_export_button.clicked.connect(self.export_feedback)
        layout.addStretch(1)
        # Sichtbarkeit API-Key Felder
        def on_provider_changed(idx):
            provider = self.provider_combo.currentText()
            self.openai_key_edit.setVisible(provider == "OpenAI")
            self.hf_key_edit.setVisible(provider == "HuggingFace")
        self.provider_combo.currentIndexChanged.connect(on_provider_changed)
        on_provider_changed(self.provider_combo.currentIndex())
        self.performance_combo = QtWidgets.QComboBox()
        self.performance_combo.addItems([
            _msg("Automatisch (empfohlen)", "Automatic (recommended)"),
            _msg("Maximal (schnell, hohe Last)", "Maximum (fast, high load)"),
            _msg("Schonend (wenig Threads)", "Gentle (few threads)")
        ])
        layout.addWidget(QtWidgets.QLabel(_msg("Performance-Modus:", "Performance mode:")))
        layout.addWidget(self.performance_combo)
        # Feld-Checkboxen für Tag-Übernahme
        self.field_checkboxes = {}
        layout.addWidget(QtWidgets.QLabel(_msg("KI-Felder als Tags speichern:", "Save AI fields as tags:")))
        for field, tag in self.KI_FIELDS:
            cb = QtWidgets.QCheckBox(_msg(f"{field} als Tag speichern", f"Save {field} as tag"))
            cb.setChecked(bool(config.setting[f"aiid_save_{field}"]) if f"aiid_save_{field}" in config.setting else True)
            layout.addWidget(cb)
            self.field_checkboxes[field] = cb
        self.loglevel_combo = QtWidgets.QComboBox()
        self.loglevel_combo.addItems([
            _msg("Nur Fehler", "Errors only"),
            _msg("Normal", "Normal"),
            _msg("Debug (alles)", "Debug (all)")
        ])
        layout.addWidget(QtWidgets.QLabel(_msg("Logging-Level:", "Logging level:")))
        layout.addWidget(self.loglevel_combo)
        self.log_export_button = QtWidgets.QPushButton(_msg("Logdatei exportieren", "Export log file"))
        layout.addWidget(self.log_export_button)
        self.log_export_button.clicked.connect(self.export_log)
        # KI-Feature: Cover-Bildersuche
        self.cover_api_key_edit = QtWidgets.QLineEdit()
        self.cover_api_key_edit.setPlaceholderText(_msg("Bing API-Key für Cover-Suche", "Bing API key for cover search"))
        layout.addWidget(self.cover_api_key_edit)
        self.cover_btn = QtWidgets.QPushButton(_msg("Cover-Vorschlag holen", "Get cover suggestion"))
        layout.addWidget(self.cover_btn)
        self.cover_btn.clicked.connect(self.show_cover_suggestion)
        # KI-Feature: Dubletten-Erkennung
        self.dup_btn = QtWidgets.QPushButton(_msg("Dublettensuche starten", "Find duplicates"))
        layout.addWidget(self.dup_btn)
        self.dup_btn.clicked.connect(self.show_duplicates)
        # KI-Feature: Lyrics-Erkennung
        self.lyrics_api_key_edit = QtWidgets.QLineEdit()
        self.lyrics_api_key_edit.setPlaceholderText(_msg("Lyrics-API-Key (z.B. Genius)", "Lyrics API key (e.g. Genius)"))
        layout.addWidget(self.lyrics_api_key_edit)
        self.lyrics_btn = QtWidgets.QPushButton(_msg("Lyrics holen", "Get lyrics"))
        layout.addWidget(self.lyrics_btn)
        self.lyrics_btn.clicked.connect(self.show_lyrics_suggestion)
        # KI-Feature: Playlist/Stimmungs-Vorschläge
        self.playlist_btn = QtWidgets.QPushButton(_msg("Playlist-Vorschlag", "Playlist suggestion"))
        layout.addWidget(self.playlist_btn)
        self.playlist_btn.clicked.connect(self.show_playlist_suggestion)
        # Tooltips für KI-Feature-Buttons
        self.cover_btn.setToolTip(_msg("Lässt die KI ein passendes Cover suchen und vorschlagen.", "Let the AI suggest a suitable cover."))
        self.dup_btn.setToolTip(_msg("Findet potenzielle Dubletten in deiner Sammlung.", "Finds potential duplicates in your collection."))
        self.lyrics_btn.setToolTip(_msg("Holt Songtexte per KI oder Lyrics-API.", "Fetches lyrics via AI or lyrics API."))
        self.playlist_btn.setToolTip(_msg("Erstellt Playlists oder Stimmungs-Vorschläge per KI.", "Creates playlists or mood suggestions via AI."))
        self.cover_api_key_edit.setToolTip(_msg("API-Key für Bing Image Search, um Cover zu finden.", "API key for Bing Image Search to find covers."))
        self.lyrics_api_key_edit.setToolTip(_msg("API-Key für Lyrics-Provider wie Genius.", "API key for lyrics provider such as Genius."))
        self.loglevel_combo.setToolTip(_msg("Wähle, wie viele Log-Meldungen gespeichert werden.", "Choose how many log messages are saved."))
        self.log_export_button.setToolTip(_msg("Exportiere die aktuelle Logdatei.", "Export the current log file."))
        self.feedback_stats_button.setToolTip(_msg("Zeigt die Statistik zu deinem Feedback an.", "Shows statistics about your feedback."))
        self.feedback_export_button.setToolTip(_msg("Exportiere dein Feedback als Datei.", "Export your feedback as a file."))
        self.clear_cache_button.setToolTip(_msg("Leert den KI-Cache.", "Clears the AI cache."))
        self.cache_stats_button.setToolTip(_msg("Zeigt Statistiken zum KI-Cache an.", "Shows statistics about the AI cache."))
        self.cache_entries_button.setToolTip(_msg("Verwalte einzelne KI-Cache-Einträge.", "Manage individual AI cache entries."))
        self.debug_checkbox.setToolTip(_msg("Aktiviere detailliertes Debug-Logging.", "Enable detailed debug logging."))
        self.performance_combo.setToolTip(_msg("Steuert die Geschwindigkeit und Systemlast der KI-Verarbeitung.", "Controls the speed and system load of AI processing."))
        self.lang_combo.setToolTip(_msg("Sprache der Oberfläche und Prompts.", "Language of the UI and prompts."))
        # Tooltips für Feld-Checkboxen
        for field, cb in self.field_checkboxes.items():
            cb.setToolTip(_msg(f"Soll das Feld '{field}' als Tag gespeichert werden?", f"Should the field '{field}' be saved as a tag?"))
        # Reset-Button
        self.reset_btn = QtWidgets.QPushButton(_msg("Zurücksetzen auf Standard", "Reset to default"))
        self.reset_btn.setToolTip(_msg("Setzt alle Plugin-Einstellungen auf die Standardwerte zurück.", "Resets all plugin settings to default values."))
        layout.addWidget(self.reset_btn)
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        # Export/Import-Buttons
        self.export_settings_btn = QtWidgets.QPushButton(_msg("Einstellungen exportieren", "Export settings"))
        self.export_settings_btn.setToolTip(_msg("Exportiert alle Plugin-Einstellungen als JSON-Datei.", "Exports all plugin settings as a JSON file."))
        layout.addWidget(self.export_settings_btn)
        self.export_settings_btn.clicked.connect(self.export_settings)
        self.import_settings_btn = QtWidgets.QPushButton(_msg("Einstellungen importieren", "Import settings"))
        self.import_settings_btn.setToolTip(_msg("Importiert Plugin-Einstellungen aus einer JSON-Datei.", "Imports plugin settings from a JSON file."))
        layout.addWidget(self.import_settings_btn)
        self.import_settings_btn.clicked.connect(self.import_settings)

    def clear_cache(self):
        if QtWidgets.QMessageBox.question(self, _msg("Cache leeren", "Clear cache"), _msg("Wirklich den gesamten KI-Cache löschen?", "Really clear the entire KI cache?")) == QtWidgets.QMessageBox.StandardButton.Yes:
            _aiid_cache.clear()
            _save_cache()
            QtWidgets.QMessageBox.information(self, _msg("Cache", "Cache"), _msg("Cache wurde geleert.", "Cache cleared."))

    def show_cache_stats(self):
        count = len(_aiid_cache)
        if count == 0:
            msg = _msg("Cache ist leer.", "Cache is empty.")
        else:
            ages = [int(time.time() - v['ts']) for v in _aiid_cache.values() if isinstance(v, dict) and 'ts' in v]
            size = len(str(_aiid_cache).encode("utf-8"))
            msg = _msg(f"Anzahl Einträge: {count}\nGröße: {size} Bytes", f"Number of entries: {count}\nSize: {size} Bytes")
            if ages:
                msg += _msg(f"\nÄltester Eintrag: {max(ages)}s\nJüngster Eintrag: {min(ages)}s", f"\nOldest entry: {max(ages)}s\nNewest entry: {min(ages)}s")
        QtWidgets.QMessageBox.information(self, _msg("Cache-Statistiken", "Cache Statistics"), msg)

    def show_cache_entries(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(_msg("KI-Cache-Einträge verwalten", "Manage KI Cache Entries"))
        layout = QtWidgets.QVBoxLayout(dialog)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        inner_layout = QtWidgets.QVBoxLayout(inner)
        for key, value in list(_aiid_cache.items()):
            entry_widget = QtWidgets.QWidget()
            entry_layout = QtWidgets.QHBoxLayout(entry_widget)
            entry_label = QtWidgets.QLabel(f"{key}: {value['value'] if isinstance(value, dict) and 'value' in value else value}")
            del_btn = QtWidgets.QPushButton(_msg("Löschen", "Delete"))
            def make_del_func(k):
                return lambda: self.delete_cache_entry(dialog, k)
            del_btn.clicked.connect(make_del_func(key))
            entry_layout.addWidget(entry_label)
            entry_layout.addWidget(del_btn)
            inner_layout.addWidget(entry_widget)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        close_btn = QtWidgets.QPushButton(_msg("Schließen", "Close"))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.resize(600, 400)
        dialog.exec()

    def delete_cache_entry(self, parent_dialog, key):
        if key in _aiid_cache:
            del _aiid_cache[key]
            _save_cache()
            QtWidgets.QMessageBox.information(self, _msg("Cache", "Cache"), _msg(f"Eintrag '{key}' wurde gelöscht.", f"Entry '{key}' deleted."))
        parent_dialog.close()
        self.show_cache_entries()

    def load(self):
        debug_value = False
        if "aiid_debug_logging" in config.setting:
            debug_value = bool(config.setting["aiid_debug_logging"])
        self.debug_checkbox.setChecked(debug_value)
        # Sprache
        lang = config.setting["aiid_ui_language"] if "aiid_ui_language" in config.setting else "auto"
        if not isinstance(lang, str) or lang not in ("auto", "de", "en"):
            lang = "auto"
        lang_map = {"auto": 0, "de": 1, "en": 2}
        self.lang_combo.setCurrentIndex(lang_map[lang])
        # Anbieter
        provider = config.setting["aiid_provider"] if "aiid_provider" in config.setting else "Ollama"
        idx = self.provider_combo.findText(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        # OpenAI-Key
        self.openai_key_edit.setText(config.setting["aiid_openai_key"] if "aiid_openai_key" in config.setting else "")
        # HF-Key
        self.hf_key_edit.setText(config.setting["aiid_hf_key"] if "aiid_hf_key" in config.setting else "")
        # Sichtbarkeit
        self.provider_combo.currentIndexChanged.emit(self.provider_combo.currentIndex())
        # Performance-Modus
        perf = config.setting["aiid_performance_mode"] if "aiid_performance_mode" in config.setting else "auto"
        if not isinstance(perf, str) or perf not in ("auto", "max", "gentle"):
            perf = "auto"
        perf_map = {"auto": 0, "max": 1, "gentle": 2}
        self.performance_combo.setCurrentIndex(perf_map[perf])
        # Feld-Checkboxen
        for field, cb in self.field_checkboxes.items():
            cb.setChecked(bool(config.setting[f"aiid_save_{field}"]) if f"aiid_save_{field}" in config.setting else True)
        # Logging-Level
        loglevel = config.setting["aiid_log_level"] if "aiid_log_level" in config.setting else "WARNING"
        if not isinstance(loglevel, str) or loglevel not in ("WARNING", "INFO", "DEBUG"):
            loglevel = "WARNING"
        loglevel_map = {"WARNING": 0, "INFO": 1, "DEBUG": 2}
        self.loglevel_combo.setCurrentIndex(loglevel_map[loglevel])
        set_log_level_from_config()
        self.cover_api_key_edit.setText(config.setting["aiid_bing_api_key"] if "aiid_bing_api_key" in config.setting else "")
        self.lyrics_api_key_edit.setText(config.setting["aiid_lyrics_api_key"] if "aiid_lyrics_api_key" in config.setting else "")

    def save(self):
        config.setting["aiid_debug_logging"] = self.debug_checkbox.isChecked()
        config.setting["aiid_provider"] = self.provider_combo.currentText()
        config.setting["aiid_openai_key"] = self.openai_key_edit.text()
        config.setting["aiid_hf_key"] = self.hf_key_edit.text()
        idx = self.lang_combo.currentIndex()
        config.setting["aiid_ui_language"] = ["auto", "de", "en"][idx]
        idx = self.performance_combo.currentIndex()
        config.setting["aiid_performance_mode"] = ["auto", "max", "gentle"][idx]
        for field, cb in self.field_checkboxes.items():
            config.setting[f"aiid_save_{field}"] = cb.isChecked()
        idx = self.loglevel_combo.currentIndex()
        config.setting["aiid_log_level"] = ["WARNING", "INFO", "DEBUG"][idx]
        set_log_level_from_config()
        config.setting["aiid_bing_api_key"] = self.cover_api_key_edit.text()
        config.setting["aiid_lyrics_api_key"] = self.lyrics_api_key_edit.text()

    def show_feedback_stats(self):
        data = load_feedback()
        if not data:
            msg = _msg("Noch kein Feedback vorhanden.", "No feedback yet.")
        else:
            msg = ""
            for field, stats in data.items():
                msg += f"{field}: 👍 {stats['correct']} | 👎 {stats['wrong']}\n"
        QtWidgets.QMessageBox.information(self, _msg("Feedback-Statistik", "Feedback statistics"), msg)

    def export_feedback(self):
        data = load_feedback()
        if not data:
            QtWidgets.QMessageBox.information(self, _msg("Feedback exportieren", "Export feedback"), _msg("Kein Feedback zum Exportieren vorhanden.", "No feedback to export."))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Feedback exportieren", "Export feedback"), "aiid_feedback_export.json", "JSON (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                QtWidgets.QMessageBox.information(self, _msg("Feedback exportiert", "Feedback exported"), _msg("Feedback wurde exportiert.", "Feedback exported."))
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), str(e))

    def export_log(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Logdatei exportieren", "Export log file"), "aiid_plugin.log", "Log (*.log)")
        if path:
            try:
                shutil.copy(LOG_PATH, path)
                QtWidgets.QMessageBox.information(self, _msg("Logdatei exportiert", "Log file exported"), _msg("Logdatei wurde exportiert.", "Log file exported."))
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), str(e))

    def show_cover_suggestion(self):
        QtWidgets.QMessageBox.information(self, _msg("Cover-Vorschlag", "Cover suggestion"), _msg("Hier könnte ein Cover-Vorschlag erscheinen.", "A cover suggestion would appear here."))
    def show_duplicates(self):
        QtWidgets.QMessageBox.information(self, _msg("Dublettensuche", "Duplicate search"), _msg("Hier könnten Dubletten angezeigt werden.", "Duplicates would be shown here."))
    def show_lyrics_suggestion(self):
        QtWidgets.QMessageBox.information(self, _msg("Lyrics-Vorschlag", "Lyrics suggestion"), _msg("Hier könnten Lyrics angezeigt werden.", "Lyrics would be shown here."))
    def show_playlist_suggestion(self):
        QtWidgets.QMessageBox.information(self, _msg("Playlist-Vorschlag", "Playlist suggestion"), _msg("Hier könnte eine Playlist angezeigt werden.", "A playlist would be shown here."))

    def reset_to_defaults(self):
        # Setze alle aiid_-Settings auf Standardwerte
        keys = [k for k in config.setting if isinstance(k, str) and k.startswith("aiid_")]
        for k in keys:
            config.setting[k] = None
        QtWidgets.QMessageBox.information(self, _msg("Zurückgesetzt", "Reset"), _msg("Alle Einstellungen wurden auf Standard zurückgesetzt.", "All settings have been reset to default."))
        self.load()
    def export_settings(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Einstellungen exportieren", "Export settings"), "aiid_settings.json", "JSON (*.json)")
        if path:
            keys = [k for k in config.setting if isinstance(k, str) and k.startswith("aiid_")]
            data = {k: config.setting[k] for k in keys}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            QtWidgets.QMessageBox.information(self, _msg("Exportiert", "Exported"), _msg("Einstellungen wurden exportiert.", "Settings exported."))
    def import_settings(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, _msg("Einstellungen importieren", "Import settings"), "", "JSON (*.json)")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                config.setting[k] = v
            QtWidgets.QMessageBox.information(self, _msg("Importiert", "Imported"), _msg("Einstellungen wurden importiert.", "Settings imported."))
            self.load()

register_options_page(AIMusicIdentifierOptionsPage)

# Globale Thread-Limitierung für KI-Worker
_MAX_KI_THREADS = 2
_active_ki_threads = 0
_ki_worker_queue = deque()

# Semaphore für parallele AcoustID-Lookups
_ACOUSTID_MAX_PARALLEL = 2
_acoustid_semaphore = threading.Semaphore(_ACOUSTID_MAX_PARALLEL)

# Chunk-Größe für Batch-Import (wie viele Dateien pro Block an Picard übergeben werden)
_CHUNK_SIZE = 20

class WorkerSignals(QObject):
    result_ready = pyqtSignal(str, object)
    error = pyqtSignal(str, object)

class BatchProgressDialog(QtWidgets.QDialog):
    def __init__(self, total_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Batch-Verarbeitung", "Batch Processing"))
        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setMaximum(total_files)
        self.cancel_button = QtWidgets.QPushButton(_msg("Abbrechen", "Cancel"), self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        self.cancelled = False
        self.cancel_button.clicked.connect(self.cancel)
    def update_progress(self, value):
        self.progress.setValue(value)
    def cancel(self):
        self.cancelled = True


def process_files_with_progress(file_list, process_func, parent=None):
    dialog = BatchProgressDialog(len(file_list), parent)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    success_count = 0
    error_count = 0
    errors = []
    for idx, file in enumerate(file_list, 1):
        if dialog.cancelled:
            break
        try:
            result = process_func(file)
            if isinstance(result, str) and "Fehler" in result:
                error_count += 1
                errors.append(f"{file}: {result}")
            else:
                success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f"{file}: {e}")
        dialog.update_progress(idx)
        QtWidgets.QApplication.processEvents()
    dialog.close()
    summary = _msg(f"Fertig! Erfolgreich: {success_count}, Fehler: {error_count}", f"Finished! Success: {success_count}, Errors: {error_count}")
    if dialog.cancelled:
        summary = _msg("Abgebrochen! ", "Cancelled! ") + summary
    if errors:
        summary += _msg(f"\nFehlerliste:\n", f"\nError list:\n") + "\n".join(errors[:10])
        if len(errors) > 10:
            summary += _msg(f"\n... und {len(errors)-10} weitere Fehler.", f"\n... and {len(errors)-10} more errors.")
    QtWidgets.QMessageBox.information(parent, _msg("Batch-Ergebnis", "Batch Result"), summary)

def get_genre_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welches Musikgenre hat der Song '{title}' von '{artist}'? ", f"What music genre does the song '{title}' by '{artist}' have? ") +
        _msg("Antworte nur mit dem Genre, ohne weitere Erklärungen.", "Answer only with the genre, without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_genre::" + model + f"::{title}::{artist}"
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
    genre = call_ai_provider(prompt, model, tagger, file_name)
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
        _msg(f"Welche Stimmung hat der Song '{title}' von '{artist}'? ", f"What mood does the song '{title}' by '{artist}' have? ") +
        _msg("Antworte nur mit einem Wort (z.B. fröhlich, melancholisch, energetisch).", "Answer only with one word (e.g., cheerful, melancholic, energetic).")
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
    mood = call_ai_provider(prompt, model, tagger, file_name)
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
        _msg(f"In welcher Sprache ist der Song '{title}' von '{artist}' gesungen? ", f"In which language is the song '{title}' by '{artist}' sung? ") +
        _msg("Antworte nur mit der Sprache (z.B. Deutsch, Englisch, Spanisch), ohne weitere Erklärungen.", "Answer only with the language (e.g., German, English, Spanish), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_language::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    language = call_ai_provider(prompt, model, tagger, file_name)
    if language and "Fehler" not in language:
        if use_cache:
            _aiid_cache[cache_key] = {"value": language, "ts": time.time()}
            _save_cache()
    return language

def get_instruments_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welche Hauptinstrumente sind im Song '{title}' von '{artist}' zu hören? ", f"Which main instruments are heard in the song '{title}' by '{artist}'? ") +
        _msg("Antworte nur mit einer kommagetrennten Liste (z.B. Gitarre, Schlagzeug, Bass), ohne weitere Erklärungen.", "Answer only with a comma-separated list (e.g., Guitar, Drums, Bass), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_instruments::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    instruments = call_ai_provider(prompt, model, tagger, file_name)
    if instruments and "Fehler" not in instruments:
        if use_cache:
            _aiid_cache[cache_key] = {"value": instruments, "ts": time.time()}
            _save_cache()
    return instruments

def get_mood_emoji_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welches Emoji passt am besten zur Stimmung des Songs '{title}' von '{artist}'? ", f"Which emoji best fits the mood of the song '{title}' by '{artist}'? ") +
        _msg("Antworte nur mit einem Emoji, ohne weitere Erklärungen.", "Answer only with one emoji, without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_mood_emoji::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            return v["value"]
    emoji = call_ai_provider(prompt, model, tagger, file_name)
    if emoji and "Fehler" not in emoji:
        if use_cache:
            _aiid_cache[cache_key] = {"value": emoji, "ts": time.time()}
            _save_cache()
    return emoji

def get_epoch_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"In welcher musikalischen Epoche wurde der Song '{title}' von '{artist}' veröffentlicht? ", f"In which musical era was the song '{title}' by '{artist}' released? ") +
        _msg("Antworte nur mit einer Dekade (z.B. 80er, 90er, 2000er), ohne weitere Erklärungen.", "Answer only with a decade (e.g., 80s, 90s, 2000s), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_epoch::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Epoche aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Epoch from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Epoche, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Epochen-Vorschlag wird berechnet...", "AI epoch suggestion in progress..."))
    epoch = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if epoch and "Fehler" not in epoch:
        log.info(f"AI Music Identifier: Epoche von KI für {title} - {artist}: {epoch}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": epoch, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Epoche, Datei: {file_name}, Key: {cache_key}, Wert: {epoch}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Epochen-Vorschlag von KI für {title} - {artist}: {epoch}", f"AI Music Identifier: No valid epoch suggestion from AI for {title} - {artist}: {epoch}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Epochen-Fehler: {epoch}", f"AI epoch error: {epoch}"))
    return epoch

def get_style_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welcher Musikstil beschreibt den Song '{title}' von '{artist}' am besten? ", f"Which music style best describes the song '{title}' by '{artist}'? ") +
        _msg("Antworte nur mit dem Stil (z.B. Synthpop, Hardrock, Trap), ohne weitere Erklärungen.", "Answer only with the style (e.g., Synthpop, Hardrock, Trap), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_style::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Stil aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Style from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Stil, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Stil-Vorschlag wird berechnet...", "AI style suggestion in progress..."))
    style = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if style and "Fehler" not in style:
        log.info(f"AI Music Identifier: Stil von KI für {title} - {artist}: {style}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": style, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Stil, Datei: {file_name}, Key: {cache_key}, Wert: {style}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Stil-Vorschlag von KI für {title} - {artist}: {style}", f"AI Music Identifier: No valid style suggestion from AI for {title} - {artist}: {style}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Stil-Fehler: {style}", f"AI style error: {style}"))
    return style

def get_instruments_detailed_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welche Instrumente sind im Song '{title}' von '{artist}' zu hören? ", f"Which instruments are heard in the song '{title}' by '{artist}'? ") +
        _msg("Antworte mit einer möglichst detaillierten, kommagetrennten Liste (z.B. E-Gitarre, Drum Machine, Synthesizer), ohne weitere Erklärungen.", "Answer with a detailed, comma-separated list (e.g., E-Guitar, Drum Machine, Synthesizer), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_instruments_detailed::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Instrumentierung (detailliert) aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Instruments (detailed) from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Instrumentierung (detailliert), Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Instrumentierungs-Vorschlag wird berechnet...", "AI instruments suggestion in progress..."))
    instruments = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if instruments and "Fehler" not in instruments:
        log.info(f"AI Music Identifier: Instrumentierung (detailliert) von KI für {title} - {artist}: {instruments}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": instruments, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Instrumentierung (detailliert), Datei: {file_name}, Key: {cache_key}, Wert: {instruments}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Instrumentierungs-Vorschlag von KI für {title} - {artist}: {instruments}", f"AI Music Identifier: No valid instruments suggestion from AI for {title} - {artist}: {instruments}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Instrumentierungs-Fehler: {instruments}", f"AI instruments error: {instruments}"))
    return instruments

def get_mood_emojis_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"Welche Emojis passen zur Stimmung des Songs '{title}' von '{artist}'? ", f"Which emojis fit the mood of the song '{title}' by '{artist}'? ") +
        _msg("Antworte nur mit einer Emoji-Liste (z.B. 😊🎉), ohne weitere Erklärungen.", "Answer only with an emoji list (e.g., 😊🎉), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_mood_emojis::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Emoji-Liste aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Emoji list from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Emoji-Liste, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Emoji-Vorschlag wird berechnet...", "AI emoji suggestion in progress..."))
    emojis = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if emojis and "Fehler" not in emojis:
        log.info(f"AI Music Identifier: Emoji-Liste von KI für {title} - {artist}: {emojis}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": emojis, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Emoji-Liste, Datei: {file_name}, Key: {cache_key}, Wert: {emojis}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Emoji-Vorschlag von KI für {title} - {artist}: {emojis}", f"AI Music Identifier: No valid emoji suggestion from AI for {title} - {artist}: {emojis}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Emoji-Fehler: {emojis}", f"AI emoji error: {emojis}"))
    return emojis

def get_language_code_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        _msg(f"In welcher Sprache ist der Song '{title}' von '{artist}' gesungen? ", f"In which language is the song '{title}' by '{artist}' sung? ") +
        _msg("Antworte nur mit dem ISO-639-1 Sprachcode (z.B. de, en, es), ohne weitere Erklärungen.", "Answer only with the ISO-639-1 language code (e.g., de, en, es), without further explanations.")
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_language_code::" + model + f"::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in _aiid_cache:
        v = _aiid_cache[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(_msg(f"AI Music Identifier: Sprachcode aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)", f"AI Music Identifier: Language code from AI cache for {title} - {artist}: {v['value']} (age: {age}s)"))
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Hit] Typ: Sprachcode, Datei: {file_name}, Key: {cache_key}, Alter: {age}s, Wert: {v['value']}")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(_msg("KI-Sprachcode-Vorschlag wird berechnet...", "AI language code suggestion in progress..."))
    lang_code = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if lang_code and "Fehler" not in lang_code:
        log.info(f"AI Music Identifier: Sprachcode von KI für {title} - {artist}: {lang_code}")
        if use_cache:
            _aiid_cache[cache_key] = {"value": lang_code, "ts": time.time()}
            _save_cache()
            if is_debug_logging():
                log.debug(f"AI Music Identifier: [Cache-Store] Typ: Sprachcode, Datei: {file_name}, Key: {cache_key}, Wert: {lang_code}")
    else:
        log.warning(_msg(f"AI Music Identifier: Kein gültiger Sprachcode-Vorschlag von KI für {title} - {artist}: {lang_code}", f"AI Music Identifier: No valid language code suggestion from AI for {title} - {artist}: {lang_code}"))
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(_msg(f"KI-Sprachcode-Fehler: {lang_code}", f"AI language code error: {lang_code}"))
    return lang_code

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
    # Sprachumschaltung mit Benutzerauswahl
    lang = None
    if "aiid_ui_language" in config.setting and config.setting["aiid_ui_language"] != "auto":
        lang = config.setting["aiid_ui_language"]
    else:
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
            log.warning(_msg(f"[Performance] KI-Request dauerte ungewöhnlich lange: {elapsed:.1f}s (Datei: {file_name})", f"[Performance] AI request took unusually long: {elapsed:.1f}s (file: {file_name})"))
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [KI-Response] Datei: {file_name}, Dauer: {elapsed:.2f}s, Status: {response.status_code}")
        response.raise_for_status()
        result = response.json()["response"].strip()
        log.info(f"AI Music Identifier: Ollama-Antwort erhalten für Datei {file_name}: {result}")
        return result
    except requests.Timeout as e:
        msg = _msg(f"[Netzwerkfehler] KI-Timeout bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI timeout on Ollama request for file {file_name}: {e}")
        log.error(f"[Netzwerkfehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except requests.ConnectionError as e:
        msg = _msg(f"[Netzwerkfehler] KI-Netzwerkfehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI network error on Ollama request for file {file_name}: {e}")
        log.error(f"[Netzwerkfehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except requests.HTTPError as e:
        msg = _msg(f"[API-Fehler] HTTP-Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[API error] HTTP error on Ollama request for file {file_name}: {e}")
        log.error(f"[API-Fehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except Exception as e:
        msg = _msg(f"[Lokaler Fehler] Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Local error] Error on Ollama request for file {file_name}: {e}")
        log.error(f"[Lokaler Fehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg

def call_ai_provider(prompt, model, tagger=None, file_name=None):
    provider = config.setting["aiid_provider"] if "aiid_provider" in config.setting else "Ollama"
    if provider == "Ollama":
        return call_ollama(prompt, model, tagger, file_name)
    elif provider == "OpenAI":
        return call_openai(prompt, model, tagger, file_name)
    elif provider == "HuggingFace":
        return call_huggingface(prompt, model, tagger, file_name)
    else:
        return _msg("Unbekannter KI-Anbieter", "Unknown AI provider")

def call_openai(prompt, model, tagger=None, file_name=None):
    api_key = config.setting["aiid_openai_key"] if "aiid_openai_key" in config.setting else ""
    if not api_key:
        msg = _msg("[API-Fehler] Kein OpenAI API-Key gesetzt.", "[API error] No OpenAI API key set.")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model if model else "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.2
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"].strip()
        return result
    except Exception as e:
        msg = _msg(f"[OpenAI-Fehler] {e}", f"[OpenAI error] {e}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg

def call_huggingface(prompt, model, tagger=None, file_name=None):
    api_key = config.setting["aiid_hf_key"] if "aiid_hf_key" in config.setting else ""
    if not api_key:
        msg = _msg("[API-Fehler] Kein HuggingFace API-Key gesetzt.", "[API error] No HuggingFace API key set.")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"inputs": prompt}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        # HF-API kann verschiedene Formate liefern
        if isinstance(result, list) and len(result) > 0 and "generated_text" in result[0]:
            return result[0]["generated_text"].strip()
        elif isinstance(result, dict) and "error" in result:
            return _msg(f"[HF-Fehler] {result['error']}", f"[HF error] {result['error']}")
        else:
            return str(result)
    except Exception as e:
        msg = _msg(f"[HF-Fehler] {e}", f"[HF error] {e}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg

def get_optimal_thread_count():
    try:
        cpu_count = psutil.cpu_count(logical=True) or 1
        load = psutil.getloadavg()[0] / cpu_count if cpu_count else 1.0
        if load < 0.5:
            return min(4, int(cpu_count))
        elif load < 1.0:
            return min(2, int(cpu_count))
        else:
            return 1
    except Exception:
        return 2  # Fallback

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
                if self.tagger and hasattr(self.tagger, 'window'):
                    QtWidgets.QMessageBox.critical(self.tagger.window, "KI-Fehler", str(result or "Unbekannter Fehler"))
        except Exception as e:
            self.signals.error.emit(str(e), None)
            if self.tagger and hasattr(self.tagger, 'window'):
                QtWidgets.QMessageBox.critical(self.tagger.window, "KI-Fehler", str(e))

class KISuggestionDialog(QtWidgets.QDialog):
    def __init__(self, suggestions, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("KI-Vorschläge prüfen und übernehmen", "Check and accept AI suggestions"))
        self.edits = {}
        layout = QtWidgets.QFormLayout(self)
        for key, value in suggestions.items():
            field_widget = QtWidgets.QWidget()
            field_layout = QtWidgets.QHBoxLayout(field_widget)
            edit = QtWidgets.QLineEdit(str(value) if value is not None else "")
            self.edits[key] = edit
            field_layout.addWidget(edit)
            btn_good = QtWidgets.QPushButton("👍")
            btn_bad = QtWidgets.QPushButton("👎")
            btn_good.setToolTip(_msg("Vorschlag ist korrekt", "Suggestion is correct"))
            btn_bad.setToolTip(_msg("Vorschlag ist falsch", "Suggestion is wrong"))
            btn_good.clicked.connect(lambda _, k=key: save_feedback(k, True))
            btn_bad.clicked.connect(lambda _, k=key: save_feedback(k, False))
            field_layout.addWidget(btn_good)
            field_layout.addWidget(btn_bad)
            layout.addRow(key, field_widget)
        self.accepted_all = False
        self.rejected_all = False
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_accept = QtWidgets.QPushButton(_msg("Alle übernehmen", "Accept all"))
        self.btn_reject = QtWidgets.QPushButton(_msg("Alle ablehnen", "Reject all"))
        btn_layout.addWidget(self.btn_accept)
        btn_layout.addWidget(self.btn_reject)
        layout.addRow(btn_layout)
        self.btn_accept.clicked.connect(self.accept_all)
        self.btn_reject.clicked.connect(self.reject_all)
    def accept_all(self):
        self.accepted_all = True
        self.accept()
    def reject_all(self):
        self.rejected_all = True
        self.reject()
    def get_results(self):
        return {k: e.text() for k, e in self.edits.items()}

def show_ki_suggestions_dialog(suggestions, parent=None):
    dialog = KISuggestionDialog(suggestions, parent)
    result = dialog.exec()
    if dialog.accepted_all:
        return dialog.get_results()
    elif dialog.rejected_all:
        return None
    else:
        return None

_FEEDBACK_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_feedback.json")

def save_feedback(field, is_correct):
    try:
        if os.path.exists(_FEEDBACK_PATH):
            with open(_FEEDBACK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        if field not in data:
            data[field] = {"correct": 0, "wrong": 0}
        if is_correct:
            data[field]["correct"] += 1
        else:
            data[field]["wrong"] += 1
        with open(_FEEDBACK_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Feedback speichern fehlgeschlagen: {e}")

def load_feedback():
    if os.path.exists(_FEEDBACK_PATH):
        with open(_FEEDBACK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# Mapping KI-Feld → Picard-Tag
KI_TO_PICARD_TAG = {
    "genre": "genre",
    "mood": "mood",
    "epoch": "decade",
    "style": "style",
    "instruments": "instruments",
    "mood_emojis": "mood_emoji",
    "language_code": "language"
}

def apply_ki_tags_to_metadata(metadata, ki_results):
    for ki_field, tag in KI_TO_PICARD_TAG.items():
        if (f"aiid_save_{ki_field}" not in config.setting or config.setting[f"aiid_save_{ki_field}"]) and ki_field in ki_results:
            metadata[tag] = ki_results[ki_field]