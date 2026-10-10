"""API-key guard for mutating routes."""

import os
from functools import wraps

from flask import jsonify, request


def require_api_key(view):
    """Require `X-API-Key` when an API_KEY is configured server-side.

    Fails OPEN when no API_KEY is set (so a missing .env never locks the whole
    device out) and CLOSED with 401 when one is set and the header is wrong or
    missing. GET pages for the config UI and image previews stay unprotected.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        configured = os.getenv("API_KEY")
        if configured and request.headers.get("X-API-Key") != configured:
            return jsonify({"error": "Invalid or missing API key"}), 401
        return view(*args, **kwargs)
    return wrapper
