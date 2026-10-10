"""awtrix-gpt: drive a 32x8 AWTRIX LED matrix with real data and a little LLM whimsy.

Layout (one responsibility per module):

    paths        project-relative paths (prompt template, templates/, photos/)
    text         pure text helpers for the matrix: accent folding, truncation, colouring
    clock        HTTP client for the AWTRIX clock itself
    weather      OpenWeather fetching + weather lines built IN CODE from real numbers
    sea          Open-Meteo Marine fetching + the sea widget line
    news         NewsAPI/RSS fetching + news lines built IN CODE from real headlines
    llm/         LLM clients (Ollama with JSON-schema structured output, Gemini)
    generation   prompt building, output schema and response parsing for the LLM
    scheduler    "is it time to refresh?" rules (active hours, interval)
    content      the content model shown on the clock
    manager      AwtrixManager: orchestrates refresh + display cycle
    runner       background thread that drives the manager
    printing     thermal-printer text/image helpers
    web/         Flask app factory and blueprints
"""
