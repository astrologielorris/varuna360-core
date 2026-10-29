# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Inspector Underline panel headers of the three Chart-tab info panels.

SPEC-PANELS-001 §2.6 (winner of the 2026-10-22 panel titles mockup
competition, ``mockups_panel-titles-macos_20261022-1137/designer_c/mockup_1``).
The header is a neutral strip in the toolbar's macOS language: sentence-case
tabs (regular when inactive, semibold when active) with a 2 px accent rule on
the header's bottom hairline, one shared swap button (the toolbar's plate
states, accent tint when its alternate view is on) and, in
``info_panel_splitter.FoldButton``, one shared chevron.

Every widget PAINTS itself at paint time from the live theme
(``get_theme_colors()`` + ``bar_tokens()``, Rule 20) and the live
``panel_titles`` font area, so a theme switch, a font preset change or a
Display Scale change needs only ``refresh_panel_headers(gui)``. Callers never
style these widgets with a stylesheet: the active tab is ``set_active``, the
swap state is ``set_on``, the folded bar is ``set_header_folded``.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ui.qt_theme import bar_tokens, get_theme_colors, is_light_theme, scaled_area_px, scaled_px

QWIDGETSIZE_MAX = 16777215
HEADER_ATTRS = ("karakas_header", "strength_header", "aspects_header")

# The header buttons are QAbstractButtons, NOT QPushButtons: qt-material's
# app-wide ``QPushButton { height; padding; text-transform }`` rules (a widget
# stylesheet cannot unset ``height``) and the font sweeps that restyle every
# QPushButton never reach them, so the painted size hint is the only size.


# ------------------------------------------------------------------ metrics
def title_px() -> int:
    return max(1, scaled_area_px("panel_titles"))


def header_height() -> int:
    """30 px at the default Panel Titles size, growing with it."""
    return max(scaled_px(28), round(title_px() * 2.15))


def header_scale() -> float:
    """The mockup's ``--fs``: every glyph and plate scales with the header."""
    return header_height() / 30.0


def widget_scale(widget) -> float:
    """``header_scale()``, capped for a widget given ``set_scale_cap``: a
    fixed-width column (the dasha panels, 265 px) keeps its plates and tab
    padding at the Display Scale while the Panel Titles font still grows."""
    cap = getattr(widget, "_scale_cap", None)
    fs = header_scale()
    return min(fs, cap()) if cap is not None else fs


def set_scale_cap(widget, cap) -> None:
    """``cap``: zero-argument callable read at measure / paint time, or None."""
    widget._scale_cap = cap
    if hasattr(widget, "refresh_size"):
        widget.refresh_size()
    widget.updateGeometry()
    widget.update()


def tab_font(active: bool):
    from ui.font_bootstrap import bar_font
    return bar_font(title_px(), 600 if active else 490)


