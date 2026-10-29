# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""One-line summaries of the folded Chart-tab info panels (SPEC-LAYOUT-001 D6).

Computed from the chart, never read from a folded (unrendered) body: the same
capability functions the panel controllers render (SPEC-AIC-001 INV-1), so a
summary and the open table can never disagree. Each text is cached under a
revision key (chart object, zodiac mode, Avastha view, DUC Bala method); a
chart change or a DUC method change (SPEC-STR-001 §7.5) makes the key stale,
so a resize or a repaint never recomputes anything.
"""
from __future__ import annotations

import traceback
from typing import Any, Dict, Optional, Tuple

PENDING = "…"        # shown until the summary of the current chart is computed

GLYPHS = {"Sun": "☉", "Moon": "☽", "Mars": "♂", "Mercury": "☿",
          "Jupiter": "♃", "Venus": "♀", "Saturn": "♄"}


def title(name: str) -> str:
    """The panel title a folded panel's capture header carries (plan D7a)."""
    from core.i18n import t
    if name == "karakas":
        return t("panel.info.title.karakas", "Karakas")
    if name == "strength":
        return t("panel.info.title.strength", "Strength")
    return t("panel.info.title.avastha", "Avastha")


def _planet(name: str) -> str:
    from core.i18n import term
    glyph = GLYPHS.get(name)
    shown = term("planet", name)
    return f"{glyph} {shown}" if glyph else shown


def karakas_text(chart, mode: str) -> str:
    """"AK ♂ Mars · AmK ☽ Moon": the two first karakas of the Karakas table."""
    from core.capabilities.karakas_aspects import karaka_rows
    roles = {r["code"]: r["planet"] for r in karaka_rows(chart, mode)}
    parts = [f"{code} {_planet(roles[code])}" for code in ("AK", "AmK") if code in roles]
    return " · ".join(parts)


def strength_text(chart, duc_method=None) -> str:
    """"Strongest: ♄ Saturn 42.9": the highest Duc Bala of the Strength table."""
    from core.capabilities.strength import strength_rows
    rows = strength_rows(chart, duc_method)
    if not rows:
        return ""
    best = max(rows, key=lambda r: r["duc_bala"])
    from core.i18n import t
    return t("panel.info.summary.strength", "Strongest: {planet} {value}",
             planet=_planet(best["planet"]), value=best["text"]["duc_bala"])


def avastha_text(chart, mode: str, view: str, duc_method=None) -> str:
    """"Avastha total +166 ☉ Su": the highest TOTAL of the Avastha table in the
    view the panel shows (pure or a strength-refined view)."""
    from core.capabilities.avastha import avastha_grid
    grid = avastha_grid(chart, mode, view, duc_method)
    totals = grid["values"]["total"]
    planets = grid["planets"]
    if not totals:
        return ""
    i = max(range(len(totals)), key=lambda k: totals[k])
    value = totals[i]
    num = f"{value:+.0f}" if view == "pure" else f"{value:+.1f}"
    name = planets[i]
    short = f"{GLYPHS[name]} {name[:2]}" if name in GLYPHS else name   # the table's row label
    from core.i18n import t
    return t("panel.info.summary.avastha", "Avastha total {value} {planet}",
             value=num, planet=short)


class SummaryModel:
    """Revision-tagged cache of the three summaries (plan D6)."""

    def __init__(self):
        self._cache: Dict[str, Tuple[Any, str]] = {}
        self._failed: Dict[str, Any] = {}      # name -> key whose calculation raised

    @staticmethod
    def key(name: str, gui) -> Optional[tuple]:
        state = getattr(gui, "state", None)
        chart = getattr(state, "active_chart", None)
        if chart is None:
            return None
        mode = getattr(state, "aditya_mode", "aditya")
        view = None
        if name == "bottom":
            ctrl = getattr(gui, "avastha_controller", None)
            view = ctrl.current_view() if ctrl is not None else "pure"
        from apps.widgets.panel_controllers.duc_method import current_duc_method
        return (chart, mode, view, current_duc_method())

    def invalidate(self) -> None:
        self._cache.clear()
        self._failed.clear()

    def cached(self, name: str, gui) -> Optional[str]:
        """The text when it is current for the active chart, else None."""
        key = self.key(name, gui)
        if key is None:
            return ""
        hit = self._cache.get(name)
        return hit[1] if hit is not None and _same(hit[0], key) else None

    def text(self, name: str, gui, *, retry: bool = False) -> str:
        """The current summary, computed now when stale ("" on no chart or a
        calculation error, plan D6). A failed calculation is remembered for
        its key so a repaint or a resize never re-runs it; ``retry=True`` (an
        explicit capture / remote read) runs it again."""
        hit = self.cached(name, gui)
        key = self.key(name, gui)
        if hit is not None and not (retry and self._failed_for(name, key)):
            return hit
        chart, mode, view, duc_method = key
        try:
            if name == "karakas":
                text = karakas_text(chart, mode)
            elif name == "strength":
                text = strength_text(chart, duc_method)
            else:
                text = avastha_text(chart, mode, view or "pure", duc_method)
        except Exception:
            traceback.print_exc()
            self._failed[name] = key
            text = ""
        else:
            self._failed.pop(name, None)
        self._cache[name] = (key, text)
        return text

    def _failed_for(self, name: str, key) -> bool:
        failed = self._failed.get(name)
        return failed is not None and key is not None and _same(failed, key)

    def status(self, name: str, gui) -> Tuple[str, Optional[str]]:
        """Capture status of a folded panel (plan D7a): 'ok' when the summary
        is current for the active chart, 'error' when its calculation raised,
        else 'pending'."""
        key = self.key(name, gui)
        hit = self._cache.get(name)
        if key is None or hit is None or not _same(hit[0], key):
            return "pending", None
        if self._failed_for(name, key):
            return "error", None
        return "ok", hex(id(key[0]))


def _same(a: tuple, b: tuple) -> bool:
    return a[0] is b[0] and a[1:] == b[1:]
