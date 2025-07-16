# Hilfsfunktionen für AI Music Identifier Plugin

import difflib
import locale
import logging
from PyQt6 import QtWidgets
from .constants import VALID_GENRES, VALID_MOODS

def _msg(de, en):
    lang = locale.getdefaultlocale()[0]
    return de if lang and lang.startswith("de") else en

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

def show_error(tagger, message):
    """Zeigt eine Fehlermeldung im Log und in der UI (Statusleiste und ggf. MessageBox) an."""
    logging.getLogger().error(f"AI Music Identifier: {message}")
    if tagger and hasattr(tagger, 'window'):
        tagger.window.set_statusbar_message(message)
        QtWidgets.QMessageBox.critical(tagger.window, "Fehler", message)

# Hier können weitere kleine Hilfsfunktionen ergänzt werden
