"""AwtrixManager with every collaborator faked: no clock, no network, no LLM."""

import json
import unittest
from datetime import datetime, timedelta

from awtrix_gpt.clock import AwtrixClient
from awtrix_gpt.content import Content
from awtrix_gpt.generation import CONTENT_SCHEMA, FALLBACK_LINES
from awtrix_gpt.manager import AwtrixManager
from awtrix_gpt.news import Headline
from awtrix_gpt.scheduler import UpdateScheduler
from awtrix_gpt.text import Highlighter

CONFIG = {
    "display": {"host": "10.0.0.5", "debug": False, "message_duration": 10, "cycle_delay": 7,
                "active_hours": {"start": 7, "end": 23}, "update_interval": 1800},
    "weather": {"cities": {
        "MARSEILLE": {"name": "Marseille", "language": "fr", "lat": 43.3, "lon": 5.4},
        "AMANTEA": {"name": "Amantea", "language": "it", "lat": 39.1, "lon": 16.1},
    }},
    "words": {"cities": ["marseille"]},
    "colors": {"cities": "#00BFFF", "default": "#FFFFFF", "numbers": "#FFD700"},
}

WEATHER = {
    "MARSEILLE": {"temp": 18, "feels_like": 17, "description": "ciel degage", "wind_speed": 3.0,
                  "wind_direction": 300, "humidity": 50, "temp_min": 17, "temp_max": 19, "cloudiness": 5},
    "AMANTEA": {"temp": 24, "feels_like": 25, "description": "cielo sereno", "wind_speed": 1.0},
}
HEADLINES = [Headline("Budget 2027 : le gouvernement presente son plan", source="Le Monde"),
             Headline("Tempete sur la Bretagne ce week-end", source="Le Figaro")]
LLM_JSON = json.dumps({
    "messages": ["Buongiorno Betty, caffe?", "Marziol, ton smoothie t'attend"],
    "suggested_activities": ["Pasta alla Norma ce soir"],
    "poems": ["Mer calme, coeur leger"],
    # the model must not be able to smuggle facts in:
    "news": ["Etat d'urgence sanitaire en Corse"],
    "weather": ["Il pleut a Marseille"],
})


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self

    def raise_for_status(self):
        pass


class FakeWeather:
    def __init__(self, data):
        self.data, self.latest, self.calls = data, {}, 0

    def fetch(self, force=False):
        self.calls += 1
        self.latest = self.data
        return self.data


class FakeSea:
    temperature = 17.5
    wave = {"height": 0.4}
    wave_height = 0.4

    def refresh(self, force=False):
        pass


class FakeNews:
    def __init__(self, headlines):
        self.headlines = headlines

    def fetch(self, force=False):
        return self.headlines


class FakeLLM:
    name = "fake"

    def __init__(self, result):
        self.result, self.calls = result, []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeScenes:
    def __init__(self):
        self.calls = []

    def refresh_scenes(self, host, weather, sea=None):
        self.calls.append((host, weather, sea))


class FakeLocalInfo:
    BIN_SCHEDULE = {0: ("Sors les ordures", "#33CC33")}

    def __init__(self, parasol=False):
        self.parasol = parasol

    def get_display_lines(self, weather=None, sea_wave=None):
        return ["Air Marseille: bon (20)"]

    def get_parasol_warning(self):
        return {"alert": self.parasol, "detail": "rafales 15m/s ce soir"}

    def get_bin_reminder(self):
        return self.BIN_SCHEDULE[0]


def make_manager(*, llm=None, headlines=HEADLINES, weather=WEATHER, now=None, local_info=None):
    session = FakeSession()
    sleeps = []
    clock_now = now or datetime(2026, 10, 10, 10, 0)
    manager = AwtrixManager(
        CONFIG,
        clock=AwtrixClient("10.0.0.5", session=session),
        highlighter=Highlighter.from_config(CONFIG),
        weather=FakeWeather(weather),
        sea=FakeSea(),
        news=FakeNews(headlines),
        llm=llm if llm is not None else FakeLLM(LLM_JSON),
        prompt_template="Time {timestamp}. M: {marseille_weather}. A: {amantea_weather}.",
        scheduler=UpdateScheduler.from_config(CONFIG["display"]),
        local_info=local_info,
        scenes=FakeScenes(),
        sleep=sleeps.append,
        now=lambda: clock_now,
        shuffle=lambda items: None,     # deterministic order
    )
    manager._test_session = session
    manager._test_sleeps = sleeps
    return manager


