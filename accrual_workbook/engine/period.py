"""Accounting period helpers. The fiscal year is the calendar year."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def month_index(key: str) -> int:
    """'2026-09' -> absolute month number, for month arithmetic."""
    y, m = key.split("-")
    return int(y) * 12 + int(m) - 1


def key_from_index(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


@dataclass(frozen=True, order=True)
class Period:
    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> "Period":
        try:
            y, m = str(text).strip().split("-")[:2]
            p = cls(int(y), int(m))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"period must look like 2026-09, got {text!r}") from exc
        if not 1 <= p.month <= 12:
            raise ValueError(f"bad month in period {text!r}")
        return p

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def end(self) -> date:
        return month_end(self.year, self.month)

    @property
    def fy_start(self) -> date:
        return date(self.year, 1, 1)

    @property
    def fy_end(self) -> date:
        return date(self.year, 12, 31)

    @property
    def months_elapsed(self) -> int:
        return self.month

    @property
    def reverse_date(self) -> date:
        nxt = self.next()
        return nxt.start

    @property
    def label(self) -> str:  # "Sep 2026"
        return f"{MONTH_ABBR[self.month - 1]} {self.year}"

    @property
    def short(self) -> str:  # "Sep 26"
        return f"{MONTH_ABBR[self.month - 1]} {self.year % 100:02d}"

    @property
    def memo_tag(self) -> str:  # "Sep2026"
        return f"{MONTH_ABBR[self.month - 1]}{self.year}"

    def prev(self) -> "Period":
        return Period(self.year - 1, 12) if self.month == 1 else Period(self.year, self.month - 1)

    def next(self) -> "Period":
        return Period(self.year + 1, 1) if self.month == 12 else Period(self.year, self.month + 1)

    def fy_month_keys(self) -> list[str]:
        """Service months Jan..period month of the fiscal year."""
        return [f"{self.year:04d}-{m:02d}" for m in range(1, self.month + 1)]

    def __str__(self) -> str:
        return self.key
