"""Config UI page and the /api/config/* form handlers."""

import logging
import os

from flask import Blueprint, redirect, render_template, request, url_for

from awtrix_gpt.paths import PROMPT_TEMPLATE_PATH
from awtrix_gpt.web.auth import require_api_key
from awtrix_gpt.web.services import error, manager, ok, services
from config_loader import load_config, save_config

bp = Blueprint("config", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    return redirect(url_for("config.config_interface"))


@bp.route("/config")
def config_interface():
    try:
        camera = services().camera
        available_cameras = camera.list_available_cameras() if camera else []
        return render_template("config.html", config=load_config(force_reload=True),
                               available_cameras=available_cameras,
                               api_key=os.getenv("API_KEY", ""))
    except Exception as e:
        logger.error("Error loading configuration: %s", e)
        return error(e)


@bp.route("/api/config/display", methods=["POST"])
@require_api_key
def update_display_config():
    try:
        config = load_config(force_reload=True)
        display = config["display"]
        display["host"] = request.form["host"]
        display["debug"] = "debug" in request.form
        display["active_hours"]["start"] = int(request.form["start_hour"])
        display["active_hours"]["end"] = int(request.form["end_hour"])
        display["message_duration"] = int(request.form["message_duration"])
        save_config(config)

        services().runner.start(host=display["host"], debug=display["debug"])
        return ok(message="Display settings updated successfully")
    except Exception as e:
        logger.error("Error updating display config: %s", e)
        return error(e)


@bp.route("/api/config/prompt", methods=["GET", "POST"])
@require_api_key
def manage_prompt_template():
    if request.method == "POST":
        try:
            new_template = request.form.get("prompt_template")
            if new_template:
                PROMPT_TEMPLATE_PATH.write_text(new_template, encoding="utf-8")
                current = manager()
                if current:
                    current.prompt_template = new_template
                return ok(message="Prompt template updated successfully")
            return error("prompt_template is required", 400)
        except Exception as e:
            logger.error("Error updating prompt template: %s", e)
            return error(e)
    try:
        return ok(template=PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Error reading prompt template: %s", e)
        return error(e)


@bp.route("/api/config/colors", methods=["POST"])
@require_api_key
def update_color_config():
    try:
        config = load_config(force_reload=True)
        for category in config["colors"]:
            hex_value = request.form.get(f"{category}_hex")
            if hex_value:
                config["colors"][category] = hex_value
        save_config(config)
        return ok(message="Colors updated successfully")
    except Exception as e:
        logger.error("Error updating color config: %s", e)
        return error(e)


@bp.route("/api/config/words", methods=["POST"])
@require_api_key
def update_word_config():
    try:
        config = load_config(force_reload=True)
        for category in config["words"]:
            words_text = request.form.get(f"{category}_words", "")
            config["words"][category] = [w.strip() for w in words_text.split(",") if w.strip()]
        save_config(config)
        return ok(message="Word categories updated successfully")
    except Exception as e:
        logger.error("Error updating word config: %s", e)
        return error(e)


@bp.route("/api/config/weather", methods=["POST"])
@require_api_key
def update_weather_config():
    try:
        config = load_config(force_reload=True)
        for city_key, city in config["weather"]["cities"].items():
            city.update({
                "name": request.form.get(f"{city_key}_name"),
                "language": request.form.get(f"{city_key}_language"),
                "lat": float(request.form.get(f"{city_key}_lat")),
                "lon": float(request.form.get(f"{city_key}_lon")),
            })
        save_config(config)
        return ok(message="Weather cities updated successfully")
    except Exception as e:
        logger.error("Error updating weather config: %s", e)
        return error(e)
