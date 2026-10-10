"""Real French headlines, fetched from NewsAPI or RSS and turned into display lines IN CODE.

The LLM is never asked for news: a 4B model reads real headlines and writes
its own invented ones anyway. Here a headline on the clock is always a real
title from a real feed, trimmed to the panel's width.

Pure functions (testable without network) come first; `NewsService` does the
fetching with injectable HTTP/feed parsers.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import Any, Callable, Iterable, Mapping, Optional, Union
from urllib.parse import urlparse

import feedparser
import requests

from awtrix_gpt.text import DEFAULT_MAX_CHARS, ascii_fold, collapse_whitespace, truncate_line

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"

DEFAULT_RSS_FEEDS: dict[str, str] = {
    "Le Monde": "https://www.lemonde.fr/rss/une.xml",
    "Le Figaro": "https://www.lefigaro.fr/rss/figaro_actualites.xml",
    "L'Express": "https://www.lexpress.fr/rss/alaune.xml",
}

# Publisher names that aggregators append to titles ("Titre - Le Monde").
KNOWN_SOURCES = (
    "Le Monde", "Le Figaro", "L'Express", "Libération", "Liberation", "BFMTV",
    "franceinfo", "France Info", "20 Minutes", "Ouest-France", "Le Parisien",
    "L'Équipe", "L'Equipe", "Les Echos", "Le Point", "L'Obs", "Marianne",
    "Mediapart", "La Provence", "Sud Ouest", "La Croix", "Le HuffPost",
)

# A "headline" shorter than this is a section label, not news.
MIN_TITLE_CHARS = 12
DEFAULT_NEWS_LIMIT = 6
USER_AGENT = "Mozilla/5.0 (compatible; awtrix-gpt/1.0; RSS reader)"

_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Headline:
    title: str
    summary: str = ""
    source: str = ""


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def _get(obj: Any, key: str, default=None):
    """Read `key` from a dict, a feedparser FeedParserDict or a plain object."""
    if hasattr(obj, "get"):
        value = obj.get(key, default)
        return default if value is None else value
    return getattr(obj, key, default)


def _strip_source_suffix(title: str, source: str = "") -> str:
    names = [source] if source else []
    names.extend(KNOWN_SOURCES)
    for name in names:
        if not name:
            continue
        pattern = re.compile(r"\s+[-|–—]\s+" + re.escape(name) + r"\s*$", re.IGNORECASE)
        stripped = pattern.sub("", title)
        if stripped != title:
            return stripped.strip()
    return title


def clean_title(title: Optional[str], source: str = "") -> str:
    """Unescape HTML entities, collapse whitespace, drop a trailing publisher name."""
    text = collapse_whitespace(html.unescape(str(title or "")))
    return _strip_source_suffix(text, source)


def clean_summary(summary: Optional[str]) -> str:
    return collapse_whitespace(html.unescape(_TAG.sub(" ", str(summary or ""))))


def source_name_from_url(url: str) -> str:
    """'https://www.lemonde.fr/rss/une.xml' -> 'lemonde.fr'."""
    host = urlparse(url).netloc or url
    return host[4:] if host.startswith("www.") else host


def rss_feeds_from_config(value: Union[None, Mapping[str, str], Iterable[str]]) -> dict[str, str]:
    """Accept `{name: url}` or `[url, ...]` from config; default to the built-in feeds."""
    if not value:
        return dict(DEFAULT_RSS_FEEDS)
    if isinstance(value, Mapping):
        return {str(name): str(url) for name, url in value.items()}
    return {source_name_from_url(str(url)): str(url) for url in value}


def headlines_from_feed(feed: Any, source: str = "", limit: int = 8) -> list[Headline]:
    """Headlines from a parsed RSS/Atom feed (feedparser result or an equivalent dict)."""
    out: list[Headline] = []
    for entry in (_get(feed, "entries") or [])[:limit]:
        title = clean_title(_get(entry, "title"), source)
        if len(title) < MIN_TITLE_CHARS:
            continue
        summary = clean_summary(_get(entry, "summary") or _get(entry, "description"))
        out.append(Headline(title=title, summary=summary, source=source))
    return out


def headlines_from_newsapi(data: Mapping, limit: int = 8) -> list[Headline]:
    """Headlines from a NewsAPI `top-headlines` JSON payload."""
    out: list[Headline] = []
    for article in (data.get("articles") or [])[:limit]:
        source = str((article.get("source") or {}).get("name") or "")
        title = clean_title(article.get("title"), source)
        if len(title) < MIN_TITLE_CHARS or title.lower() == "[removed]":
            continue
        out.append(Headline(title=title, summary=clean_summary(article.get("description")), source=source))
    return out


def interleave_by_source(headlines: Iterable[Headline]) -> list[Headline]:
    """Round-robin across sources so one feed does not monopolise the clock."""
    by_source: dict[str, list[Headline]] = {}
    for headline in headlines:
        by_source.setdefault(headline.source, []).append(headline)
    return [h for group in zip_longest(*by_source.values()) for h in group if h is not None]


def build_news_lines(headlines: Iterable[Headline], *, max_chars: int = DEFAULT_MAX_CHARS,
                     limit: int = DEFAULT_NEWS_LIMIT, with_source: bool = True) -> list[str]:
    """Turn real headlines into panel lines: '<Source>: <title trimmed to width>'.

    Deduplicates identical titles, folds accents (the matrix font has none) and
    never exceeds `max_chars` including the source prefix.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for headline in headlines:
        title = ascii_fold(clean_title(headline.title, headline.source))
        if len(title) < MIN_TITLE_CHARS:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        prefix = f"{ascii_fold(headline.source)}: " if with_source and headline.source else ""
        body = truncate_line(title, max_chars - len(prefix))
        if body:
            lines.append(prefix + body)
        if len(lines) >= limit:
            break
    return lines


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

