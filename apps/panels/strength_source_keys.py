# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Strength panel: header keys choose the retinue strength source (SPEC-RST-001 D-20).

The Strength table (PLANET | DIGBALA | UCCHA | CHESTA | DUC BALA) gets a painted
header (``StrengthKeyHeader``): the four strength headers are keycaps in one
exclusive group, each with a small lamp before its label.

- Click an unlit key: ``chart.retinue_strength_on`` True and
  ``chart.retinue_strength_source`` = that column. Click the lit key: display off.
  Click another key while one is lit: switch straight to it.
- The lit key is the same keycap pushed in (sunk: inset shade, lip gone, 2 px down,
  accent edge) with its lamp lit (white centre, soft accent, accent rim, faint accent
  ring). Display off: no key lit.
- In the lit column each planet's value sits on a small rounded stone in that
  planet's own glow colour (``planet_shadow_color``), strength-scaled
  (Moonstone Pill formula); the other columns keep today's cells.
- Size (td-esl0r): the keys follow the Table Headers font. The header height and
  the key columns' minimum widths come from ``scaled_area_px('table_headers')`` so
  the label is always painted at that size; ``fit_to_font`` re-fits them on every
  font / scale refresh (``relayout_info_panels``).

PLANET key (td-e6jsp, D-21): the PLANET header is a key of the same family. It
works only with a lit strength key: pressing it lights it and keeps the lit
strength key, or lights DUC BALA when none is lit; switching the strength key off
switches PLANET off too; switching PLANET off leaves the strength key. While both
are lit, the planets on the charts wear the Ember Aura (``chart.planet_glow_mode``
= "strength", ``core.planet_strength_glow``) and each planet symbol in the PLANET
column sits on a light disc in its strength colour. The stones and the discs use
the one strength palette (``STRENGTH_PALETTE``; the Moon is white).

