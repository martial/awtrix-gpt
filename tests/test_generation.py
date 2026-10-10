import io
import json
import unittest
from datetime import datetime

from awtrix_gpt.generation import (CONTENT_SCHEMA, LLM_KEYS, PHOTO_POEM_SCHEMA, build_prompt, first_line,
                                   load_prompt_template, love_note_prompt, parse_llm_response,
                                   parse_photo_poem)
from awtrix_gpt.llm import create_llm_client, strip_code_fences
from awtrix_gpt.llm.ollama import OllamaClient

NOW = datetime(2026, 10, 10, 14, 5)


class SchemaTests(unittest.TestCase):
    def test_schema_asks_only_for_creative_keys(self):
        self.assertEqual(set(CONTENT_SCHEMA["properties"]), set(LLM_KEYS))
        self.assertEqual(set(CONTENT_SCHEMA["required"]), set(LLM_KEYS))
        self.assertNotIn("news", CONTENT_SCHEMA["properties"])
        self.assertNotIn("weather", CONTENT_SCHEMA["properties"])

    def test_schema_is_an_object_with_min_items(self):
        self.assertEqual(CONTENT_SCHEMA["type"], "object")
        self.assertEqual(CONTENT_SCHEMA["properties"]["messages"]["minItems"], 8)


class ParseLLMResponseTests(unittest.TestCase):
    def test_happy_path_with_code_fences(self):
        raw = '```json\n{"messages": ["a", "b"], "suggested_activities": ["c"], "poems": ["d"]}\n```'
        self.assertEqual(parse_llm_response(raw),
                         {"messages": ["a", "b"], "suggested_activities": ["c"], "poems": ["d"]})

    def test_news_and_weather_from_the_model_are_dropped(self):
        raw = json.dumps({"messages": ["m"], "news": ["Le prix du lait a augmente de 15%"],
                          "weather": ["Il pleut a Marseille"], "suggested_activities": [], "poems": []})
        parsed = parse_llm_response(raw)
        self.assertEqual(set(parsed), set(LLM_KEYS))
        self.assertNotIn("Il pleut a Marseille", json.dumps(parsed))

    def test_key_aliases(self):
        raw = json.dumps({"message": ["m"], "activities": ["a"], "poem": ["p"]})
        self.assertEqual(parse_llm_response(raw), {"messages": ["m"], "suggested_activities": ["a"], "poems": ["p"]})

    def test_cleans_lines(self):
        raw = json.dumps({"messages": ["  deux\nlignes ", "", 42, None, "DEUX LIGNES", "ok"],
                          "suggested_activities": "not a list", "poems": []})
        self.assertEqual(parse_llm_response(raw)["messages"], ["deux lignes", "ok"])
        self.assertEqual(parse_llm_response(raw)["suggested_activities"], [])

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_llm_response("{not json")
        with self.assertRaises(ValueError):
            parse_llm_response("[]")
        with self.assertRaises(ValueError):
            parse_llm_response("")

    def test_empty_object_gives_empty_lists(self):
        self.assertEqual(parse_llm_response("{}"), {k: [] for k in LLM_KEYS})


class BuildPromptTests(unittest.TestCase):
    def test_fills_timestamp_and_city_weather(self):
        out = build_prompt("At {timestamp}: M={marseille_weather} A={amantea_weather} {{json}}", NOW,
                           {"MARSEILLE": "18C", "AMANTEA": "24C"})
        self.assertEqual(out, "At Saturday 10 October 2026 14:05: M=18C A=24C {json}")

    def test_unknown_placeholders_are_left_alone(self):
        out = build_prompt("x {french_news} y {timestamp}", NOW, {})
        self.assertEqual(out, "x {french_news} y Saturday 10 October 2026 14:05")

    def test_broken_format_syntax_falls_back_to_substitution(self):
        out = build_prompt('{"result": "poem"} at {timestamp}', NOW, {})
        self.assertEqual(out, '{"result": "poem"} at Saturday 10 October 2026 14:05')

    def test_real_template_no_longer_asks_for_news_or_weather_keys(self):
        prompt = build_prompt(load_prompt_template(), NOW, {"MARSEILLE": "18C clear", "AMANTEA": "24C"})
        self.assertNotIn("{timestamp}", prompt)
        self.assertNotIn("{marseille_weather}", prompt)
        self.assertNotIn("{french_news}", prompt)
        self.assertIn("18C clear", prompt)
        self.assertNotIn("'news'", prompt)
        self.assertNotIn("'weather'", prompt)
        self.assertNotIn('"news"', prompt)
        self.assertIn("'messages'", prompt)
        self.assertIn("'poems'", prompt)


