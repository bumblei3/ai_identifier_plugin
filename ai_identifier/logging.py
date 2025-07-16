import logging
import os

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