def _alpha(color, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _overlay(white: bool, a: float) -> QColor:
    c = QColor(Qt.GlobalColor.white if white else Qt.GlobalColor.black)
    c.setAlphaF(a)
    return c


def inks() -> dict:
    """Header colours for the current theme (paint time, never cached)."""
    th = get_theme_colors()
    tok = bar_tokens()
    light = bool(is_light_theme())
    text = QColor(th["secondary_text"])
    if light:
        # The light palette's surface text is a mid grey (7:1 on the strip):
        # it is the INACTIVE ink, the active ink goes most of the way to black.
        strong = QColor(round(text.red() * 0.45), round(text.green() * 0.45),
                        round(text.blue() * 0.45))
        dim = text
    else:
        strong, dim = text, _alpha(text, 0.70)
    return {
        "light": light,
        "strong": strong,
        "dim": dim,
        "accent": QColor(th["primary"]),
        "accent_ink": QColor(th["primary_dark"] if light else th["primary_light"]),
        "tint": _alpha(th["primary"], 0.15 if light else 0.24),
        "tint_h": _alpha(th["primary"], 0.22 if light else 0.32),
        "hdr_a": _overlay(True, 0.95) if light else _overlay(True, 0.045),
        "hdr_b": tok["bar_b"] if light else _overlay(True, 0.018),
        "gloss": tok["gloss"],
        "hair": tok["hair"],
        "ctl_h": _overlay(False, 0.055) if light else _overlay(True, 0.095),
        "ctl_a": tok["ctl_a"],
        "well": tok["well"],
        "well_line": tok["well_line"],
        "muted": tok["muted"],
    }


def frame_surface() -> QColor:
    """The info panel frames' surface (``get_frame_style``: ``SURFACE`` dark,
    ``secondary`` light), read live. A strip that does not sit on an info frame
    (the dasha panels) paints it first, so its translucent gradient lands on
    the same colour and the strips match."""
    import ui.qt_theme as qt
    if is_light_theme():
        return QColor(get_theme_colors()["secondary"])
    return QColor(qt.SURFACE)


def plate_colors(btn, ink: dict, on: bool = False):
    """(plate fill or None, glyph colour) of a header glyph button."""
    if btn.isDown():
        return ink["ctl_a"], (ink["accent_ink"] if on else ink["strong"])
    if on:
        return (ink["tint_h"] if btn.underMouse() else ink["tint"]), ink["accent_ink"]
    if btn.underMouse():
        return ink["ctl_h"], ink["strong"]
    return None, ink["dim"]


def stroke_pen(color: QColor, width: float) -> QPen:
    return QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin)


# ------------------------------------------------------------------- header
class PanelHeader(QWidget):
    """The header strip: toolbar gradient, .5 px top gloss, bottom hairline the
    active tab's rule sits on. Top corners round; all four when folded."""

    def __init__(self, parent=None, *, own_surface: bool = False):
        super().__init__(parent)
        self._folded = False
        self._own_surface = own_surface      # paint frame_surface() under the gradient
        self.setFixedHeight(header_height())

    def set_folded(self, folded: bool) -> None:
        if folded != self._folded:
            self._folded = folded
            self.update()

    def refresh(self) -> None:
        self.setFixedHeight(header_height())
        for w in self.findChildren(QWidget):
            if hasattr(w, "refresh_size"):
                w.refresh_size()
            if isinstance(w, HeaderTab):
                w.sync_font()
            w.updateGeometry()                 # tabs, swap, chevron, summary chip
            w.update()
        if self.layout() is not None:
            self.layout().invalidate()
        self.update()

    def paintEvent(self, _event):
        ink = inks()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        rad = 6.0 * header_scale()
        path = QPainterPath()
        if self._folded:
            path.addRoundedRect(r, rad, rad)
        else:
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + rad)
            path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
            path.lineTo(r.right() - rad, r.top())
            path.quadTo(r.right(), r.top(), r.right(), r.top() + rad)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
        if self._own_surface:
            p.fillPath(path, frame_surface())
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, ink["hdr_a"])
        g.setColorAt(1.0, ink["hdr_b"])
        p.fillPath(path, g)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 1.0), _alpha(ink["gloss"], ink["gloss"].alphaF() * 0.5))
        if not self._folded:
            p.fillRect(QRectF(r.left(), r.bottom() - 1.0, r.width(), 1.0), ink["hair"])
        p.end()


