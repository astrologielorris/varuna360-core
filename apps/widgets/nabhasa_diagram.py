# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Nabhasa yoga "defining combination" diagrams (North + South Indian).
====================================================================
Lightweight QPainter widgets that draw a yoga's DEFINING HOUSE PATTERN (a set of
house numbers 1-12) in the two classical grids, so the user can drag the popup
beside their own chart and compare house-grid to house-grid (spec §5):

  * ``NabhasaHouseDiagram`` draws ONE grid ("north" diamond or "south" square),
    highlighting the pattern's houses. For Vajra/Yava the benefic vs malefic
    houses are tinted differently.
  * ``DualNabhasaDiagram`` stacks both grids side by side with a caption; this is
    what the widget's movable popup embeds.

Theme-reactive: every colour is read LIVE from ``ui/qt_theme.py`` inside
``paintEvent`` (``get_theme_colors`` / ``pari_sem``), so a light<->dark switch
just needs ``refresh_theme()`` (which repaints). NO raw hex, NO pro/ import (H11).
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPolygonF, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout

from ui.qt_theme import get_theme_colors, pari_sem, scaled_px, is_light_theme

# Map a yoga's auspiciousness class to a pari_sem accent key (theme-reactive).
SEM_FOR_AUSPICIOUSNESS = {
    "auspicious": "maha",     # green
    "mixed": "khala",         # amber
    "difficult": "dainya8",   # red
}

# --- North Indian (diamond) geometry, normalized to the unit square ----------
# House 1 is the top-centre kite; numbering runs counterclockwise. The four
# angles (1,4,7,10) are the central kites; the other eight are corner triangles.
_NP = {
    "TL": (0.0, 0.0), "TM": (0.5, 0.0), "TR": (1.0, 0.0),
    "LM": (0.0, 0.5), "C": (0.5, 0.5), "RM": (1.0, 0.5),
    "BL": (0.0, 1.0), "BM": (0.5, 1.0), "BR": (1.0, 1.0),
    "QTL": (0.25, 0.25), "QTR": (0.75, 0.25),
    "QBR": (0.75, 0.75), "QBL": (0.25, 0.75),
}
_NORTH_HOUSES = {
    1: ("QTL", "TM", "QTR", "C"),   # top kite (angle)
    2: ("TL", "TM", "QTL"),
    3: ("TL", "QTL", "LM"),
    4: ("LM", "QTL", "C", "QBL"),   # left kite (angle)
    5: ("LM", "QBL", "BL"),
    6: ("BL", "QBL", "BM"),
    7: ("QBL", "BM", "QBR", "C"),   # bottom kite (angle)
    8: ("BM", "BR", "QBR"),
    9: ("BR", "RM", "QBR"),
    10: ("RM", "QBR", "C", "QTR"),  # right kite (angle)
    11: ("TR", "RM", "QTR"),
    12: ("TR", "QTR", "TM"),
}

# --- South Indian (square) geometry: 12 perimeter cells of a 4x4 grid ---------
# R6 RESOLVED (user feedback 2026-07-14): the South Indian grid is now drawn
#   sign-FIXED (Pisces top-left, clockwise) with houses rotating from the
#   ascendant (see _SOUTH_SIGN_CELLS / _paint_south_signs), matching the app's
#   real South Indian chart view. The abstract house layout below is kept only as
#   a fallback for when no ascendant is supplied.
_SOUTH_CELLS = {
    1: (0, 0), 2: (1, 0), 3: (2, 0), 4: (3, 0),
    5: (3, 1), 6: (3, 2), 7: (3, 3), 8: (2, 3),
    9: (1, 3), 10: (0, 3), 11: (0, 2), 12: (0, 1),
}

# The REAL South Indian chart layout: signs are FIXED (Pisces top-left, running
# clockwise), houses rotate from the ascendant. sign_index (0=Aries .. 11=Pisces)
# -> (col, row) of the 4x4 perimeter. When an ascendant is supplied the South
# grid draws THIS so house 1 lands on the ascendant's sign (e.g. Gemini), instead
# of the abstract house layout above.
_SOUTH_SIGN_CELLS = {
    11: (0, 0), 0: (1, 0), 1: (2, 0), 2: (3, 0),   # Pisces Aries Taurus Gemini
    3: (3, 1), 4: (3, 2), 5: (3, 3),               # Cancer Leo Virgo
    6: (2, 3), 7: (1, 3), 8: (0, 3),               # Libra Scorpio Sagittarius
    9: (0, 2), 10: (0, 1),                         # Capricorn Aquarius
}
_SIGN_ABBR = ("Ar", "Ta", "Ge", "Cn", "Le", "Vi",
              "Li", "Sc", "Sg", "Cp", "Aq", "Pi")


