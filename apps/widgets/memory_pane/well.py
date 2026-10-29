# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The profile well (MC-INTENT "Profile well", "Page ticks", "LOAD bezel key").

Library Well material: recessed, gold stripe at the left; a readout column
(the active PROFILE's name in small caps, the chart count + CHARTS, one tick
per page with the open page gold) and the LOAD bezel key inside the well
(profile-well round, 2026-10-22: a glass disc seated in a recessed ring).
At the compact steps the name, CHARTS and the LOAD caption fold into the
tooltips; nothing else changes.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QPushButton, QWidget

from apps.widgets.action_bar.paint_surfaces import soft_glow

from .paint import (KeyboardFocusMixin, area_factor, area_qss, design_font, dpr_of, draw_icon, paint_drop,
                    paint_recess, paint_thumb, rounded, text_width)
from .tokens import pane_tokens, with_alpha

WELL_H = 52
_PAD_L, _PAD_R, _GAP = 8.0, 6.0, 7.0
_STRIPE_W, _STRIPE_H = 3.0, 28.0
# Bezel ring / glass disc: full steps 30 / 24, compact steps (S2, S3) 28 / 22.
_BEZEL, _DISC = 30.0, 24.0
_BEZEL_C, _DISC_C = 28.0, 22.0
_FOCUS = 3.0           # 2 px focus ring 1 px off the bezel
_KEY_W, _KEY_H = 36, 44
_MAX_TICKS = 16


def _round_glow(p, ring: QRectF, color, blur: float):
    """CSS ``0 0 <blur>px <color>`` around a circle: a radial falloff drawn
    outside the circle only (an outer box-shadow never shows under its box)."""
    r = ring.width() / 2.0
    ext = 1.5 * blur
    c = ring.center()
    outer = QPainterPath()
    outer.addEllipse(c, r + ext, r + ext)
    inner = QPainterPath()
    inner.addEllipse(c, r, r)
    g = QRadialGradient(c, r + ext)
    k = r / (r + ext)
    a = color.alphaF()
    sigma = blur / 2.0
    for i in range(7):
        d = ext * i / 6.0                    # distance past the edge
        # erfc-shaped falloff of a blurred edge: 0.5 at the edge
        f = 0.5 * math.erfc(d / (sigma * math.sqrt(2.0)))
        g.setColorAt(k + (1.0 - k) * i / 6.0, with_alpha(color, a * f))
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(outer.subtracted(inner), g)


