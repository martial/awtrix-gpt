"""The content the clock rotates through, grouped by where it came from."""

from dataclasses import dataclass, field, fields
from typing import Iterable


@dataclass(frozen=True)
class ContentItem:
    id: str
    text: str


def items_from_lines(lines: Iterable[str], prefix: str) -> list[ContentItem]:
    return [ContentItem(id=f"{prefix}_{i}", text=line) for i, line in enumerate(lines)]


@dataclass
class Content:
    """Everything currently displayable.

    `weather`, `news` and `local_info` are built in code from real data;
    `messages`, `suggested_activities` and `poems` come from the LLM.
    """

    messages: list[ContentItem] = field(default_factory=list)
    weather: list[ContentItem] = field(default_factory=list)
    news: list[ContentItem] = field(default_factory=list)
    suggested_activities: list[ContentItem] = field(default_factory=list)
    poems: list[ContentItem] = field(default_factory=list)
    local_info: list[ContentItem] = field(default_factory=list)

    def categories(self) -> dict[str, list[ContentItem]]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def all_items(self) -> list[ContentItem]:
        return [item for items in self.categories().values() for item in items]

    def counts(self) -> dict[str, int]:
        return {name: len(items) for name, items in self.categories().items()}

    def is_empty(self) -> bool:
        return not self.all_items()
