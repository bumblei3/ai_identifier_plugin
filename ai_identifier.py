from picard import config, log
from picard.metadata import Metadata
import musicbrainzngs
import pyacoustid
from picard.ui.options import OptionsPage
from PyQt5 import QtWidgets
import hashlib

PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "Du"
PLUGIN_DESCRIPTION = """
Identifiziert Musik mit AcoustID und aktualisiert die Track-Metadaten (Titel, Künstler, Album, Veröffentlichungsdatum).
Der AcoustID API-Key kann in den Plugin-Einstellungen gesetzt werden.
"""
PLUGIN_VERSION = "0.9"
PLUGIN_API_VERSIONS = ["2.0", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "3.0"]
PLUGIN_LICENSE = "MIT"
PLUGIN_LICENSE_URL = "https://opensource.org/licenses/MIT"

musicbrainzngs.set_useragent("ai_music_identifier_plugin", "0.9", "dein.email@beispiel.com")

# Caching für identifizierte Dateien (Hash: Metadaten)
_aiid_cache = {}

def _get_api_key():
    return config.setting.get("aiid_acoustid_api_key", "")

def _get_lang():
    return config.setting.get("user_interface_language", "en")[:2]

def _msg(msg_de, msg_en):
    return msg_de if _get_lang() == "de" else msg_en

class AIIDOptionsPage(OptionsPage):
    NAME = "aiid"
    TITLE = "AI Music Identifier"
    PARENT = "plugins"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key_edit.setText(config.setting.get("aiid_acoustid_api_key", ""))
        layout = QtWidgets.QFormLayout()
        layout.addRow("AcoustID API Key:", self.api_key_edit)
        self.setLayout(layout)

    def load(self):
        self.api_key_edit.setText(config.setting.get("aiid_acoustid_api_key", ""))

    def save(self):
        config.setting["aiid_acoustid_api_key"] = self.api_key_edit.text().strip()

#register_options_page(AIIDOptionsPage)

def process_file(tagger, metadata, file):
    log.debug("AI Music Identifier: Entering process_file for %s", file.filename)
    if not file.filename:
        log.error("AI Music Identifier: No file path provided")
        return

    api_key = _get_api_key()
    if not api_key:
        msg = _msg("Bitte AcoustID API-Key in den Plugin-Einstellungen setzen.",
                   "Please set AcoustID API key in the plugin settings.")
        log.error("AI Music Identifier: No valid AcoustID API key configured")
        tagger.window.set_statusbar_message(msg)
        return

    # Caching: Hash über Dateipfad + Größe
    try:
        file_hash = hashlib.sha1((file.filename + str(file.size)).encode("utf-8")).hexdigest()
    except Exception:
        file_hash = None

    if file_hash and file_hash in _aiid_cache:
        cached = _aiid_cache[file_hash]
        metadata.update(cached)
        msg = _msg("Metadaten aus Cache übernommen für %s", "Loaded metadata from cache for %s") % file.filename
        tagger.window.set_statusbar_message(msg)
        log.debug("AI Music Identifier: Used cached metadata for %s", file.filename)
        return

    log.debug("AI Music Identifier: Processing file %s", file.filename)
    try:
        duration, fp = pyacoustid.fingerprint_file(file.filename)
        log.debug("AI Music Identifier: Generated fingerprint for %s (duration: %s)", file.filename, duration)
        results = pyacoustid.lookup(api_key, fp, duration)

        if results and 'results' in results and len(results['results']) > 0:
            result = results['results'][0]
            log.debug("AI Music Identifier: Found AcoustID match: %s", result)

            # Update metadata (nur wenn leer)
            if not metadata["title"]:
                metadata["title"] = result.get("title", metadata["title"])
            if not metadata["artist"]:
                artists = result.get("artists", [{}])
                metadata["artist"] = artists[0].get("name", metadata["artist"]) if artists else metadata["artist"]
            if not metadata["album"]:
                release_groups = result.get("releasegroups", [{}])
                metadata["album"] = release_groups[0].get("title", metadata["album"]) if release_groups else metadata["album"]

            # Fetch additional metadata from MusicBrainz if available
            if "recordings" in result and result["recordings"]:
                mbid = result["recordings"][0].get("id")
                if mbid:
                    try:
                        release = musicbrainzngs.get_recording_by_id(mbid, includes=["releases"])
                        release_list = release["recording"].get("release-list", [])
                        if release_list and not metadata["date"]:
                            metadata["date"] = release_list[0].get("date", metadata["date"])
                        log.debug("AI Music Identifier: Fetched MusicBrainz metadata: %s", metadata)
                    except musicbrainzngs.MusicBrainzError as e:
                        log.warning("AI Music Identifier: Failed to fetch MusicBrainz data for MBID %s: %s", mbid, e)

            # Cache speichern
            if file_hash:
                _aiid_cache[file_hash] = dict(metadata)

            msg = _msg("Metadaten aktualisiert für %s", "Updated metadata for %s") % file.filename
            tagger.window.set_statusbar_message(msg)
            log.debug("AI Music Identifier: Updated metadata: %s", metadata)
        else:
            msg = _msg("Keine Übereinstimmung gefunden für %s", "No matches found for %s") % file.filename
            log.warning("AI Music Identifier: No AcoustID matches found for %s", file.filename)
            tagger.window.set_statusbar_message(msg)

    except pyacoustid.NoBackendError:
        msg = _msg("Chromaprint-Backend nicht gefunden. Bitte libchromaprint installieren.",
                   "Chromaprint backend not found. Please install libchromaprint.")
        log.error("AI Music Identifier: Chromaprint backend not found.")
        tagger.window.set_statusbar_message(msg)
    except pyacoustid.FingerprintGenerationError:
        msg = _msg("Fehler beim Fingerprinting von %s", "Failed to fingerprint %s") % file.filename
        log.error("AI Music Identifier: Failed to generate fingerprint for %s", file.filename)
        tagger.window.set_statusbar_message(msg)
    except pyacoustid.WebServiceError as e:
        msg = _msg("AcoustID API-Fehler für %s", "AcoustID API error for %s") % file.filename
        log.error("AI Music Identifier: AcoustID API error for %s: %s", file.filename, e)
        tagger.window.set_statusbar_message(msg)
    except Exception as e:
        msg = _msg("Fehler bei der Verarbeitung von %s", "Error processing %s") % file.filename
        log.error("AI Music Identifier: Unexpected error for %s: %s", file.filename, e)
        tagger.window.set_statusbar_message(msg)

from picard.extension_points import ExtensionPoint
log.debug("AI Music Identifier: Registering file_post_addition_processor")
ExtensionPoint("file_post_addition_processor").register(__name__, process_file)
log.debug("AI Music Identifier: Registering file_post_save_processor")