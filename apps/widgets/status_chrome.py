# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Status-bar chart chrome — the position-ORDER control (and, from WI-3, the
fullscreen button). SPEC-FSV-001.

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

import weakref

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from apps.widgets.cot_index_item import COT_ORDER_KEY, read_persisted_order
from core.cards_of_truth_data import ORDER_LABELS


class _StatusPill(QWidget):
    """A small painted pill for ``QMainWindow.statusBar().addPermanentWidget``.

    Subclasses supply ``_text()`` (the pill's label or glyph) and ``_activate()``
    (the click action). The paint, hover and sizing are shared so the ORDER pill
    and the fullscreen pill cannot drift into two different-looking chips.
    """

    PAD_X = 12
    PAD_Y = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    # -- subclass hooks ---------------------------------------------------

    def _text(self):
        raise NotImplementedError

    def _activate(self):
        raise NotImplementedError

    # -- typography / sizing ---------------------------------------------

    def _font(self):
        from ui.qt_theme import get_scale_factor
        f = QFont("Inter")
        f.setPixelSize(max(6, int(round(10.0 * get_scale_factor()))))
        f.setWeight(QFont.Weight.Bold)
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        return f

    def sizeHint(self):
        fm = QFontMetrics(self._font())
        width = fm.horizontalAdvance(self._text()) + 2 * self.PAD_X
        height = fm.height() + 2 * self.PAD_Y
        return QSize(int(width), int(height))

    def minimumSizeHint(self):
        return self.sizeHint()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _event):
        from ui.qt_theme import GOLD, get_theme_colors

        colors = get_theme_colors()
        fill = QColor(colors["secondary"])
        fill.setAlphaF(0.94 if self._hover else 0.80)
        border = QColor(GOLD)
        border.setAlphaF(0.75 if self._hover else 0.45)
        ink = QColor(colors["primary_text"])
        if not self._hover:
            ink.setAlphaF(0.80)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2.0
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(rect, radius, radius)
        p.setFont(self._font())
        p.setPen(QPen(ink))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text())
        p.end()

    def refresh_theme(self):
        """Repaint under the new palette.

        Colours are read live in ``paintEvent`` (SPEC-THM-001 live-read
        pattern), so a theme switch needs only a repaint — no cached stylesheet
        to re-apply.
        """
        try:
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


class StatusOrderButton(_StatusPill):
    """The always-visible position-order control — SAFE PLAN-1 WI-2.

    One control, one home, on all five chart pages. Unlike the retired viewport
    pill it does NOT gate on ``cot.show_in_chart``: it is always shown, because
    the order also drives the Cards of Truth page (page 4) which is not governed
    by that setting, and because users must never have to hunt for it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # WEAK, per apps/widgets/cot_index_item's module docstring:
        # SettingsManager.on_changed keeps its callbacks for the life of the
        # process and never unsubscribes, so a strong closure over ``self``
        # would pin this widget. It lives as long as the main window anyway,
        # but the weak pattern is the house convention and costs nothing.
        _ref = weakref.ref(self)

        def _order_hook(_key, _value, _ref=_ref):
            button = _ref()
            if button is not None:
                button._on_order_changed()

        self._order_hook = _order_hook
        try:
            from managers.settings_manager import get_settings
            get_settings().on_changed(COT_ORDER_KEY, _order_hook)
        except Exception:                                # noqa: BLE001
            pass

    def _text(self):
        order = read_persisted_order()
        return f"Order · {ORDER_LABELS.get(order, order)}"

    def _on_order_changed(self):
        try:
            # "Solar System" and "Week Day" differ in width, so the status bar
            # must re-lay-out, not just repaint.
            self.updateGeometry()
            self.update()
        except RuntimeError:
            pass

    def _activate(self):
        current = read_persisted_order()
        try:
            from managers.settings_manager import get_settings
            get_settings().set(
                COT_ORDER_KEY,
                "vedic" if current == "solar_system" else "solar_system")
        except Exception as e:                           # noqa: BLE001
            print(f"[FSV] Warning: could not switch the position order: {e}")


class StatusFullscreenButton(_StatusPill):
    """The fullscreen toggle — SAFE PLAN-1 WI-3, right of the ORDER pill.

    A glyph pill, the mouse equivalent of the app-wide ``F`` key: both call the
    same ``ViewFloatManager`` toggle. Always visible on all five chart pages.
    """

    GLYPH = "⛶"        # SQUARE FOUR CORNERS — the fullscreen convention

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
