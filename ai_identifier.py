from picard import config, log
from picard.metadata import Metadata
import musicbrainzngs
import pyacoustid

PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "Du"
PLUGIN_DESCRIPTION = """
Identifies music using AcoustID and updates track metadata with title, artist, album, and release date.
Requires an AcoustID API key (hardcoded in the plugin).
"""
PLUGIN_VERSION = "0.5"
PLUGIN_API_VERSIONS = ["2.0", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "3.0"]
PLUGIN_LICENSE = "MIT"
PLUGIN_LICENSE_URL = "https://opensource.org/licenses/MIT"

# Configure MusicBrainz user agent
musicbrainzngs.set_useragent("ai_music_identifier_plugin", "0.5", "dein.email@beispiel.com")

# Hardcoded AcoustID API key (replace with your own)
ACOUSTID_API_KEY = "YOUR_API_KEY"

def process_file(tagger, metadata, track, path):
    log.debug("AI Music Identifier: Entering process_file for %s", path)
    
    if not path:
        log.error("AI Music Identifier: No file path provided")
        return

    if not ACOUSTID_API_KEY or ACOUSTID_API_KEY == "YOUR_ACOUSTID_API_KEY":
        log.error("AI Music Identifier: No valid AcoustID API key configured")
        tagger.window.set_statusbar_message("AI Music Identifier: Please set a valid AcoustID API key in the plugin code")
        return

    log.debug("AI Music Identifier: Processing file %s", path)
    try:
        # Fingerprint the audio file
        duration, fp = pyacoustid.fingerprint_file(path)
        log.debug("AI Music Identifier: Generated fingerprint for %s (duration: %s)", path, duration)
        results = pyacoustid.lookup(ACOUSTID_API_KEY, fp, duration)
        
        if results and 'results' in results and len(results['results']) > 0:
            result = results['results'][0]
            log.debug("AI Music Identifier: Found AcoustID match: %s", result)
            
            # Update metadata (only if fields are empty)
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
            
            log.debug("AI Music Identifier: Updated metadata: %s", metadata)
            tagger.window.set_statusbar_message("AI Music Identifier: Updated metadata for %s", path)
        else:
            log.warning("AI Music Identifier: No AcoustID matches found for %s", path)
            tagger.window.set_statusbar_message("AI Music Identifier: No matches found for %s", path)
    
    except pyacoustid.NoBackendError:
        log.error("AI Music Identifier: Chromaprint backend not found. Please install libchromaprint.")
        tagger.window.set_statusbar_message("AI Music Identifier: Chromaprint backend not found")
    except pyacoustid.FingerprintGenerationError:
        log.error("AI Music Identifier: Failed to generate fingerprint for %s", path)
        tagger.window.set_statusbar_message("AI Music Identifier: Failed to fingerprint %s", path)
    except pyacoustid.WebServiceError as e:
        log.error("AI Music Identifier: AcoustID API error for %s: %s", path, e)
        tagger.window.set_statusbar_message("AI Music Identifier: AcoustID API error for %s", path)
    except Exception as e:
        log.error("AI Music Identifier: Unexpected error for %s: %s", path, e)
        tagger.window.set_statusbar_message("AI Music Identifier: Error processing %s", path)

# Register the plugin
from picard.extension_points import ExtensionPoint
log.debug("AI Music Identifier: Registering file_post_load_processor")
ExtensionPoint("file_post_load_processor").register(__name__, process_file)