class NabhasaHouseDiagram(QWidget):
    """One themed house grid (north diamond or south square)."""

    def __init__(self, style="north", parent=None):
        super().__init__(parent)
        self._style = style if style in ("north", "south") else "north"
        self._houses = frozenset()
        self._benefic = frozenset()
        self._malefic = frozenset()
        self._sem_key = "neutral"
        self._asc = None               # ascendant sign index (0-11) or None
        side = scaled_px(150)
        self.setMinimumSize(side, side)

    def set_pattern(self, houses, benefic=(), malefic=(), sem_key="neutral",
                    asc_sign_index=None):
        """Set the highlighted house-set. ``benefic``/``malefic`` override the
        single-tint highlight for split shapes (Vajra/Yava). When
        ``asc_sign_index`` (0-11) is given, the South grid is drawn sign-fixed
        (real South Indian chart) with house 1 on the ascendant's sign."""
        self._houses = frozenset(int(h) for h in houses)
        self._benefic = frozenset(int(h) for h in benefic)
        self._malefic = frozenset(int(h) for h in malefic)
        self._sem_key = sem_key or "neutral"
        self._asc = (int(asc_sign_index)
                     if asc_sign_index is not None and int(asc_sign_index) >= 0
                     else None)
        self.update()

    def refresh_theme(self):
        self.update()

    # -- painting -----------------------------------------------------------
    def _square_rect(self):
        """Largest centred square inside the widget, with a small margin."""
        w, h = self.width(), self.height()
        side = max(10, min(w, h) - scaled_px(6))
        x = (w - side) / 2.0
        y = (h - side) / 2.0
        return QRectF(x, y, side, side)

    def _fill_for(self, house, base_hi):
        """Highlight colour for an occupied house (benefic/malefic aware). A house
        that holds BOTH a benefic and a malefic karaka is drawn mixed (amber) so
        the cruel occupancy is not hidden behind the benefic tint."""
        in_ben = house in self._benefic
        in_mal = house in self._malefic
        if in_ben and in_mal:
            c = QColor(pari_sem("khala")["hi"])   # mixed: gentle + cruel share it
        elif in_ben:
            c = QColor(pari_sem("maha")["hi"])
        elif in_mal:
            c = QColor(pari_sem("dainya8")["hi"])
        else:
            c = QColor(base_hi)
        c.setAlpha(150 if is_light_theme() else 120)
        return c

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        theme = get_theme_colors()
        line = QColor(theme["primary_text"])
        line.setAlpha(150)
        pen = QPen(line, max(1, scaled_px(1)))
        p.setPen(pen)

        sem = pari_sem(self._sem_key)
        base_hi = sem["hi"]
        rect = self._square_rect()

        font = QFont()
        font.setPixelSize(max(7, scaled_px(9)))
        p.setFont(font)
        text_col = QColor(theme["primary_text"])

        if self._style == "north":
            self._paint_north(p, rect, pen, base_hi, text_col)
        else:
            self._paint_south(p, rect, pen, base_hi, text_col)
        p.end()

    def _to_px(self, rect, key):
        nx, ny = _NP[key]
        return QPointF(rect.x() + nx * rect.width(),
                       rect.y() + ny * rect.height())

    def _paint_north(self, p, rect, pen, base_hi, text_col):
        for house, keys in _NORTH_HOUSES.items():
            poly = QPolygonF([self._to_px(rect, k) for k in keys])
            if house in self._houses:
                p.setBrush(QBrush(self._fill_for(house, base_hi)))
            else:
                p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            p.drawPolygon(poly)
            # house number at the polygon centroid
            cx = sum(pt.x() for pt in poly) / poly.count()
            cy = sum(pt.y() for pt in poly) / poly.count()
            p.setPen(QPen(text_col))
            p.drawText(QRectF(cx - 10, cy - 8, 20, 16),
                       Qt.AlignCenter, str(house))

    def _paint_south(self, p, rect, base_pen, base_hi, text_col):
        cell = rect.width() / 4.0
        if self._asc is not None:
            self._paint_south_signs(p, rect, cell, base_pen, base_hi, text_col)
        else:
            # Fallback: the abstract house layout (house 1 top-left, clockwise),
            # used only when no ascendant is supplied.
            for house, (col, row) in _SOUTH_CELLS.items():
                r = QRectF(rect.x() + col * cell, rect.y() + row * cell, cell, cell)
                p.setBrush(QBrush(self._fill_for(house, base_hi))
                           if house in self._houses else Qt.NoBrush)
                p.setPen(base_pen)
                p.drawRect(r)
                p.setPen(QPen(text_col))
                p.drawText(r, Qt.AlignCenter, str(house))
        # outline of the inner blank block for a clean frame
        inner = QRectF(rect.x() + cell, rect.y() + cell, 2 * cell, 2 * cell)
        p.setBrush(Qt.NoBrush)
        p.setPen(base_pen)
        p.drawRect(inner)

    def _paint_south_signs(self, p, rect, cell, base_pen, base_hi, text_col):
        """Real South Indian grid: signs fixed (Pisces top-left, clockwise),
        houses rotate from the ascendant so house 1 sits on the ascendant sign."""
        asc = self._asc
        theme = get_theme_colors()
        asc_pen = QPen(QColor(pari_sem("maha")["hi"]), max(2, scaled_px(2)))
        for sign, (col, row) in _SOUTH_SIGN_CELLS.items():
            r = QRectF(rect.x() + col * cell, rect.y() + row * cell, cell, cell)
            house = (sign - asc) % 12 + 1
            p.setBrush(QBrush(self._fill_for(house, base_hi))
                       if house in self._houses else Qt.NoBrush)
            # The ascendant sign (house 1) gets an accent border so the reader
            # sees where the chart "starts" (e.g. Gemini, not Pisces).
            p.setPen(asc_pen if house == 1 else base_pen)
            p.drawRect(r)
            # Two lines: the fixed sign abbreviation, then the house number.
            p.setPen(QPen(text_col))
            top = QRectF(r.x(), r.y() + scaled_px(2), r.width(), r.height() / 2.0)
            bot = QRectF(r.x(), r.y() + r.height() / 2.0 - scaled_px(2),
                         r.width(), r.height() / 2.0)
            p.drawText(top, Qt.AlignCenter, _SIGN_ABBR[sign])
            tag = "Asc" if house == 1 else str(house)
            p.drawText(bot, Qt.AlignCenter, tag)


