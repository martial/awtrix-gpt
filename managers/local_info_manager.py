"""
Local info & recommendations for the Marseille <-> Cassis area.

All sources are keyless and free:
  - Open-Meteo Air Quality  -> AQI, UV, pollen
  - Open-Meteo Forecast     -> sunrise / sunset / golden hour / UV max
  - Open-Meteo Marine       -> tides (sea level), next high/low for Cassis
  - OpenAgenda (via Opendatasoft public API) -> real upcoming public events

Plus a small curated list of real Marseille/Cassis spots, surfaced as
"what to do now" recommendations filtered by live conditions.
"""

import logging
from datetime import datetime, timedelta

import requests


# Real, hand-picked spots around Marseille & Cassis, tagged by the conditions
# in which they shine. Used by get_recommendation() to suggest something real.
RECOS = [
    {"name": "Calanque de Sormiou", "tags": {"sea_calm", "sunny", "hot", "swim"}},
    {"name": "Calanque d'En-Vau (Cassis)", "tags": {"sea_calm", "sunny", "hike", "swim"}},
    {"name": "Plage de la Grande Mer, Cassis", "tags": {"sunny", "swim", "family"}},
    {"name": "Cap Canaille en voiture", "tags": {"sunny", "evening", "romantic", "view"}},
    {"name": "Vallon des Auffes au coucher", "tags": {"evening", "romantic", "view"}},
    {"name": "Apéro au Vieux-Port", "tags": {"evening", "romantic"}},
    {"name": "Notre-Dame de la Garde", "tags": {"sunny", "view", "family"}},
    {"name": "Port de Cassis & glace", "tags": {"evening", "family", "hot"}},
    {"name": "Sentier du Petit Nice", "tags": {"sunny", "hike", "view"}},
    {"name": "MuCEM (intérieur)", "tags": {"rain", "family", "culture"}},
    {"name": "Musée Cosquer (intérieur)", "tags": {"rain", "family", "culture"}},
    {"name": "Marché de Noailles", "tags": {"rain", "family", "culture"}},
    {"name": "Cours Julien, bars & street art", "tags": {"evening", "rain", "culture"}},
]


