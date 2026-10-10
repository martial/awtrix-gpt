"""AwtrixManager: the one place that knows the order of operations.

It owns no I/O of its own: the clock client, weather/sea/news services, LLM
client and highlighter are injected (see `from_config` for the production
wiring), which is what makes the refresh and display logic testable without
a clock, a network or a GPU.
"""

import logging
import os
import random
import time
from datetime import datetime
from typing import Callable, Mapping, Optional

from awtrix_gpt.clock import AwtrixClient
from awtrix_gpt.content import Content, items_from_lines
from awtrix_gpt.generation import (CONTENT_SCHEMA, FALLBACK_LINES, LLM_KEYS, build_prompt,
                                   load_prompt_template, parse_llm_response)
from awtrix_gpt.llm import LLMClient, create_llm_client
from awtrix_gpt.news import DEFAULT_NEWS_LIMIT, NewsService, build_news_lines, rss_feeds_from_config
from awtrix_gpt.news_rewrite import build_news_lines_llm
from awtrix_gpt.scheduler import UpdateScheduler
from awtrix_gpt.sea import SeaService, sea_widget_line
from awtrix_gpt.text import DEFAULT_MAX_CHARS, Highlighter
from awtrix_gpt.weather import WeatherService, build_weather_lines, describe_weather_for_prompt
from managers import awtrix_scenes
from managers.local_info_manager import LocalInfoManager

CATEGORY_PREFIX = {
    "messages": "MSG", "weather": "WTH", "news": "NEWS",
    "suggested_activities": "ACT", "poems": "POEM", "local_info": "INFO",
}
PRIMARY_CITY = "MARSEILLE"   # the city the scenes, sea widget and local info describe
REMINDER_DURATION = 10
SEA_WIDGET_DURATION = 4


