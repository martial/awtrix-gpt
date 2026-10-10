"""Shorten real headlines with the LLM — without letting it invent any.

A Le Monde title is ~90 characters of wire-service register; the matrix shows a
short familiar line. Rewriting is a good job for the model. *Producing* news is
not: asked for a list of headlines inside a large creative prompt, a 4B model
writes plausible fiction ("etat d'urgence sanitaire en Corse").

So the rewrite is narrow (one headline, one instruction) and, more importantly,
never trusted: `grounding_failure` re-reads the candidate against its source and
rejects anything that introduces content words or numbers the source never had.
A rejected rewrite falls back to the plain truncated title, so the worst case is
the behaviour we had before the model was involved.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Protocol

from awtrix_gpt.news import Headline, MIN_TITLE_CHARS, clean_title
from awtrix_gpt.text import DEFAULT_MAX_CHARS, ascii_fold, collapse_whitespace, truncate_line

logger = logging.getLogger(__name__)

MIN_OVERLAP = 0.6
MIN_MATCHED_WORDS = 2
SIGNIFICANT_CHARS = 4

# Short French/Italian function words carry no factual weight, so they neither
# prove grounding nor betray invention.
STOPWORDS = frozenset("""
avec dans pour sans sous sur vers chez entre apres avant depuis contre selon
cette cettes ceux celle celles leur leurs notre notre votre elle elles ils
mais donc alors aussi plus moins tres bien tout tous toute toutes meme encore
etre avoir fait faire dire dit vont sont etait etaient sera seront ont est
les des une uns que qui quoi dont lequel laquelle
della delle degli nella nelle sono stato stati come anche
""".split())

_WORD = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"\d+")

# A rewrite that turns "deux morts" into "dix morts" is the worst failure this
# display can have, and digits alone do not catch it: French headlines spell
# small counts out. Spelled numerals are therefore compared like figures.
SPELLED_NUMBERS = {
    "zero": "0", "un": "1", "une": "1", "deux": "2", "trois": "3", "quatre": "4",
    "cinq": "5", "six": "6", "sept": "7", "huit": "8", "neuf": "9", "dix": "10",
    "onze": "11", "douze": "12", "treize": "13", "quatorze": "14", "quinze": "15",
    "seize": "16", "vingt": "20", "trente": "30", "quarante": "40", "cinquante": "50",
    "soixante": "60", "cent": "100", "cents": "100", "mille": "1000",
    "million": "1000000", "millions": "1000000",
    "milliard": "1000000000", "milliards": "1000000000",
}

# The model is asked for French and mostly complies, but a stray English verb
# ("Denies") slips through grounding because the surrounding nouns do match.
ENGLISH_MARKERS = frozenset("""
denies says said with from after before against during about over under
people killed dead wounded police government president minister according
report reports claim claims accused arrested attack warns urges seeks
""".split())


def _figures(text: str) -> set[str]:
    """Quantities in `text`, normalised so "deux" and "2" compare equal.

    Leading zeros are dropped for the same reason: the point is to catch a
    changed quantity, not a changed spelling.
    """
    folded = ascii_fold(text).lower()
    figures = {str(int(digits)) for digits in _NUMBER.findall(folded)}
    figures |= {SPELLED_NUMBERS[word] for word in _WORD.findall(folded) if word in SPELLED_NUMBERS}
    return figures


def significant_words(text: str) -> set[str]:
    """Lowercase, accent-folded content words of `text` (stopwords dropped)."""
    folded = ascii_fold(text).lower()
    return {
        word for word in _WORD.findall(folded)
        if len(word) >= SIGNIFICANT_CHARS and word not in STOPWORDS
    }


def _is_derived(word: str, source_words: Iterable[str]) -> bool:
    """True if `word` plausibly comes from one of `source_words`.

    Rewriting inflects ("manifestations" -> "manifestation", "hausse" ->
    "hausses"), so an exact set match is too strict; a shared 4-character stem
    in either direction is enough.
    """
    return any(
        word == other or word.startswith(other[:SIGNIFICANT_CHARS]) or other.startswith(word[:SIGNIFICANT_CHARS])
        for other in source_words
    )


def grounding_failure(source: str, candidate: str) -> Optional[str]:
    """Explain why `candidate` is not supported by `source`, or None if it is.

    Returning the reason rather than a bool keeps the logs diagnosable: when a
    rewrite is dropped we want to know whether the model padded, drifted or
    invented a figure.
    """
    candidate_words = significant_words(candidate)
    if not candidate_words:
        return "no content word"

    source_words = significant_words(source)
    matched = {word for word in candidate_words if _is_derived(word, source_words)}
    if len(matched) < min(MIN_MATCHED_WORDS, len(candidate_words)):
        return f"only {len(matched)} word(s) from the source"

    ratio = len(matched) / len(candidate_words)
    if ratio < MIN_OVERLAP:
        invented = sorted(candidate_words - matched)[:4]
        return f"overlap {ratio:.0%} < {MIN_OVERLAP:.0%}, invented {invented}"

    # Figures are the most harmful thing a rewrite can invent ("+15%", "3 morts").
    extra_figures = _figures(candidate) - _figures(source)
    if extra_figures:
        return f"figures absent from the source: {sorted(extra_figures)}"

    english = {word for word in candidate_words if word in ENGLISH_MARKERS}
    if english - significant_words(source):
        return f"English words: {sorted(english)}"

    return None


REWRITE_PROMPT = """Raccourcis ce titre de presse pour un afficheur LED.

