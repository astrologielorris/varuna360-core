# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The closeness-by-fame plane (SPEC-LIB-002 §4.5, Constellation Desk).

A 7 x 6 grid: columns are row 1 (Family .. Follow, then Not personal, drawn
wider), rows are row 2 (How known, 0 at the bottom to 5 at the top). Cells
are tinted by zone. One click on a cell sets rows 1 and 2 together
(``picked(who, known)``); arrow keys move the point while the plane has focus.
The current chart is a dashed ring with "?" while rows 1 and 2 are guesses,
a solid dot with a check once they are the user's (INV-1). Charts rated in
this visit stay as small faint dots.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.library import rating
from panels.find_chart import kit, zone_tones

COLUMNS = rating.WHO
_WIDE = 1.6  # the Not personal column


class RatePlane(QWidget):
    picked = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._point = None       # (who, known) or None
        self._confirmed = False
        self._trail: list[tuple[str, int]] = []
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("Who this person is to you, by how known")
        self.refresh_metrics()

    # ---------------------------------------------------------- state
    def set_point(self, who, known, confirmed: bool) -> None:
        self._point = (who, known) if who in COLUMNS and known is not None else None
        self._confirmed = bool(confirmed) and self._point is not None
        self.update()

    def set_trail(self, points) -> None:
        self._trail = [(w, k) for w, k in points if w in COLUMNS and k is not None]
        self.update()

    def point(self):
        return self._point

    def is_confirmed(self) -> bool:
        return self._confirmed

    # ---------------------------------------------------------- geometry
    def refresh_metrics(self) -> None:
        fs = kit.area_fs("info_text")
        self._cell_h = round(17 * fs)
        self._axis_w = round(16 * fs)
        self._label_h = round(16 * fs)
        self.setFixedHeight(6 * self._cell_h + self._label_h + 2)
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(round(300 * kit.area_fs("info_text")), self.height())

    def _columns(self) -> list[tuple[float, float]]:
        """(x, width) of each column."""
        units = len(COLUMNS) - 1 + _WIDE
        unit = (self.width() - self._axis_w - 1) / units
        out, x = [], float(self._axis_w)
        for who in COLUMNS:
            w = unit * (_WIDE if who == "not_personal" else 1)
            out.append((x, w))
            x += w
        return out

    def cell_rect(self, who: str, known: int) -> QRectF:
        x, w = self._columns()[COLUMNS.index(who)]
        y = (5 - known) * self._cell_h
        return QRectF(x, y, w, self._cell_h)

    def cell_at(self, pos) -> tuple[str, int] | None:
        if pos.y() < 0 or pos.y() >= 6 * self._cell_h:
            return None
        known = 5 - int(pos.y() // self._cell_h)
        for who, (x, w) in zip(COLUMNS, self._columns()):
            if x <= pos.x() < x + w:
                return who, known
        return None

    # ---------------------------------------------------------- input
    def setEnabled(self, on: bool) -> None:  # noqa: N802 - Qt name
        super().setEnabled(on)
        self.update()

    def mousePressEvent(self, e):
        hit = self.cell_at(e.position())
        if hit and self.isEnabled():
            self.setFocus(Qt.MouseFocusReason)
            self.picked.emit(*hit)

    def keyPressEvent(self, e):
        moves = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, 1),
                 Qt.Key_Down: (0, -1)}
        if e.key() in moves and self.isEnabled():
            who, known = self._point or ("not_personal", 0)
            dx, dy = moves[e.key()]
            i = max(0, min(len(COLUMNS) - 1, COLUMNS.index(who) + dx))
            self.picked.emit(COLUMNS[i], max(0, min(5, known + dy)))
            e.accept()
            return
        super().keyPressEvent(e)

    # ---------------------------------------------------------- paint
    def paintEvent(self, _event):
        t = kit.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fs = kit.area_fs("info_text")
        small = QFont(self.font())
        small.setPixelSize(max(8, round(9 * fs)))
        p.setFont(small)
        # cells
        for who in COLUMNS:
            for known in range(6):
                r = self.cell_rect(who, known)
                z = rating.zone(who, known)
                p.fillRect(r.adjusted(0.5, 0.5, -0.5, -0.5), zone_tones.cell(z))
        # grid lines
        p.setPen(QPen(t["hair_soft"], 1))
        cols = self._columns()
        for x, _w in cols[1:]:
            p.drawLine(QPointF(x, 0), QPointF(x, 6 * self._cell_h))
        for k in range(1, 6):
            p.drawLine(QPointF(self._axis_w, k * self._cell_h),
                       QPointF(self.width() - 1, k * self._cell_h))
        # zone labels
        bold = QFont(small)
        bold.setBold(True)
        bold.setLetterSpacing(QFont.PercentageSpacing, 108)
        p.setFont(bold)
        pad = 3 * fs
        for z, who, known, align in ((rating.PRIVATE, "family", 1, Qt.AlignLeft | Qt.AlignBottom),
                                     (rating.MIXED, "family", 5, Qt.AlignLeft | Qt.AlignTop),
                                     (rating.PUBLIC, "not_personal", 5, Qt.AlignRight | Qt.AlignTop)):
            r = self.cell_rect(who, known).adjusted(pad, 1, -pad, -1)
            if who == "family":
                r.setRight(self.cell_rect("short_friend", known).right())
            p.setPen(zone_tones.tone(z))
            p.drawText(r, align, z)
        # axis and column labels
        p.setFont(small)
        p.setPen(t["muted"])
        for k in range(6):
            r = QRectF(0, (5 - k) * self._cell_h, self._axis_w - 3, self._cell_h)
            p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, str(k))
        for who, (x, w) in zip(COLUMNS, cols):
            r = QRectF(x, 6 * self._cell_h + 1, w, self._label_h)
            on = self._point is not None and self._point[0] == who
            p.setPen(t["primary_text"] if on else t["muted"])
            p.drawText(r, Qt.AlignCenter, rating.WHO_SHORT[who])
        # trail
        for who, known in self._trail:
            c = self.cell_rect(who, known).center()
            col = zone_tones.tone(rating.zone(who, known))
            col.setAlphaF(0.45)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(c, 3 * fs, 3 * fs)
        # current point (INV-1: one painter decides both looks)
        if self._point is not None:
            who, known = self._point
            c = self.cell_rect(who, known).center()
            col = zone_tones.tone(rating.zone(who, known))
            rad = min(self._cell_h * 0.42, 7.5 * fs)
            if self._confirmed:
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawEllipse(c, rad, rad)
                tick = QPainterPath(QPointF(c.x() - rad * 0.45, c.y()))
                tick.lineTo(c.x() - rad * 0.1, c.y() + rad * 0.38)
                tick.lineTo(c.x() + rad * 0.5, c.y() - rad * 0.4)
                pen = QPen(t["fg_on_accent"], max(1.5, 1.6 * fs))
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(tick)
            else:
                pen = QPen(col, max(1.2, 1.3 * fs), Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, rad, rad)
                p.setPen(col)
                p.drawText(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), Qt.AlignCenter, "?")
        if self.hasFocus():
            p.setPen(QPen(t["primary"], 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self._axis_w, 0, self.width() - self._axis_w - 1,
                              6 * self._cell_h).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()
