# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Cursor highlight (SPEC-REC-001 §4.5): a coloured circle that follows the
mouse pointer over every app, always on during a take, no hold needed
(Lorris, 2026-10-17; desktop translation of the mobile touch highlight).

A frameless, always-on-top, input-transparent window centred on the pointer
(INV-5). A 60 Hz timer reads ``QCursor.pos()`` and moves the window only when
the pointer moved. With a compositor the circle is translucent; without one
(Xvfb), the window is shaped to a ring and painted opaque (INV-6).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

# Semantic highlight colours (Rule 20 exception: a pointer colour, not theme).
COLOURS = {"red": "#E53935", "rose": "#EC407A", "orange": "#FB8C00",
           "yellow": "#FDD835", "blue": "#1E88E5", "green": "#43A047"}
SIZES = {"S": 40, "M": 64, "L": 96}
RING = 3
TICK_MS = 16


class CursorHighlight(QWidget):
    def __init__(self, color="red", opacity=50, size="M", shape="disc_ring",
                 translucent=True):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.X11BypassWindowManagerHint)
        super().__init__(None, flags)
        self.setObjectName("recorder_cursor_highlight")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._translucent = translucent
        if translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._last = QPoint(-1, -1)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._follow)
        self.configure(color, opacity, size, shape)

    def configure(self, color, opacity, size, shape):
        self._color = QColor(COLOURS.get(color, COLOURS["red"]))
        self._opacity = max(20, min(80, int(opacity))) / 100.0
        self._diameter = SIZES.get(size, SIZES["M"])
        self._shape = shape if shape in ("disc", "ring", "disc_ring") else "disc_ring"
        side = self._diameter + 2 * RING
        self.setFixedSize(side, side)
        if not self._translucent:
            outer = QRegion(QRect(0, 0, side, side), QRegion.RegionType.Ellipse)
            inner = QRegion(QRect(RING * 2, RING * 2, side - RING * 4, side - RING * 4),
                            QRegion.RegionType.Ellipse)
            self.setMask(outer.subtracted(inner))           # ring only: never hides the target
        self.update()

    def start(self):
        self._last = QPoint(-1, -1)
        self._follow()
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _follow(self):
        pos = QCursor.pos()
        if pos == self._last:
            return
        self._last = pos
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() // 2)

    def paintEvent(self, _event):                           # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = self.width()
        box = QRect(RING, RING, side - 2 * RING, side - 2 * RING)
        if not self._translucent:
            p.setPen(QPen(self._color, RING * 2))
            p.drawEllipse(box.adjusted(RING, RING, -RING, -RING))
            return
        if self._shape in ("disc", "disc_ring"):
            fill = QColor(self._color)
            fill.setAlphaF(self._opacity)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawEllipse(box)
        if self._shape in ("ring", "disc_ring"):
            edge = QColor(self._color)
            edge.setAlphaF(min(1.0, self._opacity + 0.3))
            p.setPen(QPen(edge, RING))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(box)