# --------------------------------------------------------------------- tabs
class HeaderTab(QAbstractButton):
    """One sub-tab of a panel header. Painted: sentence case, regular dim ink
    inactive, semibold strong ink active, 2 px accent rule on the header
    hairline. The width is the SEMIBOLD width, so switching never moves a tab.
    In a folded header only the active tab stays (as the section title).
    ``set_elide(True)`` (a lone title, the dasha panels) lets the tab shrink
    below its text width; the text is then cut at the right with an ellipsis
    instead of being clipped at both ends."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._elide = False
        self.setText(text)
        self._active = False
        self._folded = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Keyboard focus only (a click never leaves a focus ring behind).
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.sync_font()

    def sync_font(self) -> None:
        """Keep ``font()`` equal to the painted font, so font probes and
        ``fontMetrics()`` measure what is on screen."""
        self.setFont(tab_font(self._active))

    # state ---------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.sync_font()
            self._apply_collapse()
            self.update()

    def is_active(self) -> bool:
        return self._active

    def set_header_folded(self, folded: bool) -> None:
        if folded != self._folded:
            self._folded = folded
            self._apply_collapse()
            self.update()

    def _collapsed(self) -> bool:
        return self._folded and not self._active

    def _apply_collapse(self) -> None:
        collapsed = self._collapsed()
        self.setMaximumWidth(0 if collapsed else QWIDGETSIZE_MAX)
        # A collapsed tab is out of the keyboard order too (no invisible focus).
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if collapsed else Qt.FocusPolicy.TabFocus)
        self.updateGeometry()

    def is_collapsed(self) -> bool:
        return self._collapsed()

    # geometry ------------------------------------------------------------
    def _pad(self) -> float:
        return 8.0 * widget_scale(self)

    def sizeHint(self):
        fm = QFontMetricsF(tab_font(True))
        w = fm.horizontalAdvance(self.text()) + 2 * self._pad()
        return QSize(int(round(w + 0.5)), header_height())

    def minimumSizeHint(self):
        if self._collapsed():
            return QSize(0, 0)
        if self._elide:
            fm = QFontMetricsF(tab_font(True))
            w = fm.horizontalAdvance(self.text()[:1] + "\u2026") + 2 * self._pad()
            return QSize(min(self.sizeHint().width(), int(round(w + 0.5))), 0)
        return QSize(self.sizeHint().width(), 0)

    def set_elide(self, elide: bool) -> None:
        self._elide = bool(elide)
        self.setSizePolicy(QSizePolicy.Policy.Preferred if self._elide else QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)
        self.updateGeometry()
        self.update()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.updateGeometry()

    # paint ---------------------------------------------------------------
    def paintEvent(self, _event):
        if self.width() <= 0:
            return
        ink = inks()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        hot = self.underMouse() or self.isDown()
        p.setFont(tab_font(self._active))
        p.setPen(ink["strong"] if (self._active or hot) else ink["dim"])
        r = QRectF(self.rect())
        fm = QFontMetricsF(p.font())
        room = r.width() - 2 * self._pad()
        if self._elide and fm.horizontalAdvance(self.text()) > room:
            text = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, room)
            p.drawText(r.adjusted(self._pad(), 0, -self._pad(), 0),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        else:
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        if not self._folded and (self._active or hot):
            pad = self._pad()
            rule = QRectF(pad, r.bottom() - 2.0, max(0.0, r.width() - 2 * pad), 2.0)
            path = QPainterPath()
            path.addRoundedRect(rule.adjusted(0, 0, 0, 1.0), 1.0, 1.0)
            p.setClipRect(QRectF(r.left(), r.bottom() - 2.0, r.width(), 2.0))
            p.fillPath(path, ink["accent"] if self._active else ink["hair"])
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            p.setClipping(False)
            p.setPen(QPen(_alpha(ink["accent"], 0.6), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 4, -2, -4), 4, 4)
        p.end()


# ------------------------------------------------------------- swap button
_SWAP_PATHS = (((2.75, 5.25), (12.75, 5.25)), ((10.25, 2.75), (12.75, 5.25), (10.25, 7.75)),
               ((13.25, 10.75), (3.25, 10.75)), ((5.75, 8.25), (3.25, 10.75), (5.75, 13.25)))


class HeaderSwapButton(QAbstractButton):
    """The one swap button of every panel header (SF "arrow.left.arrow.right"):
    a .5 px separator hairline, then a 26 x 22 plate, borderless at rest, the
    toolbar's hover / pressed plates, the accent tint when ``set_on(True)``
    (the panel shows its alternate view). Hidden in a folded header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self._folded = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.refresh_size()

    def set_on(self, on: bool) -> None:
        on = bool(on)
        if on != self._on:
            self._on = on
            self.setAccessibleDescription("on" if on else "off")
            self.update()

    def is_on(self) -> bool:
        return self._on

    def set_header_folded(self, folded: bool) -> None:
        if folded != self._folded:
            self._folded = folded
            self.refresh_size()

    def _lead(self) -> float:
        """Room for the separator hairline before the plate (3 + .5 + 5 px)."""
        return 8.5 * widget_scale(self)

    def refresh_size(self) -> None:
        fs = widget_scale(self)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if self._folded else Qt.FocusPolicy.TabFocus)
        if self._folded:
            self.setFixedSize(0, 0)
        else:
            self.setFixedSize(int(round(self._lead() + 26 * fs)), int(round(22 * fs)))
        self.updateGeometry()

    def paintEvent(self, _event):
        if self.width() <= 0:
            return
        ink = inks()
        fs = widget_scale(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = float(self.height())
        sep_h = 14.0 * fs
        p.fillRect(QRectF(3.0 * fs, (h - sep_h) / 2, max(1.0, 0.5 * fs), sep_h), ink["hair"])
        plate = QRectF(self._lead(), 0, self.width() - self._lead(), h)
        fill, glyph = plate_colors(self, ink, self._on)
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(plate, 5 * fs, 5 * fs)
        box = 16.0 * fs
        ox = plate.center().x() - box / 2
        oy = plate.center().y() - box / 2
        k = box / 16.0
        p.setPen(stroke_pen(glyph, max(1.2, 1.45 * fs)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pts in _SWAP_PATHS:
            path = QPainterPath()
            path.moveTo(ox + pts[0][0] * k, oy + pts[0][1] * k)
            for x, y in pts[1:]:
                path.lineTo(ox + x * k, oy + y * k)
            p.drawPath(path)
        p.end()


# ------------------------------------------------------- glyph plate button
class HeaderGlyphButton(QAbstractButton):
    """A 22 px plate button of a panel header (the chevron's plate, §2.6):
    borderless at rest with the glyph in the dim ink, the toolbar's hover /
    pressed plates. ``glyph(painter, box, color, fs)`` draws the glyph in a
    16-unit box; ``set_glyph`` swaps it (the dasha fold <-> unfold)."""

    def __init__(self, glyph=None, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.refresh_size()

    def set_glyph(self, glyph) -> None:
        self._glyph = glyph
        self.update()

    def refresh_size(self) -> None:
        s = int(round(22 * widget_scale(self)))
        self.setFixedSize(s, s)
        self.updateGeometry()

    def paintEvent(self, _event):
        ink = inks()
        fs = widget_scale(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        fill, glyph = plate_colors(self, ink)
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 5 * fs, 5 * fs)
        if self._glyph is not None:
            self._glyph(p, r.adjusted(3 * fs, 3 * fs, -3 * fs, -3 * fs), glyph, fs)
        if self.hasFocus():
            p.setPen(QPen(_alpha(ink["accent"], 0.6), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5 * fs, 5 * fs)
        p.end()


# ------------------------------------------------------ segmented control
def segment_font(checked: bool, px: int | None = None):
    from ui.font_bootstrap import bar_font
    return bar_font(max(1, px if px is not None else title_px() - 1), 600 if checked else 490)


class SegmentButton(QAbstractButton):
    """One segment of a ``SegmentedControl`` (the toolbar's segmented control):
    checked = the raised thumb (``thumb_top`` -> ``thumb_bottom``, hairline
    edge, soft drop) with the strong ink, unchecked = the dim ink on the well,
    hover = the strong ink. Checkable; the caller owns the button group.
    ``font_px`` (zero-argument callable) picks the label's font area (default:
    the header's 'panel_titles' size - 1); the box grows with it, so a large
    font never clips the label."""

    def __init__(self, text: str = "", parent=None, *, font_px=None):
        super().__init__(parent)
        self._font_px = font_px
        self.setText(text)
        self.setCheckable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(lambda _on: self.sync_font())
        self.refresh_size()

    def _font(self, checked: bool):
        return segment_font(checked, self._font_px() if self._font_px else None)

    def sync_font(self) -> None:
        """``font()`` equals the painted font (font probes measure the screen)."""
        self.setFont(self._font(self.isChecked()))
        self.update()

    def refresh_size(self) -> None:
        # Sized from the label's own font (Display Scale + its area), not from
        # the header scale: a large Panel Titles size must not widen five
        # boxes past a fixed-width column (review 2026-10-22).
        fm = QFontMetricsF(self._font(True))
        w = max(scaled_px(22), fm.horizontalAdvance(self.text()) + scaled_px(12))
        h = max(scaled_px(20), fm.height() + scaled_px(6))
        self.setFixedSize(int(round(w)), int(round(h)))
        self.sync_font()
        self.updateGeometry()

    def paintEvent(self, _event):
        ink = inks()
        tok = bar_tokens()
        fs = header_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect())
        rad = 4.5 * fs
        checked = self.isChecked()
        if checked:
            thumb = r.adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(tok["drop"], tok["drop"].alphaF() * 0.6))
            p.drawRoundedRect(thumb.translated(0, 0.75), rad, rad)
            g = QLinearGradient(thumb.topLeft(), thumb.bottomLeft())
            g.setColorAt(0.0, tok["thumb_top"])
            g.setColorAt(1.0, tok["thumb_bottom"])
            p.setBrush(g)
            p.setPen(QPen(ink["hair"], 0.5))
            p.drawRoundedRect(thumb, rad, rad)
        elif self.isDown():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink["ctl_a"])
            p.drawRoundedRect(r, rad, rad)
        hot = self.underMouse() or self.isDown()
        p.setFont(self._font(checked))
        p.setPen(ink["strong"] if (checked or hot) else ink["dim"])
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus():
            p.setPen(QPen(_alpha(ink["accent"], 0.6), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad, rad)
        p.end()


class SegmentedControl(QWidget):
    """The recessed well (``well`` fill, .5 px ``well_line`` edge) that holds a
    row of ``SegmentButton``s. Hidden segments leave no gap (the well wraps
    the visible ones). ``refresh`` re-measures after a font / scale change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        lay = QHBoxLayout(self)
        lay.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._apply_margins()

    def _apply_margins(self) -> None:
        m = max(1, int(round(2 * header_scale())))
        self.layout().setContentsMargins(m, m, m, m)

    def add_segment(self, button: "SegmentButton") -> None:
        self.layout().addWidget(button)

    def segments(self):
        return [w for w in self.findChildren(SegmentButton)]

    def refresh(self) -> None:
        self._apply_margins()
        for b in self.segments():
            b.refresh_size()
        self.layout().invalidate()
        self.updateGeometry()
        self.update()

    def paintEvent(self, _event):
        ink = inks()
        fs = header_scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.25, 0.25, -0.25, -0.25)
        p.setBrush(ink["well"])
        p.setPen(QPen(ink["well_line"], 0.5))
        p.drawRoundedRect(r, 6.5 * fs, 6.5 * fs)
        p.end()


# ---------------------------------------------------------------- helpers
def set_active_tab(buttons, active) -> None:
    """Mark ``active`` (a button, or None) as the one active tab of a group."""
    for b in buttons:
        if b is not None and hasattr(b, "set_active"):
            b.set_active(b is active)


def set_header_folded(header, folded: bool) -> None:
    """Folded bar: the active tab stays as the title, the others and the swap
    button collapse, the bottom hairline goes (the summary chip fills the
    right side, owned by InfoPanelStack)."""
    if hasattr(header, "set_folded"):
        header.set_folded(folded)
    for w in header.findChildren(QWidget):
        if isinstance(w, (HeaderTab, HeaderSwapButton)):
            w.set_header_folded(folded)


def refresh_panel_headers(gui) -> None:
    """Theme, font or Display Scale change: re-measure and repaint the three
    headers (sizes and colours are read live, nothing to restyle)."""
    for attr in HEADER_ATTRS:
        header = getattr(gui, attr, None)
        if header is not None and hasattr(header, "refresh"):
            header.refresh()
