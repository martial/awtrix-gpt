"""Project-relative paths, resolved once so no module depends on the cwd."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "prompt_template.txt"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
PHOTOS_DIR = PROJECT_ROOT / "photos"
