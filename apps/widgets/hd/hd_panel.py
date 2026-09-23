"""The Human Design page: the graph, its toolbar, the two planet columns and the card.

The graph itself is ``HDBodygraphView``; this is the furniture around it. Laid out as
mockup 27: an in-view toolbar across the top with the frame control beneath it, the
Design column on the left, the Personality column on the right, and the reading card and
channel list under them.

Two conventions matter here:

  * Everything is an IN-VIEW control. The app's own chrome gains no row for this page --
    the label, filter, motion and frame controls all live inside the view.
  * Fonts come from ``scaled_area_font('info_text')`` and its siblings, never from a
    literal point size, so the app's font scaling reaches this page like every other.

Rule 20 holds except for the declared HD palette: the centre hues and the two activation
colours come from ``hd_palette()``; everything else -- panels, borders, text, buttons --
comes from ``get_theme_colors()``.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.font_bootstrap import HD_BODY_FAMILIES, hd_symbol_font
from ui.qt_theme import (
    get_theme_colors, hd_palette, hex_to_rgb_str, scaled_area_font, scaled_area_px,
    scaled_px,
)
from . import hd_geometry as G
from .hd_bodygraph_view import HDBodygraphView
from .hd_channel_names import CHANNEL_ORDER, channel_name
from .hd_fixture import GLYPHS, NAMES
from .hd_painter import VIEWBOX, normalise_model

#: The three gate-one frames. Standard is the default and is LOCKED: Josh's comment in
#: libaditya (gate 1 fixed on the ecliptic, no Aditya shift, no sidereal) is an opinion,
#: and the app does not bake in an opinion about which frame is true -- exactly as the
#: main zodiac offers all three systems and lets the user choose. The other two are
#: reachable only through the Advanced HD setting; this page never offers them.
FRAMES = (
    ("standard", "Standard", "tropical, gate 1 at 223.25 deg", True),
    ("aditya", "Aditya-shifted", "gate 1 at 193.25 deg, the Aditya Circle offset", False),
    ("sidereal", "Sidereal", "gate 1 by the chart's own ayanamsa", False),
)


def _panel_qss(colors: dict, radius: int = 12) -> str:
    return (f"background: rgba({hex_to_rgb_str(colors['secondary_light'])}, 0.10);"
            f"border: 1px solid rgba({hex_to_rgb_str(colors['secondary_text'])}, 0.10);"
            f"border-radius: {radius}px;")


def _tooltip_qss(colors: dict) -> str:
    """The tooltip rule every hoverable widget on this page carries itself.

    A tooltip is styled from the nearest ancestor that owns a stylesheet, and on
    Lorris's screen that produced a dark box with dark text on the light theme (a
    row's own rgba band and ink, painted onto a ToolTip window). Spelling the
    tooltip out on the carrier, in the same tokens qt-material's global rule uses,
    makes it read the same whatever the ancestors say.
    """
    return (f" QToolTip {{ background-color: {colors['secondary_light']};"
            f" color: {colors['secondary_text']};"
            f" border: 1px solid {colors['secondary_dark']};"
            f" border-radius: 4px; padding: 4px; }}")


#: Row metrics, shared by both columns so a row sits level with its twin. The height is
#: a floor, not a cap: it stops a row collapsing onto its own descenders.
_ROW_HEIGHT = 23
_GLYPH_WIDTH = 16
#: Inset inside a planet row, both sides. The row paints its own band and its own
#: hairline, so its contents must clear those rather than sit on them.
_ROW_PAD_X = 7
#: Gap between the parts of a row, and the card's own outer inset.
_ROW_SPACING = 7
_CARD_PAD_X = 11
#: and in compact, where 11 px of card padding each side is room the content needs more
_CARD_PAD_X_COMPACT = 7
#: The page's own margins and the two gaps in the body row, roomy and compact. Every
#: pixel here is a pixel the graph does not get, and in the narrow case the graph is
#: what is short.
_BODY_GAP = 11
_BODY_GAP_COMPACT = 6
_PAGE_PAD = (10, 12)
_PAGE_PAD_COMPACT = (6, 6)
#: How wide each side column sits. The graph is the subject of this page and the columns
#: are its index, so they take the narrowest width that still holds "Personality" and a
#: gate.line, and everything else goes to the graph.
_COLUMN_WIDTH = 208
#: Inner padding of a channel chip. The horizontal one is larger because the chip has a
#: 7px corner radius: text level with the corner is optically nearer the edge than the
#: same gap on a straight run of border.
_CHIP_PAD_X = 10
#: and in compact mode, where the room the padding takes is room a channel name needs
_CHIP_PAD_X_COMPACT = 6
_CHIP_PAD_Y = 5
#: What a chip and its list take beyond their padding and their text: the chip's 1 px
#: border, the layouts' own spacing, the scroll area's frame. MEASURED -- card width
#: minus the name label's width at a known card width -- because adding the constants
#: up came out 12 px short and clipped the longest channel name.
_CHIP_UNMODELLED = 12
#: What a card title takes beyond its own text. MEASURED, like _CHIP_UNMODELLED.
_TITLE_CHROME = 2
#: The graph is not worth showing below this. When the roomy columns would leave it
#: less, they go compact instead -- see _share_the_width.
_COMPACT_GRAPH = 340
#: The floor both side cards share -- the reading on the left, the channel index on the
#: right. They must match, or whichever is taller squeezes its own planet column and the
#: two columns stop showing the same rows.
_SIDE_CARD_MIN_HEIGHT = 150


def _value_width() -> int:
    """Wide enough for the widest gate.line the model can print, and no wider.

    This was 52 px, which is a third more than the string needs. In a 208 px column the
    slack is invisible; in the narrowest column it is a third of the room the planet's
    name was fighting for.
    """
    metrics = QFontMetrics(_dense_font("info_text", bold=True))
    return metrics.horizontalAdvance("64.6") + scaled_px(4)


def _key_width() -> int:
    """Wide enough for the widest channel key there is.

    It was a guessed 34 px. "32-54" needs 40, so every key made of two two-digit gates
    was cut -- at EVERY window size, which is why widening the page never showed it and
    why it took a probe that asks each label whether its text fits.
    """
    metrics = QFontMetrics(_dense_font("info_text", bold=True))
    return max(metrics.horizontalAdvance(f"{min(a, b)}-{max(a, b)}")
               for a, b, _name in CHANNEL_ORDER) + scaled_px(2)


def _compact_column_floor() -> int:
    """The floor for a column that has dropped its planet NAMES.

    Only the planet rows go compact -- glyph, gate.line, dot -- and on their own they
    would fit in about 108 px. They do not get to set the width on their own: the four
    widgets in the two side stacks are all held to ONE width (see _share_the_width), so
    the floor is whatever the widest of them needs, and that is the channel index. A
    wrapped label cannot break inside a word, so "Transformation" plus the chip's
    padding, the card's padding and the scroll bar is the real number.
    """
    name = QFontMetrics(_dense_font("info_text"))
    caption = QFontMetrics(scaled_area_font("status"))
    chrome = (2 * _CARD_PAD_X_COMPACT + 2 * scaled_px(_ROW_PAD_X)
              + scaled_px(_GLYPH_WIDTH))
    rows = chrome + 2 * scaled_px(_ROW_SPACING) + _value_width() + _StateDot.SIZE
    head = chrome + 2 * scaled_px(_ROW_SPACING) + _StateDot.SIZE + \
        caption.horizontalAdvance("GATE.LINE")
    longest = max((word for _a, _b, label in CHANNEL_ORDER
                   for word in label.split()), key=name.horizontalAdvance)
    chips = (2 * _CARD_PAD_X_COMPACT + 2 * scaled_px(2) + _scrollbar_extent()
             + _CHIP_UNMODELLED
             + 2 * scaled_px(_CHIP_PAD_X_COMPACT) + name.horizontalAdvance(longest))
    # the card titles lose their letter-spacing in compact, which is where the widest
    # of them (PERSONALITY) was spending 22 px
    title = QFontMetrics(scaled_area_font("panel_titles", bold=True))
    titles = 2 * _CARD_PAD_X_COMPACT + _TITLE_CHROME + max(
        title.horizontalAdvance(word)
        for word in ("THE READING", "PERSONALITY", "CHANNELS"))
    return int(max(rows, head, chips, titles))


def _scrollbar_extent() -> int:
    from PySide6.QtWidgets import QApplication, QStyle
    app = QApplication.instance()
    if app is None:
        return 16
    return app.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)


class _NarrowsItsPadding:
    """Mixin: a card whose side padding follows its own ``_compact`` flag.

    Three cards need exactly this and nothing else, and the alternative is the same
    four lines written three times and updated twice.
    """

    def _narrow_padding(self) -> None:
        margins = self._outer.contentsMargins()
        side = _CARD_PAD_X_COMPACT if self._compact else _CARD_PAD_X
        self._outer.setContentsMargins(side, margins.top(), side, margins.bottom())


def _column_floor() -> int:
    """The narrowest a planet column may be squeezed to. MEASURED, not guessed.

    The old figure was 132 px, and its comment said a glyph, an elided name and a
    gate.line still fit there. They did not. The row's stretch is on the NAME, so a
    squeeze comes out of the name and out of nothing else: at 132 px the name label was
    allotted three pixels, and the column showed a glyph and a number with a hole
    between them. That is the shape Lorris kept reporting as "the glyph is against the
    border" -- the glyph had not moved, everything after it had gone.

    Deriving the floor from the fonts the rows actually paint in also means it follows
    the app's font scale instead of going stale the next time that moves. Both the row
    and the BODY / GATE.LINE header have to fit, so the floor is whichever is wider.
    """
    name = QFontMetrics(_dense_font("info_text"))
    caption = QFontMetrics(scaled_area_font("status"))
    chrome = (2 * _CARD_PAD_X + 2 * scaled_px(_ROW_PAD_X) + scaled_px(_GLYPH_WIDTH)
              + 3 * scaled_px(_ROW_SPACING) + _StateDot.SIZE)
    row = chrome + max(name.horizontalAdvance(n) for n in NAMES) + _value_width()
    head = (chrome + caption.horizontalAdvance("BODY")
            + caption.horizontalAdvance("GATE.LINE"))
    return int(max(row, head))


def _area_px(area: str, ratio: float = 1.0) -> int:
    """The pixel size an area font ACTUALLY paints at, one notch tighter when asked.

    Not ``scaled_area_px``, and the difference is visible. The app's area sizes are one
    table read two ways: ``scaled_area_font`` hands the number to ``setPointSize`` while
    ``scaled_area_px`` returns it as pixels, and a point is about 1.33 px at 96 dpi. So
    the two disagree by a third, and this page was designed and approved against what
    the QFont painted. Sizing the stylesheet from ``scaled_area_px`` shrank every label
    on the page by a quarter -- correct plumbing, wrong result.

    ``QFontInfo`` resolves the font the way the screen will, so the stylesheet asks for
    exactly the size ``setFont`` would have produced, and the design does not move.
    """
    from PySide6.QtGui import QFontInfo

    font = scaled_area_font(area)
    px = font.pixelSize()
    if px <= 0:                       # specified in points: ask what that resolves to
        px = QFontInfo(font).pixelSize()
    return max(9, round(px * ratio))


def _font_css(area: str, bold: bool = False, ratio: float = 1.0,
              families: tuple = ()) -> str:
    """Font sizing as STYLESHEET text, which is the only kind this app honours.

    qt-material ships ``* { font-family: Roboto; font-size: 13px; }``. The universal
    selector reaches every widget in the process and a QSS rule beats ``setFont``, so
    every ``setFont`` on a styled widget here was INERT: the columns and the reading
    card painted at a flat 13 px no matter what the user set the app's text size to.
    Measured before this change, the row ink was 182x23 px at app scales 1.0, 1.4 AND
    1.8 -- identical pixels, three settings.

    It is worth naming why that survived review. The QFont objects were correct; every
    check that asked a widget what font it held got the right answer back, and the
    docstring on the old helper cheerfully promised "turn the app's text up and these
    follow". Nothing rendered twice and compared. The rule for this app is: sizing goes
    in the widget's own stylesheet, which outranks the global one -- the way
    vimshottari_panel and varga_column already do it.

    ``families`` matters for the symbol labels. The universal rule sets Roboto on them
    too, so the bundled Noto Sans Symbols2 was being bypassed and the body glyphs came
    from whatever the system happened to fall back to. That works on a machine with a
    good symbol font and shows boxes on one without.

    Custom-PAINTED text is the exception and still takes a QFont: a QPainter is not a
    styled widget and never sees the sheet.
    """
    css = (f"font-size: {_area_px(area, ratio)}px;"
           f" font-weight: {'bold' if bold else 'normal'};")
    if families:
        css += " font-family: " + ", ".join(f'"{f}"' for f in families) + ";"
    return css


def _dense_font(area: str, bold: bool = False, ratio: float = 0.86):
    """An area font, one notch tighter, sized in PIXELS to match ``_font_css``.

    The side columns are a 14-row table read at a glance, not body copy, and at the
    app's full ``info_text`` size they crowd the graph off the page.

    This no longer decides what the user sees -- the stylesheet does -- but it must
    still agree with it, because ``QFontMetrics`` on these widgets is what elides the
    long body names and reserves the note's height. A metrics font that disagreed with
    the painted one would elide against the wrong width, which is a subtler bug than
    the one being fixed here.
    """
    font = scaled_area_font(area, bold=bold)
    font.setPixelSize(_area_px(area, ratio))
    return font


class _ElidedLabel(QLabel):
    """A label that gives up width instead of holding the window open.

    The header line is the only elastic thing in the toolbar: everything else is a
    control that has to stay readable. Without this the toolbar's natural width is a
    hard floor on the whole panel, so a 1200 px window cannot exist.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setStyleSheet(self, sheet: str) -> None:  # noqa: N802 - Qt name
        # the label shows its full text as a tooltip once elided, and that tooltip
        # takes its look from the nearest styled ancestor: this label
        super().setStyleSheet(sheet + _tooltip_qss(get_theme_colors()))

    def setText(self, text: str) -> None:  # noqa: N802 - Qt name
        self._full = text
        super().setText(text)
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().resizeEvent(event)
        self._elide()

    def minimumSizeHint(self):  # noqa: N802 - Qt name
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        shown = metrics.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                   max(0, self.width() - 2))
        if shown != super().text():
            super().setText(shown)
        self.setToolTip("" if shown == self._full else self._full)