Writes go through ``StrengthSourceCycler.select`` (the F10 path: write with
``persist_runtime_change``, keep the Settings page in step, redraw the chart hosts
with the Apply tail's own calls, no overlay). The lit key and the stones follow the
setting through the settings manager's keyed change callbacks, so F10, Settings
Apply and section resets move them with no extra call. Rule 4b: no window
attribute; the header owns its controller and subscription and drops it when the
table is destroyed. Supersedes the D-19 underline bar.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionHeader, QTableWidget

from core import planet_strength_glow as psg
from core.retinue_strength import KEY_ON, KEY_SOURCE
from core.strength_stone import (  # noqa: F401  (the panel's colour maths, Qt-free)
    BLACK, INK_DARK, SOURCE_COLUMN, WHITE, active_column, mix, parse_value, planet_lit,
    stone_style)
from apps.panels.keycap_paint import paint_keycap, paint_lamp  # noqa: F401  (shared keycap painters)

COLUMN_SOURCE = {c: s for s, c in SOURCE_COLUMN.items()}
PLANET_COLUMN = 0          # the PLANET key (td-e6jsp)
PLANET_TIP = ("Planets glow with the strength of the lit key: a wide, bright glow "
              "is strong, a faint one is weak. Needs a strength key; DUC Bala "
              "lights if none is lit.")
# Row order of the table (StrengthController._PLANET_ORDER).
PLANET_ROWS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# "chart.retinue_strength" prefixes the on/off and source keys; "appearance" carries
# the theme; KEY_MODE is the PLANET key.
_WATCHED = ("chart.retinue_strength", "appearance", psg.KEY_MODE)


def _theme():
    from ui.qt_theme import get_theme_colors
    return get_theme_colors()


def _is_light():
    from ui.qt_theme import is_light_theme
    return is_light_theme()


def accent_color() -> str:
    """The theme accent of the lit key's edge and lamp (Rule 20)."""
    return _theme()["primary"]


def paint_value_stone(painter: QPainter, rect, text: str, planet_hex: str, value: float,
                      cell: str, font: QFont):
    """Draw one value on its stone inside ``rect`` (the cell already filled)."""
    from ui.qt_theme import desat_hex, scaled_px
    th = _theme()
    st = stone_style(desat_hex(planet_hex), value, cell, th["secondary_text"], _is_light())
    r = QRectF(rect)
    ix, iy = scaled_px(6), scaled_px(4)
    h = max(12.0, min(r.height() - 2 * iy, float(scaled_px(28))))
    w = max(12.0, r.width() - 2 * ix)
    stone = QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)
    radius = min(float(scaled_px(8)), h / 2)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    grad = QRadialGradient(QPointF(stone.center().x(), stone.top()),
                           max(stone.width(), stone.height()) * 0.85)
    grad.setColorAt(0.0, QColor(st["top"]))
    grad.setColorAt(0.55, QColor(st["fill"]))
    grad.setColorAt(1.0, QColor(st["rim"]))
    edge = QColor(st["edge"])
    edge.setAlphaF(st["edge_alpha"])
    painter.setPen(QPen(edge, 1.0))
    painter.setBrush(QBrush(grad))
    painter.drawRoundedRect(stone.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    f = QFont(font)
    if st["bold"]:
        f.setBold(True)
    painter.setFont(f)
    painter.setPen(QColor(st["text"]))
    painter.drawText(stone, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return st


def planet_colours() -> dict:
    """``{planet: hex}``: the strength palette (td-e6jsp: one palette for the
    stones, the PLANET column discs and the chart auras; the user's manual
    planet glow colours are not read)."""
    return {p: psg.STRENGTH_PALETTE[p] for p in PLANET_ROWS}


def symbol_centre_x(option, fm: QFontMetricsF, text: str) -> float:
    """Centre x of the planet symbol (the first word) of a PLANET cell; ``option``
    is the cell's initialised view-item option."""
    from PySide6.QtWidgets import QApplication
    widget = option.widget
    style = widget.style() if widget is not None else QApplication.style()
    rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, widget)
    margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1
    symbol = text.split(" ")[0] if text else ""
    return rect.left() + margin + fm.horizontalAdvance(symbol) / 2.0


def paint_planet_tint(painter: QPainter, option, text: str, planet_hex: str, value: float):
    """The PLANET column disc (Ember Aura MC-INTENT): a 22 px circle behind the
    symbol, radial gradient of the planet colour from alpha 0.12 + 0.55 t to 0;
    where the colour is weak on the theme, a 1 px theme-ink ring at 0.12 + 0.30 t.
    The name text is painted afterwards, unchanged."""
    from ui.qt_theme import desat_hex, scaled_px
    light = _is_light()
    rect = QRectF(option.rect)
    d = min(float(scaled_px(22)), rect.height() - 2.0)
    if d <= 4:
        return
    cx = symbol_centre_x(option, QFontMetricsF(option.font), text)
    centre = QPointF(cx, rect.center().y())
    colour = QColor(desat_hex(planet_hex))
    grad = QRadialGradient(centre, d / 2.0)
    c0 = QColor(colour)
    c0.setAlphaF(psg.tint_alpha(value))
    c1 = QColor(colour)
    c1.setAlphaF(0.0)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(1.0, c1)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawEllipse(centre, d / 2.0, d / 2.0)
    if psg.weak_on_theme(planet_hex, light):
        ink = QColor(_theme()["secondary_text"] if light else WHITE)
        ink.setAlphaF(psg.tint_ring_alpha(value))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ink, 1.0))
        painter.drawEllipse(centre, d / 2.0 - 0.5, d / 2.0 - 0.5)
    painter.restore()


# ---------------------------------------------------------------- keycaps
def key_palette(light: bool | None = None) -> dict:
    """Keycap colours from the theme tokens (Rule 20)."""
    from ui.qt_theme import elevation_color
    th = _theme()
    light = _is_light() if light is None else light
    text = th["secondary_text"]
    e2, e3 = elevation_color(2), elevation_color(3)
    if light:
        face_top = mix(e3, WHITE, 0.75)
        face_bot = mix(e2, WHITE, 0.15)
        edge = mix(e2, text, 0.24)
        lip = mix(e2, text, 0.30)
        sunk_top = mix(face_bot, text, 0.10)
        sunk_bot = mix(face_bot, WHITE, 0.30)
        shade = text
        muted = mix(text, face_bot, 0.55)
    else:
        face_top = mix(e3, th["secondary_light"], 0.30)
        face_bot = mix(e2, th["secondary_light"], 0.08)
        edge = mix(th["secondary_dark"], BLACK, 0.55)
        lip = mix(th["secondary_dark"], BLACK, 0.40)
        sunk_top = mix(face_bot, BLACK, 0.30)
        sunk_bot = mix(face_bot, BLACK, 0.08)
        shade = BLACK
        muted = mix(text, face_bot, 0.50)
    return {"face_top": face_top, "face_bot": face_bot, "edge": edge, "lip": lip,
            "sunk_top": sunk_top, "sunk_bot": sunk_bot, "shade": shade, "muted": muted,
            "text": text, "accent": th["primary"]}


