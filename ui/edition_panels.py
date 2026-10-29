# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Main-window panels an edition package adds, refreshed by Core by name.

Core never names a Pro-only panel (td-txv5v). The Pro package registers its
panels here when it is imported (``pro/__init__.py``); the main window
(``apps/core_gui_qt.py``) walks these lists where it used to list the panel
attributes by hand:

- ``chart_refresh_attrs()``: panels not yet on a PanelController that get
  ``update_from_chart`` when their tab is visible and are marked dirty
  (``_chart_dirty``) otherwise, then refreshed on tab switch.
- ``theme_refresh_attrs()``: panels in the theme and font-size fan-outs
  (``refresh_theme``).
- ``icon_refreshers()``: ``(attr, fn)`` pairs; ``fn(panel)`` rebuilds icons
  rasterised into the panel's scene after a Chart Display Apply.
- ``left_ayanamsa_note()``: the sentence the dasha ayanamsa chooser adds for
  the left panel, naming the edition's pages that follow its ayanamsa
  (empty when the edition has none).

Every attribute is read with ``getattr(window, attr, None)``, so a panel that
is not built is skipped. Pure data, Qt-free, stdlib only.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

_CHART_REFRESH: List[str] = []
_THEME_REFRESH: List[str] = []
_ICON_REFRESH: List[Tuple[str, Callable]] = []
_LEFT_AYANAMSA_NOTE = [""]


def register_panel(attr: str, *, chart_refresh: bool = False, theme_refresh: bool = False,
                   icon_refresh: Callable = None) -> None:
    """Register the window attribute ``attr`` of an edition panel. Registering
    the same attribute again does not add it twice."""
    if chart_refresh and attr not in _CHART_REFRESH:
        _CHART_REFRESH.append(attr)
    if theme_refresh and attr not in _THEME_REFRESH:
        _THEME_REFRESH.append(attr)
    if icon_refresh is not None and all(a != attr for a, _fn in _ICON_REFRESH):
        _ICON_REFRESH.append((attr, icon_refresh))


def set_left_ayanamsa_note(text: str) -> None:
    _LEFT_AYANAMSA_NOTE[0] = text or ""


def chart_refresh_attrs() -> Tuple[str, ...]:
    return tuple(_CHART_REFRESH)


def theme_refresh_attrs() -> Tuple[str, ...]:
    return tuple(_THEME_REFRESH)


def icon_refreshers() -> Tuple[Tuple[str, Callable], ...]:
    return tuple(_ICON_REFRESH)


def left_ayanamsa_note() -> str:
    return _LEFT_AYANAMSA_NOTE[0]
