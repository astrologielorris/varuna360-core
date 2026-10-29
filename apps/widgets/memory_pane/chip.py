# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""One chart chip in the tray (MC-INTENT "Chart chips").

A ChartMemoryButton, so everything the old buttons did still works unchanged:
``clicked`` (load, or toggle in Select mode), the right-click
``customContextMenuRequested`` and the SPEC-TRN-006 drag onto TRANSIT. Only
the pixels are new: flat 108 x 22 chip, raised thumb + gold underline for the
open chart, an 11 px check box in Select mode, ellipsis only when the name
does not fit (full name in the tooltip).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen

from apps.widgets.chart_memory_button import ChartMemoryButton

from .paint import KeyboardFocusMixin, area_qss, cap_baseline, design_font, dpr_of, paint_accent, paint_thumb, rounded
from .tokens import pane_tokens

CHIP_W = 108          # design width (scaled by the Chart Names font area)
CHIP_H = 22
CHIP_RADIUS = 6.0
CHIP_PAD = 9.0
BOX = 11.0


class MemoryChip(KeyboardFocusMixin, ChartMemoryButton):
    """A chart chip. ``current`` = the open chart; ``select_mode`` shows the
    check box, ``checked_box`` ticks it."""

    def __init__(self, text, entry_id, parent=None, *, draggable=True,
                 current=False, select_mode=False, checked_box=False):
        super().__init__(text, entry_id, parent, draggable=draggable)
        self.current = bool(current)
        self.select_mode = bool(select_mode)
        self.checked_box = bool(checked_box)
        self._hover = False
        self.setObjectName("memoryChip")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.apply_font()

    def apply_font(self):
        # QSS keeps qt-material's QPushButton rules (height 32, padding,
        # borders) off the chip and carries the Chart Names font size.
        # qt-material's "height" beats setFixedSize: pin it to the design.
        self.setStyleSheet(
            "QPushButton#memoryChip { border: none; background: transparent;"
            " padding: 0px; margin: 0px; min-width: 0px;"
            " height: %dpx; min-height: %dpx; max-height: %dpx; %s }"
            % (CHIP_H, CHIP_H, CHIP_H, area_qss("chart_memory", 11)))

    # -- hover --------------------------------------------------------------

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    # -- paint --------------------------------------------------------------

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        if self.current:
            paint_thumb(p, r, CHIP_RADIUS, tok, dpr)
        if self.isDown():
            p.fillPath(rounded(r, CHIP_RADIUS), tok["ov_a"])
        elif self._hover and not self.current:
            p.fillPath(rounded(r, CHIP_RADIUS), tok["ov_h"])

        x = CHIP_PAD
        if self.select_mode:
            box = QRectF(x, (r.height() - BOX) / 2.0, BOX, BOX)
            if self.checked_box:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(tok["primary"])
                p.drawRoundedRect(box, 3, 3)
                tick = QPainterPath(QPointF(box.x() + 2.6, box.y() + 5.7))
                tick.lineTo(QPointF(box.x() + 4.6, box.y() + 7.6))
                tick.lineTo(QPointF(box.x() + 8.4, box.y() + 3.5))
                pen = QPen(tok["on_primary"], 1.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(tick)
            else:
                p.setPen(QPen(tok["box_line"], 1.0))
                p.setBrush(tok["secondary_light"])
                p.drawRoundedRect(box.adjusted(.5, .5, -.5, -.5), 2.5, 2.5)
            x += BOX + 6.0

        font = design_font(self, 11, 640 if self.current else 500, .005,
                           area="chart_memory")
        p.setFont(font)
        hot = self.current or self._hover
        p.setPen(tok["primary_text"] if hot else tok["secondary_text"])
        avail = max(0.0, r.width() - x - CHIP_PAD)
        name = QFontMetricsF(font).elidedText(self.text(), Qt.TextElideMode.ElideRight, avail)
        p.drawText(QPointF(x, cap_baseline(font, 0.0, r.height())), name)

        if self.current:
            paint_accent(p, CHIP_PAD, r.width() - CHIP_PAD, r.height() - 2.0,
                         tok["gold"], tok["thumb_acc_glow"], dpr)
        if self.focus_visible():
            pen = QPen(tok["ring"], 2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(rounded(r.adjusted(1, 1, -1, -1), CHIP_RADIUS - 1))
        p.end()
