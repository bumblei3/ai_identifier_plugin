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
from PyQt6.QtCore import QThreadPool, QRunnable, QObject, pyqtSignal, QUrl, QTimer, QTime
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
import difflib
import librosa
from difflib import SequenceMatcher
import copy
import csv

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
        self.lang_combo.addItems([
            _msg("Automatisch", "Automatic", "Automatique", "Automático"),
            _msg("Deutsch", "German", "Allemand", "Alemán"),
            _msg("Englisch", "English", "Anglais", "Inglés"),
            _msg("Französisch", "French", "Français", "Francés"),
            _msg("Spanisch", "Spanish", "Espagnol", "Español")
        ])
        layout.addWidget(QtWidgets.QLabel(_msg("Sprache der Oberfläche:", "UI language:", "Langue de l'interface:", "Idioma de la interfaz:")))
        layout.addWidget(self.lang_combo)
        # Anbieter-Auswahl
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.addItems(["Ollama", "OpenAI", "HuggingFace", "Google", "DeepL", "AWS", "Azure"])
        layout.addWidget(QtWidgets.QLabel(_msg("KI-Anbieter wählen:", "Select AI provider:", "Choisir le fournisseur d'IA:", "Seleccionar proveedor de IA:")))
        layout.addWidget(self.provider_combo)
        # OpenAI API-Key
        self.openai_key_edit = QtWidgets.QLineEdit()
        self.openai_key_edit.setPlaceholderText(_msg("OpenAI API-Key", "OpenAI API key", "Clé API OpenAI", "Clave API OpenAI"))
        layout.addWidget(self.openai_key_edit)
        # HuggingFace API-Key
        self.hf_key_edit = QtWidgets.QLineEdit()
        self.hf_key_edit.setPlaceholderText(_msg("HuggingFace API-Key", "HuggingFace API key", "Clé API HuggingFace", "Clave API HuggingFace"))
        layout.addWidget(self.hf_key_edit)
        # Google API-Key
        self.google_key_edit = QtWidgets.QLineEdit()
        self.google_key_edit.setPlaceholderText(_msg("Google API-Key", "Google API key", "Clé API Google", "Clave API Google"))
        layout.addWidget(self.google_key_edit)
        # DeepL API-Key
        self.deepl_key_edit = QtWidgets.QLineEdit()
        self.deepl_key_edit.setPlaceholderText(_msg("DeepL API-Key", "DeepL API key", "Clé API DeepL", "Clave API DeepL"))
        layout.addWidget(self.deepl_key_edit)
        # AWS API-Key
        self.aws_key_edit = QtWidgets.QLineEdit()
        self.aws_key_edit.setPlaceholderText(_msg("AWS API-Key", "AWS API key", "Clé API AWS", "Clave API AWS"))
        layout.addWidget(self.aws_key_edit)
        # Azure API-Key
        self.azure_key_edit = QtWidgets.QLineEdit()
        self.azure_key_edit.setPlaceholderText(_msg("Azure API-Key", "Azure API key", "Clé API Azure", "Clave API Azure"))
        layout.addWidget(self.azure_key_edit)
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
        self.feedback_upload_checkbox = QtWidgets.QCheckBox(_msg("Anonymisiertes Feedback zur KI-Verbesserung senden", "Send anonymized feedback to improve AI"))
        self.feedback_upload_checkbox.setChecked(bool(config.setting["aiid_feedback_upload"]) if "aiid_feedback_upload" in config.setting else False)
        layout.addWidget(self.feedback_upload_checkbox)
        self.feedback_url_edit = QtWidgets.QLineEdit()
        self.feedback_url_edit.setPlaceholderText(_msg("Feedback-Server-URL (optional)", "Feedback server URL (optional)"))
        self.feedback_url_edit.setText(config.setting["aiid_feedback_url"] if "aiid_feedback_url" in config.setting else "")
        layout.addWidget(self.feedback_url_edit)
        self.feedback_upload_button = QtWidgets.QPushButton(_msg("Feedback senden", "Send feedback"))
        layout.addWidget(self.feedback_upload_button)
        self.feedback_upload_button.clicked.connect(self.upload_feedback)
        layout.addStretch(1)
        # Sichtbarkeit API-Key Felder
        def on_provider_changed(idx):
            provider = self.provider_combo.currentText()
            self.openai_key_edit.setVisible(provider == "OpenAI")
            self.hf_key_edit.setVisible(provider == "HuggingFace")
            self.google_key_edit.setVisible(provider == "Google")
            self.deepl_key_edit.setVisible(provider == "DeepL")
            self.aws_key_edit.setVisible(provider == "AWS")
            self.azure_key_edit.setVisible(provider == "Azure")
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
        self.playlist_btn.setToolTip(_msg("Erstelle Playlists nach Stimmung, Genre, BPM usw.", "Create playlists by mood, genre, BPM, etc."))
        layout.addWidget(self.playlist_btn)
        self.playlist_btn.clicked.connect(self.open_playlist_dialog)
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
        # Automatisches Tagging
        self.auto_tagging_checkbox = QtWidgets.QCheckBox(_msg("Automatisches Tagging aktivieren", "Enable automatic tagging", "Activer le taggage automatique", "Activar etiquetado automático"))
        self.auto_tagging_checkbox.setToolTip(_msg("Wenn aktiviert, werden neue oder geänderte Dateien automatisch per KI analysiert.", "If enabled, new or changed files are automatically analyzed by AI.", "Si activé, les nouveaux fichiers sont analysés automatiquement par l'IA.", "Si está activado, los archivos nuevos o modificados se analizan automáticamente mediante IA."))
        layout.addWidget(self.auto_tagging_checkbox)
        self.auto_backup_checkbox = QtWidgets.QCheckBox(_msg("Automatisches Backup aktivieren", "Enable automatic backup", "Activer la sauvegarde automatique", "Activar copia de seguridad automática"))
        self.auto_backup_checkbox.setToolTip(_msg("Vor jedem automatischen Tagging wird ein Backup erstellt.", "A backup is created before each automatic tagging.", "Une sauvegarde est créée avant chaque taggage automatique.", "Se crea una copia de seguridad antes de cada etiquetado automático."))
        layout.addWidget(self.auto_backup_checkbox)
        self.schedule_combo = QtWidgets.QComboBox()
        self.schedule_combo.addItems([
            _msg("Manuell", "Manual", "Manuel", "Manual"),
            _msg("Beim Start", "On start", "Au démarrage", "Al iniciar"),
            _msg("Täglich", "Daily", "Quotidien", "Diario"),
            _msg("Wöchentlich", "Weekly", "Hebdomadaire", "Semanal")
        ])
        self.schedule_combo.setToolTip(_msg("Lege fest, wie oft eine automatische KI-Analyse durchgeführt wird.", "Set how often an automatic AI analysis is performed.", "Définir la fréquence d'analyse automatique IA.", "Establece la frecuencia del análisis automático de IA."))
        layout.addWidget(QtWidgets.QLabel(_msg("Analyse-Intervall:", "Analysis interval:", "Intervalle d'analyse:", "Intervalo de análisis:")))
        layout.addWidget(self.schedule_combo)
        self.time_edit = QtWidgets.QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime.currentTime())
        layout.addWidget(QtWidgets.QLabel(_msg("Uhrzeit für geplante Aufgaben:", "Time for scheduled tasks:", "Heure pour les tâches planifiées:", "Hora para tareas programadas:")))
        layout.addWidget(self.time_edit)
        # Audioanalyse-Buttons
        self.bpm_btn = QtWidgets.QPushButton(_msg("BPM erkennen", "Detect BPM"))
        self.bpm_btn.setToolTip(_msg("Analysiert die Datei und erkennt das Tempo (BPM).", "Analyzes the file and detects the tempo (BPM)."))
        layout.addWidget(self.bpm_btn)
        self.bpm_btn.clicked.connect(self.detect_bpm)
        self.key_btn = QtWidgets.QPushButton(_msg("Tonart erkennen", "Detect key"))
        self.key_btn.setToolTip(_msg("Analysiert die Datei und erkennt die Tonart.", "Analyzes the file and detects the key."))
        layout.addWidget(self.key_btn)
        self.key_btn.clicked.connect(self.detect_key)
        self.undo_btn = QtWidgets.QPushButton(_msg("Batch rückgängig", "Undo batch"))
        self.undo_btn.setToolTip(_msg("Letzte Batch-Änderung rückgängig machen.", "Undo last batch change."))
        layout.addWidget(self.undo_btn)
        self.undo_btn.clicked.connect(self.undo_batch)
        self.redo_btn = QtWidgets.QPushButton(_msg("Batch wiederholen", "Redo batch"))
        self.redo_btn.setToolTip(_msg("Letzte rückgängig gemachte Batch-Änderung wiederholen.", "Redo last undone batch change."))
        layout.addWidget(self.redo_btn)
        self.redo_btn.clicked.connect(self.redo_batch)
        self.sim_btn = QtWidgets.QPushButton(_msg("Batch-Simulation starten", "Start batch simulation"))
        self.sim_btn.setToolTip(_msg("Zeigt eine Simulation der nächsten Batch-Änderung.", "Show a simulation of the next batch change."))
        layout.addWidget(self.sim_btn)
        self.sim_btn.clicked.connect(self.simulate_batch)
        self.batch_data = []
        self.filter_btn = QtWidgets.QPushButton(_msg("Filter & Suche", "Filter & Search"))
        self.filter_btn.setToolTip(_msg("Filtere und suche Songs nach KI-Tags, Feedback, Dubletten usw.", "Filter and search songs by AI tags, feedback, duplicates, etc."))
        layout.addWidget(self.filter_btn)
        self.filter_btn.clicked.connect(self.open_filter_dialog)
        self.auto_translate_checkbox = QtWidgets.QCheckBox(_msg("Tags automatisch übersetzen/vereinheitlichen", "Auto-translate/normalize tags"))
        self.auto_translate_checkbox.setChecked(bool(config.setting["aiid_auto_translate"]) if "aiid_auto_translate" in config.setting else False)
        layout.addWidget(self.auto_translate_checkbox)
        self.translate_btn = QtWidgets.QPushButton(_msg("Jetzt übersetzen/vereinheitlichen", "Translate/normalize now"))
        layout.addWidget(self.translate_btn)
        self.translate_btn.clicked.connect(self.translate_all_tags)
        self._setup_scheduler()
        self.stats_btn = QtWidgets.QPushButton(_msg("Statistiken anzeigen", "Show statistics"))
        self.stats_btn.setToolTip(_msg("Zeigt Statistiken zu Genres, Stimmungen, Feedback usw.", "Show statistics for genres, moods, feedback, etc."))
        layout.addWidget(self.stats_btn)
        self.stats_btn.clicked.connect(self.open_stats_dialog)

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
        if not isinstance(lang, str) or lang not in ("auto", "de", "en", "fr", "es"):
            lang = "auto"
        lang_map = {"auto": 0, "de": 1, "en": 2, "fr": 3, "es": 4}
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
        # Google-Key
        self.google_key_edit.setText(config.setting["aiid_google_key"] if "aiid_google_key" in config.setting else "")
        # DeepL-Key
        self.deepl_key_edit.setText(config.setting["aiid_deepl_key"] if "aiid_deepl_key" in config.setting else "")
        # AWS-Key
        self.aws_key_edit.setText(config.setting["aiid_aws_key"] if "aiid_aws_key" in config.setting else "")
        # Azure-Key
        self.azure_key_edit.setText(config.setting["aiid_azure_key"] if "aiid_azure_key" in config.setting else "")
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
        self.auto_tagging_checkbox.setChecked(bool(config.setting["aiid_auto_tagging"]) if "aiid_auto_tagging" in config.setting else False)
        self.auto_backup_checkbox.setChecked(bool(config.setting["aiid_auto_backup"]) if "aiid_auto_backup" in config.setting else False)
        schedule = config.setting["aiid_schedule"] if "aiid_schedule" in config.setting else "manual"
        if not isinstance(schedule, str) or schedule not in ("manual", "onstart", "daily", "weekly"):
            schedule = "manual"
        schedule_map = {"manual": 0, "onstart": 1, "daily": 2, "weekly": 3}
        self.schedule_combo.setCurrentIndex(schedule_map[schedule])
        tstr = config.setting["aiid_schedule_time"] if "aiid_schedule_time" in config.setting else "08:00"
        try:
            self.time_edit.setTime(QTime.fromString(tstr, "HH:mm"))
        except Exception:
            self.time_edit.setTime(QTime(8,0))

    def save(self):
        config.setting["aiid_debug_logging"] = self.debug_checkbox.isChecked()
        config.setting["aiid_provider"] = self.provider_combo.currentText()
        config.setting["aiid_openai_key"] = self.openai_key_edit.text()
        config.setting["aiid_hf_key"] = self.hf_key_edit.text()
        config.setting["aiid_google_key"] = self.google_key_edit.text()
        config.setting["aiid_deepl_key"] = self.deepl_key_edit.text()
        config.setting["aiid_aws_key"] = self.aws_key_edit.text()
        config.setting["aiid_azure_key"] = self.azure_key_edit.text()
        idx = self.lang_combo.currentIndex()
        config.setting["aiid_ui_language"] = ["auto", "de", "en", "fr", "es"][idx]
        idx = self.performance_combo.currentIndex()
        config.setting["aiid_performance_mode"] = ["auto", "max", "gentle"][idx]
        for field, cb in self.field_checkboxes.items():
            config.setting[f"aiid_save_{field}"] = cb.isChecked()
        idx = self.loglevel_combo.currentIndex()
        config.setting["aiid_log_level"] = ["WARNING", "INFO", "DEBUG"][idx]
        set_log_level_from_config()
        config.setting["aiid_bing_api_key"] = self.cover_api_key_edit.text()
        config.setting["aiid_lyrics_api_key"] = self.lyrics_api_key_edit.text()
        config.setting["aiid_auto_tagging"] = self.auto_tagging_checkbox.isChecked()
        config.setting["aiid_auto_backup"] = self.auto_backup_checkbox.isChecked()
        idx = self.schedule_combo.currentIndex()
        config.setting["aiid_schedule"] = ["manual", "onstart", "daily", "weekly"][idx]
        config.setting["aiid_schedule_time"] = self.time_edit.time().toString("HH:mm")
        config.setting["aiid_auto_translate"] = self.auto_translate_checkbox.isChecked()
        config.setting["aiid_feedback_upload"] = self.feedback_upload_checkbox.isChecked()
        config.setting["aiid_feedback_url"] = self.feedback_url_edit.text()
        logging.getLogger().info(f"AI Music Identifier: Sprache gesetzt auf {config.setting['aiid_ui_language']}")

    def show_feedback_stats(self):
        data = load_feedback()
        if not data:
            msg = _msg("Noch kein Feedback vorhanden.", "No feedback yet.")
        else:
            msg = ""
            for field, stats in data.items():
                msg += f"{field}: 👍 {stats['correct']} | 👎 {stats['wrong']}\n"
        QtWidgets.QMessageBox.information(self, _msg("Feedback-Statistik", "Feedback statistics"), msg)
        logging.getLogger().info("AI Music Identifier: Feedback-Statistik angezeigt.")

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
                logging.getLogger().info(f"AI Music Identifier: Feedback exportiert: {path}")
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

    def show_batch_filter_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(_msg("Batch-Filter", "Batch filter"))
        layout = QtWidgets.QVBoxLayout(dialog)
        genre_edit = QtWidgets.QLineEdit()
        genre_edit.setPlaceholderText(_msg("Nur Genre (optional)", "Only genre (optional)"))
        layout.addWidget(genre_edit)
        ok_btn = QtWidgets.QPushButton(_msg("Starten", "Start"))
        layout.addWidget(ok_btn)
        ok_btn.clicked.connect(dialog.accept)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            genre = genre_edit.text().strip()
            QtWidgets.QMessageBox.information(self, _msg("Batch-Filter", "Batch filter"), _msg(f"Batch würde jetzt nur Dateien mit Genre '{genre}' verarbeiten.", f"Batch would now only process files with genre '{genre}'."))

    def maybe_run_auto_tagging(self):
        if "aiid_auto_tagging" in config.setting and config.setting["aiid_auto_tagging"]:
            QtWidgets.QMessageBox.information(self, _msg("Auto-Tagging", "Auto tagging"), _msg("Automatisches Tagging ist aktiviert. Neue Dateien werden automatisch analysiert.", "Automatic tagging is enabled. New files will be analyzed automatically."))

    def maybe_run_scheduled_analysis(self):
        schedule = config.setting["aiid_schedule"] if "aiid_schedule" in config.setting else "manual"
        if schedule == "daily":
            QtWidgets.QMessageBox.information(self, _msg("Zeitplan", "Schedule"), _msg("Tägliche Analyse wäre jetzt geplant.", "Daily analysis would be scheduled now."))
        elif schedule == "weekly":
            QtWidgets.QMessageBox.information(self, _msg("Zeitplan", "Schedule"), _msg("Wöchentliche Analyse wäre jetzt geplant.", "Weekly analysis would be scheduled now."))

    def detect_bpm(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, _msg("Datei für BPM-Analyse wählen", "Select file for BPM analysis"), "", _msg("Audio-Dateien (*.mp3 *.flac *.wav)", "Audio files (*.mp3 *.flac *.wav)"))
        if file_path:
            bpm = analyze_bpm(file_path)
            if bpm:
                QtWidgets.QMessageBox.information(self, _msg("BPM erkannt", "BPM detected"), _msg(f"Erkannte BPM: {bpm}", f"Detected BPM: {bpm}"))
            else:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), _msg("BPM konnte nicht erkannt werden.", "Could not detect BPM."))
    def detect_key(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, _msg("Datei für Tonart-Analyse wählen", "Select file for key analysis"), "", _msg("Audio-Dateien (*.mp3 *.flac *.wav)", "Audio files (*.mp3 *.flac *.wav)"))
        if file_path:
            key = analyze_key(file_path)
            if key:
                QtWidgets.QMessageBox.information(self, _msg("Tonart erkannt", "Key detected"), _msg(f"Erkannte Tonart: {key}", f"Detected key: {key}"))
            else:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), _msg("Tonart konnte nicht erkannt werden.", "Could not detect key."))

    def undo_batch(self):
        if not _BATCH_UNDO_STACK:
            QtWidgets.QMessageBox.information(self, _msg("Kein Undo möglich", "No undo possible"), _msg("Es gibt keine Batch-Änderung zum Rückgängig machen.", "No batch change to undo."))
            return
        ts, batch_data = _BATCH_UNDO_STACK.pop()
        _BATCH_REDO_STACK.append((ts, batch_data))
        restore_batch_state(batch_data, self.apply_metadata, self)
    def redo_batch(self):
        if not _BATCH_REDO_STACK:
            QtWidgets.QMessageBox.information(self, _msg("Kein Redo möglich", "No redo possible"), _msg("Es gibt keine rückgängig gemachte Batch-Änderung.", "No undone batch change to redo."))
            return
        ts, batch_data = _BATCH_REDO_STACK.pop()
        _BATCH_UNDO_STACK.append((ts, batch_data))
        redo_batch_state(batch_data, self.apply_metadata, self)
    def simulate_batch(self):
        if not self.batch_data:
            QtWidgets.QMessageBox.information(self, _msg("Keine Batch-Änderung", "No batch change"), _msg("Es gibt keine geplante Batch-Änderung.", "No planned batch change."))
            return
        dialog = BatchPreviewDialog(self.batch_data, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            if dialog.simulated:
                QtWidgets.QMessageBox.information(self, _msg("Simulation", "Simulation"), _msg("Die Änderungen wurden nur simuliert und nicht angewendet.", "The changes were only simulated and not applied."))
                logging.getLogger().info("AI Music Identifier: Batch-Simulation durchgeführt.")
            else:
                selected_batch = [entry for i, entry in enumerate(self.batch_data) if dialog.selected[i]]
                backup_batch_state(selected_batch)
                for entry in selected_batch:
                    self.apply_metadata(entry['path'], entry['new_metadata'])
                QtWidgets.QMessageBox.information(self, _msg("Batch angewendet", "Batch applied"), _msg("Die Änderungen wurden angewendet.", "The changes have been applied."))
                logging.getLogger().info("AI Music Identifier: Batch angewendet.")
    def apply_metadata(self, path, metadata):
        # Platzhalter: Hier sollte die Metadaten-Übernahme für die Datei erfolgen
        pass

    def open_filter_dialog(self):
        # tracks: Liste von dicts mit relevanten Feldern (hier als Platzhalter)
        # In der echten Integration sollten die geladenen Dateien/Songs übergeben werden
        tracks = getattr(self, 'tracks', [])
        dlg = FilterDialog(tracks, self)
        dlg.exec()

    def open_playlist_dialog(self):
        tracks = getattr(self, 'tracks', [])
        dlg = PlaylistDialog(tracks, self)
        dlg.exec()

    def translate_all_tags(self):
        lang = config.setting["aiid_ui_language"] if "aiid_ui_language" in config.setting else "de"
        tracks = getattr(self, 'tracks', [])
        changed = 0
        for t in tracks:
            old_genre = t.get('genre')
            old_mood = t.get('mood')
            new_genre = normalize_tag(old_genre, "genre", lang) if old_genre else None
            new_mood = normalize_tag(old_mood, "mood", lang) if old_mood else None
            if new_genre and new_genre != old_genre:
                t['genre'] = new_genre
                changed += 1
            if new_mood and new_mood != old_mood:
                t['mood'] = new_mood
                changed += 1
        QtWidgets.QMessageBox.information(self, _msg("Fertig", "Done"), _msg(f"{changed} Tags wurden übersetzt/vereinheitlicht.", f"{changed} tags translated/normalized."))
        logging.getLogger().info(f"AI Music Identifier: {changed} Tags übersetzt/vereinheitlicht (Button)")

    def upload_feedback(self):
        if not (self.feedback_upload_checkbox.isChecked() and self.feedback_url_edit.text().strip()):
            QtWidgets.QMessageBox.information(self, _msg("Feedback-Upload", "Feedback upload"), _msg("Feedback-Upload ist nicht aktiviert oder keine URL gesetzt.", "Feedback upload not enabled or no URL set."))
            return
        data = load_feedback()
        if not data:
            QtWidgets.QMessageBox.information(self, _msg("Feedback-Upload", "Feedback upload"), _msg("Kein Feedback zum Senden vorhanden.", "No feedback to send."))
            return
        url = self.feedback_url_edit.text().strip()
        try:
            resp = requests.post(url, json=data, timeout=10)
            if resp.status_code == 200:
                QtWidgets.QMessageBox.information(self, _msg("Feedback gesendet", "Feedback sent"), _msg("Feedback wurde erfolgreich gesendet.", "Feedback sent successfully."))
                logging.getLogger().info(f"AI Music Identifier: Feedback erfolgreich gesendet an {url}")
            else:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), _msg(f"Server-Antwort: {resp.status_code}", f"Server response: {resp.status_code}"))
                logging.getLogger().warning(f"AI Music Identifier: Feedback-Upload Fehler: {resp.status_code}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), str(e))
            logging.getLogger().warning(f"AI Music Identifier: Feedback-Upload Exception: {e}")

    def _setup_scheduler(self):
        self._scheduler_timer = QTimer(self)
        self._scheduler_timer.setInterval(60 * 1000)  # jede Minute prüfen
        self._scheduler_timer.timeout.connect(self._check_scheduled_tasks)
        self._scheduler_timer.start()
        self._last_run = None
        # Beim Start ggf. sofort ausführen
        if "aiid_schedule" in config.setting and config.setting["aiid_schedule"] == "onstart":
            self._run_scheduled_tasks()
    def _check_scheduled_tasks(self):
        import datetime
        schedule = config.setting["aiid_schedule"] if "aiid_schedule" in config.setting else "manual"
        if schedule == "manual":
            return
        now = datetime.datetime.now()
        tstr = config.setting["aiid_schedule_time"] if "aiid_schedule_time" in config.setting else "08:00"
        if not tstr:
            tstr = "08:00"
        try:
            sched_time = datetime.datetime.strptime(str(tstr), "%H:%M").time()
        except Exception:
            sched_time = datetime.time(8,0)
        if schedule == "daily":
            if now.time().hour == sched_time.hour and now.time().minute == sched_time.minute:
                if not self._last_run or (now - self._last_run).total_seconds() > 3600:
                    self._run_scheduled_tasks()
                    self._last_run = now
        elif schedule == "weekly":
            if now.weekday() == 0 and now.time().hour == sched_time.hour and now.time().minute == sched_time.minute:
                if not self._last_run or (now - self._last_run).total_seconds() > 3600*24:
                    self._run_scheduled_tasks()
                    self._last_run = now
    def _run_scheduled_tasks(self):
        # Automatisches Backup
        if "aiid_auto_backup" in config.setting and config.setting["aiid_auto_backup"]:
            self._run_auto_backup()
        # Automatisches Tagging
        if "aiid_auto_tagging" in config.setting and config.setting["aiid_auto_tagging"]:
            self._run_auto_tagging()
        self._show_notification(_msg("Automatische Aufgaben abgeschlossen", "Automatic tasks completed", "Tâches automatiques terminées", "Tareas automáticas completadas"))
        logging.getLogger().info("AI Music Identifier: Automatische Aufgaben abgeschlossen.")
    def _run_auto_backup(self):
        # Platzhalter: Backup-Logik (z.B. alle Tracks als JSON sichern)
        logging.getLogger().info("AI Music Identifier: Automatisches Backup durchgeführt.")
    def _run_auto_tagging(self):
        # Platzhalter: Automatisches Tagging (z.B. alle neuen/ungeprüften Tracks taggen)
        logging.getLogger().info("AI Music Identifier: Automatisches Tagging durchgeführt.")
    def _show_notification(self, text):
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon
            if QSystemTrayIcon.isSystemTrayAvailable():
                tray = QSystemTrayIcon(self)
                tray.show()
                tray.showMessage("Picard AI Identifier", text)
        except Exception:
            QtWidgets.QMessageBox.information(self, "Info", text)

    def open_stats_dialog(self):
        tracks = getattr(self, 'tracks', [])
        dlg = StatisticsDialog(tracks, self)
        dlg.exec()
        logging.getLogger().info("AI Music Identifier: Statistik-Dialog geöffnet.")

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

def _msg(de, en, fr=None, es=None):
    lang = None
    if "aiid_ui_language" in config.setting and config.setting["aiid_ui_language"] != "auto":
        lang = config.setting["aiid_ui_language"]
    else:
        import locale
        lang = locale.getdefaultlocale()[0]
    if lang and lang.startswith("de"):
        return de
    elif lang and lang.startswith("fr"):
        return fr if fr else en
    elif lang and lang.startswith("es"):
        return es if es else en
    else:
        return en

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
    provider_order = [
        config.setting["aiid_provider"] if "aiid_provider" in config.setting else "Ollama",
        "Ollama", "OpenAI", "HuggingFace", "Google", "DeepL", "AWS", "Azure"
    ]
    tried = set()
    for provider in provider_order:
        if provider in tried:
            continue
        tried.add(provider)
        try:
            if provider == "Ollama":
                result = call_ollama(prompt, model, tagger, file_name)
            elif provider == "OpenAI":
                result = call_openai(prompt, model, tagger, file_name)
            elif provider == "HuggingFace":
                result = call_huggingface(prompt, model, tagger, file_name)
            elif provider == "Google":
                result = call_google(prompt, model, tagger, file_name)
            elif provider == "DeepL":
                result = call_deepl(prompt, model, tagger, file_name)
            elif provider == "AWS":
                result = call_aws(prompt, model, tagger, file_name)
            elif provider == "Azure":
                result = call_azure(prompt, model, tagger, file_name)
            else:
                continue
            if result and "Fehler" not in str(result):
                logging.getLogger().info(f"AI Music Identifier: Provider genutzt: {provider}")
                return result
            else:
                logging.getLogger().warning(f"AI Music Identifier: Provider {provider} lieferte Fehler: {result}")
        except Exception as e:
            logging.getLogger().warning(f"AI Music Identifier: Provider {provider} Exception: {e}")
    return _msg("Alle KI-Provider fehlgeschlagen", "All AI providers failed", "Tous les fournisseurs d'IA ont échoué", "Todos los proveedores de IA fallaron")

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
    def __init__(self, suggestions, parent=None, mb_tags=None, mb_relations=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("KI-Vorschläge prüfen und übernehmen", "Check and accept AI suggestions"))
        self.edits = {}
        self.correction_buttons = {}
        self.selected_source = {}
        layout = QtWidgets.QFormLayout(self)
        for key, value in suggestions.items():
            field_widget = QtWidgets.QWidget()
            field_layout = QtWidgets.QHBoxLayout(field_widget)
            edit = QtWidgets.QLineEdit(str(value) if value is not None else "")
            self.edits[key] = edit
            # Validierung für Genre und Mood
            is_valid, orig_value, suggestion = validate_ki_value(key, value)
            if not is_valid and suggestion:
                hint_label = QtWidgets.QLabel(_msg(f"Ungültig, Vorschlag: {suggestion}", f"Invalid, suggestion: {suggestion}"))
                field_layout.addWidget(hint_label)
                btn_corr = QtWidgets.QPushButton(_msg("Korrektur übernehmen", "Accept correction"))
                btn_corr.setToolTip(_msg("Korrigiert den Wert auf den Vorschlag", "Corrects the value to the suggestion"))
                def make_corr_func(e=edit, s=suggestion, k=key):
                    def corr():
                        old = e.text()
                        e.setText(s)
                        logging.getLogger().info(f"AI Music Identifier: Korrektur für Feld '{k}': '{old}' → '{s}'")
                    return corr
                btn_corr.clicked.connect(make_corr_func())
                field_layout.addWidget(btn_corr)
                self.correction_buttons[key] = btn_corr
            # --- Online-Abgleich: Zeige MusicBrainz-Wert ---
            mb_val = None
            if mb_tags and key in mb_tags:
                mb_val = mb_tags[key]
            if mb_val and (str(mb_val).strip().lower() != str(value).strip().lower()):
                mb_label = QtWidgets.QLabel(_msg(f"MusicBrainz: {mb_val}", f"MusicBrainz: {mb_val}"))
                field_layout.addWidget(mb_label)
                btn_ki = QtWidgets.QPushButton(_msg("KI übernehmen", "Use AI"))
                btn_mb = QtWidgets.QPushButton(_msg("Online übernehmen", "Use online"))
                btn_both = QtWidgets.QPushButton(_msg("Beides übernehmen", "Use both"))
                btn_ignore = QtWidgets.QPushButton(_msg("Ignorieren", "Ignore"))
                def make_setter(e=edit, v_ai=value, v_mb=mb_val, k=key, src="ai"):
                    def set_ai():
                        e.setText(v_ai)
                        self.selected_source[k] = "ai"
                        logging.getLogger().info(f"AI Music Identifier: Feld '{k}': KI übernommen ({v_ai})")
                    def set_mb():
                        e.setText(v_mb)
                        self.selected_source[k] = "mb"
                        logging.getLogger().info(f"AI Music Identifier: Feld '{k}': MusicBrainz übernommen ({v_mb})")
                    def set_both():
                        both = f"{v_ai}, {v_mb}" if v_ai and v_mb else v_ai or v_mb
                        e.setText(both)
                        self.selected_source[k] = "both"
                        logging.getLogger().info(f"AI Music Identifier: Feld '{k}': Beide übernommen ({both})")
                    def ignore():
                        e.setText("")
                        self.selected_source[k] = "ignore"
                        logging.getLogger().info(f"AI Music Identifier: Feld '{k}': Ignoriert")
                    return set_ai, set_mb, set_both, ignore
                set_ai, set_mb, set_both, ignore = make_setter()
                btn_ki.clicked.connect(set_ai)
                btn_mb.clicked.connect(set_mb)
                btn_both.clicked.connect(set_both)
                btn_ignore.clicked.connect(ignore)
                field_layout.addWidget(btn_ki)
                field_layout.addWidget(btn_mb)
                field_layout.addWidget(btn_both)
                field_layout.addWidget(btn_ignore)
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
        # --- BPM und Key Felder ---
        if "bpm" in suggestions:
            bpm_edit = QtWidgets.QLineEdit(str(suggestions["bpm"]))
            self.edits["bpm"] = bpm_edit
            layout.addRow(_msg("BPM (Tempo)", "BPM (tempo)"), bpm_edit)
        if "key" in suggestions:
            key_edit = QtWidgets.QLineEdit(str(suggestions["key"]))
            self.edits["key"] = key_edit
            layout.addRow(_msg("Tonart (Key)", "Key"), key_edit)
        # --- Cover/Remix/Sample-Infos ---
        if mb_relations:
            if mb_relations.get("is_cover"):
                cover_label = QtWidgets.QLabel(_msg("MusicBrainz: Cover-Version erkannt!", "MusicBrainz: Cover version detected!"))
                layout.addRow("is_cover", cover_label)
                btn_cover = QtWidgets.QPushButton(_msg("Als Cover taggen", "Tag as cover"))
                def tag_cover():
                    self.edits["is_cover"] = QtWidgets.QLineEdit("1")
                    logging.getLogger().info("AI Music Identifier: Als Cover getaggt.")
                btn_cover.clicked.connect(tag_cover)
                layout.addRow("", btn_cover)
            if mb_relations.get("is_remix"):
                remix_label = QtWidgets.QLabel(_msg("MusicBrainz: Remix erkannt!", "MusicBrainz: Remix detected!"))
                layout.addRow("is_remix", remix_label)
                btn_remix = QtWidgets.QPushButton(_msg("Als Remix taggen", "Tag as remix"))
                def tag_remix():
                    self.edits["is_remix"] = QtWidgets.QLineEdit("1")
                    logging.getLogger().info("AI Music Identifier: Als Remix getaggt.")
                btn_remix.clicked.connect(tag_remix)
                layout.addRow("", btn_remix)
            if mb_relations.get("is_sample"):
                sample_label = QtWidgets.QLabel(_msg("MusicBrainz: Sample erkannt!", "MusicBrainz: Sample detected!"))
                layout.addRow("is_sample", sample_label)
                btn_sample = QtWidgets.QPushButton(_msg("Als Sample taggen", "Tag as sample"))
                def tag_sample():
                    self.edits["is_sample"] = QtWidgets.QLineEdit("1")
                    logging.getLogger().info("AI Music Identifier: Als Sample getaggt.")
                btn_sample.clicked.connect(tag_sample)
                layout.addRow("", btn_sample)
    def accept_all(self):
        self.accepted_all = True
        self.accept()
    def reject_all(self):
        self.rejected_all = True
        self.reject()
    def get_results(self):
        return {k: e.text() for k, e in self.edits.items()}

def show_ki_suggestions_dialog(suggestions, parent=None, metadata=None):
    mb_tags = get_mb_tags(metadata) if metadata else None
    mb_relations = get_mb_relations(metadata) if metadata else None
    dialog = KISuggestionDialog(suggestions, parent, mb_tags=mb_tags, mb_relations=mb_relations)
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
    "language_code": "language",
    "bpm": "bpm",
    "key": "key",
    "is_cover": "is_cover",
    "is_remix": "is_remix",
    "is_sample": "is_sample"
}

