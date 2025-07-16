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

# --- KI-Funktionen ---
def get_genre_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
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
    log.info(f"AI Music Identifier: Starte Genre-KI-Request für '{title}' von '{artist}' (Modell: {model})")
    if use_cache and cache_key in get_cache():
        v = get_cache()[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(f"AI Music Identifier: Genre-Vorschlag aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)")
            return v["value"]
    else:
        log.info(f"AI Music Identifier: Kein Cache-Treffer für Genre von '{title}' - '{artist}' (Modell: {model})")
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Genre-Vorschlag wird berechnet...")
    genre = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if genre and "Fehler" not in genre:
        log.info(f"AI Music Identifier: Genre-Vorschlag von KI für {title} - {artist}: {genre}")
        if use_cache:
            get_cache()[cache_key] = {"value": genre, "ts": time.time()}
            save_cache()
            log.info(f"AI Music Identifier: Genre-Vorschlag für '{title}' - '{artist}' im Cache gespeichert.")
    return genre

def get_style_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
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
            log.info(f"AI Music Identifier: Stil aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Stil-Vorschlag wird berechnet...")
    style = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if style and "Fehler" not in style:
        log.info(f"AI Music Identifier: Stil-Vorschlag von KI für {title} - {artist}: {style}")
        if use_cache:
            get_cache()[cache_key] = {"value": style, "ts": time.time()}
            save_cache()
    return style

def get_language_code_suggestion(title: str, artist: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
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
            log.info(f"AI Music Identifier: Sprachcode aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)")
            return v["value"]
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("KI-Sprachcode-Vorschlag wird berechnet...")
    lang_code = call_ai_provider(prompt, model, tagger, file_name)
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message("")
    if lang_code and "Fehler" not in lang_code:
        log.info(f"AI Music Identifier: Sprachcode-Vorschlag von KI für {title} - {artist}: {lang_code}")
        if use_cache:
            get_cache()[cache_key] = {"value": lang_code, "ts": time.time()}
            save_cache()
    return lang_code

def call_ai_provider(prompt: str, model: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Ruft den passenden KI-Provider auf (Ollama, OpenAI, HuggingFace).
    :param prompt: Prompt für die KI
    :param model: Modellname/Provider
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Antwort der KI als String oder Fehlermeldung
    """
    try:
        if model.startswith("ollama"):
            return call_ollama(prompt, model, tagger=tagger, file_name=file_name)
        elif model.startswith("openai"):
            return call_openai(prompt, model, tagger=tagger, file_name=file_name)
        elif model.startswith("hf") or model.startswith("huggingface"):
            return call_huggingface(prompt, model, tagger=tagger, file_name=file_name)
        else:
            msg = f"Unbekannter Provider/Modell: {model}"
            show_error(tagger, msg)
            return msg
    except Exception as e:
        show_error(tagger, f"Fehler bei KI-Provider: {e}")
        return str(e)

def call_ollama(prompt: str, model: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Ruft Ollama-Provider auf (Platzhalter).
    :param prompt: Prompt für die KI
    :param model: Modellname
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Antwort der KI als String oder Fehlermeldung
    """
    try:
        # Hier würde der echte API-Aufruf stehen
        # raise Exception("Testfehler Ollama")  # Zum Testen
        return "Ollama-Antwort (Platzhalter)"
    except Exception as e:
        show_error(tagger, f"Fehler bei Ollama-Request: {e}")
        return str(e)

def call_openai(prompt: str, model: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Ruft OpenAI-Provider auf (Platzhalter).
    :param prompt: Prompt für die KI
    :param model: Modellname
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Antwort der KI als String oder Fehlermeldung
    """
    # Platzhalter für OpenAI-API-Aufruf
    return "OpenAI-Antwort (Platzhalter)"

def call_huggingface(prompt: str, model: str, tagger=None, file_name: Optional[str]=None) -> Optional[str]:
    """
    Ruft HuggingFace-Provider auf (Platzhalter).
    :param prompt: Prompt für die KI
    :param model: Modellname
    :param tagger: (optional) Picard-Tagger-Objekt
    :param file_name: (optional) Dateiname für Logging
    :return: Antwort der KI als String oder Fehlermeldung
    """
    # Platzhalter für HuggingFace-API-Aufruf
    return "HuggingFace-Antwort (Platzhalter)"

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