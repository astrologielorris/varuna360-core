# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""The app-level accent-ink QSS block (SPEC-THM-001 §13).

Kept apart from ``ui.accent_ink`` (which ``ui.qt_theme`` imports and the SI
architecture ratchet budgets) because only ``ui.input_font_qss`` needs it.
"""
from __future__ import annotations

import re
import sys

from ui.accent_ink import on_accent_ink

_QSS_BEGIN = "/* VARUNA_ACCENT_INK_BEGIN */"
_QSS_END = "/* VARUNA_ACCENT_INK_END */"


def accent_selection_qss() -> str:
    """App-level QSS giving qt-material's own accent fills a readable ink.

    qt-material inks its own accent fills with colours chosen for the ground:
    focused selected item-view rows on ``primaryColor``, the highlighted item of
    every menu, combo popup and menu bar on ``primaryLightColor``, checked /
    pressed buttons and Linux dialog tool buttons on ``primaryColor``. Same
    selectors, appended later, so they win.
    ``selection-color`` is set too: Windows reads it for item views. The
    universal ``* { selection-color }`` is NOT overridden: widgets that set
    their own selection background rely on inheriting it.
    """
    from ui.qt_theme import get_theme_colors
    theme = get_theme_colors()
    on_primary = on_accent_ink(theme["primary"])
    on_light = on_accent_ink(theme["primary_light"])
    on_button = on_accent_ink(theme["primary"], theme["secondary_dark"])
    on_tool = on_accent_ink(theme["primary"], theme["secondary_text"])
    return (
        f"{_QSS_BEGIN}\n"
        "QTableView::item:selected:focus, QTreeView::item:selected:focus, "
        "QListView::item:selected:focus "
        f"{{ color: {on_primary}; selection-color: {on_primary}; }}\n"
        "QComboBox::item:selected, QCalendarWidget QMenu::item:selected, "
        "QMenu::item:selected, QMenuBar::item:selected, QMenuBar::item:pressed "
        f"{{ color: {on_light}; }}\n"
        # qt-material inks checked / pressed buttons with secondaryDarkColor
        # (#e6e6e6 on Light Yellow's #ffea00) and, on Linux, dialog tool
        # buttons with secondaryTextColor (white on Dark Cyan's #4dd0e1).
        f"QPushButton:checked, QPushButton:pressed {{ color: {on_button}; }}\n"
        # qt-material fills dialog tool buttons with primary on Linux only;
        # elsewhere they sit on the ground, where this ink would not read.
        + ("QDialog QToolButton, QDialog QToolButton:hover, QDialog QToolButton:pressed, "
           f"QDialog QToolButton:checked {{ color: {on_tool}; }}\n"
           if sys.platform.startswith("linux") else "")
        + f"{_QSS_END}"
    )


_BLOCK_RE = re.compile(re.escape(_QSS_BEGIN) + r".*?" + re.escape(_QSS_END) + r"\n?", re.S)


def strip_accent_selection_qss(sheet: str) -> str:
    """``sheet`` without a previous :func:`accent_selection_qss` block. The
    block is (re)appended by ``ui.input_font_qss.apply_global_input_font_qss``
    in the same single app-sheet write, after every ``apply_stylesheet`` (boot
    and live switch): an extra ``app.setStyleSheet`` would repolish every
    widget of the app a second time."""
    return _BLOCK_RE.sub("", sheet or "")