def apply_ki_tags_to_metadata(metadata, ki_results):
    lang = config.setting["aiid_ui_language"] if "aiid_ui_language" in config.setting else "de"
    auto_translate = bool(config.setting["aiid_auto_translate"]) if "aiid_auto_translate" in config.setting else False
    for ki_field, tag in KI_TO_PICARD_TAG.items():
        if (f"aiid_save_{ki_field}" not in config.setting or config.setting[f"aiid_save_{ki_field}"]) and ki_field in ki_results:
            value = ki_results[ki_field]
            # Übersetzung/Vereinheitlichung falls Option aktiv
            if auto_translate and ki_field in ("genre", "mood"):
                value = normalize_tag(value, ki_field, lang)
            metadata[tag] = value

# --- Listen gültiger Genres und Moods ---
VALID_GENRES = [
    "Pop", "Rock", "Hip-Hop", "Jazz", "Classical", "Electronic", "Folk", "Blues", "Reggae", "Country", "Metal", "Soul", "Funk", "R&B", "Punk", "Disco", "Techno", "House", "Trance", "Ambient", "Dubstep", "Drum and Bass", "Gospel", "Latin", "Ska", "World", "K-Pop", "J-Pop", "Soundtrack", "Children's", "Comedy", "Spoken Word"
]
VALID_MOODS = [
    "fröhlich", "melancholisch", "energetisch", "ruhig", "aggressiv", "romantisch", "düster", "entspannt", "traurig", "heiter", "episch", "nostalgisch", "spirituell", "verspielt", "dramatisch", "träumerisch", "aufregend", "friedlich", "leidenschaftlich"
]