class _Segmented(QWidget):
    """A small pill of mutually exclusive buttons, as in the mockup's toolbar."""

    changed = Signal(str)

    def __init__(self, options, current, parent=None):
        super().__init__(parent)
        self._options = options
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for key, label in options:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(key == current)
            button.setFont(scaled_area_font("buttons"))
            self._group.addButton(button)
            self._buttons[key] = button
            # A bound method, not a lambda closing over self. PySide connects a bound
            # method of a QObject without keeping the object alive; a lambda that
            # captures self is held by the connection and the whole widget leaks.
            button.clicked.connect(self._clicked)
            layout.addWidget(button)
        self.refresh_theme()

    def _clicked(self, _checked: bool = False) -> None:
        button = self.sender()
        for key, candidate in self._buttons.items():
            if candidate is button:
                self.changed.emit(key)
                return

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
            return
        # A key this control does not offer. Leave NOTHING selected rather than leaving
        # the previous button lit, which would name the wrong option as the active one.
        # The group is exclusive, so it has to be opened to clear the last button.
        self._group.setExclusive(False)
        for button in self._buttons.values():
            button.setChecked(False)
        self._group.setExclusive(True)

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        palette = hd_palette()
        accent = hex_to_rgb_str(palette["red"] if "red" in palette else colors["primary"])
        line = hex_to_rgb_str(colors["secondary_text"])
        # qt-material's global QPushButton rule sets text-transform: uppercase,
        # font-weight: bold and height: 36px, and a QSS rule beats setFont every time
        # (the standing trap in this codebase). A toolbar of shouting 36 px pills is not
        # the design, so every one of those is answered here rather than in Python.
        size = scaled_area_px("buttons")
        self.setStyleSheet(f"""
            QPushButton {{
                text-transform: none;
                font-weight: normal;
                font-size: {size}px;
                height: {size + 9}px;
                border: 1px solid rgba({line}, 0.12);
                border-right: none;
                background: rgba({line}, 0.04);
                color: {colors['secondary_text']};
                padding: 4px 11px;
            }}
            QPushButton:first-child {{ border-top-left-radius: 11px;
                                        border-bottom-left-radius: 11px; }}
            QPushButton:last-child  {{ border-right: 1px solid rgba({line}, 0.12);
                                        border-top-right-radius: 11px;
                                        border-bottom-right-radius: 11px; }}
            QPushButton:hover  {{ background: rgba({line}, 0.10); }}
            QPushButton:checked{{ background: rgba({accent}, 0.34);
                                  color: {colors['primary_text']}; }}
        """)
        for button in self._buttons.values():
            button.setFont(scaled_area_font("buttons"))


