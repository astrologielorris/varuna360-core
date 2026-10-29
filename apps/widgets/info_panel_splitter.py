# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Glass splitter, fold button and summary chip of the Chart-tab info panels.

SPEC-LAYOUT-001 stream B (the "Four-Stop Glass Slider" of the 2026-10-15
mockup competition winner). Every widget here PAINTS itself from the live
theme (``get_theme_colors()``, Rule 20) and the live font areas
(``scaled_area_px``), so a theme switch or a font preset change only needs an
``update()`` / ``updateGeometry()``; there is no construction-time stylesheet
to replay and no graphics effect (Rule 18 does not arise).

The handle never resizes anything itself: it reports click / drag to the
``InfoPanelStack`` that owns the splitter, which owns all layout state.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QSplitter, QSplitterHandle, QWidget

from apps.widgets.info_panel_layout import CLICK_SLOP
from ui.qt_theme import get_scale_factor, get_theme_colors, scaled_area_px, scaled_px

from core.i18n import t


def knob_tip() -> str:
    return t("panel.info.splitter.knob_tip",
             "Click: swap which side is open. Drag: resize, snaps to fold / fit / half")


def auto_tip() -> str:
    return t("panel.info.splitter.auto_tip", "Panels AUTO: heights follow the window height")


def auto_label() -> str:
    return t("panel.info.splitter.auto", "AUTO")


def fold_tip() -> str:
    return t("panel.info.fold_tip", "Fold or unfold this panel")


CHIP_MIN_CAP = 170        # px at scale 1: the widest summary room a folded bar reserves


def small_px(base: float) -> int:
    """Display-Scale a SMALL pixel value (scaled_px floors at 5 px, too coarse
    for a 1-2 px line, gap or pen)."""
    return max(1, int(round(base * get_scale_factor())))


