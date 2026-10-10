"""Google Gemini client. `google-genai` is imported lazily so the rest of the
app (and the tests) work on machines where it is not installed."""

import base64
import logging
from typing import Optional

from awtrix_gpt.llm import DEFAULT_GEMINI_MODEL, strip_code_fences


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: Optional[str], model: str = DEFAULT_GEMINI_MODEL, logger=None):
        from google import genai  # noqa: WPS433 - optional heavy dependency
        from google.genai import types

        self._genai = genai
        self._types = types
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.logger = logger or logging.getLogger(__name__)

    def generate(self, prompt: str, *, schema: Optional[dict] = None,
                 images: Optional[list[str]] = None, web_search: bool = False,
                 timeout: int = 300) -> str:
        contents: list = []
        for image_b64 in images or ():
            contents.append(self._types.Part.from_bytes(data=base64.b64decode(image_b64),
                                                        mime_type="image/jpeg"))
        contents.append(prompt)

        config = None
        if web_search:
            config = self._types.GenerateContentConfig(tools=[{"google_search": {}}])
        elif schema is not None:
            config = self._types.GenerateContentConfig(response_mime_type="application/json")

        response = self._client.models.generate_content(
            model=self.model, contents=contents if len(contents) > 1 else prompt, config=config)
        return strip_code_fences(response.text or "")