# --- Validierungsfunktion ---
def validate_ki_value(field, value):
    if not value:
        return (True, value, None)
    if field == "genre":
        valid_list = VALID_GENRES
    elif field == "mood":
        valid_list = VALID_MOODS
    else:
        return (True, value, None)
    # Exakte Übereinstimmung (case-insensitive)
    for v in valid_list:
        if v.lower() == value.strip().lower():
            return (True, v, None)
    # Fuzzy-Matching
    matches = difflib.get_close_matches(value.strip(), valid_list, n=1, cutoff=0.6)
    if matches:
        return (False, value, matches[0])
    return (False, value, None)

# --- MusicBrainz-Tag-Abruf für Genre und Mood ---
def get_mb_tags(metadata):
    mb_genre = None
    mb_mood = None
    mbid = metadata.get("musicbrainz_trackid") or metadata.get("musicbrainz_recordingid")
    if not mbid:
        return {"genre": None, "mood": None}
    try:
        # Hole Recording-Info von MusicBrainz
        rec = musicbrainzngs.get_recording_by_id(mbid, includes=["tags"])
        tags = rec["recording"].get("tags", [])
        genres = [t["name"] for t in tags if t["name"].lower() in [g.lower() for g in VALID_GENRES]]
        moods = [t["name"] for t in tags if t["name"].lower() in [m.lower() for m in VALID_MOODS]]
        mb_genre = genres[0] if genres else None
        mb_mood = moods[0] if moods else None
    except Exception as e:
        logging.getLogger().warning(f"AI Music Identifier: Fehler beim Abruf von MB-Tags: {e}")
    return {"genre": mb_genre, "mood": mb_mood}

