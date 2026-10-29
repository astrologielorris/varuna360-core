# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The four rating rows of the chart card (SPEC-LIB-002 §4.6).

``RatingRow(row)``: row 1 ("who") as seven named segments (Night Orbit, D-4,
D-12); rows 2 to 4 as a "0" pill and five stars (Constellation Desk), the
value's words beside them. Each row ends with its tag: "guess · <source>"
in italic grey, or "✓ yours" in green.

INV-1: one painter decides both looks from the row's state. A guess is drawn
hollow and dashed (segment outline, star outline); a value of the user's is
drawn solid. ``set_state(value, guess, source)``; a click emits
``changed(row, value)``; ``set_focused`` draws the keyboard row marker.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.library import rating
from panels.find_chart import kit, zone_tones


def star_path(c: QPointF, r: float) -> QPainterPath:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a)))
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


class RatingRow(QWidget):
    changed = Signal(str, object)

    def __init__(self, row: str, parent=None) -> None:
        super().__init__(parent)
        self.row = row
        self._value = None
        self._guess = False
        self._source = ""
        self._focused = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(rating.ROW_TITLES[row])
        self.refresh_metrics()

    # ---------------------------------------------------------- state
    def set_state(self, value, guess: bool, source: str = "") -> None:
        self._value, self._guess, self._source = value, bool(guess) and value is not None, source
        self.update()

    def value(self):
        return self._value

    def is_guess(self) -> bool:
        return self._guess

    def tag_text(self) -> str:
        if self._value is None:
            return ""
        return f"guess · {self._source}" if self._guess else "✓ yours"

    def set_focused(self, on: bool) -> None:
        self._focused = bool(on)
        self.update()

    # ---------------------------------------------------------- geometry
    def refresh_metrics(self) -> None:
        fs = kit.area_fs("info_text")
        self._fs = fs
        self._title_h = round(15 * fs)
        self._ctl_h = round(22 * fs)
        self.setFixedHeight(self._title_h + self._ctl_h + round(4 * fs))
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(round(300 * self._fs), self.height())

    def _left(self) -> float:
        return 8 * self._fs

    def control_rects(self) -> list[tuple[object, QRectF]]:
        """(value, hit rect) of each choice."""
        y, h = self._title_h, self._ctl_h
        x0, right = self._left(), self.width() - 1
        if self.row == "who":
            n = len(rating.WHO)
            gap = 3 * self._fs
            w = (right - x0 - gap * (n - 1)) / n
            return [(who, QRectF(x0 + i * (w + gap), y, w, h)) for i, who in enumerate(rating.WHO)]
        side = h
        out = [(0, QRectF(x0, y, side * 1.1, h))]
        x = x0 + side * 1.1 + 4 * self._fs
        for v in range(1, 6):
            out.append((v, QRectF(x, y, side, h)))
            x += side + 1 * self._fs
        return out

    # ---------------------------------------------------------- input
    def mousePressEvent(self, e):
        if not self.isEnabled():
            return
        for value, r in self.control_rects():
            if r.contains(e.position()):
                self.changed.emit(self.row, value)
                return

    # ---------------------------------------------------------- paint
    def paintEvent(self, _event):
        t = kit.tokens()
        fs = self._fs
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QFont(self.font())
        base.setPixelSize(max(9, round(11 * fs)))
        small = QFont(base)
        small.setPixelSize(max(8, round(10 * fs)))
        if self._focused:
            p.fillRect(QRectF(0, 2, max(2.0, 2.5 * fs), self.height() - 4), t["primary"])
        # title and tag
        p.setFont(base)
        p.setPen(t["primary_text"])
        title_r = QRectF(self._left(), 0, self.width() * 0.6, self._title_h)
        p.drawText(title_r, Qt.AlignLeft | Qt.AlignVCenter, rating.ROW_TITLES[self.row])
        tag = self.tag_text()
        if tag:
            f = QFont(small)
            f.setItalic(self._guess)
            f.setBold(not self._guess)
            p.setFont(f)
            p.setPen(t["muted"] if self._guess else t["green"])
            p.drawText(QRectF(0, 0, self.width() - 2, self._title_h),
                       Qt.AlignRight | Qt.AlignVCenter, tag)
        rects = self.control_rects()
        if self.row == "who":
            self._paint_segments(p, t, rects, small)
        else:
            self._paint_stars(p, t, rects, small)
        p.end()

    def _paint_segments(self, p, t, rects, font) -> None:
        fs = self._fs
        p.setFont(font)
        for who, r in rects:
            on = who == self._value
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4 * fs, 4 * fs)
            if on and not self._guess:
                p.fillPath(path, t["primary"])
                p.setPen(t["fg_on_accent"])
            elif on:
                p.fillPath(path, t["ctl"])
                pen = QPen(t["primary"], max(1.2, 1.3 * fs), Qt.DashLine)
                p.setPen(pen)
                p.drawPath(path)
                p.setPen(t["primary_text"])
            else:
                p.fillPath(path, t["ctl"])
                p.setPen(t["secondary_text"])
            p.drawText(r, Qt.AlignCenter, rating.WHO_SHORT[who] if who != "not_personal" else "Public")

    def _paint_stars(self, p, t, rects, font) -> None:
        fs = self._fs
        value = self._value
        gold = zone_tones.star()
        zero_v, zero_r = rects[0]
        zero_on = value == 0
        path = QPainterPath()
        path.addRoundedRect(zero_r.adjusted(1, 3 * fs, -1, -3 * fs), 8 * fs, 8 * fs)
        p.setFont(font)
        if zero_on and not self._guess:
            p.fillPath(path, t["secondary_text"])
            p.setPen(t["menu_fill"])
        else:
            pen = QPen(t["muted"], 1, Qt.DashLine if zero_on else Qt.SolidLine)
            p.setPen(pen)
            p.drawPath(path)
            p.setPen(t["primary_text"] if zero_on else t["muted"])
        p.drawText(zero_r, Qt.AlignCenter, "0")
        for v, r in rects[1:]:
            c = r.center()
            star = star_path(c, r.height() * 0.42)
            filled = value is not None and v <= value
            if filled and not self._guess:
                p.fillPath(star, gold)
            elif filled:
                pen = QPen(gold, max(1.2, 1.3 * fs), Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(star)
            else:
                p.setPen(QPen(t["muted"], max(1.0, 1.1 * fs)))
                p.setBrush(Qt.NoBrush)
                p.drawPath(star)
        words = rating.words(self.row, value)
        if words:
            f = QFont(font)
            f.setItalic(True)
            p.setFont(f)
            p.setPen(t["muted"])
            x = rects[-1][1].right() + 8 * fs
            p.drawText(QRectF(x, rects[0][1].top(), self.width() - x, rects[0][1].height()),
                       Qt.AlignLeft | Qt.AlignVCenter, words)
