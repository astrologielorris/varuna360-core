# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
The smart token entry bar for the New & Edit tab (WI-3).

One line of natural language in, four coloured chips out: NAME, DATE, TIME,
PLACE. Parsing is deterministic and local — ``parse_birth_text`` runs on a
150 ms debounce after each keystroke and returns both the structured fields and
the half-open character spans they came from. The spans are what make the chips
honest: a chip's × blanks EXACTLY the characters that produced it and re-parses
the remainder, so the bar can never clear a field it did not set.

Why chips are real widgets and not painted regions
--------------------------------------------------
A painted "token" inside the QLineEdit would look identical and be unreachable
by the keyboard, by the accessibility tree and by a screenshot test. Each chip
is therefore a child QFrame carrying a focusable QToolButton whose accessible
name is "Clear <field>", so the token can be dropped without a mouse.

What this widget does NOT do
----------------------------
It never creates or mutates a chart. Ctrl+Enter emits ``accept_requested`` and
stops; the binding manager (WI-4) owns the form and the chart. Keeping the
decision out of here is what lets the same bar serve both New and Edit modes.

Layout and colour are ported from the ``.smartbar`` block of the New & Edit
mockup. The four chip colours are the DOMAIN element palette (Fire/Air/
Water/Earth from ``wheel_items.py``) rather than theme colours, because the
meaning of "date is yellow" must not drift between light and dark.
"""

import re
import traceback

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy,
    QToolButton, QWidget, QVBoxLayout,
)

from ui.qt_theme import (desat_hex, dim_text, get_theme_colors,
                         is_light_theme)
from ui.themed_style import ThemedStyleMixin
from ui.image_paste_line_edit import ImagePasteLineEdit, AiToggleButton

__all__ = ["TokenEntryBar", "TokenChip", "FIELD_ORDER"]

#: Element palette, authoritative copy from ``apps/widgets/wheel_items.py``.
#: DOMAIN data, not theme data — these four values mean Fire/Earth/Air/Water
#: everywhere in the app. Passed through ``desat_hex`` EXACTLY once at style
#: time (SPEC-SAT-001); they are literals, so unlike ``get_theme_colors()``
#: values they are NOT already desaturated.
ELEMENT_COLORS = {
    "Fire": "#E57373",
    "Earth": "#A67C52",
    "Air": "#F0C75E",
    "Water": "#1E4D8C",
}

#: Chip colour per parsed field, matching the mockup's ``.tok-*`` rules.
FIELD_ELEMENT = {
    "name": "Fire",
    "date": "Air",
    "time": "Water",
    "place": "Earth",
}

#: Chip order, left to right. Also the legend order.
FIELD_ORDER = ("name", "date", "time", "place")

#: Semantic destructive colour for the × affordance. The one non-element
#: literal in this file; desaturated once like the element colours.
DANGER_HEX = "#FF3B30"

#: Default horizontal gutter. A host that lays this bar out beside other bands
#: overrides it with ``set_side_gutter`` so every band shares ONE edge.
SIDE_GUTTER = 16

# ---- Chip metrics, ported from the mockup's `.tok` rules -------------------
CHIP_RADIUS = 8           # .tok border-radius
CHIP_FONT = "12px"        # .tok font
CHIP_TAG_FONT = "8.5px"   # .tok small
HINT_FONT = "10.5px"      # .smartline .hintk
PROMPT_FONT = "14px"      # .prompt

#: Alpha of the chip's own accent used as its fill. The chip TEXT is measured
#: against this composited background, not against the bare bar.
CHIP_TINT = 0.13

#: Keystroke-to-parse delay in milliseconds. Long enough that a fast typist
#: parses once per word rather than once per character, short enough that the
#: chips still feel live.
PARSE_DEBOUNCE_MS = 150

MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

PLACEHOLDER = ('type naturally…  "Albert Einstein, Mar 14 1879 11:30, Ulm, Germany"'
               '  (every token stays editable below)')


def _rgba(hex_color, alpha):
    """``rgba(r,g,b,a)`` string for a hex colour at ``alpha`` (0.0-1.0).

    The mockup expresses chip fills as ``color-mix(... 12%, transparent)``,
    which Qt stylesheets have no equivalent for. An explicit rgba() is the
    faithful translation and keeps the underlying widget colour showing through
    in BOTH themes, so no light/dark branch is needed for the chip fills.
    """
    color = QColor(hex_color)
    if not color.isValid():
        return hex_color
    return "rgba(%d, %d, %d, %.3f)" % (
        color.red(), color.green(), color.blue(), max(0.0, min(1.0, alpha)))


def _element_hex(field):
    """Desaturated element colour for a parsed field (SPEC-SAT-001, once)."""
    return desat_hex(ELEMENT_COLORS[FIELD_ELEMENT[field]])


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


#: WI-10, the "Middle" pick: the MOCKUP's chip inks, corrected only where they
#: fail against our fills. Four are the mockup's value verbatim; four are the
#: smallest hue-preserving move that reaches 4.5:1 (measured, not chosen).
#:
#: These are hand-picked colours, which is why they are a table and not a
#: formula. The derivation in ``_element_ink`` cannot reach them: it only walks
#: lightness from the element colour, and light ``time`` never moves at all
#: because ``#1E4D8C`` already clears the floor, while the mockup deliberately
#: brightened it to ``#0B62B0``.
#:
#: Ratios below are at full saturation. Like every other colour here they pass
#: through ``desat_hex`` once (SPEC-SAT-001), so the SATURATION setting moves
#: ink and fill together, exactly as it already did for the derived values.
CHIP_INK = {
    "light": {
        "name":  "#af423d",   # mockup #B4443F was 4.44 on our fill -> 4.64
        "date":  "#866700",   # mockup #8A6A00 was 4.41 -> 4.62
        "time":  "#0B62B0",   # mockup verbatim, 4.62
        "place": "#7A5330",   # mockup verbatim, 5.41
    },
    "dark": {
        "name":  "#f37a7a",   # mockup #E57373 was 4.23 -> 4.74
        "date":  "#F0C75E",   # mockup verbatim, 6.96
        "time":  "#5EADFF",   # mockup verbatim, 6.07
        "place": "#c0905f",   # mockup #A67C52 was 3.46 -> 4.55
    },
}


def _chip_ink(field):
    """The ink for a chip's tag and value.

    Falls back to the derived :func:`_element_ink` for a field that has an
    ELEMENT but no entry here — the realistic drift, where a token type is
    added to ``FIELD_ELEMENT``/``FIELD_ORDER`` and this table is forgotten. It
    then gets readable derived ink instead of a KeyError.

    A field unknown to ``FIELD_ELEMENT`` still raises, from ``_element_hex``.
    That is deliberate: this widget has no colour to offer a token it has never
    heard of, and inventing one would hide the wiring mistake.
    """
    picked = CHIP_INK["light" if is_light_theme() else "dark"].get(field)
    if picked is None:
        return _element_ink(field, tint=CHIP_TINT)
    return desat_hex(picked)


def _muted_ink(floor=4.5):
    """The dim foreground tier, on BOTH themes.

    ``secondary_light`` is ``#4f5b62`` on the dark theme and ``#ffffff`` on the
    light one, so using it as TEXT painted every hint in this bar white on a
    near-white bar. ``dim_text`` is the central policy for a dim tier over the
    8-key palette (SPEC-THM-001, td-iqjb F2). Mirrors ``new_edit_workspace``,
    which mirrors this module's ``_rgba``/``_element_hex`` in the same way.
    """
    # The alpha is MEASURED, not chosen. The two themes are not symmetric (the
    # light foreground is #555555 on #f5f5f5, the dark one is #ffffff on
    # #232629), and this text lands on TWO different surfaces — the panel
    # (secondary) and the inset combo/chip fills (secondary_dark). A constant
    # tuned against one of them misses on the other: 0.78 gives 4.05:1 on
    # #f5f5f5 but only 3.69:1 on #e6e6e6. So take the lowest alpha that clears
    # the floor on EVERY surface the text actually sits on, which re-derives
    # itself for any theme rather than being right for two of them.
    theme = get_theme_colors()
    foreground = theme["secondary_text"]
    surfaces = (theme["secondary"], theme["secondary_dark"])
    alpha = 1.0
    for candidate in (0.62, 0.70, 0.78, 0.86, 0.94, 1.0):
        if all(_contrast(_blend(foreground, surface, candidate).name(),
                         surface) >= floor for surface in surfaces):
            alpha = candidate
            break
    return dim_text(foreground, alpha)


def _hairline(alpha=0.22):
    """A border that survives both themes — white-on-near-white otherwise."""
    return _rgba(get_theme_colors()["secondary_text"], alpha)


def _accent_ink():
    """An accent readable as TEXT: ``primary_light`` washes out on light."""
    theme = get_theme_colors()
    return theme["primary_dark"] if is_light_theme() else theme["primary_light"]


def _ink_on(hex_color):
    """Black or white, whichever actually wins ON ``hex_color``.

    Rule 20 semantic exception: the fill is domain/severity colour, so the ink
    has to be chosen from the fill rather than from the theme.
    """
    color = QColor(hex_color)
    if not color.isValid():
        return "#ffffff"
    # WCAG luminance, sRGB LINEARISED — see new_edit_workspace._ink_on.
    luma = _relative_luminance(color)
    return ("#1a1a1a"
            if (luma + 0.05) / (_INK_DARK_LUMA + 0.05) >= 1.05 / (luma + 0.05)
            else "#ffffff")


def _tidy(line):
    """Collapse the stray commas and runs of spaces a blanked span leaves.

    Mirrors the mockup's ``dropToken`` cleanup, in the same order: space before
    a comma, comma-comma, leading/trailing separators, then multiple spaces.
    """
    line = re.sub(r"\s+,", ",", line)
    line = re.sub(r",\s*,", ",", line)
    line = re.sub(r"^[,\s]+|[,\s]+$", "", line)
    line = re.sub(r"\s{2,}", " ", line)
    return line


def format_chip_value(field, parsed):
    """Human text for a chip — from the PARSED fields, never the raw slice.

    The raw slice is what the user typed ("mar 14 79"); the chip shows what the
    parser UNDERSTOOD ("Mar 14 1879"). Showing the slice back would make a
    misparse invisible, which is the one failure this bar exists to surface.

    Returns ``None`` when the field is not present, which is also the signal to
    build no chip for it.
    """
    try:
        if field == "name":
            value = (parsed.get("name") or "").strip()
            return value or None
        if field == "date":
            year, month, day = (parsed.get("year"), parsed.get("month"),
                                parsed.get("day"))
            if not (year and month and day):
                return None
            if 1 <= int(month) <= 12:
                return "%s %d %d" % (MONTH_ABBR[int(month) - 1], int(day),
                                     int(year))
            return "%04d-%02d-%02d" % (int(year), int(month), int(day))
        if field == "time":
            if not parsed.get("has_time"):
                return None
            return "%02d:%02d:%02d" % (int(parsed.get("hour") or 0),
                                       int(parsed.get("minute") or 0),
                                       int(parsed.get("second") or 0))
        if field == "place":
            city = (parsed.get("city") or "").strip()
            if not city:
                return None
            tail = (parsed.get("country") or parsed.get("state") or "").strip()
            return "%s, %s" % (city, tail) if tail else city
    except Exception:
        traceback.print_exc()
    return None


class _ClearButton(QToolButton):
    """The chip's ×. Focusable, and answers Enter/Return/Delete as a click.

    QToolButton already fires on Space; Delete is added because "this token is
    wrong, remove it" is what the key means everywhere else in the app, and
    Enter because a user tabbing through chips expects it.
    """

    def __init__(self, field, parent=None):
        super().__init__(parent)
        self.setText("×")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Clear %s" % field)
        self.setToolTip("Clear %s token" % field)
        self.setFixedSize(15, 15)
        self.setAutoRaise(True)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                           Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class _ChipsViewport(QScrollArea):
    """Scroll area that asks for the width its chips actually need.

    A plain QScrollArea reports a small, fixed size hint that has nothing to do
    with what it contains, so once four chips were parsed only about 7% of them
    was visible — at EVERY width from 760 to 1920, including widths with room
    for all of them. The scrollbar meant no data was lost, but chips were hidden
    with space to spare, which is worse than the overflow it was added to solve.

    The trigger is LATE POPULATION, not the size policy — worth stating plainly
    because the first explanation of this bug (and its commit message) blamed
    the policy. An isolated probe puts the collapse at 48 px under BOTH Maximum
    and Preferred when the chips are added after the first layout pass, and at
    540 px under BOTH when they exist at construction. The chips only exist
    after a parse, so the layout had already sized this widget while its
    container was empty and nothing told it otherwise.

    So the hint follows the CONTENT while the minimum stays near zero: "show the
    chips whenever there is room" becomes the default, and the near-zero minimum
    is what stops the chips' width propagating back into the workspace floor
    (the 994 px clamp this viewport exists to prevent).

    WHY THE HINT IS RE-ASSERTED FROM AN EVENT FILTER
    ------------------------------------------------
    A single ``updateGeometry()`` at the end of the render pass is NOT enough,
    and the reason is worth keeping: the parent layout does not re-read
    ``sizeHint()`` on demand, it caches what the widget reported at the moment
    it was told to look. Under the app's qt-material global stylesheet the chips
    are not styled yet at that moment — polish happens later, on the event loop
    — so the render-path call publishes a hint of 8 px, and nothing ever
    corrects it. The chips then sit at 8 px with 1300 px of free row, which is
    the ORIGINAL bug wearing a different cause.

    This was invisible for a while because the tests and probes ran with no
    global stylesheet, where the chips are sized immediately and the single call
    reports the truth. An unstyled Qt app is not the app; the regression test for
    this applies the stylesheet.

    So the viewport watches its own content and re-publishes whenever the width
    it would report actually changes — late styling, a font change, a chip added
    or cleared.

    WHICH EVENTS ACTUALLY CARRY IT, measured rather than assumed (a styled parse
    of a four-chip line): the filter runs on StyleChange 9 times, Resize 6 and
    LayoutRequest 3, and exactly one of each is the one that moves the published
    width. ``Polish`` never fires at all — the container is polished before the
    chips exist, and the chips' own polish reaches it as ChildPolished, which is
    deliberately NOT in the filtered set. It is kept as a cheap superset rather
    than removed, since an unobserved event costs one comparison; it is named
    here as "never seen to fire" so nobody reads it as the mechanism.

    Re-publishing only on a CHANGE skips pointless layout invalidations. It is
    NOT what makes this converge — a probe with that test removed also settles,
    because the width is read from the CONTENT's hint, which has no feedback
    path from the viewport's own geometry or from the scrollbar appearing.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._published_width = None

    def setWidget(self, widget):
        super().setWidget(widget)
        if widget is not None:
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.widget() and event.type() in (
                QEvent.Type.LayoutRequest, QEvent.Type.Resize,
                QEvent.Type.Polish, QEvent.Type.StyleChange):
            self.publish_content_width()
        return super().eventFilter(obj, event)

    def publish_content_width(self):
        """Tell the parent layout the content width changed — once per change.

        Idempotent by design: callers may invoke it defensively (the render path
        does) without costing a layout pass when nothing moved.
        """
        content = self.widget()
        width = content.sizeHint().width() if content is not None else 0
        if width != self._published_width:
            self._published_width = width
            self.updateGeometry()

    def sizeHint(self):
        hint = super().sizeHint()
        content = self.widget()
        if content is not None:
            hint.setWidth(content.sizeHint().width() + 2)   # +2 for the frame
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class _ChipEditor(QLineEdit):
    """The in-place editor a chip swaps in. Escape and blur CANCEL.

    Both cancels are the same promise: nothing leaves this widget unless the
    user pressed Enter. A blur that committed would turn "I clicked a chip,
    thought better of it and clicked elsewhere" into an edit of the line, which
    is the one outcome the user did not ask for.
    """

    commit = Signal(str)
    cancel = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFrame(False)
        self._done = False
        self.returnPressed.connect(self._commit)
        self.textChanged.connect(self._fit)

    def _fit(self):
        # The hint below changed, and a layout only re-reads a hint it is told
        # has moved. Without this the editor keeps whatever width it was seeded
        # with and the text scrolls inside a box that never grows.
        self.updateGeometry()

    def sizeHint(self):
        """As wide as its TEXT, not as wide as a text box.

        QLineEdit's own hint reserves ~17 characters regardless of content,
        which made the chip jump 45px the moment it was clicked and shoved
        every chip to its right along with it. Measured on the date chip:
        146px as a label, 191px as a default-hinted editor.
        """
        hint = super().sizeHint()
        width = self.fontMetrics().horizontalAdvance(self.text() or " ") + 2
        hint.setWidth(max(width, self.minimumWidth()))
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()

    def _commit(self):
        if self._done:
            return
        self._done = True
        self.commit.emit(self.text())

    def _cancel(self):
        if self._done:
            return
        self._done = True
        self.cancel.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._cancel()


