# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart panel's responsive tiers (SPEC-FIND-005 §4.8).

Two decisions, both from widths the tiers never change themselves:

- the **layout tier** (T0..T4) from the panel's own width, with the bar's
  ``TierEngine`` (16 px hysteresis): inspector docked or sheet, picker
  columns or drill-down, table or cards;
- the **toolbar label row**: starting at the layout tier's row of
  ``FC_LABELS``, the first row whose measured width fits the toolbar.

The decisions are pure functions; ``ResponsiveController`` only feeds them
the panel's resize events and emits ``tier_changed``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QEvent, QObject, Signal

from apps.widgets.action_bar.tier_engine import TierEngine

T0, T1, T2, T3, T4 = range(5)

#: Cold-start and shrinking thresholds (px); growing adds the hysteresis.
LAYOUT_WIDTHS: tuple[int, ...] = (1280, 1025, 821, 641, 0)
HYSTERESIS_PX = 16

#: Per toolbar key, its label per row: a str (``""`` = icon only) or
#: ``None`` = hidden (moved into the "..." menu). Five rows, one per layout
#: tier; a narrower toolbar steps further down (``label_row``). EASY / ADV
#: keep a label down to the last row.
FC_LABELS: Mapping[str, tuple[str | None, ...]] = {
    "easy": ("EASY", "EASY", "EASY", "EASY", "EASY"),
    "advanced": ("ADVANCED", "ADV", "ADV", "ADV", "ADV"),
    "ask_ai": ("ASK AI", "ASK AI", "ASK AI", "", ""),
    "search_web": ("SEARCH WEB", "WEB", "WEB", "", ""),
    "filters": ("FILTERS", "FILTERS", "FILTERS", "", None),
    "library": ("LIBRARY", "LIBRARY", "LIBRARY", "", None),
    "more": (None, None, None, None, ""),
}
ROWS = 5


def layout_engine() -> TierEngine:
    """A TierEngine over the layout thresholds (the last one, 0, made
    strictly decreasing with a negative sentinel)."""
    widths = [float(w) for w in LAYOUT_WIDTHS[:-1]] + [-1.0]
    engine = TierEngine(hysteresis_px=HYSTERESIS_PX)
    engine.set_table(widths, width=float(LAYOUT_WIDTHS[0]))
    return engine


def cold_tier(width: float) -> int:
    """The layout tier at ``width`` with no history."""
    for tier, need in enumerate(LAYOUT_WIDTHS):
        if width >= need:
            return tier
    return T4


def label_row(
    layout_tier: int,
    available: float,
    measure: Callable[[int], float],
) -> int:
    """The toolbar label row: the layout tier's row, or the next narrower one
    while ``measure(row)`` (the toolbar's width with that row's labels)
    exceeds ``available``. The last row is kept even if it overflows."""
    row = max(0, min(layout_tier, ROWS - 1))
    while row < ROWS - 1 and measure(row) > available:
        row += 1
    return row


def labels_at(row: int) -> dict[str, str | None]:
    return {key: labels[row] for key, labels in FC_LABELS.items()}


def row_width(
    row: int,
    box: Callable[[str, str], float],
    *,
    gaps: float,
    fixed: float,
    present: Sequence[str] = tuple(FC_LABELS),
) -> float:
    """The toolbar's width at ``row``: each present key's box for its label
    (``box(key, label)``), hidden ones left out, plus ``gaps`` and the
    ``fixed`` parts (the SearchWell minimum, margins)."""
    total = fixed + gaps
    for key in present:
        label = FC_LABELS[key][row]
        if label is not None:
            total += box(key, label)
    return total


class ResponsiveController(QObject):
    """Watches ``panel``'s width; emits ``tier_changed(int)`` when the layout
    tier moves (TierEngine hysteresis). Reads only the panel's own width."""

    tier_changed = Signal(int)

    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        self._panel = panel
        self._engine = layout_engine()
        self._engine.set_table(self._engine.fit_widths, width=float(panel.width() or 1920))
        panel.installEventFilter(self)

    @property
    def tier(self) -> int:
        return self._engine.tier

    def feed(self, width: float) -> int:
        before = self._engine.tier
        after = self._engine.on_width(float(width))
        if after != before:
            self.tier_changed.emit(after)
        return after

    def eventFilter(self, obj, event):
        if obj is self._panel and event.type() == QEvent.Type.Resize:
            self.feed(event.size().width())
        return False
