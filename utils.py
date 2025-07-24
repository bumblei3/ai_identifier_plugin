# Hilfsfunktionen für AI Music Identifier Plugin

# pyright: reportMissingImports=false
import difflib
import locale
import logging as std_logging
from PyQt6 import QtWidgets
from .constants import VALID_GENRES, VALID_MOODS
from typing import Any, Optional
from . import picard_logging as logging
import threading
import csv
import json

# Globale Liste für nicht erkannte Songs
unmatched_songs = []

def msg(de: str, en: Optional[str] = None) -> str:
    """
    Gibt die deutsche oder englische Version einer Nachricht zurück (je nach UI-Sprache).
    :param de: Deutsche Nachricht
    :param en: Englische Nachricht (optional)
    :return: Nachricht in passender Sprache
    """
    lang = locale.getdefaultlocale()[0]
    return de if lang and lang.startswith("de") else en if en else de

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

def show_error(tagger: Any, message: Optional[str], message_en: Optional[str] = None) -> None:
    """
    Zeigt eine Fehlermeldung im Log und ggf. in der UI an. Unterstützt Mehrsprachigkeit.
    :param tagger: (optional) Picard-Tagger-Objekt
    :param message: Fehlermeldung (deutsch oder allgemein)
    :param message_en: (optional) Englische Fehlermeldung
    """
    message = message or "Unbekannter Fehler"
    msg_text: str = str(msg(message, message_en) or "Unbekannter Fehler")
    title: str = str(msg("Fehler", "Error") or "Fehler")
    if not msg_text:
        msg_text = "Unbekannter Fehler"
    if not title:
        title = "Fehler"
    title_str: str = title if title is not None else "Fehler"
    msg_str: str = msg_text if msg_text is not None else "Unbekannter Fehler"
    std_logging.getLogger().error(f"AI Music Identifier: {msg_str}")
    # KEINE GUI-Operationen mehr!
    #if tagger and hasattr(tagger, 'window'):
    #    tagger.window.set_statusbar_message(msg_str)
    #    def reset_status():
    #        import time
    #        time.sleep(5)
    #        tagger.window.set_statusbar_message(msg("Bereit", "Ready"))
    #    threading.Thread(target=reset_status, daemon=True).start()
    #QtWidgets.QMessageBox.critical(tagger.window, title_str, msg_str)
    # Stattdessen nur Logging
    std_logging.getLogger().info(f"AI Music Identifier: Fehler gemeldet (nur Log, keine GUI): {msg_str}")

def is_debug_logging() -> bool:
    """
    Gibt True zurück, wenn Debug-Logging in der Picard-Konfiguration aktiviert ist.
    """
    try:
        from picard import config
        return bool(config.setting.get("aiid_debug_logging", False))
    except Exception:
        return False

