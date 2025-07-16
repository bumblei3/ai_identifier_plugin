from ai_identifier.config import validate_config
from picard import log  # type: ignore[import]

def check_config_on_start():
    problems = validate_config()
    if problems:
        msg = "AI Identifier Plugin: Konfigurationsprobleme erkannt:\n"
        for key, problem in problems.items():
            msg += f"- {key}: {problem}\n"
        log.warning(msg)
        # Optional: Auch in eine eigene Datei schreiben
        with open("aiid_config_warnings.log", "a") as f:
            f.write(msg + "\n")

check_config_on_start()