class TokenChip(ThemedStyleMixin, QFrame):
    """One parsed token: uppercase field tag, understood value, and its ×.

    Emits :attr:`clear_clicked` and :attr:`edit_requested` with its field name;
    it does not touch the line itself, because the line belongs to the bar and
    only the bar knows the spans that are currently valid. The chip is told
    what raw text to edit (:meth:`begin_edit`) rather than reaching for it,
    for the same reason.
    """

    clear_clicked = Signal(str)
    edit_requested = Signal(str)
    edit_committed = Signal(str, str)
    edit_cancelled = Signal(str)

    def __init__(self, field, value, parent=None):
        super().__init__(parent)
        self.field = field
        self.setObjectName("tokenChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName("%s token: %s" % (field, value))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to edit this token")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 5, 5)
        layout.setSpacing(6)

        self.tag_label = QLabel(field.upper())
        self.value_label = QLabel(value)
        self.clear_button = _ClearButton(field, self)
        self.clear_button.clicked.connect(
            lambda: self.clear_clicked.emit(self.field))

        layout.addWidget(self.tag_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.clear_button)

        self.editor = None
        self._x_shown = False
        self._register_themed(self, self._chip_style)
        self._register_themed(self.tag_label, self._tag_style)
        self._register_themed(self.value_label, self._value_style)
        self._register_themed(self.clear_button, self._clear_style)

    # -- editing -------------------------------------------------------------

    def mouseReleaseEvent(self, event):
        """A click anywhere on the chip body asks to edit it.

        The × is a real button and accepts its own clicks, so clearing never
        arrives here — the two affordances do not compete for the same press.
        """
        if (event.button() == Qt.MouseButton.LeftButton
                and self.editor is None
                and self.rect().contains(event.position().toPoint())):
            self.edit_requested.emit(self.field)
        super().mouseReleaseEvent(event)

    def begin_edit(self, raw_text):
        """Swap the value label for an editor seeded with ``raw_text``.

        The seed is the text as it stands IN THE LINE, not the chip's formatted
        display value. Those differ — a chip may read ``1879-03-14`` for a line
        that says ``Mar 14 1879`` — and it is the line's own characters that
        get replaced on commit. Seeding with the pretty form would hand the
        parser a string the user never wrote and quietly re-interpret it.
        """
        if self.editor is not None:
            return
        self.editor = _ChipEditor(raw_text, self)
        # NOT put in the themed registry: it is created and destroyed per edit,
        # and that registry has no removal, so registering here would leave a
        # dead C++ pointer behind for every edit the user ever makes. A theme
        # switch mid-edit is handled by refresh_theme() instead.
        self.editor.setStyleSheet(self._editor_style())
        self.editor.setMinimumWidth(36)
        self.editor.commit.connect(self._on_editor_commit)
        self.editor.cancel.connect(self._on_editor_cancel)

        self.value_label.hide()
        self.layout().replaceWidget(self.value_label, self.editor)
        self.editor.show()
        self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self.editor.selectAll()

    def end_edit(self):
        """Put the label back. Safe to call when no edit is open."""
        editor = self.editor
        if editor is None:
            return
        self.editor = None
        # Silence it before teardown. Re-parenting a FOCUSED line edit fires
        # focusOut, which is its cancel path, so a plain teardown would emit a
        # cancellation for an edit that was already resolved.
        editor._done = True
        self.layout().replaceWidget(editor, self.value_label)
        self.value_label.show()
        editor.setParent(None)
        editor.deleteLater()

    def _on_editor_commit(self, text):
        field = self.field
        self.end_edit()
        self.edit_committed.emit(field, text)

    def _on_editor_cancel(self):
        field = self.field
        self.end_edit()
        self.edit_cancelled.emit(field)

    # -- styles: each re-reads the palette per call, so replay works ---------

    def _chip_style(self):
        ink = _element_hex(self.field)
        return ("QFrame#tokenChip {"
                " border: 1px solid %s;"
                " border-radius: %dpx;"
                " background-color: %s; }"
                "QFrame#tokenChip:hover { border-color: %s; }"
                % (_rgba(ink, 0.45), CHIP_RADIUS, _rgba(ink, CHIP_TINT),
                   _rgba(desat_hex(DANGER_HEX), 0.45)))

    def _tag_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 800;"
                " background: transparent; border: none; }"
                % (_chip_ink(self.field), CHIP_TAG_FONT))

    def _value_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 500;"
                " font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
                " background: transparent; border: none; }"
                % (_chip_ink(self.field), CHIP_FONT))

    def _editor_style(self):
        """The editor wears the value label's clothes, plus a caret.

        Matching the label rather than looking like a text box is the point:
        the chip must not visibly change size or shape when it becomes
        editable, or every click makes the whole chip row jump.
        """
        return ("QLineEdit { color: %s; font-size: %s; font-weight: 500;"
                " font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
                " background: transparent; border: none; padding: 0px;"
                " selection-background-color: %s; }"
                % (_chip_ink(self.field), CHIP_FONT,
                   _rgba(_element_hex(self.field), 0.45)))

    def _clear_style(self):
        """The × keeps its geometry always and only its PAINT is conditional.

        Hiding the widget outright would make it unfocusable, which would undo
        the reason it is a real button; fading it instead keeps Tab order and
        the accessibility tree intact while matching the mockup's hover reveal.
        """
        danger = desat_hex(DANGER_HEX)
        if not self._x_shown:
            return ("QToolButton { border: none; background: transparent;"
                    " color: transparent; }")
        return ("QToolButton {"
                " border: 1px solid %s; border-radius: 7px;"
                " background-color: %s; color: %s;"
                " font-size: %s; font-weight: 700; padding: 0px; }"
                "QToolButton:hover, QToolButton:focus {"
                " background-color: %s; }"
                % (_rgba(danger, 0.55), danger,
                   _ink_on(danger), CHIP_TAG_FONT, _rgba(danger, 0.85)))

    def _set_x_shown(self, shown):
        if shown != self._x_shown:
            self._x_shown = bool(shown)
            self.clear_button.setStyleSheet(self._clear_style())

    # -- reveal on hover or keyboard focus ----------------------------------

    def enterEvent(self, event):
        self._set_x_shown(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.clear_button.hasFocus():
            self._set_x_shown(False)
        super().leaveEvent(event)

    def refresh_theme(self):
        self._replay_themed()
        if self.editor is not None:
            self.editor.setStyleSheet(self._editor_style())


class _EntryLineEdit(ImagePasteLineEdit):
    """Entry line edit that surrenders Tab, Ctrl+Enter and Ctrl+L to the bar and
    inherits image paste/drop diversion (``image_pasted``) from
    ``ImagePasteLineEdit``.

    Tab must be intercepted in ``event()``, not ``keyPressEvent()``: Qt consumes
    it earlier as focus navigation, so a keyPressEvent override never sees it.
    The paste chord is NOT one of the keys handled here, so ``event()`` falls
    through to the base ``keyPressEvent``, where an image on the clipboard is
    diverted to ``image_pasted`` and text paste flows normally.
    """

    tab_pressed = Signal()
    accept_pressed = Signal()
    clear_pressed = Signal()

    def event(self, event):
        if event.type() == event.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            if (key == Qt.Key.Key_Tab
                    and not (mods & Qt.KeyboardModifier.ShiftModifier)):
                # Only swallow Tab when there is something to accept; on an empty
                # line let Qt do its normal focus traversal (finding #3).
                if self.text().strip():
                    self.tab_pressed.emit()
                    return True
                return super().event(event)
            if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and (mods & Qt.KeyboardModifier.ControlModifier)):
                self.accept_pressed.emit()
                return True
            if (key == Qt.Key.Key_L
                    and (mods & Qt.KeyboardModifier.ControlModifier)):
                self.clear_pressed.emit()
                return True
        return super().event(event)