def handle_acoustid_no_match(file_path, title, artist, length, format, acoustid_id, tagger=None, album=None, tracknumber=None, error_reason=None):
    """
    Loggt und zeigt eine strukturierte Warnung, wenn AcoustID keinen Treffer liefert.
    Nimmt den Song zusätzlich in die globale unmatched_songs-Liste auf.
    :param file_path: Pfad zur Musikdatei
    :param title: Titel
    :param artist: Künstler
    :param length: Länge (Sekunden)
    :param format: Dateiformat (mp3, flac, ...)
    :param acoustid_id: generierter AcoustID-Fingerprint
    :param tagger: (optional) Picard-Tagger-Objekt
    :param album: (optional) Albumname
    :param tracknumber: (optional) Tracknummer
    :param error_reason: (optional) Fehlerursache
    """
    from .picard_logging import log_event
    import time
    log_event(
        "warning",
        msg(
            "AcoustID: Kein Treffer für Datei.",
            "AcoustID: No match for file."
        ),
        file=file_path,
        title=title,
        artist=artist,
        length=length,
        format=format,
        acoustid_id=acoustid_id,
        album=album,
        tracknumber=tracknumber,
        error_reason=error_reason
    )
    unmatched_songs.append({
        "file_path": file_path,
        "title": title,
        "artist": artist,
        "length": length,
        "format": format,
        "acoustid_id": acoustid_id,
        "album": album,
        "tracknumber": tracknumber,
        "error_reason": error_reason or "AcoustID-No-Match",
        "timestamp": int(time.time())
    })
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(
            msg(
                "Kein Treffer in AcoustID/MusicBrainz – evtl. seltener Song, Remix oder unvollständige Metadaten.",
                "No match in AcoustID/MusicBrainz – possibly rare song, remix or incomplete metadata."
            )
        )
    # Automatischer Export nach jedem No-Match
    try:
        from .config import get_setting
        from .picard_logging import log_event
        import os
        csv_path = get_setting("aiid_export_path", "~/unmatched_songs.csv")
        if not isinstance(csv_path, str) or not csv_path:
            csv_path = "~/unmatched_songs.csv"
        csv_path = os.path.expanduser(csv_path)
        json_path = os.path.splitext(csv_path)[0] + ".json"
        html_path = os.path.splitext(csv_path)[0] + "_add_links.html"
        mbjson_path = os.path.splitext(csv_path)[0] + "_musicbrainz_import.json"
        export_unmatched_songs_csv(unmatched_songs, csv_path)
        export_unmatched_songs_json(unmatched_songs, json_path)
        export_unmatched_songs_html(unmatched_songs, html_path)
        export_unmatched_songs_musicbrainz_json(unmatched_songs, mbjson_path)
        summary_de = f"Nicht erkannte Songs exportiert (CSV: {csv_path}, JSON: {json_path}, HTML: {html_path}, MB-JSON: {mbjson_path})"
        summary_en = f"Unmatched songs exported (CSV: {csv_path}, JSON: {json_path}, HTML: {html_path}, MB-JSON: {mbjson_path})"
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg(summary_de, summary_en))
        log_event("info", msg(summary_de, summary_en), csv=csv_path, json=json_path, html=html_path, mbjson=mbjson_path)
        # Automatische KI-Analyse (Genre) im Hintergrund
        import asyncio
        from .ki import get_genre_suggestion
        async def run_ki():
            genre = await get_genre_suggestion(title, artist, tagger, file_path)
            log_event("info", f"KI-Genre-Analyse für No-Match: {title} - {artist} → {genre}", file=file_path, title=title, artist=artist, genre=genre)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(run_ki())
            else:
                loop.run_until_complete(run_ki())
        except Exception as e:
            log_event("error", f"Fehler bei automatischer KI-Analyse nach No-Match: {e}", file=file_path, title=title, artist=artist)
    except Exception as e:
        std_logging.getLogger().error(f"AIID Export nach AcoustID-No-Match fehlgeschlagen: {e}")

def generate_musicbrainz_add_url(title: Optional[str], artist: Optional[str], album: Optional[str] = None, length: Optional[int] = None, acoustid_id: Optional[str] = None) -> str:
    """
    Erzeugt einen vorbefüllten Link zum MusicBrainz-Release-Formular für einen neuen Song.
    :param title: Songtitel
    :param artist: Künstler
    :param album: (optional) Albumname
    :param length: (optional) Länge in Sekunden
    :param acoustid_id: (optional) AcoustID-Fingerprint
    :return: URL als String
    """
    import urllib.parse
    base_url = "https://musicbrainz.org/release/add"
    params = {
        "artist_credit.names.0.name": artist or "",
        "mediums.0.track.0.title": title or "",
    }
    if album:
        params["release.name"] = album
    if length is not None:
        params["mediums.0.track.0.length"] = str(int(length) * 1000)  # ms
    if acoustid_id:
        params["mediums.0.track.0.acoustid_id"] = acoustid_id
    query = urllib.parse.urlencode(params)
    return f"{base_url}?{query}"

def export_unmatched_songs_csv(songs: list, csv_path: str) -> None:
    """
    Exportiert eine Liste von nicht erkannten Songs als CSV mit MusicBrainz-Add-URL.
    :param songs: Liste von Dicts mit Schlüsseln: file_path, title, artist, length, format, acoustid_id, album, tracknumber, error_reason, timestamp
    :param csv_path: Zielpfad für die CSV-Datei
    """
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["file_path", "title", "artist", "album", "tracknumber", "length", "format", "acoustid_id", "error_reason", "timestamp", "musicbrainz_add_url"])
        for song in songs:
            url = generate_musicbrainz_add_url(
                title=song.get("title"),
                artist=song.get("artist"),
                album=song.get("album"),
                length=song.get("length"),
                acoustid_id=song.get("acoustid_id")
            )
            writer.writerow([
                song.get("file_path", ""),
                song.get("title", ""),
                song.get("artist", ""),
                song.get("album", ""),
                song.get("tracknumber", ""),
                song.get("length", ""),
                song.get("format", ""),
                song.get("acoustid_id", ""),
                song.get("error_reason", ""),
                song.get("timestamp", ""),
                url
            ])

