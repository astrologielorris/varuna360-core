# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The three zone tones of Rate and Sort (SPEC-LIB-002 §4.2, D-13, D-25).

Lorris's chosen mockup colours: Constellation Desk's in a light theme, Night
Orbit's in a dark one, chosen by ``ui.qt_theme.is_light_theme()``. Widgets read
the tones only here; ``ui/qt_theme.py`` does not grow. ``tone(zone)`` is the
mark colour, ``cell(zone)`` the plane's cell tint.
"""
from PySide6.QtGui import QColor

from core.library.rating import MIXED, PRIVATE, PUBLIC

_LIGHT = {PRIVATE: "#b2457a", MIXED: "#c17a10", PUBLIC: "#2c66cf"}
_LIGHT_CELL = {PRIVATE: "#fbeff5", MIXED: "#fdf5e8", PUBLIC: "#eef4fe"}
_DARK = {PRIVATE: "#e27aa9", MIXED: "#e8ab4c", PUBLIC: "#6fa2f3"}
_DARK_CELL_ALPHA = 0.11
#: The stars of rows 3 and 4 (the mockups' gold).
_STAR = {True: "#e2a206", False: "#e8b84c"}


def _light() -> bool:
    from ui.qt_theme import is_light_theme
    return bool(is_light_theme())


def tone(zone) -> QColor:
    if zone not in _LIGHT:
        return QColor("#8a8a8e")
    return QColor((_LIGHT if _light() else _DARK)[zone])


def cell(zone) -> QColor:
    if zone not in _LIGHT:
        return QColor(0, 0, 0, 0)
    if _light():
        return QColor(_LIGHT_CELL[zone])
    c = QColor(_DARK[zone])
    c.setAlphaF(_DARK_CELL_ALPHA)
    return c


def star() -> QColor:
    return QColor(_STAR[_light()])
