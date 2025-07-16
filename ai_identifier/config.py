"""
Zentrale Konfigurationslogik für AI Music Identifier Plugin
"""
from typing import Dict, Any, Optional
import re

try:
    from picard import config as picard_config  # type: ignore[import]
except ImportError:
    picard_config = None

# Default-Konfiguration
DEFAULTS = {
    "aiid_ollama_url": "http://localhost:11434",
    "aiid_ollama_timeout": 60,
    "aiid_ollama_max_parallel_requests": 3,  # Maximale gleichzeitige Ollama-Requests
    "aiid_openai_api_key": "",
    "aiid_huggingface_api_key": "",
    "aiid_acoustid_api_key": "",
    "aiid_debug_logging": False,
    # Weitere Optionen nach Bedarf
}


def get_setting(key: str, default=None):
    """Liest eine Einstellung aus der Picard-Konfiguration oder gibt den Default zurück (niemals None, wenn Default angegeben)."""
    if picard_config and hasattr(picard_config, "setting"):
        try:
            value = picard_config.setting[key]
        except KeyError:
            value = DEFAULTS.get(key, default)
    else:
        value = DEFAULTS.get(key, default)
    if value is None and default is not None:
        return default
    return value


def validate_config() -> Dict[str, str]:
    """
    Prüft die wichtigsten Konfigurationswerte und gibt Fehler/Hinweise zurück.
    :return: Dict mit Fehlern oder Warnungen (key = Option, value = Problem)
    """
    problems = {}
    # Beispiel: Ollama-URL
    url = get_setting("aiid_ollama_url")
    if not url or not re.match(r"^https?://", str(url)):
        problems["aiid_ollama_url"] = "Ungültige oder fehlende Ollama-URL."
    # Beispiel: OpenAI API-Key
    openai_key = get_setting("aiid_openai_api_key")
    if openai_key and not re.match(r"^sk-[A-Za-z0-9]{20,}$", openai_key):
        problems["aiid_openai_api_key"] = "OpenAI API-Key sieht ungültig aus."
    # Beispiel: AcoustID API-Key
    acoustid_key = get_setting("aiid_acoustid_api_key")
    if not acoustid_key:
        problems["aiid_acoustid_api_key"] = "AcoustID API-Key fehlt."
    # Weitere Prüfungen nach Bedarf
    return problems


def get_all_settings() -> Dict[str, Any]:
    """Gibt alle aktuellen Konfigurationswerte zurück (Picard oder Defaults)."""
    result = {}
    for key in DEFAULTS:
        result[key] = get_setting(key)
    return result

# Optional: Profile für verschiedene Nutzungsarten
PROFILES = {
    "schnell": {
        "aiid_ollama_timeout": 20,
        "aiid_ollama_max_parallel_requests": 3,
        "aiid_debug_logging": False,
    },
    "genau": {
        "aiid_ollama_timeout": 60,
        "aiid_ollama_max_parallel_requests": 2,
        "aiid_debug_logging": True,
    },
    "offline": {
        "aiid_ollama_url": "http://localhost:11434",
        "aiid_openai_api_key": "",
        "aiid_huggingface_api_key": "",
    },
}

def apply_profile(profile: str):
    """Setzt die Einstellungen eines Profils (nur in Picard-Laufzeitumgebung sinnvoll)."""
    if profile not in PROFILES or not picard_config:
        return
    for key, value in PROFILES[profile].items():
        picard_config.setting[key] = value