class _StateDot(QWidget):
    """The per-row activation dot.

    Three states, and the split one is the point: a gate held by BOTH columns reads as
    one disc cut in half, design on the left and personality on the right, so a reader
    scanning either column can see at a glance which of its gates the other column also
    holds. A solid disc is that column alone; a hollow ring is a body that prints but
    activates nothing.
    """

    SIZE = 11

    def __init__(self, parent=None):
        super().__init__(parent)
        self._left = None                      # design half / whole
        self._right = None                     # personality half
        self._ring = False
        self.setFixedSize(self.SIZE, self.SIZE)

    def set_state(self, left, right, ring: bool = False) -> None:
        self._left, self._right, self._ring = left, right, ring
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(0.5, 0.5, self.SIZE - 1.0, self.SIZE - 1.0)
        if self._ring:
            pen = QPen(QColor(self._left or "#888888"))
            pen.setWidthF(1.2)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(box)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        if self._left and self._right:
            path = QPainterPath()
            path.moveTo(box.center())
            path.arcTo(box, 90, 180)
            path.closeSubpath()
            painter.setBrush(QColor(self._left))
            painter.drawPath(path)
            path = QPainterPath()
            path.moveTo(box.center())
            path.arcTo(box, 270, 180)
            path.closeSubpath()
            painter.setBrush(QColor(self._right))
            painter.drawPath(path)
        elif self._left:
            painter.setBrush(QColor(self._left))
            painter.drawEllipse(box)


class _RowStrip(QFrame):
    """One planet row. Knows its gate, so it can be raised and can raise the graph."""

    entered = Signal(object)              # the gate number, or None on leave
    clicked = Signal(object)              # the gate number, on a click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gate: int | None = None
        self.highlighted = False
        self.setMouseTracking(True)

    def enterEvent(self, event):  # noqa: N802 - Qt name
        super().enterEvent(event)
        self.entered.emit(self.gate)

    def leaveEvent(self, event):  # noqa: N802 - Qt name
        super().leaveEvent(event)
        self.entered.emit(None)

    def mousePressEvent(self, event):  # noqa: N802 - Qt name
        super().mousePressEvent(event)
        if self.gate is not None:
            self.clicked.emit(self.gate)