class RefreshContentTests(unittest.TestCase):
    def test_news_and_weather_come_from_data_not_from_the_llm(self):
        m = make_manager()
        content = m.refresh_content()

        self.assertEqual([i.text for i in content.news], [
            "Le Monde: Budget 2027 : le gouvernement presente son plan",
            "Le Figaro: Tempete sur la Bretagne ce week-end",
        ])
        self.assertEqual([i.text for i in content.weather], [
            "Marseille: 18C, ciel degage | vent 11 km/h",
            "Amantea: 24C, cielo sereno | vento 4 km/h",
        ])
        everything = " ".join(i.text for i in content.all_items())
        self.assertNotIn("Corse", everything)
        self.assertNotIn("Il pleut", everything)

    def test_creative_categories_come_from_the_llm(self):
        m = make_manager()
        content = m.refresh_content()
        self.assertEqual([i.text for i in content.messages], ["Buongiorno Betty, caffe?", "Marziol, ton smoothie t'attend"])
        self.assertEqual([i.text for i in content.suggested_activities], ["Pasta alla Norma ce soir"])
        self.assertEqual([i.text for i in content.poems], ["Mer calme, coeur leger"])
        self.assertEqual(content.messages[0].id, "MSG_0")
        self.assertEqual(content.news[0].id, "NEWS_0")

    def test_llm_gets_the_schema_and_real_weather_context_but_no_news(self):
        m = make_manager()
        m.refresh_content()
        prompt, kwargs = m.llm.calls[0]
        self.assertIs(kwargs["schema"], CONTENT_SCHEMA)
        self.assertIn("Saturday 10 October 2026 10:00", prompt)
        self.assertIn("18C", prompt)
        self.assertIn("ciel degage", prompt)
        self.assertNotIn("Budget 2027", prompt)

    def test_llm_failure_keeps_facts_and_uses_fallback_for_creative(self):
        m = make_manager(llm=FakeLLM(RuntimeError("ollama down")))
        content = m.refresh_content()
        self.assertEqual(len(content.news), 2)
        self.assertEqual(len(content.weather), 2)
        self.assertEqual([i.text for i in content.messages], FALLBACK_LINES["messages"])
        self.assertEqual([i.text for i in content.poems], FALLBACK_LINES["poems"])
        self.assertIsNotNone(m.last_update)

    def test_invalid_llm_json_is_a_soft_failure(self):
        m = make_manager(llm=FakeLLM("{} trailing garbage"))
        content = m.refresh_content()
        self.assertEqual([i.text for i in content.messages], FALLBACK_LINES["messages"])
        self.assertEqual(len(content.news), 2)

    def test_second_failure_keeps_previous_creative_content(self):
        m = make_manager()
        m.refresh_content()
        m.llm = FakeLLM(RuntimeError("down"))
        content = m.refresh_content()
        self.assertEqual([i.text for i in content.messages], ["Buongiorno Betty, caffe?", "Marziol, ton smoothie t'attend"])

    def test_no_llm_client_at_all(self):
        m = make_manager(llm=False)
        m.llm = None
        content = m.refresh_content()
        self.assertEqual([i.text for i in content.suggested_activities], FALLBACK_LINES["suggested_activities"])
        self.assertEqual(len(content.news), 2)

    def test_empty_news_feed_means_no_news_lines(self):
        content = make_manager(headlines=[]).refresh_content()
        self.assertEqual(content.news, [])

    def test_missing_weather_means_no_weather_lines_and_prompt_says_so(self):
        m = make_manager(weather={})
        content = m.refresh_content()
        self.assertEqual(content.weather, [])
        self.assertIn("data unavailable", m.llm.calls[0][0])

    def test_local_info_and_scenes_are_refreshed(self):
        m = make_manager(local_info=FakeLocalInfo())
        content = m.refresh_content()
        self.assertEqual([i.text for i in content.local_info], ["Air Marseille: bon (20)"])
        host, weather, sea = m.scenes.calls[0]
        self.assertEqual(host, "10.0.0.5")
        self.assertEqual(weather["temp"], 18)
        self.assertEqual(sea, {"height": 0.4, "temp": 17.5})

    def test_refresh_resets_queue_and_stamps_time(self):
        m = make_manager()
        m.message_queue = ["stale"]
        m.refresh_content()
        self.assertEqual(m.message_queue, [])
        self.assertEqual(m.last_update, datetime(2026, 10, 10, 10, 0))