def _alpha(hex_color: str, a: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _small_font(base: QFont, px: int, bold=True) -> QFont:
    f = QFont(base)
    f.setPixelSize(max(6, int(px)))
    f.setBold(bold)
    return f


def handle_thickness() -> int:
    """Splitter handle height: room for the knob and the AUTO chip text."""
    chip = QFontMetrics(_small_font(QFont(), auto_px())).height() + small_px(4)
    return max(scaled_px(16), chip)


def auto_px() -> int:
    return max(scaled_px(8), scaled_area_px("table_headers") - 3)


class GlassSplitter(QSplitter):
    """Vertical QSplitter whose handles are ``GlassHandle``s. ``owner`` is the
    InfoPanelStack that receives the handle gestures."""

    def __init__(self, owner, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self._owner = owner
        self.setChildrenCollapsible(False)
        self.setHandleWidth(handle_thickness())

    def createHandle(self):
        return GlassHandle(self.orientation(), self, self._owner)


class GlassHandle(QSplitterHandle):
    """Glass line with a round knob (click: exchange the pair; drag: resize with
    snap) and, on the first handle, the AUTO chip."""

    def __init__(self, orientation, splitter, owner):
        super().__init__(orientation, splitter)
        self._owner = owner
        self._press = None          # (y, on_auto)
        self._dragging = False
        self._hover = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setToolTip(knob_tip())

    # -- geometry ---------------------------------------------------------
    def index(self) -> int:
        """Handle i sits between splitter widgets i-1 and i."""
        return self.splitter().indexOf(self)

    def has_auto(self) -> bool:
        return self.index() == 1

    def knob_rect(self) -> QRect:
        w, h = scaled_px(40), min(self.height() - 2, scaled_px(14))
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def auto_rect(self) -> QRect:
        if not self.has_auto():
            return QRect()
        fm = QFontMetrics(_small_font(self.font(), auto_px()))
        w = fm.horizontalAdvance(auto_label()) + small_px(8)
        h = min(self.height() - 2, fm.height() + small_px(2))
        return QRect(small_px(4), (self.height() - h) // 2, w, h)

    def sizeHint(self):
        return QSize(scaled_px(60), handle_thickness())

    # -- mouse ------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        y = self.mapTo(self.splitter(), e.position().toPoint()).y()
        self._press = (y, self.auto_rect().contains(e.position().toPoint()))
        self._dragging = False
        e.accept()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        hover = self.knob_rect().contains(pos) or self.auto_rect().contains(pos)
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.SplitVCursor)
            self.setToolTip(auto_tip() if self.auto_rect().contains(pos) else knob_tip())
            self.update()
        if self._press is None:
            return
        y = self.mapTo(self.splitter(), pos).y()
        dy = y - self._press[0]
        if not self._dragging and abs(dy) > CLICK_SLOP and not self._press[1]:
            self._dragging = True
            self._owner.drag_begin(self.index())
        if self._dragging:
            self._owner.drag_move(self.index(), dy)
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._press is None:
            return super().mouseReleaseEvent(e)
        on_auto = self._press[1]
        self._press = None
        if self._dragging:
            self._dragging = False
            self._owner.drag_end(self.index())
        elif on_auto:
            self._owner.set_auto_by_user()
        else:
            self._owner.exchange_at(self.index(), user=True)
        e.accept()

    def leaveEvent(self, e):
        if self._hover:
            self._hover = False
            self.update()
        super().leaveEvent(e)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, _event):
        th = get_theme_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        # the glass line, fading at both ends
        lit = self._hover or self._dragging
        line = QLinearGradient(0, 0, w, 0)
        core = _alpha(th["primary_light"], 0.95 if lit else 0.55)
        line.setColorAt(0.0, _alpha(th["primary_light"], 0.0))
        line.setColorAt(0.18, core)
        line.setColorAt(0.82, core)
        line.setColorAt(1.0, _alpha(th["primary_light"], 0.0))
        lh = small_px(2)
        p.fillRect(QRectF(small_px(6), (h - lh) / 2, w - 2 * small_px(6), lh), line)
        # the knob
        k = QRectF(self.knob_rect())
        grad = QLinearGradient(0, k.top(), 0, k.bottom())
        grad.setColorAt(0.0, _alpha(th["primary_light"], 0.85 if lit else 0.6))
        grad.setColorAt(1.0, _alpha(th["primary"], 0.85 if lit else 0.6))
        p.setPen(QPen(_alpha(th["primary_text"], 0.55), 1))
        p.setBrush(grad)
        p.drawRoundedRect(k.adjusted(0.5, 0.5, -0.5, -0.5), k.height() / 2, k.height() / 2)
        # two arrows (up and down): the pair exchanges
        self._paint_arrows(p, k, QColor(th["primary_text"]))
        # the AUTO chip
        if self.has_auto():
            self._paint_auto(p, th)
        p.end()

    def _paint_arrows(self, p, k, color):
        cx, cy = k.center().x(), k.center().y()
        a = max(2.0, k.height() * 0.28)
        p.setPen(QPen(color, max(1.0, 1.4 * get_scale_factor()), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for dx, up in ((-a * 0.9, True), (a * 0.9, False)):
            x = cx + dx
            top, bot = cy - a, cy + a
            p.drawLine(QPointF(x, top), QPointF(x, bot))
            tip = top if up else bot
            s = -1 if up else 1
            p.drawLine(QPointF(x, tip), QPointF(x - a * 0.6, tip - s * a * 0.6))
            p.drawLine(QPointF(x, tip), QPointF(x + a * 0.6, tip - s * a * 0.6))

    def _paint_auto(self, p, th):
        r = QRectF(self.auto_rect())
        on = bool(self._owner.is_auto())
        p.setPen(QPen(QColor(th["primary_light"] if on else th["secondary_light"]), 1))
        p.setBrush(QColor(th["primary_dark"] if on else th["secondary_dark"]))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), small_px(4), small_px(4))
        p.setFont(_small_font(self.font(), auto_px()))
        p.setPen(QColor(th["primary_text"] if on else th["secondary_text"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, auto_label())


class FoldButton(QAbstractButton):
    """The one chevron of every panel header (SPEC-PANELS-001 §2.6, SF
    "chevron.down"): a 22 px plate, borderless at rest, the toolbar's hover /
    pressed plates; down = open, right = folded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folded = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(fold_tip())
        self.setAccessibleName(fold_tip())
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.refresh_size()

    def refresh_size(self):
        from apps.widgets.panel_header import header_scale
        s = int(round(22 * header_scale()))
        self.setFixedSize(s, s)

    def set_folded(self, folded: bool):
        if folded != self._folded:
            self._folded = folded
            self.update()

    def paintEvent(self, _event):
        from apps.widgets.panel_header import header_scale, inks, plate_colors, stroke_pen
        ink = inks()
        fs = header_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        fill, glyph = plate_colors(self, ink)
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 5 * fs, 5 * fs)
        k = (r.width() - 6 * fs) / 16.0          # 16-unit glyph box inside 3 px padding
        ox, oy = r.left() + 3 * fs, r.top() + 3 * fs
        pts = (((6.25, 4.25), (10.0, 8.0), (6.25, 11.75)) if self._folded     # right
               else ((4.25, 6.25), (8.0, 10.0), (11.75, 6.25)))               # down
        path = QPainterPath()
        path.moveTo(ox + pts[0][0] * k, oy + pts[0][1] * k)
        for x, y in pts[1:]:
            path.lineTo(ox + x * k, oy + y * k)
        p.setPen(stroke_pen(glyph, max(1.3, 1.6 * fs)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class SummaryChip(QWidget):
    """The one-line summary pill a folded panel shows in its header (plan B.2).
    Right-aligned, elided to the room the header tabs leave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def text(self) -> str:
        return self._text

    def set_text(self, text: str):
        if text != self._text:
            self._text = text
            self.setToolTip(text)
            self.setAccessibleName(text)
            self.updateGeometry()
            self.update()

    def _font(self) -> QFont:
        from ui.font_bootstrap import bar_font
        return bar_font(max(scaled_px(9), scaled_area_px("panel_titles") - 1), 530)

    def sizeHint(self):
        from apps.widgets.panel_header import header_scale
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance(self._text) + small_px(20), int(round(20 * header_scale())))

    def minimumSizeHint(self):
        # A folded bar shows its summary before the trailing tabs (the mockup
        # clips the tab strip); capped so the column keeps its minimum width.
        return QSize(min(self.sizeHint().width(), scaled_px(CHIP_MIN_CAP)),
                     self.sizeHint().height())

    def paintEvent(self, _event):
        """SPEC-PANELS-001 §2.6: the summary in a recessed well, right-aligned;
        each part in strong ink, the " · " separators muted, elided at the end."""
        if not self._text:
            return
        from apps.widgets.panel_header import header_scale, inks
        ink = inks()
        fs = header_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = self._font()
        fm = QFontMetrics(font)
        pad = 8 * fs
        w = min(self.width(), fm.horizontalAdvance(self._text) + 2 * pad)
        if w < 2 * pad + fm.horizontalAdvance("…"):
            p.end()
            return
        h = min(self.height(), 20 * fs)
        r = QRectF(self.width() - w, (self.height() - h) / 2, w, h)
        p.setPen(QPen(ink["well_line"], 1))
        p.setBrush(ink["well"])
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 5 * fs, 5 * fs)
        p.setFont(font)
        room = int(w - 2 * pad)
        text = fm.elidedText(self._text, Qt.TextElideMode.ElideRight, room)
        x = r.left() + pad
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        for i, part in enumerate(text.split(" · ")):
            if i:
                p.setPen(ink["muted"])
                sep = " · "
                p.drawText(QRectF(x, r.top(), fm.horizontalAdvance(sep) + 1, r.height()), flags, sep)
                x += fm.horizontalAdvance(sep)
            p.setPen(ink["strong"])
            p.drawText(QRectF(x, r.top(), fm.horizontalAdvance(part) + 1, r.height()), flags, part)
            x += fm.horizontalAdvance(part)
        p.end()
