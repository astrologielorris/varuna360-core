# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The EXCH panel parts of the exchange chain (SPEC-EXCH-002 §4.1 A, td-m79zy).

The metal RANK bookmark tag of an exchange card, the short chain swatch of its
tie row, the EXCHANGE SCALE ladder (6 metal seals, this chart's exchanges as
house-pair chips on their rows) and the legend shown by the THREAD key's "?".
All painted with the chart's own code (``exchange_chain_paint``), so the panel
and the chart show the same metal. Theme tokens for every surface (Rule 20);
the rank metals are the semantic palette. Every string through ``t()``.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPicture
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from AI_tools.AI_main_function.interchange_rank import (RANK_LINES, RANK_WORDS, exchange_rank,
                                                         house_marks)
from core import exchange_chain as xc
from core.i18n import t
from apps.widgets import exchange_chain_paint as xp
from ui.qt_theme import dim_text, elevation_color, get_theme_colors, is_light_theme, scaled_px


# ---------------------------------------------------------------- wording
def rank_word(rank):
    return t(f"panel.exchange.rank.{rank}.word", RANK_WORDS[rank])


def rank_line(rank):
    return t(f"panel.exchange.rank.{rank}.line", RANK_LINES[rank])


def metal_name(rank):
    names = {6: t("panel.exchange.metal.6", "polished gold"),
             5: t("panel.exchange.metal.5", "sterling silver"),
             4: t("panel.exchange.metal.4", "bronze"),
             3: t("panel.exchange.metal.3", "tarnished pewter"),
             2: t("panel.exchange.metal.2", "rusted iron"),
             1: t("panel.exchange.metal.1", "rusted broken iron")}
    return names[rank]


def thread_label():
    return t("panel.exchange.thread", "THREAD")


def thread_tip():
    # SPEC-VAC-001 D-11: the chains step aside while a center drawing (Tajika or Vedic)
    # holds the South Indian center.
    return "\n".join((t("panel.exchange.thread_tip", "Draws every exchange as a metal chain "
                        "between its two signs. The metal tells the rank."),
                      t("panel.exchange.thread_held", "Hidden while aspects are drawn in "
                        "the center")))


def ladder_tip():
    return t("panel.exchange.scale_tip", "Where each exchange sits, from 1 most difficult to 6 "
             "very good. Rank from the two houses. Each rank has its metal.")


def legend_text():
    return t("panel.exchange.legend",
             "Exchange chain. Two planets each sit in the sign the other one rules, so the "
             "two houses are chained together. The metal tells how the exchange works out, "
             "from gold (very good) to broken rusted iron (most difficult). Marks on the chain "
             "name the hard houses: craters in the metal for the 6th (illness), a chain that "
             "fades out toward the 12th house (loss), crushed rings and a lightning hazard "
             "sign for the 8th (sudden chaos), and a snapped open ring for the worst exchange. "
             "The knot names the two houses and carries the rank number; the dark discs show "
             "the partner planet, at home in the sign it rules.")


def note_12th():
    return t("panel.exchange.note_12th", "12th: with some houses it can also give spirituality.")


def rank_word_colour(rank):
    """The rank word under a card header: the metal shadow tone on a light theme
    (#6B5320 on gold and silver, for contrast), the light tone on a dark one."""
    m = xc.METAL[rank]
    if is_light_theme():
        return xc.WORD_ON_LIGHT if rank >= 5 else m.dk
    return m.li


# ---------------------------------------------------------------- the tag
class RankTag(QWidget):
    """The bookmark RANK tag hanging at the top right of an exchange card."""

    def __init__(self, rank, parent=None):
        super().__init__(parent)
        self.rank = int(rank)
        self.setFixedSize(scaled_px(36), scaled_px(48))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setToolTip(t("panel.exchange.rank_tip", "Rank {rank} of 6: {word}, {metal}",
                          rank=self.rank, word=rank_word(self.rank), metal=metal_name(self.rank)))

    def paintEvent(self, _e):
        p = QPainter(self)
        xp.rank_tag(p, QRectF(self.rect()), self.rank, t("panel.exchange.rank_word", "RANK"))
        p.end()


