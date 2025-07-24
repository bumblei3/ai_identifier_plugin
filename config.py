"""
Bereinigte Konfiguration für AI Music Identifier Plugin
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

class PluginConfig:
    """ereinfachte Plugin-Konfiguration ohne Ollama"""
    
    def __init__(self):
        self.config_file = Path.home() / ".config" / "MusicBrainz" / "Picard" / "ai_identifier_config.json"
        self.default_config = {
            "debug_mode": False,
            "log_level": "INFO",
            "crash_protection": True,
            "max_crashes": 3,
            "memory_limit_mb": 512,
            "timeout_seconds": 30
        }
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration aus Datei oder erstellt Standardwerte"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Merge mit Standardwerten für fehlende Einträge
                    for key, value in self.default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            else:
                # Erstelle Standardkonfiguration
                self.save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            print(f"Fehler beim Laden der Konfiguration: {e}")
            return self.default_config.copy()
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Speichert die Konfiguration in Datei"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"Fehler beim Speichern der Konfiguration: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Holt einen Konfigurationswert"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Setzt einen Konfigurationswert"""
        self.config[key] = value
        return self.save_config(self.config)
    
    def reset_to_defaults(self) -> bool:
        """Setzt die Konfiguration auf Standardwerte zurück"""
        return self.save_config(self.default_config.copy())

class CrashProtection:
    """Crash-Schutz für das Plugin"""
    
    def __init__(self, config: PluginConfig):
        self.config = config
        self.crash_count = 0
        self.max_crashes = config.get("max_crashes", 3)
        self.retry_delay = config.get("retry_delay", 5.0)
    
    def is_enabled(self) -> bool:
        """Prüft, ob Crash-Schutz aktiv ist"""
        return self.config.get("crash_protection", True)
    
    def can_continue(self) -> bool:
        """Prüft, ob das Plugin weiterarbeiten kann"""
        if not self.is_enabled():
            return True
        return self.crash_count < self.max_crashes
    
    def record_crash(self) -> None:
        """Zeichnet einen Crash auf"""
        self.crash_count += 1
        print(f"🚨 Plugin-Crash #{self.crash_count} von {self.max_crashes}")
    
    def reset_crash_count(self) -> None:
        """Setzt den Crash-Zähler zurück"""
        self.crash_count = 0

class PerformanceMonitor:
    """Performance-Überwachung für das Plugin"""
    
    def __init__(self, config: PluginConfig):
        self.config = config
        self.memory_limit = config.get("memory_limit_mb", 512) * 1024 * 1024  # MB zu Bytes
        self.timeout = config.get("timeout_seconds", 30)
    
    def check_memory_usage(self) -> bool:
        """Prüft den Speicherverbrauch"""
        try:
            import psutil
            process = psutil.Process()
            memory_usage = process.memory_info().rss
            return memory_usage < self.memory_limit
        except ImportError:
            # psutil nicht verfügbar, ignoriere Speicherprüfung
            return True
    
    def get_memory_usage_mb(self) -> float:
        """Gibt den aktuellen Speicherverbrauch in MB zurück"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0

# Globale Instanzen
config = PluginConfig()
crash_protection = CrashProtection(config)
performance_monitor = PerformanceMonitor(config)

def get_setting(key: str, default: Any = None) -> Any:
    """Globale Funktion zum Abrufen von Konfigurationswerten"""
    return config.get(key, default)

def set_setting(key: str, value: Any) -> bool:
    """Globale Funktion zum Setzen von Konfigurationswerten"""
    return config.set(key, value)

# Performance-Optimierungen für das AI-Plugin
# Diese Werte können in der Konfiguration überschrieben werden
