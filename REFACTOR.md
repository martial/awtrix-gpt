# Refactor notes

## Why

The LLM (gemma3:4b) was asked for five categories. Two of them are factual and
it fabricated them every cycle: invented French headlines even though real RSS
headlines were in the prompt, and contradictory weather ("il pleut" / "le
soleil brille" for the same city). Prompt instructions did not fix it. This
refactor removes the problem instead of arguing with the model:

- **news** is built in code from the real NewsAPI/RSS headlines
  (`awtrix_gpt/news.py`). A news line on the clock is always a real title,
  prefixed with its source and trimmed to the panel width.
- **weather** is built in code from the real OpenWeather numbers
  (`awtrix_gpt/weather.py`), in the city's language (fr / it). Every line
  derives from the same numbers, so they cannot contradict each other.
- **messages, suggested_activities, poems** stay with the LLM. The prompt still
  receives the real weather as *context* (so activities fit the day) but is
  told not to produce weather or news. The JSON schema sent to Ollama has
  exactly those three keys; anything the model emits under `news` or `weather`
  is dropped at parse time (`generation.parse_llm_response`).

Secondary goal: `flask_server.py` (845 lines) and the `AwtrixManager`
god-class (580 lines mixing HTTP, weather, news, prompt, LLM, parsing,
scheduling and display) are split into small modules with injected
dependencies, so the pure logic is unit-testable without a clock, a network
or Ollama.

## New layout

```
flask_server.py              entry point (33 lines): logging, .env, create_app().run()
config_loader.py             unchanged
prompt_template.txt          UPDATED: no news/weather asks, 3 output keys (see below)
pytest.ini                   new: points pytest at tests/ (keeps test_cam.py out)
REFACTOR.md                  this file

awtrix_gpt/                  new package: all application code
  paths.py                   project-relative paths (prompt template, templates/, photos/)
  text.py                    ascii_fold, truncate_line, Highlighter (word colouring)
  clock.py                   AwtrixClient: POST /api/notify (show, push_text)
  weather.py                 WeatherService (OpenWeather) + build_weather_lines() [pure]
  sea.py                     SeaService (Open-Meteo Marine) + sea_widget_line() [pure]
  news.py                    NewsService (NewsAPI -> RSS) + build_news_lines() [pure]
  llm/__init__.py            LLMClient protocol, create_llm_client(config)
  llm/ollama.py              OllamaClient: schema-object `format`, keep_alive, num_ctx, think guard
  llm/gemini.py              GeminiClient (google-genai imported lazily)
  generation.py              CONTENT_SCHEMA, build_prompt, parse_llm_response, fallbacks,
                             love-note and photo-poem prompts/schemas/parsers
  scheduler.py               UpdateScheduler: active hours + refresh interval
  content.py                 ContentItem / Content model
  manager.py                 AwtrixManager: orchestrates refresh + display cycle (DI)
  runner.py                  DisplayRunner thread; `python -m awtrix_gpt.runner` = headless mode
  printing.py                wrap_and_reverse_text, format_french_timestamp, add_text_to_image
  web/__init__.py            create_app(): Flask factory, registers blueprints
  web/services.py            per-app container (runner, camera, printer) + ok()/error()
  web/auth.py                require_api_key
  web/routes_config.py       /, /config, /api/config/*
  web/routes_display.py      /api/status, /api/send, /api/display_now, /api/love_note,
                             /api/local_info, /api/events, /api/parasol, /api/bins
  web/routes_camera.py       /api/config/camera, /api/camera/*, /photos/<file>
  web/routes_printer.py      /api/printer/*, /api/generate_poem_with_photo

managers/                    kept for code that was already well separated
  awtrix_scenes.py           unchanged except one bug fix (see below)
  local_info_manager.py      unchanged
  camera_manager.py          cv2 import guarded; raises RuntimeError at init if missing
  printer_manager.py         thermalprinter import guarded; same
  display_manager.py         REMOVED (replaced by awtrix_gpt/manager.py)

tests/                       130+ unittest tests, no network/hardware needed
```

All routes, their methods and their JSON shapes are unchanged (the config page
reads `/api/status` fields `running`, `host`, `poems_count`, `weather_count`,
`messages_count`, `queue_remaining`, `last_update`; all still present, plus
`news_count`, `activities_count`, `llm`).

## Ollama request (unchanged guarantees)

- `format` is a JSON **schema object** (`generation.CONTENT_SCHEMA`), never
  `"json"`. `tests/test_generation.py` asserts it.
- `think: false` is only sent to models matching `qwen3|lfm`.
- `keep_alive`, `options.num_ctx`, `options.temperature` read from
  `ollama_keep_alive`, `ollama_num_ctx`, `ollama_temperature`.
- The photo-poem endpoint now also uses a schema object (`PHOTO_POEM_SCHEMA`)
  instead of `format: "json"`, since JSON mode returns `{}` with gemma3.

## Config

Every existing `config.yaml` key keeps working. New **optional** keys (defaults
in code, nothing to add):

```yaml
display:
  max_line_chars: 70        # width budget for news/weather lines (default 70)
news:
  max_items: 6              # headlines per refresh (default 6)
  with_source: true         # prefix "Le Monde: ..." (default true)
  rss_feeds:                # {name: url} or [url, ...]; default Le Monde / Le Figaro / L'Express
    Le Monde: https://www.lemonde.fr/rss/une.xml
gemini_model: gemini-3.1-flash-lite-preview   # only used when ai_provider: gemini
```

Environment (`.env`) is unchanged: `OPENWEATHER_API_KEY`, `NEWS_API_KEY`,
`GEMINI_API_KEY`, `API_KEY`, `AWTRIX_HOST`, `AWTRIX_DEBUG`, `PORT`, `FLASK_DEBUG`.

## Behaviour changes worth knowing

- News: all three RSS feeds are read (5 per feed, round-robin by source)
  instead of stopping at the first feed with entries. Feeds are fetched with
  `requests` (10 s timeout, browser-ish User-Agent) and parsed by feedparser;
  if that fails for a feed it falls back to `feedparser.parse(url)` as before.
  Watch the log line `News: N headlines from [...]` after deploy.
- A content refresh resets the display queue so the fresh batch starts
  immediately (previously the old shuffled queue drained first, ~15 min).
- `last_update` is stamped even when the refresh fails, so a dead Ollama is
  retried on the normal interval, not every 5 s.
- When the LLM fails, the previous creative lines are kept (static fallbacks
  only on the very first failure); news/weather are unaffected.
- Weather fetch within the 10-min rate limit returns the cached data instead of
  `{}` (the old behaviour fed "data unavailable" to the prompt on re-init).
- `/api/send` no longer blocks the HTTP request for `duration` seconds; it
  pushes a notification like `/api/display_now`.
- Missing camera/printer/opencv no longer prevents the server from starting;
  their routes return 503. `/api/camera/settings` returns 501 (the methods it
  called never existed on `CameraManager`).
- Bug fixes: `awtrix_scenes.refresh_scenes` read `wind_deg` but the weather
  dict key is `wind_direction` (the flag always blew west); Open-Meteo wave
  series is now requested in `Europe/Paris` so the "current hour" index is
  right; `DisplayRunner` restart could leave the old display thread running
  (shared stop event cleared by the new start).

## Deploying

1. Copy the whole tree. New: `awtrix_gpt/` (package), `tests/`, `pytest.ini`,
   `REFACTOR.md`. Removed: `managers/display_manager.py` (delete it on the Pi
   so nothing stale lingers). Modified: `flask_server.py`,
   `managers/camera_manager.py`, `managers/printer_manager.py`,
   `managers/awtrix_scenes.py` (1 line), `prompt_template.txt`.
2. **`prompt_template.txt` is gitignored** so it will not arrive via git: copy
   it by hand (or paste it through the config page). The LLM must not be asked
   for `news`/`weather` any more; the schema only allows the three keys, but an
   outdated template wastes tokens asking for them.
3. No new dependencies; `requirements.txt` is untouched. Nothing to change in
   the systemd unit (`venv/bin/python flask_server.py` from the project root).
4. Verify on the Pi:
   ```
   venv/bin/python -m py_compile flask_server.py awtrix_gpt/*.py awtrix_gpt/*/*.py managers/*.py
   venv/bin/python -c "import flask_server"
   venv/bin/python -m unittest discover -s tests -t .
   ```
   then restart the service and check the journal for
   `Content refreshed: {...}` with non-zero `news` and `weather` counts.

## Deliberately left alone

- `managers/awtrix_scenes.py` and `managers/local_info_manager.py`: already
  single-purpose and well documented; moving them would be churn.
- The evening parasol/bin reminders are still pushed on every display cycle
  after 18:00 (as before). Throttling them once per evening is a one-liner in
  `AwtrixManager._evening_reminders` if wanted; it is a behaviour choice, not
  a refactor.
- `install.sh`, `test_cam.py`, `templates/config.html`, `config.yaml`: untouched.

---

## Addendum — the LLM *does* shorten the news (added after the refactor)

The first pass took news away from the LLM entirely. That was too blunt: a Le Monde
title is ~90 characters of wire-service register and the matrix shows a short
familiar line, so rewriting is genuinely useful. What had to go was the model
*producing* news, not the model *shortening* it.

`awtrix_gpt/news_rewrite.py` does the shortening and never trusts the result:

- One narrow call per headline ("shorten this title, French, no accents, N chars max"),
  not a news slot inside a large creative prompt — that framing is what made the model
  write fiction.
- `grounding_failure(source, candidate)` re-reads every rewrite against its own source
  and returns the reason it is unusable, or `None`. It rejects: too few content words
  from the source, overlap under 60 %, a **quantity** the source never had, and English
  words that drifted in. Quantities are normalised, so "deux" and "2" compare equal and
  only a genuinely *changed* number is refused.
- Any rejection — and any timeout or Ollama error — falls back to the plain truncated
  title. The worst case is therefore exactly the no-LLM behaviour.

Config (`news:` block, all optional): `rewrite` (default `true`) and `rewrite_timeout`
(default `60`). `rewrite: false` restores pure truncation.

Measured against 8 live Le Monde headlines with gemma3:4b: 8/8 accepted after the
quantity normalisation. An earlier run of the same sample caught three real faults —
an English "Denies", a drifted "Soignant, un rayon de soleil", and a changed figure —
each correctly refused and replaced by the truncated title.

Cost: one extra Ollama call per headline (a few seconds) on a 30-minute cycle.

### Stale personal content

`prompt_template.txt` still described Elisa as pregnant and Leontine as 8 months old;
she was born 22 July 2025. Pregnancy references are gone, the age is now derived from
`{timestamp}`, and the model is explicitly forbidden from asserting a developmental
milestone it cannot know.
