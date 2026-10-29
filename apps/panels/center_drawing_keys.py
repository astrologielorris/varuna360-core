# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Panel widgets shared by the center drawings (SPEC-VAC-001 §4.0, §4.4; SPEC-TJK-003 §4.4):
``PlanetKeyHeader`` (a matrix header of compact Strength-family planet keys, lit discs from
``body_disc``), ``VirupaRail`` (the "min. virupas" groove: a tick per mark, a gold notch above
45, a keycap thumb, "shown / total", ticks that can name their mark), ``TourKey`` (right end
of the rail row), ``CellMarks`` (a see-through child of a table's viewport: the tour's ring and
the lit lanes) and ``CenterToggle`` (a drawing's header button with its glyph). Widgets only:
every text comes from the drawing, the state from its controller; a key press calls
``on_key(body)``, the rail emits ``valueChanged(int)``."""
from __future__ import annotations

import math
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QHeaderView, QSizePolicy, QStyle,
                               QStyleOptionHeader, QToolTip, QWidget)

from apps.panels.keycap_paint import paint_keycap
from apps.panels.strength_source_keys import key_font, key_geometry, key_label_px, key_palette
from apps.widgets.panel_header import (HeaderSwapButton, inks, plate_colors, stroke_pen,
                                       widget_scale)
from core.planet_strength_glow import STRENGTH_PALETTE
from core.strength_stone import WHITE, mix

KEY_RADIUS = 7.0
RAIL_MAX = 60
STRONG_NOTCH = 45                # the gold notch: strong marks (virupas >= 45)
TICK_HIT_PX = 4.0                # a tick tooltip answers within this many pixels


# ------------------------------------------------------------------ planet keys
def body_disc(body: str, extra=None, default: str = "#808080") -> str:
    """A lit key's disc: the Strength planet palette, else ``extra[body]``, else ``default``."""
    from ui.qt_theme import desat_hex
    return desat_hex(STRENGTH_PALETTE.get(body) or (extra or {}).get(body, default))


class PlanetKeyHeader(QHeaderView):
    """A matrix header whose sections are compact planet keys: ``bodies`` in section
    order, ``labels[body]`` the keycap label, ``disc(body)`` the lit key's disc colour,
    ``sizing`` = (column header height, row height) callables for ``fit_to_font``."""

    def __init__(self, orientation, bodies: Sequence[str], labels, disc: Callable[[str], str],
                 sizing, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setHighlightSections(False)
        self.setSectionsClickable(True)
        self._bodies = tuple(bodies)
        self._labels = labels
        self._disc = disc
        self._sizing = sizing
        self._lit = frozenset()
        self._hover = None
        self._pressing = None
        self.on_key = None            # callable(body) set by the controller

    # -- state ----------------------------------------------------------------
    def body(self, logical):
        return self._bodies[logical] if 0 <= logical < len(self._bodies) else None

    def set_lit(self, lit):
        lit = frozenset(lit)
        if lit != self._lit:
            self._lit = lit
            self.viewport().update()

    # -- size -----------------------------------------------------------------
    def key_geo(self):
        return key_geometry(key_label_px(), compact=True)

    def key_height(self) -> int:
        g = self.key_geo()
        fm = QFontMetricsF(key_font(self.font(), g["px"]))
        return int(math.ceil(g["top"] + math.ceil(fm.height()) + 2 * g["vpad"] + g["lip"]
                             + g["bottom"]))

    def key_width(self) -> int:
        g = self.key_geo()
        fm = QFontMetricsF(key_font(self.font(), g["px"]))
        label = max((fm.horizontalAdvance(self._labels[b]) for b in self._bodies), default=0)
        return int(math.ceil(g["ml"] + g["mr"] + 2 * g["hpad"] + g["d"] + g["gap"] + label + 1))

    def fit_to_font(self):
        """Horizontal: header height. Vertical: header width and the row height
        (max of the table's own row height and a key). Both re-fit together, from
        relayout_info_panels and at install."""
        table = self.parent()
        column_height, row_height = self._sizing
        if self.orientation() == Qt.Orientation.Horizontal:
            self.setFixedHeight(max(column_height(), self.key_height()))
            other = table.verticalHeader() if table is not None else None
            if isinstance(other, PlanetKeyHeader):
                other.fit_to_font()
        else:
            self.setFixedWidth(self.key_width())
            self.setDefaultSectionSize(max(row_height(), self.key_height()))
        self.viewport().update()

    # -- mouse (a key press toggles; a double click is a second press) ----------
    def mousePressEvent(self, e):
        logical = self.logicalIndexAt(e.position().toPoint())
        if self.body(logical) and e.button() == Qt.MouseButton.LeftButton:
            self._pressing = logical
            self.viewport().update()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        logical = self.logicalIndexAt(e.position().toPoint())
        held, self._pressing = self._pressing, None
        if held is not None:
            self.viewport().update()
            e.accept()
            if logical == held and callable(self.on_key):
                self.on_key(self.body(logical))
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.body(self.logicalIndexAt(e.position().toPoint())):
            self.mousePressEvent(e)
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        logical = self.logicalIndexAt(e.position().toPoint())
        logical = logical if self.body(logical) else None
        if logical != self._hover:
            self._hover = logical
            self.viewport().update()
        if self._pressing is not None:
            e.accept()
            return
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.viewport().update()
        super().leaveEvent(e)

    # -- paint ----------------------------------------------------------------
    def paintSection(self, painter, rect, logical):
        body = self.body(logical)
        if body is None or not rect.isValid():
            super().paintSection(painter, rect, logical)
            return
        opt = QStyleOptionHeader()
        self.initStyleOptionForIndex(opt, logical)
        opt.rect = rect
        opt.text = ""
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header, opt, painter, self)
        painter.restore()
        geo = self.key_geo()
        if rect.width() < self.key_width():
            # a narrow column key: no lamp, so the code itself stays readable
            geo = dict(geo, d=0.0, gap=0.0, hpad=1.0, ml=0.5, mr=1.0)
        painter.save()
        paint_keycap(painter, QRectF(rect), self._labels[body], lit=body in self._lit,
                     pressing=(logical == self._pressing), hover=(logical == self._hover),
                     geo=geo, font=key_font(self.font(), geo["px"]), pal=key_palette(),
                     radius_cap=KEY_RADIUS, disc=self._disc(body))
        painter.restore()


def install_key_headers(table, make_header):
    """Give a matrix its two key headers, ``make_header(orientation, table)`` building
    each; returns (horizontal, vertical)."""
    out = []
    for orientation in (Qt.Orientation.Horizontal, Qt.Orientation.Vertical):
        old = table.horizontalHeader() if orientation == Qt.Orientation.Horizontal else table.verticalHeader()
        header = make_header(orientation, table)
        header.setDefaultAlignment(old.defaultAlignment())
        header.setMinimumSectionSize(1)
        if orientation == Qt.Orientation.Horizontal:
            header.setStretchLastSection(False)
            table.setHorizontalHeader(header)        # Qt deletes the old header
            for col in range(table.columnCount()):
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        else:
            table.setVerticalHeader(header)
            header.setVisible(True)
        out.append(header)
    out[0].fit_to_font()
    return tuple(out)


# ------------------------------------------------------------------ virupa rail
class VirupaRail(QWidget):
    """Min. virupas 0-60: groove, one tick per mark in its colour, a gold notch above 45,
    the 0/15/30/45/60 scale, a keycap thumb with the value, the part left of the thumb
    tinted (its ticks faded), then "shown / total". ``label`` is painted before the
    groove; ``count_sample`` sizes the count; ``tick_text(index)`` (optional) names the
    tick under the cursor in a tooltip, else the widget's own tooltip shows."""

    valueChanged = Signal(int)

    def __init__(self, label: str, count_sample: str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)
        self._label = label
        self._count_sample = count_sample
        self._value = 0
        self._ticks = ()           # (virupas, colour hex)
        self._counts = (0, 0)
        self.tick_text: Optional[Callable[[int], str]] = None
        self.refresh_size()

    # -- state ----------------------------------------------------------------
    def value(self) -> int:
        return self._value

    def set_value(self, value, emit=False):
        value = max(0, min(RAIL_MAX, int(value)))
        if value != self._value:
            self._value = value
            self.update()
            if emit:
                self.valueChanged.emit(value)

    def set_ticks(self, ticks):
        self._ticks = tuple(ticks)
        self.update()

    def set_counts(self, shown, total):
        if (shown, total) != self._counts:
            self._counts = (shown, total)
            self.update()

    # -- geometry -------------------------------------------------------------
    def _font(self, bold=False):
        from ui.qt_theme import scaled_area_px
        f = QFont(self.font())
        f.setPixelSize(max(9, int(scaled_area_px("tables") * 0.9)))
        f.setBold(bold)
        return f

    def refresh_size(self):
        fm = QFontMetricsF(self._font())
        self.setFixedHeight(int(math.ceil(fm.height() * 2.9)))
        self.updateGeometry()

    def _layout(self):
        """(label rect, groove rect, count rect, thumb width) for the current width."""
        fm = QFontMetricsF(self._font())
        fb = QFontMetricsF(self._font(True))
        h = float(self.height())
        pad = 6.0
        label_w = fm.horizontalAdvance(self._label) + pad
        count_w = fb.horizontalAdvance(self._count_sample) + pad
        thumb_w = fb.horizontalAdvance(str(RAIL_MAX)) + 12.0
        top = h * 0.18
        groove_h = max(5.0, h * 0.16)
        x0 = pad + label_w + thumb_w / 2
        x1 = max(x0 + 20.0, self.width() - pad - count_w - thumb_w / 2)
        groove = QRectF(x0, top + h * 0.17, x1 - x0, groove_h)
        return (QRectF(pad, 0, label_w, top * 2 + h * 0.34), groove,
                QRectF(self.width() - pad - count_w, 0, count_w, top * 2 + h * 0.34), thumb_w)

    def _x_of(self, value, groove):
        return groove.left() + groove.width() * value / RAIL_MAX

    def _value_at(self, x):
        groove = self._layout()[1]
        if groove.width() <= 0:
            return self._value
        return int(round((x - groove.left()) / groove.width() * RAIL_MAX))

    def tick_at(self, x: float) -> Optional[int]:
        """The index of the tick nearest ``x`` within TICK_HIT_PX, or None."""
        groove = self._layout()[1]
        best, best_d = None, TICK_HIT_PX
        for i, (virupas, _colour) in enumerate(self._ticks):
            d = abs(self._x_of(max(0.0, min(RAIL_MAX, virupas)), groove) - x)
            if d <= best_d:
                best, best_d = i, d
        return best

    # -- input ----------------------------------------------------------------
    def event(self, e):
        if e.type() == QEvent.Type.ToolTip and callable(self.tick_text):
            index = self.tick_at(e.pos().x())
            if index is not None:
                QToolTip.showText(e.globalPos(), self.tick_text(index), self)
                return True
        return super().event(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_value(self._value_at(e.position().x()), emit=True)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.set_value(self._value_at(e.position().x()), emit=True)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def keyPressEvent(self, e):
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1,
                 Qt.Key.Key_Up: 1, Qt.Key.Key_PageDown: -5, Qt.Key.Key_PageUp: 5}
        if e.key() in steps:
            self.set_value(self._value + steps[e.key()], emit=True)
        elif e.key() == Qt.Key.Key_Home:
            self.set_value(0, emit=True)
        elif e.key() == Qt.Key.Key_End:
            self.set_value(RAIL_MAX, emit=True)
        else:
            super().keyPressEvent(e)
            return
        e.accept()

    # -- paint ----------------------------------------------------------------
    def paintEvent(self, _event):
        from ui.qt_theme import get_theme_colors
        th = get_theme_colors()
        pal = key_palette()
        label_r, groove, count_r, thumb_w = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        text = QColor(th["secondary_text"])
        p.setFont(self._font())
        p.setPen(text)
        p.drawText(label_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
        tick_h = self._paint_groove(p, pal, groove)
        self._paint_scale(p, pal, groove, tick_h)
        self._paint_thumb(p, pal, groove, thumb_w)
        p.setFont(self._font(True))
        p.setPen(text)
        shown, total = self._counts
        p.drawText(count_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   f"{shown} / {total}")
        if self.hasFocus():
            ring = QColor(pal["accent"])
            ring.setAlphaF(0.6)
            p.setPen(QPen(ring, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        p.end()

    def _paint_groove(self, p, pal, groove) -> float:
        """Recessed groove, its tint left of the thumb, one tick per mark (faded left of
        the thumb), the gold notch above 45. Returns the tick height."""
        from ui.qt_theme import GOLD, desat_hex
        r = groove.height() / 2
        p.setPen(QPen(QColor(pal["edge"]), 1.0))
        p.setBrush(QColor(pal["sunk_top"]))
        p.drawRoundedRect(groove, r, r)
        xv = self._x_of(self._value, groove)
        if self._value > 0:
            tint = QColor(pal["accent"])
            tint.setAlphaF(0.35)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(QRectF(groove.left(), groove.top(), xv - groove.left(), groove.height()), r, r)
        tick_h = groove.height() * 2.2
        for virupas, colour in self._ticks:
            x = self._x_of(max(0.0, min(RAIL_MAX, virupas)), groove)
            c = QColor(desat_hex(colour))
            c.setAlphaF(0.28 if virupas < self._value else 0.95)
            p.setPen(QPen(c, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x, groove.center().y() - tick_h / 2),
                       QPointF(x, groove.center().y() + tick_h / 2))
        xn = self._x_of(STRONG_NOTCH, groove)
        notch = QPainterPath()
        notch.moveTo(xn - 4, groove.top() - tick_h * 0.55 - 4)
        notch.lineTo(xn + 4, groove.top() - tick_h * 0.55 - 4)
        notch.lineTo(xn, groove.top() - tick_h * 0.55 + 2)
        notch.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(desat_hex(GOLD)))
        p.drawPath(notch)
        return tick_h

    def _paint_scale(self, p, pal, groove, tick_h):
        small = self._font()
        small.setPixelSize(max(8, int(small.pixelSize() * 0.8)))
        p.setFont(small)
        p.setPen(QColor(pal["muted"]))
        sfm = QFontMetricsF(small)
        for mark in (0, 15, 30, 45, 60):
            x = self._x_of(mark, groove)
            p.drawText(QRectF(x - 20, groove.bottom() + tick_h * 0.6, 40, sfm.height()),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, str(mark))

    def _paint_thumb(self, p, pal, groove, thumb_w):
        """The keycap thumb with the value."""
        bold = self._font(True)
        fb = QFontMetricsF(bold)
        th_h = fb.height() + 6
        xv = self._x_of(self._value, groove)
        cell = QRectF(xv - thumb_w / 2, groove.center().y() - th_h / 2 - 1, thumb_w, th_h + 2)
        geo = {"px": bold.pixelSize(), "top": 0.0, "bottom": 0.0, "ml": 0.0, "mr": 0.0,
               "lip": 2.0, "vpad": 2.0, "hpad": 2.0, "d": 0.0, "gap": 0.0}
        thumb_pal = dict(pal, edge=pal["accent"], muted=pal["accent"])
        paint_keycap(p, cell, str(self._value), lit=False, pressing=False, hover=True,
                     geo=geo, font=bold, pal=thumb_pal, radius_cap=5.0)


# ------------------------------------------------------------------ tour key
class TourKey(QAbstractButton):
    """The tour key at the right end of the rail row: a Strength-family keycap whose lamp
    is lit while the tour plays. ``tooltips`` = (idle, playing). The controller sets the
    state; a click emits ``clicked``. Same height as the rail; the key sits on the rail's
    count line."""

    def __init__(self, text: str, tooltips, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._tooltips = tuple(tooltips)
        self._playing = False
        self.setToolTip(self._tooltips[0])
        self.refresh_size()

    def playing(self) -> bool:
        return self._playing

    def set_playing(self, playing):
        playing = bool(playing)
        if playing != self._playing:
            self._playing = playing
            self.setToolTip(self._tooltips[int(playing)])
            self.update()

    def refresh_size(self, height=None):
        """Font / scale change: the key re-fits; ``height`` is the rail's height."""
        font = key_font(self.font())
        geo = key_geometry(font.pixelSize())
        fm = QFontMetricsF(font)
        width = fm.horizontalAdvance(self.text()) + geo["d"] + geo["gap"] + 2 * geo["hpad"] + 10
        self.setFixedSize(int(math.ceil(width)), int(height or math.ceil(fm.height() * 2.9)))
        self.updateGeometry()

    def sizeHint(self):
        return self.size()

    def paintEvent(self, _event):
        font = key_font(self.font())
        geo = dict(key_geometry(font.pixelSize()), top=0.0, bottom=0.0, ml=1.0, mr=4.0)
        key_h = QFontMetricsF(font).height() + geo["lip"] + 2 * geo["vpad"]
        cy = self.height() * 0.35                    # the rail's label and count line
        cell = QRectF(0, max(0.0, cy - key_h / 2), self.width(), min(key_h, self.height()))
        p = QPainter(self)
        paint_keycap(p, cell, self.text(), lit=self._playing, pressing=self.isDown(),
                     hover=self.underMouse(), geo=geo, font=font, pal=key_palette(),
                     radius_cap=KEY_RADIUS)
        p.end()


# ------------------------------------------------------------------ cell marks
class CellMarks(QWidget):
    """Marks over a matrix (SPEC-TJK-003 §4.9, SPEC-VAC-001 §3.5): an accent ring around
    the tour's cells and the lit rows / columns tinted with the accent at alpha .12. A
    see-through child of the table's viewport, cells and delegate untouched; it re-lays
    out on viewport resize, header section resize, scroll and font change."""

    TINT_ALPHA = 0.12

    def __init__(self, table):
        super().__init__(table.viewport())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._table = table
        self._cells = ()
        self._rows = ()
        self._columns = ()
        self._follower = _Relayout(self.relayout, table)
        self.hide()

    def show_cells(self, cells):
        """``cells``: (row, column) pairs of the ring; empty drops the ring."""
        self._cells = tuple(cells)
        self.relayout()

    def show_lanes(self, rows=(), columns=()):
        """Tint these rows and columns (lit keys); empty drops the tint."""
        self._rows, self._columns = tuple(rows), tuple(columns)
        self.relayout()

    def relayout(self, *_):
        if not (self._cells or self._rows or self._columns):
            self.hide()
            return
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _event):
        from ui.qt_theme import get_theme_colors
        accent = QColor(get_theme_colors()["primary"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._rows or self._columns:
            self._paint_lanes(p, accent)
        p.setPen(QPen(accent, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        model = self._table.model()
        for row, col in self._cells:
            rect = QRectF(self._table.visualRect(model.index(row, col)))
            p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 3, 3)
        p.end()

    def _paint_lanes(self, p, accent):
        tint = QColor(accent)
        tint.setAlphaF(self.TINT_ALPHA)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        table, area = self._table, QRectF(self.rect())
        for row in self._rows:
            p.drawRect(QRectF(0, table.rowViewportPosition(row), area.width(), table.rowHeight(row)))
        for col in self._columns:
            p.drawRect(QRectF(table.columnViewportPosition(col), 0, table.columnWidth(col), area.height()))


class _Relayout(QObject):
    """Calls ``relayout`` when the table's viewport resizes, a header section resizes,
    the table scrolls or its font changes."""

    def __init__(self, relayout, table):
        super().__init__(table)
        self._relayout = relayout
        table.viewport().installEventFilter(self)
        table.installEventFilter(self)
        table.horizontalHeader().sectionResized.connect(relayout)
        table.verticalHeader().sectionResized.connect(relayout)
        table.horizontalScrollBar().valueChanged.connect(relayout)
        table.verticalScrollBar().valueChanged.connect(relayout)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange):
            self._relayout()
        return False


# ------------------------------------------------------------------ toggle
class CenterToggle(HeaderSwapButton):
    """A drawing's header button: OFF grey, ON in the theme accent with a small lit dot.
    ``glyph(painter, square, scale)`` draws the drawing's glyph inside its 14 px square.
    A ``HeaderSwapButton`` so ``set_header_folded`` folds it with the header."""

    def __init__(self, glyph: Callable[[QPainter, QRectF, float], None], parent=None):
        super().__init__(parent)
        self._glyph = glyph

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
        fill, glyph = plate_colors(self, ink, self.is_on())
        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(plate, 5 * fs, 5 * fs)
        box = 14.0 * fs
        sq = QRectF(plate.center().x() - box / 2, plate.center().y() - box / 2, box, box)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(stroke_pen(glyph, max(1.1, 1.3 * fs)))
        self._glyph(p, sq, fs)
        if self.is_on():
            dot = QColor(mix(QColor(glyph).name(), WHITE, 0.25))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(sq.right() - 0.5 * fs, sq.top() + 0.5 * fs), 2.2 * fs, 2.2 * fs)
        p.end()
