PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "Dein Name"
PLUGIN_DESCRIPTION = "Identifiziert Musikdateien per AcoustID und ergänzt Metadaten (inkl. Genre, ISRC, Label, Tracknummer)."
PLUGIN_VERSION = "0.9.1"
PLUGIN_API_VERSIONS = ["3.0"]

from picard import config, log
from picard.metadata import Metadata
import musicbrainzngs
import pyacoustid
from PyQt5 import QtWidgets
import hashlib

_aiid_cache = {}

def _msg(de, en):
    # Einfache Sprachumschaltung
    import locale
    lang = locale.getdefaultlocale()[0]
    return de if lang and lang.startswith("de") else en

def _get_api_key():
    # Hole den AcoustID API-Key aus den Picard-Einstellungen
    return config.setting.get("aiid_acoustid_api_key", "")

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
        item_text = f"{title} – {artists} [{album}]"
        list_widget.addItem(item_text)
    layout.addWidget(list_widget)
    button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    layout.addWidget(button_box)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    dialog.setLayout(layout)
    if dialog.exec_() == QtWidgets.QDialog.Accepted and list_widget.currentRow() >= 0:
        return list_widget.currentRow()
    return None

def fetch_additional_metadata(result, metadata):
    # Genre
    if "tags" in result and not metadata.get("genre"):
        tags = result["tags"]
        if isinstance(tags, list) and tags:
            metadata["genre"] = tags[0]
        elif isinstance(tags, dict) and "name" in tags:
            metadata["genre"] = tags["name"]
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

def file_post_load_processor(tagger, metadata, file):
    print("AIID: process_file called for", getattr(file, "filename", file))
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
            acoustid_results = results['results']
            # Wenn mehr als ein Treffer, Auswahl anzeigen
            if len(acoustid_results) > 1:
                idx = select_result_dialog(acoustid_results, tagger.window)
                if idx is None:
                    msg = _msg("Keine Auswahl getroffen für %s", "No selection made for %s") % file.filename
                    tagger.window.set_statusbar_message(msg)
                    return
                result = acoustid_results[idx]
            else:
                result = acoustid_results[0]
            log.debug("AI Music Identifier: Selected AcoustID match: %s", result)

            # Metadaten immer aktualisieren (auch wenn schon vorhanden)
            metadata["title"] = result.get("title", metadata.get("title", ""))
            artists = result.get("artists", [{}])
            metadata["artist"] = artists[0].get("name", metadata.get("artist", "")) if artists else metadata.get("artist", "")
            release_groups = result.get("releasegroups", [{}])
            metadata["album"] = release_groups[0].get("title", metadata.get("album", "")) if release_groups else metadata.get("album", "")

            # Zusätzliche Felder ergänzen
            fetch_additional_metadata(result, metadata)

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