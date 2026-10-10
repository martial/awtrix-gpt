"""What we ask the LLM for, and how we read its answer. Pure: no I/O besides
reading the prompt template file.

The LLM is asked ONLY for the categories where inventing is the point:
messages, suggested_activities, poems. News and weather are built in code
(see `news.py`, `weather.py`); anything the model emits under those keys is
dropped on parsing.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from awtrix_gpt.paths import PROMPT_TEMPLATE_PATH
from awtrix_gpt.text import ascii_fold, collapse_whitespace

LLM_KEYS = ("messages", "suggested_activities", "poems")

# Local models rename keys from run to run; take the first alias holding a list.
KEY_ALIASES = {
    "messages": ("messages", "message", "msgs"),
    "suggested_activities": ("suggested_activities", "activities", "suggestions"),
    "poems": ("poems", "poem", "poetry"),
}

# JSON schema sent as Ollama's `format` (structured outputs). Keys MUST match LLM_KEYS.
CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": {"type": "string"}, "minItems": 8},
        "suggested_activities": {"type": "array", "items": {"type": "string"}, "minItems": 2},
        "poems": {"type": "array", "items": {"type": "string"}, "minItems": 2},
    },
    "required": list(LLM_KEYS),
}

FALLBACK_LINES = {
    "messages": ["Elisa et Marziol, amoureux des petites joies"],
    "suggested_activities": ["Un petit smoothie ensemble?"],
    "poems": ["Marseille Amantea, deux coeurs unis"],
}

TIMESTAMP_FORMAT = "%A %d %B %Y %H:%M"


def load_prompt_template(path: Path = PROMPT_TEMPLATE_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


class _SafeParams(dict):
    """Leave unknown `{placeholders}` untouched instead of raising KeyError."""

    def __missing__(self, key):
        return "{" + key + "}"


def build_prompt(template: str, now: datetime, weather_descriptions: Mapping[str, str]) -> str:
    """Fill `{timestamp}` and `{<city>_weather}` (e.g. `{marseille_weather}`) in the template.

    The template is user-editable through the web UI, so formatting is
    tolerant: unknown placeholders stay as written, and if the template is not
    valid format syntax at all we fall back to plain substitution.
    """
    params = {"timestamp": now.strftime(TIMESTAMP_FORMAT)}
    params.update({f"{key.lower()}_weather": text for key, text in weather_descriptions.items()})
    try:
        return template.format_map(_SafeParams(params))
    except (ValueError, IndexError, KeyError):
        out = template
        for key, value in params.items():
            out = out.replace("{" + key + "}", value)
        return out


def _clean_lines(values) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str):
            continue
        # The matrix font has no accented glyphs, and the prompt asks the model
        # to avoid them — it does not comply, so fold here as news and weather
        # already do. Dedup after folding, so "cafe" and "café" count as one.
        line = ascii_fold(collapse_whitespace(value))
        if line and line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    return lines


def parse_llm_response(raw_text: str) -> dict[str, list[str]]:
    """Parse the model's JSON into `{key: [lines]}` for LLM_KEYS only.

    Strips code fences, resolves key aliases, keeps only non-empty strings and
    collapses each to a single line. Raises ValueError on invalid JSON or a
    non-object payload so the caller can fall back explicitly.
    """
    text = (raw_text or "").replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM response is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"LLM response is a {type(data).__name__}, expected an object")

    result: dict[str, list[str]] = {}
    for key in LLM_KEYS:
        lines: list[str] = []
        for alias in KEY_ALIASES[key]:
            lines = _clean_lines(data.get(alias))
            if lines:
                break
        result[key] = lines
    return result


# --------------------------------------------------------------------------
# Smaller one-off generations used by the web endpoints
# --------------------------------------------------------------------------

LOVE_NOTE_PROMPT = (
    "Écris UN seul mot doux très court (max 70 caractères, une seule ligne, "
    "sans guillemets ni emoji) pour un couple franco-italien, Elisa et Marziol, "
    "entre Marseille et Amantea. Style tendre, poétique, parfois en français "
    "parfois en italien. Réponds uniquement par le message."
)


def love_note_prompt(lang_hint: str = "") -> str:
    return LOVE_NOTE_PROMPT + (f" {lang_hint}" if lang_hint else "")


def first_line(text: str, max_chars: int = 80) -> str:
    """The first non-empty line of a free-text answer, capped."""
    for line in (text or "").splitlines():
        line = line.strip().strip('"“”')
        if line:
            return line[:max_chars]
    return ""


PHOTO_POEM_PROMPT = """
Looking at this photo, analyze the scene and create a response following these rules:

1. Return a JSON object with three keys:
- "result": the poem (Italian or French)
- "description": a scene description in French (max 3 lines of 32 chars) about:
    * Room ambiance and lighting
    * Order/disorder level
    * Presence of people/objects
    * General atmosphere
- "timestamp": current time in French format (leave this empty, code will fill it)

Poem rules:
- Maximum 8 lines
- Maximum 32 characters per line
- If there is a man in the picture, refer to him as "Marziol"
- If there is a woman in the picture, refer to her as "Elisa"
- You must include persons in the poem.
- Use \\n for line breaks

Return exact format:
{
    "result": "poem here with\\nline breaks",
    "description": "French description here\\nwith line breaks if needed",
    "timestamp": ""
}

Do not use markdown or other formatting.
"""

PHOTO_POEM_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
        "description": {"type": "string"},
        "timestamp": {"type": "string"},
    },
    "required": ["result", "description"],
}


def parse_photo_poem(raw_text: str) -> dict[str, str]:
    """`{"result": poem, "description": text}`; raises ValueError on bad JSON."""
    text = (raw_text or "").replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"photo poem response is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("photo poem response is not a JSON object")
    return {"result": str(data.get("result") or ""), "description": str(data.get("description") or "")}