class LoadKey(KeyboardFocusMixin, QPushButton):
    """The LOAD bezel key: a glass disc with the folder-down glyph seated in a
    recessed ring, the LOAD caption under it; the whole column is one button.
    The hover glow around the ring is painted by the well (it spills past
    the key's own rectangle)."""

    def __init__(self, parent=None):
        super().__init__("LOAD", parent)
        self.setObjectName("memoryLoadKey")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.show_caption = True
        self._hover = False
        self.apply_font()

    def _bezel_size(self) -> float:
        return _BEZEL if self.show_caption else _BEZEL_C

    def apply_font(self):
        # The caption grows with the Buttons & Controls area; so does the key.
        ring = round(self._bezel_size() + 2 * _FOCUS)
        cap_w = QFontMetricsF(self.caption_font()).horizontalAdvance("LOAD") + 2
        w = max(ring, round(cap_w)) if self.show_caption else ring
        self.setFixedSize(w, _KEY_H)
        self.setStyleSheet(
            "QPushButton#memoryLoadKey { border: none; background: transparent;"
            " padding: 0px; margin: 0px; min-width: 0px;"
            " height: %dpx; min-height: %dpx; max-height: %dpx; %s }"
            % (_KEY_H, _KEY_H, _KEY_H, area_qss("buttons", 6.5)))

    def caption_font(self):
        return design_font(self, 6.5, 700, .14)

    def set_show_caption(self, show: bool):
        self.show_caption = bool(show)
        self.apply_font()
        self.update()

    def lit(self) -> bool:
        """Hover ring + glow: on hover and while pressed."""
        return self._hover or self.isDown()

    def bezel_rect(self) -> QRectF:
        """The ring in this key's coordinates, the bezel + caption centred."""
        b = self._bezel_size()
        cap_h = (QFontMetricsF(self.caption_font()).capHeight() + 3.0
                 if self.show_caption else 0.0)
        top = max(_FOCUS, (self.height() - b - cap_h) / 2.0)
        return QRectF((self.width() - b) / 2.0, top, b, b)

    def _set_hover(self, on: bool):
        self._hover = on
        self.update()
        if self.parentWidget() is not None:
            self.parentWidget().update()      # the glow lives on the well

    def enterEvent(self, e):
        self._set_hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_hover(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self.parentWidget() is not None:
            self.parentWidget().update()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.parentWidget() is not None:
            self.parentWidget().update()

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bezel = self.bezel_rect()
        lit, down = self.lit(), self.isDown()

        # The machined ring: channel fill, inset shade, 0.5 px hair line
        # (1 px primary 60 % while lit).
        paint_recess(p, bezel, bezel.width() / 2.0, tok["channel"],
                     tok["hair"], tok["well_inset"], dpr)
        if lit:
            p.setPen(QPen(with_alpha(tok["primary"], .60), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(bezel.adjusted(.5, .5, -.5, -.5))

        d = _DISC if self.show_caption else _DISC_C
        c = bezel.center()
        disc = QRectF(c.x() - d / 2.0, c.y() - d / 2.0, d, d)
        r = d / 2.0
        if down:
            paint_recess(p, disc, r, tok["ctl_a"], tok["hair_soft"], tok["well_inset"], dpr)
        else:
            paint_drop(p, disc, r, tok["drop"])
            paint_thumb(p, disc, r, tok, dpr)
            self._paint_crescent(p, disc, tok)
        nudge = .5 if down else 0.0
        draw_icon(p, "mp_folder", QRectF(c.x() - 6.5, c.y() - 6.5 + nudge, 13, 13),
                  tok["primary"], dpr)

        if self.show_caption:
            font = self.caption_font()
            fm = QFontMetricsF(font)
            p.setFont(font)
            p.setPen(tok["primary"] if lit else tok["secondary_text"])
            tw = text_width(font, "LOAD")
            p.drawText(QPointF((self.width() - tw) / 2.0, bezel.bottom() + 3.0 + fm.capHeight()),
                       "LOAD")
        if self.focus_visible():
            p.setPen(QPen(tok["ring"], 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(bezel.adjusted(-2, -2, 2, 2))
        p.end()

    @staticmethod
    def _paint_crescent(p, disc, tok):
        """The gloss crescent: top 1.5 px, 8 px tall, 4 px in from each side,
        domed top and flat-ish bottom (CSS radii 50%/80% top, 45%/20% bottom)."""
        h = 8.0 * disc.width() / _DISC
        l, t = disc.left() + 4.0, disc.top() + 1.5
        w = disc.width() - 8.0
        b = t + h
        path = QPainterPath()
        path.moveTo(l, t + .8 * h)
        path.arcTo(QRectF(l, t, w, 1.6 * h), 180, -180)
        path.lineTo(l + w, b - .2 * h)
        path.arcTo(QRectF(l + w - .9 * w, b - .4 * h, .9 * w, .4 * h), 0, -90)
        path.lineTo(l + .45 * w, b)
        path.arcTo(QRectF(l, b - .4 * h, .9 * w, .4 * h), 270, -90)
        path.closeSubpath()
        g = QLinearGradient(QPointF(0, t), QPointF(0, b))
        g.setColorAt(0.0, tok["crescent"])
        g.setColorAt(1.0, with_alpha(tok["crescent"], 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, g)


class ProfileWell(QWidget):
    """Readout + LOAD key. ``set_state`` feeds it; it only draws."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("memoryProfileWell")
        self.setFixedHeight(WELL_H)
        self.load_key = LoadKey(self)
        self.profile_name = ""
        self.count = 0
        self.page = 1
        self.pages = 1
        self.compact = False
        self._update_tooltip()

    def set_state(self, profile_name, count, page, pages):
        self.profile_name = profile_name or ""
        self.count = max(0, int(count))
        self.pages = max(1, int(pages))
        self.page = max(1, min(int(page), self.pages))
        self._update_tooltip()
        self.update()

    def set_compact(self, compact: bool):
        self.compact = bool(compact)
        self.load_key.set_show_caption(not self.compact)
        self.place_key()
        self.update()

    def _update_tooltip(self):
        name = self.profile_name.upper()
        self.setToolTip(f"{self.count:,} charts in profile {name} · "
                        f"page {self.page} of {self.pages}")

    def place_key(self):
        self.load_key.move(int(self.width() - _PAD_R - self.load_key.width() + 2),
                           (WELL_H - _KEY_H) // 2)

    def resizeEvent(self, e):
        self.place_key()
        super().resizeEvent(e)

    # -- paint --------------------------------------------------------------

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        r = QRectF(0, 0, self.width(), WELL_H)
        paint_recess(p, r, 8.0, tok["well"], tok["well_line"], tok["well_inset"], dpr)
        key = self.load_key
        if key.lit():
            # 0 0 7px primary 35 % around the bezel, under the key.
            ring = key.bezel_rect().translated(key.x(), key.y())
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            _round_glow(p, ring, with_alpha(tok["primary"], .35), 7.0)

        stripe = QRectF(_PAD_L, (WELL_H - _STRIPE_H) / 2.0, _STRIPE_W, _STRIPE_H)
        soft_glow(p, stripe, tok["stripe_glow"], dpr)
        g = QLinearGradient(stripe.topLeft(), stripe.bottomLeft())
        g.setColorAt(0.0, tok["gold_hi"])
        g.setColorAt(1.0, tok["gold"])
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(rounded(stripe, 2.0), g)

        x = stripe.right() + _GAP
        right = self.load_key.x() - _GAP + 2
        avail = max(0.0, right - x)

        name_font = design_font(self, 8, 650, .14, caps=True)
        num_font = design_font(self, 15, 680, -.015)
        unit_font = design_font(self, 7.5, 640, .12)
        nfm, cfm, ufm = QFontMetricsF(name_font), QFontMetricsF(num_font), QFontMetricsF(unit_font)
        # Line boxes are the fonts' cap heights (CSS line-height 1), measured
        # live so a bigger Buttons & Controls area cannot make them collide.
        # If the three lines do not fit the well, the name goes to the
        # tooltip first (as at the compact steps), then the gaps tighten.
        name_h, num_h, gauge_h = nfm.capHeight(), cfm.capHeight(), 11.0
        show_name = not self.compact
        gap = 4.0
        room = WELL_H - 6.0
        if show_name and name_h + num_h + gauge_h + 2 * gap > room:
            show_name = False
        if num_h + gauge_h + gap > room:
            gap = 2.0
        total = num_h + gap + gauge_h + (name_h + gap if show_name else 0.0)
        y = max(3.0, (WELL_H - total) / 2.0)

        if show_name:
            p.setFont(name_font)
            p.setPen(tok["muted"])
            text = nfm.elidedText(self.profile_name, Qt.TextElideMode.ElideRight, avail)
            p.drawText(QPointF(x, y + name_h), text)
            y += name_h + gap

        num = f"{self.count:,}"
        base = y + num_h
        p.setFont(num_font)
        p.setPen(tok["primary_text"])
        num_text = cfm.elidedText(num, Qt.TextElideMode.ElideRight, avail)
        p.drawText(QPointF(x, base), num_text)
        nx = x + cfm.horizontalAdvance(num_text) + 4
        if not self.compact and nx + ufm.horizontalAdvance("CHARTS") <= right:
            p.setFont(unit_font)
            p.setPen(tok["secondary_text"])
            p.drawText(QPointF(nx, base), "CHARTS")
        y = base + gap
        self._paint_gauge(p, tok, dpr, x, y, avail)
        p.end()

    def readout_width(self) -> float:
        """Room for the readout column, between the stripe and the LOAD key."""
        return max(0.0, (self.load_key.x() - _GAP + 2) - (_PAD_L + _STRIPE_W + _GAP))

    def uses_ticks(self, avail=None) -> bool:
        """One tick per page while they fit beside the LOAD key (and at most
        16 pages); otherwise the 40 px track with a gold thumb."""
        avail = self.readout_width() if avail is None else avail
        return self.pages <= _MAX_TICKS and self.pages * 4.0 - 2.0 <= avail

    def _paint_gauge(self, p, tok, dpr, x, y, avail):
        n, cur = self.pages, self.page
        p.setPen(Qt.PenStyle.NoPen)
        if self.uses_ticks(avail):
            for i in range(1, n + 1):
                if i == cur:
                    t = QRectF(x, y, 2.0, 11.0)
                    soft_glow(p, t, tok["thumb_acc_glow"], dpr, blur=5.0)
                    p.setBrush(tok["gold"])
                else:
                    t = QRectF(x, y + 1.5, 2.0, 8.0)
                    p.setBrush(tok["hair"])
                p.drawRoundedRect(t, 1.0, 1.0)
                x += 4.0
            return
        tw = max(12.0, min(40.0, avail))
        track = QRectF(x, y + 4.0, tw, 3.0)
        p.setBrush(tok["hair_soft"])
        p.drawRoundedRect(track, 1.5, 1.5)
        p.setPen(QPen(tok["hair"], 0.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(track.adjusted(.25, .25, -.25, -.25), 1.5, 1.5)
        p.setPen(Qt.PenStyle.NoPen)
        tx = x + ((tw - 6.0) * (cur - 1) / max(1, n - 1))
        thumb = QRectF(tx, y + 3.0, 6.0, 5.0)
        soft_glow(p, thumb, tok["thumb_acc_glow"], dpr, blur=5.0)
        p.setBrush(tok["gold"])
        p.drawRoundedRect(thumb, 2.0, 2.0)