# ---------------------------------------------------------------- the swatch
class ChainSwatch(QWidget):
    """A short straight chain between the two phantom pins (the tie row), or a
    bare mini chain (the legend). Recorded once into a QPicture."""

    def __init__(self, rank, house_a, house_b, pins=None, seed=1, width=100, height=26,
                 parent=None):
        super().__init__(parent)
        self.rank = int(rank)
        self._marks = house_marks(house_a, house_b, self.rank)
        self._end8 = 0 if house_a == 8 else 1
        self._end12 = 0 if house_a == 12 else 1
        self._pins = pins
        self._seed = seed
        self._w, self._h = width, height
        self._pic = None
        self._style = None
        self.setFixedSize(QSize(width, height))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _record(self, style):
        pic = QPicture()
        p = QPainter(pic)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self._w, self._h
        pad = h / 2 if self._pins else 6
        P = xc.Poly([(pad + 2, h / 2), (w - pad - 2, h / 2)])
        o = xc.ChainOpts(self.rank, .42 * h / 26, self._marks, self._end8, self._end12,
                         self._seed, False, True, style, h / 26)
        xp.paint_chain(p, P, o)
        if self._pins:
            m = xc.METAL[self.rank]
            from apps.widgets.exchange_chain_items import GLYPHS
            r = 9.5 * h / 26
            xp.pin(p, h / 2 - 1, h / 2, GLYPHS.get(self._pins[0], ""), m.li, r)
            xp.pin(p, w - h / 2 + 1, h / 2, GLYPHS.get(self._pins[1], ""), m.li, r)
        p.end()
        return pic

    def paintEvent(self, _e):
        from managers.settings_manager import get_settings
        style = xc.chain_style(get_settings().get)
        if self._pic is None or style != self._style:
            self._pic, self._style = self._record(style), style
        p = QPainter(self)
        p.drawPicture(0, 0, self._pic)
        p.end()


