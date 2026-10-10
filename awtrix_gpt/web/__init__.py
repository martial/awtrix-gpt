"""Flask application factory. Routes live in the `routes_*` blueprints."""

import logging
import os
from typing import Callable, Optional

from flask import Flask

from awtrix_gpt.manager import AwtrixManager
from awtrix_gpt.paths import TEMPLATES_DIR
from awtrix_gpt.runner import DisplayRunner
from awtrix_gpt.web.services import Services
from config_loader import load_config

logger = logging.getLogger(__name__)


def _default_manager_factory(host: Optional[str] = None, debug: Optional[bool] = None) -> AwtrixManager:
    return AwtrixManager.from_config(load_config(force_reload=True), host=host, debug=debug)


def _try_init(label: str, factory: Callable):
    """Hardware peripherals are optional: a missing camera or printer must not stop the clock."""
    try:
        return factory()
    except Exception as e:
        logger.warning("%s unavailable: %s", label, e)
        return None


def create_app(*, manager_factory: Callable = _default_manager_factory,
               start_display: bool = True, init_hardware: bool = True) -> Flask:
    """Build the app. Tests pass `start_display=False, init_hardware=False`."""
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))

    runner = DisplayRunner(manager_factory)
    if start_display:
        host = os.getenv("AWTRIX_HOST") or load_config()["display"]["host"]
        debug = os.getenv("AWTRIX_DEBUG", "False").lower() == "true"
        try:
            runner.start(host, debug)
        except Exception as e:
            logger.error("Failed to initialize display on startup: %s", e)

    camera = printer = None
    if init_hardware:
        from managers.camera_manager import CameraManager
        from managers.printer_manager import ThermalPrinterManager
        camera = _try_init("Camera", CameraManager)
        printer = _try_init("Thermal printer", ThermalPrinterManager)

    app.extensions["awtrix"] = Services(runner=runner, camera=camera, printer=printer)

    from awtrix_gpt.web.routes_camera import bp as camera_bp
    from awtrix_gpt.web.routes_config import bp as config_bp
    from awtrix_gpt.web.routes_display import bp as display_bp
    from awtrix_gpt.web.routes_printer import bp as printer_bp
    for blueprint in (config_bp, display_bp, camera_bp, printer_bp):
        app.register_blueprint(blueprint)

    return app
