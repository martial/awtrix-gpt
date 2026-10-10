import unittest
from datetime import datetime, timedelta

from awtrix_gpt.sea import SeaService, current_hour_values, sea_widget_line
from awtrix_gpt.weather import (WeatherService, build_weather_lines, city_weather_lines,
                                describe_weather_for_prompt, parse_openweather, wind_kmh)

CITIES = {
    "MARSEILLE": {"name": "Marseille", "language": "fr", "lat": 43.3, "lon": 5.4},
    "AMANTEA": {"name": "Amantea", "language": "it", "lat": 39.1, "lon": 16.1},
}

OPENWEATHER_PAYLOAD = {
    "main": {"temp": 17.6, "feels_like": 13.2, "temp_min": 15.1, "temp_max": 19.4,
             "humidity": 62, "pressure": 1015},
    "wind": {"speed": 12.4, "deg": 320},
    "clouds": {"all": 20},
    "visibility": 10000,
    "weather": [{"description": "ciel dégagé"}],
}


class ParseOpenWeatherTests(unittest.TestCase):
    def test_flattens_and_rounds(self):
        w = parse_openweather(OPENWEATHER_PAYLOAD)
        self.assertEqual(w["temp"], 18)
        self.assertEqual(w["feels_like"], 13)
        self.assertEqual(w["temp_min"], 15)
        self.assertEqual(w["temp_max"], 19)
        self.assertEqual(w["wind_speed"], 12.4)
        self.assertEqual(w["wind_direction"], 320)
        self.assertEqual(w["cloudiness"], 20)
        self.assertEqual(w["description"], "ciel dégagé")

    def test_missing_fields_do_not_crash(self):
        w = parse_openweather({"main": {"temp": 20}})
        self.assertEqual(w["temp"], 20)
        self.assertIsNone(w["feels_like"])
        self.assertIsNone(w["wind_speed"])
        self.assertEqual(w["description"], "")

    def test_wind_kmh(self):
        self.assertEqual(wind_kmh(10), 36)
        self.assertIsNone(wind_kmh(None))
        self.assertIsNone(wind_kmh("n/a"))


class CityWeatherLinesTests(unittest.TestCase):
    def test_main_line_in_french_with_folded_description_and_kmh(self):
        lines = city_weather_lines("Marseille", {"temp": 18, "description": "ciel dégagé",
                                                 "wind_speed": 3.0}, "fr")
        self.assertEqual(lines, ["Marseille: 18C, ciel degage | vent 11 km/h"])

    def test_italian_phrasing(self):
        lines = city_weather_lines("Amantea", {"temp": 24, "description": "cielo sereno", "wind_speed": 2.0,
                                               "feels_like": 28}, "it")
        self.assertEqual(lines, ["Amantea: 24C, cielo sereno | vento 7 km/h", "Amantea: percepiti 28C"])

    def test_mistral_detected_only_in_marseille_with_strong_northwesterly(self):
        w = {"temp": 15, "wind_speed": 15.0, "wind_direction": 320}
        self.assertIn("Marseille: mistral 54 km/h", city_weather_lines("Marseille", w, "fr", mistral_zone=True))
        self.assertIn("Amantea: vento forte 54 km/h", city_weather_lines("Amantea", w, "it"))
        southerly = dict(w, wind_direction=180)
        self.assertIn("Marseille: vent fort 54 km/h", city_weather_lines("Marseille", southerly, "fr", mistral_zone=True))

    def test_feels_like_only_when_it_differs(self):
        self.assertEqual(len(city_weather_lines("M", {"temp": 18, "feels_like": 17}, "fr")), 1)
        self.assertEqual(city_weather_lines("M", {"temp": 18, "feels_like": 13}, "fr")[1], "M: ressenti 13C")

    def test_humidity_and_minmax(self):
        lines = city_weather_lines("M", {"temp": 20, "humidity": 90, "temp_min": 14, "temp_max": 22}, "fr")
        self.assertIn("M: humidite 90%", lines)
        self.assertIn("M: min 14C / max 22C", lines)

    def test_no_temperature_means_no_lines(self):
        self.assertEqual(city_weather_lines("M", {"description": "pluie"}, "fr"), [])

    def test_lines_never_contradict_each_other(self):
        """Every line is derived from the same numbers: one description per city, period."""
        w = {"temp": 18, "description": "pluie legere", "wind_speed": 4, "feels_like": 18}
        lines = city_weather_lines("Marseille", w, "fr")
        self.assertEqual(sum("pluie" in l for l in lines), 1)
        self.assertFalse(any("soleil" in l for l in lines))


