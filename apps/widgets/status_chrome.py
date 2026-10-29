# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Status-bar chart chrome: the captioned action pills (AI capture, AI readings,
AI setting, AI search) and the fullscreen button. SPEC-FSV-001.

The position-ORDER pill described below was removed from the status bar on
2026-10-19 (Lorris: not good enough there; the AI search pill takes the
space). The order stays in Settings, the Placements dialog and the Cards of
Truth view, all on ``cot.planet_order``. The history is kept for context.

Why this module exists
----------------------
The position-order control used to live inside the chart canvas: a viewport
pill on three QGraphicsView charts (``CotOrderButton``) plus a fourth painted
copy inside the Cards of Truth view. Four homes, three of them gated on
``cot.show_in_chart`` (default off), so a user who wanted to flip the order
first had to find the control — and it moved, or vanished, page to page.

SAFE PLAN-1 WI-2 collapses all of that into ONE control with ONE home: a
permanent widget on the right of ``QMainWindow.statusBar()``, the SAME button
in the SAME place on all five chart pages, always visible (Lorris, explicit
2026-07-29). It shares ``cot.planet_order`` with the Settings combo, the
Placements dialog and the Cards of Truth view, so no two surfaces can disagree
about which order is in force.

Painted, not a QSS ``QPushButton``
----------------------------------
The pill reuses the Cards of Truth order-pill recipe (secondary fill, gold
hairline, hover brighten, uppercase Inter) so it reads as the SAME control
users already knew, merely relocated. It reads ``get_theme_colors()`` LIVE in
``paintEvent``; its colours therefore never freeze at construction — the exact
failure ``ThemedStyleMixin._register_themed`` exists to prevent (SPEC-THM-001)
— and ``refresh_theme()`` is a bare repaint, the same live-read pattern
``core_gui_qt`` already uses for the Cards of Truth view. The host
``QMainWindow`` is not a ``ThemedStyleMixin``, so it drives the repaint through
``_on_theme_changed -> _refresh_attr('status_order_button')``.
"""


from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget


# Partner reading pill (SPEC-PRT-001 §4.3.1): semantic red, a Rule 20
# exception like red/green, beside the GOLD hairline the other pills use.
# White caption on both (contrast >= 4.5:1).
PARTNER_RED_LIGHT = "#B71C1C"
PARTNER_RED_DARK = "#C62828"


def partner_red():
    """The partner pill red for the current theme (by theme luminance)."""
    from ui.qt_theme import is_light_theme
    return PARTNER_RED_LIGHT if is_light_theme() else PARTNER_RED_DARK


class _StatusPill(QWidget):
    """A small painted pill for ``QMainWindow.statusBar().addPermanentWidget``.

    Subclasses supply ``_text()`` (the pill's label or glyph) and ``_activate()``
    (the click action). The paint, hover and sizing are shared so the action pills
    and the fullscreen pill cannot drift into different-looking chips.
    """

    PAD_X = 12
    PAD_Y = 5
    _BORDER = 1.0            # the hairline paintEvent insets by (width-1.0)
    _MAX_PREF_WIDTH = 260    # deliberate preferred-width cap: past this a large
                             # font degrades to elide+tooltip, not a wide pill
    # Text captions elide to the available width and grow a full-text tooltip
    # when clipped; a glyph subclass (fullscreen) sets this False — a symbol is
    # one cell wide, must never be elided, and owns a fixed help tooltip.
    ELIDE = True
    # A help tooltip assigned with setToolTip (the AI setting pill's approved
    # tip): the elision never clears or replaces it (W6c review F4).
    _help_tip = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._apply_min_height()

    def setToolTip(self, tip):
        """An explicit help tooltip: kept through every paint."""
        self._help_tip = tip or None
        QWidget.setToolTip(self, tip)

    # -- subclass hooks ---------------------------------------------------

    def _text(self):
        raise NotImplementedError

    def _activate(self):
        raise NotImplementedError

    # -- typography / sizing ---------------------------------------------

    def _font(self):
        # SPEC-FONT-001 B7-a4: the pill is a text caption — exactly what the
        # 'status' area governs — so it follows that area, not a bare scale
        # literal. scaled_tier_size preserves the 10px default at 1.0/defaults
        # (parity) while scaling with the status-area setting AND global scale.
        # (The fullscreen SUBCLASS overrides this with a glyph-only font that
        # stays scale-only — a symbol renders as an icon, not text: SKIP.)
        from ui.qt_theme import scaled_tier_size
        f = QFont("Inter")
        f.setPixelSize(max(6, scaled_tier_size(10.0, 'status')))
        f.setWeight(QFont.Weight.Bold)
        # Normal case (AI setting redesign, td-bztjj item 9, Lorris
        # 2026-10-11): every pill shows its caption as written. Set explicitly
        # so a theme's ``text-transform: uppercase`` never resolves into it.
        f.setCapitalization(QFont.Capitalization.MixedCase)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        return f

    def _text_avail(self, total_width):
        """Inner width available to the DRAWN caption at a given widget width.

        THE single width computation — paintEvent, sizeHint and the fit oracle
        all route through it, so the 1px painted-border inset (paintEvent draws
        into ``width-1``) can never disagree between measure and paint. That
        disagreement was the round-2 bug: sizeHint omitted the border, so at
        defaults paint had 1px less than the text and elided "…" with a tooltip.
        """
        return (total_width - self._BORDER) - 2 * self.PAD_X

    def _pref_width(self):
        """Preferred pill width: exactly wide enough for the full caption at
        defaults (so `_text_avail(_pref_width) == full text`, no elision), but
        DELIBERATELY capped so a large font degrades to bounded-width + elide +
        tooltip rather than a bar-eating 500px+ pill (FIX-1, B7-a round-3)."""
        full = QFontMetrics(self._font()).horizontalAdvance(self._text())
        natural = full + 2 * self.PAD_X + self._BORDER + 1  # +1 slack: no elision at fit
        if self.ELIDE:
            return min(natural, self._MAX_PREF_WIDTH)
        return natural

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        return QSize(int(self._pref_width()), int(fm.height() + 2 * self.PAD_Y))

    def minimumSizeHint(self):
        # Full HEIGHT (the bar must accommodate the font — never clip the glyph
        # vertically) but a MINIMAL width: the caption elides horizontally in a
        # width-constrained status bar rather than forcing a wide pill that eats
        # the bar (FIX-1). Width floor = one ellipsis + pads + border.
        fm = QFontMetrics(self._font())
        min_w = fm.horizontalAdvance("…") + 2 * self.PAD_X + self._BORDER
        return QSize(int(min_w), int(fm.height() + 2 * self.PAD_Y))

    def _apply_min_height(self):
        """Force the status bar to give at least the font's height so the glyph
        is never vertically clipped (FIX-1: updateGeometry alone did not make
        the bar honor the taller sizeHint). Re-called whenever the font changes."""
        fm = QFontMetrics(self._font())
        self.setMinimumHeight(fm.height() + 2 * self.PAD_Y)

    def _elided_text(self, avail_width):
        """The caption as it will actually be drawn at the given inner width —
        elided with a trailing ellipsis when the full text does not fit. The
        single source both paintEvent and the fit-or-elide oracle read."""
        fm = QFontMetrics(self._font())
        return fm.elidedText(self._text(), Qt.TextElideMode.ElideRight,
                             max(0, int(avail_width)))

    # -- painting ---------------------------------------------------------

    def _pill_colors(self):
        """(fill, border, ink) read live from the theme; a subclass may tint."""
        from ui.qt_theme import GOLD, get_theme_colors

        colors = get_theme_colors()
        fill = QColor(colors["secondary"])
        fill.setAlphaF(0.94 if self._hover else 0.80)
        border = QColor(GOLD)
        border.setAlphaF(0.75 if self._hover else 0.45)
        ink = QColor(colors["primary_text"])
        if not self._hover:
            ink.setAlphaF(0.80)
        return fill, border, ink

    def paintEvent(self, _event):
        fill, border, ink = self._pill_colors()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2.0
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(rect, radius, radius)
        p.setFont(self._font())
        p.setPen(QPen(ink))
        text = self._text()
        if self.ELIDE:
            # Fit-or-elide (FIX-1): draw as much of the caption as the width
            # holds; when clipped, show the full caption in a tooltip instead of
            # slicing a glyph mid-stroke. A pill with its own help tooltip
            # (setToolTip) keeps it: elision only owns the tooltip of a pill
            # without one. _text_avail is THE shared width computation
            # sizeHint and the oracle also use.
            shown = self._elided_text(self._text_avail(self.width()))
            if self._help_tip is None:
                QWidget.setToolTip(self, text if shown != text else "")
            text = shown
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def refresh_theme(self):
        """Repaint under the new palette (and re-lay-out for a new font size).

        Colours are read live in ``paintEvent`` (SPEC-THM-001 live-read
        pattern), so a theme switch needs only a repaint. The font is also read
        live from ``_font()`` (B7-a4, now the 'status' area), so when this is
        called from the FONT fan-out the glyph size changes too. We re-assert the
        minimum HEIGHT from the new font (so the bar accommodates it — FIX-1:
        updateGeometry alone did not) and invalidate the cached geometry; the
        WIDTH is elided in paintEvent, so a width-constrained bar clips cleanly to
        a tooltip rather than slicing the caption (the td-2o8u fixed-geometry
        lesson, hardened after the B7-a review).
        """
        try:
            self._apply_min_height()
            self.updateGeometry()
            self.update()
        except RuntimeError:
            pass

    # -- interaction ------------------------------------------------------

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._activate()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # Qt forwards a double-click to mousePressEvent by default, so without
        # this a fast double-click fires _activate() TWICE — and for a toggle
        # (the ORDER pill) the second firing undoes the first, leaving the
        # control looking dead. Swallow the left-button double-click: the first
        # press already did the acting. (The retired in-canvas order button
        # guarded the same hazard; SPEC-FSV-001, Codex review.)
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class StatusFullscreenButton(_StatusPill):
    """The fullscreen toggle — SAFE PLAN-1 WI-3, at the right of the pills.

    A glyph pill, the mouse equivalent of the app-wide ``F`` key: both call the
    same ``ViewFloatManager`` toggle. Always visible on all five chart pages.
    """

    GLYPH = "⛶"        # SQUARE FOUR CORNERS — the fullscreen convention
    ELIDE = False       # a single symbol is never elided; keeps its help tooltip

    def __init__(self, on_toggle, parent=None):
        super().__init__(parent)
        self._on_toggle = on_toggle
        self.setToolTip("Fullscreen the chart (F; Esc or F to exit)")

    def _font(self):
        # The glyph is a symbol, not a letter: keep the platform's default font
        # family so Qt can substitute a font that actually has it, and do NOT
        # force AllUppercase (which would do nothing here but is misleading).
        from ui.qt_theme import get_scale_factor
        f = QFont()
        f.setPixelSize(max(9, int(round(13.0 * get_scale_factor()))))
        f.setWeight(QFont.Weight.Bold)
        return f

    def _text(self):
        return self.GLYPH

    def _activate(self):
        try:
            self._on_toggle()
        except Exception as e:                           # noqa: BLE001
            print(f"[FSV] Warning: fullscreen toggle failed: {e}")


class StatusCaptureButton(_StatusPill):
    """A captioned action pill: AI capture (SPEC-AIC-001 D-10), AI readings,
    AI setting, AI search (SPEC-FIND-006 §4.3): the mouse entry point to the
    action ``on_capture`` runs."""

    def __init__(self, caption, on_capture, parent=None, keep_case=False):
        # ``keep_case``: draw the caption in its own case instead of the pill
        # recipe's uppercase (the AI setting pill shows its approved words
        # exactly as approved, D-21, Lorris 2026-10-10). Set before the base
        # init, which measures the font.
        self._keep_case = bool(keep_case)
        super().__init__(parent)
        self._caption = caption
        self._on_capture = on_capture

    def _font(self):
        f = super()._font()
        if self._keep_case:
            f.setCapitalization(QFont.Capitalization.MixedCase)
        return f

    def _text(self):
        return self._caption

    def _activate(self):
        try:
            self._on_capture()
        except Exception as e:                           # noqa: BLE001
            print(f"[AIC] Warning: capture failed to start: {e}")


class StatusPartnerButton(StatusCaptureButton):
    """The red partner reading pill (SPEC-PRT-001 §4.3.1), right of the AI
    pills: same recipe, filled with the theme's partner red, white caption."""

    def __init__(self, caption, on_open, parent=None):
        super().__init__(caption, on_open, parent, keep_case=True)

    def _pill_colors(self):
        fill = QColor(partner_red())
        border = QColor(fill).darker(130 if self._hover else 115)
        if self._hover:
            fill = fill.lighter(112)
        return fill, border, QColor("#FFFFFF")