class LocalInfoManager:
    MARSEILLE = (43.2965, 5.3698)
    CASSIS = (43.2150, 5.5380)

    # Evening-before bin reminders, keyed by weekday (Mon=0 .. Sun=6).
    # (text, hex color). Collections: ménagères Tue & Thu, carton Wed.
    BIN_SCHEDULE = {
        0: ("Sors les ordures menageres (demain mardi)", "#33CC33"),
        1: ("Sors le CARTON (demain mercredi)", "#D2691E"),
        2: ("Sors les ordures menageres (demain jeudi)", "#33CC33"),
    }

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._cache = {}
        self._cache_at = {}
        self.ttl = timedelta(minutes=30)

    # --- caching helper -------------------------------------------------
    def _cached(self, key, fn):
        now = datetime.now()
        if key in self._cache and (now - self._cache_at.get(key, datetime.min)) < self.ttl:
            return self._cache[key]
        try:
            val = fn()
            self._cache[key] = val
            self._cache_at[key] = now
            return val
        except Exception as e:
            self.logger.error(f"LocalInfo[{key}] error: {e}")
            return self._cache.get(key)  # stale on failure, else None

    # --- sources --------------------------------------------------------
    def get_air_quality(self):
        def _fetch():
            lat, lon = self.MARSEILLE
            url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
                   f"?latitude={lat}&longitude={lon}"
                   "&current=european_aqi,pm2_5,uv_index,grass_pollen,olive_pollen,ragweed_pollen"
                   "&timezone=Europe%2FParis")
            c = requests.get(url, timeout=8).json().get("current", {})
            return {
                "aqi": c.get("european_aqi"),
                "uv": c.get("uv_index"),
                "pm2_5": c.get("pm2_5"),
                "pollen": max(c.get("grass_pollen") or 0, c.get("olive_pollen") or 0,
                              c.get("ragweed_pollen") or 0),
            }
        return self._cached("air", _fetch)

    def get_sun_times(self):
        def _fetch():
            lat, lon = self.MARSEILLE
            url = ("https://api.open-meteo.com/v1/forecast"
                   f"?latitude={lat}&longitude={lon}"
                   "&daily=sunrise,sunset,uv_index_max&timezone=Europe%2FParis&forecast_days=1")
            d = requests.get(url, timeout=8).json().get("daily", {})
            sunrise = d.get("sunrise", [None])[0]
            sunset = d.get("sunset", [None])[0]
            golden = None
            if sunset:
                golden = (datetime.fromisoformat(sunset) - timedelta(minutes=60)).strftime("%H:%M")
            return {
                "sunrise": sunrise[11:16] if sunrise else None,
                "sunset": sunset[11:16] if sunset else None,
                "golden_hour": golden,
                "uv_max": (d.get("uv_index_max") or [None])[0],
            }
        return self._cached("sun", _fetch)

    def get_tides(self):
        """Next high & low tide for Cassis from the hourly sea-level series."""
        def _fetch():
            lat, lon = self.CASSIS
            url = ("https://marine-api.open-meteo.com/v1/marine"
                   f"?latitude={lat}&longitude={lon}"
                   "&hourly=sea_level_height_msl&timezone=Europe%2FParis&forecast_days=2")
            h = requests.get(url, timeout=8).json().get("hourly", {})
            times = h.get("time", [])
            levels = h.get("sea_level_height_msl", [])
            now = datetime.now()
            future = [(t, l) for t, l in zip(times, levels)
                      if l is not None and datetime.fromisoformat(t) >= now]
            high = low = None
            # turning points: compare neighbours
            for i in range(1, len(future) - 1):
                t, l = future[i]
                prev, nxt = future[i - 1][1], future[i + 1][1]
                if high is None and l >= prev and l >= nxt:
                    high = t[11:16]
                if low is None and l <= prev and l <= nxt:
                    low = t[11:16]
                if high and low:
                    break
            return {"high": high, "low": low}
        return self._cached("tides", _fetch)

    def get_events(self, limit=6):
        """Real upcoming public events for Marseille & Cassis (OpenAgenda)."""
        def _fetch():
            base = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
                    "evenements-publics-openagenda/records")
            where = ('(location_city like "Marseille" or location_city like "Cassis") '
                     'and firstdate_begin>=now()')
            params = {
                "where": where,
                "order_by": "firstdate_begin asc",
                "limit": limit,
                "select": "title_fr,firstdate_begin,location_name,location_city",
            }
            rows = requests.get(base, params=params, timeout=10).json().get("results", [])
            events = []
            for r in rows:
                title = (r.get("title_fr") or "").strip()
                begin = (r.get("firstdate_begin") or "")[:10]
                venue = (r.get("location_name") or r.get("location_city") or "").strip()
                if title:
                    events.append({"title": title, "date": begin, "venue": venue,
                                   "city": r.get("location_city")})
            return events
        return self._cached("events", _fetch) or []

    def get_parasol_warning(self, gust_threshold_ms=11.0, rain_prob_threshold=50):
        """Evening alert: should the parasols be put away tonight?

        Looks at the forecast from now through the coming night (~next 9h) for
        Marseille and flags strong wind gusts and/or likely rain. Returns
        {'alert': bool, 'reason': str, 'detail': str}.
        """
        def _fetch():
            lat, lon = self.MARSEILLE
            url = ("https://api.open-meteo.com/v1/forecast"
                   f"?latitude={lat}&longitude={lon}"
                   "&hourly=precipitation_probability,wind_gusts_10m"
                   "&wind_speed_unit=ms&timezone=Europe%2FParis&forecast_days=2")
            h = requests.get(url, timeout=8).json().get("hourly", {})
            times = h.get("time", [])
            gusts = h.get("wind_gusts_10m", [])
            rain = h.get("precipitation_probability", [])
            now = datetime.now()
            horizon = now + timedelta(hours=9)
            max_gust = 0.0
            max_rain = 0
            for i, t in enumerate(times):
                dt = datetime.fromisoformat(t)
                if now <= dt <= horizon:
                    if i < len(gusts) and gusts[i] is not None:
                        max_gust = max(max_gust, float(gusts[i]))
                    if i < len(rain) and rain[i] is not None:
                        max_rain = max(max_rain, int(rain[i]))
            return {"max_gust": round(max_gust, 1), "max_rain": max_rain}

        data = self._cached("parasol", _fetch) or {}
        max_gust = data.get("max_gust", 0)
        max_rain = data.get("max_rain", 0)

        windy = max_gust >= gust_threshold_ms
        rainy = max_rain >= rain_prob_threshold
        if windy and rainy:
            reason, detail = "vent & pluie", f"rafales {round(max_gust)}m/s, pluie {max_rain}%"
        elif windy:
            reason, detail = "vent", f"rafales {round(max_gust)}m/s ce soir"
        elif rainy:
            reason, detail = "pluie", f"pluie {max_rain}% ce soir"
        else:
            reason, detail = "", ""
        return {"alert": windy or rainy, "reason": reason, "detail": detail}

    def get_bin_reminder(self):
        """Today's trash reminder as (text, color), or None. Caller gates on evening."""
        return self.BIN_SCHEDULE.get(datetime.now().weekday())

    # --- recommendation engine -----------------------------------------
    def get_recommendation(self, weather=None, sea_wave=None):
        """Pick a real spot matching current conditions (deterministic by hour)."""
        cond = set()
        hour = datetime.now().hour
        if hour >= 18 or hour < 7:
            cond.add("evening")
        desc = (weather or {}).get("description", "").lower()
        temp = (weather or {}).get("temp")
        if any(w in desc for w in ("pluie", "rain", "pioggia", "orage")):
            cond.add("rain")
        else:
            cond.add("sunny")
        if isinstance(temp, (int, float)) and temp >= 26:
            cond.add("hot")
        try:
            if sea_wave and float(sea_wave.get("height", 1)) < 0.6:
                cond.add("sea_calm")
        except Exception:
            pass

        scored = [(len(cond & r["tags"]), r["name"]) for r in RECOS]
        scored = [s for s in scored if s[0] > 0] or [(0, r["name"]) for r in RECOS]
        best = max(s[0] for s in scored)
        top = [name for sc, name in scored if sc == best]
        # rotate deterministically through equally-good picks by hour
        return top[hour % len(top)]

    # --- matrix-friendly lines -----------------------------------------
    def get_display_lines(self, weather=None, sea_wave=None):
        """Short strings (~<42 chars) to rotate on the LED matrix."""
        lines = []
        air = self.get_air_quality()
        if air and air.get("aqi") is not None:
            uv = air.get("uv")
            uv_str = f" | UV {round(uv)}" if uv is not None else ""
            qual = "bon" if air["aqi"] <= 40 else ("moyen" if air["aqi"] <= 60 else "mediocre")
            lines.append(f"Air Marseille: {qual} ({round(air['aqi'])}){uv_str}")
            if (air.get("pollen") or 0) > 20:
                lines.append(f"Pollen eleve: {round(air['pollen'])} grains/m3")

        sun = self.get_sun_times()
        if sun and sun.get("sunset"):
            lines.append(f"Coucher {sun['sunset']} | heure doree {sun.get('golden_hour','')}")

        tides = self.get_tides()
        if tides and (tides.get("high") or tides.get("low")):
            parts = []
            if tides.get("high"):
                parts.append(f"haute {tides['high']}")
            if tides.get("low"):
                parts.append(f"basse {tides['low']}")
            lines.append("Cassis maree: " + " | ".join(parts))

        for ev in self.get_events(limit=3):
            when = ev["date"]
            lines.append(f"{when[5:]}: {ev['title'][:34]} @ {ev['venue'][:18]}")

        reco = self.get_recommendation(weather, sea_wave)
        if reco:
            lines.append(f"A faire: {reco}")

        return lines

    def get_full(self, weather=None, sea_wave=None):
        return {
            "air_quality": self.get_air_quality(),
            "sun": self.get_sun_times(),
            "tides": self.get_tides(),
            "events": self.get_events(),
            "recommendation": self.get_recommendation(weather, sea_wave),
        }