class _PlanetColumn(_NarrowsItsPadding, QFrame):
    """One activation column: 14 rows of glyph, body, gate.line, and a state dot.

    Both columns run on ONE grid so a row sits level with its twin in the other column,
    which is what lets a reader compare Design against Personality by eye.
    """

    #: Re-emitted from whichever row the pointer is over: the gate number, or None.
    row_entered = Signal(object)
    #: A row was clicked. Pins that gate, exactly as clicking it on the graph does.
    row_clicked = Signal(object)
    #: The row area was scrolled. The twin column follows, so the two stay on one grid.
    scrolled = Signal(int)

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side                       # "design" | "personality"
        self._rows = []
        self._compact = False
        self._mirroring = False
        self._build()

    def mirror_scroll(self, value: int) -> None:
        """Follow the twin column's scroll position.

        Guarded against the echo: setValue would emit valueChanged and send the
        position straight back, and the two columns would fight over a rounding
        difference forever.
        """
        bar = self.rows_scroll.verticalScrollBar()
        if bar.value() == value or self._mirroring:
            return
        # NOT blockSignals: the scroll AREA moves its viewport by listening to this very
        # signal, so silencing the bar sets the number and leaves the rows where they
        # were -- the two columns then agree on a scroll position while showing
        # different rows, which is the exact failure this mirroring exists to prevent.
        # A re-entrancy flag stops the echo instead.
        self._mirroring = True
        try:
            bar.setValue(value)
        finally:
            self._mirroring = False

    def set_focus_gates(self, gates) -> None:
        """Raise the rows whose gate is in ``gates``.

        Both columns follow the SAME set, which is the point: hovering the Sacral raises
        every row on both sides that put a gate into it, so the reader sees which half of
        the chart is doing the work without reading a single number.
        """
        gates = set(gates or ())
        changed = False
        for strip, _glyph, _name, _value, _dot in self._rows:
            wanted = strip.gate is not None and strip.gate in gates
            if wanted != strip.highlighted:
                strip.highlighted = wanted
                changed = True
        if changed:
            self.refresh_theme()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self._outer = outer
        outer.setContentsMargins(_CARD_PAD_X, 9, _CARD_PAD_X, 10)
        outer.setSpacing(5)

        self.title = QLabel("DESIGN" if self.side == "design" else "PERSONALITY")
        self.stamp = QLabel("")
        outer.addWidget(self.title)
        outer.addWidget(self.stamp)

        self.head = QFrame()
        head_row = QHBoxLayout(self.head)
        head_row.setContentsMargins(scaled_px(_ROW_PAD_X), 3, scaled_px(_ROW_PAD_X), 3)
        head_row.setSpacing(7)
        self.head_body = QLabel("BODY")
        self.head_gate = QLabel("GATE.LINE")
        self.head_gate.setAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
        head_row.addSpacing(scaled_px(_GLYPH_WIDTH))
        head_row.addWidget(self.head_body, 1)
        head_row.addWidget(self.head_gate)
        head_row.addSpacing(_StateDot.SIZE)
        outer.addWidget(self.head)

        # The 14 rows are fixed height, so without a scroll area the column cannot
        # shrink and it dictates the minimum height of the whole application window:
        # 14 rows plus chrome is 439 px, and the app allows a 960x540 window whose page
        # area is nearer 440. The rows scroll instead. Both columns share one scroll
        # POSITION (see _mirror_scroll), because "a row sits level with its twin" is the
        # property that lets a reader compare the two sides, and two independently
        # scrolled columns would quietly break it.
        self._rows_host = QWidget()
        self.rows_box = QVBoxLayout(self._rows_host)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setWidget(self._rows_host)
        self.rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # tall enough for four rows before it starts scrolling; below that the column is
        # not worth showing at all. It PREFERS all fourteen, so in any normal window the
        # scrollbar never appears and the column looks exactly as it did before.
        self.rows_scroll.setMinimumHeight(scaled_px(_ROW_HEIGHT) * 4)
        self.rows_scroll.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.MinimumExpanding)
        self._rows_host.setMinimumHeight(scaled_px(_ROW_HEIGHT) * 14)
        outer.addWidget(self.rows_scroll, 1)

        for index in range(14):
            strip = _RowStrip()
            strip.entered.connect(self.row_entered)
            strip.clicked.connect(self.row_clicked)
            strip.setFixedHeight(scaled_px(_ROW_HEIGHT))
            line = QHBoxLayout(strip)
            # The glyph used to start on the strip's own left edge, so the Sun sat hard
            # against the panel border -- flagged twice before this stuck. The row is a
            # band with a background of its own, so it needs its own inset; the column's
            # outer margin is not the row's margin.
            line.setContentsMargins(scaled_px(_ROW_PAD_X), 0, scaled_px(_ROW_PAD_X), 0)
            line.setSpacing(scaled_px(_ROW_SPACING))
            glyph = QLabel(GLYPHS[index])
            glyph.setFixedWidth(scaled_px(_GLYPH_WIDTH))
            name = _ElidedLabel(NAMES[index])
            # the name is what compact mode hides, so the row has to say it some other
            # way; the tooltip sits on the STRIP so the whole row answers, not a
            # 16 px glyph
            strip.setToolTip(NAMES[index])
            value = QLabel("--")
            value.setFixedWidth(_value_width())
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            dot = _StateDot()
            line.addWidget(glyph)
            line.addWidget(name, 1)
            line.addWidget(value)
            line.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            self.rows_box.addWidget(strip)
            self._rows.append((strip, glyph, name, value, dot))

        self.rows_scroll.verticalScrollBar().valueChanged.connect(self.scrolled)

    def set_compact(self, on: bool) -> None:
        """Drop the planet names. The glyph is the name, and the tooltip has the word.

        BODY goes with them -- with nothing under it but the glyph column it was
        labelling something the reader can already see -- while GATE.LINE stays, because
        "20.2" needs saying once.
        """
        if on == self._compact:
            return
        self._compact = on
        self._narrow_padding()
        self.head_body.setVisible(not on)
        for _strip, _glyph, name, _value, _dot in self._rows:
            name.setVisible(not on)

    def update_from_model(self, model: dict) -> None:
        # every level of this dict can be missing or None while WI-2 is still filling
        # it in; a half-built model must render as blanks, never take the page down
        activations = model.get("activations") or {}
        rows = activations.get(self.side) or []
        gates = model.get("gates") or {}
        palette = hd_palette()
        colors_secondary = get_theme_colors()["secondary_text"]
        own = palette["design"] if self.side == "design" else palette["personality"]

        stamp = model.get("design_datetime" if self.side == "design"
                          else "personality_datetime") or ""
        text = stamp.replace("T", " ").replace("Z", "")
        if text.count(":") == 2:
            text = text.rsplit(":", 1)[0]
        self.stamp.setText(text + " UTC")

        for index, (_strip, glyph, name, value, dot) in enumerate(self._rows):
            row = rows[index] if index < len(rows) else None
            if not isinstance(row, dict):
                row = None
            available = bool(row and row.get("available"))
            activates = bool(row and row.get("activates"))
            # ANY row with a gate is hoverable, Chiron included. It used to be excluded
            # for activating nothing, which confused two different things: what a body
            # puts INTO the chart, and where its gate SITS on the graph. The second is
            # true of Chiron as much as of the Sun, and it is what hovering answers.
            _strip.gate = row.get("gate") if (available and row) else None
            if not available or row.get("gate") is None:
                value.setText("--")
                _strip.gate = None
                dot.set_state(None, None)
                continue
            line_no = row.get("line")
            value.setText(f"{row['gate']}.{line_no}" if line_no is not None
                          else str(row["gate"]))
            state = gates.get(str(row["gate"]), "none") if activates else "none"
            if not activates:
                # prints but activates nothing: a hollow ring, not an absence
                dot.set_state(colors_secondary, None, ring=True)
            elif state == "both":
                dot.set_state(palette["design"], palette["personality"])
            elif state == "none":
                dot.set_state(None, None)
            else:
                dot.set_state(own, None)
            self._paint_name(name, _strip, "1.0")

        self.refresh_theme()

    def _paint_name(self, label, strip, opacity: str) -> None:
        """The body name, bright when its row is raised.

        Kept in one place because the name is styled from two directions -- the ghost
        opacity when the model loads, and the highlight when the pointer moves -- and
        the two used to overwrite each other.
        """
        colors = get_theme_colors()
        ink = colors["primary_text"] if strip.highlighted else colors["secondary_text"]
        label.setStyleSheet(
            f"color: rgba({hex_to_rgb_str(ink)},"
            f" {'1.0' if strip.highlighted else opacity});"
            f" border: none; background: transparent;"
            + _font_css("info_text", ratio=0.86))

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        palette = hd_palette()
        own = palette["design"] if self.side == "design" else palette["personality"]
        own_rgb = hex_to_rgb_str(own)
        self.setStyleSheet(_panel_qss(colors))
        self.title.setStyleSheet(
            f"color: {own}; letter-spacing: {0 if self._compact else 2}px;"
            f" border: none; background: transparent;"
            + _font_css("status", bold=True))
        # the column heading is a caption over a dense table, not a page title: the
        # panel_titles size swamps the 26 px rows it labels
        self.title.setFont(scaled_area_font("status", bold=True))
        for label in (self.stamp, self.head_body, self.head_gate):
            label.setStyleSheet(
                f"color: rgba({hex_to_rgb_str(colors['secondary_text'])}, 0.55);"
                f"border: none; background: transparent;" + _font_css("status"))
            label.setFont(scaled_area_font("status"))
        # every label inside a bordered QFrame inherits that border unless it says
        # otherwise, which draws a box round each row
        bare = "border: none; background: transparent;"
        line = hex_to_rgb_str(colors['secondary_text'])
        self.head.setStyleSheet(
            f"QFrame {{ background: rgba({line}, 0.05); border: none;"
            f" border-top: 1px solid rgba({line}, 0.16);"
            f" border-bottom: 1px solid rgba({line}, 0.16); }}")
        for index, (strip, glyph, name, value, dot) in enumerate(self._rows):
            # a hairline under every row and a faint band on alternate ones: the reader
            # tracks a value across two columns 700 px apart, and needs the rail
            band = 0.06 if index % 2 else 0.0
            if strip.highlighted:
                # A raised row is a PILL, not a tint. This is the reader's answer to
                # "which body put a gate into the centre I am pointing at", and it has to
                # survive a glance across 700 px of page, so it takes a filled ground, a
                # full-strength border in the column's own colour, and brighter ink.
                strip.setStyleSheet(
                    f"QFrame {{ background: rgba({own_rgb}, 0.28);"
                    f" border: 1px solid rgba({own_rgb}, 0.85);"
                    f" border-radius: 6px; }}" + _tooltip_qss(colors))
            else:
                # every row the same, Chiron included: it used to carry a dashed top
                # border marking it out as the odd one, which is a judgement the reader
                # can make from the row's own dot
                strip.setStyleSheet(
                    f"QFrame {{ background: rgba({line}, {band}); border: none;"
                    f" border-bottom: 1px solid rgba({line}, 0.15); }}"
                    + _tooltip_qss(colors))
            for widget in (name, value):
                widget.setFont(_dense_font("info_text"))
            glyph.setFont(hd_symbol_font(round(scaled_area_px("info_text") * 0.86)))
            glyph.setStyleSheet(
                f"color: rgba({hex_to_rgb_str(colors['primary_text'] if strip.highlighted
                                              else colors['secondary_text'])},"
                f" {'1.0' if strip.highlighted else '0.75'}); {bare}"
                + _font_css("info_text", ratio=0.86, families=HD_BODY_FAMILIES))
            value.setStyleSheet(
                f"color: {colors['primary_text'] if strip.highlighted else own}; {bare}"
                + _font_css("info_text", bold=True, ratio=0.86))
            value.setFont(_dense_font("info_text", bold=True))
            self._paint_name(name, strip, "1.0")


