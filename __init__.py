# pyright: reportMissingImports=false
# AI Music Identifier Plugin für Picard


from picard import log
from .ki import get_genre_suggestion
from .picard_logging import log_event, log_exception

PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "AI Assistant"
PLUGIN_DESCRIPTION = "Identifiziert Musikdateien per AcoustID und ergänzt Metadaten (inkl. Genre, ISRC, Label, Tracknummer)."
PLUGIN_VERSION = "0.9.2"
PLUGIN_API_VERSIONS = ["3.0"]

_processing_files = False

# Jetzt erst kommt der große try-Block!
try:

    # KI-Analyse als Patch für Track.update
    from picard.track import Track
    _original_update = Track.update

    def aiid_update(self, *args, **kwargs):
        result = _original_update(self, *args, **kwargs)
        file_name = getattr(self, "filename", None)
        metadata = getattr(self, "metadata", None)
        title = metadata.get("title") if metadata else None
        artist = metadata.get("artist") if metadata else None
        log.info("AI Identifier: Track.update-Hook aufgerufen")
        log_event("info", "Track.update-Hook wurde ausgelöst", file=file_name)
        log_event("debug", "Track.update-Hook: Metadaten", title=title, artist=artist, file=file_name)
        try:
            import requests
            if title and artist:
                log_event("info", "KI-Analyse: Starte Request", title=title, artist=artist, file=file_name)
                prompt = f"Bestimme das Genre für: {title} von {artist}."
                response = requests.post(
                    "http://127.0.0.1:11435",
                    json={"prompt": prompt, "model": "mistral"},
                    timeout=30
                )
                log_event("info", "KI-Analyse: Request ausgeführt", title=title, artist=artist, file=file_name)
                response.raise_for_status()
                result_json = response.json()
                genre = result_json.get("result", "Unbekannt")
                log_event("info", "KI-Analyse Ergebnis", genre=genre, title=title, artist=artist, file=file_name)
            else:
                log_event("info", "KI-Analyse übersprungen, da Titel oder Artist fehlen", file=file_name)
        except Exception as e:
            log_event("error", "KI-Analyse Exception", error=str(e), file=file_name)
            log_exception("KI-Analyse Fehler", error=str(e), file=file_name)
        return result

    Track.update = aiid_update
    log.info("AI Identifier: Track.update-Hook registriert")

except Exception as e:
    log.error(f"AI Identifier: Fehler beim Patchen: {e}")

# Am Ende der Datei:
# NICHT direkt aufrufen!
# plugin_loaded()  # <-- Das ruft Picard automatisch auf!
