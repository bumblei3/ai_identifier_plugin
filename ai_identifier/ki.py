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

# --- KI-Funktionen ---
def get_genre_suggestion(title, artist, tagger=None, file_name=None):
    prompt = (
        f"Welches Musikgenre hat der Song '{title}' von '{artist}'? "
        "Antworte nur mit dem Genre, ohne weitere Erklärungen."
    )
    model = str(config.setting["aiid_ollama_model"]) if "aiid_ollama_model" in config.setting else "mistral"
    cache_key = f"ki_genre::{model}::{title}::{artist}"
    use_cache = bool(config.setting["aiid_enable_cache"]) if "aiid_enable_cache" in config.setting else True
    if use_cache and cache_key in get_cache():
        v = get_cache()[cache_key]
        if isinstance(v, dict):
            age = int(time.time() - v["ts"])
            log.info(f"AI Music Identifier: Genre-Vorschlag aus KI-Cache für {title} - {artist}: {v['value']} (Alter: {age}s)")
            return v["value"]
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
    return genre

def get_style_suggestion(title, artist, tagger=None, file_name=None):
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

def get_language_code_suggestion(title, artist, tagger=None, file_name=None):
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

def call_ai_provider(prompt, model, tagger=None, file_name=None):
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

def call_ollama(prompt, model, tagger=None, file_name=None):
    try:
        # Hier würde der echte API-Aufruf stehen
        # raise Exception("Testfehler Ollama")  # Zum Testen
        return "Ollama-Antwort (Platzhalter)"
    except Exception as e:
        show_error(tagger, f"Fehler bei Ollama-Request: {e}")
        return str(e)

def call_openai(prompt, model, tagger=None, file_name=None):
    # Platzhalter für OpenAI-API-Aufruf
    return "OpenAI-Antwort (Platzhalter)"

def call_huggingface(prompt, model, tagger=None, file_name=None):
    # Platzhalter für HuggingFace-API-Aufruf
    return "HuggingFace-Antwort (Platzhalter)"

def get_cover_analysis(cover_path, title=None, artist=None, tagger=None, file_name=None):
    # Platzhalter für Cover-Analyse
    return "Cover-Analyse (Platzhalter)"

def get_genre_subcategories(genre, title, artist, tagger=None, file_name=None):
    # Platzhalter für Subgenre-Analyse
    return "Subgenre-Analyse (Platzhalter)"

def analyze_key(file_path):
    # Platzhalter für Tonart-Analyse
    return "Tonart-Analyse (Platzhalter)" 