class _ReadingCard(_NarrowsItsPadding, QFrame):
    """Type, Strategy, Authority, Profile, Definition, Incarnation Cross."""

    #: In compact the titles drop their letter-spacing. It is 2 px a character, which on
    #: PERSONALITY is 22 px -- the difference between a card that fits the narrow column
    #: and one that sets the floor for the whole page.
    _compact = False

    def set_compact(self, on: bool) -> None:
        if on != self._compact:
            self._compact = on
            self._narrow_padding()
            self.refresh_theme()

    ROWS = (("type", "Type"), ("strategy", "Strategy"), ("authority", "Authority"),
            ("profile", "Profile"), ("definition", "Definition"))

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        self._outer = outer
        outer.setContentsMargins(_CARD_PAD_X, 9, _CARD_PAD_X, 11)
        outer.setSpacing(6)
        self.title = QLabel("THE READING")
        outer.addWidget(self.title)

        # The card scrolls, as it does in mockup 27. Without this its six rows set a
        # 346 px floor on the LEFT side of the page while the channel index on the right
        # floors at 165, so the two side columns are handed different amounts of room
        # and the Design column starts hiding bodies the Personality column still shows.
        # Equal minimums on both sides is what keeps the two columns on one grid.
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(host)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(_SIDE_CARD_MIN_HEIGHT)
        outer.addWidget(self.scroll, 1)
        self._chips = {}
        for key, label in self.ROWS:
            chip = QFrame()
            inner = QVBoxLayout(chip)
            inner.setContentsMargins(9, 5, 9, 6)
            inner.setSpacing(1)
            caption = QLabel(label.upper())
            value = QLabel("--")
            # These wrap, and that is load-bearing rather than cosmetic. A non-wrapping
            # QLabel's minimum width is its whole string, which forces the scroll host
            # wider than its viewport; with the horizontal scrollbar off (it is, this is
            # a reading card, not a spreadsheet) the overflow is simply CUT, with no
            # scrollbar and no ellipsis to say so. "6/2 (Role Model - Hermit)" lost its
            # closing bracket that way. Wrapping lets the host shrink to the viewport, so
            # a long value costs a second line instead of its tail.
            value.setWordWrap(True)
            caption.setWordWrap(True)
            inner.addWidget(caption)
            inner.addWidget(value)
            layout.addWidget(chip)
            self._chips[key] = (chip, caption, value)
        # The cross is the longest string on the page -- "Right Angle Cross of the
        # Sleeping Phoenix (55/59 | 34/20)" -- in the narrowest column. As one run of
        # text it wrapped wherever the width happened to fall, which put the break in
        # the middle of the name as often as not and left the gates orphaned on a line
        # of their own anyway. So the break is CHOSEN: the name wraps as it must, the
        # gates always start their own line, and the whole thing sits in a chip like
        # every other value in this card rather than loose against the card edge.
        self.cross_chip = QFrame()
        cross_box = QVBoxLayout(self.cross_chip)
        cross_box.setContentsMargins(9, 5, 9, 6)
        cross_box.setSpacing(1)
        self.cross_caption = QLabel("INCARNATION CROSS")
        self.cross_caption.setWordWrap(True)
        self.cross = QLabel("")
        self.cross.setWordWrap(True)
        self.cross.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.cross.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cross_gates = QLabel("")
        self.cross_gates.setWordWrap(True)
        self.cross_gates.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignTop)
        self.cross_gates.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        cross_box.addWidget(self.cross_caption)
        cross_box.addWidget(self.cross)
        cross_box.addWidget(self.cross_gates)
        layout.addWidget(self.cross_chip)
        layout.addStretch(1)

    def cross_line(self) -> str:
        """The cross as one line, the way the status bar and the CLI say it."""
        gates = self.cross_gates.text()
        return f"{self.cross.text()} {gates}".strip()

    def update_from_model(self, model: dict) -> None:
        for key, _ in self.ROWS:
            text = model.get(key)
            if key == "profile" and text and model.get("profile_name"):
                # contract v1.1's additive field: "4/2" plus its two line archetypes.
                # Absent -- an older model -- the bare profile still reads correctly.
                text = f"{text} ({model['profile_name']})"
            self._chips[key][2].setText(str(text) if text else "--")
        cross = model.get("incarnation_cross") or {}
        gates = cross.get("gates") or []
        label = cross.get("label", "")
        # The gates go in parentheses only when the label is a NAME. On a profile the
        # model cannot name, it falls back to label="Gates a/b | c/d" and sets `named`
        # false, and appending there would print the same four gates twice in one line.
        # A model older than contract v1.2 carries no `named` key at all and its label
        # is that same gate fallback, so ABSENT has to read as "not a name": the cost
        # of being wrong that way is a missing detail, the other way is a visible
        # stutter. Matches the CLI's text line, which gates on the same field.
        named = len(gates) == 4 and cross.get("named") is True
        self.cross.setText(label or "--")
        self.cross_gates.setText(
            f"({gates[0]}/{gates[1]} | {gates[2]}/{gates[3]})" if named else "")
        self.cross_gates.setVisible(bool(named))
        self.refresh_theme()

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        palette = hd_palette()
        self.setStyleSheet(_panel_qss(colors))
        spacing = 0 if self._compact else 2
        self.title.setStyleSheet(f"color: rgba({hex_to_rgb_str(colors['secondary_text'])},"
                                 f" 0.55); letter-spacing: {spacing}px;"
                                 f" border: none; background: transparent;"
                                 + _font_css("panel_titles", bold=True))
        self.title.setFont(scaled_area_font("panel_titles", bold=True))
        line = hex_to_rgb_str(colors["secondary_text"])
        for index, (key, _) in enumerate(self.ROWS):
            chip, caption, value = self._chips[key]
            # the Type chip is the one a reader looks for first, so it wears the
            # accent; the rest are quiet
            accent = palette["red"] if index == 0 else None
            chip.setStyleSheet(
                f"background: rgba({hex_to_rgb_str(accent) if accent else line},"
                f" {0.18 if accent else 0.05});"
                f"border: 1px solid rgba({line}, 0.10); border-radius: 8px;")
            caption.setStyleSheet(f"color: rgba({line}, 0.50); letter-spacing: 1.5px;"
                                  f"border: none; background: transparent;"
                                  + _font_css("status"))
            caption.setFont(scaled_area_font("status"))
            value.setStyleSheet(f"color: {colors['secondary_text']};"
                                f"border: none; background: transparent;"
                                + _font_css("info_text", bold=True, ratio=0.86))
            value.setFont(_dense_font("info_text", bold=True))
        self.cross_chip.setStyleSheet(
            f"background: rgba({line}, 0.05);"
            f"border: 1px solid rgba({line}, 0.10); border-radius: 8px;")
        self.cross_caption.setStyleSheet(
            f"color: rgba({line}, 0.50); letter-spacing: 1.5px;"
            f"border: none; background: transparent;" + _font_css("status"))
        self.cross_caption.setFont(scaled_area_font("status"))
        # line-height gives the wrapped lines air; without it a three-line cross reads
        # as one block of text jammed into the bottom of the card
        for part, alpha in ((self.cross, 0.78), (self.cross_gates, 0.55)):
            part.setStyleSheet(f"color: rgba({line}, {alpha});"
                               f"border: none; background: transparent;"
                               f"line-height: 140%;"
                               + _font_css("status"))
            part.setFont(scaled_area_font("status"))


#: The model's own spelling of every channel key: gate numbers, low first. Anything else
#: coming from the model is not a channel this view can draw.
_MODEL_CHANNEL_KEYS = frozenset(
    f"{min(a, b)}-{max(a, b)}" for a, b, _name in CHANNEL_ORDER)