class AwtrixManager:
    """Refreshes content on schedule and walks the clock through it."""

    def __init__(self, config: Mapping, *, clock: AwtrixClient, highlighter: Highlighter,
                 weather: WeatherService, sea: SeaService, news: NewsService,
                 llm: Optional[LLMClient], prompt_template: str, scheduler: UpdateScheduler,
                 local_info: Optional[LocalInfoManager] = None, debug: Optional[bool] = None,
                 scenes=awtrix_scenes, sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], datetime] = datetime.now,
                 shuffle: Callable[[list], None] = random.shuffle, logger=None):
        self.config = config
        self.clock = clock
        self.highlighter = highlighter
        self.weather = weather
        self.sea = sea
        self.news = news
        self.llm = llm
        self.prompt_template = prompt_template
        self.scheduler = scheduler
        self.local_info = local_info
        self.scenes = scenes
        self._sleep = sleep
        self._now = now
        self._shuffle = shuffle
        self.logger = logger or logging.getLogger(__name__)

        display = config["display"]
        self.debug = bool(display.get("debug", False)) if debug is None else bool(debug)
        self.message_duration = int(display.get("message_duration", 10))
        self.cycle_delay = int(display.get("cycle_delay", 7))
        self.max_chars = int(display.get("max_line_chars", DEFAULT_MAX_CHARS))
        news_cfg = config.get("news") or {}
        self.news_limit = int(news_cfg.get("max_items", DEFAULT_NEWS_LIMIT))
        self.news_with_source = bool(news_cfg.get("with_source", True))
        # The model only ever *shortens* a real headline, and news_rewrite re-checks
        # the result against its source before it is allowed through.
        self.news_rewrite = bool(news_cfg.get("rewrite", True))
        self.news_rewrite_timeout = int(news_cfg.get("rewrite_timeout", 60))
        self.cities: Mapping[str, Mapping] = config["weather"]["cities"]

        self.content = Content()
        self.message_queue: list = []
        self.last_update: Optional[datetime] = None
        self.logger.info("AWTRIX manager ready for %s", self.host)

    @classmethod
    def from_config(cls, config: Mapping, *, host: Optional[str] = None,
                    debug: Optional[bool] = None, env: Mapping[str, str] = os.environ,
                    logger=None) -> "AwtrixManager":
        """Production wiring: real HTTP clients, API keys from the environment."""
        logger = logger or logging.getLogger(__name__)
        cities = config["weather"]["cities"]
        news_cfg = config.get("news") or {}

        llm: Optional[LLMClient] = None
        try:
            llm = create_llm_client(config, env)
        except Exception as e:
            logger.error("LLM client unavailable, creative content will use fallbacks: %s", e)

        local_info: Optional[LocalInfoManager] = None
        try:
            local_info = LocalInfoManager(logger=logger)
        except Exception as e:
            logger.error("LocalInfoManager init failed: %s", e)

        return cls(
            config,
            clock=AwtrixClient(host or config["display"]["host"], logger=logger),
            highlighter=Highlighter.from_config(config),
            weather=WeatherService(cities, env.get("OPENWEATHER_API_KEY"), logger=logger),
            sea=SeaService(logger=logger),
            news=NewsService(api_key=env.get("NEWS_API_KEY"),
                             rss_feeds=rss_feeds_from_config(news_cfg.get("rss_feeds")),
                             logger=logger),
            llm=llm,
            prompt_template=load_prompt_template(),
            scheduler=UpdateScheduler.from_config(config["display"]),
            local_info=local_info,
            debug=debug,
            logger=logger,
        )

    @property
    def host(self) -> str:
        return self.clock.host

    # ------------------------------------------------------------------
    # Content refresh
    # ------------------------------------------------------------------

    def refresh_content(self) -> Content:
        """Rebuild every category. Factual ones come from data, creative ones from the LLM.

        Always stamps `last_update`, even on failure, so a broken upstream is
        retried on the normal interval rather than every few seconds.
        """
        now = self._now()
        try:
            self.content = self._build_content(now)
        except Exception as e:
            self.logger.exception("Content refresh failed: %s", e)
            if self.content.is_empty():
                self.content = self._fallback_content()
        finally:
            self.message_queue = []          # show the fresh batch right away
            self.last_update = now
        self.logger.info("Content refreshed: %s", self.content.counts())
        return self.content

    def _build_content(self, now: datetime) -> Content:
        weather = self._guarded(self.weather.fetch, {}, "Weather fetch")
        self._guarded(self.sea.refresh, None, "Sea refresh")
        headlines = self._guarded(self.news.fetch, [], "News fetch")

        content = Content()
        content.weather = items_from_lines(
            build_weather_lines(weather, self.cities, max_chars=self.max_chars), CATEGORY_PREFIX["weather"])
        content.news = items_from_lines(self._news_lines(headlines), CATEGORY_PREFIX["news"])
        for key, lines in self._generate_llm_lines(weather, now).items():
            setattr(content, key, items_from_lines(lines, CATEGORY_PREFIX[key]))
        content.local_info = items_from_lines(self._local_info_lines(weather), CATEGORY_PREFIX["local_info"])

        self._refresh_scenes(weather)
        return content

    def _news_lines(self, headlines) -> list[str]:
        """Real headlines, shortened by the LLM when it is available and allowed.

        Never a source of news: `build_news_lines_llm` falls back to the plain
        truncated title whenever a rewrite is missing, late or not supported by
        the headline it came from.
        """
        if not self.news_rewrite or self.llm is None:
            return build_news_lines(headlines, max_chars=self.max_chars, limit=self.news_limit,
                                    with_source=self.news_with_source)
        return self._guarded(
            lambda: build_news_lines_llm(headlines, self.llm, max_chars=self.max_chars,
                                         limit=self.news_limit, with_source=self.news_with_source,
                                         timeout=self.news_rewrite_timeout),
            build_news_lines(headlines, max_chars=self.max_chars, limit=self.news_limit,
                             with_source=self.news_with_source),
            "News rewrite")

    def _generate_llm_lines(self, weather: Mapping, now: datetime) -> dict[str, list[str]]:
        """messages / suggested_activities / poems from the LLM; previous or static lines on failure."""
        if self.llm is None:
            self.logger.warning("No LLM client: using fallback lines")
            return self._previous_llm_lines_or_fallback()

        descriptions = {key: describe_weather_for_prompt(weather.get(key)) for key in self.cities}
        prompt = build_prompt(self.prompt_template, now, descriptions)
        self.logger.info("Prompt built (%d chars) for %s", len(prompt), self.llm.name)
        try:
            raw = self.llm.generate(prompt, schema=CONTENT_SCHEMA, web_search=True)
            lines = parse_llm_response(raw)
        except Exception as e:
            self.logger.error("LLM content generation failed: %s", e)
            return self._previous_llm_lines_or_fallback()

        previous = self._previous_llm_lines_or_fallback()
        return {key: lines[key] or previous[key] for key in LLM_KEYS}

    def _previous_llm_lines_or_fallback(self) -> dict[str, list[str]]:
        return {
            key: [item.text for item in getattr(self.content, key)] or list(FALLBACK_LINES[key])
            for key in LLM_KEYS
        }

    def _fallback_content(self) -> Content:
        content = Content()
        for key, lines in FALLBACK_LINES.items():
            setattr(content, key, items_from_lines(lines, CATEGORY_PREFIX[key]))
        return content

    def _local_info_lines(self, weather: Mapping) -> list[str]:
        if not self.local_info:
            return []
        try:
            return self.local_info.get_display_lines(weather=weather.get(PRIMARY_CITY) or {},
                                                     sea_wave=self.sea.wave)
        except Exception as e:
            self.logger.error("Local info refresh error: %s", e)
            return []

    def _refresh_scenes(self, weather: Mapping) -> None:
        """Re-render the ambient GIF scenes from the same forecast and push them to the clock."""
        try:
            self.scenes.refresh_scenes(self.host, weather.get(PRIMARY_CITY) or {},
                                       sea={"height": self.sea.wave_height, "temp": self.sea.temperature})
        except Exception as e:
            self.logger.error("Scenes refresh error: %s", e)

    def _guarded(self, fn: Callable, default, label: str):
        try:
            result = fn()
            return default if result is None else result
        except Exception as e:
            self.logger.error("%s failed: %s", label, e)
            return default

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def show_text(self, text: str, duration: Optional[int] = None) -> None:
        """Show one coloured line and wait for it: the display loop paces itself this way."""
        duration = duration or self.message_duration
        try:
            self.clock.show(self.highlighter.fragments(text), duration)
            self._sleep(duration)
        except Exception as e:
            self.logger.error("Display error: %s", e)

    def push_text(self, text: str, *, rainbow: bool = False, color: Optional[str] = None,
                  duration: Optional[int] = None, hold: bool = False) -> None:
        """Non-blocking overlay notification (Telegram bridge, love notes)."""
        self.clock.push_text(text, duration=duration or self.message_duration, rainbow=rainbow,
                             color=color, hold=hold, highlighter=self.highlighter)

    def display_cycle(self) -> None:
        """Show the next queued line (reshuffling when the queue is empty), then the sea widget."""
        self._evening_reminders()

        if self.content.is_empty():
            self.logger.warning("No content available for display - clock keeps its own scene loop")
            return

        if not self.message_queue:
            self.message_queue = self.content.all_items()
            self._shuffle(self.message_queue)

        item = self.message_queue.pop(0)
        self.logger.debug("Displaying (%d remaining): %s", len(self.message_queue), item.text)
        self.show_text(item.text)
        self._sleep(self.cycle_delay)
        self._sea_widget()

    def _evening_reminders(self) -> None:
        """Parasol alert and bin reminder, red/high-priority, evenings only."""
        if not self.local_info or self._now().hour < 18:
            return
        try:
            warning = self.local_info.get_parasol_warning()
            if warning.get("alert"):
                self.push_text(f"Rentre les parasols! {warning['detail']}", color="#FF0000",
                               duration=REMINDER_DURATION)
                self._sleep(REMINDER_DURATION)
            reminder = self.local_info.get_bin_reminder()
            if reminder:
                text, color = reminder
                self.push_text(text, color=color, duration=REMINDER_DURATION)
                self._sleep(REMINDER_DURATION)
        except Exception as e:
            self.logger.error("Parasol/bin reminder error: %s", e)

    def _sea_widget(self) -> None:
        try:
            self.sea.refresh()
            marseille = self.weather.latest.get(PRIMARY_CITY)
            if marseille and marseille.get("temp") is not None:
                self.show_text(sea_widget_line(marseille["temp"], self.sea.temperature, self.sea.wave_height),
                               duration=SEA_WIDGET_DURATION)
        except Exception as e:
            self.logger.error("Sea widget error: %s", e)

    # ------------------------------------------------------------------
    # Loop step + status
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """One iteration of the main loop: refresh if due, then one display step."""
        if self.scheduler.is_due(self.last_update, self._now()):
            self.refresh_content()
        self.display_cycle()

    def status(self) -> dict:
        counts = self.content.counts()
        return {
            "host": self.host,
            "debug": self.debug,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "llm": self.llm.name if self.llm else None,
            "messages_count": counts["messages"],
            "weather_count": counts["weather"],
            "news_count": counts["news"],
            "activities_count": counts["suggested_activities"],
            "poems_count": counts["poems"],
            "info_count": counts["local_info"],
            "queue_remaining": len(self.message_queue),
        }
