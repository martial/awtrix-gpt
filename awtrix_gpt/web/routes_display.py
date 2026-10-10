"""Live display endpoints: status, ad-hoc messages, love notes, local info."""

import logging

from flask import Blueprint, request

from awtrix_gpt.generation import first_line, love_note_prompt
from awtrix_gpt.web.auth import require_api_key
from awtrix_gpt.web.services import error, llm_client, manager, ok, services

bp = Blueprint("display", __name__)
logger = logging.getLogger(__name__)

FRENCH_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


@bp.route("/api/status", methods=["GET"])
def get_status():
    current = manager()
    data = {"initialized": current is not None, "running": services().runner.running}
    if current:
        data.update(current.status())
    return ok(data=data)


@bp.route("/api/send", methods=["POST"])
@require_api_key
def send_message():
    """Show a custom coloured message (non-blocking)."""
    current = manager()
    if not current:
        return error("Display not initialized")
    try:
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        duration = int(data.get("duration", 15))
        if not text:
            return error("Text is required", 400)
        current.push_text(text, duration=duration)
        return ok(message="Message sent successfully", text=text, duration=duration)
    except Exception as e:
        logger.error("Error sending message: %s", e)
        return error(e)


@bp.route("/api/display_now", methods=["POST"])
@require_api_key
def display_now():
    """Push an ad-hoc message/emoji to the matrix (Telegram -> matrix bridge)."""
    current = manager()
    if not current:
        return error("Display not initialized")
    try:
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return error("Text is required", 400)
        current.push_text(text, rainbow=bool(data.get("rainbow", False)), color=data.get("color"),
                          duration=int(data.get("duration", 12)), hold=bool(data.get("hold", False)))
        return ok(message="Displayed", text=text)
    except Exception as e:
        logger.error("Error in /api/display_now: %s", e)
        return error(e)


@bp.route("/api/love_note", methods=["POST", "GET"])
@require_api_key
def love_note():
    """Generate a short love note, scroll it rainbow on the matrix, print if a printer is there."""
    current = manager()
    if not current:
        return error("Display not initialized")
    try:
        data = request.get_json(force=True, silent=True) or {}
        note = (data.get("text") or "").strip()
        if not note:
            note = first_line(llm_client().generate(love_note_prompt(data.get("lang", "")), timeout=120))
        current.push_text(note, rainbow=True, duration=int(data.get("duration", 15)))

        printed = False
        printer = services().printer
        if printer and getattr(printer, "is_initialized", False):
            try:
                printer.print_text(note + "\n", 2)
                printed = True
            except Exception as pe:
                logger.warning("Love note print skipped: %s", pe)
        return ok(note=note, printed=printed)
    except Exception as e:
        logger.error("Error in /api/love_note: %s", e)
        return error(e)


def _local_info():
    current = manager()
    return current, (current.local_info if current else None)


@bp.route("/api/local_info", methods=["GET"])
def local_info_route():
    """Real Marseille/Cassis info: air quality, sun, tides, events, reco."""
    current, info = _local_info()
    if not info:
        return error("Local info not available", 503)
    try:
        weather = current.weather.latest.get("MARSEILLE") or {}
        return ok(data=info.get_full(weather=weather, sea_wave=current.sea.wave))
    except Exception as e:
        logger.error("Error in /api/local_info: %s", e)
        return error(e)


@bp.route("/api/events", methods=["GET"])
def events_route():
    _, info = _local_info()
    if not info:
        return error("Local info not available", 503)
    try:
        return ok(events=info.get_events(limit=int(request.args.get("limit", 6))))
    except Exception as e:
        logger.error("Error in /api/events: %s", e)
        return error(e)


@bp.route("/api/parasol", methods=["GET"])
def parasol_route():
    _, info = _local_info()
    if not info:
        return error("Local info not available", 503)
    try:
        return ok(data=info.get_parasol_warning())
    except Exception as e:
        logger.error("Error in /api/parasol: %s", e)
        return error(e)


@bp.route("/api/bins", methods=["GET"])
def bins_route():
    _, info = _local_info()
    if not info:
        return error("Local info not available", 503)
    try:
        today = info.get_bin_reminder()
        schedule = {FRENCH_DAYS[day]: text for day, (text, _color) in info.BIN_SCHEDULE.items()}
        return ok(today=today[0] if today else None, schedule=schedule)
    except Exception as e:
        logger.error("Error in /api/bins: %s", e)
        return error(e)
