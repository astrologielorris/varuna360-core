"""SPEC-BAR-001 F2 / D-23(b) — the overlaid-chart identity chip, painted.

The frozen mockup's `.ovl` chip (vibrancy_segmented.html :412-431) is a flex
row — a fixed ◇ (`--primary_light`), the name (`--primary_text`, weight 590,
`flex:0 1 auto`, ellipsis) and the birth info (`--muted`, `flex:0 60 auto`,
ellipsis) inside a `--ctl` fill with a 0.5px `--hair-soft` INSET hairline (NOT a
1px border, and NOT the blue `--primary`). The info gives ground first (shrink
60 vs the name's 1) and, at d1+, is hidden entirely so the chip reads name-only.

This widget reproduces that with real elision and real allocated geometry, using
the bar's own fractional-pixel text primitives (so it matches the goldens) and
`bar_tokens()` for colour (Rule 20 / INV-4 — no hex, read at paint time). It
replaces the three plain QLabels, which had no stretch, no elision and a
spurious blue border (the two CP-4 overlay reds + the responsiveness gap Sol
flagged: at 1707px the old info span silently clipped a 175px string into 115px;
at 1563px the name got 8px for 34px and showed neither the wide chip nor the
required name-only collapse).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .bar_types import draw_bar_text, text_advance

# Mockup text styles (px, weight, tracking-em) — .ovl is 10.5/530/.012em; the
# name overrides weight to 590; the info inherits 530 but paints --muted.
CHIP_BASE = (10.5, 530, 0.012)     # ◇ and info
CHIP_NAME = (10.5, 590, 0.012)     # name

# Mockup geometry (CSS px, scaled by fs at paint time).
_GAP = 5.0
_PAD_X = 7.0
_HEIGHT = 18.0
_RADIUS = 4.0
_ELLIPSIS = "…"


class OverlayChip(QWidget):
    """Painted ◇ · name · info chip with mockup-faithful flex elision."""

    def __init__(self, fs: float = 1.0, parent=None):
        super().__init__(parent)
        self._fs = float(fs)
        self._dia = "◇"          # U+25C7 WHITE DIAMOND
        self._name = ""
        self._info = ""
        self._collapsed = False       # info hidden by the tier gate (d1+)
        # Last painted layout — the test surface (real allocated geometry).
        self._name_rect = QRect()
        self._info_rect = QRect()
        self._info_drawn = False
        self._elided_name = ""
        self._elided_info = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    # -- content -----------------------------------------------------------
    def set_content(self, name: str, info: str) -> None:
        name, info = name or "", info or ""
        if (name, info) == (self._name, self._info):
            return
        self._name, self._info = name, info
        self.updateGeometry()
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        """d1+ hides the info span entirely (mockup: `.ovl-info{display:none}`)."""
        collapsed = bool(collapsed)
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            self.updateGeometry()
            self.update()

    def set_fs(self, fs: float) -> None:
        if abs(fs - self._fs) > 1e-6:
            self._fs = float(fs)
            self.updateGeometry()
            self.update()

    # -- test / introspection surface -------------------------------------
    def info_shown(self) -> bool:
        """True iff the info span is actually painted (not collapsed, has room)."""
        return self._info_drawn

    def name_rect(self) -> QRect:
        return QRect(self._name_rect)

    def info_rect(self) -> QRect:
        return QRect(self._info_rect)

    def elided_name(self) -> str:
        return self._elided_name

    def elided_info(self) -> str:
        return self._elided_info

    def natural_width(self) -> int:
        """Width that shows ◇ + full name + full info with no elision."""
        return self._width_for(collapsed=False, elide=False)

    # -- sizing ------------------------------------------------------------
    def _adv(self, text: str, style) -> float:
        return text_advance(text, style[0], style[1], style[2], self._fs)

    def _width_for(self, collapsed: bool, elide: bool) -> int:
        pad = _PAD_X * self._fs
        gap = _GAP * self._fs
        w = pad + self._adv(self._dia, CHIP_BASE) + gap + self._adv(self._name, CHIP_NAME)
        if self._info and not collapsed:
            w += gap + self._adv(self._info, CHIP_BASE)
        w += pad
        return int(round(w))

    def sizeHint(self) -> QSize:
        return QSize(self._width_for(self._collapsed, elide=False),
                     int(round(_HEIGHT * self._fs)))

    def minimumSizeHint(self) -> QSize:
        # The floor: ◇ + gap + an elided-to-ellipsis name + padding, so the
        # well can shrink the chip all the way to name-only without clipping.
        # MAJOR 1: ceil, never round. The true floor at real d5 (chip view ~40px)
        # is a fractional value (e.g. 40.31px); rounding it DOWN gave the paint
        # path one sub-pixel LESS than the ellipsis needs, so _elide() returned
        # "" and the chip showed the diamond ALONE. Rounding UP guarantees the
        # allocated box always fits ◇ + gap + "…" — the name survives the
        # collapse as at least an ellipsis, which is the frozen d5 behavior.
        pad = _PAD_X * self._fs
        gap = _GAP * self._fs
        w = pad + self._adv(self._dia, CHIP_BASE) + gap \
            + self._adv(_ELLIPSIS, CHIP_NAME) + pad
        return QSize(math.ceil(w), math.ceil(_HEIGHT * self._fs))

    # -- elision -----------------------------------------------------------
    def _elide(self, text: str, style, max_w: float) -> str:
        """Longest prefix of ``text`` (+ ellipsis) whose advance <= max_w, using
        the fractional metric the goldens are measured with."""
        if max_w <= 0:
            return ""
        if self._adv(text, style) <= max_w + 0.75:      # rounding slack
            return text
        ell = self._adv(_ELLIPSIS, style)
        if ell > max_w:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._adv(text[:mid], style) + ell <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return (text[:lo] + _ELLIPSIS) if lo else _ELLIPSIS

    # -- paint -------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        from ui.qt_theme import bar_tokens
        tok = bar_tokens()
        fs = self._fs
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        radius = _RADIUS * fs

        # background --ctl + inset 0.5px --hair-soft hairline (NOT a blue border).
        # MINOR 6 / Rule 20 / INV-4: colour comes ONLY from bar_tokens() (the
        # single colour truth, complete 60-key table in both themes) — no literal
        # QColor fallbacks, which were unreachable hex bypassing the contract.
        bg = tok["ctl"]
        hair = tok["hair_soft"]
        inset = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(inset, radius, radius)
        pen = QPen(hair)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(inset, radius, radius)

        pad = _PAD_X * fs
        gap = _GAP * fs
        h = r.height()
        eps = 0.75          # sub-pixel slack: never elide over a rounding crumb

        def band(x, w):
            return QRectF(x, 0, w, h)

        # widget-local coords start at 0; use width(), not right() (inclusive)
        x = pad
        inner_right = r.width() - pad

        # ◇ — fixed, primary_light
        dia_w = self._adv(self._dia, CHIP_BASE)
        p.setPen(QPen(tok["primary_light"]))
        draw_bar_text(p, band(x, dia_w), Qt.AlignVCenter | Qt.AlignLeft,
                      self._dia, *CHIP_BASE, fs=fs)
        x += dia_w + gap

        remaining = inner_right - x
        name_nat = self._adv(self._name, CHIP_NAME)
        info_nat = self._adv(self._info, CHIP_BASE)
        show_info = (not self._collapsed) and bool(self._info)

        info_min = self._adv(_ELLIPSIS, CHIP_BASE)
        if show_info:
            if name_nat + gap + info_nat <= remaining + eps:    # both fit whole
                name_w, info_w = name_nat, info_nat
            elif name_nat + gap + info_min <= remaining + eps:  # info gives ground first
                name_w = name_nat
                info_w = remaining - name_nat - gap
            else:                                                # info gone → name only
                show_info = False
                name_w = min(name_nat, remaining)
        else:
            name_w = min(name_nat, remaining)

        name_w = max(0.0, name_w)
        # name — primary_text, weight 590, elides last
        self._elided_name = self._elide(self._name, CHIP_NAME, name_w)
        nr = band(x, name_w)
        p.setPen(QPen(tok["primary_text"]))
        draw_bar_text(p, nr, Qt.AlignVCenter | Qt.AlignLeft,
                      self._elided_name, *CHIP_NAME, fs=fs)
        self._name_rect = nr.toRect()

        if show_info:
            ix = x + name_w + gap
            iw = max(0.0, inner_right - ix)
            self._elided_info = self._elide(self._info, CHIP_BASE, iw)
            ir = band(ix, iw)
            p.setPen(QPen(tok["muted"]))
            draw_bar_text(p, ir, Qt.AlignVCenter | Qt.AlignLeft,
                          self._elided_info, *CHIP_BASE, fs=fs)
            self._info_rect = ir.toRect()
            self._info_drawn = bool(self._elided_info)
        else:
            self._elided_info = ""
            self._info_rect = QRect()
            self._info_drawn = False
        p.end()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update()
