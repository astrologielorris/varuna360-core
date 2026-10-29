# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""A font refresh re-sets only the style sheets that changed (review
2026-10-13 H6).

The window's font refresh (``_on_font_sizes_changed``) regenerates every
panel's style sheet, about 155 ``setStyleSheet`` calls, and Qt re-polishes a
widget and its whole subtree on every call, even when the text is the same.
One font area changes a few of them; the rest were 0.5-0.6 s of identical
re-polish per refresh. Inside ``unchanged_sheets_skipped()`` a call whose
sheet equals the widget's current one does nothing: an identical sheet
gives an identical style (the tab widget sheet already worked this way,
td-8m3kd). Anything that changes the application sheet still re-polishes
everything through Qt itself.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtWidgets import QWidget

_depth = 0
_real = None            # QWidget.setStyleSheet as found when the scope opened


def _set_if_changed(widget, sheet):
    if widget.styleSheet() == sheet:
        return
    _real(widget, sheet)


@contextmanager
def unchanged_sheets_skipped():
    """While open, ``QWidget.setStyleSheet`` with the widget's current sheet
    is a no-op (nested uses are fine; the GUI thread only)."""
    global _depth, _real
    if _depth == 0:
        _real = QWidget.setStyleSheet
        QWidget.setStyleSheet = _set_if_changed
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if _depth == 0:
            QWidget.setStyleSheet = _real
            _real = None
