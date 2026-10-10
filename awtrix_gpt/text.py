"""Pure text helpers for a 32x8 LED matrix.

The AWTRIX font has no accented glyphs and the panel scrolls a single line,
so everything that reaches the clock goes through `ascii_fold` and, for
anything of unbounded length (headlines), `truncate_line`.
"""

import re
import unicodedata
from typing import Iterable, Mapping

# A scrolling line this long takes ~15 s to pass on the panel; longer than
# that and nobody reads it to the end.
DEFAULT_MAX_CHARS = 70

# Typographic characters NFKD would simply drop (turning "l'Europe" into
# "lEurope"); map them to their ASCII cousins first.
_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ",
    "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE",
})

_WORD_SPLIT = re.compile(r"(\W+)")


def ascii_fold(text: str) -> str:
    """Strip accents and typographic punctuation: 'été à Marseille' -> 'ete a Marseille'."""
    text = str(text).translate(_TYPOGRAPHIC)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def collapse_whitespace(text: str) -> str:
    """Turn any run of whitespace (including newlines) into one space."""
    return " ".join(str(text).split())


def truncate_line(text: str, max_chars: int = DEFAULT_MAX_CHARS, ellipsis: str = "...") -> str:
    """Collapse whitespace and cut `text` to `max_chars`, preferring a word boundary.

    The cut never lands on a trailing separator, so "Le gouvernement, ..." does
    not happen. If no word boundary exists in the second half of the budget the
    text is cut mid-word rather than shortened to nothing.
    """
    text = collapse_whitespace(text)
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    budget = max(max_chars - len(ellipsis), 1)
    cut = text[:budget]
    boundary = cut.rfind(" ")
    if boundary >= budget // 2:
        cut = cut[:boundary]
    return cut.rstrip(" ,;:-'\"(") + ellipsis


class Highlighter:
    """Split a line into AWTRIX text fragments, colouring configured words.

    `words` maps a category to its word list and `colors` maps the same
    categories to hex colours; `default` and `numbers` are special colour
    keys. Category order (dict order) decides which colour wins when a word
    appears in several lists, matching the original behaviour.
    """

    def __init__(self, words: Mapping[str, Iterable[str]], colors: Mapping[str, str]):
        self._default = colors.get("default", "#FFFFFF")
        self._numbers = colors.get("numbers", self._default)
        self._by_word: dict[str, str] = {}
        for category, word_list in words.items():
            color = colors.get(category, self._default)
            for word in word_list or ():
                self._by_word.setdefault(ascii_fold(str(word)).lower(), color)

    @classmethod
    def from_config(cls, config: Mapping) -> "Highlighter":
        return cls(config.get("words", {}) or {}, config.get("colors", {}) or {})

    def color_for(self, word: str) -> str:
        color = self._by_word.get(word.lower())
        if color is not None:
            return color
        return self._numbers if word[:1].isdigit() else self._default

    def fragments(self, text: str) -> list[dict[str, str]]:
        """Return `[{"t": word, "c": "#RRGGBB"}, ...]` as the AWTRIX notify API expects."""
        return [
            {"t": word, "c": self.color_for(word)}
            for word in _WORD_SPLIT.split(ascii_fold(text))
            if word
        ]