class TokenEntryBar(ThemedStyleMixin, QWidget):
    """The natural-language entry line, its chips, and the parse legend.

    Signals (the WI-4 binding contract):
        ``parsed(dict)`` — every parse, including spans and the empty case.
        ``line_changed(str)`` — raw line text on every user edit.
        ``token_cleared(str)`` — a chip's × was used; the field name.
        ``accept_requested()`` — Ctrl+Enter.
        ``clear_requested()`` — Ctrl+L.
        ``tab_accept()`` — Tab with something to complete.
    """

    parsed = Signal(dict)
    line_changed = Signal(str)
    token_cleared = Signal(str)
    accept_requested = Signal()
    clear_requested = Signal()
    tab_accept = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tokenEntryBar")

        self._last_parsed = {}
        #: The exact line text that produced ``_last_parsed`` (and thus its
        #: spans).  A chip's × is only safe to act on while the live line still
        #: equals this; otherwise the spans are stale and would cut the wrong
        #: characters, so we re-parse first.
        self._parsed_line = None
        self._chips = []
        #: Re-entrancy guard: a ``parsed`` handler that writes text back (a WI-4
        #: manager normalising the line) must not drive ``_parse_now`` into
        #: unbounded synchronous recursion.
        self._parsing = False
        #: Set while a programmatic ``set_line`` runs, so the echo of our own
        #: text back through ``textChanged`` is not reported as a user edit.
        self._suppress_line_changed = False

        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(PARSE_DEBOUNCE_MS)
        self._parse_timer.timeout.connect(self._parse_now)

        self._build_ui()

    # -- construction --------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        self._outer_layout = outer
        outer.setContentsMargins(SIDE_GUTTER, 12, SIDE_GUTTER, 0)
        outer.setSpacing(0)

        self.line_frame = QFrame()
        self.line_frame.setObjectName("smartLine")
        self.line_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,
                                     True)
        line_layout = QHBoxLayout(self.line_frame)
        line_layout.setContentsMargins(14, 8, 10, 8)
        line_layout.setSpacing(8)

        self.prompt_label = QLabel("❯")
        self.prompt_label.setAccessibleName("entry prompt")

        self.chips_container = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(3, 0, 3, 0)
        self.chips_layout.setSpacing(7)

        # The chips ride in a viewport, and this is load-bearing. Four populated
        # chips sum to a ~930px minimum, and a minimum PROPAGATES: it forced the
        # whole workspace to ~994px, so at 760px the window could not shrink and
        # the layout was clipped instead of reflowing. (The earlier overflow
        # sweep missed it because it measured an EMPTY bar — the chips only
        # exist once a line has been parsed.) The viewport terminates that
        # propagation: the bar can be told any width and the chips scroll inside
        # it rather than dictating the window's floor. Mirrors the mockup, where
        # `.toks` is `flex:0 1 auto; min-width:0`.
        self.chips_viewport = _ChipsViewport()
        self.chips_viewport.setWidgetResizable(True)
        self.chips_viewport.setFrameShape(QFrame.Shape.NoFrame)
        self.chips_viewport.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_viewport.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chips_viewport.setWidget(self.chips_container)
        # Preferred, NOT Maximum: Maximum caps the widget at its size hint and
        # never lets it grow, which is what pinned the chips at 48 px.
        self.chips_viewport.setSizePolicy(QSizePolicy.Policy.Preferred,
                                          QSizePolicy.Policy.Preferred)
        self.chips_viewport.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        self.chips_viewport.viewport().setStyleSheet(
            "background: transparent;")

        self.line_edit = _EntryLineEdit()
        self.line_edit.setObjectName("smartInput")
        self.line_edit.setPlaceholderText(PLACEHOLDER)
        self.line_edit.setAccessibleName("natural language birth data entry")
        self.line_edit.setFrame(False)
        self.line_edit.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        # `flex:1 1 90px; min-width:0` in the mockup — the input yields before
        # the bar does.
        self.line_edit.setMinimumWidth(90)
        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.tab_pressed.connect(self._on_tab)
        self.line_edit.accept_pressed.connect(self.accept_requested.emit)
        self.line_edit.clear_pressed.connect(self._on_clear_shortcut)

        self.hint_label = QLabel("Tab accepts · Ctrl+Enter creates")

        # Sparkle AI toggle: the image-reading affordance. Mounted always (Pro
        # promotion in Lite); the paste controller enables/disables it by
        # capability when attach_image_paste() runs. Own settings key so New &
        # Edit and Transit toggle AI independently.
        self._ai_toggle = AiToggleButton(
            settings_key="newedit.reading_use_ai", parent=self)

        line_layout.addWidget(self.prompt_label)
        line_layout.addWidget(self.chips_viewport)
        line_layout.addWidget(self.line_edit, 1)
        line_layout.addWidget(self.hint_label)
        line_layout.addWidget(self._ai_toggle)

        outer.addWidget(self.line_frame)
        outer.addWidget(self._build_legend())

        self._register_themed(self.line_frame, self._line_frame_style)
        self._register_themed(self.prompt_label, self._prompt_style)
        self._register_themed(self.line_edit, self._input_style)
        self._register_themed(self.hint_label, self._muted_style)

    def _build_legend(self):
        """The static ``parsed deterministically`` legend under the line."""
        legend = QWidget()
        layout = QHBoxLayout(legend)
        layout.setContentsMargins(30, 5, 4, 0)
        layout.setSpacing(8)

        lead = QLabel("parsed deterministically ·")
        layout.addWidget(lead)
        self._register_themed(lead, self._muted_style)

        for field in FIELD_ORDER:
            entry = QWidget()
            entry_layout = QHBoxLayout(entry)
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(5)

            swatch = QLabel()
            swatch.setFixedSize(7, 7)
            swatch.setAccessibleName("%s colour" % field)
            self._register_themed(
                swatch,
                lambda f=field: ("QLabel { background-color: %s;"
                                 " border-radius: 2px; }" % _element_hex(f)))

            caption = QLabel(field)
            self._register_themed(caption, self._muted_style)

            entry_layout.addWidget(swatch)
            entry_layout.addWidget(caption)
            layout.addWidget(entry)

        tail = QLabel("· hover a chip for its × to clear that token")
        self._register_themed(tail, self._muted_style)
        layout.addWidget(tail)
        layout.addStretch(1)
        return legend

    # -- styles --------------------------------------------------------------

    def _line_frame_style(self):
        theme = get_theme_colors()
        return ("QFrame#smartLine {"
                " background-color: %s;"
                " border: 1px solid %s;"
                " border-radius: 14px; }"
                % (theme["secondary"], _hairline(0.24)))

    def _prompt_style(self):
        return ("QLabel { color: %s; font-size: %s; font-weight: 700;"
                " font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;"
                " background: transparent; }"
                % (_accent_ink(), PROMPT_FONT))

    def _input_style(self):
        """The typed line, plus an EXPLICIT placeholder colour.

        Left to itself Qt derives the placeholder from the text colour at 50%
        alpha, and the two themes are not symmetric, so one derivation cannot
        serve both: measured, that gave #a5a5a5 on the light panel — 2.26:1,
        under this file's 4.5 floor and the faintest text in the widget — while
        the dark theme landed at a comfortable 4.93:1. The one line that tells
        a first-time user what the bar accepts should not be the hardest thing
        on it to read.

        The mockup says the same thing in CSS (``::placeholder{color:var(--txt3);
        opacity:1}``): the muted TIER, not the foreground at half strength.
        """
        theme = get_theme_colors()
        return ("QLineEdit#smartInput {"
                " background: transparent; border: none;"
                " color: %s; font-size: 13px; font-weight: 500;"
                " placeholder-text-color: %s;"
                " min-height: 26px; }"
                % (theme["secondary_text"], _muted_ink()))

    def _muted_style(self):
        return ("QLabel { color: %s; font-size: %s;"
                " background: transparent; }" % (_muted_ink(), HINT_FONT))

    #: Below this the static keyboard hint is hidden: it is the one element on
    #: the row that carries no data and no control, so it is what should go
    #: first when the row runs out of room.
    HINT_HIDE_WIDTH = 1100

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            hint = getattr(self, "hint_label", None)
            if hint is not None:
                hint.setVisible(self.width() >= self.HINT_HIDE_WIDTH)
        except Exception:
            traceback.print_exc()

    def set_side_gutter(self, pixels):
        """Match a host's horizontal gutter.

        The bar keeps its own sensible default when used alone; a host that
        stacks it above other bands sets this so the left and right edges line
        up with them instead of drifting apart as the host's gutter changes.
        """
        try:
            margins = self._outer_layout.contentsMargins()
            self._outer_layout.setContentsMargins(
                int(pixels), margins.top(), int(pixels), margins.bottom())
        except Exception:
            traceback.print_exc()

    def refresh_theme(self):
        """Re-apply every registered style, chips included (SPEC-THM-001)."""
        self._replay_themed()
        if getattr(self, "_ai_toggle", None) is not None:
            try:
                self._ai_toggle.refresh_theme()
            except Exception:
                traceback.print_exc()
        for chip in self._chips:
            try:
                chip.refresh_theme()
            except Exception:
                traceback.print_exc()

    # -- public API ----------------------------------------------------------

    def set_line(self, text):
        """Set the line programmatically: re-parses and re-chips, never accepts.

        ``line_changed`` is deliberately NOT emitted — the caller is the one who
        supplied the text (a chart load reading its tokens back into the bar),
        and echoing it invites a binding loop. ``parsed`` IS emitted, because
        the structured read-back is the point.

        Idempotent: setting the line to text it already holds (and has already
        parsed) is a no-op. That is what lets a WI-4 manager echo the current
        line back from its ``parsed`` handler without a feedback loop (#2).
        """
        text = text or ""
        if text == self.line_edit.text() and self._parsed_line == text:
            return
        self._suppress_line_changed = True
        try:
            self.line_edit.setText(text or "")
        finally:
            self._suppress_line_changed = False
        self._parse_timer.stop()
        self._parse_now()

    def current_line(self):
        """The raw text exactly as typed."""
        return self.line_edit.text()

    def attach_image_paste(self, extractor_provider):
        """Wire the sparkle toggle + image paste to the shared extractor.

        Called by the host (EditChartPanel) after construction with the
        edition-gated ``ai_image_extractor`` (or None in Lite). All the logic
        lives in the Core controller; this only hands it the pieces. Safe to
        call with ``None`` (the toggle then shows disabled / Pro-only)."""
        from apps.widgets.token_bar_image_paste import TokenBarImagePaste
        self._image_paste = TokenBarImagePaste(
            bar=self,
            line_edit=self.line_edit,
            toggle=self._ai_toggle,
            extractor_provider=extractor_provider,
            notify=None,
            parent=self,
        )

    def clear(self):
        """Blank the line, the chips and the cached parse."""
        self._suppress_line_changed = True
        try:
            self.line_edit.clear()
        finally:
            self._suppress_line_changed = False
        self._parse_timer.stop()
        self.line_changed.emit("")
        self._parse_now()

    # -- input handling ------------------------------------------------------

    def _on_text_changed(self, text):
        if not self._suppress_line_changed:
            self.line_changed.emit(text)
        self._parse_timer.start()

    def _on_tab(self):
        if self.line_edit.text().strip():
            self.tab_accept.emit()

    def _on_clear_shortcut(self):
        self.clear_requested.emit()
        self.clear()

    # -- parsing -------------------------------------------------------------

    @staticmethod
    def _parse(line):
        """Deterministic parse of ``line``. Never raises, never returns None.

        The parser is imported HERE rather than at module scope so that merely
        importing this widget stays a pure-Qt operation — the parser package
        pulls a sizeable dependency graph that a GUI import path should not pay
        for, and a headless test of the chip formatting should not need it.
        """
        try:
            from AI_tools.AI_main_function.text_to_chtk import parse_birth_text
            result = parse_birth_text(line, partial=True, with_spans=True)
            return result if isinstance(result, dict) else {}
        except Exception:
            # partial=True already promises not to raise on bad input; this
            # catch is for everything else (a missing parser, an unexpected
            # regression). The bar degrades to "no chips" — the user keeps
            # typing, the GUI does not die.
            traceback.print_exc()
            return {}

    def _parse_now(self):
        # Re-entrancy guard: if a `parsed` handler writes text back and re-enters
        # here, do nothing this pass — the write's own textChanged will schedule
        # a fresh parse on the debounce. This bounds the recursion (finding #2).
        if self._parsing:
            return
        self._parsing = True
        try:
            line = self.line_edit.text()
            result = self._parse(line)
            self._last_parsed = result
            self._parsed_line = line
            self._render_chips(result)
            if not line.strip():
                # An EMPTY bar states nothing, so it says nothing (WI-11).
                #
                # This is not a tidiness rule. The parser answers an empty line
                # with a full dict carrying city="Unknown" — TRUTHY — so the
                # obvious `if not parsed: return` on the listening side never
                # fires for the one case it was written for, and the form is
                # left defended only by a downstream match on the literal
                # string "Unknown". Not emitting removes the case at its
                # source: clearing the bar can no longer put anything in front
                # of the form to be misread.
                #
                # Clearing the bar is still reported — via `clear_requested`,
                # which says "the user cleared it" rather than "here is a parse
                # of nothing". The two are different claims and only one of
                # them is true.
                return
            self.parsed.emit(dict(result))
        finally:
            self._parsing = False

    # -- chips ---------------------------------------------------------------

    def _clear_chip_widgets(self):
        """Drop the chip widgets AND their registry entries.

        Chips are dynamic children, so leaving them registered would make the
        next ``refresh_theme`` call into deleted C++ objects — they own their
        own registries and are re-created from scratch on every parse.
        """
        for chip in self._chips:
            # Close any open editor FIRST. Tearing down a focused QLineEdit
            # fires focusOut, which is this widget's cancel path — letting that
            # run against a half-dismantled chip means a signal handler
            # reaching into a layout that is on its way out.
            chip.end_edit()
            self.chips_layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []

    def _render_chips(self, result):
        self._clear_chip_widgets()
        spans = result.get("spans") or {}
        for field in FIELD_ORDER:
            value = format_chip_value(field, result)
            if not value:
                continue
            if not spans.get(field):
                # No span means the bar cannot un-set it later; showing a chip
                # whose × would be a no-op is worse than showing no chip.
                continue
            chip = TokenChip(field, value, self.chips_container)
            chip.clear_clicked.connect(self._on_chip_cleared)
            chip.edit_requested.connect(self._on_chip_edit_requested)
            chip.edit_committed.connect(self._on_chip_edit_committed)
            self.chips_layout.addWidget(chip)
            self._chips.append(chip)
        self.chips_container.setVisible(bool(self._chips))

        # The viewport's size hint is derived from this content, so the layout
        # has to be told it changed — without this the bar keeps the width it
        # computed when the bar was empty. This call is the fast path only: under
        # a global stylesheet the chips are not styled yet here, so the viewport
        # also re-publishes from its event filter once they are.
        self.chips_container.adjustSize()
        self.chips_viewport.publish_content_width()
    def _fresh_span(self, field):
        """``(start, end)`` for ``field`` against the LIVE line, or ``None``.

        The spans in ``_last_parsed`` describe ``_parsed_line``. If the live
        text has moved on since then (a keystroke with the debounce still
        pending), those spans point at the wrong characters — so re-parse the
        live line first and use its fresh spans (finding #1).
        """
        if (self._parse_timer.isActive()
                or self.line_edit.text() != self._parsed_line):
            self._parse_timer.stop()
            self._parse_now()
        span = ((self._last_parsed or {}).get("spans") or {}).get(field)
        if not span:
            return None
        try:
            start, end = int(span[0]), int(span[1])
        except Exception:
            traceback.print_exc()
            return None
        if not (0 <= start <= end <= len(self.line_edit.text())):
            # Stale span (the line moved on since the parse that produced it).
            # Refusing beats rewriting the wrong characters.
            return None
        return start, end

    def _rewrite_span(self, start, end, replacement):
        """Put ``replacement`` in place of ``line[start:end]`` and re-parse.

        The exact sequence ``_on_chip_cleared`` uses, because the binding reads
        chip ownership off these signals: a chip edit has to be
        indistinguishable from the same text typed into the bar, or the form
        would decide the two came from different authors.
        """
        line = self.line_edit.text()
        new_line = _tidy(line[:start] + replacement + line[end:])
        self._suppress_line_changed = True
        try:
            self.line_edit.setText(new_line)
        finally:
            self._suppress_line_changed = False
        self._parse_timer.stop()
        self.line_changed.emit(new_line)
        self._parse_now()
        return new_line

    def _on_chip_cleared(self, field):
        """Blank exactly this token's characters, tidy, re-parse, re-chip."""
        span = self._fresh_span(field)
        if span is None:
            return
        self._rewrite_span(span[0], span[1], " " * (span[1] - span[0]))
        self.token_cleared.emit(field)

    # -- chip editing --------------------------------------------------------

    def _on_chip_edit_requested(self, field):
        """Open the editor on the chip's own characters.

        Only one chip edits at a time: opening a second would leave the first
        holding a span that the commit of either one invalidates.
        """
        for chip in self._chips:
            chip.end_edit()
        span = self._fresh_span(field)
        if span is None:
            return
        # _fresh_span may have re-parsed and rebuilt every chip, so the chip
        # that asked is possibly already deleted. Find the live one by field.
        for chip in self._chips:
            if chip.field == field:
                chip.begin_edit(self.line_edit.text()[span[0]:span[1]])
                return

    def _on_chip_edit_committed(self, field, text):
        """Substitute the edited text back into the line.

        No ``token_edited`` signal exists and none is wanted: an edit IS the
        line changing, and the line changing is already reported by
        ``line_changed`` + ``parsed``. A third signal saying the same thing is
        a second write path into the form, which is exactly what the binding's
        ownership protocol cannot have.
        """
        span = self._fresh_span(field)
        if span is None:
            return
        if not text.strip():
            # Editing a token down to nothing is how a user says "remove it".
            # Route it to the clear path rather than writing an empty span, so
            # it emits token_cleared like the × does — the form must not be
            # left holding a value the bar no longer shows.
            self._on_chip_cleared(field)
            return
        self._rewrite_span(span[0], span[1], text.strip())


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    bar = TokenEntryBar()
    bar.resize(1000, 90)
    bar.setWindowTitle("TokenEntryBar — standalone")

    bar.parsed.connect(
        lambda d: print("parsed:", {k: d.get(k) for k in
                                    ("name", "year", "month", "day", "hour",
                                     "minute", "city")}, "spans:",
                        d.get("spans")))
    bar.line_changed.connect(lambda t: print("line_changed:", repr(t)))
    bar.token_cleared.connect(lambda f: print("token_cleared:", f))
    bar.accept_requested.connect(lambda: print("accept_requested"))
    bar.clear_requested.connect(lambda: print("clear_requested"))
    bar.tab_accept.connect(lambda: print("tab_accept"))

    bar.show()
    bar.set_line("Albert Einstein, Mar 14 1879 11:30, Ulm, Germany")
    sys.exit(app.exec())
