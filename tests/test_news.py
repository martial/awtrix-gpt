import unittest
from datetime import datetime, timedelta

from awtrix_gpt.news import (DEFAULT_RSS_FEEDS, Headline, NewsService, build_news_lines, clean_title,
                             headlines_from_feed, headlines_from_newsapi, interleave_by_source,
                             rss_feeds_from_config, source_name_from_url)


class CleanTitleTests(unittest.TestCase):
    def test_unescapes_entities_and_collapses_whitespace(self):
        self.assertEqual(clean_title("Macron &amp; Meloni :\n  sommet  "), "Macron & Meloni : sommet")

    def test_strips_trailing_publisher(self):
        self.assertEqual(clean_title("Le prix du gaz baisse - Le Monde"), "Le prix du gaz baisse")
        self.assertEqual(clean_title("Greve des pilotes | Le Figaro"), "Greve des pilotes")
        self.assertEqual(clean_title("Titre – BFMTV"), "Titre")

    def test_strips_the_feeds_own_source_name(self):
        self.assertEqual(clean_title("Titre - La Marseillaise", source="La Marseillaise"), "Titre")

    def test_keeps_hyphens_inside_a_title(self):
        title = "Jean-Luc Melenchon repond au Rassemblement - national"
        self.assertEqual(clean_title(title), title)

    def test_none(self):
        self.assertEqual(clean_title(None), "")


class FeedParsingTests(unittest.TestCase):
    FEED = {"entries": [
        {"title": "Budget 2027 : le gouvernement presente son plan", "summary": "<p>Le detail &eacute;</p>"},
        {"title": "Sport"},                                            # too short -> dropped
        {"title": "Canicule : vigilance orange dans 12 departements", "description": "desc"},
    ]}

    def test_headlines_from_feed(self):
        heads = headlines_from_feed(self.FEED, source="Le Monde")
        self.assertEqual([h.title for h in heads], [
            "Budget 2027 : le gouvernement presente son plan",
            "Canicule : vigilance orange dans 12 departements",
        ])
        self.assertEqual(heads[0].summary, "Le detail é")
        self.assertEqual(heads[1].summary, "desc")
        self.assertTrue(all(h.source == "Le Monde" for h in heads))

    def test_limit(self):
        self.assertEqual(len(headlines_from_feed(self.FEED, "x", limit=1)), 1)

    def test_empty_or_malformed_feed(self):
        self.assertEqual(headlines_from_feed({}, "x"), [])
        self.assertEqual(headlines_from_feed({"entries": None}, "x"), [])

    def test_headlines_from_newsapi(self):
        data = {"articles": [
            {"title": "Reforme des retraites adoptee - Le Monde", "description": "d1", "source": {"name": "Le Monde"}},
            {"title": "[Removed]", "source": {"name": "x"}},
            {"title": "Tempete sur la Bretagne ce week-end", "description": None, "source": {}},
        ]}
        heads = headlines_from_newsapi(data)
        self.assertEqual([h.title for h in heads], ["Reforme des retraites adoptee",
                                                    "Tempete sur la Bretagne ce week-end"])
        self.assertEqual(heads[0].source, "Le Monde")
        self.assertEqual(heads[1].summary, "")

    def test_interleave_by_source(self):
        heads = [Headline("a1", source="A"), Headline("a2", source="A"), Headline("b1", source="B")]
        self.assertEqual([h.title for h in interleave_by_source(heads)], ["a1", "b1", "a2"])


class BuildNewsLinesTests(unittest.TestCase):
    def test_lines_are_real_titles_with_source_prefix_folded_and_bounded(self):
        heads = [Headline("Élections : la gauche l'emporte à Marseille", source="Le Monde")]
        self.assertEqual(build_news_lines(heads), ["Le Monde: Elections : la gauche l'emporte a Marseille"])

    def test_width_includes_prefix(self):
        heads = [Headline("Un titre vraiment tres long qui ne tiendra jamais sur la matrice", source="Le Figaro")]
        (line,) = build_news_lines(heads, max_chars=40)
        self.assertLessEqual(len(line), 40)
        self.assertTrue(line.startswith("Le Figaro: "))
        self.assertTrue(line.endswith("..."))

    def test_without_source(self):
        self.assertEqual(build_news_lines([Headline("Un titre assez long", source="X")], with_source=False),
                         ["Un titre assez long"])

    def test_dedupes_and_limits(self):
        heads = [Headline("Le meme titre repete", source="A"), Headline("Le meme titre repete", source="B"),
                 Headline("Un deuxieme titre", source="A"), Headline("Un troisieme titre", source="A")]
        lines = build_news_lines(heads, limit=2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "A: Le meme titre repete")
        self.assertEqual(lines[1], "A: Un deuxieme titre")

    def test_drops_too_short_titles(self):
        self.assertEqual(build_news_lines([Headline("Sport", source="A")]), [])

    def test_empty_input_gives_empty_list_not_invented_news(self):
        self.assertEqual(build_news_lines([]), [])


