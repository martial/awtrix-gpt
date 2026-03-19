import yaml
import os
import threading
from typing import Dict, Any

_config_cache = None
_config_lock = threading.Lock()
_config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """Load configuration from YAML file with thread-safe caching."""
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache
    with _config_lock:
        if _config_cache is not None and not force_reload:
            return _config_cache
        with open(_config_path, 'r', encoding='utf-8') as file:
            _config_cache = yaml.safe_load(file)
        return _config_cache


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to YAML file and update cache."""
    global _config_cache
    with _config_lock:
        with open(_config_path, 'w', encoding='utf-8') as file:
            yaml.dump(config, file, default_flow_style=False)
        _config_cache = config
