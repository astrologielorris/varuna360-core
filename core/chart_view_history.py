"""Session history of the charts the user viewed (back / forward).

Not the chart list order: a browser-style trail of every chart shown, across
profiles, for this run of the app only (kept in memory, never saved). Visiting
a new chart while stepped back drops the forward part, as in a web browser.

Pure Python, no Qt: the chart list panel records visits and drives navigation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

MAX_ENTRIES = 200


@dataclass(frozen=True)
class HistoryEntry:
    profile_id: str
    chart_id: str
    name: str


class ChartViewHistory:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: list[HistoryEntry] = []
        self._pos = -1
        self._max = max_entries
        self._suppress = 0

    # -- recording ---------------------------------------------------------

    def record(self, profile_id, chart_id, name) -> None:
        """Note that ``chart_id`` of ``profile_id`` is now on screen.

        Ignored while navigating (``suppressed``) and when the chart is the
        one already current (re-selecting the same chart after an edit).
        """
        if self._suppress or not chart_id:
            return
        entry = HistoryEntry(str(profile_id or ""), str(chart_id), str(name or ""))
        cur = self.current()
        if cur is not None and (cur.profile_id, cur.chart_id) == (entry.profile_id, entry.chart_id):
            if cur.name != entry.name:  # renamed in place: keep the label fresh
                self._entries[self._pos] = entry
            return
        del self._entries[self._pos + 1:]
        self._entries.append(entry)
        if len(self._entries) > self._max:
            del self._entries[:len(self._entries) - self._max]
        self._pos = len(self._entries) - 1

    @contextmanager
    def suppressed(self):
        """Selections made inside this block are not recorded (navigation,
        and the profile restore it may trigger)."""
        self._suppress += 1
        try:
            yield
        finally:
            self._suppress -= 1

    # -- navigation --------------------------------------------------------

    def current(self) -> HistoryEntry | None:
        return self._entries[self._pos] if 0 <= self._pos < len(self._entries) else None

    def peek(self, step: int) -> HistoryEntry | None:
        """The entry ``step`` places away (-1 back, +1 forward), or None."""
        i = self._pos + step
        return self._entries[i] if 0 <= i < len(self._entries) else None

    def can_go(self, step: int) -> bool:
        return self.peek(step) is not None

    def move(self, step: int) -> HistoryEntry | None:
        """Step the position and return the entry now current."""
        entry = self.peek(step)
        if entry is not None:
            self._pos += step
        return entry

    def discard(self, entry: HistoryEntry) -> None:
        """Drop every occurrence of a chart that no longer exists, keeping the
        position on the same entry (or the nearest earlier one)."""
        before = self._entries[:self._pos + 1]
        kept_before = [e for e in before if e != entry]
        self._entries = kept_before + [e for e in self._entries[self._pos + 1:] if e != entry]
        self._pos = len(kept_before) - 1 if kept_before else (0 if self._entries else -1)
        # Collapse neighbours that became equal after the removal.
        i = 1
        while i < len(self._entries):
            if self._entries[i] == self._entries[i - 1]:
                del self._entries[i]
                if self._pos >= i:
                    self._pos -= 1
            else:
                i += 1

    @property
    def position(self) -> int:
        return self._pos

    def __len__(self) -> int:
        return len(self._entries)
