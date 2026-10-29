# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The V1 | V2 switch of the Strength panel (SPEC-RST-001 D-22, td-9scg9).

Two small keycaps in the style of the DIGBALA / UCCHA / CHESTA / DUC BALA keys
(``strength_source_keys.key_palette``, same lamp-less face, the lit one sunk with the
accent edge). Placement (Lorris, 2026-10-14): in the empty area of the Strength table
below its last planet row, left-aligned, never in the title row and never a new row
above the table. ``SwitchPlacer`` keeps it there as the table resizes, scrolls or
changes rows: right under the last row while there is room, else in a bottom strip the
table reserves for it (``StrengthTable.reserve``, a bottom viewport margin), so it never covers a row (the rows scroll instead).
As a child of the table it shows exactly when the Strength page shows.

A click writes ``chart.retinue_strength_style`` and redraws the chart hosts on screen
through the source keys' own path (``StrengthSourceCycler.redraw_hosts``); with the
strength display off nothing reads the look, so nothing is redrawn. The lit half
follows the setting through the settings manager's keyed change callback (any
writer). Rule 4b: no window attribute; the switch drops its subscription when destroyed.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QTableWidget, QWidget

from core import jewel_lamp as jl
from core import settings_registry as registry
from core.retinue_strength import KEY_ON
from core.i18n import t

LABELS = jl.STYLES          # painted as "V1" / "V2" (value.upper(), not translated)


def legend() -> str:
    return t("strength.style_switch.tip",
             "Strength look. V1: Lamplight. V2: Jewel Lamp. Colour = Uccha, dignity. "
             "Cut = Digbala, aim reached. Light = Chesta, how much the planet shines.")


