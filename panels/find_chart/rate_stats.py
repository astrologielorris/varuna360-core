# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Rate and Sort's summary and statistics (SPEC-LIB-002 §4.3, §4.11).

``SessionRing``: Night Orbit's ring. An inner ring split into one arc per
chart of this visit (the zone tone when rated, hatched when skipped, a
dashed outline for the current one), inside a thin outer ring for the share
of the library with a confirmed rating; "2 / 5" and "TODAY" in the centre.
``set_visit(states, current)``: ``states`` per arc ``("rated", zone)``,
``("skipped", None)`` or ``("open", None)``; ``set_library(fraction)``.

``ZoneTile``: Library Atlas's tile, a ring (confirmed share), the count, the
label and "n confirmed · m guessed". ``ZoneTiles`` holds PRIVATE, MIXED,
PUBLIC and UNRATED; ``set_stats(overview)`` reads ``core.library.stats.overview``.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from core.library import rating
from panels.find_chart import kit, zone_tones


class SessionRing(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._arcs: list[tuple[str, object]] = []
        self._current = -1
        self._library = 0.0
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        d = round(64 * kit.area_fs("info_text"))
        self.setFixedSize(d, d)

    def set_visit(self, arcs, current: int) -> None:
        self._arcs, self._current = list(arcs), current
        self.update()

    def set_library(self, fraction: float) -> None:
        self._library = max(0.0, min(1.0, fraction))
        self.update()

    def centre_text(self) -> str:
        done = sum(1 for s, _z in self._arcs if s in ("rated", "skipped"))
        return f"{done} / {len(self._arcs)}"

    def paintEvent(self, _event):
        t = kit.tokens()
        fs = kit.area_fs("info_text")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        outer_w = max(2.0, 2.5 * fs)
        p.setPen(QPen(t["recess"], outer_w))
        p.drawEllipse(r)
        if self._library > 0:
            pen = QPen(t["primary"], outer_w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, -round(self._library * 360 * 16))
        inner_w = max(4.0, 6 * fs)
        inner = r.adjusted(outer_w + inner_w, outer_w + inner_w, -outer_w - inner_w,
                           -outer_w - inner_w)
        n = max(1, len(self._arcs))
        gap = 6 if n > 1 else 0
        span = 360 / n
        for i in range(n):
            state, zone = self._arcs[i] if i < len(self._arcs) else ("open", None)
            start = 90 - i * span - gap / 2
            length = -(span - gap)
            if state == "rated":
                pen = QPen(zone_tones.tone(zone), inner_w)
            elif state == "skipped":
                pen = QPen(QBrush(t["muted"], Qt.BDiagPattern), inner_w)
            else:
                pen = QPen(t["recess"], inner_w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(inner, round(start * 16), round(length * 16))
            if i == self._current and state == "open":
                dash = QPen(t["primary"], max(1.0, 1.2 * fs), Qt.DashLine)
                p.setPen(dash)
                p.drawArc(inner.adjusted(-inner_w / 2, -inner_w / 2, inner_w / 2, inner_w / 2),
                          round(start * 16), round(length * 16))
        f = QFont(self.font())
        f.setPixelSize(max(10, round(14 * fs)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(t["primary_text"])
        mid = QRectF(r.left(), r.center().y() - 11 * fs, r.width(), 15 * fs)
        p.drawText(mid, Qt.AlignCenter, self.centre_text())
        f.setPixelSize(max(7, round(8 * fs)))
        f.setBold(False)
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        p.setFont(f)
        p.setPen(t["muted"])
        p.drawText(QRectF(r.left(), mid.bottom(), r.width(), 11 * fs), Qt.AlignCenter, "TODAY")
        p.end()


class ZoneTile(QWidget):
    def __init__(self, zone: str, parent=None) -> None:
        super().__init__(parent)
        self.zone = zone          # PRIVATE, MIXED, PUBLIC or "UNRATED"
        self._count = 0
        self._fraction = 0.0
        self._line = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        self.setFixedHeight(round(58 * kit.area_fs("info_text")))

    def sizeHint(self) -> QSize:
        return QSize(round(84 * kit.area_fs("info_text")), self.height())

    def set_values(self, count: int, fraction: float, line: str) -> None:
        self._count, self._fraction, self._line = count, max(0.0, min(1.0, fraction)), line
        self.setToolTip(line)
        self.update()

    def paintEvent(self, _event):
        t = kit.tokens()
        fs = kit.area_fs("info_text")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        tone = zone_tones.tone(self.zone) if self.zone in zone_tones._LIGHT else t["secondary_text"]
        p.setPen(QPen(t["hair_soft"], 1))
        p.setBrush(zone_tones.cell(self.zone) if self.zone in zone_tones._LIGHT else t["ctl"])
        p.drawRoundedRect(box, 6 * fs, 6 * fs)
        d = 18 * fs
        ring = QRectF(box.right() - d - 6 * fs, box.top() + 6 * fs, d, d)
        w = max(2.0, 3 * fs)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(t["recess"], w))
        p.drawEllipse(ring)
        if self._fraction > 0:
            pen = QPen(tone, w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, -round(self._fraction * 360 * 16))
        f = QFont(self.font())
        f.setPixelSize(max(10, round(15 * fs)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(tone)
        x = box.left() + 7 * fs
        p.drawText(QRectF(x, box.top() + 4 * fs, box.width(), 20 * fs),
                   Qt.AlignLeft | Qt.AlignVCenter, f"{self._count:,}")
        f.setPixelSize(max(7, round(8.5 * fs)))
        f.setLetterSpacing(QFont.PercentageSpacing, 108)
        p.setFont(f)
        p.drawText(QRectF(x, box.top() + 24 * fs, box.width(), 12 * fs),
                   Qt.AlignLeft | Qt.AlignVCenter, self.zone)
        f.setBold(False)
        f.setLetterSpacing(QFont.PercentageSpacing, 100)
        p.setFont(f)
        p.setPen(t["muted"])
        p.drawText(QRectF(x, box.top() + 37 * fs, box.width() - 9 * fs, 14 * fs),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self._line, Qt.ElideRight,
                                              round(box.width() - 12 * fs)))
        p.end()


class ZoneTiles(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tiles = {z: ZoneTile(z) for z in (rating.PRIVATE, rating.MIXED, rating.PUBLIC,
                                               "UNRATED")}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(round(5 * kit.area_fs("info_text")))
        for tile in self.tiles.values():
            lay.addWidget(tile, 1)

    def set_stats(self, s: dict) -> None:
        for z in (rating.PRIVATE, rating.MIXED, rating.PUBLIC):
            c, g = s["zones"][z]["confirmed"], s["zones"][z]["guessed"]
            self.tiles[z].set_values(c + g, c / (c + g) if c + g else 0.0,
                                     f"{c:,} confirmed · {g:,} guessed")
        total = s["charts"]
        self.tiles["UNRATED"].set_values(s["unrated"], s["rated"] / total if total else 0.0,
                                         f"{s['rated']:,} of {total:,} rated")

    def refresh_metrics(self) -> None:
        self.layout().setSpacing(round(5 * kit.area_fs("info_text")))
        for tile in self.tiles.values():
            tile.refresh_metrics()
            tile.update()
