"""Ollama `/api/generate` client with JSON-schema structured output."""

import json
import logging
import re
import urllib.request
from typing import Callable, Mapping, Optional

from awtrix_gpt.llm import DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_MODEL, strip_code_fences

# Only genuinely reasoning models get `think: false`. Sent to gemma3 together
# with a schema it makes the model return `{}` instantly (tested 2026-10-10).
THINKING_MODELS = re.compile(r"qwen3|lfm", re.IGNORECASE)


class OllamaClient:
    name = "ollama"

    def __init__(self, host: str, model: str, *, num_ctx: int = 8192, keep_alive: str = "30m",
                 temperature: float = 0.8, urlopen: Callable = urllib.request.urlopen, logger=None):
        self.host = host.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.temperature = temperature
        self._urlopen = urlopen
        self.logger = logger or logging.getLogger(__name__)

    @classmethod
    def from_config(cls, config: Mapping, **overrides) -> "OllamaClient":
        return cls(
            host=config.get("ollama_host", DEFAULT_OLLAMA_HOST),
            model=config.get("ollama_model", DEFAULT_OLLAMA_MODEL),
            num_ctx=int(config.get("ollama_num_ctx", 8192)),
            keep_alive=config.get("ollama_keep_alive", "30m"),
            temperature=float(config.get("ollama_temperature", 0.8)),
            **overrides,
        )

    def build_payload(self, prompt: str, *, schema: Optional[dict] = None,
                      images: Optional[list[str]] = None) -> dict:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Keep the model resident so we do not pay the load time on every cycle.
            "keep_alive": self.keep_alive,
            "options": {
                # The prompt alone is ~2000 tokens. Ollama's default num_ctx=4096
                # silently truncated responses mid-string and broke json.loads().
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
            },
        }
        if schema is not None:
            # A schema OBJECT (structured outputs), never the string "json":
            # gemma3 answers {} to JSON mode.
            payload["format"] = schema
        if images:
            payload["images"] = list(images)
        if THINKING_MODELS.search(self.model):
            payload["think"] = False
        return payload

    def generate(self, prompt: str, *, schema: Optional[dict] = None,
                 images: Optional[list[str]] = None, web_search: bool = False,
                 timeout: int = 300) -> str:
        payload = self.build_payload(prompt, schema=schema, images=images)
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self._urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        return strip_code_fences(result.get("response", ""))