class DisplayCycleTests(unittest.TestCase):
    def test_cycle_shows_next_item_then_sea_widget(self):
        m = make_manager()
        m.refresh_content()
        total = len(m.content.all_items())
        m.display_cycle()

        posts = m._test_session.posts
        self.assertEqual(len(posts), 2)
        url, payload = posts[0]
        self.assertEqual(url, "http://10.0.0.5/api/notify")
        self.assertEqual(payload["duration"], 10)
        self.assertEqual(payload["text"][0]["t"], "Buongiorno")          # first item, no shuffle
        self.assertEqual("".join(f["t"] for f in posts[1][1]["text"]),
                         "Marseille: 18C | Eau: 17.5C | Houle: 0.4m")
        self.assertEqual(posts[1][1]["duration"], 4)
        self.assertEqual(len(m.message_queue), total - 1)
        self.assertEqual(m._test_sleeps, [10, 7, 4])

    def test_queue_refills_when_empty(self):
        m = make_manager()
        m.refresh_content()
        for _ in range(len(m.content.all_items()) + 1):
            m.display_cycle()
        self.assertEqual(len(m.message_queue), len(m.content.all_items()) - 1)

    def test_no_content_no_post(self):
        m = make_manager()
        m.display_cycle()
        self.assertEqual(m._test_session.posts, [])

    def test_evening_reminders_only_after_18h(self):
        morning = make_manager(local_info=FakeLocalInfo(parasol=True), now=datetime(2026, 10, 12, 10, 0))
        morning.display_cycle()
        self.assertEqual(morning._test_session.posts, [])

        evening = make_manager(local_info=FakeLocalInfo(parasol=True), now=datetime(2026, 10, 12, 20, 0))
        evening.display_cycle()
        texts = [p[1]["text"] for p in evening._test_session.posts]
        self.assertEqual(texts, ["Rentre les parasols! rafales 15m/s ce soir", "Sors les ordures"])
        self.assertEqual(evening._test_session.posts[0][1]["color"], "#FF0000")

    def test_highlighter_colours_words_in_display(self):
        m = make_manager()
        m.show_text("Marseille 18C")
        payload = m._test_session.posts[0][1]
        colors = {f["t"]: f["c"] for f in payload["text"]}
        self.assertEqual(colors["Marseille"], "#00BFFF")
        self.assertEqual(colors["18C"], "#FFD700")

    def test_display_error_is_swallowed(self):
        m = make_manager()

        def boom(*a, **k):
            raise ConnectionError("clock offline")
        m.clock.notify = boom
        m.show_text("x")   # must not raise


class TickAndStatusTests(unittest.TestCase):
    def test_tick_refreshes_when_due_then_displays(self):
        m = make_manager()
        m.tick()
        self.assertEqual(m.weather.calls, 1)
        self.assertEqual(len(m._test_session.posts), 2)
        m.tick()
        self.assertEqual(m.weather.calls, 1)           # not due again

    def test_tick_outside_active_hours_does_not_refresh(self):
        m = make_manager(now=datetime(2026, 10, 10, 3, 0))
        m.tick()
        self.assertEqual(m.weather.calls, 0)

    def test_status_keys_used_by_the_config_page(self):
        m = make_manager()
        m.refresh_content()
        status = m.status()
        for key in ("host", "debug", "last_update", "poems_count", "weather_count", "messages_count",
                    "news_count", "queue_remaining"):
            self.assertIn(key, status)
        self.assertEqual(status["news_count"], 2)
        self.assertEqual(status["llm"], "fake")

    def test_push_text_variants(self):
        m = make_manager()
        m.push_text("hello", rainbow=True, duration=5)
        m.push_text("hello", color="#FF0000", hold=True)
        m.push_text("Marseille")
        posts = [p[1] for p in m._test_session.posts]
        self.assertEqual(posts[0], {"duration": 5, "repeat": 1, "text": "hello", "rainbow": True})
        self.assertEqual(posts[1], {"duration": 10, "repeat": 1, "text": "hello", "color": "#FF0000", "hold": True})
        self.assertEqual(posts[2]["text"], [{"t": "Marseille", "c": "#00BFFF"}])


class ContentModelTests(unittest.TestCase):
    def test_counts_and_empty(self):
        c = Content()
        self.assertTrue(c.is_empty())
        self.assertEqual(set(c.counts()), {"messages", "weather", "news", "suggested_activities", "poems", "local_info"})


if __name__ == "__main__":
    unittest.main()
