"""Flask routes against a fake manager: no display thread, no camera, no printer."""

import os
import unittest
from unittest import mock

from awtrix_gpt.web import create_app


class FakeLocalInfo:
    BIN_SCHEDULE = {1: ("Sors le CARTON (demain mercredi)", "#D2691E")}

    def get_bin_reminder(self):
        return self.BIN_SCHEDULE[1]

    def get_parasol_warning(self):
        return {"alert": False, "reason": "", "detail": ""}

    def get_events(self, limit=6):
        return [{"title": "Concert"}][:limit]

    def get_full(self, weather=None, sea_wave=None):
        return {"weather_seen": weather, "sea_wave": sea_wave}


class FakeManager:
    host = "10.0.0.5"
    debug = False
    prompt_template = "old"

    def __init__(self):
        self.pushed = []
        self.local_info = FakeLocalInfo()
        self.weather = type("W", (), {"latest": {"MARSEILLE": {"temp": 18}}})()
        self.sea = type("S", (), {"wave": {"height": 0.3}})()

    def status(self):
        return {"host": self.host, "poems_count": 3, "weather_count": 2, "messages_count": 8,
                "news_count": 4, "queue_remaining": 5, "last_update": "2026-10-10T10:00:00"}

    def push_text(self, text, **kwargs):
        self.pushed.append((text, kwargs))


def make_client(manager=None):
    app = create_app(start_display=False, init_hardware=False)
    app.testing = True
    app.extensions["awtrix"].runner.manager = manager
    return app.test_client(), app


class StatusTests(unittest.TestCase):
    def test_status_without_manager(self):
        client, _ = make_client(None)
        body = client.get("/api/status").get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"], {"initialized": False, "running": False})

    def test_status_with_manager_exposes_dashboard_fields(self):
        client, _ = make_client(FakeManager())
        data = client.get("/api/status").get_json()["data"]
        self.assertTrue(data["initialized"])
        self.assertFalse(data["running"])          # thread not started in tests
        self.assertEqual(data["poems_count"], 3)
        self.assertEqual(data["queue_remaining"], 5)
        self.assertEqual(data["host"], "10.0.0.5")

    def test_root_redirects_to_config(self):
        client, _ = make_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/config"))


class DisplayRoutesTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.client, _ = make_client(self.manager)

    def test_send_pushes_text(self):
        response = self.client.post("/api/send", json={"text": "Ciao", "duration": 7})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.pushed, [("Ciao", {"duration": 7})])

    def test_send_requires_text(self):
        self.assertEqual(self.client.post("/api/send", json={}).status_code, 400)

    def test_display_now_passes_options(self):
        self.client.post("/api/display_now", json={"text": "<3", "rainbow": True, "hold": True, "duration": 3})
        self.assertEqual(self.manager.pushed, [("<3", {"rainbow": True, "color": None, "duration": 3, "hold": True})])

    def test_love_note_with_given_text_does_not_call_llm(self):
        with mock.patch("awtrix_gpt.web.routes_display.llm_client") as llm:
            body = self.client.post("/api/love_note", json={"text": "Ti amo"}).get_json()
        llm.assert_not_called()
        self.assertEqual(body["note"], "Ti amo")
        self.assertFalse(body["printed"])
        self.assertEqual(self.manager.pushed[0][1]["rainbow"], True)

    def test_love_note_generated(self):
        fake_llm = mock.Mock()
        fake_llm.generate.return_value = '"Sei il mio sole"\nseconde ligne'
        with mock.patch("awtrix_gpt.web.routes_display.llm_client", return_value=fake_llm):
            body = self.client.post("/api/love_note", json={}).get_json()
        self.assertEqual(body["note"], "Sei il mio sole")

    def test_local_info_routes(self):
        self.assertEqual(self.client.get("/api/bins").get_json()["schedule"], {"mardi": "Sors le CARTON (demain mercredi)"})
        self.assertEqual(self.client.get("/api/events?limit=1").get_json()["events"], [{"title": "Concert"}])
        self.assertFalse(self.client.get("/api/parasol").get_json()["data"]["alert"])
        data = self.client.get("/api/local_info").get_json()["data"]
        self.assertEqual(data["weather_seen"], {"temp": 18})
        self.assertEqual(data["sea_wave"], {"height": 0.3})

    def test_without_manager_display_routes_fail_cleanly(self):
        client, _ = make_client(None)
        self.assertEqual(client.post("/api/send", json={"text": "x"}).status_code, 500)
        self.assertEqual(client.get("/api/bins").status_code, 503)


class HardwareAbsentTests(unittest.TestCase):
    def test_camera_and_printer_routes_return_503(self):
        client, _ = make_client(FakeManager())
        self.assertEqual(client.post("/api/camera/photo").status_code, 503)
        self.assertEqual(client.get("/api/camera/preview").status_code, 503)
        self.assertEqual(client.get("/api/printer/status").status_code, 503)
        self.assertEqual(client.post("/api/generate_poem_with_photo").status_code, 503)


class ApiKeyTests(unittest.TestCase):
    def test_key_enforced_only_when_configured(self):
        client, _ = make_client(FakeManager())
        with mock.patch.dict(os.environ, {"API_KEY": "secret"}):
            self.assertEqual(client.post("/api/send", json={"text": "x"}).status_code, 401)
            ok = client.post("/api/send", json={"text": "x"}, headers={"X-API-Key": "secret"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(client.get("/api/status").status_code, 200)   # GET stays open
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_KEY", None)
            self.assertEqual(client.post("/api/send", json={"text": "x"}).status_code, 200)


class PromptRouteTests(unittest.TestCase):
    def test_get_and_post_prompt_template(self):
        manager = FakeManager()
        client, _ = make_client(manager)
        with mock.patch("awtrix_gpt.web.routes_config.PROMPT_TEMPLATE_PATH") as path:
            path.read_text.return_value = "TEMPLATE"
            self.assertEqual(client.get("/api/config/prompt").get_json()["template"], "TEMPLATE")
            response = client.post("/api/config/prompt", data={"prompt_template": "NEW"})
            path.write_text.assert_called_once_with("NEW", encoding="utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(manager.prompt_template, "NEW")


if __name__ == "__main__":
    unittest.main()
