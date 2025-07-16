import logging
import os
import traceback

LOGFILE = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_plugin.log")
LOGLEVEL = os.environ.get("AIID_LOGLEVEL", "INFO").upper()

logging.basicConfig(
    level=LOGLEVEL,
    format="%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)


def log_event(level, msg, **context):
    """Zentrale Logging-Funktion mit Kontextinformationen."""
    logger = logging.getLogger("ai_identifier")
    if context:
        msg += " | " + " ".join(f"{k}={v!r}" for k, v in context.items())
    getattr(logger, level.lower())(msg)


def log_exception(msg, **context):
    """Loggt eine Exception mit Stacktrace und Kontext."""
    context["stacktrace"] = traceback.format_exc()
    log_event("error", msg, **context)
