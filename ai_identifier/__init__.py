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
from .ui import AIMusicIdentifierOptionsPage
from .utils import *
from .workflow import *

from picard.extension_points.options_pages import register_options_page
register_options_page(AIMusicIdentifierOptionsPage)

# ... hier kann die Haupt-Plugin-Logik stehen, z.B. Event-Hooks, Initialisierung, etc. ...
