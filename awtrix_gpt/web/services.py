"""Shared per-app state for the blueprints, plus small response helpers."""

from dataclasses import dataclass
from typing import Any, Optional

from flask import current_app, jsonify

from awtrix_gpt.llm import LLMClient, create_llm_client
from awtrix_gpt.manager import AwtrixManager
from awtrix_gpt.runner import DisplayRunner
from config_loader import load_config


@dataclass
class Services:
    runner: DisplayRunner
    camera: Any = None      # managers.camera_manager.CameraManager, when opencv + a camera exist
    printer: Any = None     # managers.printer_manager.ThermalPrinterManager, when connected


def services() -> Services:
    return current_app.extensions["awtrix"]


def manager() -> Optional[AwtrixManager]:
    return services().runner.manager


def llm_client() -> LLMClient:
    """A fresh client each call: `ai_provider` / `ollama_*` can change at runtime via config.yaml."""
    return create_llm_client(load_config())


def ok(**payload):
    return jsonify({"status": "success", **payload})


def error(message: str, status: int = 500):
    return jsonify({"status": "error", "message": str(message)}), status