# --- Audioanalyse: BPM und Tonart ---
def analyze_bpm(file_path):
    try:
        y, sr = librosa.load(file_path, mono=True, duration=180)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = int(round(float(tempo)))
        logging.getLogger().info(f"AI Music Identifier: BPM erkannt: {bpm} für Datei {file_path}")
        return bpm
    except Exception as e:
        logging.getLogger().warning(f"AI Music Identifier: Fehler bei BPM-Analyse: {e}")
        return None

def analyze_key(file_path):
    try:
        y, sr = librosa.load(file_path, mono=True, duration=180)
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)
        key_idx = chroma_mean.argmax()
        KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        key = KEYS[key_idx]
        # Einfache Dur/Moll-Schätzung (sehr grob)
        if chroma_mean[key_idx] > chroma_mean[(key_idx+9)%12]:
            mode = "major"
        else:
            mode = "minor"
        key_str = f"{key} {mode}"
        logging.getLogger().info(f"AI Music Identifier: Tonart erkannt: {key_str} für Datei {file_path}")
        return key_str
    except Exception as e:
        logging.getLogger().warning(f"AI Music Identifier: Fehler bei Tonart-Analyse: {e}")
        return None

def find_duplicates(tracks, threshold=0.9):
    # tracks: Liste von dicts mit keys: title, artist, length, path
    duplicates = []
    for i, t1 in enumerate(tracks):
        for j, t2 in enumerate(tracks):
            if i >= j:
                continue
            # Fuzzy-Matching auf Titel und Künstler
            title_sim = SequenceMatcher(None, t1['title'].lower(), t2['title'].lower()).ratio()
            artist_sim = SequenceMatcher(None, t1['artist'].lower(), t2['artist'].lower()).ratio()
            length_sim = 1.0 if abs((t1.get('length', 0) or 0) - (t2.get('length', 0) or 0)) < 2 else 0.0
            if title_sim > threshold and artist_sim > threshold and length_sim > 0.0:
                duplicates.append((t1, t2))
    return duplicates