class _ChannelChip(QFrame):
    """One row of the channel index: key, name, and what KIND of line it is.

    The number and the name, and nothing else. There used to be a kind badge here --
    STRAIGHT / BRAID / a parallel-group name -- on the argument that a reader tracing a
    line needs to know how it is drawn. On screen it read as noise beside the name and
    it was taking a third of the room the name needed, so the name truncated to pay for
    it. The braid is still legible on the graph itself, which is where it matters.
    """

    clicked = Signal(str)

    def __init__(self, key: str, name: str, defined: bool, braid: bool,
                 parent=None):
        super().__init__(parent)
        self.defined, self.braid = defined, braid
        self.geometry_key = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grid = QGridLayout(self)
        # Real inner padding. It was (6, 2, 6, 2) against a 1px border with a 7px corner
        # radius, so the text started inside the curve -- it read as touching the chip
        # rather than sitting in it. The radius is why the horizontal pad is the larger.
        self._compact = False
        self._pad()
        self._grid.setHorizontalSpacing(scaled_px(8))
        self._grid.setVerticalSpacing(scaled_px(1))
        self.key = QLabel(key)
        self.key.setMinimumWidth(_key_width())
        self.key.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # WRAPS, never elides. The name had 55 px in a 206 px chip and "Channel of
        # Curiosity" came out as "Curio...", which tells the reader nothing. Wrapping
        # costs a second line in a list that already scrolls; truncating costs the name.
        self.name = QLabel(name)
        self.name.setWordWrap(True)
        self.name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # A word-wrapped label cannot break INSIDE a word, so its minimum width is its
        # longest one: "Transformation" is 94 px and would have set the floor for the
        # whole page, 32 px above what the rest of the card needs, and enough to leave
        # the graph narrower than its own index. Stacking is the way out -- see
        # set_stacked -- so the name is told it may be narrow and the LIST decides when.
        self.name.setMinimumWidth(scaled_px(1))
        self._stacked = False
        self._grid.addWidget(self.key, 0, 0)
        self._grid.addWidget(self.name, 0, 1)
        self._grid.setColumnStretch(1, 1)
        self.refresh_theme()

    def _pad(self) -> None:
        side = scaled_px(_CHIP_PAD_X_COMPACT if self._compact else _CHIP_PAD_X)
        self._grid.setContentsMargins(side, scaled_px(_CHIP_PAD_Y),
                                      side, scaled_px(_CHIP_PAD_Y))

    def set_compact(self, on: bool) -> None:
        """Give the name the room the padding was taking."""
        if on != self._compact:
            self._compact = on
            self._pad()

    def set_stacked(self, on: bool) -> None:
        """Put the name under the key instead of beside it.

        All the chips do this together, on the list's word, so the index stays one grid
        rather than a ragged mix of one- and two-line rows.
        """
        if on == self._stacked:
            return
        self._stacked = on
        self._grid.removeWidget(self.name)
        if on:
            self._grid.addWidget(self.name, 1, 0, 1, 2)
            self._grid.setColumnStretch(1, 0)
        else:
            self._grid.addWidget(self.name, 0, 1)
            self._grid.setColumnStretch(1, 1)
        self._grid.activate()

    def mousePressEvent(self, event):  # noqa: N802 - Qt name
        super().mousePressEvent(event)
        if self.geometry_key:
            self.clicked.emit(self.geometry_key)

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        palette = hd_palette()
        line = hex_to_rgb_str(colors["secondary_text"])
        bare = "border: none; background: transparent;"
        if self.defined:
            edge = hex_to_rgb_str(palette["red"])
            self.setStyleSheet(f"QFrame {{ background: rgba({edge}, 0.16);"
                               f" border: 1px solid rgba({edge}, 0.50);"
                               f" border-radius: 7px; }}")
        else:
            self.setStyleSheet(f"QFrame {{ background: rgba({line}, 0.05);"
                               f" border: 1px solid rgba({line}, 0.09);"
                               f" border-radius: 7px; }}")
        self.key.setStyleSheet(
            f"color: {palette['design'] if self.defined else colors['primary_text']};"
            f" {bare}" + _font_css("info_text", bold=True, ratio=0.86))
        self.key.setFont(_dense_font("info_text", bold=True))
        self.name.setStyleSheet(f"color: rgba({line},"
                                f" {'1.0' if self.defined else '0.72'}); {bare}"
                                + _font_css("info_text", ratio=0.86))
        self.name.setFont(_dense_font("info_text"))
        # The key column is measured from the CURRENT Info text font; set at build
        # only, it kept the old width after a font change and cut the key (td-168ze).
        self.key.setMinimumWidth(_key_width())


class _ChannelList(_NarrowsItsPadding, QFrame):
    """All 36 channels, named, the defined ones raised. The six braid channels are
    reachable HERE.

    That is deliberate: on the graph the braid's five tracks are the pointer targets, not
    its six channels, because overlapping hit paths on shared track make "which channel
    is under the cursor" arbitrary. This list is where those six stay individually
    selectable.
    """

    channel_clicked = Signal(str)

    #: In compact the title drops its letter-spacing and the chips drop padding, so the
    #: longest channel name still fits the narrow column. See _compact_column_floor.
    _compact = False

    def set_compact(self, on: bool) -> None:
        if on == self._compact:
            return
        self._compact = on
        self._narrow_padding()
        for chip in self._chips:
            chip.set_compact(on)
        self._choose_shape()
        self.refresh_theme()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        self._outer = outer
        outer.setContentsMargins(_CARD_PAD_X, 9, _CARD_PAD_X, 11)
        outer.setSpacing(5)
        self.title = QLabel("CHANNELS")
        self.count = QLabel("")
        outer.addWidget(self.title)
        outer.addWidget(self.count)
        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        # a margin down each side too, so the chips are not flush against the card edge
        self._list.setContentsMargins(scaled_px(2), scaled_px(4), scaled_px(2), 0)
        self._list.setSpacing(scaled_px(4))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(_SIDE_CARD_MIN_HEIGHT)
        outer.addWidget(scroll, 1)
        self._scroll = scroll
        self._chips = []
        self._stacked = False

    #: The widest single word in any channel name. A wrapped label cannot break inside a
    #: word, so this is the number that decides whether a name fits beside its key.
    _LONGEST_WORD = max((word for _a, _b, name in CHANNEL_ORDER
                         for word in name.split()), key=len)

    def resizeEvent(self, event):  # noqa: N802 - Qt name
        super().resizeEvent(event)
        self._choose_shape()

    def _choose_shape(self) -> None:
        """Beside the key while the longest name still fits there; under it when not."""
        if not self._chips:
            return
        metrics = QFontMetrics(self._chips[0].name.font())
        room = (self._scroll.viewport().width() - 2 * scaled_px(2)
                - 2 * scaled_px(_CHIP_PAD_X) - _key_width() - scaled_px(8))
        stacked = metrics.horizontalAdvance(self._LONGEST_WORD) > room
        if stacked == self._stacked:
            return
        self._stacked = stacked
        for chip in self._chips:
            chip.set_stacked(stacked)

    def update_from_model(self, model: dict) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chips = []

        raw = model.get("channels") or {}
        # Only channels this view can actually DRAW are counted. A key the geometry does
        # not have is a model bug, and reporting "1 of 1 defined" over an empty list --
        # which is what counting the raw dict did -- hides it behind a plausible number.
        channels = {key: value for key, value in raw.items()
                    if isinstance(value, dict) and key in _MODEL_CHANNEL_KEYS}
        self.unknown_channels = sorted(set(raw) - set(channels))
        defined = {k for k, v in channels.items() if v.get("defined")}
        self.count.setText(f"{len(defined)} of {len(channels) or 36} defined"
                           + (f"  ({len(self.unknown_channels)} unrecognised)"
                              if self.unknown_channels else ""))
        # every channel, not only the defined ones: the list is the chart's index, and a
        # reader looks things up in it by name whether or not this chart has them. The
        # order is anatomical, head to root, and the pair reads upper gate first.
        for upper, lower, _name in CHANNEL_ORDER:
            geometry_key = G.channel_key(upper, lower)
            model_key = f"{min(upper, lower)}-{max(upper, lower)}"
            if model_key not in channels:
                continue
            key, low, high = model_key, upper, lower
            chip = _ChannelChip(f"{low}-{high}", channel_name(low, high),
                                key in defined, G.is_braid(geometry_key))
            chip.setProperty("hd_channel", geometry_key)
            chip.geometry_key = geometry_key
            chip.clicked.connect(self.channel_clicked)
            self._list.addWidget(chip)
            self._chips.append(chip)
        self._list.addStretch(1)
        self.refresh_theme()
        # the chips are new, so the shape has to be decided again: _stacked describes
        # chips that no longer exist
        self._stacked = False
        self._choose_shape()

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        line = hex_to_rgb_str(colors["secondary_text"])
        self.setStyleSheet(_panel_qss(colors))
        self.title.setStyleSheet(f"color: rgba({line}, 0.55);"
                                 f" letter-spacing: {0 if self._compact else 2}px;"
                                 f"border: none; background: transparent;"
                                 + _font_css("panel_titles", bold=True))
        self.title.setFont(scaled_area_font("panel_titles", bold=True))
        self.count.setStyleSheet(f"color: rgba({line}, 0.45);"
                                 f"border: none; background: transparent;"
                                 + _font_css("status"))
        self.count.setFont(scaled_area_font("status"))
        for chip in self._chips:
            chip.refresh_theme()
        # A font change moves the longest word's width without resizing the list, so
        # the beside / stacked shape must be chosen again here, not only on resize:
        # at Info text 24 the names stayed beside the key and were cut ("Abst", td-168ze).
        self._choose_shape()


