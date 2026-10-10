"""When should content be regenerated? Pure rules, no I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Optional


@dataclass(frozen=True)
class UpdateScheduler:
    start_hour: int
    end_hour: int
    interval: timedelta

    @classmethod
    def from_config(cls, display_cfg: Mapping) -> "UpdateScheduler":
        hours = display_cfg.get("active_hours", {}) or {}
        return cls(
            start_hour=int(hours.get("start", 0)),
            end_hour=int(hours.get("end", 23)),
            interval=timedelta(seconds=int(display_cfg.get("update_interval", 1800))),
        )

    def in_active_hours(self, now: datetime) -> bool:
        return self.start_hour <= now.hour <= self.end_hour

    def is_due(self, last_update: Optional[datetime], now: datetime) -> bool:
        """True when inside active hours and `interval` has elapsed (or never updated)."""
        if not self.in_active_hours(now):
            return False
        return last_update is None or (now - last_update) >= self.interval