class DualNabhasaDiagram(QWidget):
    """North + South Indian grids side by side with a caption (popup body)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._north = NabhasaHouseDiagram("north", self)
        self._south = NabhasaHouseDiagram("south", self)

        self._title = QLabel("", self)
        self._title.setAlignment(Qt.AlignCenter)
        self._caption = QLabel("", self)
        self._caption.setAlignment(Qt.AlignCenter)
        self._caption.setWordWrap(True)

        grids = QHBoxLayout()
        grids.setContentsMargins(0, 0, 0, 0)
        grids.addWidget(self._north, 1)
        grids.addWidget(self._south, 1)

        lay = QVBoxLayout(self)
        m = scaled_px(6)
        lay.setContentsMargins(m, m, m, m)
        lay.addWidget(self._title)
        lay.addLayout(grids, 1)
        lay.addWidget(self._caption)
        self.refresh_theme()

    def set_yoga(self, title, houses, caption="", benefic=(), malefic=(),
                 auspiciousness="mixed", asc_sign_index=None):
        sem_key = SEM_FOR_AUSPICIOUSNESS.get(auspiciousness, "neutral")
        self._title.setText(title)
        self._caption.setText(caption)
        # North Indian is house-fixed (ascendant-independent); South Indian is
        # sign-fixed, so it needs the ascendant to place the houses.
        self._north.set_pattern(houses, benefic, malefic, sem_key)
        self._south.set_pattern(houses, benefic, malefic, sem_key,
                                asc_sign_index=asc_sign_index)
        self.refresh_theme()

    def refresh_theme(self):
        theme = get_theme_colors()
        title_px = max(10, scaled_px(12))
        cap_px = max(8, scaled_px(9))
        self._title.setStyleSheet(
            f"color:{theme['primary_text']}; font-weight:bold; "
            f"font-size:{title_px}px;")
        self._caption.setStyleSheet(
            f"color:{theme['secondary_text']}; font-size:{cap_px}px;")
        self._north.refresh_theme()
        self._south.refresh_theme()
