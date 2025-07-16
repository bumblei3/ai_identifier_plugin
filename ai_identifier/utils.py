# Hilfsfunktionen für AI Music Identifier Plugin

# pyright: reportMissingImports=false
import difflib
import locale
import logging as std_logging
from PyQt6 import QtWidgets
from .constants import VALID_GENRES, VALID_MOODS
from typing import Any, Optional
from . import logging

def _msg(de: str, en: Optional[str] = None) -> str:
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

def show_error(tagger: Any, message: str) -> None:
    """
    Zeigt eine Fehlermeldung im Log und ggf. in der UI an.
    :param tagger: (optional) Picard-Tagger-Objekt
    :param message: Fehlermeldung
    """
    std_logging.getLogger().error(f"AI Music Identifier: {message}")
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(message)
        QtWidgets.QMessageBox.critical(tagger.window, "Fehler", message)

# Hier können weitere kleine Hilfsfunktionen ergänzt werden
