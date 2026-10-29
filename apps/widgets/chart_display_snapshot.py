# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The chart display settings tree, for read-only use while drawing.

``SettingsManager.get_chart_display()`` deep-copies the whole defaults tree and
merges the stored ``chart_display`` over it on every call (about half a
millisecond). The drawing passes ask once per planet shadow and per sign shadow,
some 135 times on each birth-time step over the chart views. Here the merged
tree is rebuilt only when the stored value changes: its ``repr`` is the key, so
every write path counts, an in-place edit included. Callers only read it.
"""
from managers.settings_manager import DEFAULT_CHART_DISPLAY, get_settings

_KEPT = [None, None, None]   # settings manager, repr of its stored tree, merged tree


def chart_display():
    """``get_chart_display()`` of the settings in use (never mutate the result)."""
    s = get_settings()
    key = repr(s.get("chart_display", None))
    if _KEPT[0] is not s or _KEPT[1] != key:
        _KEPT[:] = [s, key, s.get_chart_display()]
    return _KEPT[2]


def chart_display_section(section):
    """``get_chart_display_section(section)``, read from the kept tree."""
    return chart_display().get(section, DEFAULT_CHART_DISPLAY.get(section, {}))