class ConfigHelpersTests(unittest.TestCase):
    def test_source_name_from_url(self):
        self.assertEqual(source_name_from_url("https://www.lemonde.fr/rss/une.xml"), "lemonde.fr")

    def test_rss_feeds_from_config(self):
        self.assertEqual(rss_feeds_from_config(None), DEFAULT_RSS_FEEDS)
        self.assertEqual(rss_feeds_from_config({"X": "http://x/rss"}), {"X": "http://x/rss"})
        self.assertEqual(rss_feeds_from_config(["https://www.lefigaro.fr/rss/a.xml"]),
                         {"lefigaro.fr": "https://www.lefigaro.fr/rss/a.xml"})


class _Response:
    def __init__(self, payload=None, content=b"", status=200):
        self._payload = payload
        self.content = content
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class NewsServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 12, 0)
        self.calls = []

    def _clock(self):
        return self.now

    def test_rss_path_without_api_key(self):
        feeds = {"Le Monde": "http://lm/rss", "Le Figaro": "http://lf/rss"}
        parsed = {
            b"lm": {"entries": [{"title": "Premier titre du Monde"}, {"title": "Deuxieme titre du Monde"}]},
            b"lf": {"entries": [{"title": "Premier titre du Figaro"}]},
        }

        def http_get(url, **kw):
            self.calls.append(url)
            return _Response(content=b"lm" if "lm" in url else b"lf")

        svc = NewsService(rss_feeds=feeds, http_get=http_get, parse_feed=lambda c: parsed[c], now=self._clock)
        heads = svc.fetch()
        self.assertEqual([h.title for h in heads], ["Premier titre du Monde", "Premier titre du Figaro",
                                                    "Deuxieme titre du Monde"])
        self.assertNotIn("newsapi", " ".join(self.calls))

    def test_newsapi_first_then_rss_fallback_when_empty(self):
        def http_get(url, **kw):
            self.calls.append(url)
            if "newsapi" in url:
                return _Response(payload={"articles": []})
            return _Response(content=b"feed")

        feed = {"entries": [{"title": "Un vrai titre de secours"}]}
        svc = NewsService(api_key="k", rss_feeds={"S": "http://s/rss"}, http_get=http_get,
                          parse_feed=lambda c: feed, now=self._clock)
        self.assertEqual([h.title for h in svc.fetch()], ["Un vrai titre de secours"])
        self.assertTrue(self.calls[0].startswith("https://newsapi.org"))

    def test_newsapi_results_are_used_when_present(self):
        def http_get(url, **kw):
            return _Response(payload={"articles": [{"title": "Titre NewsAPI complet - Le Monde",
                                                    "source": {"name": "Le Monde"}}]})
        svc = NewsService(api_key="k", http_get=http_get, parse_feed=lambda c: {"entries": []}, now=self._clock)
        self.assertEqual([h.title for h in svc.fetch()], ["Titre NewsAPI complet"])

    def test_cache_and_force(self):
        counter = {"n": 0}

        def http_get(url, **kw):
            counter["n"] += 1
            return _Response(content=b"x")

        svc = NewsService(rss_feeds={"S": "http://s"}, http_get=http_get,
                          parse_feed=lambda c: {"entries": [{"title": "Un titre suffisamment long"}]},
                          now=self._clock, ttl=timedelta(minutes=15))
        svc.fetch(); svc.fetch()
        self.assertEqual(counter["n"], 1)
        self.now += timedelta(minutes=16)
        svc.fetch()
        self.assertEqual(counter["n"], 2)
        svc.fetch(force=True)
        self.assertEqual(counter["n"], 3)

    def test_failure_keeps_previous_headlines(self):
        state = {"fail": False}

        def http_get(url, **kw):
            if state["fail"]:
                raise ConnectionError("down")
            return _Response(content=b"x")

        def parse_feed(c):
            if state["fail"]:
                raise ConnectionError("down")
            return {"entries": [{"title": "Un titre suffisamment long"}]}

        svc = NewsService(rss_feeds={"S": "http://s"}, http_get=http_get, parse_feed=parse_feed, now=self._clock)
        first = svc.fetch()
        self.assertEqual(len(first), 1)
        state["fail"] = True
        self.assertEqual(svc.fetch(force=True), first)

    def test_direct_fetch_failure_falls_back_to_feedparser_fetching_the_url(self):
        seen = []

        def parse_feed(arg):
            seen.append(arg)
            return {"entries": [{"title": "Un titre suffisamment long"}]} if isinstance(arg, str) else {"entries": []}

        svc = NewsService(rss_feeds={"S": "http://s/rss"}, http_get=lambda *a, **k: _Response(status=403),
                          parse_feed=parse_feed, now=self._clock)
        self.assertEqual(len(svc.fetch()), 1)
        self.assertEqual(seen[-1], "http://s/rss")


if __name__ == "__main__":
    unittest.main()
