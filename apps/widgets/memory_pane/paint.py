# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Shared painting for the memory pane: fonts, recessed surfaces, glass.

The hairline, recess and glow primitives are the action bar's own
(apps/widgets/action_bar/paint_surfaces.py), so the pane and the bar under it
are drawn by the same code and cannot drift apart. Colours come in from
``tokens.pane_tokens()`` only.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath

from apps.widgets.action_bar.paint_controls import icon_pixmap
from apps.widgets.action_bar.paint_surfaces import (
    _inner_shadow, draw_inset_hairline, hairline_coverage, hairline_width,
    snap_to_device, soft_glow)

from ui.qt_theme import scaled_area_factor

# Qt names the weights it has; the mockup's in-between CSS weights map to the
# nearest face the app font ships.
_WEIGHTS = ((450, QFont.Weight.Normal), (560, QFont.Weight.Medium),
            (660, QFont.Weight.DemiBold), (10_000, QFont.Weight.Bold))


def _weight(css: int) -> QFont.Weight:
    for limit, w in _WEIGHTS:
        if css < limit:
            return w
    return QFont.Weight.Bold


def area_factor(area: str) -> float:
    """The font area's size against its default (1.0 at defaults)."""
    try:
        return max(0.5, float(scaled_area_factor(area)))
    except Exception:
        return 1.0


def area_qss(area: str, design_px: float) -> str:
    """QSS that gives a painted widget its font size (setFont is inert under
    qt-material); ``font()`` then reports the area's live size to tests."""
    return "font-size: %dpx;" % max(5, round(design_px * area_factor(area)))


def design_font(widget, design_px: float, css_weight: int = 500,
                spacing_em: float = 0.0, area: str = "buttons",
                caps: bool = False) -> QFont:
    """A painter font at the mockup's fractional px, scaled by the font area."""
    f = QFont(widget.font())
    px = design_px * area_factor(area)
    dpi = widget.logicalDpiY() or 96
    f.setPointSizeF(max(4.0, px * 72.0 / dpi))
    f.setWeight(_weight(css_weight))
    if spacing_em:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * spacing_em)
    # qt-material's QPushButton rule uppercases the widget font; the painter
    # decides case itself.
    f.setCapitalization(QFont.Capitalization.AllUppercase if caps
                        else QFont.Capitalization.MixedCase)
    return f


def cap_baseline(font: QFont, top: float, height: float) -> float:
    """Baseline that centres the CAPITALS of ``font`` in [top, top+height].

    ``AlignVCenter`` centres the font's whole line box (ascent + descent),
    which puts capitals a pixel or more below the middle; the eye centres
    on the caps (Lorris, 2026-10-22: labels "too low")."""
    fm = QFontMetricsF(font)
    return top + (height + fm.capHeight()) / 2.0


def text_width(font: QFont, text: str) -> float:
    """Ink width of ``text``: the advance minus the letter spacing Qt also
    adds after the last glyph (so tracked labels centre truly)."""
    if not text:
        return 0.0
    w = QFontMetricsF(font).horizontalAdvance(text)
    if font.letterSpacingType() == QFont.SpacingType.AbsoluteSpacing:
        w -= font.letterSpacing()
    return max(0.0, w)


def rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, min(radius, rect.width() / 2.0, rect.height() / 2.0))
    path.addRoundedRect(rect, r, r)
    return path


def dpr_of(widget) -> float:
    try:
        return float(widget.devicePixelRatioF()) or 1.0
    except Exception:
        return 1.0


def paint_recess(p: QPainter, rect: QRectF, radius: float, fill, line,
                 shade, dpr: float) -> None:
    """A recessed surface: fill + ``inset 0 1px 2.5px`` shade + 0.5 px rim."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = rounded(rect, radius)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)
    _inner_shadow(p, path, rect, shade)
    draw_inset_hairline(p, rect, radius, line, dpr)


def paint_drop(p: QPainter, rect: QRectF, radius: float, color: QColor) -> None:
    """``0 .5px 1.5px <color>`` drop, two soft rings (the D-pad's technique)."""
    p.setPen(Qt.PenStyle.NoPen)
    for grow, a in ((1.0, .35), (0.5, .5)):
        c = QColor(color)
        c.setAlphaF(color.alphaF() * a)
        p.setBrush(c)
        r = rect.adjusted(-grow, -grow + .5, grow, grow + .5)
        p.drawPath(rounded(r, radius + grow))


def _gloss_line(p: QPainter, path: QPainterPath, rect: QRectF, color, dpr):
    band = QPainterPath()
    band.addRect(QRectF(rect.left(), snap_to_device(p, rect.top(), dpr),
                        rect.width(), hairline_width(dpr)))
    c = QColor(color)
    c.setAlphaF(c.alphaF() * hairline_coverage(dpr))
    p.fillPath(path.intersected(band), c)


def paint_raised(p: QPainter, rect: QRectF, radius: float, top, bottom,
                 rim, tok: dict, dpr: float) -> None:
    """A raised glass surface: gradient fill, top gloss, 0.5 px rim."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = rounded(rect, radius)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0.0, top)
    g.setColorAt(1.0, bottom)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(path, g)
    _gloss_line(p, path, rect, tok["gloss"], dpr)
    draw_inset_hairline(p, rect, radius, rim, dpr)


def paint_thumb(p: QPainter, rect: QRectF, radius: float, tok: dict,
                dpr: float) -> None:
    """The raised thumb of the ADITYA CIRCLE active idiom."""
    paint_raised(p, rect, radius, tok["thumb_top"], tok["thumb_bottom"],
                 tok["hair_soft"], tok, dpr)


def paint_accent(p: QPainter, x1: float, x2: float, bottom: float,
                 color: QColor, glow: QColor, dpr: float) -> None:
    """A 1.5 px rounded accent bar with a soft glow (``.acc`` / ``::after``)."""
    r = QRectF(x1, bottom - 1.5, max(0.0, x2 - x1), 1.5)
    if r.width() <= 0:
        return
    soft_glow(p, r, glow, dpr, blur=6.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(r, 0.75, 0.75)


def draw_icon(p: QPainter, name: str, slot: QRectF, color: QColor,
              dpr: float) -> None:
    """Blit a recoloured ``img/icons/bar_<name>.svg`` glyph into ``slot``."""
    pm = icon_pixmap(name, slot.width(), QColor(color), dpr)
    if pm is None:
        return
    p.drawPixmap(QPointF(round(slot.x() * dpr) / dpr, round(slot.y() * dpr) / dpr), pm)


class KeyboardFocusMixin:
    """``focus_visible()``: focus that came from the keyboard (CSS
    ``:focus-visible``), so a mouse click or window activation never draws
    the ring."""

    _kbd_focus = False

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason,
                                         Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def focus_visible(self) -> bool:
        return self._kbd_focus and self.hasFocus()
