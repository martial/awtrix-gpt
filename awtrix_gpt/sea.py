"""Sea temperature and swell off Marseille from Open-Meteo Marine (keyless)."""

import logging
from datetime import datetime, timedelta
from typing import Callable, Mapping, Optional

import requests

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
TIMEZONE = "Europe/Paris"


def current_hour_values(hourly: Mapping, hour: int, keys: tuple[str, ...]) -> Optional[dict]:
    """Pick index `hour` from each hourly series; None if any is missing."""
    out = {}
    for key in keys:
        series = hourly.get(key) or []
        if hour >= len(series) or series[hour] is None:
            return None
        out[key] = series[hour]
    return out


def sea_widget_line(air_temp, sea_temp: Optional[float], wave_height) -> str:
    """'Marseille: 18C | Eau: 17.2C | Houle: 0.4m' (estimated water temp when the API is down)."""
    air = int(air_temp)
    if sea_temp is not None:
        water = f"Eau: {sea_temp}C"
    else:
        water = f"Eau: ~{max(13, min(26, air - 2))}C"
    line = f"Marseille: {air}C | {water}"
    if wave_height is not None:
        line += f" | Houle: {round(float(wave_height), 1)}m"
    return line


class SeaService:
    """Cached sea surface temperature and wave height/direction/period."""

    def __init__(self, *, lat: float = 43.2965, lon: float = 5.3698,
                 wave_lat: float = 43.25, wave_lon: float = 5.37,
                 ttl: timedelta = timedelta(minutes=30), http_get: Callable = requests.get,
                 now: Callable[[], datetime] = datetime.now, logger=None):
        self.lat, self.lon = lat, lon
        self.wave_lat, self.wave_lon = wave_lat, wave_lon
        self.ttl = ttl
        self._http_get = http_get
        self._now = now
        self.logger = logger or logging.getLogger(__name__)
        self.temperature: Optional[float] = None
        self.wave: Optional[dict] = None
        self._fetched_at: Optional[datetime] = None

    def refresh(self, force: bool = False) -> None:
        now = self._now()
        if not force and self._fetched_at and (now - self._fetched_at) < self.ttl:
            return
        temperature = self.fetch_temperature()
        if temperature is not None:
            self.temperature = round(temperature, 1)
        wave = self.fetch_waves(now.hour)
        if wave is not None:
            self.wave = wave
        self._fetched_at = now
        self.logger.info("Sea data: temp=%sC wave=%s", self.temperature, self.wave)

    @property
    def wave_height(self) -> Optional[float]:
        return (self.wave or {}).get("height")

    def fetch_temperature(self) -> Optional[float]:
        try:
            response = self._http_get(MARINE_URL, params={
                "latitude": self.lat, "longitude": self.lon,
                "current": "sea_surface_temperature"}, timeout=5)
            return (response.json().get("current") or {}).get("sea_surface_temperature")
        except Exception as e:
            self.logger.error("Sea temperature error: %s", e)
            return None

    def fetch_waves(self, hour: int) -> Optional[dict]:
        try:
            response = self._http_get(MARINE_URL, params={
                "latitude": self.wave_lat, "longitude": self.wave_lon,
                "hourly": "wave_height,wave_direction,wave_period",
                "timezone": TIMEZONE, "forecast_days": 1}, timeout=5)
            values = current_hour_values(response.json().get("hourly") or {}, hour,
                                         ("wave_height", "wave_direction", "wave_period"))
            if values is None:
                return None
            return {"height": values["wave_height"], "direction": values["wave_direction"],
                    "period": values["wave_period"]}
        except Exception as e:
            self.logger.error("Sea wave error: %s", e)
            return None
