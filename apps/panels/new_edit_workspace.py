# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
New & Edit workspace — the VIEW of the redesigned New & Edit tab (WI-1).

One widget, no brain. It owns the fields, the embedded place picker and the
footer actions of the New & Edit mockup, and it emits what the user did. It
does NOT convert local time to UTC, geocode a place, build a chart or write a
file: a separate controller (its own work item) drives the setters below and
answers the signals. That split is the whole point — the same surface has to
serve BOTH "create a new chart" and "edit the loaded one", and a view that
decided anything for itself would have to know which of the two it was in.

What it mirrors, and why exactly
--------------------------------
* ``collect_data()`` returns the SAME dict — same keys, same types, same
  Local/UTC hour selection rule — as ``EditInfoSubTab.collect_data``. The
  downstream contract (BirthDataManager, the CHTK writer) is pinned there;
  a second dialect of the same form would be a second set of bugs.
* ``set_coordinates`` / ``set_city`` / ``set_country`` / ``set_timezone`` /
  ``set_location_note`` keep the semantics of the ``EditInfoSubTab`` setters of
  those names, so an existing host can drive this view unchanged. The one
  deliberate difference: ``set_timezone`` here does not re-derive an offset or
  touch DST (that is calculation, and calculation is the controller's).
* The three element accents (Fire / Air / Earth) are the DOMAIN palette from
  ``wheel_items.py``, passed through ``desat_hex`` exactly once (SPEC-SAT-001),
  like ``token_entry_bar.py``. They are meaning, not theme: step 2 is "air"
  everywhere, in both light and dark.

Deliberately absent
-------------------
The mockup's header theme toggle (dropped — the app has one already) and the
AI-assist affordance on the entry bar (its own work item). Region and elevation
ARE shown, because a picked place has them and hiding them makes the picker
look lossy, but they are DECORATIVE: nothing reads them, nothing persists them.
"""

import traceback

from PySide6.QtCore import (QByteArray, QEasingCurve, QEvent,
                            QPropertyAnimation, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDoubleValidator,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QIntValidator,
    QPixmap,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QValidator,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtSvg import QSvgRenderer

from apps.panels.edit_map_subtab import EditMapSubTab
from apps.widgets.token_entry_bar import TokenEntryBar
from ui.qt_theme import desat_hex, dim_text, get_theme_colors, is_light_theme
from ui.themed_style import ThemedStyleMixin

__all__ = ["NewEditWorkspace"]

# Rodden Rating (Lois Rodden's data-accuracy scale, as used by Astro-Databank).
# Ordered by DESCENDING reliability so the help table reads as a scale. The
# empty string is the first-class "unrated" state (collect_data reports '' for
# it, exactly like gender), never a code. These meanings are approved copy; the
# help popup renders them and each is also the action's accessible description.
_RODDEN_CODES = (
    ("AA", "Accurate. From a birth certificate, official record, or a document "
           "recorded at the time (baptismal, family bible)."),
    ("A",  "Accurate. Quoted from the person, family, friend, or associate, "
           "from memory."),
    ("B",  "Biography or autobiography. From a published book rather than "
           "quoted directly."),
    ("C",  "Caution, no source. Undocumented or \"personal\" data, origin "
           "unknown."),
    ("DD", "Dirty data. Two or more conflicting or unverified sources; data in "
           "dispute."),
    ("X",  "No birth time. The date is known but no time was recorded."),
    ("XX", "No birth date. No reliable birth data at all."),
)
_RODDEN_VALUES = tuple(code for code, _ in _RODDEN_CODES)

#: Help "?" glyph for the Rodden control (design by Opus 5). GLYPH-ONLY on a
#: "0 0 24 24" grid: the button already draws the circular chip + border via
#: stylesheet, so a self-contained badge would double the ring. Stroke-based
#: (not filled) at 2.75 weight with round caps so the hook survives rasterizing
#: at 22px on a dark surface -- the exact "invisible hairline" failure the old
#: 9.5px text "?" had. ``currentColor`` is substituted with the accent ink at
#: render time (QSvgRenderer has no CSS cascade, so it must be a concrete hex).
_RODDEN_HELP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
    ' width="24" height="24" fill="none">'
    '<path d="M8.6 9.2a3.5 3.5 0 1 1 4.9 3.2c-1 .6-1.5 1.25-1.5 2.25v.55"'
    ' stroke="currentColor" stroke-width="2.75"'
    ' stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="12" cy="18.55" r="1.45" fill="currentColor"/>'
    '</svg>'
)


class _BoundedIntValidator(QIntValidator):
    """QIntValidator that BLOCKS typing an impossible value.

    Plain QIntValidator returns ``Intermediate`` (not ``Invalid``) for an
    in-range-digit-count value that is out of bounds, so a user can type ``13``
    into a month field and it only trips at Create/Save time. Here we return
    ``Invalid`` — which the line edit refuses — for any value that has already
    overshot the top and can therefore never grow back into range (``13`` for a
    1..12 field, ``32`` for 1..31, ``24`` for 0..23, ``60`` for 0..59). Values
    still below the bottom stay ``Intermediate`` so partial input like ``0`` on
    the way to ``05`` is not blocked. Only USER keystrokes are gated; the ranges
    are non-negative here, so no sign handling is needed, and ``setText`` /
    ``populate`` bypass validation entirely (load paths are unaffected).
    """

    def validate(self, text, pos):
        if text == "":
            return (QValidator.State.Intermediate, text, pos)
        if not text.isdigit():
            return (QValidator.State.Invalid, text, pos)
        value = int(text)
        if value > self.top():
            return (QValidator.State.Invalid, text, pos)
        if value < self.bottom():
            return (QValidator.State.Intermediate, text, pos)
        return (QValidator.State.Acceptable, text, pos)

#: Element palette, authoritative copy from ``apps/widgets/wheel_items.py``.
#: DOMAIN data, not theme data. Literals, so they need ``desat_hex`` — unlike
#: ``get_theme_colors()`` values, which arrive already desaturated
#: (SPEC-SAT-001: desaturate once, never twice).
ELEMENT_COLORS = {
    "Fire": "#E57373",
    "Earth": "#A67C52",
    "Air": "#F0C75E",
    "Water": "#1E4D8C",
}

MONO = "'JetBrains Mono', 'DejaVu Sans Mono', monospace"

# ---- Type scale and metrics, ported from the mockup ------------------------
# The mockup states these in px and they are RELATIVE to its 13px base, which is
# also what qt-material sets, so px ports 1:1 and keeps the intended
# proportions. Pinning them here also stops the panel inheriting a size for
# controls while its labels stay fixed — that mismatch is what made the form
# look inflated next to the mockup.
BASE_FONT = "13px"        # --fs, and .inp / .combo input
LABEL_FONT = "10.5px"     # .fl row labels, .chip
UNIT_FONT = "9.5px"       # .combo .unit
TITLE_FONT = "11px"       # .sthead h3
TAG_FONT = "10.5px"       # tags and step badges
CHIP_VALUE_FONT = "12px"  # summary card values

#: The mockup's `.fr` gap is 10 and its `.fl` column is 84. Both are shaved a
#: little here because the widest row (coordinates: label + two 6-decimal
#: fields + two hemisphere chips) had ~6 px of slack, which is not slack — the
#: same row fits at 13 px and overflows once anything moves. 8/78 buys ~14 px,
#: and the steps viewport now shows a scrollbar rather than clipping if a large
#: font eats even that.
ROW_SPACING = 8
LABEL_COLUMN = 78
HINT_FONT = "10.5px"      # .smartline .hintk

#: --ok from the mockup: the toast's confirmation edge. Rule 20 semantic
#: exception (success), desaturated once like the element colours.
OK_HEX = "#4CAF50"

#: Qt applies min/max-height to the CONTENT box, so a 1 px border adds 2 px to
#: the painted height. Bordered controls therefore ask for two pixels less, or
#: they end up taller than the borderless ones sitting next to them.
BORDER_ADJUST = 2

#: Qt's QWIDGETSIZE_MAX. PySide6 does not export it from QtWidgets, so it is
#: named here rather than left as a bare 16777215 at each call site.
MAX_WIDGET_WIDTH = 16777215

BUTTON_RADIUS = 10        # --r
BUTTON_HEIGHT = 34        # .btn height
BUTTON_PAD_X = 15         # .btn padding
BUTTON_FONT = "12.5px"    # .btn font
BUTTON_WEIGHT = 600

#: The mockup states `.btn.primary{color:#fff}` outright, and white-on-blue is
#: what a primary action looks like everywhere. Contrast-picking the ink instead
#: chose BLACK on both themes (on #448aff black measures 5.2:1 to white's 3.3:1)
#: and inverted the design. This is a deliberate, measured deviation from
#: contrast-optimal: the ratio is the mockup's own, and the button is a large,
#: bold, unambiguous target. The element BADGES keep the measured pick, because
#: there the mockup itself concedes the principle — it hardcodes dark ink on the
#: light Air badge for exactly this reason.
PRIMARY_BUTTON_INK = "#ffffff"
#: The mockup says 32, but a QLineEdit at 13px will not paint below 34 — its
#: own minimumSizeHint (font metrics + frame margins) outranks a QSS max-height,
#: verified by measurement. Matching the combos to the real floor keeps the row
#: internally consistent, which reads better than two heights two pixels apart.
FIELD_HEIGHT = 34         # .inp / .combo height (mockup 32, Qt floor 34)

#: The mockup's ``minmax(430px, 500px)`` left column. The map is what gives way
#: when the window narrows, because a half-width map still works and a
#: half-width form does not.
IDENTITY_MIN_WIDTH = 430
IDENTITY_MAX_WIDTH = 500

#: ``EditMapSubTab`` cannot go below this (its search field alone sets a 250 px
#: floor). Measured, not guessed — see ``_orientation_for``.
MAP_MIN_WIDTH = 465

#: Widest value each measured field must hold WITHOUT clipping. Six signed
#: decimals is what ``set_coordinates`` writes ("%.6f"), so it is the real
#: worst case, not a comfortable-looking sample.
COORD_SAMPLE = "-123.456789"

#: Horizontal gutter, as a fraction of window width, clamped. ONE knob for all
#: four bands (entry bar, header, splitter, footer) so they cannot drift apart.
#: 16 px is right on a small window and far too thin on a wide one, where the
#: whole workspace ends up pinned against the right edge with no breathing room.
SIDE_GUTTER_MIN = 16
SIDE_GUTTER_MAX = 44
SIDE_GUTTER_RATIO = 0.024

#: Alpha of the accent fill behind a tag's own text — the tag's contrast is
#: measured against this composite, not against the bare panel.
TAG_TINT = 0.16
OFFSET_SAMPLE = "+13:45"


def _rgba(hex_color, alpha):
    """``rgba(...)`` for a hex colour — Qt has no ``color-mix()``.

    Same translation as ``token_entry_bar._rgba``: an explicit alpha keeps the
    widget underneath showing through, so tinted fills need no light/dark
    branch.
    """
    color = QColor(hex_color)
    if not color.isValid():
        return hex_color
    return "rgba(%d, %d, %d, %.3f)" % (
        color.red(), color.green(), color.blue(), max(0.0, min(1.0, alpha)))


def _element_hex(element):
    """Desaturated element colour (SPEC-SAT-001 — applied once, here)."""
    return desat_hex(ELEMENT_COLORS[element])


def _relative_luminance(color):
    """WCAG relative luminance of a QColor (sRGB linearised, then weighted)."""
    def channel(value):
        return (value / 12.92 if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4)

    return (0.2126 * channel(color.redF())
            + 0.7152 * channel(color.greenF())
            + 0.0722 * channel(color.blueF()))


#: Luminance of the "#1a1a1a" ink, precomputed for the comparison in _ink_on.
_INK_DARK_LUMA = 0.01106


def _contrast(hex_a, hex_b):
    """WCAG contrast ratio between two hex colours."""
    lum_a = _relative_luminance(QColor(hex_a))
    lum_b = _relative_luminance(QColor(hex_b))
    hi, lo = max(lum_a, lum_b), min(lum_a, lum_b)
    return (hi + 0.05) / (lo + 0.05)


def _lighten(hex_color, factor=112):
    """A lighter shade, for the hover gradient's top stop.

    The mockup hovers with `filter: brightness(1.06)`, which QSS has no
    equivalent for. Lifting the top stop keeps it a GRADIENT — setting both
    stops to the same colour (the previous rule) flattened the button on hover,
    which reads as a different control rather than the same one lit.
    """
    return QColor(hex_color).lighter(factor).name()


def _blend(color, backdrop, alpha):
    """``color`` at ``alpha`` composited over ``backdrop``, as a QColor."""
    top, back = QColor(color), QColor(backdrop)
    return QColor(*[round(alpha * t + (1 - alpha) * b)
                    for t, b in ((top.red(), back.red()),
                                 (top.green(), back.green()),
                                 (top.blue(), back.blue()))])


def _element_ink(element, tint=0.0, floor=4.5):
    """An element accent used as TEXT, moved AWAY from its background until it
    is readable.

    The element palette is tuned to be seen as a FILL. As ink it collapses
    against whichever end of the range its own lightness sits near: Air
    (#F0C75E) on the light theme's #f5f5f5 is 1.4:1 — the yellow tag nobody
    could read — and Water (#1E4D8C) on the dark theme's #232629 is 1.81:1.

    So the direction cannot be fixed: darkening is right on light and WRONG on
    dark. An earlier version only ever darkened, which pushed Water to #06101d
    (1.26:1) — worse than the untouched colour it was trying to rescue, and
    invisible. The hue is preserved either way, so step 2 still reads as air.

    ``tint`` is the alpha of a fill drawn from this same accent behind the text
    (the chips and tags do exactly that): the contrast that matters is against
    the COMPOSITED background, not against the bare panel.
    """
    surface = get_theme_colors()["secondary"]
    lighten = not is_light_theme()
    ink = QColor(_element_hex(element))
    for _ in range(16):
        backdrop = _blend(ink, surface, tint) if tint else QColor(surface)
        if _contrast(ink.name(), backdrop.name()) >= floor:
            break
        moved = ink.lighter(112) if lighten else ink.darker(112)
        if moved.rgb() == ink.rgb():
            break          # hit black or white; no further move available
        ink = moved
    return ink.name()


def _muted_alpha(floor=4.5):
    """The alpha the dim tier needs, MEASURED rather than chosen.

    The two themes are not symmetric (the light foreground is ``#555555`` on
    ``#f5f5f5``, the dark one is ``#ffffff`` on ``#232629``), and this text
    lands on TWO different surfaces — the panel (``secondary``) and the inset
    combo/chip fills (``secondary_dark``). A constant tuned against one of them
    misses on the other: 0.78 gives 4.05:1 on ``#f5f5f5`` but only 3.69:1 on
    ``#e6e6e6``. So take the lowest alpha that clears the floor on EVERY
    surface the text actually sits on, which re-derives itself for any theme
    rather than being right for two of them.
    """
    theme = get_theme_colors()
    foreground = theme["secondary_text"]
    surfaces = (theme["secondary"], theme["secondary_dark"])
    for candidate in (0.62, 0.70, 0.78, 0.86, 0.94, 1.0):
        if all(_contrast(_blend(foreground, surface, candidate).name(),
                         surface) >= floor for surface in surfaces):
            return candidate
    return 1.0


def _muted_ink(floor=4.5):
    """The dim foreground tier, on BOTH themes, as a QSS ``color:`` value.

    The 8-key palette has exactly one foreground (``secondary_text``) and no
    dim tier, so this used to reach for ``secondary_light`` — which is
    ``#4f5b62`` on dark but ``#ffffff`` on light. That is the white-on-white:
    every caption, unit and field label styled that way was pure white on a
    ``#f5f5f5`` panel. ``dim_text`` is the central policy for this (SPEC-THM-001,
    td-iqjb F2): alpha on the real foreground reads as grey either way.

    STYLESHEETS ONLY. Painted text must use :func:`_muted_ink_color`.
    """
    return dim_text(get_theme_colors()["secondary_text"], _muted_alpha(floor))


def _muted_ink_color(floor=4.5):
    """The same dim tier as :func:`_muted_ink`, as a paintable ``QColor``.

    Two ways to say a colour, and they are not interchangeable. QSS takes the
    ``rgba(...)`` STRING; ``QColor`` cannot parse it and answers an INVALID
    colour, which paints black — silently, since an invalid QColor raises
    nothing. Measured on the derived DST label before this existed: ``#03060a``
    on the dark theme's ``#232629`` panel, i.e. a label that is there and
    cannot be read. Composite the alpha here instead of carrying it.
    """
    theme = get_theme_colors()
    return _blend(theme["secondary_text"], theme["secondary"],
                  _muted_alpha(floor))


def _hairline(alpha=0.22):
    """A divider/border that survives both themes, for the same reason.

    ``secondary_light`` as a BORDER is invisible on light (white on near-white)
    exactly as it is as text. Translucent foreground gives a visible hairline
    against any surface without adding a 9th palette key.

    STYLESHEETS ONLY. Painted strokes must use :func:`_hairline_color`.
    """
    return _rgba(get_theme_colors()["secondary_text"], alpha)


def _hairline_color(alpha=0.22):
    """The same hairline as :func:`_hairline`, as a paintable ``QColor``.

    A painter keeps real alpha, so this sets it on the colour rather than
    compositing. Handing the ``rgba(...)`` string to ``QColor`` gives an
    invalid, opaque BLACK — see :func:`_muted_ink_color` for the measurement.
    """
    color = QColor(get_theme_colors()["secondary_text"])
    color.setAlphaF(alpha)
    return color


def _accent_ink():
    """An accent readable as TEXT on the panel surface.

    ``primary_light`` is legible on a dark panel and washed out on a light one;
    ``primary_dark`` is the reverse. Pick per theme rather than compromising.
    """
    theme = get_theme_colors()
    return theme["primary_dark"] if is_light_theme() else theme["primary_light"]


def _ink_on(hex_color):
    """Black or white, whichever is readable ON ``hex_color``.

    Rule 20 SEMANTIC EXCEPTION, same class as the badge colours themselves: the
    element accents are DOMAIN data, so the text that sits on top of them has to
    be chosen from the fill, not from the theme. ``primary_text`` is what was
    used before and it is ``#3c3c3c`` on the light theme — dark grey on a mid
    Fire red is the contrast failure this replaces.
    """
    color = QColor(hex_color)
    if not color.isValid():
        return "#ffffff"
    # WCAG relative luminance — sRGB values LINEARISED first. Skipping the
    # linearisation (the tempting one-liner) understates dark-ink-on-light by a
    # factor of two and would pick the wrong ink for the mid-range accents. Then
    # simply ASK which ink wins, rather than thresholding a luminance: a cutoff
    # is wrong exactly in the middle of the range, where Fire (#E57373, black
    # 5.8:1 vs white 3.0:1) and Earth (#A67C52, 4.7 vs 3.7) both live.
    luma = _relative_luminance(color)
    on_dark = (luma + 0.05) / (_INK_DARK_LUMA + 0.05)
    on_light = 1.05 / (luma + 0.05)
    return "#1a1a1a" if on_dark >= on_light else "#ffffff"


class ToggleSwitch(QWidget):
    """A sliding on/off switch with a THIRD visual state: derived.

    Painted rather than assembled from a styled QCheckBox because the state
    that matters here has no checkbox equivalent. "Auto from zone" makes the
    DST answer come from the time zone instead of the user, and the switch then
    has to show a real value that the user did not set and cannot set. A
    disabled checkbox says "unavailable"; this says "true, but not yours" — the
    track keeps its ON colour at reduced strength instead of going grey.

    The distinction is not decoration. Greying it out would read as "DST is
    off", which is the opposite of what an auto-resolved DST=1 means.

    ``toggled(bool)`` is emitted ONLY for user interaction, never for
    :meth:`setChecked`. A derived write must not look like a decision, or the
    "manual toggle turns Auto off" rule fires on every programmatic refresh and
    silently drops the user out of auto mode.
    """

    toggled = Signal(bool)

    _TRACK_W = 34
    _TRACK_H = 18
    _KNOB_M = 2

    def __init__(self, label="", parent=None):
        super().__init__(parent)
        self._checked = False
        self._derived = False
        self._label = label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(label)
        self._font = QFont()
        self._font.setPixelSize(int(float(LABEL_FONT.rstrip("px"))))
        metrics = QFontMetrics(self._font)
        self._text_w = metrics.horizontalAdvance(label) if label else 0
        self.setFixedHeight(max(self._TRACK_H + 4, metrics.height() + 4))
        self.setFixedWidth(self._TRACK_W + (8 + self._text_w if label else 0))

    # -- state ---------------------------------------------------------------

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        """Programmatic write. Deliberately SILENT — see the class docstring."""
        value = bool(value)
        if value != self._checked:
            self._checked = value
            self.update()

    def setDerived(self, derived):
        """Show the value as coming from somewhere other than the user."""
        derived = bool(derived)
        if derived != self._derived:
            self._derived = derived
            self.setCursor(Qt.CursorShape.ArrowCursor if derived
                           else Qt.CursorShape.PointingHandCursor)
            self.update()

    def isDerived(self):
        return self._derived

    # -- interaction ---------------------------------------------------------

    def _user_toggle(self):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            # A derived switch still ACCEPTS the click: it is the user's way of
            # saying "I want to set this myself", and the host answers by
            # turning the source off. Swallowing the click would leave them
            # poking a control that visibly does nothing.
            self._user_toggle()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                           Qt.Key.Key_Enter):
            self._user_toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- paint ---------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = get_theme_colors()

        track = QColor(desat_hex(OK_HEX)) if self._checked else QColor(
            theme["secondary_dark"])
        if self._checked and self._derived:
            # Same hue, less insistence: the value is real, the authorship is
            # not the user's.
            track.setAlpha(120)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        top = (self.height() - self._TRACK_H) // 2
        painter.drawRoundedRect(0, top, self._TRACK_W, self._TRACK_H,
                                self._TRACK_H / 2, self._TRACK_H / 2)
        if not self._checked:
            painter.setPen(QPen(_hairline_color(0.28), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(0, top, self._TRACK_W - 1, self._TRACK_H - 1,
                                    (self._TRACK_H - 1) / 2,
                                    (self._TRACK_H - 1) / 2)

        knob = self._TRACK_H - 2 * self._KNOB_M
        x = (self._TRACK_W - knob - self._KNOB_M) if self._checked else self._KNOB_M
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff" if self._checked
                                else theme["secondary"]))
        painter.drawEllipse(x, top + self._KNOB_M, knob, knob)

        if self._label:
            painter.setFont(self._font)
            painter.setPen(_muted_ink_color() if self._derived
                           else QColor(theme["secondary_text"]))
            painter.drawText(self._TRACK_W + 8, 0,
                             self._text_w + 2, self.height(),
                             int(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter),
                             self._label)


class NewEditWorkspace(ThemedStyleMixin, QWidget):
    """Fields, chips, map and footer for the New & Edit tab. View only.

    Public attributes the controller uses directly:
        ``token_bar`` — the shared :class:`TokenEntryBar` (not re-implemented).
        ``map_tab``   — the real :class:`EditMapSubTab`. The controller calls
                        ``add_addon`` / ``set_selection_policy`` /
                        ``set_time_basis`` on it; this view never does, because
                        those express what the HOST wants from a click.
        ``gui``       — left None; a host may set it, and the map reads it
                        through ``getattr`` to find the loading manager.

    Signals — the controller contract:
        ``mode_changed(str)``     'new' | 'edit', on a USER segment click.
        ``create_requested()``    New-mode primary action.
        ``save_requested()``      Edit-mode primary action.
        ``cancel_requested()``    Edit-mode cancel.
        ``clear_requested()``     Clear form.
        ``copy_all_requested()``  Copy all.
        ``field_edited(str)``     One user edit, by logical field name.

    ``field_edited`` names: ``name``, ``date``, ``local_time``, ``utc_time``,
    ``offset``, ``timezone``, ``dst``, ``city``, ``country``, ``lat``, ``lon``
    — plus ``gender`` and ``time_mode``, which are the only other inputs a user
    can touch and would otherwise leave a dirty form looking clean.

    Every programmatic setter suppresses ``field_edited``: a signal that fires
    for the controller's own write is how a view/controller pair starts
    oscillating.
    """

    mode_changed = Signal(str)
    create_requested = Signal()
    save_requested = Signal()
    save_open_requested = Signal()
    cancel_requested = Signal()
    clear_requested = Signal()
    copy_all_requested = Signal()
    field_edited = Signal(str)
    #: a locked time-zone field was touched — the controller shows the "fill it
    #: from the map/search, or unlock" hint (the fields fill automatically).
    tz_locked_field_touched = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("newEditWorkspace")

        #: A host may assign this; ``EditMapSubTab`` reads it via ``getattr`` to
        #: reach the loading manager and tolerates it being absent or None.
        self.gui = None

        self._mode = "new"
        #: True while a setter writes fields, so the resulting ``textChanged``
        #: storm is not reported back as user editing.
        self._suppress = False
        #: Summary cards the controller has pinned with ``set_summary``; the
        #: auto-derived text stops touching those until they are un-pinned with
        #: an empty string.
        self._summary_pins = {}
        self._summary_cards = []
        self._summary_columns = 0
        #: (field, widest text it must hold, chrome px) — re-measured whenever
        #: the font can have changed, so a width is never stale.
        self._measured_fields = []
        #: Splitter orientation currently applied; see ``_apply_orientation``.
        self._orientation = Qt.Orientation.Horizontal

        self._build_ui()
        self._setup_validators()
        self._setup_bindings()
        self._build_toast()
        self.set_mode("new")
        self._update_summary()
        self._refit_fields()

    # =========================================================================
    # CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The existing smart entry bar, mounted as-is.
        self.token_bar = TokenEntryBar(self)
        outer.addWidget(self.token_bar)

        outer.addWidget(self._build_header())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(10)

        self.identity_panel = self._build_identity_panel()
        self.place_panel = self._build_place_panel()
        self.splitter.addWidget(self.identity_panel)
        self.splitter.addWidget(self.place_panel)
        # The form holds its width; the map absorbs whatever is left and is the
        # one allowed to collapse (mockup: minmax(430px,500px) 1fr).
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        self.splitter.setSizes([500, 900])

        wrap = QWidget()
        wrap_layout = QHBoxLayout(wrap)
        self._wrap_layout = wrap_layout
        wrap_layout.setContentsMargins(SIDE_GUTTER_MIN, 10, SIDE_GUTTER_MIN, 8)
        wrap_layout.addWidget(self.splitter)
        outer.addWidget(wrap, 1)

        outer.addWidget(self._build_footer())

    # -- header ---------------------------------------------------------------

    def _build_header(self):
        header = QWidget()
        layout = QHBoxLayout(header)
        self._header_layout = layout
        layout.setContentsMargins(SIDE_GUTTER_MIN, 10, SIDE_GUTTER_MIN, 2)
        layout.setSpacing(12)

        self.mode_segment = QFrame()
        self.mode_segment.setObjectName("modeSegment")
        self.mode_segment.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,
                                       True)
        seg_layout = QHBoxLayout(self.mode_segment)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(2)

        self.mode_group = QButtonGroup(self)
        self.new_mode_btn = QPushButton("New chart")
        self.edit_mode_btn = QPushButton("Edit loaded")
        for index, button in enumerate((self.new_mode_btn,
                                        self.edit_mode_btn)):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFlat(True)
            self.mode_group.addButton(button, index)
            seg_layout.addWidget(button)
            self._register_themed(button, self._segment_button_style)

        self.mode_tag = QLabel("New")
        self.mode_tag.setObjectName("modeTag")
        self.mode_tag.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.mode_segment)
        layout.addWidget(self.mode_tag)
        layout.addStretch(1)

        self._register_themed(self.mode_segment, self._segment_frame_style)
        self._register_themed(self.mode_tag, self._tag_style)
        return header

    # -- left panel: chart identity -------------------------------------------

    def _build_identity_panel(self):
        panel = QFrame()
        panel.setObjectName("identityPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setMinimumWidth(IDENTITY_MIN_WIDTH)
        panel.setMaximumWidth(IDENTITY_MAX_WIDTH)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head, self.identity_tag = self._panel_head("Chart identity", "New")
        layout.addWidget(head)

        # The steps scroll; the summary row stays pinned to the bottom, so a
        # 768 px-tall window still shows what the form currently means.
        steps = QWidget()
        steps_layout = QVBoxLayout(steps)
        # 10 rather than 16: the step frames carry their own left padding and
        # the panel its own inset, so the outer 16 was a third margin on the
        # same edge — and it was the 6 px that pushed the coordinate row past
        # the viewport.
        steps_layout.setContentsMargins(10, 6, 10, 6)
        steps_layout.setSpacing(0)
        steps_layout.addWidget(self._build_step_one())
        steps_layout.addWidget(self._build_step_two())
        steps_layout.addWidget(self._build_step_three())
        steps_layout.addStretch(1)

        self.steps_scroll = QScrollArea()
        self.steps_scroll.setWidgetResizable(True)
        self.steps_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # AsNeeded, not AlwaysOff. Off is what made the coordinate-row overflow
        # invisible: content wider than the viewport was silently CLIPPED, so a
        # field simply lost its right-hand end with nothing to indicate why.
        # The margins above keep the bar from appearing at normal font sizes;
        # this is the honest fallback for when a larger font does overflow.
        self.steps_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.steps_scroll.setWidget(steps)
        layout.addWidget(self.steps_scroll, 1)

        layout.addWidget(self._build_summary())

        self._register_themed(panel, self._panel_style)
        self._register_themed(self.steps_scroll, self._scroll_style)
        return panel

    def _build_step_one(self):
        step, body = self._step_frame(1, "Subject & moment", "Fire")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Person name")
        self._style_input(self.name_input)
        body.addWidget(self._field_row("Name", self.name_input))

        self.gender_group = QButtonGroup(self)
        # Not exclusive-at-birth: NEITHER is checked until someone says so, and
        # collect_data reports '' for that state exactly like EditInfoSubTab.
        self.male_radio = QRadioButton("Male")
        self.female_radio = QRadioButton("Female")
        self.gender_group.addButton(self.male_radio, 0)
        self.gender_group.addButton(self.female_radio, 1)
        for radio in (self.male_radio, self.female_radio):
            self._register_themed(radio, self._radio_style)
        # Rodden rating (optional data-accuracy tag) rides the spare width of the
        # Gender row rather than taking a dedicated row. A stretch gutter sits
        # BETWEEN the radios and the Rodden chip so the two unrelated concepts
        # read apart; Gender still reads first and Rodden is clearly a passenger.
        self._build_rodden_control()
        gender_row = QWidget()
        gr = QHBoxLayout(gender_row)
        gr.setContentsMargins(0, 0, 0, 0)
        gr.setSpacing(ROW_SPACING)
        glabel = QLabel("GENDER")
        glabel.setFixedWidth(LABEL_COLUMN)
        glabel.setAlignment(Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter)
        self._register_themed(glabel, self._field_label_style)
        gr.addWidget(glabel)
        gr.addWidget(self.male_radio)
        gr.addWidget(self.female_radio)
        gr.addStretch(1)
        gr.addWidget(self.rodden_btn)
        gr.addSpacing(6)   # bind the help glyph to the chip, tighter than a row
        gr.addWidget(self.rodden_help_btn)
        body.addWidget(gender_row)
        # Tab order: Name -> Male -> Female -> Rodden chip -> ? (insertion order
        # into an HBox plus a QButtonGroup does not reliably produce it).
        self.setTabOrder(self.name_input, self.male_radio)
        self.setTabOrder(self.female_radio, self.rodden_btn)
        self.setTabOrder(self.rodden_btn, self.rodden_help_btn)

        self.date_month = self._num_field("MM", 34)
        self.date_day = self._num_field("DD", 34)
        self.date_year = self._num_field("YYYY", 52)
        date_combo = self._combo(
            [self.date_month, "/", self.date_day, "/", self.date_year],
            unit="m/d/y")
        body.addWidget(self._field_row("Birth date", date_combo,
                                       self._chip("Gregorian"), stretch=True))

        self.local_hour = self._num_field("HH", 34)
        self.local_minute = self._num_field("MM", 34)
        self.local_second = self._num_field("SS", 34)
        local_combo = self._combo(
            [self.local_hour, ":", self.local_minute, ":", self.local_second],
            unit="local")
        # The Local/UTC pair is ONE exclusive choice of which clock is the
        # user's input; the other side is what the controller derives. Putting
        # the two radios on their own rows says that better than a mode switch
        # somewhere else on the panel would.
        # NOT IN THE LAYOUT since 2026-08-12 (Lorris): the mockup has no
        # Local/UTC radio, and on rows already labelled "Local time" and "UTC
        # time" the words were the third repetition rather than a distinction.
        # Birth data is entered local; UTC is derived.
        #
        # The WIDGETS stay because deleting them would change DATA, not just
        # chrome. `time_mode` reads them, populate() sets them, and a chart
        # saved as UTC-authoritative would come back Local — the form would
        # quietly rewrite a fact about someone's chart because a control left
        # the screen. Off-screen they hold whatever the chart said and hand it
        # back unchanged, which is the same promise the war-time DST flag gets
        # one row below.
        self.time_mode_group = QButtonGroup(self)
        self.local_radio = QRadioButton("Local Time")
        self.utc_radio = QRadioButton("UTC Time")
        self.time_mode_group.addButton(self.local_radio, 0)
        self.time_mode_group.addButton(self.utc_radio, 1)
        self.local_radio.setChecked(True)
        for radio in (self.local_radio, self.utc_radio):
            radio.setToolTip("Which clock the user typed; the other is derived")
            self._register_themed(radio, self._radio_style)
        # WI-8: an INDICATOR, not a toggle. It says the fields speak 24-hour
        # time and nothing else — no signal, no setting, no parse or
        # collect_data involvement. A QLabel rather than a disabled QPushButton
        # on purpose: a label has no clicked signal to leave unconnected, so
        # "it changes no state" is structural rather than a flag someone can
        # flip later. 12h entry is a separate, deferred piece of work.
        self.clock_chip = self._locked_chip("24 h clock")
        self.clock_chip.setToolTip(
            "Times are entered in 24-hour format. 12-hour entry is planned.")
        body.addWidget(self._field_row("Local time", local_combo,
                                       self.clock_chip, stretch=True))
        return step

    # =========================================================================
    # RODDEN RATING (optional data-accuracy tag, rides the Gender row)
    # =========================================================================

    def _build_rodden_control(self):
        """Build the Rodden chip (QToolButton + checkable QMenu) and '?' help.

        Unrated is a first-class default: the menu's first entry is 'No rating',
        checked at startup, and ``_rodden_value`` reports ''. A loaded value the
        UI does not recognise is preserved verbatim (``_rodden_loaded_value``)
        rather than silently rewritten -- the war-time DST precedent one row up.
        """
        self._rodden_loaded_value = None   # unknown code kept across a round-trip
        self._rodden_rated = False         # drives the chip's quiet/forward ink

        self.rodden_btn = QToolButton()
        self.rodden_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.rodden_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.rodden_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rodden_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.rodden_btn.setAccessibleName("Rodden rating")

        self._rodden_menu = QMenu(self.rodden_btn)
        self._rodden_group = QActionGroup(self._rodden_menu)
        self._rodden_group.setExclusive(True)
        self._rodden_actions = {}

        none_act = QAction("No rating", self._rodden_menu)
        none_act.setCheckable(True)
        none_act.setChecked(True)
        none_act.setData("")
        self._rodden_group.addAction(none_act)
        self._rodden_menu.addAction(none_act)
        self._rodden_actions[""] = none_act
        self._rodden_menu.addSeparator()
        for code, meaning in _RODDEN_CODES:
            act = QAction(code, self._rodden_menu)
            act.setCheckable(True)
            act.setData(code)
            act.setToolTip(meaning)
            act.setStatusTip(meaning)
            self._rodden_group.addAction(act)
            self._rodden_menu.addAction(act)
            self._rodden_actions[code] = act
        self.rodden_btn.setMenu(self._rodden_menu)
        self._rodden_group.triggered.connect(self._on_rodden_chosen)
        self._register_themed(self.rodden_btn, self._rodden_chip_style)
        self._update_rodden_chip_text()

        # Icon-driven, not a text "?": the old 9.5px glyph on a 22px chip read as
        # an empty circle. The SVG is set (and recolored to the accent) inside
        # _rodden_help_style, which runs at build AND on every theme refresh.
        self.rodden_help_btn = QPushButton()
        self.rodden_help_btn.setFixedSize(22, 22)
        self.rodden_help_btn.setIconSize(QSize(22, 22))
        self.rodden_help_btn.setCheckable(True)
        self.rodden_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rodden_help_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.rodden_help_btn.setToolTip("What the Rodden codes mean")
        self.rodden_help_btn.setAccessibleName("Rodden rating help")
        self.rodden_help_btn.clicked.connect(self._toggle_rodden_help)
        self._register_themed(self.rodden_help_btn, self._rodden_help_style)
        self._rodden_help_dialog = None

    def _on_rodden_chosen(self, _action):
        self._rodden_loaded_value = None   # a deliberate pick clears any unknown
        self._update_rodden_chip_text()
        self._on_field_edited("rodden")

    def _rodden_value(self):
        """The chosen code, '' when unrated, or a preserved unknown value."""
        if self._rodden_loaded_value is not None:
            return self._rodden_loaded_value
        act = self._rodden_group.checkedAction()
        return act.data() if act is not None else ""

    def _set_rodden(self, value):
        """Populate from a loaded chart; keep an unrecognised value verbatim."""
        code = "" if value is None else str(value).strip()
        if code in self._rodden_actions:
            self._rodden_loaded_value = None
            self._rodden_actions[code].setChecked(True)
        else:
            # Outside our list: do not rewrite the chart. Keep it, show it, and
            # let an explicit pick replace it.
            self._rodden_loaded_value = code or None
            self._rodden_actions[""].setChecked(True)
        self._update_rodden_chip_text()

    def _update_rodden_chip_text(self):
        value = self._rodden_value()
        self._rodden_rated = bool(value)
        # Unrated shows a muted middot, never an em dash (human-facing text).
        glyph = value if value else "·"
        self.rodden_btn.setText("Rodden  %s  ▾" % glyph)
        self.rodden_btn.setStyleSheet(self._rodden_chip_style())

    def _toggle_rodden_help(self):
        if self._rodden_help_dialog is not None:
            self._rodden_help_dialog.close()
            return
        self._open_rodden_help()

    def _open_rodden_help(self):
        """Non-modal themed help dialog (mirrors the panel's other tutorials).

        Per-open widgets are registered for live theme replay and truncated back
        to the chrome baseline on close, so a later theme switch never styles a
        deleted C++ object (SPEC-THM-001 §11.6 H6 lifetime rule).
        """
        # Track the exact widgets this dialog registers so cleanup removes only
        # those, by identity -- truncating the registry by a saved length would
        # also drop anything ELSE registered while the popup is open (a live
        # theme replay of the form, say), silently killing its future replays.
        self.__dict__.setdefault("_themed_registry", [])
        dlg_widgets = []

        def _reg(widget, style_fn):
            self._register_themed(widget, style_fn)
            dlg_widgets.append(widget)
            return widget

        dlg = QDialog(self)
        dlg.setWindowTitle("Rodden rating")
        dlg.setModal(False)
        _reg(dlg, self._rodden_dialog_style)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        title = QLabel("Rodden rating")
        _reg(title, self._rodden_dialog_title_style)
        outer.addWidget(title)
        kicker = QLabel("A data-accuracy scale for the birth record, from most "
                        "to least reliable.")
        kicker.setWordWrap(True)
        _reg(kicker, self._muted_style)
        outer.addWidget(kicker)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(360)
        _reg(scroll, self._scroll_style)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        for r, (code, meaning) in enumerate(_RODDEN_CODES):
            code_lbl = QLabel(code)
            code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _reg(code_lbl, self._rodden_code_cell_style)
            mean_lbl = QLabel(meaning)
            mean_lbl.setWordWrap(True)
            mean_lbl.setAlignment(Qt.AlignmentFlag.AlignTop
                                  | Qt.AlignmentFlag.AlignLeft)
            _reg(mean_lbl, self._rodden_meaning_cell_style)
            grid.addWidget(code_lbl, r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(mean_lbl, r, 1)
        scroll.setWidget(host)
        outer.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _reg(close_btn, self._rodden_close_style)
        close_btn.clicked.connect(dlg.close)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)
        dlg.setMinimumWidth(420)

        def _cleanup(_result=None):
            # Remove ONLY this dialog's entries, by widget identity, so a widget
            # registered by something else while the popup was open keeps its
            # live-theme replay.
            drop = {id(w) for w in dlg_widgets}
            reg = self.__dict__.get("_themed_registry", [])
            reg[:] = [(w, fn) for (w, fn) in reg if id(w) not in drop]
            self.rodden_help_btn.setChecked(False)
            self.rodden_help_btn.setFocus()
            self._rodden_help_dialog = None
        dlg.finished.connect(_cleanup)

        self._rodden_help_dialog = dlg
        origin = self.rodden_help_btn.mapToGlobal(
            self.rodden_help_btn.rect().bottomLeft())
        dlg.move(origin.x() + 8, origin.y() + 8)
        dlg.show()
        self.rodden_help_btn.setChecked(True)

    # -- Rodden styles (each re-reads the palette per call; replay-safe) ------

    def _rodden_chip_style(self):
        theme = get_theme_colors()
        rated = getattr(self, "_rodden_rated", False)
        ink = theme["secondary_text"] if rated else _muted_ink()
        border = _hairline(0.24) if rated else _hairline(0.18)
        return ("QToolButton { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 7px;"
                " padding: 4px 8px; font-size: %s; font-weight: 600; }"
                "QToolButton:hover { border-color: %s; }"
                "QToolButton:focus { border-color: %s; }"
                "QToolButton::menu-indicator { image: none; width: 0px; }"
                % (ink, theme["secondary_dark"], border, LABEL_FONT,
                   _hairline(0.40), _accent_ink()))

    def _rodden_help_style(self):
        ink = _accent_ink()
        # The "?" is a QIcon, not stylesheet text, so its color never comes from
        # the QSS `color` below (icon pixels ignore it). Re-render the glyph in
        # the accent ink here so build-time and every theme refresh stay in sync.
        self._apply_rodden_help_icon(ink)
        return ("QPushButton { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 11px; }"
                "QPushButton:hover { background-color: %s; }"
                "QPushButton:checked { background-color: %s; }"
                % (ink, _rgba(ink, 0.10), _rgba(ink, 0.34),
                   _rgba(ink, 0.22), _rgba(ink, 0.30)))

    def _apply_rodden_help_icon(self, hex_color):
        """Render the "?" SVG in ``hex_color`` at the button's DPR and set it.

        QSvgRenderer has no CSS cascade, so ``currentColor`` must be replaced
        with a concrete hex first. The pixmap is built at device resolution and
        tagged with the DPR so Qt draws it crisp on HiDPI (Opus 5 integration
        note): a 22px icon painted at 1x would soften on a 2x screen.
        """
        renderer = QSvgRenderer(
            QByteArray(_RODDEN_HELP_SVG.replace("currentColor", hex_color)
                       .encode("utf-8")))
        dpr = self.rodden_help_btn.devicePixelRatioF() or 1.0
        pixmap = QPixmap(round(22 * dpr), round(22 * dpr))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(dpr)
        self.rodden_help_btn.setIcon(QIcon(pixmap))

    def _rodden_dialog_style(self):
        theme = get_theme_colors()
        # The scroll area, its viewport and the grid host must be transparent or
        # qt-material paints a light default surface behind the meaning column
        # (light text on light = unreadable). Standard transparent-scrollarea
        # idiom: the second-level QWidget under the QScrollArea is the host.
        return ("QDialog { background-color: %s; border: 1px solid %s; }"
                "QDialog QScrollArea { background: transparent; border: none; }"
                "QDialog QScrollArea > QWidget > QWidget {"
                " background: transparent; }"
                % (theme["secondary"], _hairline(0.20)))

    def _rodden_dialog_title_style(self):
        return ("QLabel { color: %s; font-size: 15px; font-weight: 800;"
                " background: transparent; }" % _accent_ink())

    def _rodden_code_cell_style(self):
        theme = get_theme_colors()
        return ("QLabel { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 7px;"
                " padding: 3px 8px; font-family: %s; font-weight: 700;"
                " font-size: %s; }"
                % (theme["secondary_text"], theme["secondary_dark"],
                   _hairline(0.24), MONO, LABEL_FONT))

    def _rodden_meaning_cell_style(self):
        return ("QLabel { color: %s; font-size: %s; background: transparent; }"
                % (get_theme_colors()["secondary_text"], LABEL_FONT))

    def _rodden_close_style(self):
        ink = _accent_ink()
        return ("QPushButton { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 8px;"
                " padding: 5px 16px; font-size: %s; font-weight: 700; }"
                "QPushButton:hover { background-color: %s; }"
                % (ink, _rgba(ink, 0.12), _rgba(ink, 0.34), LABEL_FONT,
                   _rgba(ink, 0.22)))

    def _build_step_two(self):
        step, body = self._step_frame(2, "Time zone", "Air")

        self.utc_hour = self._num_field("HH", 34)
        self.utc_minute = self._num_field("MM", 34)
        self.utc_second = self._num_field("SS", 34)
        utc_combo = self._combo(
            [self.utc_hour, ":", self.utc_minute, ":", self.utc_second],
            unit="utc")
        self.utc_day_offset = QLabel("")
        self.utc_day_offset.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._register_themed(self.utc_day_offset, self._accent_note_style)
        # LOCK: the whole time-zone section (UTC time, offset, IANA) fills
        # automatically from a map pick or a place search. It is LOCKED by
        # default so a non-expert does not hand-type a value the map would
        # compute for them; the button unlocks manual entry, and touching a
        # locked field explains how to fill it (tz_locked_field_touched).
        self.tz_lock_btn = QToolButton()
        self.tz_lock_btn.setCheckable(True)
        self.tz_lock_btn.setAutoRaise(True)
        self.tz_lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tz_lock_btn.toggled.connect(self._on_tz_lock_toggled)
        body.addWidget(self._field_row("UTC time", utc_combo,
                                       self.utc_day_offset, self.tz_lock_btn,
                                       stretch=True))

        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("±HH:MM")
        self._style_input(self.timezone_input, mono=True)
        self._measure_field(self.timezone_input, OFFSET_SAMPLE, chrome=30)
        self.timezone_iana_input = QLineEdit()
        self.timezone_iana_input.setPlaceholderText("e.g. Europe/Berlin")
        self._style_input(self.timezone_iana_input)
        # ONE row: offset, then the two DST switches. The offset and the DST
        # answer are the same question asked twice ("what was the clock doing
        # here?"), so they read better together than as two stacked rows.
        self.dst_applied_toggle = ToggleSwitch("DST applied")
        self.dst_applied_toggle.setToolTip(
            "Whether daylight saving was in force at this birth moment. It is "
            "filled from the time zone when you pick a place; flip it to answer "
            "yourself.")
        self.dst_applied_toggle.toggled.connect(self._on_dst_applied_toggled)

        # War time (flag 2) has no switch — two toggles cannot express three
        # values. A chart that ARRIVES with 2 keeps it: the flag is remembered
        # here and returned by collect_data() until the user touches a switch,
        # so loading and saving a war-time chart round-trips instead of
        # silently becoming 0. Only an explicit toggle overwrites it, which is
        # the one case where the user has actually said otherwise.
        self._dst_loaded_flag = None

        body.addWidget(self._field_row(
            "UTC offset", self.timezone_input, self.timezone_iana_input,
            self.dst_applied_toggle))

        # The fields the lock governs. An event filter turns a click on any of
        # them, while locked, into the "fill from the map/search" hint. Locked by
        # default (experts unlock).
        # The map lock governs the OFFSET and IANA fields only (a non-expert
        # fills those from a map pick or a place search). The UTC clock is NOT
        # in this group: in UTC-input mode it is the authoritative clock the
        # user types, so locking it behind the map lock forced an unlock to
        # enter the very field the mode selects. Its read-only state instead
        # follows the mode (_apply_utc_clock_editable).
        self._tz_locked_fields = (
            self.timezone_input, self.timezone_iana_input)
        for _f in self._tz_locked_fields:
            _f.installEventFilter(self)
        self._set_tz_locked(True)
        self._apply_utc_clock_editable()
        return step

    def _apply_utc_clock_editable(self):
        """UTC clock editability tracks the input mode.

        UTC-input mode: the clock IS the authoritative input, so it is editable
        without touching the map lock. Local mode: the clock is a live-derived
        display, so it is read-only (the controller writes it via setText, which
        read-only does not block). The local clock stays editable throughout;
        which clock collect_data reads is decided by time_mode.
        """
        editable = (self.time_mode == "UTC")
        for f in (self.utc_hour, self.utc_minute, self.utc_second):
            f.setReadOnly(not editable)

    # -- Time-zone lock -------------------------------------------------------

    def _on_tz_lock_toggled(self, unlocked):
        """The lock button. CHECKED = unlocked (manual entry allowed)."""
        self._set_tz_locked(not unlocked)

    def _set_tz_locked(self, locked):
        """Lock (read-only) or unlock the time-zone fields.

        Read-only, NOT disabled — the section keeps its normal look (Lorris:
        greying 'looks bad'); the lock glyph and the touch-hint carry the state.
        The values fill from a map pick or a place search, so a non-expert should
        not hand-type them; unlocking is the expert affordance.
        """
        self.tz_locked = locked
        for f in getattr(self, "_tz_locked_fields", ()):
            f.setReadOnly(locked)
        blocked = self.tz_lock_btn.blockSignals(True)
        self.tz_lock_btn.setChecked(not locked)
        self.tz_lock_btn.blockSignals(blocked)
        self.tz_lock_btn.setText("\U0001F512" if locked else "\U0001F513")
        self.tz_lock_btn.setToolTip(
            "Time-zone values fill automatically — click the map or search a "
            "place. Click to unlock manual entry (experts)." if locked
            else "Manual entry unlocked. Click to lock again.")

    def eventFilter(self, obj, event):
        """A click on a LOCKED time-zone field surfaces the "fill it from the
        map/search, or unlock" hint. The read-only field already blocks the
        edit; this adds the guidance so the lock does not feel like a dead field.
        """
        if (event.type() == QEvent.Type.MouseButtonPress
                and getattr(self, "tz_locked", False)
                and obj in getattr(self, "_tz_locked_fields", ())):
            self.tz_locked_field_touched.emit()
        return super().eventFilter(obj, event)

    # -- DST switches ---------------------------------------------------------

    def _on_dst_applied_toggled(self, _checked):
        """A hand on the DST switch means the user is answering (it overrides a
        value the zone filled in, and drops any remembered war-time flag)."""
        self._dst_loaded_flag = None
        self._on_field_edited("dst")

    def _sync_dst_derived(self):
        """No-op retained for callers. The DST switch is never "derived" now
        that the "Auto from zone" mode is gone; it always owns its value."""
        self.dst_applied_toggle.setDerived(False)

    def _dst_flag(self):
        """The integer flag ``collect_data()`` reports. Unchanged contract.

        Returns the remembered flag when a loaded chart carried a value this
        row cannot express (war time, 2) and nobody has touched a switch since
        — otherwise the switch answers, 1 or 0.
        """
        if self._dst_loaded_flag is not None:
            return self._dst_loaded_flag
        return 1 if self.dst_applied_toggle.isChecked() else 0

    def set_dst_resolved(self, applied):
        """Controller: show what the zone resolved to, without that reading as
        a user decision (the toggle stays silent on programmatic writes)."""
        self.dst_applied_toggle.setChecked(bool(applied))
        self._sync_dst_derived()

    def _build_step_three(self):
        step, body = self._step_frame(3, "Place of birth", "Earth")

        self.city_input = QLineEdit()
        self.city_input.setPlaceholderText("City")
        self._style_input(self.city_input)
        self.country_input = QLineEdit()
        self.country_input.setPlaceholderText("Country")
        self.country_input.setFixedWidth(150)
        self._style_input(self.country_input)
        body.addWidget(self._field_row("City", self.city_input,
                                       self.country_input))

        # DECORATIVE ONLY — region and elevation are shown because a resolved
        # place has them, but nothing collects them and nothing persists them.
        # They are not in collect_data() and must never be added to it.
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("State / region (not saved)")
        self._style_input(self.region_input)
        self.elevation_chip = self._chip("elev —")
        body.addWidget(self._field_row("Region", self.region_input,
                                       self.elevation_chip))

        self.latitude_input = QLineEdit()
        self.latitude_input.setPlaceholderText("00.0000")
        self._style_input(self.latitude_input, mono=True)
        self.longitude_input = QLineEdit()
        self.longitude_input.setPlaceholderText("00.0000")
        self._style_input(self.longitude_input, mono=True)
        # 22 px padding + 2 px border from _input_style, + 6 px caret room.
        for field in (self.latitude_input, self.longitude_input):
            self._measure_field(field, COORD_SAMPLE, chrome=30)
        # Display-only formatters. The SIGNED decimal in the field is the datum
        # — a hemisphere chip that could be edited would be a second, contrary
        # source for the same number.
        # Short by necessity, not by taste: widening the coordinate fields to
        # fit "-123.456789" (P0-2) pushed this row to 480 px inside a 490 px
        # viewport, and the steps area has no horizontal scrollbar — so the
        # overflow was CLIPPED at the panel edge rather than shown. Each chip
        # sits immediately right of its own field under a COORDINATES label, so
        # "lat"/"lon" were restating what position already says.
        self.lat_dir_chip = self._chip("° N")
        self.lon_dir_chip = self._chip("° E")
        body.addWidget(self._field_row(
            "Coordinates", self.latitude_input, self.lat_dir_chip,
            self.longitude_input, self.lon_dir_chip, stretch=True))

        self.location_note_label = QLabel("")
        self.location_note_label.setWordWrap(True)
        self.location_note_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._register_themed(self.location_note_label, self._muted_style)
        body.addWidget(self.location_note_label)
        return step

    def _build_summary(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 4, 16, 12)
        layout.setSpacing(0)

        self._summary_grid = QGridLayout()
        self._summary_grid.setContentsMargins(0, 0, 0, 0)
        self._summary_grid.setSpacing(8)
        layout.addLayout(self._summary_grid)

        self.summary_values = {}
        for key, caption, element in (("subject", "Subject", "Fire"),
                                      ("moment", "Moment", "Air"),
                                      ("local_utc", "Local → UTC", "Water"),
                                      ("place", "Place", "Earth")):
            card = QFrame()
            card.setObjectName("summaryCard")
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(3)

            caption_label = QLabel(caption)
            value_label = QLabel("—")
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(caption_label)
            card_layout.addWidget(value_label)

            self._register_themed(
                card, lambda e=element: self._summary_card_style(e))
            self._register_themed(caption_label, self._muted_style)
            self._register_themed(value_label, self._summary_value_style)

            self.summary_values[key] = value_label
            self._summary_cards.append(card)

        self._relayout_summary(4)
        return container

    # -- right panel: place picker --------------------------------------------

    def _build_place_panel(self):
        panel = QFrame()
        panel.setObjectName("placePanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setMinimumWidth(0)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head, self.place_tag = self._panel_head("Place picker", "Click to pin",
                                                element="Air")
        layout.addWidget(head)

        # The REAL map. No policy, no add-ons, no reaching into .map_widget —
        # what a click MEANS is the host's decision, and the host is the
        # controller (SPEC-MAP-004 §4.2/§4.3).
        self.map_tab = EditMapSubTab(self)

        # The map is held in a viewport, and this is load-bearing rather than
        # decorative. EditMapSubTab carries a hard 465 px minimum (its search
        # field asks for 250 on its own), and an explicit minimum propagates up
        # every layout it sits in: it made the WORKSPACE refuse to be narrower
        # than 939 px. A widget that refuses to shrink inside a host that is
        # already narrower does not reflow — it is CLIPPED, which is precisely
        # the map running off the right edge. A QScrollArea terminates that
        # propagation: the workspace can now be told any width, and the map
        # keeps its own size inside the viewport instead of overhanging the
        # window.
        #
        # The vertical bar is OFF by policy: with it enabled, a wheel event over
        # the map would scroll this viewport instead of reaching the map's own
        # zoom. Horizontal appears only when it is genuinely needed, and the
        # stacked layout below 937 px (see _orientation_for) means the normal
        # narrow case never needs it at all.
        self.map_viewport = QScrollArea()
        self.map_viewport.setWidgetResizable(True)
        self.map_viewport.setFrameShape(QFrame.Shape.NoFrame)
        self.map_viewport.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.map_viewport.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.map_viewport.setWidget(self.map_tab)
        layout.addWidget(self.map_viewport, 1)

        self._register_themed(panel, self._panel_style)
        self._register_themed(self.map_viewport, self._scroll_style)
        return panel

    # -- footer ---------------------------------------------------------------

    def _build_footer(self):
        footer = QWidget()
        footer.setObjectName("workspaceFooter")
        layout = QHBoxLayout(footer)
        self._footer_layout = layout
        layout.setContentsMargins(SIDE_GUTTER_MIN, 8, SIDE_GUTTER_MIN, 10)
        layout.setSpacing(10)

        self.element_bar = QWidget()
        bar_layout = QHBoxLayout(self.element_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(4)
        for element in ("Fire", "Earth", "Air", "Water"):
            swatch = QLabel()
            swatch.setFixedSize(8, 20)
            self._register_themed(
                swatch,
                lambda e=element: ("QLabel { background-color: %s;"
                                   " border-radius: 3px; }" % _element_hex(e)))
            bar_layout.addWidget(swatch)

        self.status_label = QLabel("")
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._register_themed(self.status_label, self._muted_style)

        self.copy_all_btn = QPushButton("⧉ Copy all")
        self.clear_btn = QPushButton("Clear form")
        # "Create && open" renders "Create & open" (a single "&" is eaten as a
        # mnemonic). New's one primary action: it creates, persists and opens the
        # chart in one click, mirroring Edit's "Save & open".
        self.create_btn = QPushButton("Create && open")
        self.save_btn = QPushButton("Save changes")
        # Save & open: save, then leave this screen and show the chart (Lorris:
        # "so we click it then open the chart directly instead of staying here").
        # "&&" renders a literal ampersand; a single "&" is eaten as a Qt
        # mnemonic and the following space is drawn underlined (reads as
        # "Save_open"). Same reason the "New && Edit" tab is escaped.
        self.save_open_btn = QPushButton("Save && open")
        self.cancel_btn = QPushButton("Cancel")
        for button in (self.copy_all_btn, self.clear_btn, self.cancel_btn,
                       self.save_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._register_themed(button, self._secondary_button_style)
        # Save & open is the prominent Edit action; plain Save is now secondary.
        for button in (self.create_btn, self.save_open_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._register_themed(button, self._primary_button_style)

        # WI-13: Big-3 placeholder. Deliberately in the footer's SPARE width
        # rather than as a fifth summary card — the summary grid flows at four
        # columns, so a fifth card would wrap onto a row of its own, and a new
        # chrome row is the one thing this layout is not allowed to grow.
        # Values need a chart object, so before Create there is nothing true to
        # say here; the em dashes are the same "no value yet" glyph the summary
        # cards use, not prose.
        self.big3_chip = self._locked_chip("Asc — · Sun — · Moon —")
        self.big3_chip.setToolTip("Computed after Create")

        layout.addWidget(self.element_bar)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.big3_chip)
        layout.addWidget(self.copy_all_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(self.cancel_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.save_open_btn)
        layout.addWidget(self.create_btn)

        self._register_themed(footer, self._footer_style)
        return footer

    # -- small builders --------------------------------------------------------

    def _panel_head(self, title, tag_text, element=None):
        head = QFrame()
        head.setObjectName("panelHead")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(head)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.setSpacing(10)

        title_label = QLabel(title.upper())
        tag = QLabel(tag_text)
        tag.setObjectName("panelTag")
        tag.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(tag)

        self._register_themed(head, self._panel_head_style)
        self._register_themed(title_label, self._panel_title_style)
        self._register_themed(tag, lambda e=element: self._tag_style(e))
        return head, tag

    def _step_frame(self, number, title, element):
        """A numbered, element-accented step. Returns (frame, body layout)."""
        frame = QFrame()
        frame.setObjectName("stepFrame")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 9, 0, 10)
        outer.setSpacing(10)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(9)

        badge = QLabel(str(number))
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(title.upper())
        head_layout.addWidget(badge)
        head_layout.addWidget(title_label)
        head_layout.addStretch(1)

        outer.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        outer.addLayout(body)

        self._register_themed(frame, lambda e=element: self._step_style(e))
        self._register_themed(badge, lambda e=element: self._badge_style(e))
        self._register_themed(title_label, self._step_title_style)
        return frame, body

    def _field_row(self, label_text, *widgets, stretch=False):
        """One ``label · controls`` row. ``stretch`` left-packs the controls."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ROW_SPACING)

        label = QLabel(label_text.upper())
        label.setFixedWidth(LABEL_COLUMN)
        label.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
        self._register_themed(label, self._field_label_style)
        layout.addWidget(label)

        for widget in widgets:
            layout.addWidget(widget)
        if stretch:
            layout.addStretch(1)
        return row

    def _num_field(self, placeholder, width):
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setFrame(False)
        self._register_themed(field, self._combo_field_style)
        # Inside a combo there is no border and no horizontal padding, so the
        # only chrome is the caret. The mockup width is a FLOOR, not the answer.
        self._measure_field(field, placeholder.replace("Y", "0")
                            .replace("M", "0").replace("D", "0")
                            .replace("H", "0").replace("S", "0"),
                            chrome=8, floor=width)
        return field

    def _measure_field(self, field, sample, chrome, floor=0):
        """Register ``field`` as sized by what it must SHOW, not by a constant.

        The 92 px coordinate boxes were the clipping bug: the widest real value
        ``set_coordinates`` can write is ``-123.456789``, which needs 86 px of
        glyphs plus 24 px of padding and border — 110 px, in a 92 px box, so the
        leading character was cut ("!1.276600" for "21.276600"). Worse, the
        inputs inherit qt-material's global 13 px rather than the 8-9 pt this
        panel's own styles pin, so the shortfall is not even constant across
        font settings. Measuring the actual font removes both failure modes.
        """
        self._measured_fields.append((field, sample, chrome, floor))
        self._apply_measured(field, sample, chrome, floor)

    @staticmethod
    def _apply_measured(field, sample, chrome, floor):
        """Pin the field to the width its widest real value needs.

        Fixed, not a growable minimum. Letting these fields expand was tried and
        reverted: the layout hands spare width to whatever will take it, so the
        two-digit date and time boxes doubled (34 -> 73 px) and the ±HH:MM
        offset went to 164 px. These hold fixed-format values whose longest
        form is known exactly, so growth buys nothing and costs the layout.

        What makes a fixed width safe here is that it is MEASURED and re-taken
        on every font change (_refit_fields), and that the steps viewport now
        shows a scrollbar instead of clipping — so if a font ever outgrows the
        row, it is visible rather than a silently truncated value.
        """
        metrics = QFontMetrics(field.font())
        width = max(floor, metrics.horizontalAdvance(sample) + chrome)
        field.setFixedWidth(width)

    def _refit_fields(self):
        """Re-measure every registered field. Cheap, and correctness depends on
        it running after ANY font change — a width measured under the old font
        is exactly the stale-constant bug this replaces."""
        for field, sample, chrome, floor in self._measured_fields:
            try:
                self._apply_measured(field, sample, chrome, floor)
            except Exception:
                traceback.print_exc()

    def _combo(self, parts, unit=""):
        """The mockup's ``.combo``: joined sub-fields with a unit caption."""
        frame = QFrame()
        frame.setObjectName("comboFrame")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(1)

        for part in parts:
            if isinstance(part, str):
                separator = QLabel(part)
                self._register_themed(separator, self._muted_style)
                layout.addWidget(separator)
            else:
                layout.addWidget(part)

        if unit:
            layout.addStretch(1)
            unit_label = QLabel(unit)
            self._register_themed(unit_label, self._unit_style)
            layout.addWidget(unit_label)

        # A FLOOR, not a cap: the mockup's 200 px, but the frame grows if its
        # measured sub-fields need more. A hard 200 here would re-create the
        # coordinate clipping one level up as soon as the font grew.
        frame.setMinimumWidth(200)
        frame.setSizePolicy(QSizePolicy.Policy.Maximum,
                            QSizePolicy.Policy.Fixed)
        self._register_themed(frame, self._combo_frame_style)
        return frame

    def _build_toast(self):
        """A fade-out confirmation, floating over the workspace.

        A copy that puts nine lines on the clipboard and says nothing looks
        exactly like a copy that failed, which is what "Copy all copies one row"
        felt like. The toast is a child of the workspace, not a dialog: it must
        not take focus away from the form it is reporting on.
        """
        self._toast = QLabel("", self)
        self._toast.setObjectName("copyToast")
        self._toast.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._toast.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast.hide()
        self._register_themed(self._toast, self._toast_style)

        effect = QGraphicsOpacityEffect(self._toast)
        self._toast.setGraphicsEffect(effect)
        # Rule 18: Qt owns the effect once setGraphicsEffect has taken it, and a
        # surviving Python reference to a C++-deleted object is a segfault.
        # Reach it back through graphicsEffect() instead.
        del effect

        self._toast_fade = QPropertyAnimation(self._toast.graphicsEffect(),
                                              b"opacity", self)
        self._toast_fade.setDuration(420)
        self._toast_fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._toast_fade.finished.connect(self._toast.hide)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._fade_toast)

    def show_toast(self, text, hold_ms=1400):
        """Flash ``text`` over the workspace, then fade it."""
        try:
            self._toast_fade.stop()
            self._toast.setText(text)
            self._toast.adjustSize()
            self._toast.graphicsEffect().setOpacity(1.0)
            # show() FIRST: _place_toast() returns early while the toast is
            # hidden, so positioning before showing left the very first copy
            # confirmation parked at (0, 0).
            self._toast.show()
            self._place_toast()
            self._toast.raise_()
            self._toast_timer.start(hold_ms)
        except Exception:
            traceback.print_exc()

    def _fade_toast(self):
        self._toast_fade.setStartValue(1.0)
        self._toast_fade.setEndValue(0.0)
        self._toast_fade.start()

    def _place_toast(self):
        toast = getattr(self, "_toast", None)
        if toast is None or not toast.isVisible():
            return
        toast.move(max(0, (self.width() - toast.width()) // 2),
                   max(0, self.height() - toast.height() - 58))

    def _chip(self, text):
        chip = QLabel(text)
        chip.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._register_themed(chip, self._chip_style)
        return chip

    def _locked_chip(self, text):
        """A chip that states a fact rather than offering a choice.

        Same shape as :meth:`_chip` but in muted ink, so it reads as a label
        and not as a control someone tried to click. Not selectable either —
        a text cursor over it is the one interaction that would suggest
        otherwise.
        """
        chip = QLabel(text)
        self._register_themed(chip, self._locked_chip_style)
        return chip

    def _style_input(self, widget, mono=False):
        self._register_themed(widget,
                              lambda m=mono: self._input_style(mono=m))

    # =========================================================================
    # STYLES — every one re-reads the palette per call, so replay works
    #          (SPEC-THM-001: never a pre-rendered string).
    # =========================================================================

    def _panel_style(self):
        theme = get_theme_colors()
        return ("QFrame#identityPanel, QFrame#placePanel {"
                " background-color: %s; border: 1px solid %s;"
                " border-radius: 16px; }"
                % (theme["secondary"], _hairline(0.20)))

    def _panel_head_style(self):
        return ("QFrame#panelHead { background: transparent;"
                " border: none; border-bottom: 1px solid %s; }"
                % _hairline(0.16))

    def _panel_title_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 700;"
                " background: transparent; }"
                % (get_theme_colors()["secondary_text"], TITLE_FONT))

    def _tag_style(self, element=None):
        ink = _element_ink(element, tint=TAG_TINT) if element else _accent_ink()
        return ("QLabel { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 6px;"
                " padding: 3px 8px; font-size: %s; font-weight: 700; }"
                % (ink, _rgba(ink, TAG_TINT), _rgba(ink, 0.34), TAG_FONT))

    def _segment_frame_style(self):
        theme = get_theme_colors()
        return ("QFrame#modeSegment { background-color: %s;"
                " border: 1px solid %s; border-radius: 16px; }"
                % (theme["secondary_dark"], _hairline(0.20)))

    def _segment_button_style(self):
        theme = get_theme_colors()
        return ("QPushButton { border: none; border-radius: 13px;"
                " padding: 7px 15px; font-size: %s; font-weight: 600;"
                " color: %s; background: transparent; }"
                "QPushButton:hover { background-color: %s; color: %s; }"
                "QPushButton:checked { background-color: %s; color: %s; }"
                % (BUTTON_FONT, _muted_ink(), _hairline(0.14),
                   theme["secondary_text"], theme["primary"],
                   PRIMARY_BUTTON_INK))

    def _step_style(self, element):
        return ("QFrame#stepFrame { background: transparent;"
                " border: none; border-left: 3px solid %s;"
                " border-bottom: 1px solid %s; }"
                % (_rgba(_element_hex(element), 0.55), _hairline(0.14)))

    def _badge_style(self, element):
        fill = _element_hex(element)
        return ("QLabel { background-color: %s; color: %s;"
                " border-radius: 7px; font-size: %s; font-weight: 700;"
                " font-family: %s; }"
                % (fill, _ink_on(fill), TAG_FONT, MONO))

    def _step_title_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 700;"
                " background: transparent; }"
                % (get_theme_colors()["secondary_text"], TITLE_FONT))

    def _field_label_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 700;"
                " background: transparent; }" % (_muted_ink(), LABEL_FONT))

    def _input_style(self, mono=False):
        theme = get_theme_colors()
        return ("QLineEdit { background-color: %s; color: %s;"
                " border: 1px solid %s; border-radius: %dpx;"
                " padding: 0px 11px; min-height: %dpx;"
                " font-size: %s; font-weight: 500;%s }"
                "QLineEdit:hover { border-color: %s; }"
                # A focus FILL must not be the panel colour: at secondary the
                # field dissolved into the panel on light and sank below its
                # siblings on dark. A translucent accent reads as focus on both.
                "QLineEdit:focus { border-color: %s; background-color: %s; }"
                # LOCKED (tz fields, read-only) must look IDENTICAL to normal, not
                # greyed (Lorris: greying 'looks bad') — restate the base colours
                # so qt-material's read-only dimming cannot win by pseudo-state.
                "QLineEdit:read-only { background-color: %s; color: %s; }"
                % (theme["secondary_dark"], theme["secondary_text"],
                   _hairline(0.24), BUTTON_RADIUS,
                   FIELD_HEIGHT - BORDER_ADJUST,
                   BASE_FONT,
                   (" font-family: %s;" % MONO) if mono else "",
                   _hairline(0.4), theme["primary"],
                   _rgba(theme["primary"], 0.16),
                   theme["secondary_dark"], theme["secondary_text"]))

    def _combo_frame_style(self):
        theme = get_theme_colors()
        return ("QFrame#comboFrame { background-color: %s;"
                " border: 1px solid %s; border-radius: %dpx;"
                " min-height: %dpx; }"
                % (theme["secondary_dark"], _hairline(0.24), BUTTON_RADIUS,
                   FIELD_HEIGHT - BORDER_ADJUST))

    def _combo_field_style(self):
        theme = get_theme_colors()
        return ("QLineEdit { background: transparent; border: none;"
                " color: %s; font-family: %s; font-weight: 600;"
                " font-size: %s; padding: 0px; }"
                "QLineEdit:focus { background-color: %s; border-radius: 6px; }"
                # Locked (read-only) UTC clock keeps the same ink, never greyed.
                "QLineEdit:read-only { background: transparent; color: %s; }"
                % (theme["secondary_text"], MONO, BASE_FONT,
                   _rgba(theme["primary"], 0.16), theme["secondary_text"]))

    def _unit_style(self):
        # The mockup divides the unit from the numbers with a rule and runs it
        # full height; without that it reads as another value in the field.
        return ("QLabel { color: %s; font-size: %s; font-weight: 700;"
                " background: transparent; padding: 0px 9px;"
                " border-left: 1px solid %s; }"
                % (_muted_ink(), UNIT_FONT, _hairline(0.18)))

    def _chip_style(self):
        theme = get_theme_colors()
        return ("QLabel { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 7px;"
                " padding: 4px 8px; font-size: %s; font-weight: 600; }"
                % (theme["secondary_text"], theme["secondary_dark"],
                   _hairline(0.24), LABEL_FONT))

    def _locked_chip_style(self):
        """Muted ink on the same ground as :meth:`_chip_style`.

        The difference from a live chip is ink weight only — the border and
        fill stay, so the row keeps its rhythm and the chip does not read as a
        broken control. ``_muted_ink`` self-tunes to hold 4.5:1 against the
        surface, so "muted" never becomes "unreadable" on either theme.
        """
        theme = get_theme_colors()
        # UNIT_FONT, not LABEL_FONT: this states a fact about the fields next to
        # it, so it should sit at the same weight as the "local" unit marker
        # rather than compete with the controls. It also has to earn its place —
        # at label size the Local time row's minimum went 6 px past the steps
        # viewport, and that column has no horizontal scrollbar, so over-wide
        # means CLIPPED rather than scrollable.
        return ("QLabel { color: %s; background-color: %s;"
                " border: 1px solid %s; border-radius: 7px;"
                " padding: 3px 7px; font-size: %s; font-weight: 600; }"
                % (_muted_ink(), theme["secondary_dark"],
                   _hairline(0.18), UNIT_FONT))

    def _radio_style(self):
        return ("QRadioButton, QCheckBox { color: %s; spacing: 7px;"
                " background: transparent; font-size: %s; }"
                "QRadioButton::indicator, QCheckBox::indicator {"
                " width: 15px; height: 15px; }"
                % (get_theme_colors()["secondary_text"], BASE_FONT))

    def _muted_style(self):
        return ("QLabel { color: %s; font-size: %s;"
                " background: transparent; }" % (_muted_ink(), LABEL_FONT))

    def _accent_note_style(self):
        return ("QLabel { color: %s; font-weight: 700; font-size: %s;"
                " background: transparent; }" % (_accent_ink(), LABEL_FONT))

    def _summary_card_style(self, element):
        theme = get_theme_colors()
        return ("QFrame#summaryCard { background-color: %s;"
                " border: 1px solid %s; border-left: 3px solid %s;"
                " border-radius: 12px; }"
                % (theme["secondary_dark"], _hairline(0.20),
                   _element_hex(element)))

    def _summary_value_style(self):
        return ("QLabel { color: %s; font-family: %s; font-size: %s;"
                " font-weight: 600; background: transparent; }"
                % (get_theme_colors()["secondary_text"], MONO, CHIP_VALUE_FONT))

    def _scroll_style(self):
        return "QScrollArea { border: none; background: transparent; }"

    def _footer_style(self):
        return ("QWidget#workspaceFooter { background: transparent;"
                " border-top: 1px solid %s; }" % _hairline(0.16))

    def _primary_button_style(self):
        theme = get_theme_colors()
        # The mockup's primary is a vertical blue-light -> blue gradient, not a
        # flat fill. Qt has qlineargradient, so this is the one part of
        # `.btn.primary` that ports directly; its box-shadow has no QSS
        # equivalent and is dropped rather than faked with a border.
        return ("QPushButton { border: none; border-radius: %dpx;"
                " padding: 0px %dpx; min-height: %dpx; max-height: %dpx;"
                " font-size: %s; font-weight: %d; color: %s;"
                " background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                " stop:0 %s, stop:1 %s); }"
                "QPushButton:hover { background: qlineargradient("
                "x1:0, y1:0, x2:0, y2:1, stop:0 %s, stop:1 %s); }"
                "QPushButton:disabled { background: %s; color: %s; }"
                % (BUTTON_RADIUS, BUTTON_PAD_X, BUTTON_HEIGHT, BUTTON_HEIGHT,
                   BUTTON_FONT, BUTTON_WEIGHT, PRIMARY_BUTTON_INK,
                   theme["primary_light"], theme["primary"],
                   _lighten(theme["primary_light"]), theme["primary"],
                   theme["secondary_dark"], _muted_ink()))

    def _secondary_button_style(self):
        theme = get_theme_colors()
        return ("QPushButton { background-color: %s; color: %s;"
                " border: 1px solid %s; border-radius: %dpx;"
                " padding: 0px %dpx; min-height: %dpx; max-height: %dpx;"
                " font-size: %s; font-weight: %d; }"
                "QPushButton:hover { background-color: %s; border-color: %s; }"
                % (theme["secondary_dark"], theme["secondary_text"],
                   _hairline(0.24), BUTTON_RADIUS, BUTTON_PAD_X,
                   BUTTON_HEIGHT - BORDER_ADJUST,
                   BUTTON_HEIGHT - BORDER_ADJUST, BUTTON_FONT, BUTTON_WEIGHT,
                   _rgba(theme["primary"], 0.16), _rgba(theme["primary"], 0.5)))

    def _toast_style(self):
        theme = get_theme_colors()
        # `.toast` in the mockup is a CARD with a 3px success-coloured left
        # edge, not a solid accent pill — it confirms without shouting.
        return ("QLabel#copyToast { background-color: %s; color: %s;"
                " border: 1px solid %s; border-left: 3px solid %s;"
                " border-radius: 12px; padding: 11px 18px;"
                " font-size: %s; font-weight: 600; }"
                % (theme["secondary"], theme["secondary_text"],
                   _hairline(0.28), desat_hex(OK_HEX), BUTTON_FONT))

    def refresh_theme(self):
        """Re-apply every registered style, and cascade to the two children."""
        self._replay_themed()
        # A theme switch can bring a different font with it, and a width
        # measured under the previous one clips exactly like the constant did.
        self._refit_fields()
        for child in (getattr(self, "token_bar", None),
                      getattr(self, "map_tab", None)):
            try:
                if child is not None and hasattr(child, "refresh_theme"):
                    child.refresh_theme()
            except Exception:
                traceback.print_exc()

    # =========================================================================
    # VALIDATORS AND BINDINGS
    # =========================================================================

    def _setup_validators(self):
        """Same ranges as EditInfoSubTab — one form, one set of limits."""
        self.date_month.setValidator(_BoundedIntValidator(1, 12))
        self.date_day.setValidator(_BoundedIntValidator(1, 31))
        self.date_year.setValidator(_BoundedIntValidator(1, 9999))
        for field in (self.local_hour, self.utc_hour):
            field.setValidator(_BoundedIntValidator(0, 23))
        for field in (self.local_minute, self.local_second,
                      self.utc_minute, self.utc_second):
            field.setValidator(_BoundedIntValidator(0, 59))
        self.latitude_input.setValidator(QDoubleValidator(-90, 90, 6))
        self.longitude_input.setValidator(QDoubleValidator(-180, 180, 6))

    def _setup_bindings(self):
        text_fields = (
            (self.name_input, "name"),
            (self.date_month, "date"), (self.date_day, "date"),
            (self.date_year, "date"),
            (self.local_hour, "local_time"), (self.local_minute, "local_time"),
            (self.local_second, "local_time"),
            (self.utc_hour, "utc_time"), (self.utc_minute, "utc_time"),
            (self.utc_second, "utc_time"),
            (self.timezone_input, "offset"),
            (self.timezone_iana_input, "timezone"),
            (self.city_input, "city"), (self.country_input, "country"),
            (self.latitude_input, "lat"), (self.longitude_input, "lon"),
        )
        for widget, name in text_fields:
            widget.textChanged.connect(
                lambda _t, n=name: self._on_field_edited(n))

        # The DST switches report their own edits from their handlers, which
        # also carry the auto/derived bookkeeping — wiring _on_field_edited a
        # second time here would double-count every switch.
        self.gender_group.buttonClicked.connect(
            lambda _b: self._on_field_edited("gender"))
        self.time_mode_group.buttonClicked.connect(self._on_time_mode_clicked)

        self.mode_group.buttonClicked.connect(self._on_mode_clicked)
        self.copy_all_btn.clicked.connect(self.copy_all)
        # Ctrl+Shift+C, NOT Ctrl+C: plain copy has to keep meaning "copy what I
        # selected" inside a field, or the form stops behaving like a form.
        self._copy_all_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+C"), self, self.copy_all)
        self._copy_all_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        self.create_btn.clicked.connect(self.create_requested.emit)
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.save_open_btn.clicked.connect(self.save_open_requested.emit)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)

    def _on_field_edited(self, name):
        """One user edit. Silent while a setter is writing (no echo loops)."""
        self._update_direction_chips()
        self._update_summary()
        if self._suppress:
            return
        self.field_edited.emit(name)

    def _on_time_mode_clicked(self, _button=None):
        self._apply_utc_clock_editable()
        self._update_summary()
        if not self._suppress:
            self.field_edited.emit("time_mode")

    def _on_mode_clicked(self, button):
        mode = "new" if button is self.new_mode_btn else "edit"
        if mode == self._mode:
            return
        self.set_mode(mode)
        self.mode_changed.emit(mode)

    # =========================================================================
    # DERIVED DISPLAY (formatting only — no astronomy, no time conversion)
    # =========================================================================

    def _update_direction_chips(self):
        self.lat_dir_chip.setText(
            "° S" if _to_float(self.latitude_input.text()) < 0 else "° N")
        self.lon_dir_chip.setText(
            "° W" if _to_float(self.longitude_input.text()) < 0 else "° E")

    def _update_summary(self):
        """Re-derive the four cards from the fields, honouring pins.

        Pure string assembly over what the fields already say. It never
        computes a UTC time: the Local → UTC card shows the two clocks the form
        holds, and the controller is what makes the second one true.
        """
        name = self.name_input.text().strip()
        year = self.date_year.text().strip()
        month = self.date_month.text().strip()
        day = self.date_day.text().strip()
        moment = ("%s-%s-%s" % (year, month.zfill(2), day.zfill(2))
                  if year and month and day else "—")
        local = self._clock_text(self.local_hour, self.local_minute)
        utc = self._clock_text(self.utc_hour, self.utc_minute)
        city = self.city_input.text().strip()

        self._set_summary_card("subject", name or "—")
        self._set_summary_card("moment", moment)
        self._set_summary_card("local_utc", "%s→%s" % (local, utc))
        self._set_summary_card("place", city or "—")

    @staticmethod
    def _clock_text(hour_field, minute_field):
        hour = hour_field.text().strip()
        minute = minute_field.text().strip()
        return "%s:%s" % (hour.zfill(2), minute.zfill(2)) if hour else "—"

    def _set_summary_card(self, key, text):
        if self._summary_pins.get(key):
            return
        label = self.summary_values.get(key)
        if label is not None:
            label.setText(text)

    def _relayout_summary(self, columns):
        if columns == self._summary_columns:
            return
        self._summary_columns = columns
        for card in self._summary_cards:
            self._summary_grid.removeWidget(card)
        for index, card in enumerate(self._summary_cards):
            self._summary_grid.addWidget(card, index // columns,
                                         index % columns)

    def _summary_columns_for(self, available):
        """4 across if they actually FIT, else 2 — measured, not guessed.

        A hard pixel threshold would be a guess about one font at one scale,
        and this app rescales its fonts (``scaled_area_px``). Asking the cards
        how wide they want to be re-decides correctly at any scale, which is
        the difference between cards that wrap and cards that clip.
        """
        widest = max([card.sizeHint().width()
                      for card in self._summary_cards] or [0])
        spacing = self._summary_grid.spacing()
        return 4 if available >= widest * 4 + spacing * 3 else 2

    def resizeEvent(self, event):
        """Wrap the summary cards, and stack the panels when side-by-side stops
        fitting."""
        super().resizeEvent(event)
        try:
            # 16 px of padding either side, from _build_summary's margins.
            available = self.identity_panel.width() - 32
            self._relayout_summary(self._summary_columns_for(available))
            self._apply_gutter()
            self._apply_orientation(self._orientation_for(self.width()))
            self._cap_identity_width()
            self._place_toast()
        except Exception:
            traceback.print_exc()

    def _chrome_width(self):
        """Everything horizontal that is NOT one of the two panels: both side
        gutters, the splitter handle, and the place panel's 1 px borders.

        Derived rather than baked in — the gutter is now responsive, so a
        constant 42 here would silently under-reserve by up to 56 px on a wide
        window and hand the map a scrollbar again.
        """
        return 2 * getattr(self, "_gutter", SIDE_GUTTER_MIN) + 12

    def _apply_gutter(self):
        """Widen the shared side gutter as the window grows.

        A fixed 16 px reads as "pinned to the edge" on a wide window — the map
        in particular ran right up to the frame. Scaling with the width gives
        the content real margins when there is room and gives them back when
        there is not, and driving all four bands from ONE value is what keeps
        their left and right edges identical at every size.
        """
        gutter = int(max(SIDE_GUTTER_MIN,
                         min(SIDE_GUTTER_MAX,
                             self.width() * SIDE_GUTTER_RATIO)))
        if gutter == getattr(self, "_gutter", None):
            return
        self._gutter = gutter
        for layout in (self._header_layout, self._wrap_layout,
                       self._footer_layout):
            margins = layout.contentsMargins()
            layout.setContentsMargins(gutter, margins.top(),
                                      gutter, margins.bottom())
        self.token_bar.set_side_gutter(gutter)

    def changeEvent(self, event):
        """Re-measure when the FONT changes, not only when the theme does.

        Lorris scales the UI font per area; a bump that does not go through a
        theme refresh would otherwise leave every measured width computed under
        the previous font, which is the coordinate clipping coming straight
        back. Qt delivers FontChange after the new font has propagated, so
        measuring here reads the font the fields will actually paint with.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._refit_fields()

    def _orientation_for(self, width):
        """Side by side while both panels FIT; stacked below that.

        The map cannot be squeezed indefinitely: ``EditMapSubTab`` carries a
        465 px floor (its search field alone asks for 250). With the identity
        panel's 430 px minimum plus 32 px of margins and the 10 px handle, two
        columns stop fitting at 937 px — and a QSplitter that cannot honour its
        children's minimums does not shrink them, it OVERFLOWS its container.
        That is the truncation: the map ran off the right edge rather than
        reflowing. Stacking is the reflow, and it keeps the map whole.

        The 40 px gap between the two thresholds is hysteresis. One threshold
        would flip orientation on every pixel of a drag that crossed it, and a
        re-laid-out map on every frame of a window drag is worse than either
        layout.
        """
        floor = IDENTITY_MIN_WIDTH + MAP_MIN_WIDTH + self._chrome_width()
        if self._orientation == Qt.Orientation.Horizontal:
            return (Qt.Orientation.Vertical if width < floor
                    else Qt.Orientation.Horizontal)
        return (Qt.Orientation.Horizontal if width > floor + 40
                else Qt.Orientation.Vertical)

    def _apply_orientation(self, orientation):
        if orientation == self._orientation:
            return
        self._orientation = orientation
        self.splitter.setOrientation(orientation)
        if orientation == Qt.Orientation.Vertical:
            self.splitter.setCollapsible(0, False)
            # Drop the cached cap. Vertical clears the maximum outright, so a
            # round trip back to the SAME horizontal width would hit the
            # "cap unchanged" early return and never restore it — the form grew
            # to 500 px and squeezed the map back under its minimum.
            self._identity_cap = None
            # Stacked, split by SHARE rather than by pixels: the map is the half
            # that becomes unusable when starved, and a fixed 340 px second pane
            # left it 105 px tall on a 768 px screen.
            height = max(self.splitter.height(), 360)
            self.splitter.setSizes([int(height * 0.55), int(height * 0.45)])
        else:
            self.splitter.setSizes(
                [IDENTITY_MAX_WIDTH,
                 max(MAP_MIN_WIDTH,
                     self.width() - IDENTITY_MAX_WIDTH
                     - self._chrome_width())])

    def _cap_identity_width(self):
        """Let the form give width back before the map goes under its minimum.

        This is the mockup's ``minmax(430px, 500px)`` read the way it is meant:
        the form's 500 px is a PREFERENCE, and it yields down to 430 rather than
        pushing the map below the 465 px it needs. Without the cap there is a
        band (roughly 940-1010 px) where the form sat at its full 500 px and the
        map got a scrollbar instead — no longer truncation, but still the map
        paying for the form's comfort.
        """
        if self._orientation == Qt.Orientation.Vertical:
            # Stacked, the form spans the full width; a cap would leave it
            # marooned beside empty space.
            self.identity_panel.setMaximumWidth(MAX_WIDGET_WIDTH)
            return
        room = self.width() - self._chrome_width() - MAP_MIN_WIDTH
        cap = max(IDENTITY_MIN_WIDTH, min(IDENTITY_MAX_WIDTH, room))
        if cap == getattr(self, "_identity_cap", None):
            return
        self._identity_cap = cap
        self.identity_panel.setMaximumWidth(cap)
        # A cap alone does not move the handle: QSplitter keeps the PROPORTIONS
        # it was last given across a resize, so the form kept its old share and
        # the map stayed under its minimum anyway. Re-place the handle whenever
        # the cap actually changes — which is rare, and never mid-drag, because
        # a drag cannot cross a cap that has not moved.
        self.splitter.setSizes([cap, max(MAP_MIN_WIDTH + 2,
                                         self.width() - self._chrome_width()
                                         - cap)])

    # =========================================================================
    # PUBLIC API — the controller drives these
    # =========================================================================

    @property
    def time_mode(self):
        """'Local' or 'UTC' — which clock the user typed."""
        return "UTC" if self.utc_radio.isChecked() else "Local"

    def collect_data(self) -> dict:
        """Gather the form into the pinned birth-data dict.

        Byte-for-byte the ``EditInfoSubTab.collect_data`` contract, including
        the rule that ``hour``/``minute``/``second`` come from whichever clock
        is authoritative, and the ``{}``-on-ValueError behaviour that callers
        already treat as "the form is not usable yet".

        Region and elevation are NOT here, by design — see the class docstring.
        """
        try:
            male_checked = self.male_radio.isChecked()
            female_checked = self.female_radio.isChecked()
            gender = ('Male' if male_checked
                      else 'Female' if female_checked else '')

            if self.time_mode == "UTC":
                hour = int(self.utc_hour.text() or 0)
                minute = int(self.utc_minute.text() or 0)
                second = int(self.utc_second.text() or 0)
            else:
                hour = int(self.local_hour.text() or 0)
                minute = int(self.local_minute.text() or 0)
                second = int(self.local_second.text() or 0)

            return {
                'name': self.name_input.text().strip(),
                'year': int(self.date_year.text() or 0),
                'month': int(self.date_month.text() or 0),
                'day': int(self.date_day.text() or 0),
                'hour': hour,
                'minute': minute,
                'second': second,
                'gender': gender,
                'country': self.country_input.text().strip(),
                'city': self.city_input.text().strip(),
                'latitude': float(self.latitude_input.text() or 0),
                'longitude': float(self.longitude_input.text() or 0),
                'iana_timezone': self.timezone_iana_input.text().strip(),
                'timezone': self.timezone_input.text().strip() or '+00:00',
                'dst': self._dst_flag(),
                'time_mode': self.time_mode,
                # '' when unrated (omitted from TOML by the writer), the chosen
                # code, or a preserved unknown value.
                'rodden': self._rodden_value(),
            }
        except ValueError as exc:
            print(f"Error collecting form data: {exc}")
            return {}

    def populate(self, data: dict):
        """Fill the form from a ``collect_data``-shaped dict.

        Symmetric with ``collect_data``: ``populate(collect_data())`` leaves the
        form saying the same thing. Two rules make that true rather than nearly
        true:

        * ``hour``/``minute``/``second`` land on the clock named by
          ``time_mode``. Explicit ``local_hour``…/``utc_hour``… keys, when the
          caller has BOTH clocks, win over that and fill each side directly.
        * With only one clock supplied, the OTHER side is CLEARED rather than
          left standing. A stale derived time that no longer matches the input
          is the one thing a form like this must never show; the controller
          fills it back in with ``set_derived_utc``.

        ``dst`` expects a concrete 0/1/2 flag. The CHTK ``-1`` AUTO sentinel is
        resolved to a concrete flag by the load path before it reaches here (the
        "Auto from zone" mode was removed); a stray ``-1`` is coerced to 0 below.
        """
        data = data or {}
        self._suppress = True
        try:
            self.name_input.setText(str(data.get('name', '') or ''))
            self._set_gender(data.get('gender', ''))
            self._set_rodden(data.get('rodden'))

            self._set_text(self.date_year, data.get('year'), 4)
            self._set_text(self.date_month, data.get('month'), 2)
            self._set_text(self.date_day, data.get('day'), 2)

            mode = str(data.get('time_mode') or 'Local')
            (self.utc_radio if mode.upper() == 'UTC'
             else self.local_radio).setChecked(True)
            self._apply_utc_clock_editable()   # loaded mode governs the clock

            has_local = 'local_hour' in data
            has_utc = 'utc_hour' in data
            if has_local:
                self._set_clock(self.local_hour, self.local_minute,
                                self.local_second, data.get('local_hour'),
                                data.get('local_minute'),
                                data.get('local_second'))
            if has_utc:
                self._set_clock(self.utc_hour, self.utc_minute,
                                self.utc_second, data.get('utc_hour'),
                                data.get('utc_minute'), data.get('utc_second'))
            if mode.upper() == 'UTC':
                if not has_utc:
                    self._set_clock(self.utc_hour, self.utc_minute,
                                    self.utc_second, data.get('hour'),
                                    data.get('minute'), data.get('second'))
                if not has_local:
                    self._set_clock(self.local_hour, self.local_minute,
                                    self.local_second, None, None, None)
            else:
                if not has_local:
                    self._set_clock(self.local_hour, self.local_minute,
                                    self.local_second, data.get('hour'),
                                    data.get('minute'), data.get('second'))
                if not has_utc:
                    self._set_clock(self.utc_hour, self.utc_minute,
                                    self.utc_second, None, None, None)

            self.timezone_input.setText(str(data.get('timezone', '') or ''))
            self._set_iana_field(str(data.get('iana_timezone', '') or ''))

            dst = data.get('dst', 0)
            try:
                dst = int(dst)
            except (TypeError, ValueError):
                dst = 0
            # The load path resolves the CHTK -1 AUTO sentinel to a concrete
            # 0/1/2 before populate (resolve_recipe_dst_flag), so -1 should not
            # arrive here. Coerce defensively if a legacy metadata path still
            # carries it: -1 is no longer expressible now that "Auto from zone"
            # is gone, and it must never be persisted.
            if dst == -1:
                dst = 0
            # 2 (war time) has no switch: show it as "applied", which is true,
            # and remember the exact flag so saving an untouched chart returns
            # the 2 it arrived with rather than a 1.
            self.dst_applied_toggle.setChecked(dst in (1, 2))
            self._dst_loaded_flag = dst if dst == 2 else None
            self._sync_dst_derived()

            self.city_input.setText(str(data.get('city', '') or ''))
            self.country_input.setText(str(data.get('country', '') or ''))
            latitude = data.get('latitude')
            longitude = data.get('longitude')
            self.latitude_input.setText(
                "" if latitude is None else "%.6f" % _to_float(latitude))
            self.longitude_input.setText(
                "" if longitude is None else "%.6f" % _to_float(longitude))
        except Exception:
            traceback.print_exc()
        finally:
            self._suppress = False
        self._update_direction_chips()
        self._update_summary()

    def set_coordinates(self, lat: float, lon: float):
        """Coordinates from an external source (the map). Six decimals, signed."""
        self._suppress = True
        try:
            self.latitude_input.setText("%.6f" % _to_float(lat))
            self.longitude_input.setText("%.6f" % _to_float(lon))
        finally:
            self._suppress = False
        self._update_direction_chips()
        self._update_summary()

    def set_city(self, city: str):
        self._suppress = True
        try:
            self.city_input.setText(city or "")
        finally:
            self._suppress = False
        self._update_summary()

    def set_country(self, country: str):
        self._suppress = True
        try:
            self.country_input.setText(country or "")
        finally:
            self._suppress = False
        self._update_summary()

    def _set_iana_field(self, name):
        """Fill the IANA zone field START-first with the full name on hover.

        The field is narrow (it shares the offset row with two DST switches), and
        after a plain setText the cursor sits at the END, so the widget scrolls
        right and shows only the tail — "Europe/Paris" reads as "e/Paris",
        "America/Chicago" as "hicago". Homing the cursor shows the recognisable
        start instead, and the tooltip carries the whole name."""
        name = name or ""
        self.timezone_iana_input.setText(name)
        self.timezone_iana_input.setCursorPosition(0)
        self.timezone_iana_input.setToolTip(name)

    def set_timezone(self, timezone: str):
        """Route an IANA name or a raw offset to the right field.

        Split on '/' exactly like ``EditInfoSubTab.set_timezone``. What this one
        does NOT do is resolve the name to an offset or set DST from it — that
        is a calculation over a birth instant, and a view that did it would be
        computing chart data (SPEC-UTC-001 keeps that in one place). The
        controller resolves, then calls back with the offset.
        """
        timezone = timezone or ""
        self._suppress = True
        try:
            if '/' in timezone:
                self._set_iana_field(timezone)
            else:
                self._set_iana_field("")
                self.timezone_input.setText(timezone)
        finally:
            self._suppress = False
        self._update_summary()

    def set_timezone_resolved(self, iana_name: str, offset: str, dst_flag=None):
        """Show a controller-RESOLVED timezone: BOTH the IANA name and its
        +HH:MM offset, plus (optionally) the DST radio it resolved to.

        The view still does no arithmetic — it only displays the offset and flag
        the controller computed from the birth instant (SPEC-UTC-001 keeps the
        resolution in one place). This exists because a resolved place must fill
        the offset field (Local-mode Save/Create refuses an empty one), which the
        one-field ``set_timezone`` cannot do without clobbering the IANA name.
        ``dst_flag`` of 1 ticks Yes, 0/None ticks No; War time (2) is never
        auto-resolved and is left to the user.
        """
        self._suppress = True
        try:
            self._set_iana_field(iana_name or "")
            self.timezone_input.setText(offset or "")
            if dst_flag in (0, 1):
                self.dst_applied_toggle.setChecked(dst_flag == 1)
                self._dst_loaded_flag = None
                self._sync_dst_derived()
        finally:
            self._suppress = False
        self._update_summary()

    def set_location_note(self, note: str):
        """SPEC-MAP-004 §4.4 routing note. Empty clears it, so a stale warning
        cannot outlive the pick that caused it."""
        self.location_note_label.setText(note or "")
        self.location_note_label.setVisible(bool(note))

    def set_mode(self, mode: str):
        """'new' or 'edit'. Programmatic: does NOT emit ``mode_changed``."""
        mode = "edit" if str(mode).lower() == "edit" else "new"
        self._mode = mode
        is_new = mode == "new"

        self.new_mode_btn.setChecked(is_new)
        self.edit_mode_btn.setChecked(not is_new)
        tag = "New" if is_new else "Editing"
        self.mode_tag.setText(tag)
        self.identity_tag.setText(tag)

        self.create_btn.setVisible(is_new)
        self.save_btn.setVisible(not is_new)
        self.save_open_btn.setVisible(not is_new)
        self.cancel_btn.setVisible(not is_new)

    def mode(self) -> str:
        return self._mode

    def set_derived_utc(self, hour, minute, second=0):
        """Show the UTC clock the controller computed. Silent, and selectable.

        Pass ``None`` for hour to blank it — "not derived yet" has to be
        expressible, or the field lies during the gap between an edit and its
        recomputation.
        """
        self._suppress = True
        try:
            self._set_clock(self.utc_hour, self.utc_minute, self.utc_second,
                            hour, minute, second)
        finally:
            self._suppress = False
        self._update_summary()

    def set_day_offset(self, text: str):
        """The '(-1d)' / '(+1d)' marker beside the UTC clock. '' clears it."""
        self.utc_day_offset.setText(text or "")

    def set_summary(self, subject=None, moment=None, local_utc=None,
                    place=None):
        """Override summary cards with controller-computed text.

        A non-empty value PINS that card (the auto-derived text stops touching
        it); an empty string un-pins it and hands it back. That is what lets the
        controller show a real converted UTC in the Local → UTC card without the
        next keystroke overwriting it.
        """
        for key, value in (("subject", subject), ("moment", moment),
                           ("local_utc", local_utc), ("place", place)):
            if value is None:
                continue
            label = self.summary_values.get(key)
            if label is None:
                continue
            if value == "":
                self._summary_pins[key] = False
            else:
                self._summary_pins[key] = True
                label.setText(str(value))
        self._update_summary()

    def set_status(self, text: str):
        """Footer status/log line."""
        self.status_label.setText(text or "")

    def record_text(self) -> str:
        """The WHOLE record as text — every field a user would want to paste.

        Built from the widgets rather than from ``collect_data()`` on purpose:
        this must be able to report a half-filled form (``collect_data``
        returns ``{}`` on the first unparseable value) and must show both
        clocks, the IANA name and the hemispheres, none of which survive the
        collect contract. Formatting only — nothing here converts anything.
        """
        def field(widget):
            return widget.text().strip()

        gender = ("Male" if self.male_radio.isChecked()
                  else "Female" if self.female_radio.isChecked() else "—")
        # Each component stands or falls on its OWN. Keying the whole date off
        # the year both invented data and lost it: a form holding only a month
        # and day reported "—" (the two values the user typed, gone), while a
        # year alone reported "1879-00-00" — a day and month that were never
        # entered and do not exist. A blank stays visibly blank.
        date = "-".join(part.zfill(width) if part else "?" * width
                        for part, width in ((field(self.date_year), 4),
                                            (field(self.date_month), 2),
                                            (field(self.date_day), 2)))
        if date == "????-??-??":
            date = "—"
        flag = self._dst_flag()
        dst = {0: "No (0)", 1: "Yes (1)", 2: "War time (2)"}.get(flag, "—")
        place = ", ".join(p for p in (field(self.city_input),
                                      field(self.country_input)) if p) or "—"
        latitude = field(self.latitude_input)
        longitude = field(self.longitude_input)
        # Names the axes itself rather than echoing the on-screen chips. The
        # chips shortened to "° N"/"° E" to fit the row, and on screen their
        # position says which is which — in pasted text, nothing does.
        coords = ("lat %s %s, lon %s %s"
                  % (latitude or "—", self.lat_dir_chip.text().strip("° "),
                     longitude or "—", self.lon_dir_chip.text().strip("° "))
                  if latitude or longitude else "—")

        rows = [
            ("Name", field(self.name_input) or "—"),
            ("Gender", gender),
            ("Date", date),
            ("Local time", self._full_clock(self.local_hour, self.local_minute,
                                            self.local_second)),
            ("UTC time", self._full_clock(self.utc_hour, self.utc_minute,
                                          self.utc_second)
             + (" %s" % self.utc_day_offset.text()
                if self.utc_day_offset.text() else "")),
            ("Authoritative", self.time_mode),
            ("UTC offset", field(self.timezone_input) or "—"),
            ("Time zone", field(self.timezone_iana_input) or "—"),
            ("DST", dst),
            ("Place", place),
            ("Coordinates", coords),
        ]
        width = max(len(label) for label, _ in rows)
        return "\n".join("%-*s  %s" % (width, label, value)
                         for label, value in rows)

    def copy_all(self):
        """Put the full record on the clipboard, confirm it, and report it.

        The signal still fires AFTER the copy so a controller can log or extend
        it, but the copy no longer DEPENDS on a controller being attached —
        nothing was connected to ``copy_all_requested``, which is why the button
        appeared to do nothing (or, with a label selected, to copy just that one
        row).
        """
        try:
            QGuiApplication.clipboard().setText(self.record_text())
            self.show_toast("Full record copied")
        except Exception:
            traceback.print_exc()
        self.copy_all_requested.emit()

    @staticmethod
    def _full_clock(hour_field, minute_field, second_field):
        """Same rule as the date: no component invents or swallows another.

        Keying the clock off the hour dropped a minute typed without one, and
        substituting "0" for a blank turned a lone hour into a precise-looking
        "11:00:00" the user never entered — in a birth chart, a fabricated
        minute is not a cosmetic detail.
        """
        parts = [field.text().strip() for field in
                 (hour_field, minute_field, second_field)]
        if not any(parts):
            return "—"
        return ":".join(part.zfill(2) if part else "??" for part in parts)

    #: Shown while a lookup is in flight. Distinct from "—", which means the
    #: question has been ANSWERED with "we do not know" — a spinner and a shrug
    #: are different claims and the user acts on them differently.
    ELEVATION_PENDING = "…"

    #: Sentinel for "leave the elevation chip as it is". ``set_region`` used to
    #: take the elevation as a positional string and default it to empty, so
    #: any caller updating only the region silently wiped a resolved elevation.
    _KEEP = object()

    def set_region(self, region: str = "", elevation=_KEEP):
        """DECORATIVE. Neither value is collected, saved or read back.

        ``elevation`` defaults to leaving the chip untouched. Pass ``""`` to
        clear it explicitly.
        """
        self._suppress = True
        try:
            self.region_input.setText(region or "")
        finally:
            self._suppress = False
        if elevation is not self._KEEP:
            self.elevation_chip.setText("elev %s" % (elevation or "—"))

    def set_elevation(self, metres=None):
        """WI-7: the resolved elevation in metres, or ``None`` for unknown.

        Takes a NUMBER, not a formatted string, so the one place that decides
        how an elevation reads is this view — the lookup service has no
        business knowing the chip says "elev 75 m" (mockup #14's format).

        Still decorative: nothing here reaches ``collect_data()``, and adding
        it there would put an unsaved, unreloadable field into a chart.
        """
        text = "—"
        if metres is not None:
            try:
                value = float(metres)
            except (TypeError, ValueError):
                value = None
            # NaN and infinity survive float() and would render as "elev nan m".
            # A lookup that answered nonsense has not answered.
            if value is not None and value == value and value not in (
                    float("inf"), float("-inf")):
                text = "%d m" % round(value)
        self.elevation_chip.setText("elev %s" % text)

    def set_elevation_pending(self):
        """A lookup is in flight. Kept separate from ``set_elevation(None)`` so
        the caller cannot accidentally say "unknown" when it means "asking"."""
        self.elevation_chip.setText("elev %s" % self.ELEVATION_PENDING)

    def set_elevation_attribution(self, text: str = ""):
        """Credit the elevation source, on the chip that shows its answer.

        A real method rather than a reach into ``elevation_chip`` from outside,
        because this credit is a TERM of the data source (Open-Meteo's licence
        requires it), not decoration. Set from another layer by
        ``getattr(ws, "elevation_chip", None)`` inside a bare ``except``, it
        disappears silently the day this chip is renamed or restructured — a
        licence obligation quietly dropped, with nothing raised and nothing
        logged. Calling a method that does not exist is loud.

        The view still knows nothing about WHERE elevations come from: the
        caller passes the string. Importing the service here to read the
        constant would drag its network and sqlite dependency graph into a GUI
        module's import path.
        """
        self._elevation_attribution = str(text or "")
        self.elevation_chip.setToolTip(self._elevation_attribution)

    def dst_auto_enabled(self) -> bool:
        """Always False. The "Auto from zone" toggle (and the CHTK -1 AUTO
        side-key it wrote) was removed: DST is filled from the zone as a default
        but never persisted as an auto sentinel. Retained so the binding's
        -1-writing branches stay valid (they are now unreachable)."""
        return False

    def set_dst_auto(self, enabled: bool):
        """No-op. Kept so load paths that used to restore the "Auto from zone"
        state do not raise now that the toggle is gone."""
        return

    def clear_fields(self):
        """Blank every persisted field. Emits nothing; the host decides what a
        clear MEANS (a new blank chart, an abandoned edit) after asking for it.
        """
        self.populate({
            'name': '', 'year': None, 'month': None, 'day': None,
            'hour': None, 'minute': None, 'second': None, 'gender': '',
            'country': '', 'city': '', 'latitude': None, 'longitude': None,
            'iana_timezone': '', 'timezone': '', 'dst': 0,
            'time_mode': self.time_mode,
        })
        self.set_region("", "")
        self.set_location_note("")
        self.set_day_offset("")

    def shutdown(self, drain: bool = True):
        """Forward teardown to the map, which owns background workers."""
        try:
            if hasattr(self.map_tab, "shutdown"):
                self.map_tab.shutdown(drain=drain)
        except Exception:
            traceback.print_exc()

    # =========================================================================
    # INTERNAL SETTER HELPERS
    # =========================================================================

    def _set_gender(self, gender):
        """Allow the NEITHER state: exclusivity is dropped for the write.

        A QButtonGroup that stays exclusive cannot be returned to "no answer",
        and '' is a value this form has to be able to hold.
        """
        gender = (gender or "").strip().lower()
        self.gender_group.setExclusive(False)
        self.male_radio.setChecked(gender == "male")
        self.female_radio.setChecked(gender == "female")
        self.gender_group.setExclusive(True)

    @staticmethod
    def _set_text(field, value, width):
        field.setText("" if value in (None, "") else str(value).zfill(width))

    def _set_clock(self, hour_field, minute_field, second_field,
                   hour, minute, second):
        if hour is None:
            hour_field.clear()
            minute_field.clear()
            second_field.clear()
            return
        self._set_text(hour_field, int(hour), 2)
        self._set_text(minute_field, int(minute or 0), 2)
        self._set_text(second_field, int(second or 0), 2)


def _to_float(value):
    """Float or 0.0 — a half-typed '-' must not raise inside a formatter."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    workspace = NewEditWorkspace()
    workspace.resize(1440, 860)
    workspace.setWindowTitle("NewEditWorkspace — standalone")

    workspace.mode_changed.connect(lambda m: print("mode_changed:", m))
    workspace.create_requested.connect(lambda: print("create_requested"))
    workspace.save_requested.connect(lambda: print("save_requested"))
    workspace.cancel_requested.connect(lambda: print("cancel_requested"))
    workspace.clear_requested.connect(lambda: print("clear_requested"))
    workspace.copy_all_requested.connect(lambda: print("copy_all_requested"))
    workspace.field_edited.connect(lambda f: print("field_edited:", f))

    workspace.populate({
        'name': 'Albert Einstein', 'year': 1879, 'month': 3, 'day': 14,
        'hour': 11, 'minute': 30, 'second': 0, 'gender': 'Male',
        'country': 'Germany', 'city': 'Ulm',
        'latitude': 48.4011, 'longitude': 9.9876,
        'iana_timezone': 'Europe/Berlin', 'timezone': '+01:00',
        'dst': 0, 'time_mode': 'Local',
    })
    workspace.set_derived_utc(10, 30, 0)
    workspace.set_status("standalone preview — no controller attached")
    workspace.show()
    sys.exit(app.exec())