class StrengthStyleSwitch(QWidget):
    """``V1 | V2``: click a half to choose the look (the lit half does nothing)."""

    def __init__(self, gui=None, settings=None, parent=None):
        super().__init__(parent)
        if settings is None:
            from managers.settings_manager import get_settings
            settings = get_settings()
        self._settings, self._gui = settings, gui
        self._hover = None
        self.setObjectName("strength_style_switch")
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(legend())
        self.setAccessibleName(t("strength.style_switch.name", "Strength look"))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._subscribe()

    # -- state ------------------------------------------------------------
    def style_value(self) -> str:
        return jl.style_from_settings(self._settings.get)

    def _subscribe(self):
        import shiboken6
        me = self

        def _changed(_key, _value):
            if shiboken6.isValid(me):
                me.update()

        self._settings.on_changed(jl.KEY_STYLE, _changed)
        settings = self._settings
        self.destroyed.connect(lambda *_: settings.remove_on_changed(jl.KEY_STYLE, _changed))

    def select(self, value: str):
        """Write the look and redraw the charts on screen (the source keys' path)."""
        from managers.retinue_strength_shortcut import StrengthSourceCycler
        s = self._settings
        if value == self.style_value():
            return None
        cycler = StrengthSourceCycler(self._gui)
        if s.is_locked(jl.KEY_STYLE):
            cycler.say(t("strength.style_switch.locked", "Strength look is locked in Settings"))
            return None
        s.persist_runtime_change(jl.KEY_STYLE, value, save=False)
        s.flush()
        if bool(s.get(KEY_ON, registry.default(KEY_ON))):
            cycler.redraw_hosts()
        self.update()
        return value

    # -- geometry ---------------------------------------------------------
    def _geometry(self):
        from apps.panels.strength_source_keys import key_font, key_geometry
        g = key_geometry()
        font = key_font(self.font(), g["px"])
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(LABELS[-1].upper()) + 2 * g["hpad"] + 2 * g["px"] * 0.35
        h = fm.height() + 2 * max(2.0, g["vpad"] * 0.5) + g["lip"]
        return g, font, w, h

    def sizeHint(self):
        g, _font, w, h = self._geometry()
        return QSize(int(2 * w + g["ml"] + g["mr"] + 2), int(h + g["top"] + g["bottom"]))

    def minimumSizeHint(self):
        return self.sizeHint()

    def _half(self, x) -> int:
        return 0 if x < self.width() / 2 else 1

    # -- mouse ------------------------------------------------------------
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.select(LABELS[self._half(e.position().x())])
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        half = self._half(e.position().x())
        if half != self._hover:
            self._hover = half
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = None
        self.update()
        super().leaveEvent(e)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, _event):
        from apps.panels.strength_source_keys import key_palette
        from ui.qt_theme import scaled_px
        g, font, w, h = self._geometry()
        pal = key_palette()
        lit = self.style_value()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(font)
        radius = min(float(scaled_px(6)), h * 0.26)
        for i, value in enumerate(LABELS):
            label = value.upper()
            body = QRectF(g["ml"] + i * (w + 2), g["top"], w, h)
            sunk = value == lit
            lip = g["lip"]
            face = QRectF(body.left(), body.top() + (lip - 1 if sunk else 0), w, h - lip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["lip"]))
            p.drawRoundedRect(body, radius, radius)
            grad = QLinearGradient(face.topLeft(), face.bottomLeft())
            grad.setColorAt(0.0, QColor(pal["sunk_top" if sunk else "face_top"]))
            grad.setColorAt(1.0, QColor(pal["sunk_bot" if sunk else "face_bot"]))
            edge = pal["accent"] if (sunk or self._hover == i) else pal["edge"]
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(edge), 1.0))
            p.drawRoundedRect(face.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            p.setPen(QColor(pal["accent"] if sunk else pal["text"]))
            p.drawText(face, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


GAP = 6          # px between the last row and the switch, and to the table's left edge


class StrengthTable(QTableWidget):
    """The Strength table: a ``QTableWidget`` that can keep a bottom strip under its
    rows for the switch. ``QTableView.updateGeometries`` sets the viewport margins for
    its headers (bottom 0), so the reserved bottom is added back right after it."""

    reserve = 0

    def updateGeometries(self):
        super().updateGeometries()
        m = self.viewportMargins()
        if m.bottom() != self.reserve:
            self.setViewportMargins(m.left(), m.top(), m.right(), self.reserve)


class SwitchPlacer(QObject):
    """Keeps the switch under the table's last row (or in a reserved bottom margin)."""

    def __init__(self, table, switch):
        super().__init__(table)
        self._table, self._switch, self._margin, self._seen = table, switch, 0, None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.place)
        table.installEventFilter(self)
        # The viewport changes size on its own (scrollbar shown, margins set, the page
        # laid out after being hidden) without the table resizing, and a new row height
        # (setDefaultSectionSize: font, relayout) emits no header signal: its repaint
        # is the one sure sign, so the viewport is watched too.
        table.viewport().installEventFilter(self)
        table.verticalHeader().sectionResized.connect(lambda *_: self.place())
        table.verticalHeader().geometriesChanged.connect(self.place)
        table.horizontalHeader().geometriesChanged.connect(self.place)
        table.verticalScrollBar().valueChanged.connect(lambda *_: self.place())
        table.verticalScrollBar().rangeChanged.connect(lambda *_: self.place_later())
        table.model().rowsInserted.connect(lambda *_: self.place_later())
        table.model().rowsRemoved.connect(lambda *_: self.place_later())

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Paint:
            if self._state() != self._seen:
                self.place_later()
        elif kind in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest,
                      QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.place()
            self.place_later()
        return False

    def place_later(self):
        """Place again once the pending layout has settled (coalesced)."""
        self._timer.start(0)

    def _state(self):
        t = self._table
        return (t.verticalHeader().length(), t.verticalScrollBar().value(),
                t.viewport().geometry().getRect(), t.size().toTuple())

    def _room(self):
        """Height under the column header for rows and strip together: read from the
        table's own frame, never from the viewport (stale while hidden, and it already
        lost the strip), so the choice cannot flip on its own result."""
        t = self._table
        hsb = t.horizontalScrollBar()
        sb = hsb.height() if hsb.isVisible() else 0
        return t.contentsRect().bottom() + 1 - t.viewport().geometry().top() - sb

    def place(self):
        """Under the last row when all rows fit, else in the strip the table reserves."""
        import shiboken6
        table, sw = self._table, self._switch
        if not (shiboken6.isValid(table) and shiboken6.isValid(sw)):
            return
        hint = sw.sizeHint()
        need = hint.height() + 2 * GAP
        room = self._room()
        length = table.verticalHeader().length()
        # Decided on the full row length, never the scroll position: the rows either
        # all fit with the switch under them, or the strip is kept (no flip-flop).
        fits = length + need <= room
        margin = 0 if fits or not isinstance(table, StrengthTable) else need
        if margin != self._margin:
            self._margin = table.reserve = margin
            table.updateGeometries()                      # the rows scroll, never covered
        top = table.viewport().geometry().top()
        if margin == 0:
            y = top + length - table.verticalScrollBar().value() + GAP
        else:
            y = top + room - need + GAP                   # the strip, under the viewport
        sw.setGeometry(table.viewport().geometry().left() + GAP, int(y), hint.width(), hint.height())
        sw.raise_()
        self._seen = self._state()


def install_strength_style_switch(table, gui=None, settings=None) -> StrengthStyleSwitch:
    """Put the switch in the Strength table's empty area below its last planet row."""
    switch = StrengthStyleSwitch(gui=gui, settings=settings, parent=table)
    switch._placer = SwitchPlacer(table, switch)
    switch.show()
    switch._placer.place()
    return switch
