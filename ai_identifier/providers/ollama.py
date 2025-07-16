import aiohttp
import asyncio
from typing import Any, Optional
from picard import log  # type: ignore[import]
from PyQt6 import QtWidgets
from ..utils import is_debug_logging, msg
from ..config import get_setting
from .base import AIProviderBase
from ..logging import log_event, log_exception

class OllamaProvider(AIProviderBase):
    """
    Provider für Ollama-API (lokal).
    Erbt von AIProviderBase und implementiert die call-Methode.
    """
    _semaphore: Optional[asyncio.Semaphore] = None
    _available_models: Optional[set] = None
    _response_times: list = []
    _error_count: int = 0
    _min_parallel: int = 1
    _max_parallel: int = 10
    _adjust_threshold: int = 5  # Nach wie vielen Requests wird angepasst?
    _slow_threshold: float = 8.0  # Sek.

    @staticmethod
    async def log_available_models():
        """Liest die lokal verfügbaren Ollama-Modelle aus, loggt sie und speichert sie in _available_models."""
        url = str(get_setting("aiid_ollama_url", "http://localhost:11434"))
        url += "/api/tags"
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, timeout=timeout) as response:
                    response.raise_for_status()
                    data = await response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    OllamaProvider._available_models = set(models)
                    log_event("info", "Verfügbare Ollama-Modelle", models=", ".join(models))
        except Exception as e:
            log_event("warning", "Konnte Ollama-Modelle nicht abrufen", error=str(e))
            OllamaProvider._available_models = None

    def __init__(self):
        super().__init__(name="Ollama")
        if OllamaProvider._semaphore is None:
            max_parallel_raw = get_setting("aiid_ollama_max_parallel_requests", 3)
            max_parallel = int(max_parallel_raw) if max_parallel_raw is not None else 3
            OllamaProvider._semaphore = asyncio.Semaphore(max_parallel)
        # Modelle beim ersten Init loggen (nur einmal pro Session)
        if not hasattr(OllamaProvider, "_models_logged"):
            try:
                asyncio.create_task(OllamaProvider.log_available_models())
            except Exception:
                pass
            OllamaProvider._models_logged = True

    def _adjust_parallelism(self):
        """Passt die Semaphore dynamisch an die Performance an."""
        avg_time = sum(self._response_times) / len(self._response_times) if self._response_times else 0
        if self._semaphore is not None:
            current = getattr(self._semaphore, '_value', 1) + getattr(self._semaphore, '_waiters_count', 0)
        else:
            current = self._min_parallel
        # Bei vielen Fehlern oder langsamen Antworten: reduzieren
        if self._error_count > 0 or avg_time > self._slow_threshold:
            new_val = max(self._min_parallel, current - 1)
        else:
            new_val = min(self._max_parallel, current + 1)
        if new_val != current:
            self._semaphore = asyncio.Semaphore(new_val)
            log_event("info", msg(f"Parallele KI-Requests angepasst: {current} → {new_val}", f"Adjusted parallel KI requests: {current} → {new_val}"))
        self._response_times.clear()
        self._error_count = 0

    async def call(
        self,
        prompt: str,
        model: str = "mistral",
        tagger: Any = None,
        file_name: Optional[str] = None
    ) -> str:
        """
        Führt eine asynchrone Anfrage an die Ollama-API aus und gibt die Antwort zurück.
        """
        # Retry-Konfiguration
        max_retries_raw = get_setting("aiid_ollama_max_retries", 2)
        max_retries = int(max_retries_raw) if max_retries_raw is not None else 2
        backoff_base_raw = get_setting("aiid_ollama_retry_backoff", 2.0)
        backoff_base = float(backoff_base_raw) if backoff_base_raw is not None else 2.0
        # Prüfe, ob das Modell lokal verfügbar ist
        if OllamaProvider._available_models is not None:
            if model not in OllamaProvider._available_models:
                msg_text = msg(
                    f"Das Modell '{model}' ist lokal nicht installiert. Verfügbare Modelle: {', '.join(OllamaProvider._available_models)}",
                    f"The model '{model}' is not installed locally. Available models: {', '.join(OllamaProvider._available_models)}"
                )
                log_event("warning", msg(
                    "Angefordertes Modell nicht installiert",
                    "Requested model not installed"
                ), requested=model, available=", ".join(OllamaProvider._available_models))
                if tagger and hasattr(tagger, 'window'):
                    tagger.window.set_statusbar_message(msg_text)
                return msg_text
        # Adaptive Parallelisierung: Parameter aus Config
        min_parallel_raw = get_setting("aiid_ollama_min_parallel", 1)
        self._min_parallel = int(min_parallel_raw) if min_parallel_raw is not None else 1
        max_parallel_raw = get_setting("aiid_ollama_max_parallel", 10)
        self._max_parallel = int(max_parallel_raw) if max_parallel_raw is not None else 10
        adjust_threshold_raw = get_setting("aiid_ollama_adjust_threshold", 5)
        self._adjust_threshold = int(adjust_threshold_raw) if adjust_threshold_raw is not None else 5
        slow_threshold_raw = get_setting("aiid_ollama_slow_threshold", 8.0)
        self._slow_threshold = float(slow_threshold_raw) if slow_threshold_raw is not None else 8.0
        semaphore = OllamaProvider._semaphore or asyncio.Semaphore(3)
        async with semaphore:
            url = str(get_setting("aiid_ollama_url"))
            url += "/api/generate"
            data = {"model": model, "prompt": prompt, "stream": False}
            timeout_raw = get_setting("aiid_ollama_timeout", 60)
            timeout = int(timeout_raw) if timeout_raw is not None else 60
            aio_timeout = aiohttp.ClientTimeout(total=timeout)
            if is_debug_logging():
                self.log_debug(f"[KI-Request] Datei: {file_name}, Modell: {model}, URL: {url}, Timeout: {timeout}, Prompt: {prompt}")
            import time as _time
            start = _time.time()
            attempt = 0
            while True:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=data, timeout=aio_timeout) as response:
                            elapsed = _time.time() - start
                            self._response_times.append(elapsed)
                            if elapsed > 10:
                                log_event("warning", "KI-Request dauerte ungewöhnlich lange", file=file_name, elapsed=elapsed)
                            if is_debug_logging():
                                log_event("debug", "KI-Response", file=file_name, elapsed=elapsed, status=response.status)
                            response.raise_for_status()
                            result_json = await response.json()
                            result = result_json["response"].strip()
                            log_event("info", "Ollama-Antwort erhalten", file=file_name, result=result)
                            # Nach adjust_threshold Requests: Parallelität anpassen
                            if len(self._response_times) >= self._adjust_threshold:
                                self._adjust_parallelism()
                            return result
                except (asyncio.TimeoutError, aiohttp.ClientConnectionError, aiohttp.ClientResponseError) as e:
                    self._error_count += 1
                    is_5xx = isinstance(e, aiohttp.ClientResponseError) and 500 <= getattr(e, 'status', 0) < 600
                    if attempt < max_retries and (isinstance(e, (asyncio.TimeoutError, aiohttp.ClientConnectionError)) or is_5xx):
                        wait = backoff_base * (2 ** attempt)
                        log_event("warning", msg(
                            f"Temporärer Fehler bei Ollama-Anfrage (Versuch {attempt+1}/{max_retries+1}), warte {wait:.1f}s: {e}",
                            f"Temporary error on Ollama request (attempt {attempt+1}/{max_retries+1}), waiting {wait:.1f}s: {e}"
                        ), file=file_name, error=str(e))
                        await asyncio.sleep(wait)
                        attempt += 1
                        continue
                    # Wenn keine weiteren Versuche: Fehlerbehandlung wie bisher
                    if isinstance(e, asyncio.TimeoutError):
                        msg_text = msg(f"[Netzwerkfehler] KI-Timeout bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI timeout on Ollama request for file {file_name}: {e}")
                        log_exception("KI-Timeout bei Ollama-Anfrage", file=file_name, error=str(e))
                    elif isinstance(e, aiohttp.ClientConnectionError):
                        msg_text = msg(f"[Netzwerkfehler] KI-Netzwerkfehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Network error] AI network error on Ollama request for file {file_name}: {e}")
                        log_exception("KI-Netzwerkfehler bei Ollama-Anfrage", file=file_name, error=str(e))
                    elif isinstance(e, aiohttp.ClientResponseError):
                        msg_text = msg(f"[API-Fehler] HTTP-Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[API error] HTTP error on Ollama request for file {file_name}: {e}")
                        log_exception("HTTP-Fehler bei Ollama-Anfrage", file=file_name, error=str(e))
                    else:
                        msg_text = msg(f"[Unbekannter Fehler] Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Unknown error] Error on Ollama request for file {file_name}: {e}")
                        log_exception("Unbekannter Fehler bei Ollama-Anfrage", file=file_name, error=str(e))
                    if tagger and hasattr(tagger, 'window'):
                        tagger.window.set_statusbar_message(msg_text)
                        QtWidgets.QMessageBox.critical(tagger.window, str(msg("Fehler", "Error") or "Fehler"), msg_text)
                    return msg_text
                except Exception as e:
                    msg_text = msg(f"[Lokaler Fehler] Fehler bei Ollama-Anfrage für Datei {file_name}: {e}", f"[Local error] Error on Ollama request for file {file_name}: {e}")
                    log_exception("Lokaler Fehler bei Ollama-Anfrage", file=file_name, error=str(e))
                    if tagger and hasattr(tagger, 'window'):
                        tagger.window.set_statusbar_message(msg_text)
                        QtWidgets.QMessageBox.critical(tagger.window, str(msg("Fehler", "Error") or "Fehler"), msg_text)
                    return msg_text

# Für Kompatibilität: bisherige Funktionsweise als Funktion (jetzt async)
ollama_provider = OllamaProvider()
async def call_ollama(prompt, model="mistral", tagger=None, file_name=None):
    return await ollama_provider.call(prompt, model, tagger, file_name)
