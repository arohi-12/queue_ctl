"""Configuration management for queuectl."""
import json
import os
from typing import Any


DEFAULT_CONFIG = {
    "max_retries": 3,
    "backoff_base": 2,
    "poll_interval": 1.0,
    "job_timeout": 300,
    "default_priority": 0,
}


class Config:
    """Manages queuectl configuration with persistence."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            from queuectl.utils import get_config_path
            config_path = get_config_path()
        self.config_path = config_path
        self._config: dict = None

    def _load(self):
        if self._config is not None:
            return
        self._config = DEFAULT_CONFIG.copy()
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    user_config = json.load(f)
                    self._config.update(user_config)
            except (json.JSONDecodeError, IOError):
                pass

    def get(self, key: str, default: Any = None) -> Any:
        self._load()
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._load()
        # Attempt to cast numeric values
        if value is not None:
            try:
                if "." in str(value):
                    value = float(value)
                else:
                    value = int(value)
            except (ValueError, TypeError):
                pass
        self._config[key] = value
        self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self._config, f, indent=2)

    def get_all(self) -> dict:
        self._load()
        return self._config.copy()

    def reset(self):
        self._config = DEFAULT_CONFIG.copy()
        self._save()