def key_label_px() -> int:
    """The keys' label size: the Table Headers font area (Settings > Font Sizes >
    Table Headers, times Display Scale). Never clamped below it."""
    from ui.qt_theme import scaled_area_px
    return scaled_area_px("table_headers")


def key_geometry(px: int | None = None, compact: bool = False) -> dict:
    """Every key measure, derived from the label px so the keys grow with the
    font (td-esl0r). ``top``/``bottom``: section margin above/below the key;
    ``ml``/``mr``: left/right margin (the right one clears the grid line);
    ``lip``: the edge under the face; ``vpad``/``hpad``: face padding around the
    lamp + label; ``d``: the lamp diameter; ``gap``: lamp to label."""
    px = key_label_px() if px is None else int(px)
    geo = {
        "px": px,
        "top": 2.0, "bottom": 2.0, "ml": 1.0, "mr": 2.0,
        "lip": float(max(2, round(px / 4))),
        "vpad": float(max(3, round(px * 0.35))),
        "hpad": float(max(2, round(px * 0.2))),
        "d": float(max(7, round(px * 0.75))),
        "gap": float(max(3, round(px * 0.25))),
    }
    if compact:       # the Tajika matrix keys (SPEC-TJK-003 §4.4): thinner lip and padding
        geo.update(top=1.0, bottom=1.0, lip=float(max(2, round(px / 5))),
                   vpad=float(max(2, round(px / 5))), d=float(max(7, round(px * 0.65))))
    return geo


def key_font(base: QFont, px: int | None = None) -> QFont:
    """The label font: ``base`` family at the Table Headers px, bold."""
    f = QFont(base)
    f.setPixelSize(key_label_px() if px is None else int(px))
    f.setBold(True)
    f.setCapitalization(QFont.Capitalization.MixedCase)
    return f


def key_header_height(base: QFont | None = None, px: int | None = None) -> int:
    """Header height that holds a key whose label is at full Table Headers size:
    margins + face (text line + padding) + lip."""
    import math
    g = key_geometry(px)
    fm = QFontMetricsF(key_font(base if base is not None else QFont(), g["px"]))
    face = math.ceil(fm.height()) + 2 * g["vpad"]
    return int(math.ceil(g["top"] + face + g["lip"] + g["bottom"]))


def key_width(label: str, base: QFont | None = None, px: int | None = None) -> int:
    """Section width that shows ``label`` (upper case) whole at the Table Headers
    size beside its lamp: margins + padding + lamp + gap + text."""
    import math
    g = key_geometry(px)
    fm = QFontMetricsF(key_font(base if base is not None else QFont(), g["px"]))
    inner = g["d"] + g["gap"] + fm.horizontalAdvance(label.upper())
    return int(math.ceil(g["ml"] + g["mr"] + 2 * g["hpad"] + inner + 1))


def fill_widths(needs: list, avail: int) -> list:
    """Column widths: every column gets at least its need; spare room evens the
    columns out (the narrowest rise first) so wide panels keep equal columns.
    When the needs exceed ``avail`` the needs are returned (the table scrolls)."""
    needs = [int(n) for n in needs]
    if not needs or sum(needs) >= avail:
        return needs
    level = 0
    while sum(max(n, level + 1) for n in needs) <= avail:
        level += 1
    widths = [max(n, level) for n in needs]
    spare = avail - sum(widths)
    for i, w in enumerate(widths):        # the last pixels, left to right
        if spare <= 0:
            break
        if w == level:
            widths[i] += 1
            spare -= 1
    return widths