class NewsService:
    """Fetch headlines: NewsAPI when a key is configured, otherwise RSS. Cached for `ttl`.

    `http_get` and `parse_feed` are injectable so tests never touch the network.
    On a failed refresh the previous headlines are kept.
    """

    def __init__(self, *, api_key: Optional[str] = None,
                 rss_feeds: Optional[Mapping[str, str]] = None, per_source: int = 5,
                 ttl: timedelta = timedelta(minutes=15),
                 http_get: Callable = requests.get, parse_feed: Callable = feedparser.parse,
                 now: Callable[[], datetime] = datetime.now, logger=None):
        self.api_key = api_key or None
        self.rss_feeds = dict(rss_feeds) if rss_feeds else dict(DEFAULT_RSS_FEEDS)
        self.per_source = per_source
        self.ttl = ttl
        self._http_get = http_get
        self._parse_feed = parse_feed
        self._now = now
        self.logger = logger or logging.getLogger(__name__)
        self.headlines: list[Headline] = []
        self._fetched_at: Optional[datetime] = None

    def fetch(self, force: bool = False) -> list[Headline]:
        now = self._now()
        if not force and self._fetched_at and (now - self._fetched_at) < self.ttl:
            return self.headlines
        headlines = self._from_newsapi() if self.api_key else []
        if not headlines:
            headlines = self._from_rss()
        if headlines:
            self.headlines = headlines
            self.logger.info("News: %d headlines from %s", len(headlines),
                             sorted({h.source for h in headlines}))
        else:
            self.logger.warning("News: no headlines fetched, keeping %d previous", len(self.headlines))
        self._fetched_at = now
        return self.headlines

    def _from_newsapi(self) -> list[Headline]:
        try:
            response = self._http_get(NEWSAPI_URL, params={"country": "fr", "apiKey": self.api_key,
                                                           "pageSize": 2 * self.per_source},
                                      timeout=10)
            self.logger.info("NewsAPI status: %s", getattr(response, "status_code", "?"))
            return interleave_by_source(headlines_from_newsapi(response.json(), limit=2 * self.per_source))
        except Exception as e:
            self.logger.warning("NewsAPI error: %s", e)
            return []

    def _from_rss(self) -> list[Headline]:
        headlines: list[Headline] = []
        for source, url in self.rss_feeds.items():
            try:
                headlines.extend(headlines_from_feed(self._load_feed(url), source, self.per_source))
            except Exception as e:
                self.logger.warning("RSS error for %s (%s): %s", source, url, e)
        return interleave_by_source(headlines)

    def _load_feed(self, url: str):
        """Fetch with a timeout, then parse; fall back to feedparser's own fetch."""
        try:
            response = self._http_get(url, timeout=10, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            feed = self._parse_feed(response.content)
            if _get(feed, "entries"):
                return feed
        except Exception as e:
            self.logger.debug("Direct fetch of %s failed (%s), letting feedparser fetch it", url, e)
        return self._parse_feed(url)