# ---------------------------------------------------------------- the ladder
class ScaleLadder(QWidget):
    """The EXCHANGE SCALE: six rows, 6 on top, seals on a grey rail; rows holding
    an exchange of the chart are raised with a chip "10 ⟷ 11" (letter first
    when the chart has 2 or 3 exchanges)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hits = {}                  # rank -> [(letter, house_a, house_b)]
        self.setToolTip(ladder_tip())

    def set_exchanges(self, rows):
        """``rows``: [(rank, letter, house_a, house_b)]."""
        self._hits = {}
        for rank, letter, ha, hb in rows:
            self._hits.setdefault(int(rank), []).append((letter, ha, hb))
        self.updateGeometry()
        self.update()

    def hits(self):
        return dict(self._hits)

    def _metrics(self):
        row = scaled_px(30)
        end = scaled_px(14)
        return row, end

    def sizeHint(self):
        row, end = self._metrics()
        return QSize(scaled_px(300), 6 * row + 2 * end + scaled_px(4))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _e):
        th = get_theme_colors()
        text = QColor(th["secondary_text"])
        muted = QColor(text)
        muted.setAlphaF(.62)
        row, end = self._metrics()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        seal_r = row * .40
        x_seal = seal_r + scaled_px(3)
        small = QFont(self.font())
        small.setPixelSize(max(8, scaled_px(9)))
        small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, .6)
        p.setFont(small)
        p.setPen(muted)
        p.drawText(QRectF(x_seal * 2 + scaled_px(4), 0, w, end), Qt.AlignmentFlag.AlignVCenter,
                   t("panel.exchange.scale_top", "MORE BENEFICIAL"))
        top = end
        rail = QColor(th["secondary_light"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rail)
        p.drawRect(QRectF(x_seal - 1, top + row / 2, 2, 5 * row))
        word_f = QFont(self.font())
        word_f.setPixelSize(scaled_px(11))
        word_f.setBold(True)
        line_f = QFont(self.font())
        line_f.setPixelSize(max(8, scaled_px(9)))
        chip_f = QFont(self.font())
        chip_f.setPixelSize(max(8, scaled_px(9)))
        chip_f.setWeight(QFont.Weight.ExtraBold)
        for j, rank in enumerate(range(6, 0, -1)):
            y = top + j * row
            hits = self._hits.get(rank, [])
            if hits:
                p.setPen(QColor(th["secondary_light"]))
                p.setBrush(QColor(elevation_color(3)))
                p.drawRoundedRect(QRectF(1, y + 1, w - 2, row - 2), scaled_px(8), scaled_px(8))
            xp.seal(p, rank, x_seal, y + row / 2, seal_r)
            tx = x_seal * 2 + scaled_px(4)
            chips_w = 0.0
            p.setFont(chip_f)
            fm = p.fontMetrics()
            chip_texts = [(lt, f"{ha} ⟷ {hb}") for lt, ha, hb in hits]
            for lt, txt in reversed(chip_texts):
                tw = fm.horizontalAdvance(txt) + scaled_px(12) + (scaled_px(17) if lt else 0)
                cr = QRectF(w - scaled_px(6) - chips_w - tw, y + row * .2, tw, row * .6)
                chips_w += tw + scaled_px(4)
                p.setPen(xp._pen(QColor(xc.METAL[rank].ba), 2))
                p.setBrush(QColor("#2E251B"))
                p.drawRoundedRect(cr, scaled_px(7), scaled_px(7))
                x0 = cr.left() + scaled_px(6)
                if lt:
                    sq = QRectF(x0, cr.center().y() - scaled_px(7), scaled_px(14), scaled_px(14))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor("#F3E9D6"))
                    p.drawRoundedRect(sq, scaled_px(3), scaled_px(3))
                    p.setPen(QColor("#2E251B"))
                    p.drawText(sq, Qt.AlignmentFlag.AlignCenter, lt)
                    x0 += scaled_px(17)
                p.setPen(QColor("#F3E9D6"))
                p.drawText(QRectF(x0, cr.top(), cr.right() - x0, cr.height()),
                           Qt.AlignmentFlag.AlignVCenter, txt)
            avail = w - tx - chips_w - scaled_px(8)
            p.setPen(text)
            p.setFont(word_f)
            p.drawText(QRectF(tx, y + row * .06, avail, row * .5),
                       Qt.AlignmentFlag.AlignBottom, rank_word(rank))
            p.setPen(muted)
            p.setFont(line_f)
            line = p.fontMetrics().elidedText(rank_line(rank), Qt.TextElideMode.ElideRight,
                                              int(max(0, avail)))
            p.drawText(QRectF(tx, y + row * .54, avail, row * .42), Qt.AlignmentFlag.AlignTop, line)
        p.setFont(small)
        p.setPen(muted)
        p.drawText(QRectF(x_seal * 2 + scaled_px(4), top + 6 * row, w, end),
                   Qt.AlignmentFlag.AlignVCenter, t("panel.exchange.scale_bottom", "MORE DIFFICULT"))
        p.end()


# ---------------------------------------------------------------- the legend
_LEGEND_SAMPLES = {6: (3, 9), 5: (3, 9), 4: (3, 9), 3: (3, 6), 2: (8, 3), 1: (6, 8)}


class ChainLegend(QFrame):
    """The help of the THREAD key's "?": the legend text and a mini chain per rank
    (a tooltip window, shown while the pointer is on the "?")."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        th = get_theme_colors()
        self.setObjectName("chainLegend")
        self.setStyleSheet(
            f"QFrame#chainLegend {{ background: {elevation_color(3)}; "
            f"border: 1px solid {th['secondary_light']}; border-radius: {scaled_px(8)}px; }}"
            f"QLabel {{ color: {th['secondary_text']}; background: transparent; "
            f"font-size: {scaled_px(11)}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(scaled_px(12), scaled_px(10), scaled_px(12), scaled_px(10))
        body = QLabel(legend_text())
        body.setWordWrap(True)
        body.setMaximumWidth(scaled_px(420))
        lay.addWidget(body)
        grid = QGridLayout()
        grid.setHorizontalSpacing(scaled_px(8))
        grid.setVerticalSpacing(scaled_px(2))
        for j, rank in enumerate(range(6, 0, -1)):
            ha, hb = _LEGEND_SAMPLES[rank]
            sw = ChainSwatch(rank, ha, hb, None, seed=rank * 3, width=scaled_px(70),
                             height=scaled_px(22))
            grid.addWidget(sw, j, 0)
            grid.addWidget(QLabel(t("panel.exchange.legend_row", "{rank} {word}, {metal}",
                                    rank=rank, word=rank_word(rank), metal=metal_name(rank))), j, 1)
        lay.addLayout(grid)

    def show_near(self, widget):
        self.adjustSize()
        pos = widget.mapToGlobal(QPointF(0, widget.height()).toPoint())
        self.move(pos.x() - self.width() + widget.width(), pos.y() + scaled_px(4))
        self.show()


def legend_rows(records, letters):
    """Ladder rows [(rank, letter, house_a, house_b)] from ordered 7-tuples."""
    return [(exchange_rank(r[2], r[5], r[6]), lt, r[2], r[5]) for r, lt in zip(records, letters)]


def dim_style_text(alpha=.7):
    return dim_text(get_theme_colors()["secondary_text"], alpha)
