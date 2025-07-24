from abc import ABC, abstractmethod
from typing import Any, Optional
import logging

class AIProviderBase(ABC):
    """
    Abstrakte Basisklasse für KI-Provider.
    Definiert die Schnittstelle und gemeinsame Logik für alle Provider.
    """

    def __init__(self, name: str):
        """
        Initialisiert den Provider mit einem Namen.
        :param name: Name des Providers (z.B. "OpenAI", "Ollama")
        """
        self.name = name
        self.logger = logging.getLogger(f"AIProvider.{self.name}")

    @abstractmethod
    def call(self, prompt: str, model: Optional[str] = None, tagger: Any = None, file_name: Optional[str] = None) -> str:
        """
        Führt einen KI-Request aus und gibt die Antwort als String zurück.
        :param prompt: Prompt für die KI
        :param model: Modellname (optional)
        :param tagger: Tagger-Objekt (optional, für Statusmeldungen)
        :param file_name: Dateiname (optional, für Logging)
        :return: Antwort der KI als String
        """
        pass

    def log_info(self, message: str) -> None:
        """Loggt eine Info-Nachricht für den Provider."""
        self.logger.info(message)

    def log_error(self, message: str) -> None:
        """Loggt eine Fehler-Nachricht für den Provider."""
        self.logger.error(message)

    def log_debug(self, message: str) -> None:
        """Loggt eine Debug-Nachricht für den Provider."""
        self.logger.debug(message)

    def validate_config(self) -> Optional[str]:
        """
        Prüft, ob die Provider-Konfiguration gültig ist.
        :return: None, wenn alles ok ist, sonst eine Fehlerbeschreibung.
        """
        return None
