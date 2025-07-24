import logging
import os
import traceback
import json
import datetime
from .config import get_setting

LOGFILE = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_plugin.log")
# Log-Level aus Plugin-Konfiguration oder Umgebungsvariable
try:
    _loglevel = get_setting("aiid_loglevel", os.environ.get("AIID_LOGLEVEL", "INFO"))
    if not isinstance(_loglevel, str) or not _loglevel:
        _loglevel = "INFO"
    LOGLEVEL = _loglevel.upper()
except Exception:
    LOGLEVEL = "INFO"
JSONLOG = os.path.expanduser("~/.config/MusicBrainz/Picard/aiid_plugin.jsonl")

logging.basicConfig(
    level=LOGLEVEL,
    format="%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)


def log_event(level, msg, **context):
    """Zentrale Logging-Funktion mit Kontextinformationen. Fehler werden strukturiert geloggt. Zusätzlich maschinenlesbares JSON-Log."""
    logger = logging.getLogger("ai_identifier")
    try:
        from picard import log as picard_log
        # Schreibe immer ins Picard-Log (Info/Debug als info, Error/Warning als error)
        if level.lower() in ("error", "warning"):
            picard_log.error(f"[AIID] {msg} | " + " ".join(f"{k}={v!r}" for k, v in context.items()))
        else:
            picard_log.info(f"[AIID] {msg} | " + " ".join(f"{k}={v!r}" for k, v in context.items()))
    except Exception:
        pass
    # Kontext als maschinenlesbarer String
    context_str = " | " + " ".join(f"{k}={v!r}" for k, v in context.items()) if context else ""
    # Fehler und Warnungen im strukturierten Format
    if level.lower() in ("error", "warning"):
        prefix = "E: [AIID]" if level.lower() == "error" else "W: [AIID]"
        # Sprache erkennen (falls vorhanden)
        lang = context.get("lang")
        if not lang:
            import locale
            lang = locale.getdefaultlocale()[0] if locale.getdefaultlocale() else "unknown"
        # Deutsch/Englisch, falls msg() genutzt wurde
        msg_de = context.get("msg_de") or msg
        msg_en = context.get("msg_en") or msg
        # Kontextfelder
        file = context.get("file")
        model = context.get("model")
        error = context.get("error")
        # Strukturierte Zeile
        logline = f"{prefix} {msg_de} | file={file!r} model={model!r} error={error!r} lang={lang!r}{context_str}"
        logger.error(logline) if level.lower() == "error" else logger.warning(logline)
    else:
        # Info/debug wie bisher
        if context:
            msg += " | " + " ".join(f"{k}={v!r}" for k, v in context.items())
        getattr(logger, level.lower())(msg)
    # --- JSON-Log ---
    log_obj = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "level": level.upper(),
        "msg": msg,
        "context": context
    }
    try:
        with open(JSONLOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_obj, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_exception(msg, **context):
    """Loggt eine Exception mit Stacktrace und Kontext im strukturierten Format (auch als JSON)."""
    import traceback
    context["stacktrace"] = traceback.format_exc()
    log_event("error", msg, **context)
