# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false

PLUGIN_NAME = "AI Music Identifier"
PLUGIN_AUTHOR = "bumblei3"
PLUGIN_DESCRIPTION = "Identifiziert Musikdateien per AcoustID und ergänzt Metadaten (inkl. Genre, ISRC, Label, Tracknummer)."
PLUGIN_VERSION = "0.9.1"
PLUGIN_API_VERSIONS = ["3.0"]

from .constants import *
from .cache import load_cache, save_cache, get_cache
from .ki import *
from .worker import *
from .utils import *
from .workflow import *
from . import logging  # Initialisiert das eigene Logging-Setup
import logging as std_logging
logger = std_logging.getLogger("ai_identifier")
logger.info("Test: ai_identifier Plugin wurde geladen und Logging initialisiert!")
# Keine UI-Registrierung mehr nötig – reines Backend-Plugin

# ... hier kann die Haupt-Plugin-Logik stehen, z.B. Event-Hooks, Initialisierung, etc. ...