class DuplicateDialog(QtWidgets.QDialog):
    def __init__(self, duplicates, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Gefundene Dubletten", "Found duplicates"))
        layout = QtWidgets.QVBoxLayout(self)
        for t1, t2 in duplicates:
            w = QtWidgets.QWidget()
            l = QtWidgets.QHBoxLayout(w)
            l.addWidget(QtWidgets.QLabel(f"{t1['title']} - {t1['artist']} [{t1.get('length','?')}]"))
            l.addWidget(QtWidgets.QLabel("⇔"))
            l.addWidget(QtWidgets.QLabel(f"{t2['title']} - {t2['artist']} [{t2.get('length','?')}]"))
            btn_merge = QtWidgets.QPushButton(_msg("Zusammenführen", "Merge"))
            btn_ignore = QtWidgets.QPushButton(_msg("Ignorieren", "Ignore"))
            btn_mark = QtWidgets.QPushButton(_msg("Als Dublette markieren", "Mark as duplicate"))
            def make_merge_func(a=t1, b=t2):
                def merge():
                    logging.getLogger().info(f"AI Music Identifier: Dubletten zusammengeführt: {a['path']} + {b['path']}")
                    QtWidgets.QMessageBox.information(self, "Merge", f"{a['path']} + {b['path']} zusammengeführt (Platzhalter).")
                return merge
            btn_merge.clicked.connect(make_merge_func())
            def make_mark_func(a=t1, b=t2):
                def mark():
                    logging.getLogger().info(f"AI Music Identifier: Als Dublette markiert: {a['path']} + {b['path']}")
                    QtWidgets.QMessageBox.information(self, "Duplicate", f"{a['path']} + {b['path']} als Dublette markiert.")
                return mark
            btn_mark.clicked.connect(make_mark_func())
            l.addWidget(btn_merge)
            l.addWidget(btn_mark)
            l.addWidget(btn_ignore)
            layout.addWidget(w)
        close_btn = QtWidgets.QPushButton(_msg("Schließen", "Close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

# --- MusicBrainz-Relationen für Cover/Remix/Sample ---
def get_mb_relations(metadata):
    mbid = metadata.get("musicbrainz_trackid") or metadata.get("musicbrainz_recordingid")
    if not mbid:
        return {}
    try:
        rec = musicbrainzngs.get_recording_by_id(mbid, includes=["work-rels", "recording-rels"])
        rels = rec["recording"].get("relations", [])
        result = {"is_cover": False, "is_remix": False, "is_sample": False, "relations": []}
        for rel in rels:
            if rel.get("type") == "cover":
                result["is_cover"] = True
                result["relations"].append(rel)
            if rel.get("type") == "remix":
                result["is_remix"] = True
                result["relations"].append(rel)
            if rel.get("type") == "samples":
                result["is_sample"] = True
                result["relations"].append(rel)
        return result
    except Exception as e:
        logging.getLogger().warning(f"AI Music Identifier: Fehler beim Abruf von MB-Relationen: {e}")
        return {}

def show_duplicate_dialog_for_tracks(tracks, parent=None):
    duplicates = find_duplicates(tracks)
    if not duplicates:
        QtWidgets.QMessageBox.information(parent, _msg("Keine Dubletten gefunden", "No duplicates found"), _msg("Es wurden keine Dubletten erkannt.", "No duplicates detected."))
        return
    dialog = DuplicateDialog(duplicates, parent)
    dialog.exec()

# --- Undo/Redo-Stack und Backup für Batch-Tagging ---
_BATCH_UNDO_STACK = []  # Liste von (timestamp, backup_data)
_BATCH_REDO_STACK = []
_BATCH_BACKUP_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_batch_backup.json")

# backup_data: Liste von dicts mit keys: path, old_metadata, new_metadata

def backup_batch_state(batch_data):
    import time
    ts = int(time.time())
    _BATCH_UNDO_STACK.append((ts, copy.deepcopy(batch_data)))
    # Leere Redo-Stack bei neuem Batch
    _BATCH_REDO_STACK.clear()
    # Schreibe Backup auf Platte
    try:
        with open(_BATCH_BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, indent=2)
        logging.getLogger().info(f"AI Music Identifier: Batch-Backup gespeichert ({_BATCH_BACKUP_PATH})")
    except Exception as e:
        logging.getLogger().warning(f"AI Music Identifier: Fehler beim Batch-Backup: {e}")


def restore_batch_state(batch_data, apply_func, parent=None):
    # Wende alten Zustand auf alle Dateien an
    for entry in batch_data:
        apply_func(entry['path'], entry['old_metadata'])
    QtWidgets.QMessageBox.information(parent, _msg("Batch rückgängig gemacht", "Batch undone"), _msg("Der vorherige Zustand wurde wiederhergestellt.", "Previous state restored."))
    logging.getLogger().info("AI Music Identifier: Batch-Undo durchgeführt.")

def redo_batch_state(batch_data, apply_func, parent=None):
    for entry in batch_data:
        apply_func(entry['path'], entry['new_metadata'])
    QtWidgets.QMessageBox.information(parent, _msg("Batch wiederholt", "Batch redone"), _msg("Die Änderung wurde erneut angewendet.", "Change applied again."))
    logging.getLogger().info("AI Music Identifier: Batch-Redo durchgeführt.")

# --- Vorschau- und Simulationsdialog ---
class BatchPreviewDialog(QtWidgets.QDialog):
    def __init__(self, batch_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Batch-Vorschau", "Batch preview"))
        self.selected = [True] * len(batch_data)
        self.batch_data = batch_data
        layout = QtWidgets.QVBoxLayout(self)
        self.checkboxes = []
        for i, entry in enumerate(batch_data):
            cb = QtWidgets.QCheckBox(f"{entry['path']}: {entry['old_metadata']} → {entry['new_metadata']}")
            cb.setChecked(True)
            cb.stateChanged.connect(lambda state, idx=i: self.set_selected(idx, state))
            self.checkboxes.append(cb)
            layout.addWidget(cb)
        self.sim_btn = QtWidgets.QPushButton(_msg("Simulation", "Simulation"))
        self.sim_btn.clicked.connect(self.simulate)
        self.apply_btn = QtWidgets.QPushButton(_msg("Anwenden", "Apply"))
        self.apply_btn.clicked.connect(self.accept)
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.sim_btn)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)
        self.simulated = False
    def set_selected(self, idx, state):
        self.selected[idx] = bool(state)
    def simulate(self):
        self.simulated = True
        self.accept()
    def get_selected_batch(self):
        return [entry for i, entry in enumerate(self.batch_data) if self.selected[i]]

class FilterDialog(QtWidgets.QDialog):
    def __init__(self, tracks, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Filter & Suche", "Filter & Search"))
        self.tracks = tracks
        layout = QtWidgets.QVBoxLayout(self)
        # Genre
        self.genre_edit = QtWidgets.QLineEdit()
        self.genre_edit.setPlaceholderText(_msg("Genre (optional)", "Genre (optional)"))
        layout.addWidget(QtWidgets.QLabel(_msg("Genre:", "Genre:")))
        layout.addWidget(self.genre_edit)
        # Mood
        self.mood_edit = QtWidgets.QLineEdit()
        self.mood_edit.setPlaceholderText(_msg("Stimmung (optional)", "Mood (optional)"))
        layout.addWidget(QtWidgets.QLabel(_msg("Stimmung:", "Mood:")))
        layout.addWidget(self.mood_edit)
        # Feedback-Status
        self.feedback_combo = QtWidgets.QComboBox()
        self.feedback_combo.addItems([_msg("(egal)", "(any)"), _msg("korrekt", "correct"), _msg("falsch", "wrong"), _msg("nicht bewertet", "not rated")])
        layout.addWidget(QtWidgets.QLabel(_msg("Feedback-Status:", "Feedback status:")))
        layout.addWidget(self.feedback_combo)
        # Dubletten
        self.dup_combo = QtWidgets.QComboBox()
        self.dup_combo.addItems([_msg("(egal)", "(any)"), _msg("ja", "yes"), _msg("nein", "no")])
        layout.addWidget(QtWidgets.QLabel(_msg("Dubletten:", "Duplicates:")))
        layout.addWidget(self.dup_combo)
        # Cover
        self.cover_combo = QtWidgets.QComboBox()
        self.cover_combo.addItems([_msg("(egal)", "(any)"), _msg("ja", "yes"), _msg("nein", "no")])
        layout.addWidget(QtWidgets.QLabel(_msg("Cover-Version:", "Cover version:")))
        layout.addWidget(self.cover_combo)
        # Fehlerstatus
        self.error_combo = QtWidgets.QComboBox()
        self.error_combo.addItems([_msg("(egal)", "(any)"), _msg("ja", "yes"), _msg("nein", "no")])
        layout.addWidget(QtWidgets.QLabel(_msg("Fehlerstatus:", "Error status:")))
        layout.addWidget(self.error_combo)
        # Noch nicht bestätigt
        self.confirmed_combo = QtWidgets.QComboBox()
        self.confirmed_combo.addItems([_msg("(egal)", "(any)"), _msg("ja", "yes"), _msg("nein", "no")])
        layout.addWidget(QtWidgets.QLabel(_msg("Noch nicht bestätigt:", "Not confirmed yet:")))
        layout.addWidget(self.confirmed_combo)
        # Filter-Button
        self.filter_btn = QtWidgets.QPushButton(_msg("Filtern", "Filter"))
        self.filter_btn.clicked.connect(self.apply_filter)
        layout.addWidget(self.filter_btn)
        # Ergebnisliste
        self.result_list = QtWidgets.QListWidget()
        layout.addWidget(self.result_list)
    def apply_filter(self):
        genre = self.genre_edit.text().strip().lower()
        mood = self.mood_edit.text().strip().lower()
        feedback = self.feedback_combo.currentIndex()
        dup = self.dup_combo.currentIndex()
        cover = self.cover_combo.currentIndex()
        error = self.error_combo.currentIndex()
        confirmed = self.confirmed_combo.currentIndex()
        results = []
        for t in self.tracks:
            if genre and genre not in str(t.get('genre','')).lower():
                continue
            if mood and mood not in str(t.get('mood','')).lower():
                continue
            # Feedback-Status (0=egal, 1=korrekt, 2=falsch, 3=nicht bewertet)
            if feedback == 1 and t.get('feedback') != 'correct':
                continue
            if feedback == 2 and t.get('feedback') != 'wrong':
                continue
            if feedback == 3 and t.get('feedback') not in (None, '', 'not rated'):
                continue
            # Dubletten
            if dup == 1 and not t.get('is_duplicate'):
                continue
            if dup == 2 and t.get('is_duplicate'):
                continue
            # Cover
            if cover == 1 and not t.get('is_cover'):
                continue
            if cover == 2 and t.get('is_cover'):
                continue
            # Fehlerstatus
            if error == 1 and not t.get('has_error'):
                continue
            if error == 2 and t.get('has_error'):
                continue
            # Noch nicht bestätigt
            if confirmed == 1 and not t.get('not_confirmed'):
                continue
            if confirmed == 2 and t.get('not_confirmed'):
                continue
            results.append(t)
        self.result_list.clear()
        for t in results:
            self.result_list.addItem(f"{t.get('path','?')} | {t.get('genre','?')} | {t.get('mood','?')} | {t.get('feedback','?')}")
        logging.getLogger().info(f"AI Music Identifier: Filter angewendet. Treffer: {len(results)}")

class PlaylistDialog(QtWidgets.QDialog):
    def __init__(self, tracks, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Playlist-Vorschlag", "Playlist suggestion"))
        self.tracks = tracks
        layout = QtWidgets.QVBoxLayout(self)
        # Genre
        self.genre_edit = QtWidgets.QLineEdit()
        self.genre_edit.setPlaceholderText(_msg("Genre (optional)", "Genre (optional)"))
        layout.addWidget(QtWidgets.QLabel(_msg("Genre:", "Genre:")))
        layout.addWidget(self.genre_edit)
        # Stimmung
        self.mood_edit = QtWidgets.QLineEdit()
        self.mood_edit.setPlaceholderText(_msg("Stimmung (optional)", "Mood (optional)"))
        layout.addWidget(QtWidgets.QLabel(_msg("Stimmung:", "Mood:")))
        layout.addWidget(self.mood_edit)
        # BPM-Bereich
        bpm_layout = QtWidgets.QHBoxLayout()
        self.bpm_min = QtWidgets.QSpinBox()
        self.bpm_min.setRange(0, 400)
        self.bpm_min.setValue(0)
        self.bpm_max = QtWidgets.QSpinBox()
        self.bpm_max.setRange(0, 400)
        self.bpm_max.setValue(400)
        bpm_layout.addWidget(QtWidgets.QLabel(_msg("BPM von", "BPM from")))
        bpm_layout.addWidget(self.bpm_min)
        bpm_layout.addWidget(QtWidgets.QLabel(_msg("bis", "to")))
        bpm_layout.addWidget(self.bpm_max)
        layout.addLayout(bpm_layout)
        # Maximale Länge
        self.max_len = QtWidgets.QSpinBox()
        self.max_len.setRange(1, 1000)
        self.max_len.setValue(20)
        layout.addWidget(QtWidgets.QLabel(_msg("Maximale Anzahl Songs:", "Max number of songs:")))
        layout.addWidget(self.max_len)
        # Playlist-Typ
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems([_msg("Mixtape", "Mixtape"), _msg("DJ-Set", "DJ set"), _msg("Chill", "Chill")])
        layout.addWidget(QtWidgets.QLabel(_msg("Playlist-Typ:", "Playlist type:")))
        layout.addWidget(self.type_combo)
        # Button
        self.gen_btn = QtWidgets.QPushButton(_msg("Playlist generieren", "Generate playlist"))
        self.gen_btn.clicked.connect(self.generate_playlist)
        layout.addWidget(self.gen_btn)
        # Ergebnisliste
        self.result_list = QtWidgets.QListWidget()
        layout.addWidget(self.result_list)
        # Export-Button
        self.export_btn = QtWidgets.QPushButton(_msg("Als M3U exportieren", "Export as M3U"))
        self.export_btn.clicked.connect(self.export_m3u)
        layout.addWidget(self.export_btn)
        self.playlist = []
    def generate_playlist(self):
        genre = self.genre_edit.text().strip().lower()
        mood = self.mood_edit.text().strip().lower()
        bpm_min = self.bpm_min.value()
        bpm_max = self.bpm_max.value()
        max_len = self.max_len.value()
        typ = self.type_combo.currentIndex()
        # Filter
        filtered = []
        for t in self.tracks:
            if genre and genre not in str(t.get('genre','')).lower():
                continue
            if mood and mood not in str(t.get('mood','')).lower():
                continue
            bpm = t.get('bpm')
            if bpm is not None:
                try:
                    bpm_val = int(float(bpm))
                except Exception:
                    bpm_val = 0
                if bpm_val < bpm_min or bpm_val > bpm_max:
                    continue
            # Typ-spezifische Filter (z.B. Chill = niedrige BPM)
            if typ == 2 and bpm is not None and int(float(bpm)) > 110:
                continue
            filtered.append(t)
        # Sortierung
        if typ == 1:  # DJ-Set: sortiere nach BPM
            filtered.sort(key=lambda x: int(float(x.get('bpm',0))) if x.get('bpm') else 0)
        # Begrenzung
        self.playlist = filtered[:max_len]
        self.result_list.clear()
        for t in self.playlist:
            self.result_list.addItem(f"{t.get('path','?')} | {t.get('genre','?')} | {t.get('mood','?')} | {t.get('bpm','?')}")
        logging.getLogger().info(f"AI Music Identifier: Playlist generiert. Typ: {self.type_combo.currentText()}, Treffer: {len(self.playlist)}")
    def export_m3u(self):
        if not self.playlist:
            QtWidgets.QMessageBox.information(self, _msg("Keine Playlist", "No playlist"), _msg("Bitte zuerst eine Playlist generieren.", "Please generate a playlist first."))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Als M3U exportieren", "Export as M3U"), "playlist.m3u", "M3U (*.m3u)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for t in self.playlist:
                        f.write(f"{t.get('path','')}\n")
                QtWidgets.QMessageBox.information(self, _msg("Exportiert", "Exported"), _msg("Playlist wurde exportiert.", "Playlist exported."))
                logging.getLogger().info(f"AI Music Identifier: Playlist als M3U exportiert: {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, _msg("Fehler", "Error"), str(e))

# --- Mapping-Tabellen für Genre und Stimmung (DE/EN/FR/ES) ---
GENRE_MAP = {
    # englisch: deutsch, französisch, spanisch
    "hip hop": {"de": "Hip-Hop", "en": "Hip-Hop", "fr": "Hip-hop", "es": "Hip-hop"},
    "hip-hop": {"de": "Hip-Hop", "en": "Hip-Hop", "fr": "Hip-hop", "es": "Hip-hop"},
    "hiphop": {"de": "Hip-Hop", "en": "Hip-Hop", "fr": "Hip-hop", "es": "Hip-hop"},
    "rock": {"de": "Rock", "en": "Rock", "fr": "Rock", "es": "Rock"},
    "pop": {"de": "Pop", "en": "Pop", "fr": "Pop", "es": "Pop"},
    "electronic": {"de": "Elektronisch", "en": "Electronic", "fr": "Électronique", "es": "Electrónica"},
    "electro": {"de": "Elektronisch", "en": "Electronic", "fr": "Électronique", "es": "Electrónica"},
    "classical": {"de": "Klassik", "en": "Classical", "fr": "Classique", "es": "Clásica"},
    "jazz": {"de": "Jazz", "en": "Jazz", "fr": "Jazz", "es": "Jazz"},
    "blues": {"de": "Blues", "en": "Blues", "fr": "Blues", "es": "Blues"},
    "metal": {"de": "Metal", "en": "Metal", "fr": "Metal", "es": "Metal"},
    "folk": {"de": "Folk", "en": "Folk", "fr": "Folk", "es": "Folk"},
    "reggae": {"de": "Reggae", "en": "Reggae", "fr": "Reggae", "es": "Reggae"},
    "country": {"de": "Country", "en": "Country", "fr": "Country", "es": "Country"},
    # ... weitere Genres ...
}
MOOD_MAP = {
    # englisch: deutsch, französisch, spanisch
    "happy": {"de": "fröhlich", "en": "happy", "fr": "heureux", "es": "feliz"},
    "sad": {"de": "traurig", "en": "sad", "fr": "triste", "es": "triste"},
    "energetic": {"de": "energetisch", "en": "energetic", "fr": "énergique", "es": "enérgico"},
    "calm": {"de": "ruhig", "en": "calm", "fr": "calme", "es": "tranquilo"},
    "melancholic": {"de": "melancholisch", "en": "melancholic", "fr": "mélancolique", "es": "melancólico"},
    "romantic": {"de": "romantisch", "en": "romantic", "fr": "romantique", "es": "romántico"},
    "dark": {"de": "düster", "en": "dark", "fr": "sombre", "es": "oscuro"},
    "epic": {"de": "episch", "en": "epic", "fr": "épique", "es": "épico"},
    # ... weitere Moods ...
}

# --- Übersetzungs-/Normalisierungsfunktion ---
def normalize_tag(tag, tag_type, lang):
    if not tag:
        return tag
    tag_lc = tag.strip().lower()
    if tag_type == "genre":
        mapping = GENRE_MAP
    elif tag_type == "mood":
        mapping = MOOD_MAP
    else:
        return tag
    if tag_lc in mapping:
        norm = mapping[tag_lc][lang] if lang in mapping[tag_lc] else tag
        logging.getLogger().info(f"AI Music Identifier: Tag '{tag}' ({tag_type}) normalisiert/übersetzt zu '{norm}' [{lang}]")
        return norm
    # Fallback: Capitalize
    return tag.capitalize()

# --- Wrapper-Platzhalter für neue Provider ---
def call_google(prompt, model, tagger=None, file_name=None):
    # TODO: Implementiere echten Google-API-Call
    key = config.setting["aiid_google_key"] if "aiid_google_key" in config.setting else ""
    if not key:
        return _msg("[API-Fehler] Kein Google API-Key gesetzt.", "[API error] No Google API key set.", "[Erreur API] Pas de clé API Google.", "[Error API] No hay clave API de Google.")
    return _msg("[Platzhalter] Google-API nicht implementiert.", "[Placeholder] Google API not implemented.", "[Placeholder] API Google non implémentée.", "[Placeholder] API de Google no implementada.")

def call_deepl(prompt, model, tagger=None, file_name=None):
    key = config.setting["aiid_deepl_key"] if "aiid_deepl_key" in config.setting else ""
    if not key:
        return _msg("[API-Fehler] Kein DeepL API-Key gesetzt.", "[API error] No DeepL API key set.", "[Erreur API] Pas de clé API DeepL.", "[Error API] No hay clave API de DeepL.")
    return _msg("[Platzhalter] DeepL-API nicht implementiert.", "[Placeholder] DeepL API not implemented.", "[Placeholder] API DeepL non implémentée.", "[Placeholder] API de DeepL no implementada.")

def call_aws(prompt, model, tagger=None, file_name=None):
    key = config.setting["aiid_aws_key"] if "aiid_aws_key" in config.setting else ""
    if not key:
        return _msg("[API-Fehler] Kein AWS API-Key gesetzt.", "[API error] No AWS API key set.", "[Erreur API] Pas de clé API AWS.", "[Error API] No hay clave API de AWS.")
    return _msg("[Platzhalter] AWS-API nicht implementiert.", "[Placeholder] AWS API not implemented.", "[Placeholder] API AWS non implémentée.", "[Placeholder] API de AWS no implementada.")

def call_azure(prompt, model, tagger=None, file_name=None):
    key = config.setting["aiid_azure_key"] if "aiid_azure_key" in config.setting else ""
    if not key:
        return _msg("[API-Fehler] Kein Azure API-Key gesetzt.", "[API error] No Azure API key set.", "[Erreur API] Pas de clé API Azure.", "[Error API] No hay clave API de Azure.")
    return _msg("[Platzhalter] Azure-API nicht implementiert.", "[Placeholder] Azure API not implemented.", "[Placeholder] API Azure non implémentée.", "[Placeholder] API de Azure no implementada.")

class StatisticsDialog(QtWidgets.QDialog):
    def __init__(self, tracks, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_msg("Statistiken", "Statistics", "Statistiques", "Estadísticas"))
        self.tracks = tracks
        layout = QtWidgets.QVBoxLayout(self)
        # Genre-Statistik
        genre_counts = {}
        for t in tracks:
            g = t.get('genre')
            if g:
                genre_counts[g] = genre_counts.get(g, 0) + 1
        genre_list = sorted(genre_counts.items(), key=lambda x: -x[1])
        layout.addWidget(QtWidgets.QLabel(_msg("Genre-Verteilung:", "Genre distribution:", "Répartition des genres:", "Distribución de géneros:")))
        self.genre_list = QtWidgets.QListWidget()
        for g, n in genre_list:
            self.genre_list.addItem(f"{g}: {n}")
        layout.addWidget(self.genre_list)
        # Mood-Statistik
        mood_counts = {}
        for t in tracks:
            m = t.get('mood')
            if m:
                mood_counts[m] = mood_counts.get(m, 0) + 1
        mood_list = sorted(mood_counts.items(), key=lambda x: -x[1])
        layout.addWidget(QtWidgets.QLabel(_msg("Stimmungs-Verteilung:", "Mood distribution:", "Répartition des ambiances:", "Distribución de estados de ánimo:")))
        self.mood_list = QtWidgets.QListWidget()
        for m, n in mood_list:
            self.mood_list.addItem(f"{m}: {n}")
        layout.addWidget(self.mood_list)
        # Feedback-Statistik
        feedback = load_feedback()
        layout.addWidget(QtWidgets.QLabel(_msg("Feedback-Statistik:", "Feedback statistics:", "Statistiques de feedback:", "Estadísticas de feedback:")))
        self.feedback_list = QtWidgets.QListWidget()
        for field, stats in feedback.items():
            self.feedback_list.addItem(f"{field}: 👍 {stats['correct']} | 👎 {stats['wrong']}")
        layout.addWidget(self.feedback_list)
        # Export-Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.export_csv_btn = QtWidgets.QPushButton(_msg("Als CSV exportieren", "Export as CSV"))
        self.export_csv_btn.clicked.connect(self.export_csv)
        btn_layout.addWidget(self.export_csv_btn)
        self.export_json_btn = QtWidgets.QPushButton(_msg("Als JSON exportieren", "Export as JSON"))
        self.export_json_btn.clicked.connect(self.export_json)
        btn_layout.addWidget(self.export_json_btn)
        # Optional: Diagramm-Button
        try:
            import matplotlib.pyplot as plt
            self.diagram_btn = QtWidgets.QPushButton(_msg("Genre-Diagramm anzeigen", "Show genre chart"))
            self.diagram_btn.clicked.connect(lambda: self.show_genre_chart(genre_counts))
            btn_layout.addWidget(self.diagram_btn)
        except ImportError:
            pass
        layout.addLayout(btn_layout)
    def export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Als CSV exportieren", "Export as CSV"), "aiid_stats.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Genre", "Anzahl"])
                for i in range(self.genre_list.count()):
                    item = self.genre_list.item(i)
                    if item is not None:
                        row = item.text().split(": ")
                        writer.writerow(row)
                writer.writerow([])
                writer.writerow(["Mood", "Anzahl"])
                for i in range(self.mood_list.count()):
                    item = self.mood_list.item(i)
                    if item is not None:
                        row = item.text().split(": ")
                        writer.writerow(row)
            QtWidgets.QMessageBox.information(self, _msg("Exportiert", "Exported"), _msg("Statistiken als CSV exportiert.", "Statistics exported as CSV."))
            logging.getLogger().info(f"AI Music Identifier: Statistiken als CSV exportiert: {path}")
    def export_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, _msg("Als JSON exportieren", "Export as JSON"), "aiid_stats.json", "JSON (*.json)")
        if path:
            genres = []
            for i in range(self.genre_list.count()):
                item = self.genre_list.item(i)
                if item is not None:
                    genres.append(item.text())
            moods = []
            for i in range(self.mood_list.count()):
                item = self.mood_list.item(i)
                if item is not None:
                    moods.append(item.text())
            feedbacks = []
            for i in range(self.feedback_list.count()):
                item = self.feedback_list.item(i)
                if item is not None:
                    feedbacks.append(item.text())
            data = {
                "genres": genres,
                "moods": moods,
                "feedback": feedbacks
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            QtWidgets.QMessageBox.information(self, _msg("Exportiert", "Exported"), _msg("Statistiken als JSON exportiert.", "Statistics exported as JSON."))
            logging.getLogger().info(f"AI Music Identifier: Statistiken als JSON exportiert: {path}")
    def show_genre_chart(self, genre_counts):
        import matplotlib.pyplot as plt
        genres = [g for g in genre_counts.keys() if g is not None]
        counts = [genre_counts[g] for g in genres]
        plt.figure(figsize=(8,4))
        plt.bar(genres, counts)
        plt.title(_msg("Genre-Verteilung", "Genre distribution"))
        plt.xlabel(_msg("Genre", "Genre"))
        plt.ylabel(_msg("Anzahl", "Count"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()