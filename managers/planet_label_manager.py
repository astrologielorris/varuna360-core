# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""F11: what the text under the planets says (SPEC-PLM-001 v2).

One press moves ``chart.planet_label`` to the next mode (degrees -> planet
names -> Human Design gates -> nakshatras -> degrees), sets it on the three
chart views, redraws the ones holding a chart and says it in the status bar.
The Settings tab, the startup restore and F11 all go through ``apply``.

Rule 4b: the window gets no new attribute; the views own ``planet_label``.
"""
from __future__ import annotations

from core.planet_label import (LABEL_KEY, LEGACY_NAMES_KEY, MODE_LABELS,
                               next_mode, normalized, saved_mode)

SHORTCUT = "F11"

# (view attribute on the window, its redraw method)
_VIEWS = (("chart_view", "draw_full_chart"), ("north_indian_view", "draw_chart"),
          ("wheel_view", "draw_wheel"))


def current(gui) -> str:
    """The mode the charts are drawn with now."""
    view = getattr(gui, "wheel_view", None)
    return normalized(getattr(view, "planet_label", None))


def apply(gui, mode, persist=True, announce=False) -> str:
    """Draw every chart view with ``mode``; ``persist`` writes it (a locked
    setting is left as stored). The legacy names flag is cleared with it."""
    mode = normalized(mode)
    for attr, redraw in _VIEWS:
        view = getattr(gui, attr, None)
        if not view:
            continue
        changed = getattr(view, "planet_label", None) != mode
        view.planet_label = mode
        if changed and getattr(view, "_chart", None):
            getattr(view, redraw)()
            view.ensure_visible()
    if persist:
        from managers.settings_manager import get_settings
        s = get_settings()
        s.persist_runtime_change(LABEL_KEY, mode)
        if s.get(LEGACY_NAMES_KEY, False):
            s.persist_runtime_change(LEGACY_NAMES_KEY, False)
    if announce:
        gui.statusBar().showMessage(
            f"Under planets: {MODE_LABELS[mode]} ({SHORTCUT} for "
            f"{MODE_LABELS[next_mode(mode)]})", 3000)
    return mode


def redraw_gates(gui):
    """The Human Design level moved gate 1: redraw the views showing gates."""
    if current(gui) != "gates":
        return
    # the vector centre mini's picture is keyed without the level (SI budget):
    # drop it through the view's own invalidation event
    centre = getattr(getattr(getattr(gui, "chart_view", None), "vector_view", None), "center", None)
    if centre is not None:
        centre._invalidate_transit_cache()
    for attr, redraw in _VIEWS:
        view = getattr(gui, attr, None)
        if view and getattr(view, "_chart", None):
            getattr(view, redraw)()


def cycle(gui) -> str:
    """F11: the next mode, written and drawn."""
    return apply(gui, next_mode(current(gui)), announce=True)


def restore(gui, settings) -> str:
    """Startup and Settings Apply: draw the saved mode. A file from before the
    four modes (the legacy flag on) is moved to ``chart.planet_label`` once."""
    mode = saved_mode(settings.get)
    return apply(gui, mode, persist=bool(settings.get(LEGACY_NAMES_KEY, False)))
