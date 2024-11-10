import yaml
import os
from typing import Dict, Any

def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    
    with open(config_path, 'r', encoding='utf-8') as file:
        return yaml.safe_load(file)