class BuildWeatherLinesTests(unittest.TestCase):
    def test_both_cities_in_config_order_skipping_missing(self):
        by_city = {"MARSEILLE": {"temp": 18, "description": "nuageux", "wind_speed": 2.0}, "AMANTEA": None}
        lines = build_weather_lines(by_city, CITIES)
        self.assertEqual(lines, ["Marseille: 18C, nuageux | vent 7 km/h"])

    def test_city_name_from_key_when_missing_and_width_respected(self):
        by_city = {"X": {"temp": 1, "description": "d" * 100}}
        (line,) = build_weather_lines(by_city, {"X": {}}, max_chars=30)
        self.assertTrue(line.startswith("X: 1C, ddd"))
        self.assertLessEqual(len(line), 30)

    def test_empty_when_no_data(self):
        self.assertEqual(build_weather_lines({}, CITIES), [])


class DescribeForPromptTests(unittest.TestCase):
    def test_unavailable(self):
        self.assertEqual(describe_weather_for_prompt(None), "data unavailable")
        self.assertEqual(describe_weather_for_prompt({}), "data unavailable")

    def test_contains_real_numbers(self):
        text = describe_weather_for_prompt(parse_openweather(OPENWEATHER_PAYLOAD))
        self.assertIn("18C", text)
        self.assertIn("ciel dégagé", text)
        self.assertIn("wind 45 km/h", text)


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("boom")


class WeatherServiceTests(unittest.TestCase):
    def test_fetch_parses_each_city_and_caches(self):
        calls = []

        def http_get(url, params, timeout):
            calls.append(params["lat"])
            return _Response(OPENWEATHER_PAYLOAD)

        now = [datetime(2026, 10, 10, 9, 0)]
        svc = WeatherService(CITIES, "key", http_get=http_get, now=lambda: now[0])
        data = svc.fetch()
        self.assertEqual(set(data), {"MARSEILLE", "AMANTEA"})
        self.assertEqual(data["MARSEILLE"]["temp"], 18)
        self.assertEqual(svc.fetch(), data)                 # cached: same object, no new calls
        self.assertEqual(len(calls), 2)
        now[0] += timedelta(minutes=11)
        svc.fetch()
        self.assertEqual(len(calls), 4)

    def test_failed_city_is_none_others_survive(self):
        def http_get(url, params, timeout):
            return _Response(OPENWEATHER_PAYLOAD, status=500 if params["lat"] == 39.1 else 200)
        svc = WeatherService(CITIES, "key", http_get=http_get)
        data = svc.fetch()
        self.assertIsNotNone(data["MARSEILLE"])
        self.assertIsNone(data["AMANTEA"])

    def test_no_api_key_returns_empty_without_calling(self):
        svc = WeatherService(CITIES, None, http_get=lambda *a, **k: self.fail("must not be called"))
        self.assertEqual(svc.fetch(), {})


class SeaTests(unittest.TestCase):
    def test_sea_widget_line(self):
        self.assertEqual(sea_widget_line(18, 17.2, 0.44), "Marseille: 18C | Eau: 17.2C | Houle: 0.4m")
        self.assertEqual(sea_widget_line(18, None, None), "Marseille: 18C | Eau: ~16C")
        self.assertEqual(sea_widget_line(10, None, None), "Marseille: 10C | Eau: ~13C")   # clamped estimate

    def test_current_hour_values(self):
        hourly = {"a": [1, 2, 3], "b": [4, None, 6]}
        self.assertEqual(current_hour_values(hourly, 2, ("a", "b")), {"a": 3, "b": 6})
        self.assertIsNone(current_hour_values(hourly, 1, ("a", "b")))
        self.assertIsNone(current_hour_values(hourly, 7, ("a",)))

    def test_refresh_uses_local_hour_and_caches(self):
        requests_made = []

        def http_get(url, params, timeout):
            requests_made.append(params)
            if "current" in params:
                return _Response({"current": {"sea_surface_temperature": 17.26}})
            return _Response({"hourly": {"wave_height": [0.1] * 24, "wave_direction": [200] * 24,
                                         "wave_period": [5] * 24}})

        now = [datetime(2026, 10, 10, 15, 0)]
        svc = SeaService(http_get=http_get, now=lambda: now[0])
        svc.refresh()
        self.assertEqual(svc.temperature, 17.3)
        self.assertEqual(svc.wave_height, 0.1)
        self.assertEqual(requests_made[1]["timezone"], "Europe/Paris")
        svc.refresh()
        self.assertEqual(len(requests_made), 2)


if __name__ == "__main__":
    unittest.main()