class HDPanel(QWidget):
    """The whole Human Design page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: dict = {}
        self._frame = "standard"
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(_PAGE_PAD[0], 10, _PAGE_PAD[1], 12)
        root.setSpacing(9)

        # ---- toolbar -----------------------------------------------------------------
        # Two rows, because one does not fit. Inside the app the page gets about 656 px,
        # and the bar was a single QHBoxLayout with no way to give: the brand is a plain
        # QLabel, so "HUMAN DESIGN" simply rendered as "HUMAN DESIGI" against the
        # controls. Clipped text is the one outcome that is never acceptable here -- an
        # elided label at least says it is eliding.
        self.topbar = QFrame()
        outer = QVBoxLayout(self.topbar)
        outer.setContentsMargins(12, 7, 12, 7)
        outer.setSpacing(6)
        self._row_top = QHBoxLayout()
        self._row_top.setContentsMargins(0, 0, 0, 0)
        self._row_top.setSpacing(11)
        self._row_wrap = QHBoxLayout()
        self._row_wrap.setContentsMargins(0, 0, 0, 0)
        self._row_wrap.setSpacing(11)
        outer.addLayout(self._row_top)
        outer.addLayout(self._row_wrap)

        self.brand = QLabel("HUMAN DESIGN")
        self._row_top.addWidget(self.brand)
        self.subtitle = _ElidedLabel("")
        self._row_top.addWidget(self.subtitle, 1)

        self.label_caption = QLabel("LABELS")
        self.labels = _Segmented((("numbers", "Numbers"), ("hexagrams", "Hexagrams")),
                                 "numbers")
        self.show_caption = QLabel("SHOW")
        self.filter = _Segmented((("design", "Design"), ("both", "Both"),
                                  ("personality", "Personality")), "both")
        self.motion_caption = QLabel("MOTION")
        self.motion = _Segmented((("pulse", "Pulse"), ("calm", "Calm, no motion")),
                                 "pulse")
        # one widget so the whole control group can move between the two rows
        self.controls = QWidget()
        controls_row = QHBoxLayout(self.controls)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(11)
        for widget in (self.label_caption, self.labels, self.show_caption, self.filter,
                       self.motion_caption, self.motion):
            controls_row.addWidget(widget)
        self._row_top.addWidget(self.controls)
        self._wrapped = False
        root.addWidget(self.topbar)


        # The frame is NOT chosen here. It follows the app's zodiac mode (top bar, and
        # the lock in Settings > Zodiac mode); hd_manager maps mode to frame and this
        # page is handed the result. The pill row, its ADVANCED disclosure and the
        # frame_requested signal are gone -- a second place to pick the zodiac is a
        # second place for it to disagree with itself.

        #: Raised and left standing whenever the frame is not Standard, because a chart
        #: read in the wrong frame is wrong in a way nothing on the graph reveals.

        # ---- body --------------------------------------------------------------------
        body = QHBoxLayout()
        self._body = body
        body.setSpacing(_BODY_GAP)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.design_column = _PlanetColumn("design")
        self.reading = _ReadingCard()
        left.addWidget(self.design_column)
        left.addWidget(self.reading)
        body.addLayout(left, 0)

        centre = QVBoxLayout()
        centre.setSpacing(0)
        self.graph_frame = QFrame()
        graph_layout = QVBoxLayout(self.graph_frame)
        graph_layout.setContentsMargins(6, 6, 6, 4)
        graph_layout.setSpacing(4)
        self.view = HDBodygraphView()
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        graph_layout.addWidget(self.view, 1)
        centre.addWidget(self.graph_frame, 1)
        body.addLayout(centre, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.personality_column = _PlanetColumn("personality")
        self.channels = _ChannelList()
        right.addWidget(self.personality_column)
        right.addWidget(self.channels)
        body.addLayout(right, 0)

        # Connected HERE, after the view exists, and capturing the VIEW rather than
        # self. A lambda that closes over self is owned by a child widget which is owned
        # by self, and Qt's C++ side holds that connection: the panel then survives being
        # dropped. Capturing the view leaves no edge back to the panel.
        view = self.view
        self.labels.changed.connect(lambda k: view.set_option(label_mode=k))
        self.filter.changed.connect(lambda k: view.set_option(activation_filter=k))
        self.motion.changed.connect(lambda k: view.set_option(pulse=(k == "pulse")))

        # hover travels both ways: the graph raises the rows that fed it, and a row
        # raises the gate it put there
        design, personality = self.design_column, self.personality_column
        view.focus_changed.connect(design.set_focus_gates)
        view.focus_changed.connect(personality.set_focus_gates)
        design.row_entered.connect(view.focus_gate)
        personality.row_entered.connect(view.focus_gate)
        # one grid: scrolling either column scrolls the other to the same row
        design.scrolled.connect(personality.mirror_scroll)
        personality.scrolled.connect(design.mirror_scroll)
        # clicking a row or a channel name is the same act as clicking it on the graph,
        # and must leave the view in the same pinned state
        design.row_clicked.connect(lambda g: view.pin(("gate", int(g))))
        personality.row_clicked.connect(lambda g: view.pin(("gate", int(g))))
        self.channels.channel_clicked.connect(
            lambda key: view.pin(("track", G.tracks_of_channel(key)[0])
                                 if G.is_braid(key) else ("channel", key)))

        self._sides = (design, self.reading, personality, self.channels)
        self._compact = False
        for column in (design, personality):
            # A CEILING, not a fixed width. Fixed, the two columns took 416 px of a
            # narrow centre and the graph was left 240 px -- filling 69% of the height
            # it was given, which is the same complaint as the letterboxed full screen
            # seen from the other side. The graph is the subject of this page, so the
            # columns are what yields: they elide their names already, and both use the
            # same rule so a row still sits level with its twin.
            column.setMinimumWidth(_compact_column_floor())
            column.setMaximumWidth(scaled_px(_COLUMN_WIDTH))
            # the columns are 14 fixed rows; the CARDS beneath them are what must give
            # when the page is short, so neither is allowed to impose a floor that
            # stops the page reaching 1200x900
            # Preferred, not Fixed: Fixed would pin them at the maximum and undo the
            # ceiling above. Horizontally they compress toward the measured floor.
            column.setSizePolicy(QSizePolicy.Policy.Preferred,
                                 QSizePolicy.Policy.Preferred)
        for card in (self.reading, self.channels):
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
            # The cards sit UNDER the columns and had no width ceiling, so each one grew
            # past the 208 px column above it -- measured at 275 -- and it was the CARD,
            # not the column, setting how much width the side stack took from the graph.
            # Capping the column alone did nothing for exactly that reason.
            card.setMinimumWidth(_compact_column_floor())
            card.setMaximumWidth(scaled_px(_COLUMN_WIDTH))
        # The graph's floor is what decides whether this page FITS. Raising it to 340 to
        # win the competition against the columns worked at the sizes it was tested at
        # and broke the size Lorris actually uses: 340 plus two 175 px floors plus the
        # page's own margins put the page's minimum width at 768, and the app's centre
        # stack with the side panels open is about 656. A widget cannot refuse the size
        # its parent gives it -- it simply overflows and is CLIPPED, with no scrollbar
        # and nothing to say so, which is the "content cut out at 1920 windowed" report.
        #
        # So the floor is set from the budget rather than from the wish: page overhead
        # plus two column floors, and whatever is left is the graph's. It is expressed
        # as "wider than a column" because that is the rule it exists to keep -- the
        # subject of the page must not be narrower than its own index -- and
        # _share_the_width, not this floor, is what gives the graph the room when there
        # is room to give.
        self.view.setMinimumWidth(_compact_column_floor() + scaled_px(28))
        self.view.setMinimumHeight(scaled_px(300))

        self._set_frame("standard")
        self.refresh_theme()

    # -- state ------------------------------------------------------------------------

    def update_from_chart(self, chart, **kwargs) -> None:
        """Show an HDModel. Same signature as every other chart view."""
        # every reader below -- both columns, both cards, the subtitle -- assumes the
        # model's shape. Guarantee it once here rather than at each of them.
        self._model = normalise_model(chart)
        self.view.update_from_chart(self._model, **kwargs)
        self.design_column.update_from_model(self._model)
        self.personality_column.update_from_model(self._model)
        self.reading.update_from_model(self._model)
        self.channels.update_from_model(self._model)
        self._set_frame(self._model.get("frame", "standard"))
        self.subtitle.setText(" · ".join(
            part for part in (self._model.get("type"),
                              f"Profile {self._model.get('profile')}"
                              if self._model.get("profile") else None,
                              f"{self._model.get('authority')} authority"
                              if self._model.get("authority") else None) if part))
        self.refresh_theme()

    #: The narrowest the subtitle is worth keeping. Below this it is a few characters
    #: and an ellipsis, which tells the reader nothing the title bar has not.
    _SUBTITLE_MIN = 90

    def _lay_out_header(self) -> None:
        """Degrade the header instead of clipping it.

        In order, as the page narrows: drop the subtitle, then the group captions
        (LABELS / SHOW / MOTION -- the pills under them say Numbers, Design, Pulse and
        are legible without their heading), then move the whole control group onto a
        second row. The brand never gives way and is never cut.

        Measured against sizeHint each pass rather than remembered, because the font
        scale and the theme both change these widths and a remembered breakpoint would
        be right at one setting and wrong at the next.
        """
        if not hasattr(self, "controls"):
            return
        room = self.topbar.width() - 24                      # the bar's own margins
        brand = self.brand.sizeHint().width()

        def controls_width(with_captions: bool) -> int:
            for caption in (self.label_caption, self.show_caption, self.motion_caption):
                caption.setVisible(with_captions)
            self.controls.layout().activate()
            return self.controls.sizeHint().width()

        def wrap(on: bool) -> None:
            if on == self._wrapped:
                return
            self._wrapped = on
            (self._row_wrap if on else self._row_top).addWidget(self.controls)

        full = controls_width(True)
        if brand + 11 + self._SUBTITLE_MIN + 11 + full <= room:
            self.subtitle.setVisible(True)
            wrap(False)
            return
        self.subtitle.setVisible(False)
        if brand + 11 + full <= room:
            wrap(False)
            return
        bare = controls_width(False)
        if brand + 11 + bare <= room:
            wrap(False)
            return
        # last resort: the controls take their own row, and get their captions back if
        # they fit there -- the row is theirs alone, so it is usually roomier
        wrap(True)
        controls_width(full <= room)

    def _body_overhead(self) -> int:
        """Horizontal room outside the three columns: the page's own margins plus the
        two gaps in the body row. It was a constant 44; in compact the page tightens
        both, because every pixel here is a pixel the graph does not get and in the
        narrow case the graph is what is short."""
        margins = self._root.contentsMargins()
        return margins.left() + margins.right() + 2 * self._body.spacing()

    def resizeEvent(self, event):  # noqa: N802 - Qt name
        super().resizeEvent(event)
        self._share_the_width()
        self._lay_out_header()

    def _set_compact(self, on: bool) -> None:
        """Both columns together, always. One compact and one roomy would put the two
        halves of the chart on different grids, which is the one thing this page may
        not do."""
        if on == self._compact:
            return
        self._compact = on
        left, right = _PAGE_PAD_COMPACT if on else _PAGE_PAD
        top = self._root.contentsMargins().top()
        bottom = self._root.contentsMargins().bottom()
        self._root.setContentsMargins(left, top, right, bottom)
        self._body.setSpacing(_BODY_GAP_COMPACT if on else _BODY_GAP)
        for card in (self.design_column, self.personality_column,
                     self.reading, self.channels):
            card.set_compact(on)

    def _share_the_width(self) -> None:
        """Both sides get the SAME width; the graph gets what is left.

        Left to Qt this came out 208 and 164 -- when a QHBoxLayout has to take width
        back it shrinks whichever side it reaches first, and the two side stacks have
        different natural widths because their CARDS differ. Unequal sides break the
        one rule this page is built on, that a row sits level with its twin: the two
        gate.line values stop lining up across the page.

        So the split is decided here rather than inferred. The graph is the subject and
        is served first, up to its floor; the sides share what remains, equally, between
        their own floor and ceiling.
        """
        if not getattr(self, "_sides", None):
            return
        # Decided FIRST, and from the page width alone. Both the overhead and the column
        # floor change when compact turns on, so a trigger that reads either of them
        # reads a quantity it is about to move: measured at 725 px the page came out
        # compact on the way down and roomy on the way up, flipping as it was resized.
        # The question is always "would the ROOMY page starve the graph here", never
        # "does it now".
        roomy = self.width() - (_PAGE_PAD[0] + _PAGE_PAD[1] + 2 * _BODY_GAP)
        self._set_compact(roomy - 2 * _column_floor() < scaled_px(_COMPACT_GRAPH))
        usable = self.width() - self._body_overhead()
        # What the graph needs to FILL the height it has been given. The graph keeps its
        # aspect ratio, so width is what decides whether it fills vertically: at full
        # screen it was reaching only 91% of the height with 208 px sides, purely
        # because it was 34 px short of the width that height implied.
        height = self.view.height()
        wants = height * (VIEWBOX.width() / VIEWBOX.height()) if height > 0 else 0
        graph = max(self.view.minimumWidth(), wants)
        side = int((usable - graph) // 2)
        # Below a certain page width the honest split stops being useful: at 660 px the
        # roomy columns leave the graph 248 px, which is legible in the sense that
        # nothing is cut and unreadable in the sense that matters. So the columns give
        # up their planet NAMES -- the glyph is the name, and the tooltip has the word --
        # and the graph gets the difference. Decided above, before anything reads a
        # width that compact would change.
        floor = _compact_column_floor() if self._compact else _column_floor()
        side = max(floor, min(max(scaled_px(_COLUMN_WIDTH), floor), side))
        for widget in self._sides:
            if widget.width() != side:
                widget.setFixedWidth(side)

    def _set_frame(self, key: str) -> None:
        """Record the frame the model came in. Nothing is drawn for it.

        There was a standing warning here whenever the frame was not Standard, on the
        reasoning that a chart read in a shifted frame is wrong in a way the graph never
        reveals. That reasoning was sound while any user could reach the shifted frames
        from this page. They no longer can: HD is locked to Standard unless the user
        goes and turns on the Advanced HD setting deliberately, and the explanation
        belongs next to that switch rather than on every chart afterwards. A warning
        nobody can trigger by accident is a warning nobody reads.
        """
        self._frame = key

    # -- theme -------------------------------------------------------------------------

    def refresh_theme(self) -> None:
        colors = get_theme_colors()
        palette = hd_palette()
        line = hex_to_rgb_str(colors["secondary_text"])

        self.setStyleSheet(f"background: {palette['bg1']};")
        self.topbar.setStyleSheet(_panel_qss(colors))
        # The graph sits ON the page, not in a box on it. It used to take the same
        # panel fill and 1 px border as the cards, which drew a hard rectangle around
        # a gradient that stopped at exactly that rectangle.
        self.graph_frame.setStyleSheet("background: transparent; border: none;")

        # the wordmark takes its weight from the theme's own ink, not from a palette
        # hue: a yellow wordmark is invisible on the light theme's near-white bar
        self.brand.setTextFormat(Qt.TextFormat.RichText)
        self.brand.setText(
            f"<span style='color:{colors['primary_text']}'>HUMAN</span> "
            f"<span style='color:{palette['red']}'>DESIGN</span>")
        self.brand.setStyleSheet("letter-spacing: 3px;"
                                 "border: none; background: transparent;"
                                 + _font_css("panel_titles", bold=True))
        self.brand.setFont(scaled_area_font("panel_titles", bold=True))
        for caption in (self.subtitle, self.label_caption, self.show_caption,
                        self.motion_caption):
            caption.setStyleSheet(f"color: rgba({line}, 0.45); letter-spacing: 1.5px;"
                                  f"border: none; background: transparent;"
                                  + _font_css("status"))
            caption.setFont(scaled_area_font("status"))

        for child in (self.labels, self.filter, self.motion,
                      self.design_column, self.personality_column, self.reading,
                      self.channels):
            child.refresh_theme()
        self.view.refresh_theme()
        # a theme or font-scale change moves every width in the bar, so the header has
        # to be re-decided here as well as on resize
        self._lay_out_header()