def export_all_unmatched_songs(csv_path: str, tagger=None) -> None:
    """
    Exportiert alle gesammelten nicht erkannten Songs als CSV und leert die Liste.
    Zeigt nach Export eine Statusmeldung an (falls tagger übergeben).
    :param csv_path: Zielpfad für die CSV-Datei
    :param tagger: (optional) Picard-Tagger-Objekt
    """
    global unmatched_songs
    export_unmatched_songs_csv(unmatched_songs, csv_path)
    unmatched_songs = []
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(
            msg(
                f"Unmatched-Songs-Report gespeichert: {csv_path}",
                f"Unmatched songs report saved: {csv_path}"
            )
        )

def export_unmatched_songs_json(songs: list, json_path: str) -> None:
    """
    Exportiert eine Liste von nicht erkannten Songs als JSON mit MusicBrainz-Add-URL.
    :param songs: Liste von Dicts mit Schlüsseln: file_path, title, artist, album, tracknumber, length, format, acoustid_id, error_reason, timestamp
    :param json_path: Zielpfad für die JSON-Datei
    """
    out = []
    for song in songs:
        url = generate_musicbrainz_add_url(
            title=song.get("title"),
            artist=song.get("artist"),
            album=song.get("album"),
            length=song.get("length"),
            acoustid_id=song.get("acoustid_id")
        )
        s = dict(song)
        s["musicbrainz_add_url"] = url
        out.append(s)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

def export_all_unmatched_songs_json(json_path: str, tagger=None) -> None:
    """
    Exportiert alle gesammelten nicht erkannten Songs als JSON und leert die Liste.
    Zeigt nach Export eine Statusmeldung an (falls tagger übergeben).
    :param json_path: Zielpfad für die JSON-Datei
    :param tagger: (optional) Picard-Tagger-Objekt
    """
    global unmatched_songs
    export_unmatched_songs_json(unmatched_songs, json_path)
    unmatched_songs = []
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(
            msg(
                f"Unmatched-Songs-Report (JSON) gespeichert: {json_path}",
                f"Unmatched songs report (JSON) saved: {json_path}"
            )
        )

def export_unmatched_songs_html(songs: list, html_path: str) -> None:
    """
    Exportiert eine Liste von nicht erkannten Songs als HTML mit MusicBrainz-Add-Links.
    :param songs: Liste von Dicts mit Songdaten
    :param html_path: Zielpfad für die HTML-Datei
    """
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><title>Unmatched Songs - MusicBrainz Add Links</title></head><body>")
        f.write("<h1>Unmatched Songs – MusicBrainz Add Links</h1>")
        f.write("<ul>")
        for song in songs:
            url = generate_musicbrainz_add_url(
                title=song.get("title"),
                artist=song.get("artist"),
                album=song.get("album"),
                length=song.get("length"),
                acoustid_id=song.get("acoustid_id")
            )
            display = f"{song.get('artist','?')} – {song.get('title','?')}"
            extra = []
            if song.get("album"): extra.append(f"Album: {song['album']}")
            if song.get("tracknumber"): extra.append(f"Track: {song['tracknumber']}")
            if song.get("length"): extra.append(f"Länge: {song['length']}")
            if song.get("error_reason"): extra.append(f"Fehler: {song['error_reason']}")
            if song.get("file_path"): extra.append(f"Datei: {song['file_path']}")
            f.write(f"<li><a href='{url}' target='_blank'>{display}</a>")
            if extra:
                f.write("<ul>")
                for e in extra:
                    f.write(f"<li>{e}</li>")
                f.write("</ul>")
            f.write("</li>")
        f.write("</ul>")
        f.write("<p>Jeder Link öffnet das MusicBrainz-Formular zum Hinzufügen eines neuen Songs mit vorbefüllten Feldern.</p>")
        f.write("</body></html>")

