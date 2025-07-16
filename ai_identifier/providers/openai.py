import requests
from picard import config, log
from .cache import get_cache, save_cache
from PyQt6 import QtWidgets
from .utils import is_debug_logging, _msg

def call_openai(prompt, model, tagger=None, file_name=None):
    api_key = config.setting["aiid_openai_key"] if "aiid_openai_key" in config.setting else ""
    if not api_key:
        QtWidgets.QMessageBox.warning(None, "Fehler", _msg("Kein OpenAI-API-Key hinterlegt!", "No OpenAI API key set!"))
        return None
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    timeout = int(config.setting["aiid_openai_timeout"] or 60) if "aiid_openai_timeout" in config.setting else 60
    if is_debug_logging():
        log.debug(f"AI Music Identifier: [OpenAI-Request] Datei: {file_name}, Modell: {model}, URL: {url}, Timeout: {timeout}, Prompt: {prompt}")
    try:
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        response.raise_for_status()
        result = response.json()
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [OpenAI-Response] {result}")
        return result["choices"][0]["message"]["content"] if "choices" in result and result["choices"] else None
    except Exception as e:
        log.error(f"AI Music Identifier: OpenAI-Fehler: {e}")
        QtWidgets.QMessageBox.warning(None, "Fehler", _msg(f"OpenAI-Fehler: {e}", f"OpenAI error: {e}"))
        return None
