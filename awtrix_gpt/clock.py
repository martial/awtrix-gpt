"""HTTP client for the AWTRIX clock's notify API. Nothing else lives here."""

import logging
from typing import Optional

import requests

from awtrix_gpt.text import Highlighter

Fragments = list[dict[str, str]]


class AwtrixClient:
    """Thin wrapper over `POST http://<host>/api/notify`.

    `session` is anything with a requests-like `.post()`; tests inject a fake.
    """

    def __init__(self, host: str, *, session=None, timeout: float = 10.0, logger=None):
        self.host = host
        self.base_url = f"http://{host}/api"
        self._http = session or requests
        self._timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

    def notify(self, payload: dict) -> None:
        response = self._http.post(f"{self.base_url}/notify", json=payload, timeout=self._timeout)
        response.raise_for_status()

    def show(self, fragments: Fragments, duration: int, repeat: int = 1) -> None:
        """Show coloured fragments once. Does not block; callers pace themselves."""
        self.notify({"text": fragments, "repeat": repeat, "duration": duration})

    def push_text(self, text: str, *, duration: int, rainbow: bool = False,
                  color: Optional[str] = None, hold: bool = False,
                  highlighter: Optional[Highlighter] = None) -> None:
        """Push an ad-hoc notification (Telegram bridge, love notes).

        AWTRIX queues notifications over the running apps, so this overlays the
        normal cycle without disrupting it.
        """
        payload: dict = {"duration": duration, "repeat": 1}
        if rainbow:
            payload.update(text=text, rainbow=True)
        elif color:
            payload.update(text=text, color=color)
        else:
            payload["text"] = highlighter.fragments(text) if highlighter else text
        if hold:
            payload["hold"] = True
        self.notify(payload)