class StrengthKeyHeader(QHeaderView):
    """The Strength table's horizontal header with keycaps on columns 1-4."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("strength_key_header")
        self.setMouseTracking(True)
        self.setHighlightSections(False)
        self._lit = None          # lit column, or None
        self._planet_lit = False  # the PLANET key (td-e6jsp)
        self._hover = None        # column under the mouse
        self._pressing = None     # column held down
        self.on_key = None        # callable(column) set by the controller

    # -- state ----------------------------------------------------------------
    @property
    def lit_column(self):
        return self._lit

    def set_lit_column(self, col):
        if col != self._lit:
            self._lit = col
            self.viewport().update()

    @property
    def planet_lit(self) -> bool:
        return self._planet_lit

    def set_planet_lit(self, lit):
        if bool(lit) != self._planet_lit:
            self._planet_lit = bool(lit)
            self.viewport().update()

    def is_key(self, col) -> bool:
        return col in COLUMN_SOURCE or col == PLANET_COLUMN

    def is_lit(self, col) -> bool:
        return self._planet_lit if col == PLANET_COLUMN else col == self._lit

    # -- size (td-esl0r) ---------------------------------------------------------
    def label(self, col) -> str:
        m = self.model()
        if m is None:
            return ""
        return str(m.headerData(col, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.DisplayRole) or "")

    def column_needs(self) -> list:
        """Minimum width of each section: a key shows its label whole at the
        Table Headers size; PLANET keeps what its planet names need."""
        table = self.parent()
        needs = []
        for c in range(self.count()):
            key = key_width(self.label(c), self.font()) if self.is_key(c) else 0
            if c != PLANET_COLUMN:
                needs.append(key)
                continue
            # PLANET: a key, and at least what its planet names need
            fm = QFontMetricsF(table.font() if table is not None else self.font())
            names = max((fm.horizontalAdvance("\u263f " + n) for n in PLANET_ROWS), default=0)
            fit = table.sizeHintForColumn(c) if table is not None else 0
            needs.append(int(max(names + 12, fit, key)))
        return needs

    def layout_columns(self):
        """Fixed section widths: each key at least its key_width, spare room
        shared out evenly; when even the needs do not fit, the table scrolls
        sideways rather than shrinking a label."""
        table = self.parent()
        if table is None or self.count() == 0:
            return
        widths = fill_widths(self.column_needs(), table.viewport().width())
        for c, w in enumerate(widths):
            if self.sectionResizeMode(c) != QHeaderView.ResizeMode.Fixed:
                self.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            if self.sectionSize(c) != w:
                self.resizeSection(c, w)

    def fit_to_font(self):
        """Height and column widths from the current Table Headers size; called
        at install and by relayout_info_panels on every font / scale change."""
        h = key_header_height(self.font())
        self.setFixedHeight(h)
        self.layout_columns()
        self.viewport().update()

    # -- mouse ----------------------------------------------------------------
    def mousePressEvent(self, e):
        col = self.logicalIndexAt(e.position().toPoint())
        if self.is_key(col) and e.button() == Qt.MouseButton.LeftButton:
            self._pressing = col
            self.viewport().update()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        col = self.logicalIndexAt(e.position().toPoint())
        held, self._pressing = self._pressing, None
        if held is not None:
            self.viewport().update()
            e.accept()
            if col == held and callable(self.on_key):
                self.on_key(col)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        col = self.logicalIndexAt(e.position().toPoint())
        if self.is_key(col):
            self.mousePressEvent(e)   # a fast second click is a second press
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        col = self.logicalIndexAt(e.position().toPoint())
        col = col if self.is_key(col) else None
        if col != self._hover:
            self._hover = col
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
        if not self.is_key(logical) or not rect.isValid():
            super().paintSection(painter, rect, logical)
            return
        text = str(self.model().headerData(logical, Qt.Orientation.Horizontal,
                                           Qt.ItemDataRole.DisplayRole) or "")
        # today's section ground and border (QSS), without its label
        opt = QStyleOptionHeader()
        self.initStyleOptionForIndex(opt, logical)
        opt.rect = rect
        opt.text = ""
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header, opt, painter, self)
        painter.restore()
        painter.save()
        self._paint_key(painter, QRectF(rect), text.upper(),
                        lit=self.is_lit(logical), pressing=(logical == self._pressing),
                        hover=(logical == self._hover))
        painter.restore()

    def _paint_key(self, p: QPainter, cell: QRectF, label: str, *, lit, pressing, hover):
        from ui.qt_theme import scaled_px
        geo = key_geometry()
        paint_keycap(p, cell, label, lit=lit, pressing=pressing, hover=hover, geo=geo,
                     font=key_font(self.font(), geo["px"]), pal=key_palette(),
                     radius_cap=float(scaled_px(7)))


# ---------------------------------------------------------------- controller
class _RefitOnResize(QObject):
    """Re-lay the key columns when the table viewport changes width (panel
    resize, vertical scrollbar shown or hidden)."""

    def __init__(self, header):
        super().__init__(header)
        self._header = header
        self._w = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            w = obj.width()
            if w != self._w:
                self._w = w
                self._header.layout_columns()
        return False


class StrengthKeys:
    """Connects the header keys, the delegate stones and the settings."""

    def __init__(self, table: QTableWidget, header: StrengthKeyHeader, gui=None, settings=None):
        if settings is None:
            from managers.settings_manager import get_settings
            settings = get_settings()
        self._table = table
        self._header = header
        self._gui = gui
        self._settings = settings
        header.on_key = self.press
        self._subscribe(table)
        # the columns follow the labels: refit on width and label changes
        self._refit = _RefitOnResize(header)
        table.viewport().installEventFilter(self._refit)
        table.model().headerDataChanged.connect(self._labels_changed)
        self.refresh()

    def _labels_changed(self, orientation, _first, _last):
        import shiboken6
        if orientation == Qt.Orientation.Horizontal and shiboken6.isValid(self._header):
            self._header.layout_columns()

    @property
    def lit_column(self):
        return self._header.lit_column

    def _subscribe(self, table):
        import shiboken6
        settings = self._settings
        header = self._header
        me = self

        def _changed(key, _value):
            if shiboken6.isValid(header):
                me.interlock(key)
                me.refresh()

        for key in _WATCHED:
            settings.on_changed(key, _changed)

        def _drop(*_):
            for key in _WATCHED:
                settings.remove_on_changed(key, _changed)

        table.destroyed.connect(_drop)

    def refresh(self):
        """Re-read the setting: light the key, set the stones, repaint."""
        import shiboken6
        if not (shiboken6.isValid(self._header) and shiboken6.isValid(self._table)):
            return
        col = active_column(self._settings.get)
        self._header.set_lit_column(col)
        lit = planet_lit(self._settings.get)
        self._header.set_planet_lit(lit)
        delegate = self._table.itemDelegate()
        if hasattr(delegate, "set_stones"):
            delegate.set_stones(col, planet_colours() if col is not None else {})
        if hasattr(delegate, "set_planet_tint"):
            delegate.set_planet_tint(lit and col is not None)
        self._header.viewport().update()
        self._table.viewport().update()

    def interlock(self, key):
        """D-21 for every single-key writer (``StrengthSourceCycler.interlock``)."""
        from managers.retinue_strength_shortcut import StrengthSourceCycler
        StrengthSourceCycler(self._gui).interlock(self._settings, key)

    def press(self, col):
        """A key was clicked: on with its source, off when lit, or switch. PLANET
        toggles the planet glow (``select_planet``)."""
        from managers.retinue_strength_shortcut import StrengthSourceCycler
        if col == PLANET_COLUMN:
            on = not self._header.planet_lit
            StrengthSourceCycler(self._gui).select_planet(on)
            self.refresh()
            return on
        source = COLUMN_SOURCE.get(col)
        if source is None:
            return None
        target = None if col == self._header.lit_column else source
        StrengthSourceCycler(self._gui).select(target)
        self.refresh()
        return target


def install_strength_source_keys(table: QTableWidget, gui=None, settings=None) -> StrengthKeys:
    """Give the Strength table its key header. The header sizes itself from the
    Table Headers font (height, and column widths so no label is shrunk) and
    re-fits on viewport resizes, label changes and relayout_info_panels."""
    old = table.horizontalHeader()
    header = StrengthKeyHeader(table)
    header.setDefaultAlignment(old.defaultAlignment())
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(1)
    table.setHorizontalHeader(header)     # Qt deletes the old header
    item = table.horizontalHeaderItem(PLANET_COLUMN)
    if item is not None:
        item.setToolTip(PLANET_TIP)
    # the columns follow the labels; past the panel width the table scrolls
    # sideways instead of squeezing a key (the label never drops below its size)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    keys = StrengthKeys(table, header, gui=gui, settings=settings)
    header._keys = keys                   # lifetime: the header owns its controller
    header.fit_to_font()
    return keys
