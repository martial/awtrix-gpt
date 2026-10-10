"""Real weather, fetched from OpenWeather and turned into display lines IN CODE.

The LLM is never asked to describe the weather: given real numbers it still
wrote "il pleut" and "le soleil brille" for the same city in the same batch.
Lines here are built from the numbers, in the city's language (fr / it), and
cannot contradict each other.
"""

import logging
from datetime import datetime, timedelta
from typing import Callable, Mapping, Optional

import requests

from awtrix_gpt.text import DEFAULT_MAX_CHARS, ascii_fold, truncate_line

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

STRONG_WIND_KMH = 40      # "vent fort" from here
MISTRAL_MIN_KMH = 30      # a north-westerly this strong over Marseille is the mistral
FEELS_LIKE_DELTA = 3      # mention feels-like only when it differs noticeably
HUMID_PERCENT = 85
MINMAX_SPREAD = 3
MISTRAL_CITIES = frozenset({"MARSEILLE"})

PHRASES = {
    "fr": {"wind": "vent", "feels": "ressenti", "strong_wind": "vent fort",
           "humidity": "humidite", "minmax": "min {lo}C / max {hi}C"},
    "it": {"wind": "vento", "feels": "percepiti", "strong_wind": "vento forte",
           "humidity": "umidita", "minmax": "min {lo}C / max {hi}C"},
}


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def parse_openweather(data: Mapping) -> dict:
    """Flatten an OpenWeather `weather` response into the dict the rest of the app uses."""
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    first = (data.get("weather") or [{}])[0] or {}

    def rounded(key):
        value = main.get(key)
        return None if value is None else round(value)

    return {
        "temp": rounded("temp"),
        "feels_like": rounded("feels_like"),
        "temp_max": rounded("temp_max"),
        "temp_min": rounded("temp_min"),
        "humidity": main.get("humidity"),
        "wind_speed": wind.get("speed"),
        "wind_direction": wind.get("deg"),
        "visibility": data.get("visibility", "N/A"),
        "pressure": main.get("pressure"),
        "cloudiness": (data.get("clouds") or {}).get("all"),
        "description": first.get("description", ""),
    }


def wind_kmh(speed_ms) -> Optional[int]:
    try:
        return round(float(speed_ms) * 3.6)
    except (TypeError, ValueError):
        return None


def is_northwesterly(degrees) -> bool:
    try:
        return 280 <= float(degrees) <= 350
    except (TypeError, ValueError):
        return False


def city_weather_lines(name: str, weather: Mapping, language: str = "fr",
                       *, mistral_zone: bool = False) -> list[str]:
    """Factual one-liners for one city. Returns [] when there is no temperature."""
    temp = weather.get("temp")
    if temp is None:
        return []
    p = PHRASES.get(language, PHRASES["fr"])
    name = ascii_fold(name)
    kmh = wind_kmh(weather.get("wind_speed"))

    main = f"{name}: {temp}C"
    description = ascii_fold(weather.get("description") or "").strip()
    if description:
        main += f", {description}"
    if kmh is not None:
        main += f" | {p['wind']} {kmh} km/h"
    lines = [main]

    feels = weather.get("feels_like")
    if feels is not None and abs(feels - temp) >= FEELS_LIKE_DELTA:
        lines.append(f"{name}: {p['feels']} {feels}C")

    if kmh is not None and kmh >= STRONG_WIND_KMH:
        label = p["strong_wind"]
        if mistral_zone and kmh >= MISTRAL_MIN_KMH and is_northwesterly(weather.get("wind_direction")):
            label = "mistral"
        lines.append(f"{name}: {label} {kmh} km/h")

    humidity = weather.get("humidity")
    if humidity is not None and humidity >= HUMID_PERCENT:
        lines.append(f"{name}: {p['humidity']} {humidity}%")

    lo, hi = weather.get("temp_min"), weather.get("temp_max")
    if lo is not None and hi is not None and hi - lo >= MINMAX_SPREAD:
        lines.append(f"{name}: " + p["minmax"].format(lo=lo, hi=hi))
    return lines


def build_weather_lines(weather_by_city: Mapping[str, Optional[Mapping]],
                        cities: Mapping[str, Mapping], *,
                        max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Display lines for every configured city that has data, in config order."""
    lines: list[str] = []
    for key, city in cities.items():
        weather = weather_by_city.get(key)
        if not weather:
            continue
        lines.extend(city_weather_lines(
            city.get("name") or key.title(), weather, city.get("language", "fr"),
            mistral_zone=key in MISTRAL_CITIES))
    return [truncate_line(line, max_chars) for line in lines]


def describe_weather_for_prompt(weather: Optional[Mapping]) -> str:
    """One factual sentence of context for the LLM (it is NOT asked to repeat it)."""
    if not weather or weather.get("temp") is None:
        return "data unavailable"
    kmh = wind_kmh(weather.get("wind_speed"))
    parts = [f"{weather['temp']}C", f"feels like {weather.get('feels_like', '??')}C"]
    if weather.get("description"):
        parts.append(str(weather["description"]))
    parts.append(f"humidity {weather.get('humidity', '??')}%")
    parts.append(f"wind {kmh if kmh is not None else '??'} km/h")
    parts.append(f"cloudiness {weather.get('cloudiness', '??')}%")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

class WeatherService:
    """Current weather per configured city from OpenWeather, cached for `ttl`.

    `fetch()` returns the cached dict when called within `ttl`, never an empty
    dict just because of rate limiting. A city whose request fails maps to None.
    """

    def __init__(self, cities: Mapping[str, Mapping], api_key: Optional[str], *,
                 ttl: timedelta = timedelta(minutes=10), http_get: Callable = requests.get,
                 now: Callable[[], datetime] = datetime.now, logger=None):
        self.cities = cities
        self.api_key = api_key or None
        self.ttl = ttl
        self._http_get = http_get
        self._now = now
        self.logger = logger or logging.getLogger(__name__)
        self.latest: dict[str, Optional[dict]] = {}
        self._fetched_at: Optional[datetime] = None
        self._warned_no_key = False

    def fetch(self, force: bool = False) -> dict[str, Optional[dict]]:
        if not self.api_key:
            if not self._warned_no_key:
                self.logger.warning("OPENWEATHER_API_KEY not set: weather disabled")
                self._warned_no_key = True
            return self.latest
        now = self._now()
        if not force and self._fetched_at and (now - self._fetched_at) < self.ttl:
            return self.latest

        result: dict[str, Optional[dict]] = {}
        for key, city in self.cities.items():
            try:
                response = self._http_get(OPENWEATHER_URL, params={
                    "lat": city["lat"], "lon": city["lon"], "appid": self.api_key,
                    "units": "metric", "lang": city.get("language", "en"),
                }, timeout=10)
                response.raise_for_status()
                result[key] = parse_openweather(response.json())
            except Exception as e:
                self.logger.error("Weather error for %s: %s", key, e)
                result[key] = None
        self.latest = result
        self._fetched_at = now
        return result
