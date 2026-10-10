"""Thermal printer endpoints, including the photo -> poem -> print flow."""

import base64
import io
import logging
import traceback

from flask import Blueprint, request, send_file

from awtrix_gpt.generation import PHOTO_POEM_PROMPT, PHOTO_POEM_SCHEMA, parse_photo_poem
from awtrix_gpt.paths import PROJECT_ROOT
from awtrix_gpt.printing import add_text_to_image, format_french_timestamp, wrap_and_reverse_text
from awtrix_gpt.web.auth import require_api_key
from awtrix_gpt.web.services import error, llm_client, ok, services

bp = Blueprint("printer", __name__)
logger = logging.getLogger(__name__)

PHOTO_PATH = PROJECT_ROOT / "photo.jpg"
PHOTO_ORIGINAL_PATH = PROJECT_ROOT / "photo_original.jpg"


def _printer_or_error():
    printer = services().printer
    if printer and getattr(printer, "is_initialized", False):
        return printer, None
    return None, error("Printer not available", 503)


@bp.route("/api/printer/status", methods=["GET"])
def get_printer_status():
    printer, failure = _printer_or_error()
    if failure:
        return failure
    try:
        ready = printer.test_print()
        return ok(message="Printer is ready") if ready else error("Printer not responding")
    except Exception as e:
        logger.error("Error getting printer status: %s", e)
        return error(e)


@bp.route("/api/printer/print", methods=["POST"])
@require_api_key
def print_snapshot():
    printer, failure = _printer_or_error()
    if failure:
        return failure
    try:
        image_path = (request.get_json(force=True, silent=True) or {}).get("image_path")
        if not image_path:
            return error("Image path is required", 400)
        if printer.print_image(image_path):
            return ok(message="Image printed successfully")
        return error("Failed to print image")
    except Exception as e:
        logger.error("Error printing image: %s", e)
        return error(e)


@bp.route("/api/generate_poem_with_photo", methods=["POST", "GET"])
@require_api_key
def generate_poem_with_photo():
    """Take a photo, have the LLM write a poem about it, print both, return the captioned photo."""
    camera = services().camera
    if not camera:
        return error("Camera not available", 503)
    try:
        original, threshold = camera.get_preview_frame()
        if not original or not threshold:
            return error("Failed to capture photo")
        PHOTO_PATH.write_bytes(threshold)
        PHOTO_ORIGINAL_PATH.write_bytes(original)

        image_b64 = base64.b64encode(original).decode("utf-8")
        raw = llm_client().generate(PHOTO_POEM_PROMPT, schema=PHOTO_POEM_SCHEMA, images=[image_b64])
        try:
            poem = parse_photo_poem(raw)
        except ValueError as e:
            logger.error("Error parsing JSON: %s, raw text: %s", e, raw)
            return error(f"JSON parsing error: {e}")

        timestamp = format_french_timestamp()
        printer = services().printer
        if printer and getattr(printer, "is_initialized", False):
            printer.printer.justify("C")
            printer.printer.bold(False)
            printer.print_text("----------", 2)
            printer.print_image(str(PHOTO_PATH))
            printer.printer.bold(False)
            printer.printer.justify("L")
            printer.print_text(wrap_and_reverse_text(poem["result"]) + "\n", 0)
            printer.print_text(wrap_and_reverse_text(poem["description"]) + "\n", 0)
            printer.print_text(wrap_and_reverse_text(timestamp), 0)
            printer.print_text("\n")
        else:
            logger.warning("Printer not available: poem not printed")

        processed = add_text_to_image(threshold, poem["result"])
        return send_file(io.BytesIO(processed), mimetype="image/jpeg", as_attachment=True,
                         download_name="photo_with_poem.jpg")
    except Exception as e:
        logger.error("Error in /api/generate_poem_with_photo: %s", e)
        logger.error(traceback.format_exc())
        return error(e)
