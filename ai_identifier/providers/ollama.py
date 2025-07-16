import requests
from picard import config, log
from ai_identifier.cache import get_cache, save_cache
from PyQt6 import QtWidgets
from ai_identifier import is_debug_logging, _msg

def call_ollama(prompt, model="mistral", tagger=None, file_name=None):
    url = str(config.setting["aiid_ollama_url"]) if "aiid_ollama_url" in config.setting else "http://localhost:11434"
    url += "/api/generate"
    data = {"model": model, "prompt": prompt, "stream": False}
    timeout = int(config.setting["aiid_ollama_timeout"] or 60) if "aiid_ollama_timeout" in config.setting else 60
    if is_debug_logging():
        log.debug(f"AI Music Identifier: [KI-Request] Datei: {file_name}, Modell: {model}, URL: {url}, Timeout: {timeout}, Prompt: {prompt}")
    import time as _time
    start = _time.time()
    try:
        response = requests.post(url, json=data, timeout=timeout)
        elapsed = _time.time() - start
        if elapsed > 10:
            log.warning(_msg(f"[Performance] KI-Request dauerte ungewöhnlich lange: {elapsed:.1f}s (Datei: {file_name})", f"[Performance] AI request took unusually long: {elapsed:.1f}s (file: {file_name})"))
        if is_debug_logging():
            log.debug(f"AI Music Identifier: [KI-Response] Datei: {file_name}, Dauer: {elapsed:.2f}s, Status: {response.status_code}")
        response.raise_for_status()
        result = response.json()["response"].strip()
        log.info(f"AI Music Identifier: Ollama-Antwort erhalten für Datei {file_name}: {result}")
        return result
    except requests.Timeout as e:
        msg = _msg(f"[Netzwerkfehler] KI-Timeout bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI timeout on Ollama request for file {file_name}: {e}")
        log.error(f"[Netzwerkfehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except requests.ConnectionError as e:
        msg = _msg(f"[Netzwerkfehler] KI-Netzwerkfehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI network error on Ollama request for file {file_name}: {e}")
        log.error(f"[Netzwerkfehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except requests.HTTPError as e:
        msg = _msg(f"[API-Fehler] HTTP-Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[API error] HTTP error on Ollama request for file {file_name}: {e}")
        log.error(f"[API-Fehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
    except Exception as e:
        msg = _msg(f"[Lokaler Fehler] Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Local error] Error on Ollama request for file {file_name}: {e}")
        log.error(f"[Lokaler Fehler] {msg}")
        if tagger and hasattr(tagger, 'window'):
            tagger.window.set_statusbar_message(msg)
            QtWidgets.QMessageBox.critical(tagger.window, "KI-Fehler", msg)
        return msg
