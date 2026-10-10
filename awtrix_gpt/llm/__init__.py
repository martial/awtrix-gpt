"""LLM clients behind one small interface.

    client.generate(prompt, schema=..., images=..., web_search=...) -> raw text

`schema` is a JSON-schema object for structured output. Prefer it over JSON
mode: gemma3 returns `{}` with `format="json"` (0/4) and works with a schema
(3/3), measured 2026-10-10.
"""

import os
from typing import Mapping, Optional, Protocol

DEFAULT_OLLAMA_HOST = "http://192.168.1.81:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"


class LLMClient(Protocol):
    name: str

    def generate(self, prompt: str, *, schema: Optional[dict] = None,
                 images: Optional[list[str]] = None, web_search: bool = False,
                 timeout: int = 300) -> str: ...


def strip_code_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences even when told not to."""
    return (text or "").replace("```json", "").replace("```", "").strip()


def create_llm_client(config: Mapping, env: Mapping[str, str] = os.environ) -> LLMClient:
    """Build the provider named by `ai_provider` in config.yaml (default: ollama)."""
    provider = str(config.get("ai_provider", "ollama")).lower()
    if provider == "ollama":
        from awtrix_gpt.llm.ollama import OllamaClient
        return OllamaClient.from_config(config)
    if provider == "gemini":
        from awtrix_gpt.llm.gemini import GeminiClient
        return GeminiClient(api_key=env.get("GEMINI_API_KEY"),
                            model=config.get("gemini_model", DEFAULT_GEMINI_MODEL))
    raise ValueError(f"Unknown ai_provider {provider!r} (expected 'ollama' or 'gemini')")
