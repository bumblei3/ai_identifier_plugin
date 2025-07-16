# pyright: reportMissingImports=false
# Worker- und Threading-Logik für AI Music Identifier Plugin

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal
from collections import deque
from .ki import call_ollama
from .utils import show_error
import threading
from picard import log
from typing import Any

# Globale Thread-Limitierung für KI-Worker
_MAX_KI_THREADS = 2
_active_ki_threads = 0
_ki_worker_queue = deque()

class WorkerSignals(QObject):
    """
    Qt-Signale für Worker: Ergebnis und Fehler.
    """
    result_ready = pyqtSignal(str, object)
    error = pyqtSignal(str, object)

class AIKIRunnable(QRunnable):
    """
    QRunnable-Worker für KI-Operationen (z.B. Genre/Mood).
    """
    def __init__(self, prompt: str, model: str, field: str, tagger: Any = None):
        """
        :param prompt: Prompt für die KI
        :param model: Modellname
        :param field: Feld (z.B. "genre", "mood")
        :param tagger: (optional) Picard-Tagger-Objekt
        """
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.field = field  # "genre" oder "mood"
        self.tagger = tagger
        self.signals = WorkerSignals()

    def run(self):
        try:
            from picard import log
            log.info(f"AI Music Identifier: KI-Worker gestartet (Feld: {self.field}, Modell: {self.model})")
            if self.field == "genre":
                result = call_ollama(self.prompt, self.model, self.tagger)
            elif self.field == "mood":
                result = call_ollama(self.prompt, self.model, self.tagger)
            else:
                result = None
            if result and "Fehler" not in result:
                self.signals.result_ready.emit(self.field, result)
                log.info(f"AI Music Identifier: KI-Worker erfolgreich (Feld: {self.field})")
            else:
                self.signals.error.emit(result or "Unbekannter Fehler", None)
                show_error(self.tagger, result or "Unbekannter Fehler")
                log.error(f"AI Music Identifier: KI-Worker Fehler (Feld: {self.field}): {result}")
        except Exception as e:
            self.signals.error.emit(str(e), None)
            show_error(self.tagger, str(e))
            from picard import log
            log.error(f"AI Music Identifier: Ausnahme im KI-Worker (Feld: {self.field}): {e}")

def _on_ki_worker_finished(worker: Any) -> None:
    """
    Wird aufgerufen, wenn ein KI-Worker fertig ist. Startet ggf. nächsten Worker aus der Queue.
    :param worker: Der fertiggestellte Worker
    """
    global _active_ki_threads
    _active_ki_threads = max(0, _active_ki_threads - 1)
    if log:
        log.debug(f"AI Music Identifier: [Thread] KI-Worker beendet (aktiv: {_active_ki_threads})")
    # Starte nächsten Worker aus der Queue, falls vorhanden
    if _ki_worker_queue:
        next_worker = _ki_worker_queue.popleft()
        _start_ki_worker(next_worker)

def _start_ki_worker(worker: Any) -> None:
    """
    Startet einen KI-Worker oder stellt ihn in die Warteschlange, wenn das Limit erreicht ist.
    :param worker: Zu startender Worker
    """
    global _active_ki_threads
    if _active_ki_threads < _MAX_KI_THREADS:
        _active_ki_threads += 1
        if log:
            log.debug(f"AI Music Identifier: [Thread] Starte KI-Worker (aktiv: {_active_ki_threads})")
        worker.finished.connect(lambda: _on_ki_worker_finished(worker))
        worker.start()
    else:
        _ki_worker_queue.append(worker)
        if log:
            log.debug(f"AI Music Identifier: [Thread] KI-Worker in Warteschlange (Queue-Länge: {len(_ki_worker_queue)})")

def set_ki_thread_limit(n: int) -> None:
    """
    Setzt das globale Thread-Limit für parallele KI-Worker.
    :param n: Maximale Anzahl paralleler Threads
    """
    global _MAX_KI_THREADS
    _MAX_KI_THREADS = max(1, int(n))

__all__ = [
    'AIKIRunnable', '_start_ki_worker', 'set_ki_thread_limit'
] 