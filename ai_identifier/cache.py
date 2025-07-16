# pyright: reportMissingImports=false
# Cache-Handling für AI Music Identifier Plugin

import os
import json
import time
import logging
from picard import config
from .utils import show_error
import threading
from typing import Optional, Dict, Any
from . import logging
import logging as std_logging

_aiid_cache = {}
_cache_lock = threading.Lock()

# Speicherort für den Cache (z.B. im Picard-Config-Verzeichnis)
_CACHE_PATH = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_cache.json")

# Standard-Ablaufzeit für Cache (in Tagen)
_DEFAULT_CACHE_EXPIRY_DAYS = 7

def load_cache(tagger=None) -> None:
    """
    Lädt den Cache aus der Cache-Datei und entfernt abgelaufene Einträge.
    :param tagger: (optional) Picard-Tagger-Objekt für Fehlermeldungen
    """
    global _aiid_cache
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                now = time.time()
                expiry_days = int(config.setting["aiid_cache_expiry_days"] or _DEFAULT_CACHE_EXPIRY_DAYS) if "aiid_cache_expiry_days" in config.setting else _DEFAULT_CACHE_EXPIRY_DAYS
                expiry_sec = expiry_days * 86400
                with _cache_lock:
                    _aiid_cache.clear()
                    removed = 0
                    for k, v in list(raw.items()):
                        if isinstance(v, dict) and "ts" in v:
                            if now - v["ts"] > expiry_sec:
                                removed += 1  # abgelaufen
                                continue
                            _aiid_cache[k] = v
                        else:
                            continue
                    std_logging.getLogger().info(f"AI Music Identifier: Cache geladen mit {len(_aiid_cache)} Einträgen, {removed} abgelaufene entfernt.")
        else:
            std_logging.getLogger().info("AI Music Identifier: Keine Cache-Datei gefunden, neuer Cache wird angelegt.")
    except Exception as e:
        std_logging.getLogger().warning(f"AI Music Identifier: Konnte Cache nicht laden: {e}")
        show_error(tagger, f"Cache konnte nicht geladen werden: {e}")


def save_cache() -> None:
    """
    Speichert den aktuellen Cache asynchron in die Cache-Datei.
    """
    def _write_cache():
        try:
            with _cache_lock:
                with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(_aiid_cache, f, ensure_ascii=False, indent=2)
            std_logging.getLogger().info(f"AI Music Identifier: Cache erfolgreich gespeichert mit {len(_aiid_cache)} Einträgen.")
        except Exception as e:
            std_logging.getLogger().warning(f"AI Music Identifier: Konnte Cache nicht speichern: {e}")
    threading.Thread(target=_write_cache, daemon=True).start()


def get_cache() -> Dict[str, Any]:
    """
    Gibt das aktuelle Cache-Objekt zurück (thread-sicher).
    :return: Dictionary mit Cache-Inhalten
    """
    with _cache_lock:
        return _aiid_cache
