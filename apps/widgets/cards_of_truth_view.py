#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Cards of Truth View (SPEC-COT-001)
==================================
The 5th chart view (``chart_stack`` index 4). Draws the 14-card birth spread in
its canonical cross geometry with the natal bodies placed into the cards they
fall in.

Why a custom-painted ``QWidget`` and not a ``QGraphicsScene``
-------------------------------------------------------------
The other four views draw into a fixed-size scene and fit it into the viewport.
This figure has no natural scene size: it is a 7x5 grid whose card height is
derived from the viewport so it always fits without scrolling (SPEC-COT-001
§4.7, AC-5). Painting straight onto the widget makes that derivation the whole
layout algorithm, and there is no scroll/zoom state to keep in sync.

Everything derives from ONE number
----------------------------------
``_metrics()`` solves for ``h`` (card height) from the available rectangle and
then expresses every other dimension as a ratio of it: card width, corner
radius, rank size, pip size, chip diameter, rail height, gaps. One knob means
1920x1080 and 4K need no breakpoints, and nothing can drift out of proportion.

Theme
-----
There is no stylesheet anywhere in this widget: ``paintEvent`` reads
``is_light_theme()`` on every repaint, so a live theme switch is a plain
``update()`` and a construction-time palette freeze is structurally impossible
(this is the failure ``ThemedStyleMixin`` exists to fix; a painter has no
equivalent hole). The card palette itself is a semantic, self-contained set in
the same class as ``ELEMENT_COLORS`` in ``core/aditya_data.py`` — a playing card
is red or black, and the table it sits on is part of that object, not of the
app chrome. It lives in ONE dict below so it stays tunable in one place.

Contract highlights (full text in SPEC-COT-001 §3)
--------------------------------------------------
* **INV-1** the view never computes a card; everything comes from
  ``core.cards_of_truth_data.assemble_spread`` (INV-13: the CLI shares it).
* **INV-5/6/7** the grid is normative — row 2 runs RIGHT TO LEFT, rows 3/5 are
  centre-anchored, and the empty cells keep their space because the cross
  silhouette is the identity of the spread.
* **INV-12** an engine failure renders as a message; it never breaks the chart
  tab. E-1 and E-5 are live crash paths in the vendored engine.
* **SPEC-COT-007** the screen reaches BOTH timing families. Two mutually
  exclusive buttons in the right flank of row 1 choose between the shipped
  7-year progression and the Age-N quadration; the quadration additionally
  draws the Year Card as a round medallion in the left flank with its ledger
  beside it. Switching REBUILDS (INV-12) — the faces, the line, the rule units
  and the ledger are all different facts, not one payload relabelled. The same
  spec closes the cross up: the Ecliptic tucks half a card into the Ketu/Rahu
  row instead of holding a row of its own, which is why ``_ROW_OFFSET`` is a
  table and no longer arithmetic.
* **INV-15 (v2)** the spread FOLLOWS the active varga. The fourteen card faces
  and the birth card never move — they come from the birth date — but each body
  is filed under its DIVISIONAL sign lord, so switching D-1 to D-9 moves the
  bodies between cards. (v1 of this spec claimed a varga spread was undefined.
  It is defined, and the engine computes it natively.)