def export_all_unmatched_songs_html(html_path: str, tagger=None) -> None:
    """
    Exportiert alle gesammelten nicht erkannten Songs als HTML und leert die Liste.
    Zeigt nach Export eine Statusmeldung an (falls tagger übergeben).
    :param html_path: Zielpfad für die HTML-Datei
    :param tagger: (optional) Picard-Tagger-Objekt
    """
    global unmatched_songs
    export_unmatched_songs_html(unmatched_songs, html_path)
    unmatched_songs = []
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(
            msg(
                f"Unmatched-Songs-Links (HTML) gespeichert: {html_path}",
                f"Unmatched songs links (HTML) saved: {html_path}"
            )
        )

def export_unmatched_songs_musicbrainz_json(songs: list, json_path: str) -> None:
    """
    Exportiert eine Liste von nicht erkannten Songs als MusicBrainz-Import-JSON (Release mit allen Songs als Tracks).
    :param songs: Liste von Dicts mit Songdaten
    :param json_path: Zielpfad für die JSON-Datei
    """
    # Gruppiere nach Album (Fallback: "Unbekannt")
    from collections import defaultdict
    albums = defaultdict(list)
    for song in songs:
        album = song.get("album") or "Unbekannt"
        albums[album].append(song)
    releases = []
    for album, tracks in albums.items():
        release = {
            "title": album,
            "artist-credit": [{"artist": {"name": tracks[0].get("artist", "Unbekannt")}}],
            "medium-list": [{
                "track-list": [
                    {
                        "title": t.get("title", "Unbekannt"),
                        "length": int(float(t.get("length", 0)) * 1000) if t.get("length") else None,
                        "artist-credit": [{"artist": {"name": t.get("artist", "Unbekannt")}}],
                        "position": t.get("tracknumber") or None
                    }
                    for t in tracks
                ]
            }]
        }
        releases.append(release)
    out = {"release-list": releases}
    with open(json_path, "w", encoding="utf-8") as f:
        import json
        json.dump(out, f, ensure_ascii=False, indent=2)

def export_all_unmatched_songs_musicbrainz_json(json_path: str, tagger=None) -> None:
    """
    Exportiert alle gesammelten nicht erkannten Songs als MusicBrainz-Import-JSON und leert die Liste.
    Zeigt nach Export eine Statusmeldung an (falls tagger übergeben).
    :param json_path: Zielpfad für die JSON-Datei
    :param tagger: (optional) Picard-Tagger-Objekt
    """
    global unmatched_songs
    export_unmatched_songs_musicbrainz_json(unmatched_songs, json_path)
    unmatched_songs = []
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(
            msg(
                f"Unmatched-Songs-Import (MusicBrainz-JSON) gespeichert: {json_path}",
                f"Unmatched songs import (MusicBrainz-JSON) saved: {json_path}"
            )
        )

# Hier können weitere kleine Hilfsfunktionen ergänzt werden
__all__ = ["msg", "show_error", "is_debug_logging", "validate_ki_value"]

def safe_gui_update(tagger, update_func, *args, **kwargs):
    """
    Führt GUI-Updates threadsicher im Main-Thread aus.
    
    Args:
        tagger: Picard Tagger-Objekt
        update_func: Funktion, die im Main-Thread ausgeführt werden soll
        *args, **kwargs: Argumente für update_func
    """
    if not tagger:
        return
        
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        
        # Prüfe, ob wir im Main-Thread sind
        app = QApplication.instance()
        if app and app.thread() == tagger.thread():
            # Wir sind bereits im Main-Thread
            update_func(*args, **kwargs)
        else:
            # Wir sind in einem Worker-Thread - delegiere an Main-Thread
            QTimer.singleShot(0, lambda: update_func(*args, **kwargs))
    except Exception as e:
        # Fallback: Logge den Fehler, aber crashe nicht
        from picard import log
        log.error(f"Fehler bei threadsicherem GUI-Update: {e}")

def safe_statusbar_message(tagger, message):
    """Threadsichere Statusbar-Nachricht."""
    if tagger and hasattr(tagger, 'window'):
        safe_gui_update(tagger, tagger.window.set_statusbar_message, message)

def safe_show_error_dialog(tagger, title, message):
    """Threadsichere Fehler-Dialog-Anzeige."""
    if tagger and hasattr(tagger, 'window'):
        def show_dialog():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(tagger.window, title, message)
        safe_gui_update(tagger, show_dialog)