Titre: {title}

Regles absolues:
- Garde le MEME sens. N'ajoute aucune information, aucun chiffre, aucun nom absent du titre.
- Maximum {max_chars} caracteres.
- En francais, sans accent, sans emoji, sans guillemets.
- Une seule ligne. Reponds uniquement par le titre raccourci, rien d'autre.
"""


class _Generator(Protocol):
    def generate(self, prompt: str, *, timeout: int = ...) -> str: ...


def rewrite_headline(client: _Generator, headline: Headline, *, max_chars: int = DEFAULT_MAX_CHARS,
                     timeout: int = 60) -> str:
    """Return a shortened title, falling back to truncation when unconvinced."""
    title = clean_title(headline.title, headline.source)
    fallback = truncate_line(ascii_fold(title), max_chars)
    if len(title) <= max_chars:
        return fallback

    try:
        raw = client.generate(REWRITE_PROMPT.format(title=title, max_chars=max_chars), timeout=timeout)
    except Exception as exc:
        logger.warning("Headline rewrite failed (%s): keeping the truncated title", exc)
        return fallback

    # Split lines *before* collapsing whitespace: models like to add a trailing
    # "Voila le titre raccourci." which would otherwise be folded into the line
    # and then rejected as invented content.
    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    candidate = collapse_whitespace(ascii_fold(first_line)).strip().strip('"\u00ab\u00bb').strip()
    if len(candidate) < MIN_TITLE_CHARS:
        logger.info("Rewrite rejected (too short): %r", candidate)
        return fallback

    reason = grounding_failure(title, candidate)
    if reason:
        logger.info("Rewrite rejected (%s): %r", reason, candidate)
        return fallback

    return truncate_line(candidate, max_chars)


def build_news_lines_llm(headlines: Iterable[Headline], client: Optional[_Generator], *,
                         max_chars: int = DEFAULT_MAX_CHARS, limit: int = 6,
                         with_source: bool = True, timeout: int = 60) -> list[str]:
    """`build_news_lines`, but each title is shortened by the LLM when it helps.

    With `client=None` this is exactly the non-LLM behaviour, which is also what
    every individual headline falls back to when its rewrite is rejected.
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
        width = max_chars - len(prefix)
        body = (rewrite_headline(client, headline, max_chars=width, timeout=timeout)
                if client is not None else truncate_line(title, width))
        if body:
            lines.append(prefix + body)
        if len(lines) >= limit:
            break
    return lines
