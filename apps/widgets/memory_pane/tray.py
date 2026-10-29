# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one recessed tray holding every chip of the page (MC-INTENT "Chip tray").

Two 22 px rows, chips flow column by column, 4 px row gap, 2 px column gap,
2 px padding, radius 8, the zodiac tray material.

NO SIDEWAYS SCROLLING (Lorris, 2026-10-22 feedback): a page holds exactly
what the tray shows. ``capacity()`` = 2 rows x the columns that fit at the
design chip width; the chips then stretch to fill the row so the right edge
is even. The panel pages by that capacity, so nothing is ever hidden.

The tray is also the recorder's privacy target (``buttons_container``):
everything that carries a chart name lives inside it.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QWidget

from .chip import CHIP_H, CHIP_RADIUS
from .paint import dpr_of, paint_drop, paint_recess
from .tokens import pane_tokens

TRAY_H = 52            # 2 + 22 + 4 + 22 + 2
PAD = 2
ROW_GAP = 4
COL_GAP = 2
ROWS = 2
RADIUS = 8.0


class _Content(QWidget):
    """The chip grid. Paints the open chip's drop shadow under the chips."""

    def __init__(self, parent):
        super().__init__(parent)
        self.current = None

    def paintEvent(self, _e):
        cur = self.current
        if cur is None or cur.parent() is not self or not cur.isVisible():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_drop(p, QRectF(cur.geometry()), CHIP_RADIUS, pane_tokens()["drop"])
        p.end()


class ChipTray(QWidget):
    """Recessed tray with a two-row chip grid that always fits."""

    capacity_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("memoryChipTray")
        self.setFixedHeight(TRAY_H)
        self._content = _Content(self)
        self._content.setObjectName("memoryTrayContent")
        # qt-material paints a plain QWidget's background; the recess must
        # show through.
        self.setStyleSheet("#memoryChipTray, #memoryTrayContent"
                           " { background: transparent; border: none; }")
        self._chips = []
        self._chip_w = 108
        self._capacity = 0

    # -- geometry -----------------------------------------------------------

    @property
    def content(self) -> QWidget:
        """Parent for the chips (and the empty-state label)."""
        return self._content

    def _inner_w(self) -> int:
        return max(0, self.width() - 2 * PAD)

    def columns(self) -> int:
        """Columns that fit at the design chip width (at least one)."""
        return max(1, (self._inner_w() + COL_GAP) // (self._chip_w + COL_GAP))

    def capacity(self) -> int:
        return ROWS * self.columns()

    def chip_width(self) -> int:
        """The design width stretched so the columns fill the tray evenly."""
        cols = self.columns()
        return max(self._chip_w, (self._inner_w() - (cols - 1) * COL_GAP) // cols)

    def set_chip_width(self, w: int):
        self._chip_w = max(20, int(w))
        self._check_capacity()

    def _check_capacity(self):
        cap = self.capacity()
        if cap != self._capacity:
            self._capacity = cap
            self.capacity_changed.emit(cap)

    # -- content ------------------------------------------------------------

    def set_chips(self, chips, current=None):
        """Lay the page's chips out column by column (2 rows)."""
        self._chips = list(chips)
        self._content.current = current
        self._place()

    def _place(self):
        cw = self.chip_width()
        for i, chip in enumerate(self._chips):
            col, row = divmod(i, ROWS)
            chip.setParent(self._content)
            chip.setFixedSize(cw, CHIP_H)
            chip.move(col * (cw + COL_GAP), row * (CHIP_H + ROW_GAP))
            chip.show()
        self._content.update()

    def set_empty(self, label: QLabel):
        self._chips = []
        self._content.current = None
        label.setParent(self._content)
        label.setGeometry(0, 0, self._content.width(), self._content.height())
        label.show()

    def resizeEvent(self, e):
        self._content.setGeometry(PAD, PAD, self._inner_w(), TRAY_H - 2 * PAD)
        for child in self._content.children():
            if isinstance(child, QLabel):
                child.setGeometry(0, 0, self._content.width(), self._content.height())
        self._place()
        super().resizeEvent(e)
        self._check_capacity()

    def paintEvent(self, _e):
        tok = pane_tokens()
        p = QPainter(self)
        paint_recess(p, QRectF(0, 0, self.width(), TRAY_H), RADIUS,
                     tok["zodtray"], tok["hair"], tok["well_inset"], dpr_of(self))
        p.end()