"""
from pathlib import Path
from functools import lru_cache
import math
import weakref

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSize
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPainterPath, QLinearGradient,
    QRadialGradient, QImage, QPixmap, QFontMetrics,
)
from PySide6.QtWidgets import QDialog, QLabel, QToolTip, QVBoxLayout, QWidget

from datetime import date as _date

from apps.widgets.card_suit_art import SUIT_INK, suit_pixmap
from apps.widgets import cot_ladder
from core.cards_of_truth_data import progression_blocks
from core.cards_of_truth_data import (
    assemble_progression_spread, assemble_spread, CardsOfTruthUnavailable,
    DEFAULT_ORDER, GRID, GRID_COLS,
)

# SPEC-COT-007 §3.1/§3.2 — the Age-N quadration engine, owned by another track
# and imported through a guard ON PURPOSE. The three names below are the whole
# contract this view has with it, and a view that cannot import them still
# loads, still draws the progression family and still switches its buttons: the
# quadration screen simply says it is unavailable instead of taking the chart
# tab down with an ImportError at module scope (SPEC-COT-001 INV-12, same
# boundary).
#
# Looked up as MODULE GLOBALS at every call site, never captured into a local
# or a default argument, so a test can substitute one and so a later import
# cannot leave a stale binding behind.
try:                                                  # noqa: SIM105
    from core.cards_of_truth_data import assemble_quadration_spread
except Exception:                                     # noqa: BLE001
    assemble_quadration_spread = None
try:                                                  # noqa: SIM105
    from core.cards_of_truth_data import quadration_ages
except Exception:                                     # noqa: BLE001
    quadration_ages = None
# ``coincidences`` is deliberately NOT imported here. The spec has this view
# calling it, and the engine ended up running the scan inside
# ``assemble_quadration_spread`` — which is the only caller holding all three
# spreads at once, and which builds the progression one anyway. Reading the
# result off the payload is one scan and one place for the §3.7 copy to live;
# calling it here as well would be a second of each. See the report note.
#: The colour a body already wears in the chart views — its configured shadow
#: colour, per-planet, live from Chart Display settings. The hover highlight
#: names the planet by wearing ITS colour, so it has to be the one the wheel
#: and the South Indian chart glow with, not a second table alongside it.
#: (`core.aditya_data.PLANET_COLORS` is a different set for a different job.)
from apps.widgets.planet_shadow import planet_shadow_color
from apps.widgets.chart_view import PlanetClickSignal, SouthIndianView, PROJECT_ROOT
from ui.qt_theme import is_light_theme, get_scale_factor, desat_image, sat_key

PLANETS_PATH = PROJECT_ROOT / "img" / "planets"

# --- proportions, all relative to card height h -------------------------------
_ASPECT = 1.40           # h / w — a playing card is taller than it is wide
_GAP_Y = 0.100           # row gap
_GAP_X = 0.128           # column gap (wider: the columns carry the cross arms)
_ROW1 = 1.15             # row 1 is taller — it holds the birth card
_BASE_SCALE = 1.14       # the birth card itself is drawn larger than its cell
_RADIUS = 0.074          # corner radius — rounder, so the bevel has a curve to
                         # travel round and the card reads as moulded stock
_KEYLINE_INSET = 0.033   # inner frame inset (the double frame of a card face)
_RANK = 0.158            # rank glyph height
_MINI = 0.073            # corner suit mark
_PIP = 0.485             # hero pip, as a fraction of card WIDTH
_CHIP = 0.185            # body-icon disc diameter
_FOOT_PAD = 0.085        # rail height beyond the chip

# SPEC-COT-002 §4.1 — the two vertical gutters flanking the hero pip. Every
# value is a fraction of card HEIGHT, like everything else here, so the whole
# card solves from one number and scales 1080p to 4K without a second table.
_GUT_W = 0.143           # gutter width
_GUT_TOP = 0.319         # gutter band starts below the rank/suit index block
_MC_W = 0.110            # mini card (a pip) width
_MC_H = 0.159            # mini card height
_MC_GAP = 0.027          # between the two stacked pips
_CUSP_W = 0.104          # cusp box width  — SQUARED, never rounded
_CUSP_H = 0.077          # cusp box height
_CUSP_GAP = 0.022
_YEAR = 0.074            # period-year figures
_MAX_H = 340             # cap so a 4K window does not produce absurd cards
_CACHE_MAX = 160         # raster-cache bound; zoom makes the key space unbounded
#: The band's own raster bound. Far smaller than _CACHE_MAX because these
#: are full-figure-width pixmaps, not 20px pips.
_BAND_CACHE_MAX = 8

_W_UNITS = GRID_COLS / _ASPECT + (GRID_COLS - 1) * _GAP_X

#: Widest band any level asks for. The figure must fit at the app minimum in
#: the WORST case, so the fit guarantee is stated against this and not against
#: whichever level happens to be open.
_MAX_RULER = max(spec["band"] for spec in cot_ladder.LEVELS.values())

#: Where the ladder opens, and where it returns on a new person. D-1: the rail,
#: because a reader who never opens the predictive tools should get one thin row
#: rather than an instrument. §4.5 turns this into a persisted setting whose
#: domain is {rail, carriage}.
_DEFAULT_LEVEL = cot_ladder.RAIL

#: The deepest level whose CELLS are wired to their own data.
#:
#: Levels 2 and 3 are in the level table, solve their geometry and accept
#: clicks, but ``band_model`` still hands every level the 52 progression
#: blocks. A seven-cell row therefore draws ``to_map(slot, 7)`` — blocks 6
#: down to 0, the first 49 years of life — underneath a breadcrumb naming the
#: block the reader actually opened. That is worse than a placeholder: it is
#: plausible, and it is wrong.
#:
#: So descent stops here. A stated stopping point is a feature; a screen that
#: answers confidently with somebody else's data is a defect. Raise this the
#: moment ``year_cells`` is wired through (§4.7) — level 3 additionally needs
#: the full birth DATE, which this view does not have.
_DEEPEST_WIRED = cot_ladder.CARRIAGE

#: Which key of the selection path each level reads and writes (INV-7). The
#: rail and the carriage both select BLOCKS — they are two views of one line,
#: not two kinds of thing — so descending from the rail and highlighting on the
#: carriage fill the same key, and climbing back off the carriage clears it.
_SELECT_KEY = {
    cot_ladder.RAIL: "block",
    cot_ladder.CARRIAGE: "block",
    cot_ladder.BLOCK: "year",
    cot_ladder.YEAR: "period",
}


# ------------------------------------------------------------------ #
# The two timing families (SPEC-COT-007 D-1, INV-7)
# ------------------------------------------------------------------ #

#: The two timing families Ernst distinguishes. They are PEERS, not two depths
#: of one ladder: a quadration cycle and a progression are two different things,
#: not two levels of the same ladder.
#: Taken from the ladder where it defines them, so the two modules cannot end up
#: spelling the same family differently — a mismatch would not raise, it would
#: silently fall through to the default family on every lookup.
PROGRESSION = getattr(cot_ladder, "PROGRESSION", "progression")
QUADRATION = getattr(cot_ladder, "QUADRATION", "quadration")

#: A load guard, and nothing more. The family table lives in ``cot_ladder``
#: beside ``LEVELS`` (INV-7) because the band is what most of it describes; this
#: holds only the two fields the VIEW needs before that table exists — the
#: button copy, which is D-1 verbatim, and the line length, which bounds a
#: selection. Read through :func:`family_spec`, never directly, so the ladder's
#: table wins wherever it is present and this cannot quietly become a second
#: source of truth.
_FAMILY_FALLBACK = {
    PROGRESSION: {"line": 52, "unit_years": 7, "label": "7 Year Progression"},
    QUADRATION:  {"line": 90, "unit_years": 1, "label": "Age Quadration"},
}

#: Draw order, left to right, on the button pair. Progression first because it
#: is the family that ships and the one the reader arrives in. Named for the
#: order rather than for the set, so it cannot be mistaken for the ladder's
#: ``FAMILIES`` table, which is the data and lives there (INV-7).
FAMILY_ORDER = (PROGRESSION, QUADRATION)


def family_spec(name):
    """The family, resolved to data — ``cot_ladder.FAMILIES`` where it exists.

    Merged OVER the load guard rather than returned bare: the ladder's row is
    authoritative for everything it carries, and the two fields this view needs
    before that table exists still have to answer if it does not.
    """
    table = getattr(cot_ladder, "FAMILIES", None)
    if isinstance(table, dict):
        spec = table.get(name)
        if isinstance(spec, dict):
            return {**_FAMILY_FALLBACK[name], **spec}
    return dict(_FAMILY_FALLBACK[name])


@lru_cache(maxsize=None)
def _accepts_family(func):
    """Whether ``func`` takes a ``family`` keyword.

    The ladder becomes family-aware in a parallel track, and this view must
    load, draw and switch families against both the before and the after. A
    ``TypeError`` swallowed at the call site would hide a real signature
    mistake; asking the signature once, here, does not.

    CACHED, and the cache is what makes it usable: ``_ruler`` runs this on the
    way to every ``_cell_rect``, which is a few hundred calls per paint and a
    paint per pan step. ``inspect.signature`` on that path is a profiler entry;
    a dict lookup is not. Functions are hashable and the ladder's are module
    globals, so the key is stable for the life of the process.
    """
    try:
        import inspect
        return "family" in inspect.signature(func).parameters
    except Exception:                                # noqa: BLE001
        return False


def family_ink(pal, family):
    """The colour of a family button. Gold, for both (SPEC-COT-007 INV-8).

    **There is no second hue.** SPEC-COT-003 D-5 is Lorris's own standing
    decision — "no third hue, ever" — on the grounds that the deck is red and
    black, and that the blue it replaced came from ``get_theme_colors()``, which
    returns the constant ``#007AFF`` on every theme (SPEC-COT-003 §2.4). AC-6
    bans importing that function into this tier at all.

    The first version of this function took the theme primary for the
    progression, because SPEC-COT-007 INV-8 asked for it. INV-8 was wrong: it
    was written from SPEC-COT-003 **v1.0**, the draft rejected on sight and
    reverted at ``d445fa98``, and it was struck the day it was written.

    **The buttons are told apart by FILL, not by hue** — the active one is a
    filled pill, the inactive one is faint text on the ground (see
    ``_paint_family_buttons``). Colour was never carrying that load, and the
    family is additionally named by the breadcrumb, both captions, the rule's
    units and all fourteen faces.

    ``family`` is unused and stays in the signature deliberately: it is the slot
    a second colour would arrive through if ``get_theme_colors`` is ever fixed
    (26 call sites away, SPEC-COT-003 non-goals), and callers already pass it.

    If a second colour ever does arrive it needs a hue-collision guard, because
    a theme primary landing on the accent's own hue would leave the two buttons
    told apart by nothing at all. The guard written for the struck INV-8 (hue
    distance under 30 degrees and saturation over 0.25 falls back to
    ``pal["ink"]``) was removed with it rather than left as dead code; this
    sentence is the part worth keeping.
    """
    return QColor(pal["accent"])


#: Where each row of the cross sits, measured from the TOP OF ROW 2, as
#: ``(multiples of h, multiples of gap_y)`` — SPEC-COT-007 §3.5, normative.
#:
#: A TABLE, not arithmetic (INV-9). ``_cell_rect`` used to compute
#: ``(row - 2) * (h + gap_y)``, which is exactly why the rows were evenly
#: pitched and why the Ecliptic held a whole row of its own. It now drops HALF a
#: card below row 3 instead of a whole one, so it overlaps the Ketu and Rahu
#: arms and the five rows read as one cross rather than as a bar with three
#: stubs hanging off it. Row 5 follows the Ecliptic rather than a grid line.
#:
#: The table is the reason this is not an ``if row == 4`` in the middle of the
#: geometry: two rows moved this time, the next revision may move a third, and a
#: conditional would have to be found in the painter rather than read off here.
#: Row 1 is absent because it is measured from a different origin — it sits
#: ABOVE the band, and the band's height is a function of the open level.
_ROW_OFFSET = {
    2: (0.0, 0.0),
    3: (1.0, 1.0),
    4: (1.5, 1.0),        # the tuck: half a card, not a whole row
    5: (2.5, 2.0),
}

#: Row 2 to the bottom of row 5, in multiples of ``h`` and ``gap_y``. Derived
#: from the table above rather than restated, so the two can never disagree:
#: the deepest row's offset plus the one card it is itself tall.
_SPAN_H = max(o[0] for o in _ROW_OFFSET.values()) + 1.0      # 3.5
_SPAN_GAP = max(o[1] for o in _ROW_OFFSET.values())          # 2


def _h_units(ruler):
    """Height budget in multiples of ``h``, for a band of ``ruler`` height.

    SPEC-COT-003 INV-2: the band height is a function of the LEVEL, so this
    stopped being a module constant. Five sites read it and every one must come
    through here — a stale reader does not raise, it solves the figure at a
    height that is not on screen. ``_fit_height`` and ``_metrics`` decide the
    size, ``_clamp_pan`` decides how far it may be dragged, ``_cell_rect``
    places row 2 (and reads the band height DIRECTLY, which is why growing
    ``_RULER`` alone used to be enough and no longer is), and the zoom-anchor
    test recomputes the figure height to find the pan bound.

    SPEC-COT-007 §3.5, M-3: the tuck takes ``0.6h`` off the figure — 92px on the
    mockup's 152px card — and this is where that saving has to land. Tucking row
    4 while leaving this at ``4 + 4 * _GAP_Y`` does not raise and does not look
    broken in a screenshot: the figure simply solves for a card height that puts
    its own bottom edge below the widget, and every card drifts up by a fraction
    nobody can name. So it is computed from the same table ``_cell_rect`` reads,
    plus row 1, the gap under it and the band.
    """
    return _ROW1 + ruler + _SPAN_H + (1 + _SPAN_GAP) * _GAP_Y

_SERIF_FAMILIES = [
    "Iowan Old Style", "Palatino Linotype", "Palatino", "URW Palladio L",
    "Book Antiqua", "Georgia", "Liberation Serif", "DejaVu Serif",
]

#: The persisted setting the view, the Planet Placements dialog, the Settings
#: combo and the three in-chart corner buttons all share. One key AND one label
#: table, so no two surfaces can name the same order differently
#: (SPEC-COT-001 D-7 v2 / D-15). Re-exported under the historical name because
#: callers and tests import it from here.
from apps.widgets.cot_index_item import (            # noqa: E402
    COT_ORDER_KEY as ORDER_SETTING_KEY,
    ORDER_LABELS,
    read_persisted_order,
)


#: Month names for the rule's date labels. Built here rather than through
#: ``strftime``: ``%-d`` is a glibc extension that does not exist on Windows,
#: and ``%b`` is LOCALE-dependent, so the same build would print "22 FEB 1994"
#: on one machine and something else on another for a label that is a fixed
#: piece of chart notation, not prose.
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _date_label(d):
    """``22 FEB 1994`` from a date, or ``None``."""
    try:
        return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    except Exception:                                # noqa: BLE001
        return None


def _today():
    """Today's date, behind a seam so the age math is testable.

    ``_current_age`` reads month and day now (WI-3), so a test cannot pin an
    expected age without pinning "today" — and asking ``_current_age`` for its
    own expectation is the circular gate B-Major-1 flagged. Tests monkeypatch
    ``cards_of_truth_view._today`` to a fixed date and assert through the
    CONSUMERS (the TODAY needle, ``_today_cell``, the family-switch default).
    """
    return _date.today()


def _natal_year_of(data):
    """The birth year carried by a NATAL spread payload, or ``None``.

    Row 2 runs right to left with the birth year on the RIGHTMOST card
    (SPEC-COT-001 INV-5), so it is the smallest of the seven period years —
    read, not assumed, because the order button can renumber the row.

    Takes the payload rather than reading ``self._data`` so it can be called on
    the natal assembly BEFORE that assembly is installed, which is the whole
    point of INV-3: once a progression spread lands in ``_data`` the natal year
    is gone from the view's reach entirely.

    ``is not None``, never truthiness. Nothing here is ever 0 — but this is the
    filter shape the feature repeats four times, and one of the four is an AGE.
    """
    if not data:
        return None
    years = [e.get("period_year") for e in data.get("cards", ())
             if e.get("row") == 2 and e.get("period_year") is not None]
    return min(years) if years else None


def _rgba(hex_or_rgb, alpha=1.0):
    """QColor from '#RRGGBB' or an (r, g, b) triple, with a 0..1 alpha."""
    c = QColor(hex_or_rgb) if isinstance(hex_or_rgb, str) else QColor(*hex_or_rgb)
    c.setAlphaF(alpha)
    return c


# The card-table palette. Dark and light are TUNED, not inverted: the "black"
# suits become pale ice on the dark table (literal #000 would vanish), and the
# red is a warm coral there but a deep vermilion on parchment.
_PALETTE = {
    "dark": {
        "bg0": "#070A11", "bg1": "#101828", "glow": _rgba((96, 128, 190), .20),
        "ink": "#E7EDF9", "ink_soft": _rgba("#E7EDF9", .58),
        "ink_faint": _rgba("#E7EDF9", .30),
        "face_up": ("#1E2739", "#161D2C", "#121826"),
        "face_down": ("#10161F", "#0D121B", "#0D121B"),
        "sheen": _rgba((255, 255, 255), .075),
        "ring": _rgba((255, 255, 255), .115),
        "ring_down": _rgba((255, 255, 255), .045),
        "shadow": _rgba((0, 0, 0), .92),
        "red": SUIT_INK["dark"]["red"], "black": SUIT_INK["dark"]["black"],
        "accent": "#E7BC6E",
        "keyline": _rgba((190, 200, 255), .17),
        "keyline_lit": _rgba((202, 214, 255), .32),
        "rim_red": _rgba((244, 116, 107), .40),
        "rim_black": _rgba((190, 203, 226), .32),
        "edge_red": _rgba((244, 116, 107), .78),
        "edge_black": _rgba((190, 203, 226), .66),
        "rail_bg": _rgba((255, 255, 255), .045),
        "rail_line": _rgba((255, 255, 255), .085),
        # the card's own thickness: the sliver of stock visible under the face,
        # then the lit top bevel and the shaded bottom one
        "stock": "#05070C",
        "bevel_hi": _rgba((255, 255, 255), .22),
        "bevel_lo": _rgba((0, 0, 0), .34),
        "chip_bg": ("#F4EFE4", "#DFD6C6"), "chip_ring": _rgba((0, 0, 0), .30),
        "thread": _rgba((180, 202, 240), .16),
        "thread_soft": _rgba((180, 202, 240), .085),
        "wash": _rgba((150, 180, 235), .11),
    },
    "light": {
        "bg0": "#E4DCCD", "bg1": "#F7F3EA", "glow": _rgba((255, 255, 255), .85),
        "ink": "#1D2530", "ink_soft": _rgba("#1D2530", .56),
        "ink_faint": _rgba("#1D2530", .34),
        "face_up": ("#FFFFFF", "#FFFDF8", "#FBF6EC"),
        "face_down": ("#E9E2D4", "#E5DDCE", "#E3DBCB"),
        "sheen": _rgba((255, 255, 255), .55),
        "ring": _rgba((58, 44, 22), .13),
        "ring_down": _rgba((58, 44, 22), .09),
        "shadow": _rgba((74, 56, 28), .42),
        "red": SUIT_INK["light"]["red"], "black": SUIT_INK["light"]["black"],
        "accent": "#9B6E1E",
        "keyline": _rgba((96, 78, 40), .15),
        "keyline_lit": _rgba((96, 78, 40), .26),
        "rim_red": _rgba((190, 47, 42), .16),
        "rim_black": _rgba((27, 34, 46), .12),
        "edge_red": _rgba((190, 47, 42), .55),
        "edge_black": _rgba((27, 34, 46), .42),
        "rail_bg": _rgba((74, 56, 28), .045),
        "rail_line": _rgba((74, 56, 28), .11),
        "stock": "#CFC3AC",
        "bevel_hi": _rgba((255, 255, 255), .80),
        "bevel_lo": _rgba((74, 56, 28), .20),
        "chip_bg": ("#FBF7EF", "#EDE4D3"), "chip_ring": _rgba((74, 56, 28), .22),
        "thread": _rgba((96, 76, 44), .22),
        "thread_soft": _rgba((96, 76, 44), .12),
        "wash": _rgba((255, 252, 244), .85),
    },
}


#: The gesture card's content (SPEC-COT-005 §3.9), as (heading, rows) where a
#: row is either a (gesture, meaning) pair or a one-element prose line. Data
#: rather than a wall of markup so the wording is readable in the diff and
#: reachable from a test without parsing HTML.
#:
#: Human-facing text: no em dashes anywhere in here.
_GESTURE_HELP = (
    ("Reading the spread", (
        ("Row 2 runs RIGHT TO LEFT: the Sun and the birth year "
         "are on the right.",),
        ("Rounded means a card. Squared means a house.",),
        ("The small cards beside each main card are the Jack and King "
         "quadrations of the same seat.",),
        ("Planet glyphs below a card show which planets occupy it. "
         "House numbers in the corner show which cusps fall there.",),
    )),
    ("The 364-year band", (
        ("single click", "open the block under the cursor one level deeper"),
        ("double click", "load that block as the spread you are reading"),
        ("drag", "on the rail, slide before you let go to re-aim"),
        ("", "on the map strip, move the carriage window"),
        ("Escape", "back: first to the natal spread, then up the ladder"),
        ("left / right", "step the selection (right goes to a LOWER age)"),
    )),
    ("The two timings", (
        ("The two buttons above the band choose which timing is on. They "
         "are different things, not two depths of one.",),
        ("7 Year Progression", "52 blocks of seven years"),
        ("Age Quadration", "one deck per year of life, 90 before it repeats"),
    )),
    ("The view", (
        ("+ / - / 0", "zoom in, out, reset"),
        ("drag", "pan, once zoomed past fit"),
        ("F2", "cycle through chart views while fullscreen"),
    )),
    # SPEC-COT-007 D-11 (WI-8). The quadration teaching moved off the rail
    # caption and into the help card, stated in full rather than the caption's
    # compressed line. GUI copy: no dashes, no "coincidence", no valence.
    ("The Age Quadration", (
        ("A fresh deck is quadrated for every year of life, and the card that "
         "lands on your birth card is your Year Card for that year.",),
        ("As you keep quadrating the deck, the 90th quadration is the last one "
         "that differs from the first. The 91st matches the first again.",),
        ("So the band runs 90 ages before the cycle comes back around, and "
         "each age carries one deck.",),
    )),
    # SPEC-COT-007 D-5 + §3.2 ledger. The mechanics of the Year Card and what
    # the ledger means are read ONCE, not every time, so they belong here and
    # not on the screen. The screen shows the medallion and the result; this
    # says where the card came from and what the three lines mean.
    ("The Year Card and the ledger", (
        ("Your birthday, plus one card day for every year you have lived.",),
        ("Anchored on the birthday, not on the solar return.",),
        ("The seal on the left shows the Year Card. The three lines beside "
         "it check whether this card turns up in any of three spreads: your "
         "natal life spread (the 14 birth cards), the seven year progression, "
         "and this year's own spread.",),
        ("Landing on the Ecliptic is the strongest match: the ecliptic card "
         "is the path you are on that year. Landing on the birth card or the "
         "running 52 year period card is the next strongest.",),
        ("The natal life spread the ledger checks is your BIRTH spread, not "
         "the quadrated age deck on screen. They are different spreads.",),
    )),
    ("Learning more", (
        ("The Cards of Truth system is created and taught by Ernst Wilhelm "
         "at cardsoftruth.com, with video courses on timing, the life "
         "spread, and how to do readings.",),
        ("Carmina Divinaria on YouTube also has clear, practical videos "
         "on how to use the cards.",),
    )),
)

#: The ledger's copy, SPEC-COT-007 §3.7, taken from the ENGINE where it defines
#: it. The wording was reviewed and a first draft was rejected as robotic, so
#: there is exactly one copy of it in the product and the CLI prints the same
#: strings the screen draws (Rule 24). What is written below is a load guard
#: with the same text, not a second author.
#:
#: INV-13: the word "coincidence" appears nowhere a reader can see it, on either
#: side of this import. It is a programmer's word for an empty result and is not
#: a reader-facing term.
try:                                                  # noqa: SIM105
    from core.cards_of_truth_data import (
        SPREAD_LABELS as _SPREAD_LABELS,
        NO_MATCH_COPY as _LEDGER_MISS,
        LEDGER_FOOTER as _LEDGER_CLOSE,
        EMPTY_COPY as _LEDGER_EMPTY,
    )
except Exception:                                     # noqa: BLE001
    _SPREAD_LABELS = {}
    #: INV-4: an empty result is NORMAL — 29 of Lorris's first 90 ages carry no
    #: match across all three ledger spreads (61 carry a hit; both pinned in
    #: Q-5, per INV-5a) — so this states a fact and never apologises for one.
    _LEDGER_MISS = "it does not turn up"
    #: The line that keeps the reading on the astrologer's side (INV-3): the
    #: match says the year matters, and only the card says how.
    _LEDGER_CLOSE = "The match says the year matters. The card says how."
    _LEDGER_EMPTY = ("The Year Card does not turn up in any of these spreads. "
                     "That is the ordinary case, not a gap.")

#: The three rows, in the order §3.7 prints them — Ernst's own names for the
#: three spreads. The keys are the scan's keys; the fallback labels are used
#: only when the engine's own table is out of reach.
_LEDGER_ROWS = tuple(
    (key, _SPREAD_LABELS.get(key, fallback)) for key, fallback in (
        ("life", "in your life spread"),
        ("progression", "in the seven year progression"),
        ("year", "in this year's own spread"),
    ))


def _gesture_card_html(pal):
    """:data:`_GESTURE_HELP` as one styled document, in the card palette."""
    ink = QColor(pal["ink"]).name()
    soft = QColor(pal["ink_soft"]).name()
    accent = QColor(pal["accent"]).name()

    parts = []
    for heading, rows in _GESTURE_HELP:
        parts.append(
            f'<p style="margin:14px 0 4px 0;color:{accent};'
            f'font-weight:600;letter-spacing:1px;">{heading}</p>')
        parts.append('<table cellspacing="0" cellpadding="0">')
        for row in rows:
            if len(row) == 1:
                parts.append(
                    f'<tr><td colspan="2" style="color:{soft};'
                    f'padding:2px 0 2px 0;">{row[0]}</td></tr>')
            else:
                parts.append(
                    f'<tr><td style="color:{ink};padding:2px 18px 2px 0;'
                    f'white-space:pre;">{row[0]}</td>'
                    f'<td style="color:{soft};padding:2px 0 2px 0;">'
                    f'{row[1]}</td></tr>')
        parts.append("</table>")
    return "".join(parts)


class _GestureCard(QDialog):
    """What this view responds to, in one small view-owned popup (INV-8).

    Deliberately NOT the app's ``HelpDialog``. That dialog has no open-at-section
    API, no per-view content facility and no route from a chart view to the main
    window's singleton — and it is styled throughout by ``get_theme_colors()``,
    which reads an environment variable nothing in this codebase sets and so
    returns a constant on every theme (SPEC-COT-003 §2.4). "Reuse the existing
    machinery" was not the smaller change; it was three changes in two other
    surfaces.

    Colours come from the view's own card palette, the same dict ``paintEvent``
    reads on every repaint, so this popup is themed by the one live source this
    widget already has rather than by a second one that could disagree with it.
    """

    def __init__(self, parent, pal):
        super().__init__(parent)
        self.setWindowTitle("Cards of Truth — what this view does")
        self.setModal(False)

        label = QLabel(_gesture_card_html(pal), self)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 18)
        layout.addWidget(label)
        self.setStyleSheet(
            f"QDialog {{ background: {QColor(pal['bg1']).name()}; }}"
            f"QLabel {{ color: {QColor(pal['ink']).name()}; }}")
        self.setMinimumWidth(430)


class CardsOfTruthView(QWidget):
    """The Cards of Truth birth spread as a chart view (SPEC-COT-001)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(320, 260))
        self.setAutoFillBackground(False)

        # Same click contract as the other four views, so core_gui_qt wires it
        # to _show_planet_dialog identically.
        self.planet_click_signal = PlanetClickSignal()

        self._chart = None
        self._data = None
        self._error = None
        # The position order is a persisted app setting shared with the Planet
        # Placements dialog, not view-local state (SPEC-COT-001 D-7 v2).
        self._order = read_persisted_order()
        # The active varga (libaditya code, None = natal D-1). Stored so a
        # later order toggle re-assembles under the SAME varga instead of
        # silently dropping back to D-1.
        self._varga_code = None

        #: Which of the two timing families is on (SPEC-COT-007 D-1). Opens on
        #: the progression because that is the family that ships and the one a
        #: reader who never presses either button should get.
        self._family = PROGRESSION
        #: The ledger beside the seal: a list of ``(label, value, hit)`` plus a
        #: closing line, or ``None`` when there is nothing to say. Computed on
        #: assembly, NEVER in the painter — one of its three rows costs a
        #: secondary-progression chart build, and the painter runs on every pan
        #: step.
        self._ledger = None
        self._ledger_close = None
        #: The Year Card of the age on screen, as a card descriptor, or None.
        self._year_card = None
        #: ``(key, cells)`` for the line under the cards — see ``_line_cells``.
        #: Keyed rather than cleared, so it cannot go stale on a chart change.
        self._line_cache = None
        #: Why the quadration screen is not showing, in one short line. A failed
        #: age spread must not blank a working natal one, so it falls back to
        #: natal and says so here rather than through ``_error``.
        self._family_note = None
        # The zoom ladder. The window is which 13 of the 52 progressions the
        # carriage magnifies, and it starts at the birth block because that is
        # where a reader starts. Default level: see _DEFAULT_LEVEL.
        self._level = _DEFAULT_LEVEL
        # Which LINE is open, so a re-assembly of the same person keeps the
        # reader's place and a new person does not inherit it (_sync_ladder_to).
        self._ladder_key = (None, None)
        self._window_start = 0
        # INV-7: a PATH, not an index. What is selectable changes with the
        # level — blocks, then years, then 52-day periods — so one integer
        # would mean three different things depending on where you were, and
        # climbing would leave the wrong kind of number behind.
        self._selected = {"block": None, "year": None, "period": None}
        #: Which progression block is loaded as the WORKING SPREAD, or None for
        #: natal (SPEC-COT-005 INV-2). Independent of ``_level``: navigation and
        #: content are separate axes, so climbing or descending the ladder does
        #: not change what the fourteen cards below it are showing.
        self._loaded_block = None
        #: The natal birth year, captured from the NATAL assembly and never from
        #: a progression one (INV-3). It cannot be recovered afterwards:
        #: ``assemble_progression_spread`` leaves every ``period_year`` None and
        #: carries no natal year anywhere in its payload, so ``_birth_year()``
        #: answers None the moment a block is loaded — and that answer silently
        #: empties all 52 year lines, removes the TODAY needle and resets the
        #: whole ladder on the next re-assembly.
        self._natal_birth_year = None
        #: Whether the press that opened the current click was on a band CELL.
        #: The double click reads this instead of hit-testing (INV-1a): by the
        #: time it arrives the first click has already descended, the figure has
        #: re-solved, and the same coordinates address different data — 48 of 52
        #: rail targets resolve to the wrong block and block 0 to nothing.
        self._press_was_cell = False
        self._band_press = None          # the live band gesture, if any
        self._band_drag_anchor = None    # (x, window_start) while sliding
        self._band_press_at = None       # (x, window_start) at the press
        self._band_slid = False          # a press that turned into a slide
        self._band_geo = None
        self._band_dest = None
        self._band_key = None
        self._band_mode = "full"
        # INV-4. Insertion-ordered, bounded; _band_renders exists so a test
        # can assert the cache HELD rather than assert it was populated.
        self._band_cache = {}
        self._band_renders = 0

        # Zoom/pan. Same knobs and defaults as the QGraphicsView-based views so
        # the F2 cycle feels uniform — but the mechanism is different and better
        # here: zoom multiplies the solved card height, so the whole figure is
        # LAID OUT again at the new size rather than a rasterised scene being
        # scaled. Suits are SVG and the planet art is 2048px, so nothing softens.
        self.zoom_factor = 1.0
        self.min_zoom = 0.4
        self.max_zoom = 4.0
        self.zoom_step = 1.15
        self._pan = QPointF(0.0, 0.0)
        self._drag_from = None

        # Render caches. Suit pixmaps are keyed by colour because the same art
        # serves the red and black suits AND both themes.
        # Suit rasters live in the shared module-level cache (card_suit_art).
        self._icon_cache = {}     # (body_name, px, dpr) -> QPixmap | None

        # Rebuilt on every paint: the hit areas for body chips and the order
        # button. Painted chrome, so hit-testing has to come from the painter.
        self._chip_hits = []
        #: The body dict under the pointer, by IDENTITY. These dicts come from
        #: the assembler and are rebuilt whenever the spread is, so `is` on a
        #: stale one simply never matches and the highlight goes out — which is
        #: the correct behaviour after a reload. Equality would be wrong: two
        #: cards can hold bodies that compare equal.
        self._hover_body = None
        self._help_button_rect = QRectF()
        self._help_button_hover = False
        #: The two family buttons, as ``[(rect, family), ...]``. Painted chrome
        #: in FIGURE coordinates — they live in the right flank of row 1 (D-2),
        #: which is part of the figure and not of the widget's corners — so the
        #: hit rects are rebuilt by the painter exactly as ``_chip_hits`` is.
        self._family_hits = []
        self._family_hover = None
        #: Where the medallion landed, for the hover tooltip that points at the
        #: help card (D-5: the mechanics are read once, and that is where).
        self._seal_rect = QRectF()
        #: The view-owned gesture card (INV-8). Qt owns it once shown; the
        #: reference is dropped again on ``destroyed`` so it can never dangle.
        self._help_popup = None
        self._varga_badge_rect = QRectF()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Live sync: Settings writes cot.planet_order, this view reads it back.
        # Without this the Settings combo persists a value that no open view
        # ever picks up, which reads to the user as "the setting does nothing".
        #
        # WEAK reference: ``on_changed`` holds the callback for the life of the
        # process with no unsubscribe, so a lambda closing over ``self`` pins
        # the whole widget. One dead closure per view is a bounded cost; a
        # pinned view is not.
        _ref = weakref.ref(self)

        def _order_hook(_key, value, _ref=_ref):
            view = _ref()
            if view is not None:
                view._on_order_setting(value)

        self._settings_hook = _order_hook
        try:
            from managers.settings_manager import get_settings
            get_settings().on_changed(ORDER_SETTING_KEY, _order_hook)
        except Exception:                            # noqa: BLE001
            # A view that cannot subscribe still works; it just will not
            # live-update from Settings. Never take the chart tab down for it.
            pass

    # ------------------------------------------------------------------ #
    # Chart plumbing — the update_from_chart convention (SPEC-VIEW-001)
    # ------------------------------------------------------------------ #
    def update_from_chart(self, chart, cot_order=None, varga_code=None, **_kw):
        """Render ``chart``'s birth spread under the active varga.

        ``varga_code`` is the libaditya code from the varga column. The card
        FACES never move with it — they come from the birth date — but the
        occupants do, because each body is filed under its divisional sign lord
        (INV-15 v2).

        ``**_kw`` still swallows ``use_western_names`` / ``ayanamsa_offset`` /
        ``aditya_mode``: the card faces are not sign labels, so the zodiac mode
        does not touch them. Absorbing rather than enumerating also means a new
        kwarg on the shared call site cannot break this view.
        """
        if cot_order is not None:
            self._order = cot_order
        self._varga_code = varga_code

        self._chart = chart
        self._chip_hits = []
        self._hover_body = None

        if chart is None:
            self._data = None
            self._error = None
            self._varga_code = None
            self._natal_birth_year = None
            self._loaded_block = None
            # A gesture in flight does not survive the chart going away.
            # ``clear_chart`` disarms it through ``_sync_ladder_to``; this
            # branch does not go through there, and an armed ``_press_was_cell``
            # is a promise about a spread that no longer exists.
            self._disarm_band_gesture()
            self._ledger = None
            self._ledger_close = None
            self._year_card = None
            self._family_note = None
            self.update()
            return

        # ALWAYS assemble natal first, whatever is loaded. Three things depend
        # on it and none of them can be answered by a progression payload: the
        # ladder's reset key, the natal birth year (INV-3) and the fallback when
        # a block cannot be built.
        try:
            natal = assemble_spread(chart, self._order, self._varga_code)
            self._error = None
        except CardsOfTruthUnavailable as exc:
            # INV-12: the vendored engine has two reachable crash paths (E-1,
            # E-5). Surface them; never let one take down the chart tab.
            natal = None
            self._error = str(exc)
        except Exception as exc:                 # noqa: BLE001 — same boundary
            natal = None
            self._error = f"{type(exc).__name__}: {exc}"

        # INV-3: captured from the NATAL assembly, before anything can load a
        # block over it. A progression payload has no natal year to read back.
        self._natal_birth_year = _natal_year_of(natal)

        # §3.7 / INV-3b: the identity gate runs BEFORE the assembly decision it
        # protects. Assembling first and syncing afterwards is how a stranger's
        # chart arrives already built as block N and then keeps that spread on
        # screen under a reset, natal breadcrumb — the reset clears the ladder
        # but re-assembles nothing. Here the reset clears ``_loaded_block``, and
        # the branch below therefore builds natal.
        #
        # varga, order and zodiac changes all re-assemble the SAME person and
        # must keep the reader's place. The key is the birth card and the birth
        # year, which together are the birth DATE — and the date is exactly what
        # the ladder is a view of, so two natives who share it share the whole
        # line and carrying a selection between them is right, not stale.
        self._sync_ladder_to((natal or {}).get("birth_card"),
                             self._natal_birth_year)

        # INV-11: the loaded block is honoured INSIDE this method, because every
        # lifecycle event that must preserve it arrives here — the F2 view cycle
        # most of all, which fires more often than varga and order together.
        # A load branch anywhere else is dropped by F2 and by nothing else,
        # which is the hardest version of this bug to notice.
        self._data = natal
        self._family_note = None
        if natal is not None and self._family == QUADRATION:
            # INV-12: switching family REBUILDS. The quadration faces are a
            # different deck for a different age, not the progression's faces
            # reinterpreted, so there is no branch here that keeps the payload
            # and relabels it.
            self._data = self._assemble_quadration(chart, natal)
        elif natal is not None and self._loaded_block is not None:
            try:
                self._data = assemble_progression_spread(
                    chart, self._order, self._varga_code, self._loaded_block)
            except Exception as exc:             # noqa: BLE001 — INV-12 boundary
                # Fall back to the natal spread that is already in hand rather
                # than to an error page: the reader asked for a block, not for
                # the chart tab to go blank.
                self._loaded_block = None
                self._error = None
                _ = exc
        self._refresh_ledger()
        self.update()

    # ------------------------------------------------------------------ #
    # The two timing families (SPEC-COT-007 §3.6)
    # ------------------------------------------------------------------ #
    @property
    def family(self):
        return self._family

    def set_family(self, family):
        """Switch timing family. Returns whether anything changed.

        **INV-12 — this REBUILDS, it never reinterprets.** Everything on the
        screen is a different fact afterwards: the fourteen faces come from a
        different deck, the line under them runs 90 ages instead of 52
        progressions, the rule counts card days instead of years, and the seal
        and its ledger only exist on one side. So the ladder is reset with it —
        a selection made on a 52-cell line is not a place on a 90-cell one, and
        carrying the index across would land the reader somewhere plausible and
        wrong rather than nowhere.
        """
        if family not in FAMILY_ORDER or family == self._family:
            return False
        self._family = family
        self._level = _DEFAULT_LEVEL
        self._window_start = 0
        self._selected = {"block": None, "year": None, "period": None}
        self._loaded_block = None
        self._disarm_band_gesture()
        self._ledger = None
        self._ledger_close = None
        self._year_card = None
        self._clamp_pan()
        self._rebuild()
        return True

    def toggle_family(self):
        """Switch to the other family. The keyboard ``C`` and the remote
        ``cot_family`` command both come through here (WI-12; the key moved
        F->C when fullscreen claimed F app-wide, SPEC-FSV-001)."""
        return self.set_family(
            QUADRATION if self._family == PROGRESSION else PROGRESSION)

    def _family_spec(self):
        return family_spec(self._family)

    def _line_count(self):
        """Cells ACTUALLY on the line for the open family (WI-4 / DEF-3).

        90 is the quadration's nominal — the 90th quadration is the last one
        that differs from the first —
        and 52 the progression's. But ``FAMILIES["line"]`` is only the DECLARED
        figure. When the quadration walk is unavailable ``_line_cells`` draws
        the 52 progression blocks instead (a band that cannot draw its family
        draws the one that ships), and a count that kept saying 90 while 52
        cells were on screen desynced the hit test from the data: clicks landed
        up to 38 ages off the end, the window clamp stopped 38 short, and
        ``_active_age`` clamped to 89 on a 52-cell line. B-Major-3.

        So the count follows the data: the LENGTH of the drawn line. The memo in
        ``_line_cells`` makes this free after the first paint. Only when there is
        no spread yet (nothing to measure) does it fall back to the nominal.
        """
        data = self._data
        birth_card = data.get("birth_card") if data else None
        if birth_card:
            try:
                return len(self._line_cells(birth_card, self._natal_birth_year))
            except Exception:                        # noqa: BLE001
                pass
        try:
            return int(self._family_spec()["line"])
        except Exception:                            # noqa: BLE001
            return cot_ladder.LINE_BLOCKS

    def _deepest_wired(self):
        """The deepest level with data behind it, for the OPEN family (§3.3).

        Two levels on the quadration and two wired on the progression — the same
        number for two different reasons, which is exactly why it is asked per
        family and not shared: the quadration HAS no third level (the seven
        52-card-day periods are already row 2 of the spread), while the
        progression has two more that are simply not wired yet.
        """
        func = getattr(cot_ladder, "deepest_wired", None)
        if func is not None:
            try:
                return func(**self._family_kw(func))
            except Exception:                        # noqa: BLE001
                pass
        return _DEEPEST_WIRED

    def _window_cells(self, level=None):
        """Cells the open level shows as a WINDOW of the line, or ``None``.

        45 at the quadration's rail, 13 at either carriage, ``None`` at the
        progression's rail, which holds all 52 and never slides. Everything that
        clamps, follows or slides the window reads this rather than the family's
        ``window``: that key is the BRACKET's width on the map, and the two
        stopped being the same number when the rail gained a window of its own
        (SPEC-COT-007 §3.3c).
        """
        func = getattr(cot_ladder, "window_cells", None)
        if func is None:                    # pre-§3.3c ladder: only the carriage
            return (cot_ladder.WINDOW_CELLS
                    if (level or self._level) == cot_ladder.CARRIAGE else None)
        try:
            return func(self._level if level is None else level,
                        **self._family_kw(func))
        except Exception:                            # noqa: BLE001
            return None

    def _clamped_window(self):
        """``_window_start`` as the OPEN level can honour it. Changes nothing.

        The reading half of the clamp, and separate from the writing half
        because the hit test needs the number and must not have opinions: a
        query that moves the window would move it on a hover the moment anyone
        adds one.
        """
        cells = self._window_cells()
        if cells is None:
            # A row with no window ignores the value entirely, and the reader's
            # place on the carriage is theirs to come back to (INV-7,
            # "climbing keeps the window").
            return self._window_start
        return max(0, min(self._window_start, self._line_count() - cells))

    def _clamp_window(self):
        """Pin ``_window_start`` inside the OPEN level's window. Returns it.

        A level change moves the clamp: the carriage may sit at 77 of 90 and the
        rail below it can only reach 45, so a climb leaves a start the rail
        cannot honour. ``band_model`` clamps its own copy, so the band draws the
        right cells either way — and ``_hit_band`` reads THIS one, so without
        this the picture and the hit test disagree by up to 32 ages with nothing
        on screen to say so.
        """
        self._window_start = self._clamped_window()
        return self._window_start

    def _unit_years(self):
        """Years one cell of the line covers: 7 on the progression, 1 on an age."""
        try:
            return max(1, int(self._family_spec()["unit_years"]))
        except Exception:                            # noqa: BLE001
            return cot_ladder.BLOCK_YEARS

    def _active_age(self):
        """The age the quadration screen is showing, or ``None`` off it.

        The loaded cell when there is one; otherwise the age the native is
        living, so switching family lands on something the reader has a use for
        rather than on age 0. ``is not None`` throughout — age 0 is falsy and it
        is a real, reachable age.
        """
        if self._family != QUADRATION:
            return None
        age = self._loaded_block
        if age is None:
            age = self._current_age()
        if age is None:
            age = 0
        return max(0, min(self._line_count() - 1, age))

    def _birth_date(self):
        """The LOCAL calendar date of birth, or ``None``.

        ``usr*`` accessors only, never ``JulianDay.year()`` and friends: that
        object answers year and month in the local frame and day and hour in UTC
        under the same default argument (the E-6 defect, bead td-tvhp), so a
        date assembled from the mixed set is wrong by a day around midnight and
        right the rest of the time — which is the worst way for it to be wrong.
        """
        chart = self._chart
        if chart is None:
            return None
        try:
            jd = chart.context.timeJD
            return _date(int(jd.usryear()), int(jd.usrmonth()), int(jd.usrday()))
        except Exception:                            # noqa: BLE001
            return None

    def _assemble_quadration(self, chart, natal):
        """The Age-N spread, or the natal payload with a note saying why not.

        A quadration that cannot be built must not blank a natal spread that
        can: the reader still has fourteen real cards in front of them and the
        honest thing is to keep drawing those and say the age spread is missing.
        ``_error`` is reserved for the case where there is nothing to draw at
        all, because it replaces the whole figure with a message.
        """
        if assemble_quadration_spread is None:
            self._family_note = "age spread not available in this build"
            return natal
        try:
            return assemble_quadration_spread(
                chart, order=self._order, varga_code=self._varga_code,
                age=self._active_age())
        except Exception as exc:                     # noqa: BLE001 — INV-12
            self._family_note = f"age spread unavailable: {type(exc).__name__}"
            return natal

    # ---- the ledger (§3.2, §3.7) -------------------------------------- #
    def _refresh_ledger(self):
        """Where the Year Card falls, across the three spreads (§3.2, §3.7).

        Read off the PAYLOAD, not recomputed. ``assemble_quadration_spread``
        already runs the scan — it is the only caller that holds all three
        spreads at once, and one of the three is a progression it builds
        anyway — and it already formats every string a person sees. A second
        scan here would be a second source for the same fourteen comparisons
        and a second place for the copy to drift out of §3.7.

        Built on ASSEMBLY rather than in the painter regardless, because the
        painter runs on every pan step.
        """
        self._ledger = None
        self._ledger_close = None
        self._year_card = None
        if self._family != QUADRATION or self._data is None:
            return
        data = self._data
        self._year_card = data.get("year_card_face") or None
        scan = data.get("coincidences")
        if not scan:
            return
        self._ledger, self._ledger_close = self._ledger_lines(scan)

    def _ledger_lines(self, ranked):
        """``(rows, closing line)`` from the scan's ranked output.

        Three rows always, in the fixed printing order of :data:`_LEDGER_ROWS`.
        The scan returns them RANK-sorted, which is right for reading off the
        strongest match and wrong for a ledger: rows that reorder themselves as
        the age changes cannot be read down. So the order here is fixed and the
        rank is used only to choose the closing line.

        Every miss is printed (INV-4). A ledger that dropped its empty rows
        would read as if the scan had not run, and an empty result is the
        ordinary case — 29 of Lorris's first 90 ages carry no match across all
        three spreads (61 carry a hit; both figures pinned in Q-5, per INV-5a).
        """
        found = {}
        for entry in ranked or ():
            if isinstance(entry, dict):
                found[entry.get("key")] = entry

        rows = []
        for key, fallback_label in _LEDGER_ROWS:
            entry = found.get(key) or {}
            label = entry.get("label") or fallback_label
            names = list(entry.get("positions") or ())
            if not names:
                rows.append((label, _LEDGER_MISS, False))
            else:
                rows.append((label, "it lands on " + " and ".join(names), True))

        best = next((e for e in ranked or ()
                     if isinstance(e, dict) and e.get("rank") is not None), None)
        if best is None:
            return rows, _LEDGER_EMPTY
        copy = best.get("copy")
        if not copy:
            return rows, _LEDGER_CLOSE
        return rows, f"{copy}\n{_LEDGER_CLOSE}"

    def _sync_ladder_to(self, birth_card, birth_year):
        """Reset the ladder if this is a different line from the one open.

        WI-5 (B-Major-4): the key carries the full birth DATE, not just the
        card and year. Two natives can share a birth card and a birth year and
        differ only in month or day; a (card, year) key answered the same for
        both, so loading the second inherited the first's level, window and
        selection. The line cache at ``_line_cells`` already keyed on
        ``_birth_date()`` — this matches it. ``None`` (a chart with no readable
        date) is a stable component: the same None does not thrash, a different
        card still resets.
        """
        key = (birth_card, birth_year, self._birth_date())
        if key == self._ladder_key:
            return
        self._ladder_key = key
        self._level = _DEFAULT_LEVEL
        self._window_start = 0
        self._selected = {"block": None, "year": None, "period": None}
        # INV-11: a different person clears the LOADED block too, and clearing
        # it here — before ``update_from_chart`` decides what to assemble — is
        # what forces that decision back to natal.
        self._loaded_block = None
        self._disarm_band_gesture()
        # A different person is a different Year Card, a different ledger and a
        # different progression. Keyed caches would be safer still, but these
        # are keyed on a BLOCK index, which means the same key answers for two
        # natives — so they are cleared rather than keyed.
        self._ledger = None
        self._ledger_close = None
        self._year_card = None
        self._family_note = None
        self._clamp_pan()          # the default level may not be the open one

    def clear_chart(self):
        """Drop the spread and render the empty grid.

        Needed as its own entry point because ``_update_all_chart_views``
        returns before any fan-out when ``active_chart`` is None, so closing the
        last chart would otherwise leave the previous person's spread on screen
        (SPEC-COT-001 §4.8).
        """
        self._chart = None
        self._data = None
        self._error = None
        self._varga_code = None
        self._chip_hits = []
        self._hover_body = None
        self._natal_birth_year = None
        self._sync_ladder_to(None, None)
        self.update()

    def ensure_visible(self):
        """Parity with the QGraphicsView-based views' fit call — a repaint.

        Deliberately does NOT reset the zoom: this is called on every chart
        update and on every F2 landing, and the sibling views keep a manual zoom
        across those too (their ``user_zoomed`` flag). Use ``reset_zoom()`` (or
        press 0) to go back to fit.
        """
        self.update()

    # ------------------------------------------------------------------ #
    # Position order — one persisted setting, three surfaces
    # ------------------------------------------------------------------ #
    @property
    def order(self):
        return self._order

    def set_order(self, order, persist=True):
        """Switch the position order and, by default, persist the choice.

        ``persist`` is False when the change CAME from the setting, so the
        write-back does not re-enter the change callback.
        """
        if order not in ORDER_LABELS or order == self._order:
            return
        self._order = order
        if persist:
            try:
                from managers.settings_manager import get_settings
                get_settings().set(ORDER_SETTING_KEY, order)
            except Exception:                        # noqa: BLE001
                pass                                 # display still switches
        self._rebuild()

    def toggle_order(self):
        """What the corner button does: flip between the two orders."""
        self.set_order("vedic" if self._order == "solar_system" else "solar_system")

    def _on_order_setting(self, value):
        """The setting changed elsewhere (Settings > Zodiac & Calculation)."""
        if value in ORDER_LABELS and value != self._order:
            self._order = value
            self._rebuild()

    def _rebuild(self):
        """Re-assemble the spread for the current chart under the current order."""
        if self._chart is None:
            self.update()
            return
        self.update_from_chart(self._chart, varga_code=self._varga_code)

    # ------------------------------------------------------------------ #
    # Zoom — same knobs as the QGraphicsView-based views
    # ------------------------------------------------------------------ #
    def _set_zoom(self, new_zoom, anchor=None):
        """Apply a zoom, keeping ``anchor`` (widget coords) under the cursor.

        Anchoring is what makes wheel-zoom feel like the other views. Without
        it the figure grows from its centre and whatever you were pointing at
        slides away.
        """
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        if abs(new_zoom - self.zoom_factor) < 1e-9:
            return
        if anchor is not None:
            # Keep the anchor's position within the FIGURE fixed: the figure
            # scales about the widget centre, so the offset from that centre
            # scales by the same ratio and the pan absorbs the difference.
            ratio = new_zoom / self.zoom_factor
            centre = QPointF(self.width() / 2.0, self.height() / 2.0)
            offset = QPointF(anchor) - centre - self._pan
            self._pan -= offset * (ratio - 1.0)
        self.zoom_factor = new_zoom
        self._clamp_pan()
        self.update()

    def zoom_in(self):
        self._set_zoom(self.zoom_factor * self.zoom_step)

    def zoom_out(self):
        self._set_zoom(self.zoom_factor / self.zoom_step)

    def reset_zoom(self):
        """Back to fit, centred."""
        self.zoom_factor = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def wheelEvent(self, event):
        """Wheel/trackpad zoom, matching wheel_view's cross-platform handling.

        pixelDelta on macOS (angleDelta is synthetic and large there), kinetic
        momentum filtered on Wayland so zoom stops with the gesture, and an
        exponential step so two half-clicks equal one full click.
        """
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            event.accept()
            return

        if event.hasPixelDelta():
            raw = event.pixelDelta().y()
            if raw == 0:
                event.accept()
                return
            steps = raw * 0.02
        else:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            steps = delta / 120.0

        if event.isInverted():
            steps = -steps

        step = self.zoom_step ** abs(steps)
        target = self.zoom_factor * step if steps > 0 else self.zoom_factor / step
        self._set_zoom(target, anchor=event.position())
        event.accept()

    def keyPressEvent(self, event):
        """+/= zoom in, - zoom out, 0 reset — same keys as the other views.

        Escape unwinds in three stages (SPEC-COT-005 INV-4, D-2):

        1. a block is loaded -> return the fourteen cards to natal, leaving the
           ladder exactly where it is;
        2. else above the rail -> climb one level;
        3. else NOT CONSUMED. The rule is narrow and sufficient: do not swallow
           a key you did not act on. Escape is also conditional on focus — with
           the planet dialog or the gesture card focused it never arrives here
           at all — and that is correct, not a defect.

        Arrows are taken unmodified only, so Ctrl+Left and friends still belong
        to whoever owns them.

        Plain ``C`` toggles the timing family (DEF-4), once per physical press;
        it acts only when a spread is loaded and autorepeat is filtered.
        (``F`` was the original binding; it was ceded to the app-wide fullscreen
        QAction — SPEC-FSV-001 — because a WindowShortcut fires before this
        keyPressEvent and would otherwise steal the family toggle. SPEC-COT-007.)
        """
        key = event.key()
        plain = event.modifiers() in (Qt.KeyboardModifier.NoModifier,
                                      Qt.KeyboardModifier.KeypadModifier)
        if key == Qt.Key.Key_Escape:
            # Content before navigation: the spread is what the reader is
            # looking AT, the ladder is where they are looking FROM.
            if self.unload_block() or (self._level > cot_ladder.RAIL
                                       and self._climb()):
                event.accept()
                return
        if plain and self._data and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._step_selection(1 if key == Qt.Key.Key_Right else -1)
            event.accept()
            return
        if plain and self._data and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self._selected[_SELECT_KEY[self._level]]
            if index is not None and self._descend(index):
                event.accept()
                return

        if (plain and self._data and key == Qt.Key.Key_C
                and not event.isAutoRepeat()):
            # DEF-4 / C-4: the family switch, off the keyboard. Bound to ``C``
            # (was ``F`` until the fullscreen QAction claimed F app-wide; a
            # WindowShortcut fires ahead of this handler, so the toggle had to
            # move — SPEC-FSV-001, SPEC-COT-007). keyPressEvent
            # only fires on the focused widget, so "the view has focus" is
            # already the precondition; the ``_data`` guard is the other half
            # (nothing to switch on an empty view). ONE flip per physical press
            # — ``isAutoRepeat`` filters the held-key stream that would
            # otherwise walk the families back and forth many times a second.
            # ``toggle_family`` -> ``set_family`` is a no-op when the family
            # does not change, so the path is idempotent-safe; it does not go
            # through the mouse double-click swallow list, so INV-11 is not in
            # play here.
            self.toggle_family()
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            event.accept()
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_out()
            event.accept()
        elif event.key() == Qt.Key.Key_0:
            self.reset_zoom()
            event.accept()
        else:
            super().keyPressEvent(event)

    def refresh_theme(self):
        """Repaint under the new palette.

        Nothing to invalidate: both raster caches are COLOUR-KEYED, so a new
        palette is automatically a new key. The old tints age out through the
        shared cache bound rather than being dropped here — which also means
        switching back and forth between themes hits warm entries.
        """
        self.update()

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #
    def _ruler(self):
        """The band height for the level currently open (INV-2).

        Family-aware where the ladder is: both families give the rail 0.54h and
        the carriage 0.88h today, so this changes nothing on either — but the
        height is the family's to state, not this view's to assume.
        """
        return cot_ladder.band_height(
            self._level, **self._family_kw(cot_ladder.band_height))

    def _fit_height(self):
        """The card height at which the whole figure exactly fits, before zoom."""
        margin = 18
        avail_w = max(1, self.width() - 2 * margin)
        avail_h = max(1, self.height() - 2 * margin)
        # Both budgets are linear in h, so this is a direct solve, not a search.
        h = min(avail_h / _h_units(self._ruler()),
                avail_w / _W_UNITS, _MAX_H * get_scale_factor())
        return max(h, 34.0)                       # stay drawable in a tiny window

    def _metrics(self):
        """Solve the whole layout from the widget rect, the zoom and the pan.

        Returns ``(h, w, gap_y, gap_x, origin_x, origin_y)`` where ``h`` is the
        card height every other dimension is expressed against.

        Zoom enters here and NOWHERE else. Because it multiplies ``h``, the
        figure is re-laid-out and re-rendered at the new size on every step —
        the suits re-rasterise from SVG, the text re-lays out, the rounded rects
        re-stroke. That is why it does not soften the way scaling a rasterised
        QGraphicsScene does.
        """
        h = self._fit_height() * self.zoom_factor
        w = h / _ASPECT
        gap_y, gap_x = h * _GAP_Y, h * _GAP_X
        fig_w = GRID_COLS * w + (GRID_COLS - 1) * gap_x
        fig_h = h * _h_units(self._ruler())

        origin_x = (self.width() - fig_w) / 2.0 + self._pan.x()
        origin_y = (self.height() - fig_h) / 2.0 + self._pan.y()
        return h, w, gap_y, gap_x, origin_x, origin_y

    def _clamp_pan(self):
        """Keep the figure reachable.

        Panning is only meaningful once the figure is larger than the viewport;
        on each axis the offset is bounded by the overflow, so the figure can
        never be dragged off screen and lost. At or below fit, the axis is
        pinned to centred — otherwise a stray drag would leave the spread
        off-centre with no visual cue that it moved.
        """
        h = self._fit_height() * self.zoom_factor
        fig_w = GRID_COLS * (h / _ASPECT) + (GRID_COLS - 1) * h * _GAP_X
        fig_h = h * _h_units(self._ruler())
        slack_x = max(0.0, (fig_w - self.width()) / 2.0 + 18)
        slack_y = max(0.0, (fig_h - self.height()) / 2.0 + 18)
        self._pan.setX(max(-slack_x, min(slack_x, self._pan.x())))
        self._pan.setY(max(-slack_y, min(slack_y, self._pan.y())))

    def _cell_rect(self, row, col, m):
        """Bounding rect of grid cell (row, col), both 1-based."""
        h, w, gap_y, gap_x, ox, oy = m
        x = ox + (col - 1) * (w + gap_x)
        if row == 1:
            return QRectF(x, oy, w, h * _ROW1)
        # The ruler band sits between row 1 and row 2 (SPEC-COT-002 §4.3).
        # Every other coordinate in this view — the lattice, the wash, the pan
        # clamp — derives from _cell_rect or from _h_units, so inserting it here
        # moves the whole figure together. Nothing carries a duplicated row
        # offset that could be left behind pointing at where a card used to be.
        #
        # The row offset is a TABLE LOOKUP (INV-9). The arithmetic that used to
        # stand here pitched the rows evenly by construction, so the tuck was
        # not expressible in it at all without a special case.
        dh, dgap = _ROW_OFFSET[row]
        y = (oy + h * _ROW1 + gap_y + h * self._ruler()
             + dh * h + dgap * gap_y)
        return QRectF(x, y, w, h)

    def _card_rect(self, entry, m):
        """Drawing rect of a card — the birth card is enlarged inside its cell."""
        cell = self._cell_rect(entry["row"], entry["col"], m)
        if not entry["is_base"]:
            return cell
        h, w = m[0], m[1]
        bw, bh = w * _BASE_SCALE, h * _BASE_SCALE
        return QRectF(cell.center().x() - bw / 2, cell.center().y() - bh / 2, bw, bh)

    # ------------------------------------------------------------------ #
    # Painting
    # ------------------------------------------------------------------ #
    def paintEvent(self, _event):
        pal = _PALETTE["light" if is_light_theme() else "dark"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        self._paint_ground(p, pal)

        if self._error:
            self._paint_message(p, pal, self._error)
            p.end()
            return

        m = self._metrics()
        entries = self._data["cards"] if self._data else self._empty_entries()

        self._paint_lattice(p, pal, m)
        self._paint_ruler(p, pal, m, entries)
        self._paint_progression_band(p, pal, m, entries)
        # Row 1's flanks, BEFORE the cards. They cannot collide — only column 4
        # of row 1 is occupied — but if the birth card's enlargement ever
        # reached one of them, the card is the figure and must win.
        self._paint_seal(p, pal, m)
        self._paint_family_buttons(p, pal, m)
        self._chip_hits = []
        for entry in entries:
            self._paint_card(p, pal, m, entry, live=self._data is not None)

        # Chrome LAST and in widget coordinates: it must not zoom or pan with
        # the figure, or it would sail off screen at 4x.
        self._paint_varga_badge(p, pal)
        self._paint_help_button(p, pal)

        p.end()

    def _empty_entries(self):
        """The 14 cells with no data — the cross silhouette, kept structural."""
        return [{"index": i, "row": r, "col": c, "is_base": i == 0,
                 "occupied": False, "bodies": [], "position": "",
                 "rank_display": "", "suit_name": None, "is_red": False}
                for i, (r, c) in sorted(GRID.items())]

    def _paint_ground(self, p, pal):
        """The table: a soft pool of light under the figure."""
        rect = QRectF(self.rect())
        p.fillRect(rect, QColor(pal["bg0"]))

        g = QRadialGradient(rect.center().x(), rect.height() * 0.30,
                            max(rect.width(), rect.height()) * 0.72)
        g.setColorAt(0.0, QColor(pal["bg1"]))
        g.setColorAt(1.0, QColor(pal["bg0"]))
        p.fillRect(rect, QBrush(g))

        glow = QRadialGradient(rect.center().x(), rect.height() * 0.40,
                               max(rect.width(), rect.height()) * 0.38)
        glow.setColorAt(0.0, pal["glow"])
        glow.setColorAt(1.0, _rgba((0, 0, 0), 0.0))
        p.fillRect(rect, QBrush(glow))

    def varga_badge_label(self):
        """``"D-9 · Navamsa"``, or ``None`` on the natal spread.

        Split out of the painter so the wording is reachable without a repaint:
        the two reverse variants carry sentinel GUI numbers (1010, 2424) and a
        raw ``str(number)`` would name divisions that do not exist ("D-1010").
        ``varga_display_label`` is the same source the varga column reads, so
        the badge and the column cannot spell a division differently.
        """
        code = self._data.get("varga_code") if self._data else None
        if code is None:
            return None
        from core.varga_codes import (
            from_libaditya_varga_code, get_varga_name, varga_display_label,
        )
        number = from_libaditya_varga_code(code)
        return f"D-{varga_display_label(number)} · {get_varga_name(number)}"

    def _paint_varga_badge(self, p, pal):
        """Which division the placements follow, bottom-LEFT.

        Not decoration: with the varga wired in, the same fourteen faces can
        hold completely different bodies and nothing on the figure would say
        why. Mirrors the order pill on the right, and stays quiet on D-1 —
        the natal spread is the baseline and needs no badge shouting at you.
        """
        label = self.varga_badge_label()
        if label is None:
            self._varga_badge_rect = QRectF()
            return

        font = self._label_font(max(8.0, 10.0 * get_scale_factor()), spacing=112)
        fm = QFontMetrics(font)
        pad_x, pad_y, margin = 13, 7, 14
        width = fm.horizontalAdvance(label) + 2 * pad_x
        height = fm.height() + 2 * pad_y
        rect = QRectF(margin, self.height() - height - margin, width, height)
        self._varga_badge_rect = rect

        accent = QColor(pal["accent"])
        p.save()
        p.setPen(QPen(_rgba((accent.red(), accent.green(), accent.blue()), .45), 1))
        fill = QColor(pal["face_up"][0])
        fill.setAlphaF(0.86)
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(rect, height / 2.0, height / 2.0)
        p.setFont(font)
        p.setPen(QPen(accent))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.restore()

    def _paint_help_button(self, p, pal):
        """The gesture card's opener, TOP right (INV-8).

        Painted chrome owning its own hit rect, exactly as the order button does
        at the other corner. It exists because the view now carries two
        gestures, four levels and five keys, and not one of them is
        discoverable: a double click that silently changes what fourteen cards
        mean is the least discoverable of the lot.
        """
        size = max(9.0, 12.0 * get_scale_factor())
        font = self._label_font(size, spacing=100)
        fm = QFontMetrics(font)
        side = max(fm.height() + 9.0, 22.0)
        margin = 14
        rect = QRectF(self.width() - side - margin, margin, side, side)
        self._help_button_rect = rect

        accent = QColor(pal["accent"])
        p.save()
        p.setPen(QPen(pal["ink_faint"] if self._help_button_hover
                      else pal["rail_line"], 1))
        fill = QColor(pal["face_up"][0])
        fill.setAlphaF(0.94 if self._help_button_hover else 0.80)
        p.setBrush(QBrush(fill))
        p.drawEllipse(rect)
        p.setFont(font)
        p.setPen(QPen(accent if self._help_button_hover else pal["ink_soft"]))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
        p.restore()

    def _open_help(self):
        """Show the gesture card, or raise the one already up.

        Rule 18: once shown, Qt owns the dialog. ``WA_DeleteOnClose`` plus a
        ``destroyed`` handler means the Python reference is dropped by the same
        event that frees the C++ object, so it can never be a stale pointer —
        and a fresh dialog per open picks up the current theme with no restyle
        path to keep in sync.
        """
        if self._help_popup is not None:
            self._help_popup.raise_()
            self._help_popup.activateWindow()
            return
        pal = _PALETTE["light" if is_light_theme() else "dark"]
        dialog = _GestureCard(self, pal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._forget_help)
        self._help_popup = dialog
        dialog.show()

    def _forget_help(self, *_args):
        self._help_popup = None

    def _paint_message(self, p, pal, text):
        """INV-12 — the visible in-view failure state."""
        f = QFont()
        f.setPointSizeF(max(9.0, 11.0 * get_scale_factor()))
        p.setFont(f)
        p.setPen(QPen(pal["ink_soft"]))
        p.drawText(self.rect().adjusted(40, 0, -40, 0),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                   f"Cards of Truth unavailable for this chart.\n\n{text}")

    def _paint_lattice(self, p, pal, m):
        """Hairlines that run BEHIND the cards and show only in the gaps.

        They stitch the disconnected stubs of rows 3-5 back onto the row-2 bar
        so fourteen tiles read as one figure. Purely compositional — the threads
        carry no data.
        """
        h = m[0]

        def cx(col):
            return self._cell_rect(2, col, m).center().x()

        def cy(row):
            return self._cell_rect(row, 4, m).center().y()

        p.save()
        p.setPen(QPen(pal["thread"], 1))
        p.drawLine(QPointF(cx(1), cy(2)), QPointF(cx(7), cy(2)))          # the bar
        p.drawLine(QPointF(cx(4), cy(1)), QPointF(cx(4), cy(5)))          # the stem
        p.drawLine(QPointF(cx(3), cy(2)), QPointF(cx(3), cy(5)))
        p.drawLine(QPointF(cx(5), cy(2)), QPointF(cx(5), cy(5)))
        p.setPen(QPen(pal["thread_soft"], 1))
        p.drawLine(QPointF(cx(3), cy(3)), QPointF(cx(5), cy(3)))          # the ties
        p.drawLine(QPointF(cx(3), cy(5)), QPointF(cx(5), cy(5)))
        p.restore()

        # A wash behind row 2 — the lit bar of the spread.
        # Drawn as a CIRCULAR gradient squashed by a painter transform, not as
        # a radial gradient stretched over a wide ellipse: the latter reaches
        # zero alpha at the horizontal edge while still bright at the top and
        # bottom, which leaves a visible arc cutting across the cards.
        bar = self._cell_rect(2, 1, m).united(self._cell_rect(2, 7, m))
        wash = QRectF(bar.adjusted(-h, -h * 0.5, h, h * 0.5))
        radius = wash.height() / 2.0
        fade = QColor(pal["wash"])
        mid = QColor(fade)
        mid.setAlphaF(fade.alphaF() * 0.38)
        g = QRadialGradient(QPointF(0, 0), radius)
        g.setColorAt(0.0, fade)
        g.setColorAt(0.55, mid)
        g.setColorAt(1.0, _rgba((0, 0, 0), 0.0))

        p.save()
        p.translate(wash.center())
        p.scale(wash.width() / wash.height(), 1.0)
        p.setBrush(QBrush(g))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        p.restore()

    def _ruler_label_top(self, m, entries, fm):
        """Where the ruler's year row starts, or ``None`` when it does not fit.

        The birth card sits directly above the ruler and is drawn ENLARGED
        (``_BASE_SCALE``), so it reaches lower into the gap than its cell does.
        The ruler paints before the cards, which means an overlap is not a
        visible collision — the card simply covers the year, and the middle
        number of seven goes missing with nothing on screen to say so.

        The squeeze is not a small-window artefact of the layout: every other
        measurement scales with ``h``, but the font has a floor of 8px. Below
        about ``h = 55`` the text stops shrinking while the gap keeps closing,
        and at the widget's 320x260 minimum the row lands ~2px inside the card.

        Returning ``None`` drops the whole year row rather than the one number
        that would be hidden. A gap in a seven-year sequence reads as data;
        a rule with seven ticks and no numbers still says "seven periods, this
        way round", and every card repeats its own year in its corner
        (SPEC-COT-002 D-5), so nothing is actually lost.
        """
        h = m[0]
        row2 = self._cell_rect(2, 1, m).united(self._cell_rect(2, 7, m))
        # The mockup's own slot for this row: 0.244h above the row-2 card tops,
        # which puts it between the rule below and the band's caption line
        # above. Before the band existed this row floated on the font height and
        # drifted upward as the text hit its 8px floor; now it has a fixed berth
        # and the thing it must not collide with is the caption, not the card.
        top = row2.top() - h * cot_ladder.BAND["year_top"]
        base = next((e for e in entries if e.get("is_base")), None)
        if base is not None and top < self._card_rect(base, m).bottom():
            return None
        return top

    @staticmethod
    def _ruler_labels(entries):
        """What the rule writes over each row-2 card: ``{col: (main, sub)}``.

        **The rule's UNITS follow the family** (§3.4, Q-12). The seven positions
        never change, but what they measure does: 52-year periods counted in
        calendar years on the natal and progressed spreads, and the seven
        52-CARD-DAY periods of one year on a quadration, which are dates and not
        years. So this reads a string field first and falls back to the two
        numeric ones, rather than formatting a year and hoping.

        Read in this order and each one is a different fact:

        ``ruler_label``  the assembler wrote the axis itself. A quadration's
                         "22 FEB 1994" cannot be reconstructed from a year, and
                         a year is not the unit it counts.
        ``ruler_year``   SPEC-COT-005 §3.7 / D-4 — a loaded progression block
                         relabels the rule with its own seven calendar years,
                         in their own field precisely so ``_paint_year`` does
                         not also print them in the card corners.
        ``period_year``  the natal spread's 52-year periods.

        Joined on COL, never on list position: index 0 is the base card in row
        1, so iterating ``cards[:7]`` shifts the whole row by one.
        """
        out = {}
        for e in entries:
            if e.get("row") != 2:
                continue
            label = e.get("ruler_label")
            sub = e.get("ruler_sublabel")
            if not label and e.get("period_start") is not None:
                # A quadration's seven 52-CARD-DAY periods. Dates, not years,
                # and they travel in their own keys precisely because
                # ``period_year`` counts 52-YEAR periods and the card corner
                # draws that one (SPEC-COT-005 D-4).
                label = _date_label(e["period_start"])
                index = e.get("period_index")
                if sub is None and index is not None:
                    sub = f"PERIOD {index + 1}"
            if not label:
                year = e.get("ruler_year")
                if year is None:
                    year = e.get("period_year")
                # A year is never 0 — but the same filter shape holds an AGE
                # elsewhere in this file and 0 is falsy, so it stays `is None`.
                label = None if year is None else str(year)
            if label:
                out[e["col"]] = (label, sub or None)
        return out

    def _period_ruler_shows(self, years):
        """Whether the dated period ruler draws right now (D-10, WI-7 follow-up).

        The other half of "one ruler at a time". The ruler draws when there ARE
        periods to show and either:

        * the family has no idle decade marks (the progression, ``marks_idle_only``
          False) — its ruler is the only timeline and always draws; or
        * an Age-N spread is descended (``_loaded_block`` set) — the quadration's
          dated ruler is the LOADED reference.

        On the quadration WHILE NOTHING IS DESCENDED, the decade marks are the
        single timeline (D-10 calls them "the band's idle year reference"), so the
        ruler stands down. This is the exact mirror of the band's ``suppress_marks``
        (``marks_idle_only and loaded``): the marks show iff the ruler does not.
        WI-7 wired only the marks side, so the idle quadration drew BOTH — the bug
        this closes.
        """
        if not years:
            return False
        if self._family_spec().get("marks_idle_only") and self._loaded_block is None:
            return False
        return True

    def _paint_ruler(self, p, pal, m, entries):
        """The 52-year period ruler across the head of row 2.

        The seven years are ONE sequence stepping 52 years from the birth year,
        so they are drawn once as a sequence rather than seven times as seven
        numbers: a rule, a tick centred on each card, a leader down to it, and a
        marked origin on the birth year (SPEC-COT-002 §4.3, D-5). Each card also
        repeats its own year — the ruler answers "when does this row run", the
        card answers for itself.

        Row 2 is evenly pitched, so a tick centred on ``_cell_rect(2, col)`` is
        centred on that card by construction. No per-card arithmetic, and no way
        for the ticks to drift out of register with the cards if the grid is
        ever re-solved.
        """
        years = self._ruler_labels(entries)
        if not self._period_ruler_shows(years):
            return                                  # empty grid, or D-10 idle

        h = m[0]
        row2 = self._cell_rect(2, 1, m).united(self._cell_rect(2, 7, m))
        bar_y = row2.top() - h * 0.115
        accent = QColor(pal["accent"])

        p.save()
        # the rule, fading out at both ends so it reads as an axis rather than
        # as a box edge
        g = QLinearGradient(QPointF(row2.left() - h * 0.3, 0),
                            QPointF(row2.right() + h * 0.3, 0))
        edge = QColor(accent); edge.setAlphaF(0.0)
        mid = QColor(accent); mid.setAlphaF(0.62)
        g.setColorAt(0.0, edge)
        g.setColorAt(0.12, mid)
        g.setColorAt(0.88, mid)
        g.setColorAt(1.0, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.fillRect(QRectF(row2.left() - h * 0.3, bar_y, row2.width() + h * 0.6, 1.0),
                   QBrush(g))

        # A quadration's rule carries a date AND the period it opens, so it
        # needs two lines in the same berth the progression fills with one. The
        # main figure shrinks to make room rather than the berth growing: the
        # berth is bounded above by the band's caption and below by the rule
        # itself, and neither may move for a label.
        has_sub = any(sub for _, sub in years.values())
        f = QFont()
        f.setFamilies(_SERIF_FAMILIES)
        f.setPixelSize(max(8, int(h * (0.062 if has_sub else 0.082))))
        fm = QFontMetrics(f)
        p.setFont(f)

        label_top = self._ruler_label_top(m, entries, fm)
        sub_font = None
        if has_sub and label_top is not None:
            candidate = self._label_font(max(6.0, h * 0.040), spacing=118)
            room = bar_y - (label_top + fm.height())
            # Dropped rather than overlapped when it does not fit — the same
            # rule the year row itself follows. A period number printed through
            # the rule is worse than no period number.
            if QFontMetrics(candidate).height() <= room:
                sub_font = candidate

        # The origin is the birth year: the SMALLEST of the seven, which is the
        # rightmost card because row 2 runs right to left (SPEC-COT-001 INV-5).
        origin_col = max(years, key=lambda c: c)
        for col, (label, sub) in years.items():
            cx = self._cell_rect(2, col, m).center().x()
            is_origin = (col == origin_col)

            ink = QColor(accent)
            if is_origin:
                ink = ink.lighter(118)
            if label_top is not None:
                p.setPen(QPen(ink))
                p.drawText(QRectF(cx - h * 0.5, label_top, h, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, label)
                if sub and sub_font is not None:
                    # The quadration's "PERIOD 3" under its date. Drawn only
                    # when the assembler supplies one, so the progression rule
                    # is byte-identical to what shipped.
                    faint = QColor(accent)
                    faint.setAlphaF(0.46)
                    p.save()
                    p.setFont(sub_font)
                    p.setPen(QPen(faint))
                    p.drawText(QRectF(cx - h * 0.5, label_top + fm.height(),
                                      h, QFontMetrics(sub_font).height()),
                               Qt.AlignmentFlag.AlignCenter, sub)
                    p.restore()

            tick = QColor(accent); tick.setAlphaF(0.55)
            p.setPen(QPen(tick, 1))
            p.drawLine(QPointF(cx, bar_y - h * 0.075), QPointF(cx, bar_y))

            # the leader down to the card it belongs to, fading as it goes
            lg = QLinearGradient(QPointF(0, bar_y), QPointF(0, row2.top()))
            near = QColor(accent); near.setAlphaF(0.36)
            far = QColor(accent); far.setAlphaF(0.0)
            lg.setColorAt(0.0, near)
            lg.setColorAt(1.0, far)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillRect(QRectF(cx - 0.5, bar_y, 1.0, row2.top() - bar_y),
                       QBrush(lg))

            if is_origin:
                dot = QColor(accent)
                p.setBrush(QBrush(dot))
                p.setPen(Qt.PenStyle.NoPen)
                r = h * 0.022
                p.drawEllipse(QPointF(cx, bar_y), r, r)
                halo = QColor(accent); halo.setAlphaF(0.20)
                p.setBrush(QBrush(halo))
                p.drawEllipse(QPointF(cx, bar_y), r * 2.4, r * 2.4)

        # No margin caption any more. The band above names both tiers in its
        # legend — QUADRATION 7 x 52 against PROGRESSION 52 x 7 — which says
        # what this rule is, and says it inside the figure instead of in
        # whatever sliver of margin the centred cross happens to leave.
        p.restore()

    # ---- the progression tier ---------------------------------------- #
    def _occupants_pending(self):
        """Whether the loaded spread's occupants and cusps are NOT COMPUTED.

        A progressed spread computes both now (SPEC-COT-006): the secondary
        progression is built and grafted in the assembler, so this is True only
        when that chart build FAILED. It is not a synonym for "is a progression"
        and must not be re-derived from ``is_progressed`` — an ephemeris problem
        and a progression are different facts, and only the first one means the
        marks below would be lying.

        Two marks are suppressed off this flag and both of them are REMOVALS: an
        empty foot rail and the "none found" cusp dash. Both are statements
        about a computation that did not happen — which is why an EMPTY
        progressed position still draws them. "Computed, none here" is true and
        common on a progression (INV-5: Lorris's Moon seat is empty for the
        whole ages 49-55 block), and it is a different fact from "not computed".
        """
        return bool((self._data or {}).get("occupants_pending"))

    def _birth_year(self):
        """The birth year carried by the spread ON SCREEN, or None.

        **This is not the ladder's origin and never was.** It reads the loaded
        payload, and a progression payload has every ``period_year`` None, so it
        answers None the moment a block is loaded. Three things break silently
        off that None — the TODAY needle disappears, all 52 cells lose their
        year line, and ``_sync_ladder_to`` sees a changed key and resets the
        whole ladder. Everything that needs the ORIGIN reads
        ``_natal_birth_year`` instead (INV-3).

        Kept because it is the honest answer to a different question: what year
        does the payload currently in ``_data`` claim?
        """
        return _natal_year_of(self._data)

    def _current_age(self):
        """Whole years lived, or None when the birth year could not be read.

        Reads ``_natal_birth_year``, never ``_birth_year()``. Two consumers hang
        off this one method — ``band_model``'s TODAY needle and ``_today_cell``'s
        keyboard default — and a None here removes the needle from the band and
        sends the first arrow key to block 0 instead of to the block the native
        is living.

        WI-3: month and day count. Someone born 22 Feb is 34 until that date
        each year, not 35 the moment January opens. The year-only subtraction
        the progression tier tolerated is kept ONLY as the degraded path, for a
        chart whose full date cannot be read (``_birth_date`` is None while the
        natal year survives). "Today" comes through the ``_today`` seam so the
        tests are not circular.
        """
        year = self._natal_birth_year
        if year is None:
            return None
        today = _today()
        birth = self._birth_date()
        if birth is not None:
            # Subtract a year when this year's birthday has not yet arrived.
            had_birthday = (today.month, today.day) >= (birth.month, birth.day)
            return max(0, today.year - birth.year - (0 if had_birthday else 1))
        # Full date unreadable: the blunter year-only answer, the exception.
        return max(0, today.year - year)

    def _family_kw(self, func):
        """``{"family": ...}`` where the ladder takes one, ``{}`` where it does not.

        The ladder becomes family-aware in a parallel track (INV-7). Until its
        signatures carry the keyword, passing it would be a ``TypeError`` on
        every repaint; after they do, NOT passing it would draw a 52-cell
        progression line under an Age Quadration breadcrumb. Asked of the
        signature rather than caught from the call, so a genuine signature
        mistake still raises where it happens.
        """
        return {"family": self._family} if _accepts_family(func) else {}

    def _line_cells(self, birth_card, birth_year):
        """The whole line for the open family: 52 progressions, or 90 ages.

        Returns the progression blocks unchanged on the progression family, and
        falls back to them if the quadration walk is unavailable or fails — a
        band that cannot draw its own family draws the one that ships rather
        than disappearing, and the buttons still say which family is selected.

        Memoised on its own inputs. It is called from ``paintEvent``, which
        runs on every pan step and every hover, and the answer is 90 date walks
        and 90 card descriptors that cannot change without one of these three
        values changing. The band's raster cache sits BELOW this call and
        cannot save it. One entry, because the only thing that varies within a
        session is the family and there are two of them.
        """
        key = (self._family, birth_card, birth_year, self._birth_date())
        if self._line_cache is not None and self._line_cache[0] == key:
            return self._line_cache[1]

        cells = None
        quad_fell_back = False
        if self._family == QUADRATION:
            # NOT gated on a birth date. ``quadration_ages`` answers 90 cells
            # without one (their Year Card is None and ``cell_face`` falls back
            # to the base card), and the LENGTH is what the geometry is solved
            # from. Guarding on the date fell through to the 52 progression
            # blocks while the band kept quadration geometry: 38 cells drew
            # blank at the rail, and a carriage dragged past age 76 drew
            # nothing at all. No exception anywhere — the two halves simply
            # disagreed about how long the line was.
            if quadration_ages is not None:
                try:
                    cells = quadration_ages(birth_card, key[3]) or None
                except Exception:                    # noqa: BLE001 — INV-12
                    cells = None
            # WI-4/DEF-3: the fallback is deliberate (never a blank band), but
            # the SCREEN must say what it is showing. ``_line_count`` now
            # follows this data, so the hit test and the clamp stay in range;
            # the note is what tells the reader the age line could not be built.
            if cells is None:
                quad_fell_back = True
        if cells is None:
            cells = progression_blocks(birth_card, birth_year)
        if quad_fell_back:
            self._family_note = ("age line unavailable, showing the 7 year "
                                 "progression")
        self._line_cache = (key, cells)
        return cells

    def _paint_progression_band(self, p, pal, m, entries):
        """The 52 x 7 tier, above the 7 x 52 rule (SPEC-COT-003).

        Geometry lives in :mod:`apps.widgets.cot_ladder`, which quotes the
        mockup's own ratios. Nothing about the drawing is decided here; this
        method's whole job is to assemble the model from the loaded spread and
        hand over the row-2 rect the band measures itself against.
        """
        if not self._data:
            return
        birth_card = self._data.get("birth_card")
        if not birth_card:
            return
        # INV-3 / INV-5: the ladder is always walked from the NATAL origin,
        # whatever is loaded over it. ``_birth_year()`` is None on a progression
        # payload and every one of these 52 cells would lose its year line.
        birth_year = self._natal_birth_year

        h = m[0]
        row2 = self._cell_rect(2, 1, m).united(self._cell_rect(2, 7, m))
        geo = cot_ladder.band_geometry(h, row2, self._level,
                                       **self._family_kw(cot_ladder.band_geometry))

        blocks = self._line_cells(birth_card, birth_year)
        model = cot_ladder.band_model(
            blocks, window_start=self._window_start,
            selected=self._selected[_SELECT_KEY[self._level]],
            current_age=self._current_age(), level=self._level,
            path=self._selected, loaded=self._loaded_block,
            **self._family_kw(cot_ladder.band_model))

        # The band may not write above row 1's cards: the birth card is drawn
        # enlarged and the crumb/legend line is what reaches it first.
        top_limit = self._cell_rect(1, 1, m).bottom()
        pix, dest = self._band_raster(pal, m, row2, model, top_limit)
        if pix is not None:
            p.drawPixmap(dest, pix)
        else:                                    # nothing to draw at this size
            self._band_mode = "rule_only"
        self._band_geo = geo
        self._band_dest = dest      # where the cache landed — T-2b reads it

    # ---- the band's raster cache (SPEC-COT-003 INV-4) ----------------- #
    def _band_raster(self, pal, m, row2, model, top_limit):
        """The band as a pixmap, and where to blit it.

        Rendered in BAND-LOCAL coordinates: inside the pixmap the row-2 top is
        at the bottom edge and the left margin is at ``mx``. That is the whole
        reason a cache is possible. ``band_geometry`` returns ABSOLUTE
        coordinates, so caching pixels produced from those and re-blitting them
        at a new origin would draw the band frozen where it was while the cards
        panned underneath — a bug that looks like the band "sticking" and has
        no error to catch.

        Pan is therefore NOT in the key, and neither is the hovered body chip:
        panning moves the blit, and hover is drawn over it. Both would
        otherwise miss on every mouse move, which is the case the cache exists
        for.

        Measured before building it: the 52-cell rail costs 17.0 ms of a
        60.5 ms frame, 28%, and the widget repaints on every pan step.
        """
        h = m[0]
        mx = h * 0.09                         # the trough and the window
        my = h * 0.07                         # bracket both overhang the band
        want_h = h * (cot_ladder.band_height(self._level) + _GAP_Y) + my
        dpr = float(self.devicePixelRatioF())

        # Snap the blit to whole DEVICE pixels, then derive the local origin
        # from where it actually landed. Rounding the pixmap size and blitting
        # at a fractional point instead moves the band a pixel against the
        # cards — small, real, and exactly the class of error a cache makes
        # permanent. Deriving the origin from the snapped position makes the
        # mapping exact whatever the rounding did.
        dest = QPointF(math.floor((row2.left() - mx) * dpr) / dpr,
                       math.floor((row2.top() - want_h) * dpr) / dpr)
        local_left = row2.left() - dest.x()
        local_top = row2.top() - dest.y()
        raster_w = int(math.ceil((local_left + row2.width() + mx) * dpr))
        raster_h = int(math.ceil(local_top * dpr))
        if raster_w < 1 or raster_h < 1:
            return None, dest

        key = (
            raster_w, raster_h, dpr,
            # h itself, not just the raster it rounds to. Every coordinate,
            # font size and drop-or-draw decision inside the band is a
            # multiple of h, and the raster dimensions are integers: two h
            # values a fraction apart round to the same pixmap size while
            # sitting on opposite sides of the crumb's room-to-draw test. The
            # band would then keep whichever answer it was first rendered
            # with. Rounded, because float noise must not be a cache miss.
            round(h, 4),
            # the PALETTE, not the theme name: the band only ever sees one of
            # two, so keying on the name misses on every switch between two
            # themes of the same polarity for no visual difference
            is_light_theme(),
            # M-5. The two families draw a different line, a different cell
            # count, a different caption and a different hue into a pixmap of
            # identical dimensions at identical h — so a key without the family
            # HITS on the first switch and the reader presses a button that
            # visibly does nothing. Nothing else in this tuple separates them:
            # ``cells`` comes from the level, and both families use the same
            # levels deliberately (§3.3).
            self._family,
            model["level"], model["cells"],
            # WINDOWED, not magnified. The quadration's rail slides without a
            # map, so a key that asked about the magnifier hit on every step of
            # the slide and blitted the ages the reader started from — the band
            # frozen while the year marks under it were the only thing that
            # could have said so, and they are in the same pixmap.
            model["window_start"] if model["windowed"] else None,
            model["selected"], model["today"],
            # WI-7 / D-10: whether an Age-N spread is loaded decides whether the
            # decade marks draw (they stand down for the spread's own ruler).
            # The crumb below changes on load too, but the marks are keyed
            # EXPLICITLY here so the band re-rasters on load rather than blitting
            # a marked pixmap over the loaded ruler — the INV-12 / M-17 class of
            # cache-freeze defect this whole tuple exists to prevent.
            self._loaded_block is not None,
            # The crumb names the whole PATH, not just this level's selection,
            # so it is the one string in the band that can change while every
            # other key component stays put. Keyed literally rather than
            # argued about.
            model["crumb"],
            self._data.get("birth_card"),
            model["blocks"][0].get("year_start") if model["blocks"] else None,
        )
        self._band_key = key       # what the cache was asked for, hit or miss
        hit = self._band_cache.get(key)
        if hit is not None:
            self._band_mode = hit[1]
            return hit[0], dest

        pix = QPixmap(raster_w, raster_h)
        pix.setDevicePixelRatio(dpr)
        # Transparent, and it has to be: the lattice wash reaches half a card
        # height above row 2, so the ground under the band is a gradient, not a
        # flat colour there is any way to pre-fill with.
        #
        # The cost is that Qt drops to greyscale antialiasing on an alpha
        # destination where the widget's opaque backing store uses subpixel.
        # Measured on the rail: geometry identical to the pixel, hue identical,
        # and the cached text slightly CRISPER (438 ink px peaking at 248
        # against 495 peaking at 223 — coverage concentrated rather than
        # smeared). So T-3 compares the band with a tolerance, not byte-for-
        # byte; an exact-match oracle here would fail on a difference that is
        # both unavoidable and an improvement.
        pix.fill(Qt.GlobalColor.transparent)
        bp = QPainter(pix)
        bp.setRenderHint(QPainter.RenderHint.Antialiasing)
        bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        local_row2 = QRectF(local_left, local_top,
                            row2.width(), row2.height())
        mode = cot_ladder.paint_band(
            # The SAME family as the absolute geometry above. Solving the
            # raster's copy without it draws a 52-cell progression row while
            # ``_hit_band`` measures against a 90-cell quadration one: the band
            # would look right, and every click on it would land on the wrong
            # age with nothing on screen to say so.
            bp, pal, cot_ladder.band_geometry(
                h, local_row2, self._level,
                **self._family_kw(cot_ladder.band_geometry)),
            model, _SERIF_FAMILIES, dpr=dpr,
            # the same limit, expressed against the pixmap's own origin
            top_limit=local_top - (row2.top() - top_limit))
        bp.end()

        # Bounded, and for the same reason _CACHE_MAX exists one level down:
        # zoom multiplies h continuously, so the key space has no natural end.
        # These are full-width pixmaps, so the bound is small.
        if len(self._band_cache) >= _BAND_CACHE_MAX:
            self._band_cache.pop(next(iter(self._band_cache)))
        self._band_cache[key] = (pix, mode)
        self._band_renders += 1
        self._band_mode = mode
        return pix, dest

    # ---- row 1's two flanks (SPEC-COT-007 D-2, D-3, D-4) -------------- #
    #
    # INV-1: the frame does not grow. Row 1 spans all seven columns and only
    # column 4 carries the birth card, so both flanks are already empty space
    # inside the figure. Everything below lands in them. Drawn in FIGURE
    # coordinates, unlike the order and help buttons at the widget's corners:
    # they belong to the flank, they scale with h like every other measurement
    # here, and their hit rects are rebuilt by the painter exactly as the body
    # chips' are.

    def _flank(self, m, side):
        """The empty part of row 1, left (columns 1-3) or right (5-7)."""
        if side == "left":
            rect = self._cell_rect(1, 1, m).united(self._cell_rect(1, 3, m))
        else:
            rect = self._cell_rect(1, 5, m).united(self._cell_rect(1, 7, m))
        return rect

    @staticmethod
    def _plain_font(pixel_size, bold=False):
        f = QFont()
        f.setPixelSize(max(6, int(round(pixel_size))))
        if bold:
            f.setWeight(QFont.Weight.DemiBold)
        return f

    @staticmethod
    def _on_ink(pal, fill):
        """Legible text over ``fill``, chosen from the palette (Rule 20).

        Whichever of the palette's two extremes is furthest from the fill in
        lightness. The active family button is filled with the family's own
        hue, and that hue is the live theme primary on one side — so a fixed
        choice is legible under the theme it was picked against and invisible
        under the next one.
        """
        ink, ground = QColor(pal["ink"]), QColor(pal["bg0"])
        if abs(ink.lightnessF() - fill.lightnessF()) >= \
                abs(ground.lightnessF() - fill.lightnessF()):
            return ink
        return ground

    def _paint_family_buttons(self, p, pal, m):
        """The two family buttons, right flank of row 1 (D-1, D-2).

        Two segments of one pill, and mutually exclusive by construction: there
        is no third state and no "off", because the screen is always showing one
        of the two families. NOT a mode inside one control — the families are
        not variants of each other, and a single control implies they are.

        Painted, like the other two buttons in this view, and therefore owning
        its own hit rects — which is why :meth:`mouseDoubleClickEvent` has to
        swallow them explicitly (INV-11).
        """
        self._family_hits = []
        h = m[0]
        flank = self._flank(m, "right")

        font = self._label_font(max(7.0, h * 0.056), spacing=119)
        fm = QFontMetrics(font)
        pad_x, pad_y = h * 0.072, h * 0.040
        height = fm.height() + 2 * pad_y

        # Degrade the copy rather than the frame. D-1's own wording first; if
        # the flank cannot hold it the words shorten, and only when even the
        # shortest pair overflows does the control disappear — at which point
        # the family is still switchable by the keyboard ``F`` and the remote
        # ``cot_family`` command (WI-12), so no state is stranded off screen.
        for labels in (
            {f: family_spec(f)["label"] for f in FAMILY_ORDER},
            {PROGRESSION: "Progression", QUADRATION: "Quadration"},
            {PROGRESSION: "7 Year", QUADRATION: "Age"},
        ):
            widths = {f: fm.horizontalAdvance(labels[f].upper()) + 2 * pad_x
                      for f in FAMILY_ORDER}
            if sum(widths.values()) <= flank.width():
                break
        else:
            return

        total = sum(widths.values())
        x = flank.right() - total
        # Sat at the FOOT of the flank: above the band and the rule, level with
        # the bottom of the birth card, which is where the approved design puts
        # it and what keeps the eye off it until it is wanted.
        top = flank.bottom() - height
        radius = height / 2.0

        outline = QPainterPath()
        outline.addRoundedRect(QRectF(x, top, total, height), radius, radius)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ground = QColor(pal["face_up"][0])
        ground.setAlphaF(0.80)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ground))
        p.drawPath(outline)

        p.setFont(font)
        for family in FAMILY_ORDER:
            width = widths[family]
            rect = QRectF(x, top, width, height)
            self._family_hits.append((rect, family))
            active = family == self._family
            hot = family == self._family_hover
            if active:
                ink = family_ink(pal, family)
                p.save()
                p.setClipPath(outline)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(ink))
                p.drawRect(rect)
                p.restore()
                p.setPen(QPen(self._on_ink(pal, ink)))
            else:
                p.setPen(QPen(pal["ink"] if hot else pal["ink_faint"]))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       labels[family].upper())
            x += width

        # the divider and the frame, over the fill so the seam stays visible
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(pal["rail_line"], 1))
        p.drawPath(outline)
        seam = self._family_hits[0][0].right()
        p.drawLine(QPointF(seam, top + 1), QPointF(seam, top + height - 1))
        p.restore()

    def _paint_seal(self, p, pal, m):
        """The Year Card medallion and its ledger, left flank of row 1.

        **Round, and the shape is the argument** (D-3). A medallion cannot be
        misread as a fifteenth card of the spread; a card-shaped token can, and
        the Year Card is emphatically not one of the fourteen — it is what
        strikes one of them.

        The ledger sits BESIDE it at the same level (D-4), so everything the
        Year Card has to say is in one place. **How the Year Card is found is
        not here** (D-5): that is read once, so it lives in the help card.

        Quadration only. There is no Year Card on a progression screen, and a
        dimmed medallion saying nothing is worse than no medallion at all.
        """
        self._seal_rect = QRectF()
        if self._family != QUADRATION or self._data is None:
            return
        if not self._year_card:
            # No Year Card, no medallion. Two reachable states land here: a
            # quadration assembly that failed and fell back to the natal
            # payload, and a chart whose birth DATE could not be read at all.
            # In both the disc would be struck blank under a confident "AGE 35"
            # — a Year Card that does not exist, drawn as though it did.
            return
        h = m[0]
        flank = self._flank(m, "left")
        if flank.width() < h * 0.72:
            return

        head_h = h * 0.085
        disc = h * 0.56
        left = flank.left()
        accent = QColor(pal["accent"])

        # WI-9 / DEF-5 — the medallion group is BOTTOM-anchored in the flank so
        # it stops floating high in the band (Lorris: "lower the seal"). The
        # group is heading + gap + disc + gap + AGE label; its bottom lands on
        # the flank bottom, the same line the ledger ends on (D-4), so the two
        # bottoms align. A fixed top offset re-broke at other heights, so the
        # anchor is the bottom and the top is computed from the group's own
        # height. ``max(flank.top(), ...)`` keeps the heading on screen if a
        # very short flank ever makes the group taller than the flank.
        gap_head = h * 0.03           # heading to disc
        gap_age = h * 0.022           # disc to AGE label
        age_h = QFontMetrics(
            self._label_font(max(6.0, h * 0.048), spacing=150)).height()
        group_h = head_h + gap_head + disc + gap_age + age_h
        group_top = max(flank.top(), flank.bottom() - group_h)

        # ---- "OUTSIDE THE SPREAD": why a round thing sits beside a spread
        head_font = self._label_font(max(6.0, h * 0.046), spacing=140)
        p.save()
        p.setFont(head_font)
        faint = QColor(accent)
        faint.setAlphaF(0.62)
        p.setPen(QPen(faint))
        p.drawText(QRectF(left, group_top, flank.width(), head_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "OUTSIDE THE SPREAD")
        p.restore()

        top = group_top + head_h + gap_head
        ring = QRectF(left, top, disc, disc)
        self._seal_rect = QRectF(ring)

        # ---- the medallion. Struck metal, not a card face: a dome lit from the
        # upper left, a milled inner ring, and no keyline, no foot, no corner
        # index — none of the marks that make the fourteen read as cards.
        g = QRadialGradient(QPointF(ring.left() + disc * 0.36,
                                    ring.top() + disc * 0.28), disc * 0.72)
        g.setColorAt(0.0, accent.lighter(142))
        g.setColorAt(0.56, QColor(accent))
        g.setColorAt(1.0, accent.darker(128))
        p.save()
        p.setPen(QPen(_rgba((accent.red(), accent.green(), accent.blue()), .75), 1))
        p.setBrush(QBrush(g))
        p.drawEllipse(ring)
        milled = QPen(_rgba((0, 0, 0), .30), max(1.0, disc * 0.012),
                      Qt.PenStyle.DashLine)
        p.setPen(milled)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring.adjusted(disc * 0.095, disc * 0.095,
                                    -disc * 0.095, -disc * 0.095))
        p.restore()

        face = self._on_ink(pal, QColor(accent))
        card = self._year_card or {}
        rank = card.get("rank_display") or ""
        if rank:
            f = QFont()
            f.setFamilies(_SERIF_FAMILIES)
            f.setPixelSize(max(8, int(disc * 0.34)))
            f.setWeight(QFont.Weight.DemiBold)
            fm = QFontMetrics(f)
            p.save()
            p.setFont(f)
            p.setPen(QPen(face))
            p.drawText(QRectF(ring.left(), ring.center().y() - fm.height() * 0.86,
                              disc, fm.height()),
                       Qt.AlignmentFlag.AlignCenter, rank)
            p.restore()
            pip = self._suit_pixmap(card.get("suit_name"),
                                    int(disc * 0.21), QColor(face))
            if pip is not None:
                r = QRectF(0, 0, pip.width() / pip.devicePixelRatio(),
                           pip.height() / pip.devicePixelRatio())
                r.moveCenter(QPointF(ring.center().x(),
                                     ring.center().y() + disc * 0.17))
                p.drawPixmap(r.topLeft(), pip)

        # ---- the age it belongs to, under the medallion
        age = self._active_age()
        if age is not None:
            ring_font = self._label_font(max(6.0, h * 0.048), spacing=150)
            rfm = QFontMetrics(ring_font)
            p.save()
            p.setFont(ring_font)
            p.setPen(QPen(accent))
            p.drawText(QRectF(ring.left(), ring.bottom() + h * 0.022,
                              disc, rfm.height()),
                       Qt.AlignmentFlag.AlignCenter, f"AGE {age}")
            p.restore()

        # ---- the ledger, beside it (D-4, same level). Re-derived from the same
        # bottom anchor as the disc (WI-9): it starts at the disc top, below the
        # heading, and ends on the flank bottom, so the two bottoms align and
        # the ledger sits beside the medallion rather than floating above it.
        ledger_left = ring.right() + h * 0.13
        ledger = QRectF(ledger_left, ring.top(),
                        flank.right() - ledger_left,
                        flank.bottom() - ring.top())
        if ledger.width() >= h * 0.95:
            self._paint_ledger(p, pal, ledger, h)

        if self._family_note:
            note_font = self._plain_font(max(6.0, h * 0.046))
            p.save()
            p.setFont(note_font)
            p.setPen(QPen(pal["ink_faint"]))
            p.drawText(QRectF(left, flank.bottom() - h * 0.09,
                              flank.width(), h * 0.09),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._family_note)
            p.restore()

    def _paint_ledger(self, p, pal, rect, h):
        """Three sentences and a closing line (§3.7, verbatim).

        No column headings: each row IS a sentence, and a sentence does not need
        a header to say what its halves are. The row that hit carries a filled
        dot and a wash; the rows that did not say so plainly, because an empty
        result is normal and not a failure (INV-4).
        """
        rows = self._ledger
        if not rows:
            return
        accent = QColor(pal["accent"])
        font = self._plain_font(max(6.0, h * 0.056))
        fm = QFontMetrics(font)
        row_h = fm.height() + h * 0.030
        if row_h * len(rows) > rect.height():
            return                        # no room: the seal alone still reads

        dot_r = h * 0.017
        pad = h * 0.026
        y = rect.top()
        p.save()
        p.setFont(font)
        for label, value, hit in rows:
            row = QRectF(rect.left(), y, rect.width(), row_h)
            if hit:
                wash = QColor(accent)
                wash.setAlphaF(0.10)
                p.setPen(QPen(_rgba((accent.red(), accent.green(),
                                     accent.blue()), .30), 1))
                p.setBrush(QBrush(wash))
                p.drawRoundedRect(row, h * 0.014, h * 0.014)
            centre = QPointF(row.left() + pad, row.center().y())
            p.setBrush(QBrush(accent) if hit else Qt.BrushStyle.NoBrush)
            p.setPen(QPen(accent if hit else pal["ink_faint"], 1))
            p.drawEllipse(centre, dot_r, dot_r)

            text = QRectF(row.left() + pad * 2 + dot_r, row.top(),
                          row.width() - pad * 3 - dot_r, row.height())
            p.setPen(QPen(pal["ink"] if hit else pal["ink_faint"]))
            p.drawText(text, int(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter), label)
            p.setPen(QPen(accent if hit else pal["ink_faint"]))
            p.drawText(text, int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter), value)
            y += row_h

        if self._ledger_close:
            close_font = self._plain_font(max(6.0, h * 0.052))
            room = QRectF(rect.left(), y + h * 0.024, rect.width(),
                          rect.bottom() - y - h * 0.024)
            if room.height() >= QFontMetrics(close_font).height():
                p.setFont(close_font)
                p.setPen(QPen(pal["ink_soft"]))
                p.drawText(room, int(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignTop
                                     | Qt.TextFlag.TextWordWrap),
                           self._ledger_close)
        p.restore()

    def _struck_seats(self):
        """Seat indices the Year Card lands on in THIS year's own spread.

        WI-11 / D-12. One scan, two consumers: the ledger and the struck cards
        read the SAME assembled ``coincidences`` (INV-13, no second scan). Only
        the ``year`` spread — the fourteen cards actually on screen. The ``life``
        and ``progression`` hits are the LEDGER's to report; they are not cards
        the eye can point at, so they carry no gold. A progression or natal
        payload has no ``coincidences`` at all, so this is empty there and the
        struck treatment never reaches a family that has no Year Card (INV-7).
        """
        for entry in (self._data or {}).get("coincidences") or ():
            if isinstance(entry, dict) and entry.get("key") == "year":
                return set(entry.get("seats") or ())
        return set()

    # ---- one card ---------------------------------------------------- #
    def _paint_card(self, p, pal, m, entry, live):
        h = m[0]
        rect = self._card_rect(entry, m)
        radius = h * _RADIUS * (1.12 if entry["is_base"] else 1.0)
        occupied = bool(entry.get("occupied"))
        base = entry["is_base"]
        lifted = occupied or base

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # --- depth. Qt has no box-shadow: stack translucent rounded rects
        # outward with an alpha falloff. Occupied and base cards sit forward as
        # physical objects; empty ones stay recessed and quiet.
        self._drop_shadow(p, rect, radius, pal,
                          spread=h * (0.16 if lifted else 0.07),
                          dy=h * (0.075 if lifted else 0.03),
                          strength=1.0 if lifted else 0.45)

        # --- the stock: the card's own thickness, seen as a sliver of edge
        # below the face. A shadow alone says "this floats"; an edge says "this
        # is a physical object with a side to it", which is the difference
        # between a sticker and a card. Lifted cards show more of it, so the
        # depth cue and the occupancy cue agree instead of competing.
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(pal["stock"])))
        p.drawRoundedRect(rect.translated(0, h * (0.022 if lifted else 0.012)),
                          radius, radius)
        p.restore()

        # --- face
        stops = pal["face_up"] if lifted else pal["face_down"]
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, QColor(stops[0]))
        g.setColorAt(0.52, QColor(stops[1]))
        g.setColorAt(1.0, QColor(stops[2]))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(path)
        p.restore()

        # --- sheen, and on occupied cards a suit-tinted rim glow under the top
        p.save()
        p.setClipPath(path)
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(),
                                                        rect.top() + rect.height() * 0.55))
        sheen.setColorAt(0.0, pal["sheen"])
        sheen.setColorAt(1.0, _rgba((0, 0, 0), 0.0))
        p.fillRect(rect, QBrush(sheen))

        if occupied and not base:
            rim = pal["rim_red"] if entry["is_red"] else pal["rim_black"]
            rg = QLinearGradient(rect.topLeft(), QPointF(rect.left(),
                                                         rect.top() + rect.height() * 0.42))
            rg.setColorAt(0.0, rim)
            rg.setColorAt(1.0, _rgba((0, 0, 0), 0.0))
            p.fillRect(rect, QBrush(rg))
            # the hairline along the very top edge, in the suit's own colour
            edge = pal["edge_red"] if entry["is_red"] else pal["edge_black"]
            p.setPen(QPen(edge, 1))
            p.drawLine(QPointF(rect.left(), rect.top() + 0.5),
                       QPointF(rect.right(), rect.top() + 0.5))
        p.restore()

        # --- outer ring. A hairline at every size: the frame is there to close
        # the shape, and the depth now comes from the stock and the bevel. A
        # heavier line competes with them and flattens the card back out.
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if base:
            p.setPen(QPen(_rgba(pal["accent"], .42), 1))
        else:
            p.setPen(QPen(pal["ring"] if lifted else pal["ring_down"], 1))
        p.drawPath(path)
        p.restore()

        # --- inner keyline: the double frame of a real card face. Present on
        # every card so the architecture stays uniform; it simply brightens
        # when the card is occupied.
        inset = h * _KEYLINE_INSET
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if base:
            p.setPen(QPen(_rgba(pal["accent"], .34), 1))
        else:
            p.setPen(QPen(pal["keyline_lit"] if occupied else pal["keyline"], 1))
        p.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset),
                          radius * 0.58, radius * 0.58)
        p.restore()

        if not live:
            self._paint_bevel(p, pal, rect, radius, h)
            return                                # empty grid: silhouette only

        # --- foot band. Every card has the same slot; some are just unfilled,
        # so all fourteen pips land at the same optical height and emptiness
        # reads as intentional rather than as a missing asset.
        foot_h = h * (_CHIP + _FOOT_PAD)
        foot = QRectF(rect.left(), rect.bottom() - foot_h, rect.width(), foot_h)
        p.save()
        p.setClipPath(path)
        if base:
            self._paint_plate(p, pal, foot, h)
        elif occupied:
            self._paint_rail(p, pal, foot, h, entry)
        elif not self._occupants_pending():
            # The empty rail. It is a POSITIVE statement — "computed, none" —
            # and on a progressed spread nothing has been computed at all, so
            # drawing it would state something false about every one of the
            # fourteen cards (SPEC-COT-003 §4.4, SPEC-COT-005 INV-7). Removing
            # it is the work; the payload being empty already is not.
            faint = QColor(pal["rail_line"])
            faint.setAlphaF(faint.alphaF() * 0.42)
            p.setPen(QPen(faint, 1))
            p.drawLine(QPointF(foot.left(), foot.top()), QPointF(foot.right(), foot.top()))
        p.restore()

        self._paint_index(p, pal, rect, h, entry)
        self._paint_position(p, pal, rect, h, entry, occupied or base)
        self._paint_pip(p, pal, rect, foot, h, entry, occupied or base)
        # SPEC-COT-002. After the hero pip so the gutters overlay nothing, and
        # clipped to the card so a three-cusp stack can never spill into the
        # neighbouring column and read as that card's data.
        p.save()
        p.setClipPath(path)
        self._paint_year(p, pal, rect, h, entry, occupied or base)
        self._paint_gutters(p, pal, rect, foot, h, entry, occupied or base)
        p.restore()

        # WI-11 / D-12: the Year Card strikes the seat(s) it lands on in THIS
        # year's own spread. After the face, before the bevel, so the gold rim
        # sits over the face but the physical edge still closes the corner on top.
        if entry["index"] in self._struck_seats():
            self._paint_struck(p, pal, rect, radius, h, entry)

        # LAST. A physical edge sits in front of everything printed on the
        # face, including the occupant rail, which runs to the bottom of the
        # card and would otherwise cut the bevel off exactly where the eye
        # needs it to turn the corner.
        self._paint_bevel(p, pal, rect, radius, h)

    def _paint_bevel(self, p, pal, rect, radius, h):
        """The lit top edge and shaded bottom edge of a card with thickness.

        Two short gradient bands rather than a stroked outline. An outline of
        one colour reads as a drawn border; a light band at the top and a dark
        one at the bottom reads as a single surface curving away from a light
        source above, which is what makes the corner radius look like a rounded
        EDGE rather than a rounded rectangle.

        Clipped to the card path, so the bands follow the corner curve and stop
        cleanly instead of squaring off the shape they are meant to round.
        """
        band = h * 0.052
        p.save()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)

        hi = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.top() + band))
        hi.setColorAt(0.0, pal["bevel_hi"])
        hi.setColorAt(1.0, _rgba((255, 255, 255), 0.0))
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), band), QBrush(hi))

        lo = QLinearGradient(QPointF(0, rect.bottom() - band), QPointF(0, rect.bottom()))
        lo.setColorAt(0.0, _rgba((0, 0, 0), 0.0))
        lo.setColorAt(1.0, pal["bevel_lo"])
        p.fillRect(QRectF(rect.left(), rect.bottom() - band, rect.width(), band),
                   QBrush(lo))
        p.restore()

    def _paint_struck(self, p, pal, rect, radius, h, entry):
        """The Year Card strikes this seat (WI-11 / D-12).

        One mark only: a gold rim on the card's edge. The face underneath stays
        exactly what every other card paints — same pip, same occupants, same
        foot — so the strike never competes with the planets or the indices.
        (The earlier watermark + ribbon treatment doubled the pip and covered
        the occupant row; Lorris cut it to the rim, 2026-07-29.) Gold is the
        only accent (INV-8) and the colour comes from the theme (Rule 20). The
        age the strike belongs to lives in the ledger's prose, not on the card.
        """
        accent = QColor(pal["accent"])
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)

        # Mockup 2026-07-29-cot-struck-rim, variant B: a 2px gold rim, floored so
        # it never thins to a hairline at the minimum zoom. Clipped and inset by
        # half its width so the whole stroke lands inside the card rect and the
        # corner follows the card's own radius (a stroke centred ON the edge
        # would spill half its width over the neighbour).
        line = max(2.0, h * 0.020)
        p.save()
        p.setClipPath(clip)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(accent, line))
        p.drawRoundedRect(rect.adjusted(line / 2, line / 2, -line / 2, -line / 2),
                          radius * 0.9, radius * 0.9)
        p.restore()

    def _drop_shadow(self, p, rect, radius, pal, spread, dy, strength):
        """A soft shadow built from concentric rounded rects.

        Cheaper and more predictable than a blur pass, and at 14 cards the cost
        is invisible. Alpha falls off quadratically so the penumbra reads soft
        rather than banded.
        """
        steps = 9
        base = pal["shadow"]
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(steps, 0, -1):
            t = i / steps
            grow = spread * t
            col = QColor(base)
            col.setAlphaF(base.alphaF() * strength * 0.13 * (1.0 - t) ** 0.6)
            p.setBrush(QBrush(col))
            p.drawRoundedRect(
                rect.adjusted(-grow, -grow + dy, grow, grow + dy),
                radius + grow, radius + grow)
        p.restore()

    def _plate_lines(self):
        """What the head card's plate says: natal, or which block is loaded.

        The head card is the one place a reader can tell the two spreads apart
        at a glance, so it must never keep saying BIRTH CARD over a progressed
        base card (SPEC-COT-005 INV-2). Two lines, because the block needs both
        what it IS and which ages it covers, following the same age-band title
        convention.
        """
        data = self._data or {}
        kind = data.get("kind")
        if kind == "quadration":
            # ``is not None`` — age 0 is a real age and a falsy one, and it is
            # the age this whole tier is anchored on (Q-3: the Age 0 Year Card
            # IS the birth card).
            age = data.get("age")
            if age is None:
                age = self._active_age()
            return (family_spec(QUADRATION)["label"].upper(),
                    "AGE" if age is None else f"AGE {age}")
        if kind != "progression":
            return ("BIRTH CARD",)
        return ("7 YEAR PROGRESSION",
                f"AGES {data.get('age_start')}-{data.get('age_end')}")

    def _paint_plate(self, p, pal, foot, h):
        """The birth card's foot: an accented plate instead of a body rail."""
        accent = QColor(pal["accent"])
        g = QLinearGradient(foot.topLeft(), foot.bottomLeft())
        g.setColorAt(0.0, _rgba((accent.red(), accent.green(), accent.blue()), .13))
        g.setColorAt(1.0, _rgba((accent.red(), accent.green(), accent.blue()), .04))
        p.fillRect(foot, QBrush(g))
        p.setPen(QPen(_rgba((accent.red(), accent.green(), accent.blue()), .45), 1))
        p.drawLine(QPointF(foot.left(), foot.top()), QPointF(foot.right(), foot.top()))

        lines = self._plate_lines()
        # Two lines have to share the same plate one line had, so they take a
        # smaller face. Measured against the plate rather than assumed: at the
        # widget minimum the foot is ~9px and Qt floors a font at 8, so the
        # second line is dropped rather than drawn through the first.
        size = h * (0.053 if len(lines) == 1 else 0.044)
        f = self._label_font(size, spacing=130 if len(lines) == 1 else 108)
        fm = QFontMetrics(f)
        p.setFont(f)
        p.setPen(QPen(accent))
        if len(lines) == 1 or fm.height() * len(lines) > foot.height():
            p.drawText(foot, Qt.AlignmentFlag.AlignCenter, lines[0])
            return
        top = foot.center().y() - fm.height() * len(lines) / 2.0
        for line in lines:
            p.drawText(QRectF(foot.left(), top, foot.width(), fm.height()),
                       Qt.AlignmentFlag.AlignCenter, line)
            top += fm.height()

    def _paint_rail(self, p, pal, foot, h, entry):
        """The occupant bodies, as icons on pale discs.

        The discs are not decoration: the planet artwork is mid-to-dark toned
        and Saturn or Ketu would otherwise vanish into a dark card face. They
        also give the row a consistent rhythm whether a card holds one body or
        three.
        """
        p.fillRect(foot, QBrush(pal["rail_bg"]))
        p.setPen(QPen(pal["rail_line"], 1))
        p.drawLine(QPointF(foot.left(), foot.top()), QPointF(foot.right(), foot.top()))

        bodies = entry["bodies"]
        chip = h * _CHIP
        gap = chip * 0.20
        # Three bodies is the widest case in practice; shrink to fit rather than
        # overflow if a card ever holds more (SPEC-COT-001 §4.7).
        total = len(bodies) * chip + (len(bodies) - 1) * gap
        if total > foot.width() - h * 0.04:
            scale = (foot.width() - h * 0.04) / total
            chip, gap, total = chip * scale, gap * scale, total * scale

        x = foot.center().x() - total / 2.0
        cy = foot.center().y()
        for body in bodies:
            r = QRectF(x, cy - chip / 2.0, chip, chip)
            # The HIT rect is the un-hovered size at all times. A hovered chip
            # grows, and if the hit rect grew with it the pointer could sit in
            # the grown margin: leaving would shrink the chip out from under
            # the cursor, which re-enters, which grows it again. A hover that
            # flickers at its own edge is worse than one that starts a pixel late.
            self._chip_hits.append((r.toRect(), body))
            self._paint_chip(p, pal, r, body, body is self._hover_body)
            x += chip + gap

    def _paint_chip(self, p, pal, r, body, hot=False):
        if hot:
            # Lit in the body's OWN colour: the shadow colour it already glows
            # with in the other chart views, read live from settings. A generic
            # highlight would say "you are pointing at something"; this says
            # WHICH planet, in the colour this user has already taught himself
            # to read it by — and it follows him when he changes it.
            tint = planet_shadow_color(body["name"], fallback=pal["accent"])
            halo = QRectF(r).adjusted(-r.width() * 0.30, -r.height() * 0.30,
                                      r.width() * 0.30, r.height() * 0.30)
            glow = QRadialGradient(r.center(), halo.width() / 2.0)
            inner = QColor(tint); inner.setAlphaF(0.55)
            mid = QColor(tint); mid.setAlphaF(0.22)
            outer = QColor(tint); outer.setAlphaF(0.0)
            glow.setColorAt(0.0, inner)
            glow.setColorAt(0.55, mid)
            glow.setColorAt(1.0, outer)
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(halo)
            p.restore()
            # and the disc itself swells, so the chip lifts off the rail rather
            # than merely changing colour in place
            r = QRectF(r).adjusted(-r.width() * 0.09, -r.height() * 0.09,
                                   r.width() * 0.09, r.height() * 0.09)

        # A RADIAL gradient with the light off-centre, not a linear one: a dome
        # needs a highlight that sits somewhere on the surface and falls away in
        # every direction. A top-to-bottom ramp reads as a flat disc lit from
        # the side however bright it is made.
        g = QRadialGradient(QPointF(r.center().x() - r.width() * 0.22,
                                    r.center().y() - r.height() * 0.26),
                            r.width() * 0.95)
        g.setColorAt(0.0, QColor(pal["chip_bg"][0]).lighter(112))
        g.setColorAt(0.55, QColor(pal["chip_bg"][0]))
        g.setColorAt(1.0, QColor(pal["chip_bg"][1]))
        p.save()
        if hot:
            # The ring, not the halo, is what guarantees the hover is visible.
            # Some bodies are configured near-black (Rahu is #000000), and a
            # black glow on a dark card face is nothing at all — but the same
            # black against the pale chip disc is unmistakable. So the colour
            # is used exactly as configured, and legibility comes from drawing
            # it where there is always contrast rather than from adjusting it.
            ring = planet_shadow_color(body["name"], fallback=pal["accent"])
            ring.setAlphaF(0.90)
            p.setPen(QPen(ring, max(1.0, r.width() * 0.075)))
        else:
            p.setPen(QPen(pal["chip_ring"], 1))
        p.setBrush(QBrush(g))
        p.drawEllipse(r)
        p.restore()

        px = self._icon_pixmap(body["name"], int(r.width() * 0.86))
        if px is not None and not px.isNull():
            target = QRectF(0, 0, px.width() / px.devicePixelRatio(),
                            px.height() / px.devicePixelRatio())
            target.moveCenter(r.center())
            p.drawPixmap(target.topLeft(), px)
        else:
            # No artwork for this body — a legible initial beats an empty disc.
            f = QFont()
            f.setPointSizeF(max(5.0, r.height() * 0.42))
            f.setBold(True)
            p.save()
            p.setFont(f)
            p.setPen(QPen(QColor("#232A33")))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, body["name"][:2])
            p.restore()

    def _paint_index(self, p, pal, rect, h, entry):
        """Rank glyph and its small suit mark, in the top-left corner."""
        colour = QColor(pal["red"] if entry["is_red"] else pal["black"])
        if not entry["occupied"] and not entry["is_base"]:
            colour.setAlphaF(0.74)

        f = QFont()
        f.setFamilies(_SERIF_FAMILIES)
        f.setPixelSize(max(7, int(h * _RANK)))
        f.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(f)

        left = rect.left() + h * 0.055
        top = rect.top() + h * 0.052
        p.save()
        p.setFont(f)
        p.setPen(QPen(colour))
        p.drawText(QPointF(left, top + fm.ascent()), entry["rank_display"])
        p.restore()

        mini = h * _MINI
        px = self._suit_pixmap(entry["suit_name"], int(mini), colour)
        if px is not None:
            w = fm.horizontalAdvance(entry["rank_display"])
            mr = QRectF(0, 0, px.width() / px.devicePixelRatio(),
                        px.height() / px.devicePixelRatio())
            mr.moveCenter(QPointF(left + w / 2.0,
                                  top + fm.height() * 0.86 + mini / 2.0))
            p.drawPixmap(mr.topLeft(), px)

    def _paint_position(self, p, pal, rect, h, entry, lifted):
        """The position label, optically centred on the card face.

        Absolute centring, not a flex row: a 'J' and a '10' have different
        widths, so a label laid out beside the rank would land in a different
        place on every card and the seven cards of row 2 would not line up.
        """
        text = entry["position"]
        if not text or entry["is_base"]:
            return

        size = max(7.0, min(13.0, h * 0.0525))
        f = self._label_font(size, spacing=117)
        fm = QFontMetrics(f)

        avail = rect.width() - h * 0.11
        label = text.upper()
        if fm.horizontalAdvance(label) > avail:
            label = text[:3].upper()              # SAT / JUP — degrade, don't clip
            if fm.horizontalAdvance(label) > avail:
                return

        p.save()
        p.setFont(f)
        p.setPen(QPen(pal["ink_soft"] if lifted else pal["ink_faint"]))
        band = QRectF(rect.left(), rect.top() + h * 0.074, rect.width(), fm.height())
        p.drawText(band, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)
        p.restore()

    @staticmethod
    def _card_label(entry):
        """What a row-2 card writes under its position label, or ``None``.

        Natal: the calendar year that position's 52-year period opens
        (SPEC-COT-002 D-5). Progressed: the AGE that position covers — the seven
        calendar years are already on the ruler directly above, and SPEC-COT-003
        §4.4 forbids a period year in a progressed card's corner, so the card
        answers the question the ruler does not.

        Tested on ``is not None``, never on truthiness. **Age 0 is falsy**, and
        age 0 is the ages-0-6 block, which is the acceptance case for this whole
        feature. Written as one function returning a STRING so the decision can
        be read back rather than inferred from pixels.
        """
        age = entry.get("age")
        if age is not None:
            return f"AGE {age}"
        year = entry.get("period_year")
        return None if year is None else str(year)

    def _paint_year(self, p, pal, rect, h, entry, lifted):
        """The period year — or, on a progressed card, the age — under the
        position label.

        Drawn on the card AS WELL AS on the ruler above row 2, deliberately
        (SPEC-COT-002 D-5): the ruler answers "when does this row run", the card
        answers for itself without making the eye travel. Only the seven row-2
        cards carry one; both fields are ``None`` everywhere else.
        """
        label = self._card_label(entry)
        if label is None:
            return

        f = QFont()
        f.setFamilies(_SERIF_FAMILIES)
        f.setPixelSize(max(7, int(h * _YEAR)))
        fm = QFontMetrics(f)

        colour = QColor(pal["accent"])
        if not lifted:
            colour.setAlphaF(0.62)

        # Sits under the position band, whose own top is h*0.074.
        label_h = QFontMetrics(self._label_font(
            max(7.0, min(13.0, h * 0.0525)), spacing=117)).height()
        top = rect.top() + h * 0.074 + label_h + h * 0.012

        p.save()
        p.setFont(f)
        p.setPen(QPen(colour))
        p.drawText(QRectF(rect.left(), top, rect.width(), fm.height()),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   label)
        # the short rule under the figures, as in the approved mockup
        w = fm.horizontalAdvance(label)
        rule = QColor(pal["accent"])
        rule.setAlphaF(0.42 if lifted else 0.22)
        p.setPen(QPen(rule, 1))
        y = top + fm.height() + h * 0.008
        cx = rect.center().x()
        p.drawLine(QPointF(cx - w / 2.0, y), QPointF(cx + w / 2.0, y))
        p.restore()

    def _paint_gutters(self, p, pal, rect, foot, h, entry, lifted):
        """The cusps (LEFT gutter) and the two pips (RIGHT gutter).

        **Rounded means card, squared means house.** Both gutters carry short
        tokens at nearly the same size, and the shape is the only thing telling
        a reader that ``2`` in one column is the Two of Clubs and ``2`` in the
        other is the second house. Never draw a cusp rounded or a pip squared.

        **Sides and vertical order are fixed by the conventional layout** (D-2,
        revised). The convention places the KING above the JACK with the pips in
        the RIGHT gutter and the cusp numerals on the right. We keep our own
        single-column stacks rather than corner placement — our top-right is the
        position label and our bottom edge is the occupant rail, so the corners
        are not available — but the pips go on the RIGHT and read king ABOVE
        jack, so the card lands in the expected relative place. The cusps take
        the left gutter that the pips vacated.

        The earlier arrangement was the mirror of this in both respects, which
        put the jack where the king is expected: a silent misidentification,
        since both are valid cards.

        Both stacks start OUTSIDE the inner keyline. A gutter measured from the
        card edge alone lands on top of that frame at every size, because the
        keyline inset and the gutter inset are independent fractions of ``h``
        and the mini card is nearly as wide as the gutter.
        """
        band_top = rect.top() + h * _GUT_TOP
        band_bottom = foot.top() - h * 0.02
        if band_bottom <= band_top:
            return

        # Clear the inner keyline, then a hair more so the token does not sit
        # against the frame. Measured from the frame, not from the card edge.
        gut_in = h * (_KEYLINE_INSET + 0.020)

        # ---- right gutter: the two quadration pips, KING over JACK
        mc_w, mc_h, gap = h * _MC_W, h * _MC_H, h * _MC_GAP
        stack_h = mc_h * 2 + gap
        if stack_h <= (band_bottom - band_top):
            cx = rect.right() - gut_in - mc_w / 2.0
            top = band_top + (band_bottom - band_top - stack_h) / 2.0
            for pip in (entry.get("pip_king"), entry.get("pip_jack")):
                if pip:
                    self._paint_mini_card(
                        p, pal, QRectF(cx - mc_w / 2.0, top, mc_w, mc_h),
                        h, pip, lifted)
                top += mc_h + gap

        # ---- left gutter: the cusps
        cx = rect.left() + gut_in + h * _CUSP_W / 2.0
        if not entry.get("can_hold_cusps", True):
            # Structurally impossible, not merely absent (SPEC-COT-002 §2.3):
            # this position's lord is not one of the seven, so no cusp can ever
            # land here. Drawing the "none" dash would state something false.
            return

        cusps = entry.get("cusps") or []
        if not cusps:
            if self._occupants_pending():
                # "Computed, none" and "not computed" are different facts and
                # the dash asserts the FIRST. A progressed spread normally
                # computes its cusps (SPEC-COT-006) and so draws the dash like
                # any other; this branch is only the failed-chart case, where
                # asserting "none" would be false on all seven capable cards
                # (SPEC-COT-005 INV-7). The pips above are real card data and
                # stay either way.
                return
            # CAN hold one and does not — under a varga this is real. A short
            # dash says "none", which is true here and false above.
            dash = QColor(pal["ink_faint"])
            dash.setAlphaF(dash.alphaF() * (1.0 if lifted else 0.6))
            p.save()
            p.setPen(QPen(dash, 1))
            mid = (band_top + band_bottom) / 2.0
            p.drawLine(QPointF(cx - h * 0.036, mid), QPointF(cx + h * 0.036, mid))
            p.restore()
            return

        bw, bh, cgap = h * _CUSP_W, h * _CUSP_H, h * _CUSP_GAP
        stack_h = bh * len(cusps) + cgap * (len(cusps) - 1)
        if stack_h > (band_bottom - band_top):          # 3 cusps on a small card
            cgap = 0.0
            stack_h = bh * len(cusps)
            if stack_h > (band_bottom - band_top):
                return
        top = band_top + (band_bottom - band_top - stack_h) / 2.0

        f = QFont()
        f.setFamilies(_SERIF_FAMILIES)
        f.setPixelSize(max(6, int(bh * 0.74)))
        p.save()
        p.setFont(f)
        for n in cusps:
            box = QRectF(cx - bw / 2.0, top, bw, bh)
            p.setBrush(QBrush(pal["rail_bg"]))
            p.setPen(QPen(pal["keyline"], 1))
            p.drawRect(box)                      # SQUARED — a house, not a card
            p.setPen(QPen(pal["ink_soft"] if lifted else pal["ink_faint"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(n))
            top += bh + cgap
        p.restore()

    def _paint_mini_card(self, p, pal, box, h, pip, lifted):
        """One pip: a true miniature card face, rank over suit."""
        colour = QColor(pal["red"] if pip["is_red"] else pal["black"])
        if not lifted:
            colour.setAlphaF(0.74)

        p.save()
        p.setBrush(QBrush(pal["rail_bg"]))
        p.setPen(QPen(pal["ring"], 1))
        r = box.height() * 0.13
        p.drawRoundedRect(box, r, r)             # ROUNDED — a card, not a house

        f = QFont()
        f.setFamilies(_SERIF_FAMILIES)
        # rank_display, so the ten reads 10 rather than the engine's internal T
        f.setPixelSize(max(6, int(box.height() * 0.38)))
        f.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(f)
        p.setFont(f)
        p.setPen(QPen(colour))
        p.drawText(QRectF(box.left(), box.top() + box.height() * 0.06,
                          box.width(), fm.height()),
                   Qt.AlignmentFlag.AlignCenter, pip["rank_display"])

        mark = box.height() * 0.30
        px = self._suit_pixmap(pip["suit_name"], int(mark), colour)
        if px is not None:
            mr = QRectF(0, 0, px.width() / px.devicePixelRatio(),
                        px.height() / px.devicePixelRatio())
            mr.moveCenter(QPointF(box.center().x(),
                                  box.bottom() - box.height() * 0.26))
            p.drawPixmap(mr.topLeft(), px)
        p.restore()

    def _paint_pip(self, p, pal, rect, foot, h, entry, lifted):
        """The hero suit mark — the card is the object, everything else annotates."""
        colour = QColor(pal["red"] if entry["is_red"] else pal["black"])
        if not lifted:
            colour.setAlphaF(0.68)

        size = rect.width() * (_PIP * (1.08 if entry["is_base"] else 1.0))
        px = self._suit_pixmap(entry["suit_name"], int(size), colour)
        if px is None:
            return

        # Centre in the space between the index block and the foot band, so the
        # pip is optically centred on the FACE rather than on the rectangle.
        top = rect.top() + h * (0.052 + _RANK + _MINI + 0.04)
        core = QRectF(rect.left(), top, rect.width(), foot.top() - top)
        r = QRectF(0, 0, px.width() / px.devicePixelRatio(),
                   px.height() / px.devicePixelRatio())
        r.moveCenter(core.center())
        p.drawPixmap(r.topLeft(), px)

    # ------------------------------------------------------------------ #
    # Assets
    # ------------------------------------------------------------------ #
    @staticmethod
    def _cache_put(cache, key, value):
        """Insert into a raster cache, evicting the oldest entries past a cap.

        The caches are keyed by pixel size, which was a bounded set while the
        only thing that changed it was a window resize. Zoom makes it unbounded:
        a trackpad pinch produces a continuum of sizes, and at ~160 KB per
        planet icon an afternoon of zooming would grow to hundreds of megabytes.
        Python dicts preserve insertion order, so the oldest key is the first.
        """
        cache[key] = value
        while len(cache) > _CACHE_MAX:
            cache.pop(next(iter(cache)))
        return value

    def _label_font(self, pixel_size, spacing):
        f = QFont()
        f.setPixelSize(max(6, int(round(pixel_size))))
        f.setWeight(QFont.Weight.Bold)
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
        return f

    def _suit_pixmap(self, suit_name, px, colour):
        """A suit pip at ``px`` logical pixels, tinted to ``colour``.

        Thin wrapper over the shared rasteriser: the South Indian vector view's
        in-sign card index (SPEC-COT-001 §4.10) draws the same art, and a second
        copy of the recolour composite and the DPR cache key would be a second
        place for them to drift.
        """
        return suit_pixmap(suit_name, px, colour,
                           self.devicePixelRatioF() or 1.0)

    def _icon_pixmap(self, body_name, px):
        """The app's own planet artwork, same files as the other four views."""
        if px < 2:
            return None
        dpr = self.devicePixelRatioF() or 1.0      # see _suit_pixmap on the key
        key = (body_name, px, dpr, sat_key())
        if key in self._icon_cache:
            return self._icon_cache[key]

        filename = SouthIndianView.PLANET_ICON_NAMES.get(body_name, body_name.lower())
        path = PLANETS_PATH / f"{filename}.webp"
        pixmap = None
        if path.exists():
            img = QImage(str(path))
            if not img.isNull():
                side = max(2, int(px * dpr))
                img = img.scaled(side, side,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                img = desat_image(img)
                pixmap = QPixmap.fromImage(img)
                pixmap.setDevicePixelRatio(dpr)
        return self._cache_put(self._icon_cache, key, pixmap)

    # ------------------------------------------------------------------ #
    # Interaction
    # ------------------------------------------------------------------ #
    def _body_at(self, pos):
        for rect, body in self._chip_hits:
            if rect.contains(pos):
                return body
        return None

    def _family_at(self, pos):
        """The family button under ``pos``, or ``None``.

        Painted chrome in figure coordinates, so the rects come from the last
        paint. They cannot collide with the band: the buttons sit at the foot of
        row 1 and the band occupies the gap BELOW row 1.
        """
        for rect, family in self._family_hits:
            if rect.contains(pos):
                return family
        return None

    # ------------------------------------------------------------------ #
    # The ladder (SPEC-COT-003 INV-6)
    # ------------------------------------------------------------------ #
    def _hit_band(self, pos):
        """What the band would do with a press at ``pos``, or ``None``.

        INV-6b: interaction IS allowed to branch on level, and this is the one
        place it does. Level 1 drives a window with a single wide drag target;
        levels 0/2/3 click a cell directly. Those are two real input models and
        flattening them into one would be a fake abstraction. Painters never
        see this — the AST rule that forbids per-level drawing branches is
        scoped to drawing.

        Returns ``("cell", index)``, ``("seek", x)``, ``("drag", "carriage")``
        or ``None``. ``index`` is always a DATA index on the right-to-left
        axis, never a screen slot.
        """
        geo = self._band_geo
        if geo is None or self._band_mode == "rule_only" or not self._data:
            return None
        if not (geo["left"] <= pos.x() <= geo["right"]):
            return None

        h = geo["h"]
        pad = h * 0.035            # the band is thin; hitting it must not be
        strip = geo.get("map")     # a precision task

        if strip is not None:
            shut = cot_ladder.window_rect(geo, self._window_start)
            if shut is not None and shut.adjusted(0, -pad, 0, pad).contains(pos):
                return ("drag", "carriage")
            if QRectF(strip).adjusted(0, -pad, 0, pad).contains(pos):
                return ("seek", pos.x())

        top = geo["cell_top"] - pad
        if top <= pos.y() <= geo["cell_top"] + geo["cell_h"] + pad:
            slot = cot_ladder.slot_at(geo, pos.x())
            # WINDOWED, not "is the carriage": the quadration's rail shows 45 of
            # its 90 and slides, with no map under it. Asking which level this
            # is would land every click on the quadration rail up to 45 ages
            # away from the cell the reader is pointing at.
            if geo.get("windowed"):
                return ("cell", cot_ladder.slot_index(
                    self._clamped_window(), slot, geo["cells"]))
            return ("cell", cot_ladder.to_map(slot, geo["cells"]))
        return None

    def _set_level(self, level):
        """Open ``level``. The figure re-solves, so the pan must be re-clamped.

        ``_set_zoom`` is otherwise the only caller of ``_clamp_pan``: a level
        change that skips it leaves an offset that was legal against a 0.88h
        band and out of bounds against a 0.54h one (§3.7).
        """
        level = max(cot_ladder.RAIL, min(cot_ladder.YEAR, level))
        if level == self._level:
            return False
        self._level = level
        # The window is the level's, not the family's: 13 cells at the carriage
        # and 45 at the quadration's rail, so a start that reached the end of one
        # is past the end of the other (§3.3c).
        self._clamp_window()
        self._clamp_pan()
        self.update()
        return True

    def _descend(self, index):
        """Open cell ``index`` one level down. False at the floor.

        The floor is ``_DEEPEST_WIRED``, not ``YEAR``: below it the cells would
        draw the wrong blocks under a correct breadcrumb.
        """
        if self._level >= self._deepest_wired():
            return False                  # §3.7: a stated stopping point
        self._selected[_SELECT_KEY[self._level]] = index
        if self._level == cot_ladder.RAIL:
            self._window_start = cot_ladder.window_for(
                index, total=self._line_count(),
                **self._family_kw(cot_ladder.window_for))
        return self._set_level(self._level + 1)

    # ---- the working spread (SPEC-COT-005 INV-2) ---------------------- #
    def load_block(self, index):
        """Load line cell ``index`` as the fourteen cards on screen.

        One cell of the OPEN family: a seven-year progression block, or a single
        age of the quadration (§3.3). The two lines are different lengths, so
        the bound is the family's own and not the module constant.

        The ladder is untouched: the loaded block and the open level are
        separate axes (INV-2), because a reader walks the 364-year line far more
        often than they open a block on it, and tying the two together would
        make every navigation click also change what they are reading.

        Re-assembly goes through ``update_from_chart``, which is where the
        loaded block is honoured — see INV-11. Any load path that assembles
        directly here is silently dropped by the F2 view cycle.
        """
        if self._chart is None or not (0 <= index < self._line_count()):
            return False
        if index == self._loaded_block:
            return False
        self._loaded_block = index
        self._rebuild()
        return True

    def unload_block(self):
        """Return the fourteen cards to natal, leaving the ladder alone.

        Escape stage 1 (D-2). ``_level``, ``_window_start`` and ``_selected``
        are deliberately not touched: the reader asked to stop reading a block,
        not to lose their place on the line.
        """
        if self._loaded_block is None:
            return False
        self._loaded_block = None
        self._rebuild()
        return True

    def _climb(self):
        """Back up one level, clearing the selection that was made to leave it."""
        if self._level <= cot_ladder.RAIL:
            return False
        self._selected[_SELECT_KEY[self._level]] = None
        return self._set_level(self._level - 1)

    def _seek_window(self, block):
        """Centre the carriage window on ``block``, clamped to whole ends."""
        self._window_start = cot_ladder.window_for(
            block, total=self._line_count(),
            **self._family_kw(cot_ladder.window_for))

    def _follow_window(self, block):
        """Scroll the window the minimum needed to keep ``block`` inside it.

        The OPEN LEVEL's window, not the family's: 13 at either carriage and 45
        at the quadration's rail. It is also how the keyboard reaches the far
        half of that rail — walk the selection off the edge and the row comes
        with it — so a wrong count here strands the reader at age 44.
        """
        cells = self._window_cells()
        if cells is None:
            return
        last = self._window_start + cells - 1
        if block < self._window_start:
            self._window_start = block
        elif block > last:
            self._window_start = block - cells + 1
        self._window_start = max(0, min(
            self._window_start, self._line_count() - cells))

    def _cells_on_this_level(self):
        """How many things are selectable here.

        Not ``LEVELS[level]["cells"]`` at the carriage: thirteen is how many are
        DRAWN, and the selection runs over all fifty-two with the window
        following it.
        """
        if self._level in (cot_ladder.RAIL, cot_ladder.CARRIAGE):
            return self._line_count()
        spec = getattr(cot_ladder, "level_spec", None)
        if spec is not None:
            return spec(self._level, **self._family_kw(spec))["cells"]
        return cot_ladder.LEVELS[self._level]["cells"]

    def _today_cell(self):
        """The cell nearest TODAY on the OPEN level, or ``None``.

        Per level, because "today" is a different index at each one: a block
        number on the rail and the carriage, a year WITHIN the open block at
        level 2, a 52-day period at level 3. The first draft passed the block
        number straight through, so ``today_block(age, 7)`` computed
        ``age // 7`` clamped to 0..6 and a 42-year-old opening their own block
        landed on age 48 — a plausible number, six years wrong.
        """
        age = self._current_age()
        if age is None:
            return None
        if self._level in (cot_ladder.RAIL, cot_ladder.CARRIAGE):
            # ONE cell per age on the quadration line, seven on the progression
            # (§3.3). The divisor is the family's ``unit_years``, resolved by
            # the ladder; a module-level seven would put a 45-year-old on the
            # Age 6 quadration — a plausible number, thirty-nine years wrong.
            kw = self._family_kw(cot_ladder.today_block)
            if kw:
                return cot_ladder.today_block(age, **kw)
            return max(0, min(self._line_count() - 1,
                              age // self._unit_years()))
        if self._level == cot_ladder.BLOCK:
            block = self._selected["block"]
            if block is None:
                return None
            offset = age - block * cot_ladder.BLOCK_YEARS
            # today is only in ONE block; anywhere else there is no today cell
            return offset if 0 <= offset < cot_ladder.PERIODS else None
        return None            # level 3 needs the birth DATE (SPEC-COT-004)

    def _step_selection(self, screen_dir):
        """Move the selection one cell. ``screen_dir`` +1 is rightwards ON SCREEN.

        The axis runs right to left (SPEC-COT-001 INV-5), so rightwards is a
        LOWER index. Getting this backwards is invisible in a screenshot and
        obvious the moment anyone uses it.
        """
        key = _SELECT_KEY[self._level]
        count = self._cells_on_this_level()
        current = self._selected[key]
        if current is None:
            cell = self._today_cell()
            current = cell if cell is not None else 0
        else:
            current = max(0, min(count - 1, current - screen_dir))
        self._selected[key] = current
        # Any WINDOWED level, which is now the quadration's rail as well as the
        # two carriages. Tested against the level it used to be, the selection
        # would walk on past the right-hand edge of a rail that never moved.
        if self._window_cells() is not None:
            self._follow_window(current)
        self.update()

    def _disarm_band_gesture(self):
        """Drop a band gesture in flight, WHOLE.

        Four fields describe one press and they have to die together: the armed
        hit, the drag anchor, where the press landed and whether it has latched
        into a slide. ``mouseMoveEvent`` treats an armed press as live with no
        button check, so half a disarmed gesture leaves the view re-selecting
        cells — or sliding the row — on plain mouse movement. Called wherever
        the thing the gesture was about goes away: a new chart, a different
        person, and the double click that consumes its own forwarded press.
        """
        self._band_press = None
        self._band_drag_anchor = None
        self._band_press_at = None
        self._band_slid = False
        self._press_was_cell = False

    def _can_slide_row(self):
        """Whether the cell row itself is draggable — a window with no map.

        The carriage states its window on the map strip and is dragged BY the
        bracket, so its cell row keeps re-aiming the selection. A windowed rail
        has no map, so the cells are the only thing there is to take hold of,
        and taking hold of the content is what "slide it right to left" means.
        A level question, not a family one (INV-6b).
        """
        geo = self._band_geo
        return bool(geo) and bool(geo.get("windowed")) and geo.get("map") is None

    def _became_a_slide(self, pos):
        """Whether a press on the cells has turned into a slide, and latch it.

        Half a cell of travel, and then it stays a slide until the button comes
        up: the two gestures start identically, so the reader is only committed
        once they have moved further than a wobble. Under the threshold the row
        goes on re-aiming the selection exactly as the carriage's does, which is
        what keeps a click a click on a row whose cells are 22px wide.

        Latched rather than re-tested per move, so sliding back to where you
        started does not turn the gesture back into a click and descend on
        release.
        """
        if self._band_slid:
            return True
        if not self._can_slide_row() or self._band_press_at is None:
            return False
        pitch = (self._band_geo or {}).get("cell_pitch") or 0.0
        if pitch <= 0 or abs(pos.x() - self._band_press_at[0]) < pitch * 0.5:
            return False
        self._band_slid = True
        self._band_press = ("slide", None)
        self._band_drag_anchor = self._band_press_at
        # The press has stopped being a click, so the promise it made to the
        # double click dies with it. ``mouseDoubleClickEvent`` deliberately does
        # not hit-test (INV-1a): it trusts this flag and loads whatever
        # ``_selected["block"]`` holds. Qt attributes a second press inside the
        # double-click interval to the FIRST press, so a slide followed quickly
        # by a click can arrive as a double click with no ``mousePressEvent`` in
        # between — and would then load the age that was under the finger before
        # the row moved, which is somebody else's year and nothing on screen
        # says where it came from.
        self._press_was_cell = False
        return True

    def _slide_window(self, start):
        """Put the window at ``start``, clamped to the line. Returns whether it moved."""
        cells = self._window_cells()
        if cells is None:
            return False
        start = max(0, min(int(start), self._line_count() - cells))
        if start == self._window_start:
            return False
        self._window_start = start
        return True

    def _apply_band_press(self, hit, pos):
        """The state change a press or a drag-move makes. Never descends."""
        kind, payload = hit
        if kind == "cell":
            self._selected[_SELECT_KEY[self._level]] = payload
        elif kind == "slide":
            # The CONTENT under the finger, not a viewport indicator over it, so
            # it travels WITH the cursor and the index moves the same way: drag
            # rightwards and the cells slide right, bringing the older ages in
            # from the left. That is the opposite sign from the bracket below,
            # and both are right — one drags the map, this one drags the line.
            x0, start0 = self._band_drag_anchor
            pitch = self._band_geo["cell_pitch"]
            self._slide_window(start0 + int(round((pos.x() - x0) / pitch)))
        elif kind == "seek":
            self._seek_window(cot_ladder.block_at(self._band_geo, pos.x()))
        elif kind == "drag":
            if self._band_drag_anchor is None:
                self._band_drag_anchor = (pos.x(), self._window_start)
            else:
                x0, start0 = self._band_drag_anchor
                marks = round((pos.x() - x0) / self._band_geo["map_pitch"])
                # rightwards on screen is a LOWER index, so the window start
                # moves against the cursor, not with it.
                #
                # Clamped against the OPEN FAMILY's line, not the module's 52:
                # on the quadration the far end is 90 - 13, and a drag pinned at
                # 39 simply stops moving over the last 38 ages with no message
                # and nothing broken to see.
                self._slide_window(start0 - marks)
        self.update()

    def mousePressEvent(self, event):
        """Order button, then the band, then a pan.

        The band MUST be tested before the pan branch: this method otherwise
        falls through to figure-panning for everything, so a press on the
        carriage would drag the whole spread instead of driving the window.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Cleared on EVERY press, so a press on the map strip, on the
            # chrome or on empty space disarms the double click rather than
            # leaving it holding whatever the last cell press recorded.
            self._press_was_cell = False
            if self._help_button_rect.contains(event.position()):
                self._open_help()
                event.accept()
                return
            family = self._family_at(event.position())
            if family is not None:
                # Mutually exclusive, so pressing the one already on is a
                # no-op rather than a toggle. ``set_family`` says so itself.
                self.set_family(family)
                event.accept()
                return
            hit = self._hit_band(event.position())
            # INV-1a. This is where the double click's index comes from, and it
            # is the ONLY place it can come from. By the time the double click
            # arrives, the press and release before it have already descended a
            # level, the figure has re-solved (52 rail cells become 13 carriage
            # cells, the band goes 0.54h to 0.88h, h changes and the figure
            # recentres) and _band_geo has been rewritten by the repaint. The
            # same coordinates then address different data: swept over all 52
            # rail targets, a second hit test lands on the wrong block for 48 of
            # them, and block 0 — the ages-0-6 cell, the acceptance case — falls
            # outside the level-1 band entirely and resolves to nothing.
            self._press_was_cell = (hit is not None and hit[0] == "cell")
            if hit is not None:
                self._band_press = hit
                self._band_drag_anchor = None
                # Where the press landed and where the window was, so a drag on
                # a slidable row can measure itself against the press rather
                # than against the previous mouse-move — a per-move delta loses
                # a fraction of a cell on every event and the row drifts behind
                # the cursor.
                self._band_press_at = (event.position().x(), self._window_start)
                self._band_slid = False
                self._apply_band_press(hit, event.position())
                event.accept()
                return
            self._drag_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._band_press:
            kind = self._band_press[0]
            self._band_press = None
            self._band_drag_anchor = None
            self._band_press_at = None
            slid, self._band_slid = self._band_slid, False
            if kind == "cell" and not slid:
                # Descend on RELEASE, not on press, so a press can be dragged
                # to a neighbour first — the rail's cells are 16.6px wide at
                # 1600x950 and requiring a precise hit on one of 52 would make
                # the ladder hard to enter at the size most people run.
                index = self._selected[_SELECT_KEY[self._level]]
                if index is not None:
                    self._descend(index)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_from is not None:
            self._drag_from = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()

        if self._band_press is not None:
            kind = self._band_press[0]
            if kind == "cell" and self._became_a_slide(pos):
                kind = "slide"
            if kind == "cell":
                hit = self._hit_band(pos)
                if hit is not None and hit[0] == "cell":
                    self._apply_band_press(hit, pos)
            else:
                self._apply_band_press(self._band_press, pos)
            super().mouseMoveEvent(event)
            return

        if self._drag_from is not None:
            self._pan += pos - self._drag_from
            self._drag_from = pos
            self._clamp_pan()
            self.update()
            super().mouseMoveEvent(event)
            return

        # Hover state for the painted help button needs an explicit repaint —
        # there is no Qt widget underneath to do it for us.
        over_help = self._help_button_rect.contains(pos)
        over_family = self._family_at(pos)
        over_seal = (not self._seal_rect.isEmpty()
                     and self._seal_rect.contains(pos))
        if over_help != self._help_button_hover:
            self._help_button_hover = over_help
            self.update()
        if over_family != self._family_hover:
            self._family_hover = over_family
            self.update()

        body = None if (over_help or over_family) \
            else self._body_at(event.pos())
        # Painted chrome again: nothing under the chip will repaint it for us.
        if body is not self._hover_body:
            self._hover_body = body
            self.update()

        if over_help:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(event.globalPosition().toPoint(),
                              "What this view responds to: the two mouse "
                              "gestures, the keys, and the two spreads", self)
        elif over_family is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                "The 7 year progression and the age quadration are two "
                "different timings, not two depths of one", self)
        elif over_seal:
            # D-5: the mechanics are read once, so the medallion points at the
            # place they are written rather than carrying them itself.
            self.setCursor(Qt.CursorShape.ArrowCursor)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                "The Year Card for this age. How it is found: see the ? card",
                self)
        elif body is None:
            QToolTip.hideText()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(event.globalPosition().toPoint(),
                              self._body_tooltip(body), self)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        dirty = (self._help_button_hover
                 or self._family_hover is not None
                 or self._hover_body is not None)
        self._help_button_hover = False
        self._family_hover = None
        self._hover_body = None
        if dirty:
            self.update()
        super().leaveEvent(event)

    @staticmethod
    def _body_tooltip(body):
        """Name plus position — or name plus a plain statement that the position
        could not be read. Never a fabricated 0°00'."""
        if not body.get("position_known"):
            return f"{body['name']} — position unavailable"
        retro = " ℞" if body.get("is_retrograde") else ""
        sign = body.get("sign") or ""
        return f"{body['name']}{retro}  {body['degrees']}°{body['minutes']:02d}' {sign}".strip()

    def mouseDoubleClickEvent(self, event):
        """Load a band cell as the working spread, or open the planet dialog.

        **This handler MUST NOT hit-test** (INV-1a). Qt delivers press, release,
        dblclick, release; the release in the middle has already descended and
        re-solved the figure, so testing these coordinates against the CURRENT
        geometry resolves 48 of the 52 rail targets to the wrong block and the
        ages-0-6 cell to nothing at all. The index to load is the one the FIRST
        press recorded, and ``_selected["block"]`` already holds exactly that at
        both levels — the press writes it, and at the rail ``_descend`` writes it
        again — so this needs no new index state, only a guard saying the press
        was on a cell.

        The band branch is tested BEFORE the chips, which is the one place this
        departs from SPEC-COT-005 §3.1's sketch and does so on that section's own
        trap: after the level-0 re-solve the cards have MOVED, and a handler that
        tries the chips first can open a planet dialog for whatever body has
        slid under a cursor that was aimed at the band. Nothing is lost by the
        order — a band cell and a body chip cannot overlap, since chips sit
        inside card rects and the band sits in the row1/row2 gap, so a press
        that set ``_press_was_cell`` was never a press on a chip.

        A body whose position could not be read does NOT open the dialog: the
        dialog's whole content is the position, so opening it would display
        invented coordinates. Say so in a tooltip instead.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Painted chrome, consumed WITHOUT acting. The default
            # implementation of this method forwards to mousePressEvent, so
            # anything reachable from both fires twice on a fast double click.
            # ALL painted buttons are swallowed here, and none of them acts —
            # the press has already done the acting. (The now-removed in-canvas
            # order button first exposed this: press toggled the order, the
            # forwarded double click toggled it back, and the button looked
            # dead. SPEC-FSV-001 relocated it to the status bar.)
            #
            # SPEC-COT-007 INV-11: the two family buttons are in this list and
            # this is not optional. Their first press switches family, which
            # re-assembles fourteen faces and resets the ladder; the forwarded
            # second press would switch it straight back, leaving no trace at
            # all — a button that appears not to work, with nothing in the state
            # afterwards to say what happened.
            if (self._help_button_rect.contains(event.position())
                    or self._family_at(event.position()) is not None):
                event.accept()
                return

            if self._press_was_cell:
                # INV-1c: the default forwarding also arms _band_press with no
                # release to answer it, and mouseMoveEvent treats an armed
                # _band_press as a live gesture with no button check — which
                # leaves the view re-selecting cells on plain mouse movement.
                # Cleared here, before returning, rather than hoped away.
                self._disarm_band_gesture()
                block = self._selected["block"]
                if block is not None:
                    self.load_block(block)
                event.accept()
                return

            body = self._body_at(event.pos())
            if body is not None:
                if not body.get("position_known"):
                    QToolTip.showText(event.globalPosition().toPoint(),
                                      self._body_tooltip(body), self)
                    event.accept()
                    return
                self.planet_click_signal.clicked.emit(body["name"], {
                    "sign": body.get("sign", ""),
                    "aditya_zodiac": body.get("sign", ""),
                    "sign_index": body.get("sign_index"),
                    "degrees": body["degrees"],
                    "minutes": body["minutes"],
                    "decimal_degrees": body.get("decimal_degrees") or 0.0,
                    "is_retrograde": bool(body.get("is_retrograde")),
                })
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
