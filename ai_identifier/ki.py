# pyright: reportMissingImports=false
# KI-Logik für AI Music Identifier Plugin

from .cache import get_cache, save_cache
from .constants import VALID_GENRES, VALID_MOODS, GENRE_HIERARCHY
from .utils import show_error
from picard import config, log
import time
import difflib
import os
import requests
from PyQt6 import QtWidgets
from typing import Optional
import asyncio
from .providers.ollama import call_ollama as async_call_ollama
from .logging import log_event, log_exception
from .utils import msg

# --- KI-Funktionen ---
async def get_genre_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Liefert einen Genre-Vorschlag für einen Song basierend auf Titel und Künstler.
    Nutzt ggf. den Cache und ruft ansonsten die KI auf.
    :param title: Songtitel
    :param artist: Künstlername
    :param tagger: (optional) Picard-Tagger-Objekt für Statusmeldungen
    :param file_name: (optional) Dateiname für Logging
    :return: Genre als String oder None/Fehlermeldung
    """
    prompt = (
        f"Welches Musikgenre hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit dem Genre, ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_genre::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    log_event("info", "Starte Genre-KI-Request", title=title, artist=artist, model=model)
    if use_cache and cache_key in get_cache():
        v = get_cache()[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log_event("info", "Genre-Vorschlag aus KI-Cache", title=title, artist=artist, value=v['value'], age=age)
            return v["value"]
    else:
        log_event("info", "Kein Cache-Treffer für Genre", title=title, artist=artist, model=model)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Genre-Vorschlag wird berechnet...")
    genre = await call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if genre and "Fehler" not in genre:
        log_event("info", "Genre-Vorschlag von KI", title=title, artist=artist, genre=genre)
        if use_cache:
            get_cache()[cache_key] = {"value": genre, "ts": time.time()}
            save_cache()
            log_event("info", "Genre-Vorschlag im Cache gespeichert", title=title, artist=artist)
    return genre

async def get_style_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Liefert einen Stil-Vorschlag für einen Song basierend auf Titel und Künstler.
    :param title: Songtitel
    :param artist: Künstlername
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Stil als String oder None/Fehlermeldung
    """
    prompt = (
        f"Welcher Musikstil beschreibt den Song '{title}' von '{artist}' am besten? "
        "Antworte nur mit dem Stil (z.B. Synthpop, Hardrock, Trap), ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_style::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in get_cache():
        v = get_cache()[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log_event("info", "Stil aus KI-Cache", title=title, artist=artist, value=v['value'], age=age)
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Stil-Vorschlag wird berechnet...")
    style = await call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if style and "Fehler" not in style:
        log_event("info", "Stil-Vorschlag von KI", title=title, artist=artist, style=style)
        if use_cache:
            get_cache()[cache_key] = {"value": style, "ts": time.time()}
            save_cache()
            log_event("info", "Stil-Vorschlag im Cache gespeichert", title=title, artist=artist)
    return style

async def get_language_code_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Liefert einen ISO-639-1 Sprachcode-Vorschlag für einen Song.
    :param title: Songtitel
    :param artist: Künstlername
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Sprachcode als String oder None/Fehlermeldung
    """
    prompt = (
        f"In welcher Sprache ist der Song '{title}' von '{artist}' gesungen? "
        "Antworte nur mit dem ISO-639-1 Sprachcode (z.B. de, en, es), ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_language_code::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in get_cache():
        v = get_cache()[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log_event("info", "Sprachcode aus KI-Cache", title=title, artist=artist, value=v['value'], age=age)
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Sprachcode-Vorschlag wird berechnet...")
    lang_code = await call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if lang_code and "Fehler" not in lang_code:
        log_event("info", "Sprachcode-Vorschlag von KI", title=title, artist=artist, lang_code=lang_code)
        if use_cache:
            get_cache()[cache_key] = {"value": lang_code, "ts": time.time()}
            save_cache()
            log_event("info", "Sprachcode-Vorschlag im Cache gespeichert", title=title, artist=artist)
    return lang_code

async def call_ai_provider(prompt: str, model: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Ruft den passenden KI-Provider asynchron auf (nur noch Ollama).
    :param prompt: Prompt für die KI
    :param model: Modellname/Provider
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Antwort der KI als String oder Fehlermeldung
    """
    try:
        # Nur noch Ollama zulassen
        if model.startswith("ollama") or model in ("mistral", "llama2", "llama3", "phi3", "gemma", "mixtral"):
            return await async_call_ollama(prompt, model, tagger=tagger, file_name=file_name)
        else:
            msg = f"Unbekannter Provider/Modell: {model}"
            log_event("error", "Unbekannter Provider/Modell", model=model)
            show_error(tagger, msg)
            return msg
    except Exception as e:
        log_exception("Fehler bei KI-Provider", model=model, prompt=prompt, file=file_name, error=str(e))
        show_error(tagger, f"Fehler bei KI-Provider: {e}")
        return str(e)

# Die synchronen call_ollama/call_openai/call_huggingface entfallen, da jetzt async

async def async_batch_genre_suggestions(song_list, tagger=None):
    """
    Holt asynchron Genre-Vorschläge für eine Liste von Songs (Titel, Künstler) von Ollama.
    Die Batch-Größe wird dynamisch angepasst.
    :param song_list: Liste von Dicts mit 'title' und 'artist'
    :param tagger: (optional) Picard-Tagger-Objekt
    :return: Liste der Genre-Vorschläge (in gleicher Reihenfolge wie song_list)
    """
    import time
    from .config import get_setting
    min_batch_raw = get_setting("aiid_batch_min_size", 2)
    min_batch = int(min_batch_raw) if min_batch_raw is not None else 2
    max_batch_raw = get_setting("aiid_batch_max_size", 20)
    max_batch = int(max_batch_raw) if max_batch_raw is not None else 20
    batch_size_raw = get_setting("aiid_batch_start_size", 5)
    batch_size = int(batch_size_raw) if batch_size_raw is not None else 5
    slow_threshold_raw = get_setting("aiid_batch_slow_threshold", 8.0)
    slow_threshold = float(slow_threshold_raw) if slow_threshold_raw is not None else 8.0
    fast_threshold_raw = get_setting("aiid_batch_fast_threshold", 3.0)
    fast_threshold = float(fast_threshold_raw) if fast_threshold_raw is not None else 3.0
    adjust_step_raw = get_setting("aiid_batch_adjust_step", 1)
    adjust_step = int(adjust_step_raw) if adjust_step_raw is not None else 1
    results = []
    i = 0
    while i < len(song_list):
        batch = song_list[i:i+batch_size]
        start = time.time()
        tasks = [get_genre_suggestion(song['title'], song['artist'], tagger) for song in batch]
        batch_results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        results.extend(batch_results)
        # Fehler zählen
        error_count = sum(1 for r in batch_results if r is None or (isinstance(r, str) and "Fehler" in r))
        # Dynamische Anpassung
        if error_count > 0 or elapsed > slow_threshold:
            batch_size = max(min_batch, batch_size - adjust_step)
        elif elapsed < fast_threshold:
            batch_size = min(max_batch, batch_size + adjust_step)
        # Logging
        from .logging import log_event
        from .utils import msg
        log_event("info", msg(
            f"Batch {i//batch_size+1}: {len(batch)} Songs, {elapsed:.1f}s, Fehler: {error_count}, neue Batch-Größe: {batch_size}",
            f"Batch {i//batch_size+1}: {len(batch)} songs, {elapsed:.1f}s, errors: {error_count}, new batch size: {batch_size}"
        ))
        i += len(batch)
    return results

def get_cover_analysis(cover_path: str, title: Optional[str]=None, artist: Optional[str]=None, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Analysiert ein Coverbild (Platzhalter).
    :param cover_path: Pfad zum Coverbild
    :param title: (optional) Songtitel
    :param artist: (optional) Künstlername
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Analyseergebnis als String oder Fehlermeldung
    """
    # Platzhalter für Cover-Analyse
    return "Cover-Analyse (Platzhalter)"

def get_genre_subcategories(genre: str, title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Liefert Subgenre-Vorschläge (Platzhalter).
    :param genre: Genre
    :param title: Songtitel
    :param artist: Künstlername
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Subgenre als String oder Fehlermeldung
    """
    # Platzhalter für Subgenre-Analyse
    return "Subgenre-Analyse (Platzhalter)"

def analyze_key(file_path: str) -> Optional[str]:
    """
    Analysiert die Tonart einer Datei (Platzhalter).
    :param file_path: Pfad zur Musikdatei
    :return: Tonart als String oder Fehlermeldung
    """
    # Platzhalter für Tonart-Analyse
    return "Tonart-Analyse (Platzhalter)" 