"""Camera endpoints and the photos folder."""

import io
import logging

from flask import Blueprint, request, send_file, send_from_directory

from awtrix_gpt.paths import PHOTOS_DIR
from awtrix_gpt.web.auth import require_api_key
from awtrix_gpt.web.services import error, ok, services
from config_loader import load_config, save_config

bp = Blueprint("camera", __name__)
logger = logging.getLogger(__name__)


def _camera_or_error():
    camera = services().camera
    return camera, (None if camera else error("Camera not available", 503))


@bp.route("/api/config/camera", methods=["POST"])
@require_api_key
def update_camera_config():
    try:
        config = load_config(force_reload=True)
        cam_cfg = config["camera"]
        old_index = cam_cfg["index"]
        cam_cfg["index"] = int(request.form["camera_index"])
        cam_cfg["name"] = request.form["camera_name"]
        cam_cfg["resolution"]["width"] = int(request.form["resolution_width"])
        cam_cfg["resolution"]["height"] = int(request.form["resolution_height"])
        cam_cfg["settings"]["photo_directory"] = request.form["photo_directory"]
        save_config(config)

        svc = services()
        if svc.camera is None or old_index != cam_cfg["index"]:
            from managers.camera_manager import CameraManager
            if svc.camera is not None:
                svc.camera.close()
            svc.camera = CameraManager()
        else:
            svc.camera.initialize_camera()
        return ok(message="Camera settings updated successfully. Please wait for preview to refresh.")
    except Exception as e:
        logger.error("Error updating camera config: %s", e)
        return error(e)


@bp.route("/api/camera/photo", methods=["POST"])
@require_api_key
def take_photo():
    camera, failure = _camera_or_error()
    if failure:
        return failure
    try:
        filepath = camera.take_picture()
        if filepath:
            return ok(message="Photo taken successfully", filepath=filepath)
        return error("Failed to take photo")
    except Exception as e:
        logger.error("Error taking photo: %s", e)
        return error(e)


@bp.route("/api/camera/preview")
def get_preview():
    camera, failure = _camera_or_error()
    if failure:
        return failure
    try:
        original, _threshold = camera.get_preview_frame()
        if original:
            return send_file(io.BytesIO(original), mimetype="image/jpeg")
        return error("Failed to get preview")
    except Exception as e:
        logger.error("Error getting preview: %s", e)
        return error(e)


@bp.route("/photos/<path:filename>")
def serve_photo(filename):
    try:
        return send_from_directory(str(PHOTOS_DIR), filename)
    except Exception as e:
        logger.error("Error serving photo: %s", e)
        return error("Photo not found", 404)


@bp.route("/api/camera/settings", methods=["GET", "POST"])
@require_api_key
def manage_camera_settings():
    """Brightness/contrast/... tuning. CameraManager does not implement it yet -> 501."""
    camera, failure = _camera_or_error()
    if failure:
        return failure
    if request.method == "POST":
        adjust = getattr(camera, "adjust_settings", None)
        if adjust is None:
            return error("Camera settings adjustment not supported", 501)
        try:
            settings = request.get_json(force=True, silent=True) or {}
            adjust(brightness=settings.get("brightness"), contrast=settings.get("contrast"),
                   saturation=settings.get("saturation"), exposure=settings.get("exposure"))
            return ok(message="Camera settings updated")
        except Exception as e:
            logger.error("Error updating camera settings: %s", e)
            return error(e)
    getter = getattr(camera, "get_current_settings", None)
    if getter is None:
        return error("Camera settings readout not supported", 501)
    try:
        return ok(settings=getter())
    except Exception as e:
        logger.error("Error getting camera settings: %s", e)
        return error(e)
