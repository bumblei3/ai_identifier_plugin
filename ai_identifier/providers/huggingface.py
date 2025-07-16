import requests
from picard import config, log
from .cache import get_cache, save_cache
from PyQt6 import QtWidgets
from .utils import is_debug_logging, _msg

def call_huggingface(prompt, model, tagger=None, file_name=None):
    api_key = config.setting["aiid_hf_key"] if "aiid_hf_key" in config.setting else ""
    if not api_key:
        QtWidgets.QMessageBox.warning(None, "Fehler", _msg("Kein HuggingFace-API-Key hinterlegt!", "No HuggingFace API key set!"))
        return None
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"inputs": prompt}
    timeout = int(config.setting["aiid_huggingface_timeout"] or 60) if "aiid_huggingface_timeout" in config.setting else 60
    if is_debug_logging():
        log.debug(f"AI Music Identifier: [HuggingFace-Request] Datei: {file_name}, Modell: {model}, URL: {url}, Timeout: {timeout}, Prompt: {prompt}")
    try:
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        response.raise_for_status()
        result = response.json()
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [HuggingFace-Response] {result}")
        if isinstance(result, list) and result and "generated_text" in result[0]:
            return result[0]["generated_text"]
        return result
    except Exception as e:
        log.error(f"AI Music Identifier: HuggingFace-Fehler: {e}")
        QtWidgets.QMessageBox.warning(None, "Fehler", _msg(f"HuggingFace-Fehler: {e}", f"HuggingFace error: {e}"))
        return None