class SmallGenerationsTests(unittest.TestCase):
    def test_first_line(self):
        self.assertEqual(first_line('\n "Ti amo, Marseille" \nsecond'), "Ti amo, Marseille")
        self.assertEqual(first_line("x" * 100, 80), "x" * 80)
        self.assertEqual(first_line(""), "")

    def test_love_note_prompt_hint(self):
        self.assertTrue(love_note_prompt("en italien").endswith(" en italien"))

    def test_parse_photo_poem(self):
        self.assertEqual(parse_photo_poem('```json {"result": "p", "description": "d"} ```'),
                         {"result": "p", "description": "d"})
        self.assertEqual(parse_photo_poem('{"result": null}'), {"result": "", "description": ""})
        with self.assertRaises(ValueError):
            parse_photo_poem("nope")
        self.assertEqual(set(PHOTO_POEM_SCHEMA["properties"]), {"result", "description", "timestamp"})

    def test_strip_code_fences(self):
        self.assertEqual(strip_code_fences("```json\n{}\n```"), "{}")


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OllamaClientTests(unittest.TestCase):
    def _client(self, model, **kw):
        self.requests = []

        def urlopen(request, timeout):
            self.requests.append((request, timeout))
            return _FakeHTTPResponse(json.dumps({"response": "```json\n{\"messages\": [\"ok\"]}\n```"}).encode())

        return OllamaClient("http://mac:11434/", model, urlopen=urlopen, **kw)

    def test_payload_uses_schema_object_not_json_mode(self):
        client = self._client("gemma3:4b", num_ctx=8192, keep_alive="30m", temperature=0.8)
        payload = client.build_payload("hello", schema=CONTENT_SCHEMA)
        self.assertIs(payload["format"], CONTENT_SCHEMA)
        self.assertIsInstance(payload["format"], dict)
        self.assertNotEqual(payload["format"], "json")
        self.assertEqual(payload["options"], {"num_ctx": 8192, "temperature": 0.8})
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertFalse(payload["stream"])
        self.assertNotIn("think", payload)          # gemma3 + schema + think=False -> {} instantly
        self.assertNotIn("images", payload)

    def test_think_false_only_for_reasoning_models(self):
        self.assertIs(self._client("qwen3:8b").build_payload("p", schema=CONTENT_SCHEMA)["think"], False)
        self.assertIs(self._client("lfm2").build_payload("p")["think"], False)
        self.assertNotIn("think", self._client("llama3.2").build_payload("p"))

    def test_generate_posts_and_strips_fences(self):
        client = self._client("gemma3:4b")
        text = client.generate("hello", schema=CONTENT_SCHEMA, images=["aGk="], timeout=42)
        self.assertEqual(text, '{"messages": ["ok"]}')
        request, timeout = self.requests[0]
        self.assertEqual(request.full_url, "http://mac:11434/api/generate")
        self.assertEqual(timeout, 42)
        body = json.loads(request.data.decode())
        self.assertEqual(body["images"], ["aGk="])
        self.assertEqual(body["format"]["required"], list(LLM_KEYS))

    def test_from_config_reads_the_documented_keys(self):
        client = OllamaClient.from_config({"ollama_host": "http://h:1", "ollama_model": "gemma3:4b",
                                           "ollama_num_ctx": 4096, "ollama_keep_alive": "5m",
                                           "ollama_temperature": 0.5})
        self.assertEqual((client.host, client.model, client.num_ctx, client.keep_alive, client.temperature),
                         ("http://h:1", "gemma3:4b", 4096, "5m", 0.5))

    def test_factory(self):
        self.assertIsInstance(create_llm_client({"ai_provider": "ollama"}), OllamaClient)
        with self.assertRaises(ValueError):
            create_llm_client({"ai_provider": "openai"})


if __name__ == "__main__":
    unittest.main()


class AccentFoldingTests(unittest.TestCase):
    """The matrix has no accented glyphs and the model ignores the prompt rule."""

    def test_llm_lines_are_accent_folded(self):
        raw = '{"messages": ["Un caf\\u00e9 pour Betty, des p\\u00e2tes ce soir"]}'
        self.assertEqual(parse_llm_response(raw)["messages"],
                         ["Un cafe pour Betty, des pates ce soir"])

    def test_folding_merges_duplicates_that_differed_only_by_accent(self):
        raw = '{"messages": ["Un caf\\u00e9", "Un cafe"]}'
        self.assertEqual(parse_llm_response(raw)["messages"], ["Un cafe"])
