"""The Cards of Truth zoom-ladder band, drawn to the round-2 mockup.

Every number in ``BAND`` and ``SPAN`` is lifted out of the round-2 CoT ruler
mockup, which expresses its whole layout as ``calc(var(--h) * k)`` — a multiple
of the solved card height. That is why this module can quote the mockup rather than
paraphrase it: the mockup's coordinate system and this view's are the same
system, so a ratio copies across unchanged and can be checked against the file.

The vertical origin here is the TOP OF ROW 2, and the band grows UPWARD from
it. The mockup measures downward from the top of its figure and lands the row-2
card tops at ``1.122h``; subtracting each of its offsets from that constant is
the only conversion applied, and it is applied once, in ``BAND``.

What the band is
----------------

Two subdivisions of the same 364 years, drawn on one line:

* the **rule** — 7 periods of 52 years, the gold hairline with its seven year
  figures. This ships today and is unchanged.
* the **band** — 52 progressions of 7 years, new. A full-width *map* of all 52,
  and a *carriage* of 13 of them magnified into readable cells.

They coincide only at the two ends, which is the point: the legend states
``52 x 7`` against ``7 x 52`` with a ``!=`` between them, and the glyph turns
into ``=`` at the ONE level where the band really does draw seven divisions --
see :func:`grids_converge`.

The two timing families
-----------------------

The band draws either of the two families Ernst separates -- the 7-year
**progression** and the Age-N **quadration** -- and it draws them with one set
of painters. :data:`FAMILIES` is to a family what :data:`LEVELS` is to a level:
the whole difference, stated as data and resolved once in :func:`band_model`
into the strings and counts the painters read.

**No painter in this module may ask which family it is drawing** (SPEC-COT-007
INV-7), exactly as none asks which level. If a painter needs to know, the
answer is a missing key in :data:`FAMILIES`, not an ``if``. What was hardcoded
to the progression before that table existed was not four things but eleven,
and the ones that bite are the quiet ones: the cell label naming a RANGE of
ages where a quadration cell is one age, the ``//`` in the magnify label
turning 6.9 into 6, and the divisor in :func:`today_block` putting a
45-year-old on the Age 6 quadration.

On colour
---------

There is no third hue. The deck is red and black, the accent is the gold that
already ships, and the two families are told apart by FORM — which side of the
legend box carries its bar, and whether the joining glyph is ``!=`` or ``=``.
An earlier attempt gave the progression tier a colour of its own and it was
wrong twice over: wrong because a playing card has two colours, and wrong
because the value it reached for, ``get_theme_colors()["primary"]``, reads an
environment variable that nothing in this codebase sets, so it is a constant
blue whatever theme is on.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainterPath, QPen,
)

from apps.widgets.card_suit_art import suit_pixmap

#: Cells in the carriage. 13 of 52, so the window is a quarter of the line and
#: the magnification reads as x4 without having to be labelled a ratio.
#:
#: **The PROGRESSION family's number.** The quadration carriage is 13 as well,
#: and deliberately so (SPEC-COT-007 §3.3) — the two families look identical at
#: level 1 and only the density beneath differs. Read it from
#: :data:`FAMILIES` rather than from here in anything that can see two families.
WINDOW_CELLS = 13

#: Marks on the map. All 52, never a lived-only subset (SPEC-COT-003 INV-6).
#: The progression's line; the quadration's map carries 90.
MAP_MARKS = 52

#: Progressions on the whole line. Same number as MAP_MARKS by construction;
#: named separately because one is a count of periods and the other is a count
#: of things drawn, and they stop being the same the moment anything is cropped.
LINE_BLOCKS = 52

#: Periods inside one block, and inside one year. Both sevens, and they are the
#: same seven only at level 2 -- see :func:`grids_converge`.
PERIODS = 7

#: Years in one progression block. Equal to PERIODS by construction, since a
#: block IS seven one-year cells — but it is a length in years, not a count of
#: drawn things, and reusing PERIODS for it would make an age calculation look
#: like a layout constant.
BLOCK_YEARS = 7


# ------------------------------------------------------------------ #
# the four levels, as data (SPEC-COT-003 INV-1)
# ------------------------------------------------------------------ #

#: The narrowest cell in which an 8px rank digit still reads, with a pixel of
#: air either side. Qt floors a font at 8px, so this does NOT scale with h and
#: is the reason each level has its own height floor rather than sharing one.
MIN_CELL_WIDTH_PX = 11.0

#: Figure width as a multiple of h. Mirrors the view's ``_W_UNITS``; kept here
#: so a level's minimum height can be solved without importing the widget.
FIG_W_UNITS = 5.768

#: RAIL is the default: the whole 364 years at once, small enough not to
#: bother a reader who never opens the predictive tools (D-1).
RAIL, CARRIAGE, BLOCK, YEAR = 0, 1, 2, 3

#: Everything that differs between levels, and nothing that does not. Adding a
#: level adds a row here; it never adds an ``if level ==`` to a painter.
#:
#: ``band``      height of the whole band, as a multiple of h (INV-2)
#: ``cells``     how many cells the row carries
#: ``windowed``  whether those cells are a WINDOW of the line that slides, or
#:               the whole line standing still. See below — this is NOT the
#:               same question as ``magnify``
#: ``magnify``   whether a map + window bracket + funnel is drawn under it
#: ``rounded``   rounded cells mean CARD, squared mean a division of one
#:               (INV-1d; the same grammar the card gutters already use)
#: ``comb``      the notch comb meaning "another level waits inside this one";
#:               false at the floor, where nothing waits
#:
#: **``windowed`` and ``magnify`` were one key and are two** (SPEC-COT-007
#: §3.3c). ``windowed`` says the row shows part of the line and therefore needs
#: a ``window_start``, a clamp, a slide and a window-aware hit test.
#: ``magnify`` says a MAP STRIP is drawn beneath it with the window bracketed on
#: it — the carriage's whole look. The carriage is both; the quadration rail is
#: windowed and not magnified, and there was no way to say that while the two
#: were one word. A boolean rather than a second count, because the count is
#: already ``cells`` and two numbers for one quantity drift.
LEVELS = {
    RAIL:     {"band": 0.54, "cells": 52, "windowed": False, "magnify": False,
               "rounded": True,  "comb": True,  "name": "rail"},
    CARRIAGE: {"band": 0.88, "cells": 13, "windowed": True,  "magnify": True,
               "rounded": True,  "comb": True,  "name": "carriage"},
    BLOCK:    {"band": 0.54, "cells": 7,  "windowed": False, "magnify": False,
               "rounded": True,  "comb": True,  "name": "block"},
    YEAR:     {"band": 0.54, "cells": 7,  "windowed": False, "magnify": False,
               "rounded": False, "comb": False, "name": "year"},
}


# ------------------------------------------------------------------ #
# the two timing FAMILIES, as data (SPEC-COT-007 INV-7)
# ------------------------------------------------------------------ #

#: The two timing families Ernst distinguishes: a quadration cycle and a
#: progression, which are two different things. They are peers, not rungs of
#: one ladder.
PROGRESSION = "progression"
QUADRATION = "quadration"

#: The quadration's own level table. TWO rows, and there is nothing below the
#: carriage (SPEC-COT-007 D-6): the seven 52-card-day periods ARE row 2 of the
#: spread, each card already carrying its own period start date, so a third
#: level would redraw seven cards that are already on the table.
#:
#: ``comb`` is therefore FALSE at the carriage — the comb means "another level
#: waits inside this one", and here nothing does. It stays true at the rail,
#: where the carriage waits. Same band heights as the progression's two, which
#: is what makes the two families look identical at level 1.
#:
#: **The rail draws 45 of the 90, and slides for the other half** (SPEC-COT-007
#: §3.3c, decided on screen 2026-07-28). All 90 at once crams the width the
#: progression uses for 52 into cells 42% narrower — under the glyph floor at
#: every ordinary window size, so the row runs as bars and reads as a barcode.
#: Half the line puts 45 cells on that width, which is FEWER than the
#: progression's 52 and therefore a slightly WIDER cell: the two families now
#: read at the same size, which is what was asked for. The cost is that half the
#: line is off screen at any moment, and that is what the slide is for.
QUAD_LEVELS = {
    RAIL:     {"band": 0.54, "cells": 45, "windowed": True,  "magnify": False,
               "rounded": True,  "comb": True,  "name": "rail"},
    CARRIAGE: {"band": 0.88, "cells": 13, "windowed": True,  "magnify": True,
               "rounded": True,  "comb": False, "name": "carriage"},
}


def _cell_ages(cell, unit_years):
    """The age range one cell covers, from whatever the cell carries.

    ``progression_blocks`` states ``age_start``/``age_end`` outright.
    ``quadration_ages`` is one age per cell and need not restate what the index
    already says, so both shapes are read here rather than in four labellers.
    ``0`` is a legitimate age at both ends, so every fallback tests for None and
    never for falsiness.
    """
    start = cell.get("age_start")
    if start is None:
        start = cell.get("age")
    if start is None:
        start = cell["index"] * unit_years
    end = cell.get("age_end")
    if end is None:
        end = start + unit_years - 1
    return start, end


def _cell_years(cell, unit_years):
    """The calendar years one cell covers, or ``(None, None)`` if unknown."""
    start = cell.get("year_start")
    if start is None:
        start = cell.get("year")
    if start is None:
        return None, None
    end = cell.get("year_end")
    if end is None:
        end = start + unit_years - 1
    return start, end


def cell_face(cell, spec):
    """The card descriptor a cell is DRAWN from — and it is not the same key.

    This is the one place the two families genuinely disagree about their own
    data, and it is invisible in a unit test that only counts cells.

    On the progression line the BASE card moves: block 0 is the birth card,
    block 1 is the next Solar Value along, and ``base_card`` is what the reader
    is looking at. On the quadration line it cannot move —
    ``get_birthspread_from_quadration`` opens every quadrated deck AT the birth
    card, so seat 0 holds it at all 90 ages by construction. A rail painted from
    ``base_card`` there draws ninety identical cells: no suit runs, no gates,
    nothing to read, and every headless assertion still green.

    What discriminates one age from the next is the YEAR CARD, so that is what
    the quadration's ``cell_card_key`` names.

    Falls back to ``card`` when the family's key is absent or ``None``: without
    a birth date there IS no Year Card (``quadration_ages`` says so by returning
    None), and 90 birth cards is then the honest picture rather than a crash.
    """
    face = cell.get(spec["cell_card_key"])
    return cell["card"] if face is None else face


def _span_label(cell, spec):
    """``AGES 84-90`` — a progression cell is a range of ages."""
    a, b = _cell_ages(cell, spec["unit_years"])
    return f"AGES {a}-{b}"


def _age_label(cell, spec):
    """``AGE 45`` — a quadration cell is ONE age, and says so.

    Reusing the range form here would print ``AGES 45-45``, which reads as a
    formatting accident rather than as the fact that the unit changed.
    """
    a, _ = _cell_ages(cell, spec["unit_years"])
    return f"AGE {a}"


def _span_years(cell, spec):
    """``2075-2082``, or empty where the band has no birth year."""
    a, b = _cell_years(cell, spec["unit_years"])
    return "" if a is None else f"{a}-{b}"


def _one_year(cell, spec):
    """``2036`` — one age is one calendar year, so a range would be a lie."""
    a, _ = _cell_years(cell, spec["unit_years"])
    return "" if a is None else f"{a}"


def _span_step(cell, spec):
    """One breadcrumb step naming a progression block."""
    a, b = _cell_ages(cell, spec["unit_years"])
    return f"ages {a}-{b} · {cell_face(cell, spec)['display_symbol']}"


def _age_step(cell, spec):
    """One breadcrumb step naming an Age-N quadration.

    The card named is the YEAR CARD (:func:`cell_face`). Naming the base card
    would print the birth card in the trail at every one of the 90 ages.
    """
    a, _ = _cell_ages(cell, spec["unit_years"])
    return f"age {a} · {cell_face(cell, spec)['display_symbol']}"


def _magnify_label(line, window):
    """``magnified x4`` / ``magnified x6.9`` — the ratio, never a typed number.

    52 / 13 is exactly 4 and reads as an integer; 90 / 13 is 6.923 and reads to
    one decimal. The shipped string was ``f"magnified x{MAP_MARKS //
    WINDOW_CELLS}"``, which is 4 for the progression and 6 for the quadration —
    a wrong number that looks like a right one.
    """
    ratio = line / float(window)
    text = f"{ratio:.1f}".rstrip("0").rstrip(".")
    return f"magnified x{text}"


#: Everything that differs between the two families, and nothing that does not.
#: The same shape as :data:`LEVELS`, one rung up: a painter resolves a FAMILY to
#: data exactly as it resolves a level, and never asks which one it is drawing
#: (INV-7). An ``if family ==`` inside a painter means a key is missing here.
#:
#: ``levels``          the family's own level table; the progression's IS LEVELS
#: ``line``            cells on the rail — the whole line
#: ``window``          cells in the carriage; 13 in BOTH, deliberately (§3.3)
#: ``unit_years``      years one rail cell covers
#: ``cell_card_key``  WHICH card of a cell is drawn; the families differ (see
#:                     :func:`cell_face`) and the difference is invisible in a
#:                     test that only counts cells
#: ``periods``         divisions inside one cell, drawn as the comb's teeth
#: ``mark_years``      the step, IN YEARS, between the verticals drawn under a
#:                     cell row; ``None`` draws none (see :func:`year_marks`)
#: ``mark_labelled``   whether each of those verticals carries a calendar year.
#:                     The progression's do not: the rule below already writes
#:                     seven years across the same 364, one per row-2 card, and
#:                     the verticals are there to show the two grids MISSING
#:                     each other. A quadration's rule writes card-day dates for
#:                     ONE age, so the band's own line carries no year reference
#:                     at all unless these marks supply it
#: ``lifetime_cells``  the lifetime bracket on the map; ``None`` draws none
#: ``converge_at``     the ONE level where band and rule draw the same seven
#: ``deepest``         the deepest level that has data behind it
#: ``palette_key``     which entry of the palette the accent comes from. GOLD
#:                     for both families today, and that is a decision, not an
#:                     omission. SPEC-COT-007 INV-8 AS FIRST DRAFTED asked the
#:                     progression to take ``get_theme_colors()["primary"]``,
#:                     but that clause was STRUCK the day it was written because
#:                     SPEC-COT-003 D-5 / AC-6 forbid exactly that — the function
#:                     reads an environment variable nothing sets, so it is a
#:                     constant blue in a red-and-black card system
#:                     (SPEC-COT-003 §2.4). INV-8 now reads: both families gold,
#:                     no second hue. The slot exists so a second colour arrives
#:                     as a table edit if that function is ever fixed; the value
#:                     stays gold until it is.
FAMILIES = {
    PROGRESSION: {
        "name": PROGRESSION,
        "label": "7 Year Progression",
        "levels": LEVELS,
        "line": 52,
        "window": 13,
        "unit_years": 7,
        "periods": 7,
        # the base card MOVES on this line, and it is what the reader reads
        "cell_card_key": "card",
        "mark_years": 52,
        "mark_labelled": False,
        # The progression's 52-year marks ARE its only ruler, so they draw at
        # every level whether or not a block is loaded (WI-7 / D-10 leaves this
        # family untouched: marks_idle_only False).
        "marks_idle_only": False,
        "lifetime_cells": 13,
        "converge_at": BLOCK,
        "deepest": CARRIAGE,
        "span_label": "364 years",
        "cell_label": _span_label,
        "cell_years": _span_years,
        "crumb_step": _span_step,
        "caption_left": "52 progressions of 7 years, on the same 364 years "
                        "as the seven periods below",
        "caption_right": "a lifetime · 13 of 52",
        "palette_key": "accent",
    },
    QUADRATION: {
        "name": QUADRATION,
        "label": "Age Quadration",
        "levels": QUAD_LEVELS,
        # 90, because that is where the quadration repeats: the 90th quadration
        # is the last one that differs from the first, and the 91st matches the
        # first again.
        "line": 90,
        "window": 13,
        "unit_years": 1,
        "periods": 7,
        # NOT "card": the base seat holds the birth card at all 90 ages, so a
        # rail drawn from it is ninety identical cells. The Year Card is the
        # datum that moves — see :func:`cell_face`.
        "cell_card_key": "year_card_face",
        # DECADE marks, and they are not the progression's instrument wearing a
        # different number. §3.3b set this to None and gave the reason: the band
        # spans 90 ages against the rule's 364, so a mark at "age 52" would sit
        # at an x that means something else on the rule below. It ends with "a
        # mark there would need a different definition, not this one" — and this
        # is that definition. These verticals divide the band's OWN span into
        # decades and each carries the calendar year it falls on, so they assert
        # nothing about the rule; they are the year reference the quadration
        # line otherwise has none of (SPEC-COT-007 §3.3c).
        "mark_years": 10,
        "mark_labelled": True,
        # WI-7 / D-10 — one ruler at a time. The decade marks are the IDLE
        # year reference for the band; once an Age-N spread is loaded the
        # spread carries its own dated 7-period ruler, and the two must never
        # be on screen together. So these marks draw only while no spread is
        # loaded (marks_idle_only True); the progression's do not have this
        # flag set and are unaffected.
        "marks_idle_only": True,
        # The line IS one life, so a bracket around all of it marks nothing.
        "lifetime_cells": None,
        # The rule always draws seven 52-year periods; a quadration band draws
        # 90 or 13. There is no level at which they agree.
        "converge_at": None,
        "deepest": CARRIAGE,
        "span_label": "90 ages",
        "cell_label": _age_label,
        "cell_years": _one_year,
        "crumb_step": _age_step,
        # WI-8 / D-11: the quadration teaching moved OFF the rail and into the
        # help card (Lorris: the caption "is annoying"). The "45 of 90" count
        # already lives in the idle breadcrumb (§3.3c), so both caption sides
        # are empty and the berth stays clear at every level. The progression
        # captions are untouched.
        "caption_left": "",
        "caption_right": "",
        "palette_key": "accent",
    },
}

#: The family assumed by every call that does not name one. The progression is
#: what shipped, so a caller written before SPEC-COT-007 keeps its behaviour to
#: the byte — including the carriage's pixel-identical render (AC-3).
DEFAULT_FAMILY = PROGRESSION


def family_spec(family=DEFAULT_FAMILY):
    """The family's row of :data:`FAMILIES`. One lookup, one error message."""
    try:
        return FAMILIES[family]
    except KeyError:
        raise KeyError(f"unknown timing family {family!r}; "
                       f"known: {sorted(FAMILIES)}") from None


def level_spec(level, family=DEFAULT_FAMILY):
    """The level's row, resolved WITHIN a family.

    Two tables, one lookup: the family picks the level table and the level
    picks the row. Neither step is a branch, which is what INV-1 and INV-7 both
    ask for, and it is why the quadration can have two levels while the
    progression has four without a single caller learning the difference.
    """
    levels = family_spec(family)["levels"]
    try:
        return levels[level]
    except KeyError:
        raise KeyError(f"level {level} does not exist in the {family} family; "
                       f"it has {sorted(levels)}") from None


def levels_of(family=DEFAULT_FAMILY):
    """The levels this family offers, shallowest first."""
    return tuple(sorted(family_spec(family)["levels"]))


def window_cells(level, family=DEFAULT_FAMILY):
    """How many cells this level shows as a WINDOW of the line, or ``None``.

    ``None`` means the row IS the line: nothing to slide, nothing to clamp, and
    a slot converts to an index without consulting a start. Read this rather
    than testing the level, because the answer is 45 at the quadration's rail,
    13 at either carriage and None at the progression's rail — three different
    answers from one table.
    """
    spec = level_spec(level, family)
    return spec["cells"] if spec["windowed"] else None


def deepest_wired(family=DEFAULT_FAMILY):
    """The deepest level with real data behind it.

    The same number for both families today and for opposite reasons: the
    progression's levels 2 and 3 are unbuilt, and the quadration HAS no level
    below its carriage. Recording it per family keeps those two facts apart.
    """
    return family_spec(family)["deepest"]


def year_marks(family=DEFAULT_FAMILY, level=RAIL, window_start=0,
               birth_year=None):
    """The verticals under a cell row, right to left, as DATA.

    Returns ``[{"frac": f, "line": bool, "label": str|None}, ...]`` where
    ``frac`` is a fraction of the band width measured from the LEFT edge.
    Deliberately fractional: rounding a mark to the nearest cell edge would make
    the two grids appear to agree, which is the one thing the progression's
    marks exist to deny.

    Six lines for the progression, because 364 years hold six interior 52-year
    boundaries — a number that used to be typed as ``range(1, PERIODS)`` and
    now falls out of the family's own span.

    **Measured against the DRAWN row, not against the whole line.** A windowed
    row shows ``cells * unit_years`` years starting at ``window_start``, so a
    mark's position depends on where the window is; a mark placed against the
    line would sit still while the cells under it slid, which is exactly the
    complaint that produced this function ("the rules stay fixed"). On an
    unwindowed row ``window_start`` is 0 and the span is the whole line, which
    is the progression's case and reproduces its six fractions to the float.

    Interior marks carry a LINE. The ends do not — a vertical on the band's own
    edge reads as a box, not as a division — but they still carry a LABEL where
    the family asks for one, because the year at the right edge is the one the
    reader most wants (it is where they are).

    Nothing at a magnified level: the map strip is what says where the window
    sits there, and a second row of marks under the carriage would be a second
    answer to a question already answered.
    """
    fam = family_spec(family)
    spec = level_spec(level, family)
    step = fam["mark_years"]
    if not step or spec["magnify"]:
        return []

    unit = fam["unit_years"]
    span = spec["cells"] * unit                 # years across the DRAWN row
    if span <= 0:
        return []
    start = (window_start if spec["windowed"] else 0) * unit
    labelled = bool(fam["mark_labelled"]) and birth_year is not None

    marks = []
    first = int(math.ceil(start / float(step)))
    for k in range(first, int((start + span) // step) + 1):
        years = k * step
        frac = 1.0 - (years - start) / float(span)
        interior = 0.0 < frac < 1.0
        if not interior and not labelled:
            continue                            # an end with nothing to say
        marks.append({"frac": min(1.0, max(0.0, frac)),
                      "line": interior,
                      "label": str(birth_year + years) if labelled else None})
    return marks


def band_height(level, family=DEFAULT_FAMILY):
    """Band height for ``level``, as a multiple of the card height (INV-2).

    The rail's whole point is to be small, so pinning every level to the
    carriage's 0.88h would leave 0.34h of air in the default view and shrink
    the cards for nothing. The figure therefore re-solves on a level change.

    It does NOT re-solve on a family change: both families give the rail 0.54h
    and the carriage 0.88h, so switching family at a fixed level leaves the
    figure exactly where it was and only the density inside the band moves.
    """
    return level_spec(level, family)["band"]


#: The narrowest BAR that still reads as a mark rather than as noise. Below the
#: glyph floor the cells lose their ranks and become this; below this they are
#: not drawn at all.
MIN_BAR_WIDTH_PX = 3.0


def min_height_for(level, family=DEFAULT_FAMILY):
    """Smallest ``h`` at which ``level``'s cells can carry a RANK (INV-5b).

    Solved from :data:`MIN_CELL_WIDTH_PX`, not chosen. One shared constant was
    what v2.0 of the spec had, and it was a carriage number: 52 rail cells
    across the same width are four times narrower than 13, so a floor tuned on
    the carriage passes a 5.2px rail cell without noticing.

    Rail 99, carriage 25, seven-cell levels 13 — and 86 for the QUADRATION
    rail, whose 45 cells are FEWER than the progression's 52 and therefore
    wider, with a lower floor. It was 172 while that rail drew all 90 at once,
    which put it above every h this view solves at an ordinary window size and
    is why the row ran as bars and read as a barcode (§3.3c).
    """
    return MIN_CELL_WIDTH_PX * level_spec(level, family)["cells"] / FIG_W_UNITS


def min_bar_height_for(level, family=DEFAULT_FAMILY):
    """Smallest ``h`` at which ``level`` is drawn AT ALL, as bars.

    The rung between "readable" and "gone". A rail at h = 86 — a 700x560 panel,
    which is an ordinary size for this view — cannot carry 52 rank glyphs, and
    dropping straight to the bare rule would take away the default view on a
    window people actually use. What it CAN still carry is the thing the ranks
    were only ever a second reading of: the suit runs, the six 52-year
    boundaries and TODAY. That is a true figure, and it is the same barcode the
    carriage level already draws under its window.

    Rail 27, carriage 7, seven-cell levels 4 — all below the view's own 34.0
    clamp for every level but the rail, which is another way of saying only the
    rail ever reaches this rung.
    """
    return MIN_BAR_WIDTH_PX * level_spec(level, family)["cells"] / FIG_W_UNITS


def grids_converge(level, family=DEFAULT_FAMILY):
    """Whether the band and the rule are drawing the SAME seven divisions.

    The rule always draws seven. The band draws seven only at
    :data:`BLOCK` -- the seven one-year parts -- so that is the one level where
    the legend's joining glyph becomes ``=``. The quadration never draws seven
    of anything, so its ``converge_at`` is ``None`` and the glyph stays ``≠``
    at both of its levels.

    Was ``level >= 1``, which marked them as agreeing at :data:`CARRIAGE`,
    where the band draws THIRTEEN cells, and went on claiming it at
    :data:`YEAR`, where the units are days. The error came from renumbering:
    the round-2 mockup put the seven one-year cells at ITS level 1, and
    inserting the rail as level 0 moved every level down without moving this.

    A threshold is the wrong shape here in both directions. Convergence is a
    property of one level, not a state entered and never left.
    """
    at = family_spec(family)["converge_at"]
    return at is not None and level == at

#: Heights and offsets, in multiples of the card height ``h``, measured UP from
#: the top of row 2. Mockup value on the right, as it appears in the file.
#: One documented deviation, of +0.04h, applied to everything ABOVE the caption
#: line. The mockup renders at h = 200 and gives its caption a 0.058h berth,
#: which is 11.6px there and 8.3px at the h = 143 this view actually solves for
#: at 1600x950. Qt floors a font at 8px, so at our size the berth and the text
#: are the same height and the sentence touches both the map above it and the
#: year figures below. The mockup's ratio is right for the mockup's h; the extra
#: 0.04h buys back what the font floor takes and nothing else moves.
_BERTH = 0.040

BAND = {
    "crumb":     0.822 + _BERTH,   # 0.300  breadcrumb and legend line
    "carr_top":  0.742 + _BERTH,   # 0.380  carriage trough
    "carr_h":    0.301,            # 0.301
    "cell_top":  0.724 + _BERTH,   # 0.398  the 13 cells inside it
    "cell_h":    0.265,            # 0.265
    "fun_top":   0.450 + _BERTH,   # 0.672  funnel from window to carriage
    "fun_h":     0.058,            # 0.058
    "map_top":   0.392 + _BERTH,   # 0.730  the 52-mark map
    "map_h":     0.090,            # 0.090
    "cap_top":   0.288,            # 0.834  caption line
    "cap_h":     0.048,            # 0.048
    "year_top":  0.244,            # 0.878  the rule's seven year figures
    "tick_top":  0.154,            # 0.968  its ticks
    "rule":      0.110,            # 1.012  the rule itself
}

#: Sizes inside the band, also multiples of ``h``.
SPAN = {
    "cell_gap":    0.0,      # cells are edge to edge; the border separates them
    "cell_radius": 0.026,
    "cell_bar":    0.010,    # the suit-coloured strip along a cell's top edge
    "cell_inset":  0.020,    # the inner keyline, a card's double frame
    "cell_pad":    0.030,
    "rank":        0.075,    # rank glyph in a carriage cell
    "cell_pip":    0.052,
    "cell_lab":    0.029,    # "AGES 84-90"
    "cell_yrs":    0.036,    # "2075-2082", serif
    "comb":        0.018,    # the seven notches waiting to be the next level
    "comb_sub":    0.030,
    "mark_w":      0.560,    # of one map pitch
    "mark_h":      0.032,
    "gate_w":      0.008,    # suit-run divider on the map
    "gate_h":      0.114,
    "shut_over":   0.022,    # window bracket, beyond the map box
    "shut_h":      0.134,
    "shut_r":      0.014,
    "shut_tick":   0.024,
    "anch_h":      0.118,    # TODAY
    "anch_tri":    0.030,
    "life_h":      0.014,
    "run_label":   0.032,
    "small":       0.024,    # "MAGNIFIED x4", "A LIFETIME - 13 OF 52"
    "crumb_txt":   0.034,
    "legend_txt":  0.023,
    "legend_num":  0.030,
    "legend_pad":  0.040,
    "legend_padv": 0.016,
    "legend_bar":  0.012,
    "join":        0.052,
}


#: The Deck Rail's own offsets, from
#: ``.../2026-07-27-cot-ruler-v3/opus/mockups.html``, design I. Its figure puts
#: the row-2 card tops at ``0.990``, so each value here is
#: ``0.990 - <mockup value>``; the mockup value is in the comment, as with BAND.
#:
#: The rail is a THIRD the band's height and carries no magnifier, which is the
#: whole reason it is the default: the reader who never opens the predictive
#: tools gets one thin row instead of a carriage.
RAIL_BAND = {
    "crumb":     0.640,   # 0.350  the edge label, "later - 364 years - one deck"
    "cell_top":  0.530,   # 0.460  the 52 cells
    "cell_h":    0.200,   # 0.200
    "bdy_top":   0.550,   # 0.440  the six 52-year boundary verticals
    "bdy_h":     0.435,   # 0.435
    "today_top": 0.545,   # 0.445  TODAY needle
    "today_h":   0.245,   # 0.245
    # The year figures a mark may carry, in the one clear strip the figure has:
    # from the bottom of the cell row (0.530 - 0.200) down to the top of the
    # RULE's own year row, which the view berths at ``BAND["year_top"]`` at
    # every level. Both ends are therefore quoted, not chosen — widening this
    # row means moving something that belongs to another tier.
    "mark_top":  0.330,   #        = cell_top - cell_h
    "mark_h":    0.086,   #        = mark_top - BAND["year_top"]
    "cap_top":   0.330,   #        below the cells; the rail has no map
    "cap_h":     0.045,
    "year_top":  0.285,   # 0.705  the rule's seven year figures
    "tick_top":  0.160,   # 0.830  its ticks
    "rule":      0.115,   # 0.875  the rule itself
}

#: Which offset table each level uses. The seven-cell levels reuse the rail's:
#: they are the same shape at a different count, which is the point of INV-1.
#: The magnified level uses the carriage's offsets; every other level uses the
#: rail's. Keyed by level and shared by both families, because the OFFSETS are
#: the same picture at a different density — which is exactly what makes the
#: two families look identical at level 1 (SPEC-COT-007 §3.3).
GEOM = {RAIL: RAIL_BAND, CARRIAGE: BAND, BLOCK: RAIL_BAND, YEAR: RAIL_BAND}


def band_geometry(h, row2, level=CARRIAGE, family=DEFAULT_FAMILY):
    """Solve the band from the card height, the row-2 rect, level and family.

    One function, so the painter and the hit-tester cannot disagree about where
    a cell is. Everything is a rect; nothing is recomputed downstream.

    The level selects a ROW of :data:`GEOM` and the family selects a row of
    :data:`FAMILIES`. Both are table lookups and neither is a branch: the code
    below never asks which level or which family it is solving, and adding
    either means adding a row.

    The counts the geometry was solved with travel ON the geo dict — a
    hit-tester that re-derived them from the module constants would agree with
    the painter on the progression and disagree with it on the quadration,
    which is the sort of divergence that only shows up as a click landing one
    cell away.
    """
    left, width = row2.left(), row2.width()
    top = row2.top()
    fam = family_spec(family)
    band = GEOM[level]
    spec = level_spec(level, family)
    cells = spec["cells"]
    marks = fam["line"]

    def y(key, default=None):
        v = band.get(key, default)
        return None if v is None else top - h * v

    geo = {
        "h": h, "level": level, "family": fam["name"],
        "left": left, "right": left + width, "width": width,
        "row2_top": top,
        "cells": cells,
        # Whether a slot on this row means ``window_start + ...`` or the index
        # outright. It travels ON the geo because the hit-tester reads the geo
        # and the painter reads the model, and the two must not answer this
        # question from different tables.
        "windowed": spec["windowed"],
        "map_marks": marks,
        # the BRACKET's width on the map, which is the carriage's cell count in
        # both families. Not the same quantity as ``cells`` any more: a windowed
        # rail has a window of its own and no bracket to draw it with.
        "window_cells": fam["window"],
        "crumb_y": y("crumb"),
        "cell_top": y("cell_top"),
        "cell_h": h * band["cell_h"],
        "cell_pitch": width / cells,
        "map_pitch": width / marks,
        "cap": QRectF(left, y("cap_top"), width, h * band["cap_h"]),
        "year_y": y("year_top"),
        "tick_y": y("tick_top"),
        "rule_y": y("rule"),
    }
    # magnifier furniture, present only where a map is drawn
    if "carr_top" in band:
        geo["carriage"] = QRectF(left, y("carr_top"), width, h * band["carr_h"])
        geo["funnel"] = QRectF(left, y("fun_top"), width, h * band["fun_h"])
        geo["map"] = QRectF(left, y("map_top"), width, h * band["map_h"])
    else:
        # the cell row is its own trough; the chrome above measures against it
        geo["carriage"] = QRectF(left, geo["cell_top"], width, geo["cell_h"])
        geo["bdy_top"] = y("bdy_top")
        geo["bdy_h"] = h * band["bdy_h"]
        geo["today_top"] = y("today_top")
        geo["today_h"] = h * band["today_h"]
        if "mark_top" in band:
            geo["marks"] = QRectF(left, y("mark_top"), width,
                                  h * band["mark_h"])
    return geo


def cell_rect(geo, slot):
    """Rect of cell ``slot`` (0 leftmost). Slots are edge to edge."""
    return QRectF(geo["left"] + slot * geo["cell_pitch"], geo["cell_top"],
                  geo["cell_pitch"], geo["cell_h"])


def to_map(index, count=MAP_MARKS):
    """Drawing POSITION of ``index``, counted from the left edge, out of ``count``.

    Row 2 reads right to left with the Sun and the birth year at the right
    (SPEC-COT-001 INV-5), and the band shares its axis or the two tiers would
    run in opposite directions on one line. So index 0 — the birth block, the
    first year, the first 52-day period — is the RIGHTMOST, and the numbers
    grow leftward into the future. Everything horizontal goes through this
    function; iterating and drawing left to right is the plausible, wrong
    version.

    ``count`` is a PARAMETER (INV-1b). It was hardcoded to 52, which is right
    for the rail and the map and silently wrong for every other level: a
    seven-cell level asking for index 0 got position 51.
    """
    return count - 1 - index


def slot_index(window_start, slot, cells=WINDOW_CELLS):
    """Index shown in ``slot`` of a ``cells``-wide window starting at ``window_start``.

    With ``window_start`` 0 this is :func:`to_map` — an unwindowed row is the
    degenerate window that starts at the beginning of the line — which is why
    the cell row needs only this one converter and no branch.
    """
    return window_start + (cells - 1 - slot)


def index_slot(window_start, index, cells=WINDOW_CELLS):
    """Which SLOT shows ``index``, or ``None`` when it is outside the window.

    The inverse of :func:`slot_index`, and it exists because a marker placed by
    index — TODAY — has to be placed by slot. Reading it as ``to_map(index)``
    ignores the window: on a rail sliding through ninety ages that draws the
    needle at the right cell only while the window sits at the start of the
    line, and thirty-five cells away from the truth once it has moved.
    """
    slot = (cells - 1) - (index - window_start)
    return slot if 0 <= slot < cells else None


def window_for(block, cells=None, total=None, family=DEFAULT_FAMILY):
    """Where the window sits when the reader descends onto ``block``.

    Centred on the clicked block, clamped to whole ends. Centre rather than
    edge because the neighbours are what give a block its context, and a reader
    who clicked block 30 wants to see 24-36, not 30-42.

    ``cells`` and ``total`` default to the FAMILY's, so the clamp at the far end
    is 52 - 13 on a progression and 90 - 13 on a quadration. Left as module
    constants they would pin a quadration window 38 cells short of its own end,
    silently, and only at the end of the line.
    """
    fam = family_spec(family)
    cells = fam["window"] if cells is None else cells
    total = fam["line"] if total is None else total
    return max(0, min(block - (cells - 1) // 2, total - cells))


def mark_x(geo, position):
    """Centre x of the map mark at ``position`` (already a map position)."""
    return geo["left"] + (position + 0.5) * geo["map_pitch"]


def window_rect(geo, window_start):
    """The carriage bracket on the 52-mark map — level 1's one drag target.

    A FUNCTION, not a value the painter stashes on ``geo`` as it draws. The
    band rasters into a pixmap in band-LOCAL coordinates, so anything written
    onto the geo dict during painting is written onto a throwaway copy; a
    hit-tester reading it back off the view's absolute geo would find nothing
    there and silently never match. Returns ``None`` where there is no map.
    """
    mp = geo.get("map")
    if mp is None:
        return None
    h = geo["h"]
    marks = geo.get("map_marks", MAP_MARKS)
    cells = geo.get("window_cells", WINDOW_CELLS)
    x0 = geo["left"] + to_map(window_start + cells - 1, marks) * geo["map_pitch"]
    return QRectF(x0, mp.top() - h * SPAN["shut_over"],
                  cells * geo["map_pitch"], h * SPAN["shut_h"])


def slot_at(geo, x):
    """Cell slot under ``x`` (0 leftmost), clamped to the row."""
    slot = int((x - geo["left"]) // geo["cell_pitch"])
    return max(0, min(geo["cells"] - 1, slot))


def block_at(geo, x):
    """Block INDEX under ``x`` on the map — map position converted to index."""
    marks = geo.get("map_marks", MAP_MARKS)
    pos = int((x - geo["left"]) // geo["map_pitch"])
    return to_map(max(0, min(marks - 1, pos)), marks)


def today_block(current_age, total=None, family=DEFAULT_FAMILY):
    """Which cell of the line the native is living, or ``None`` if unknown.

    Here rather than inline in :func:`band_model` because the keyboard needs it
    too: with nothing selected yet, an arrow key selects the element nearest
    TODAY (INV-7), and a second copy of ``// 7`` is a second thing to get wrong.

    The divisor is the family's ``unit_years`` — 7 on a progression block, 1 on
    a quadration age, where the cell index IS the age. Hardcoding the 7 would
    put a 45-year-old on the Age 6 quadration.
    """
    if current_age is None or current_age < 0:
        return None
    fam = family_spec(family)
    total = fam["line"] if total is None else total
    return min(total - 1, current_age // fam["unit_years"])


#: How much of the 364-year line one life plausibly covers: 13 blocks, 91
#: years. A DISPLAY CONVENTION, not a claim and not a prediction. It exists so
#: a reader can see at a glance how far the rail runs past a lifetime; it never
#: crops (D-7 — a chart stays readable after its native dies, and post-death
#: periods are legitimate content). A native who outlives it simply extends
#: past the bracket. The quadration's line IS one life, so it sets
#: ``lifetime_cells`` to None and draws no bracket at all: a bracket around
#: everything marks nothing.
LIFETIME_BLOCKS = FAMILIES[PROGRESSION]["lifetime_cells"]


#: What the crumb says when the reader has opened nothing. Kept verbatim as the
#: level-0 text so the default view reads exactly as it always has.
CRUMB_ROOT = "natal spread"


def crumb_idle(family=DEFAULT_FAMILY, shown=None):
    """The idle crumb, naming the span the reader is looking at.

    ``364 years`` on a progression and ``90 ages`` on a quadration. The span is
    the one thing the idle line says, so a family that inherited the other's
    span would be stating the wrong length of line before anything is opened.

    ``shown`` states how many of that span are on screen, and appears ONLY when
    the row does not hold the whole line. It is where the count went when the
    quadration rail's caption gave up its berth to the year marks (§3.3c); a row
    that holds everything says nothing extra, which is why the progression's
    idle line is unchanged to the byte.
    """
    span = family_spec(family)["span_label"]
    tail = "nothing opened" if shown is None else f"{shown} shown"
    return f"{CRUMB_ROOT}   |   {span} · {tail}"


#: The progression's idle crumb, as a constant, because it is the shipped
#: default and several callers and gates name it directly.
CRUMB_IDLE = crumb_idle(PROGRESSION)


def _block_step(blk, family=DEFAULT_FAMILY):
    """One breadcrumb step naming a cell of the open line."""
    spec = family_spec(family)
    return spec["crumb_step"](blk, spec)


def crumb_for(level, path, blocks, loaded=None, family=DEFAULT_FAMILY,
              shown=None):
    """The breadcrumb: what is open, in the order it was opened.

    Built from the PATH, not from the level alone. The level says how deep the
    reader has gone; the path says what they are looking at, and a trail that
    names the depth without naming the thing is not a trail. It was a constant
    string until the ladder could actually descend, at which point it started
    saying "nothing opened" over an opened block.

    Each step is added only when the level has actually reached it, so a stale
    ancestor left in the path cannot show up as a place the reader is not.

    ``loaded`` is the block currently LOADED as the working spread
    (SPEC-COT-005 INV-9), and it is a separate input from the selection path
    because the two genuinely come apart: Escape stage 1 unloads without moving
    the ladder, and climbing unloads nothing, so a block can be open at the
    reader's eye while the ladder sits back at the rail. Derived from the level
    alone, the crumb would then say "nothing opened" over an open block — the
    same regression T-15 exists to kill, coming back through a door T-15 does
    not watch. When something is loaded it is what the reader is READING, so it
    is what the trail names.

    Built HERE, inside the model, and never formatted in the view: the band's
    pixmap cache keys on ``model["crumb"]`` literally, so a crumb assembled
    downstream would change without changing the key and the band would go on
    blitting the previous name.
    """
    spec = family_spec(family)
    if loaded is not None and 0 <= loaded < len(blocks):
        return f"{CRUMB_ROOT}   ▸   {_block_step(blocks[loaded], family)}"

    block = path.get("block") if path else None
    if level < CARRIAGE or block is None or not (0 <= block < len(blocks)):
        return crumb_idle(family, shown)

    blk = blocks[block]
    trail = [CRUMB_ROOT, _block_step(blk, family)]

    year = path.get("year")
    if level >= BLOCK and year is not None:
        start, _ = _cell_ages(blk, spec["unit_years"])
        trail.append(f"age {start + year}")
        period = path.get("period")
        if level >= YEAR and period is not None:
            trail.append(f"period {period + 1} of {spec['periods']}")
    return "   ▸   ".join(trail)


def band_model(blocks, *, window_start=0, selected=None, current_age=None,
               level=CARRIAGE, lifetime_blocks=None, path=None,
               loaded=None, family=DEFAULT_FAMILY):
    """Everything the painter needs, and nothing it has to derive.

    ``blocks`` is the family's own cell list —
    :func:`core.cards_of_truth_data.progression_blocks` for the progression,
    ``quadration_ages`` for the quadration — and both are lists of dicts
    carrying ``index``, ``base_card`` and ``card``. The labels are built here
    rather than in the painter so the strings are testable without a display,
    and so the CLI can print the same ones (Rule 24).

    ``converged`` is DERIVED here from the level rather than passed in, because
    a caller that computes it computes it wrong: the shipped one used
    ``level >= 1`` and marked the two grids as agreeing at two levels where
    they visibly do not (:func:`grids_converge`).

    Every family-dependent string and count is resolved HERE, once, into the
    model the painters read (INV-7). A painter that could see the family would
    grow one ``if`` per string; a painter that sees only the resolved strings
    cannot tell the two families apart and therefore cannot get them wrong.
    """
    fam = family_spec(family)
    spec = level_spec(level, family)
    marks = fam["line"]
    today = today_block(current_age, len(blocks), family)

    # The window, clamped ONCE, here. Everything downstream — the cell row, the
    # TODAY needle, the year marks, the cache key, the hit test — reads the
    # clamped value, so a caller holding a start that was legal at another level
    # cannot make the painter and the hit-tester disagree about which age is
    # under the cursor.
    start = (max(0, min(window_start, len(blocks) - spec["cells"]))
             if spec["windowed"] else 0)

    # Where the year marks fall, measured against THIS row: a windowed row
    # spans ``cells`` of the line starting at ``start``, so the marks travel
    # with the cells. The birth year comes off the line's first cell, which is
    # ``None`` on a chart with no birth date — and then the marks carry no
    # labels rather than a year counted from nothing.
    birth_year = _cell_years(blocks[0], fam["unit_years"])[0] if blocks else None
    year_row = year_marks(family, level, start, birth_year)

    # WI-7 / D-10 — one ruler at a time. The decade marks are the band's IDLE
    # year reference; the instant an Age-N spread is loaded (``loaded`` is not
    # None) the spread's own dated period ruler is the single ruler and the
    # marks stand down. Keyed on ``marks_idle_only`` so the progression, whose
    # 52-year marks ARE its only ruler, is untouched. The caption gate below
    # keys on ``suppress_marks`` as well as ``labelled`` so the berth the marks
    # vacate stays EMPTY here rather than resurrecting the caption via §3.3c's
    # "unlabelled -> caption returns" branch — a spread is loaded, not dateless.
    suppress_marks = bool(fam.get("marks_idle_only") and loaded is not None)
    if suppress_marks:
        year_row = []

    # The suit runs are read off the card the cell DRAWS, which is not the same
    # key in the two families (:func:`cell_face`). Comparing ``card`` on a
    # quadration line compares the birth card with itself ninety times and
    # yields zero gates -- a map with no runs on it, and nothing that fails.
    faces = [cell_face(blk, fam) for blk in blocks]
    gates = []
    for i in range(1, len(blocks)):
        if faces[i]["suit"] != faces[i - 1]["suit"]:
            # the gate sits on the LEFT edge of the older block's mark
            gates.append(to_map(i - 1, marks) + 1)

    out = []
    for blk, face in zip(blocks, faces):
        out.append(dict(blk,
                        face=face,
                        ages_label=fam["cell_label"](blk, fam),
                        years_label=fam["cell_years"](blk, fam)))

    # A lifetime bracket only means something on a line that is LONGER than a
    # life. The quadration line is exactly one life, so its ``lifetime_cells``
    # is None, no bracket is drawn, and every cell counts as lived.
    if lifetime_blocks is None:
        lifetime_blocks = fam["lifetime_cells"]
    if lifetime_blocks is None:
        last, lifetime = len(blocks) - 1, None
    else:
        last = min(lifetime_blocks - 1, len(blocks) - 1)
        lifetime = (0, last)

    # The year marks and the caption want the same berth — the strip between the
    # cell row and the rule's own year figures — and there is one of it. The
    # marks win where they exist, because a year reference on the line is the
    # thing the row cannot do without and the caption is a sentence about what
    # the row is. Where they do not exist the caption is untouched, which is
    # every level of the progression and the quadration's carriage.
    labelled = any(m["label"] for m in year_row)
    # ...and the count the caption was carrying moves to the idle crumb, on the
    # one row where the caption gave its berth up. A row that keeps its caption
    # keeps saying "13 of 90" there and must not say it twice.
    shown = spec["cells"] if (spec["windowed"] and labelled) else None

    return {
        "blocks": out,
        "window_start": start,
        "selected": selected,
        "today": today,
        "level": level,
        "family": fam["name"],
        # --- the level, resolved to DATA. Painters read these, never the level.
        "cells": spec["cells"],
        "windowed": spec["windowed"],
        "magnify": spec["magnify"],
        "rounded": spec["rounded"],
        "comb": spec["comb"],
        "min_h": min_height_for(level, family),
        "min_bar_h": min_bar_height_for(level, family),
        "glyphs": True,      # paint_band narrows this from h

        # --- the family, resolved to DATA the same way. Painters read these,
        #     never the family: an ``if family ==`` in a painter means a key is
        #     missing from FAMILIES, not that a branch was needed.
        "map_marks": marks,
        "window_cells": fam["window"],
        "comb_teeth": fam["periods"],
        "boundaries": year_row,
        "family_label": fam["label"],

        "converged": grids_converge(level, family),
        "last_lived": last,
        "lifetime": lifetime,
        "run_gates": gates,
        "to_map": to_map,
        "later_label": "later ►",
        "magnify_label": _magnify_label(marks, fam["window"]),
        "caption_left": "" if (labelled or suppress_marks) else fam["caption_left"],
        "caption_right": "" if (labelled or suppress_marks) else fam["caption_right"],
        "crumb": crumb_for(level, path, blocks, loaded, family, shown),
        "prog_formula": "52 × 7",
        "quad_formula": "7 × 52",
    }


# ------------------------------------------------------------------ #
# painting
# ------------------------------------------------------------------ #

def _label(px, spacing=150, bold=True):
    f = QFont()
    f.setPixelSize(max(6, int(round(px))))
    if bold:
        f.setWeight(QFont.Weight.Bold)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return f


def _serif(px, families, bold=True):
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(max(6, int(round(px))))
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


def _alpha(colour, a):
    c = QColor(colour)
    c.setAlphaF(a)
    return c


def _suit_ink(pal, is_red):
    return QColor(pal["red"] if is_red else pal["black"])


def paint_band(p, pal, geo, model, serif_families, dpr=1.0, top_limit=None):
    """Draw the whole band. ``model`` is what :func:`band_model` returns.

    ``top_limit`` is the lowest y the band may write on — in practice the
    bottom of row 1. The crumb and the legend live above the cell row and are
    the first things to collide with the birth card when the figure is small,
    so they are drawn only if that space is real. Passing ``None`` means the
    caller is not claiming any limit and the chrome is drawn unconditionally.

    Returns the mode actually drawn, so a caller can say WHY something is
    missing rather than silently drawing less.
    """
    h = geo["h"]
    # Both floors arrive as DATA, not as a level lookup (INV-1): the painter
    # must not know which level it is drawing. They are the LEVEL's floors,
    # solved from a readable cell width rather than shared -- one constant
    # across four levels is what v2.0 of the spec had, and it was the
    # carriage's number, which passes a 5.2px rail cell without noticing.
    if h < model["min_bar_h"]:
        return "rule_only"
    glyphs = h >= model["min_h"]
    model = dict(model, glyphs=glyphs)

    p.save()
    # The magnifier is furniture, not a level: the model says whether there is
    # one, and the painters below never ask which level they are drawing.
    if model["magnify"]:
        _paint_map(p, pal, geo, model, serif_families)
        _paint_funnel(p, pal, geo, model)
    else:
        _paint_boundaries(p, pal, geo, model, serif_families)
        _paint_today_needle(p, pal, geo, model)

    _paint_cell_row(p, pal, geo, model, serif_families, dpr)
    _paint_caption(p, pal, geo, model)

    room = None if top_limit is None else geo["carriage"].top() - top_limit
    mode = "full" if glyphs else "bars"
    if _paint_crumb(p, pal, geo, model, room):
        _paint_legend(p, pal, geo, model, serif_families, room)
    else:
        mode = "no_chrome"
    p.restore()
    return mode


# ---- the 52-year boundaries, on a level with no map ---------------- #

def _paint_boundaries(p, pal, geo, model, serif_families=None):
    """The heavy verticals where a period boundary truly lands, and their years.

    This is the rail's best instrument and the reason design I was worth
    keeping. 52 and 7 share no interior multiple, so every one of the
    progression's falls INSIDE a progression rather than on its edge — the
    figure SHOWS the two grids failing to coincide instead of asserting it with
    a glyph in a legend.

    Drawn at fractional positions, deliberately. Rounding them to the nearest
    cell edge would make the two grids appear to agree, which is the one thing
    that mark exists to deny.

    WHERE they fall is data and arrives as a list of marks
    (:func:`year_marks`), so this function neither counts them nor knows what a
    52-year period or a decade is. An empty list draws nothing.

    A mark may carry a YEAR, and then two things follow. The figure is written
    in the strip below the cells, which is the only clear one; and the vertical
    is INTERRUPTED across that strip rather than struck through the digits.
    Where a mark carries no year the line is continuous and this function draws
    exactly what it drew before the years existed.
    """
    if "bdy_top" not in geo:
        return
    h, accent = geo["h"], QColor(pal["accent"])
    row = geo.get("marks")

    # Smaller than the rule's own year figures (``0.082h``) and deliberately:
    # this is the band's axis, and two year rows of the same weight one above
    # the other read as one broken row.
    f = _serif(max(6.0, h * 0.055), serif_families or [], bold=False)
    fm = QFontMetrics(f)
    # Measured, never thresholded (INV-5): the font floors at 8px while the
    # strip is a multiple of h, so below about h = 130 the digits are taller
    # than the room and the whole row goes rather than half of it.
    room = row is not None and fm.height() <= row.height()
    p.setFont(f)

    for mark in model["boundaries"]:
        # right to left, like everything else on this axis
        x = geo["left"] + mark["frac"] * geo["width"]
        label = mark["label"] if room else None
        if mark["line"]:
            p.setPen(QPen(_alpha(accent, .55), max(1.0, h * 0.008)))
            top, bottom = geo["bdy_top"], geo["bdy_top"] + geo["bdy_h"]
            if label:
                p.drawLine(QPointF(x, top), QPointF(x, row.top()))
                p.drawLine(QPointF(x, row.bottom()), QPointF(x, bottom))
            else:
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
        if not label:
            continue
        # Centred on the mark, then pushed back inside the band: the mark at the
        # right edge IS the year the reader is standing on, and half of it drawn
        # past the end of the line is worse than the digits sitting flush.
        w = fm.horizontalAdvance(label) + h * 0.030
        left = min(max(x - w / 2, geo["left"]), geo["right"] - w)
        p.setPen(QPen(_alpha(accent, .78)))
        p.drawText(QRectF(left, row.top(), w, row.height()),
                   Qt.AlignmentFlag.AlignCenter, label)


def _paint_today_needle(p, pal, geo, model):
    """Where the native is on the line, in ink rather than gold.

    Gold is the instrument; the native's own position is a different kind of
    fact and takes the text colour, so the two never read as the same mark.

    Placed by SLOT (:func:`index_slot`), because the row it is drawn on may be
    showing a window: TODAY is simply absent while the reader has slid it off
    the end, and drawing it at ``to_map(today)`` instead would keep a needle on
    screen pointing at whatever cell happens to sit there.
    """
    if model["today"] is None or "today_top" not in geo:
        return
    slot = index_slot(model["window_start"], model["today"], model["cells"])
    if slot is None:
        return
    h = geo["h"]
    ink = _alpha(pal["ink"], .82)
    x = geo["left"] + (slot + 0.5) * geo["cell_pitch"]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(ink))
    p.drawRect(QRectF(x - h * 0.003, geo["today_top"], h * 0.006, geo["today_h"]))
    tri = QPainterPath()
    t = h * SPAN["anch_tri"]
    tri.moveTo(x - t * 0.8, geo["today_top"] - t)
    tri.lineTo(x + t * 0.8, geo["today_top"] - t)
    tri.lineTo(x, geo["today_top"])
    tri.closeSubpath()
    p.fillPath(tri, QBrush(ink))


# ---- the map: all 52, full width --------------------------------- #

def _paint_map(p, pal, geo, model, serif_families):
    h, rect = geo["h"], geo["map"]
    accent = QColor(pal["accent"])
    radius = h * 0.014
    # How many marks are on this line is DATA — 52 progressions or 90 ages —
    # and it arrives on the geo the pitch was solved from, so the marks and the
    # pitch cannot come apart.
    marks = geo["map_marks"]

    p.setPen(QPen(_alpha(pal["ink"], .12), 1))
    p.setBrush(QBrush(_alpha(pal["bg0"], .35)))
    p.drawRoundedRect(rect, radius, radius)

    base_y = rect.bottom() - h * 0.013
    mark_h = h * SPAN["mark_h"]
    mark_w = geo["map_pitch"] * SPAN["mark_w"]

    p.setPen(Qt.PenStyle.NoPen)
    for blk in model["blocks"]:
        x = mark_x(geo, to_map(blk["index"], marks))
        ink = _suit_ink(pal, blk["face"]["is_red"])
        ink.setAlphaF(.55 if blk["index"] <= model["last_lived"] else .28)
        p.setBrush(QBrush(ink))
        p.drawRect(QRectF(x - mark_w / 2, base_y - mark_h, mark_w, mark_h))

    # Suit-run gates. The runs are 10 / 13 / 13 / 13 / 3 and they close back on
    # the birth suit: a reader who counts them is checking the Solar Value walk
    # by eye, which is the one thing on this map that is worth checking.
    p.setBrush(QBrush(accent))
    for boundary in model["run_gates"]:
        gx = geo["left"] + boundary * geo["map_pitch"]
        p.drawRect(QRectF(gx - h * SPAN["gate_w"] / 2, rect.top() - h * 0.012,
                          h * SPAN["gate_w"], h * SPAN["gate_h"]))

    # The lifetime bracket: how much of the line the native actually lives.
    if model["lifetime"] is not None:
        a, b = model["lifetime"]
        x0 = geo["left"] + to_map(b, marks) * geo["map_pitch"]
        x1 = geo["left"] + (to_map(a, marks) + 1) * geo["map_pitch"]
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_alpha(accent, .50), 1))
        lh = h * SPAN["life_h"]
        p.drawLine(QPointF(x0, base_y - lh), QPointF(x0, base_y))
        p.drawLine(QPointF(x1, base_y - lh), QPointF(x1, base_y))
        p.drawLine(QPointF(x0, base_y), QPointF(x1, base_y))

    # TODAY: an ink anchor, not a gold one. Gold is the instrument; the native's
    # own position is a different kind of fact and gets the ink colour.
    if model["today"] is not None:
        ax = mark_x(geo, to_map(model["today"], marks))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_alpha(pal["ink"], .82)))
        p.drawRect(QRectF(ax - h * 0.003, rect.top() - h * 0.028,
                          h * 0.006, h * SPAN["anch_h"]))
        tri = QPainterPath()
        t = h * SPAN["anch_tri"]
        tri.moveTo(ax - t * 0.8, rect.top() - h * 0.028 - t)
        tri.lineTo(ax + t * 0.8, rect.top() - h * 0.028 - t)
        tri.lineTo(ax, rect.top() - h * 0.028)
        tri.closeSubpath()
        p.fillPath(tri, QBrush(_alpha(pal["ink"], .82)))

    # The window bracket. One target, corner-ticked, sitting proud of the map
    # box so it reads as a thing laid ON the line rather than a slice of it.
    shut = window_rect(geo, model["window_start"])
    p.setPen(QPen(accent, 1))
    p.setBrush(QBrush(_alpha(accent, .10)))
    p.drawRoundedRect(shut, h * SPAN["shut_r"], h * SPAN["shut_r"])
    tick = h * SPAN["shut_tick"]
    p.setBrush(Qt.BrushStyle.NoBrush)
    for cx, cy, dx, dy in ((shut.left(), shut.top(), 1, 1),
                           (shut.right(), shut.top(), -1, 1),
                           (shut.left(), shut.bottom(), 1, -1),
                           (shut.right(), shut.bottom(), -1, -1)):
        p.drawLine(QPointF(cx, cy), QPointF(cx + dx * tick, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * tick))

    f = _label(max(6.0, h * SPAN["small"]), spacing=190)
    fm = QFontMetrics(f)
    if fm.height() <= h * 0.062:
        p.setFont(f)
        p.setPen(QPen(_alpha(accent, .60)))
        p.drawText(QRectF(geo["left"] + h * 0.014, rect.top() - h * 0.062,
                          geo["width"] * .3, h * 0.062),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   model["later_label"])


# ---- the funnel: window bracket up to the carriage ---------------- #

def _paint_funnel(p, pal, geo, model):
    h, accent = geo["h"], QColor(pal["accent"])
    fun = geo["funnel"]
    shut = window_rect(geo, model["window_start"])
    if shut is None:
        return

    path = QPainterPath()
    path.moveTo(geo["left"], fun.top())
    path.lineTo(geo["right"], fun.top())
    path.lineTo(shut.right(), fun.bottom())
    path.lineTo(shut.left(), fun.bottom())
    path.closeSubpath()
    p.fillPath(path, QBrush(_alpha(accent, .10)))

    p.setPen(QPen(_alpha(accent, .45), 1))
    p.drawLine(QPointF(geo["left"], fun.top()), QPointF(shut.left(), fun.bottom()))
    p.drawLine(QPointF(geo["right"], fun.top()), QPointF(shut.right(), fun.bottom()))

    # The label rides inside the funnel band, which is 0.058h — under 5px once
    # h drops below 85, while the font stops at 8. Drawn there anyway it lands
    # across the map's top edge, so it is drawn only when the band can hold it.
    f = _label(max(6.0, h * SPAN["small"]), spacing=200)
    if QFontMetrics(f).height() <= fun.height():
        p.setFont(f)
        p.setPen(QPen(_alpha(accent, .70)))
        p.drawText(fun, Qt.AlignmentFlag.AlignCenter, model["magnify_label"])


# ---- the carriage: 13 readable cells ----------------------------- #

def _paint_cell_row(p, pal, geo, model, serif_families, dpr):
    h = geo["h"]
    accent = QColor(pal["accent"])
    trough = geo["carriage"]

    p.setPen(QPen(_alpha(pal["ink"], .12), 1))
    p.setBrush(QBrush(_alpha(pal["bg0"], .30)))
    p.drawRoundedRect(trough.adjusted(-h * 0.026, 0, h * 0.026, 0),
                      h * 0.032, h * 0.032)

    cells = model["cells"]
    for slot in range(cells):
        # A windowed row shows part of the line; an unwindowed one shows all of
        # it, which is the same thing with the window at the start — the model
        # pins ``window_start`` to 0 there, and ``slot_index`` then IS
        # ``to_map``. One converter, no branch, and no way for the two to drift.
        idx = slot_index(model["window_start"], slot, cells)
        if not 0 <= idx < len(model["blocks"]):
            continue
        _paint_cell(p, pal, geo, model, slot, model["blocks"][idx],
                    serif_families, dpr)


def _paint_cell(p, pal, geo, model, slot, blk, serif_families, dpr):
    h = geo["h"]
    rect = cell_rect(geo, slot)
    accent = QColor(pal["accent"])
    is_red = blk["face"]["is_red"]
    ink = _suit_ink(pal, is_red)
    selected = (blk["index"] == model["selected"])
    is_today = (blk["index"] == model["today"])
    lived = blk["index"] <= model["last_lived"]

    face = QColor(pal["face_up"][0])
    if is_red:
        face = QColor(pal["face_up"][1])
    rim = QColor(pal["rim_red"] if is_red else pal["rim_black"])
    # Rounded means CARD, squared means a division of one — the same grammar
    # the card gutters already use. It is what tells a degraded level 2 from
    # a degraded level 3, once all the text is gone (INV-1d).
    r = h * SPAN["cell_radius"] if model["rounded"] else 0.0

    body = rect.adjusted(0.5, 0.5, -0.5, -0.5)

    if not model["glyphs"]:
        # The bar rung. No rank, no pip, no frame — just the suit, so the runs
        # and their close back onto the birth suit still read. Inset so adjacent
        # bars keep a gap: 52 abutting rectangles are one rectangle.
        inset = max(0.5, body.width() * 0.16)
        bar = body.adjusted(inset, h * 0.030, -inset, -h * 0.030)
        p.setPen(QPen(accent, 1) if selected or is_today
                 else Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_alpha(ink, .70 if lived else .38)))
        p.drawRect(bar)
        return

    p.setPen(QPen(accent if (selected or is_today) else rim, 1))
    p.setBrush(QBrush(_alpha(accent, .16) if selected else face))
    p.drawRoundedRect(body, r, r)

    # the suit strip along the top edge — the cell's own colour, before any text
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(body, r, r)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(accent if selected else _alpha(ink, .55)))
    p.fillRect(QRectF(body.left(), body.top(), body.width(),
                      h * SPAN["cell_bar"]), p.brush())
    p.restore()

    # the inner keyline: a card face has a double frame, and the cell is a card
    inset = h * SPAN["cell_inset"]
    p.setPen(QPen(_alpha(accent if selected else pal["ink"], .22 if selected else .12), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body.adjusted(inset, inset, -inset, -inset),
                      h * 0.014, h * 0.014)

    # What the cell can afford, MEASURED. The mockup states its ladder as two
    # thresholds on h (text below 60, chip below 36) and those are right for
    # its own font scale; Qt floors a font at 8px, so the same ratios put an
    # 8px string in a 21px cell at h = 81 and it overruns both the neighbouring
    # cell and its own border. A threshold cannot see that. A measurement can.
    pad = h * SPAN["cell_pad"]
    lab = _label(max(6.0, h * SPAN["cell_lab"]), spacing=118)
    ys = _serif(max(6.0, h * SPAN["cell_yrs"]), serif_families, bold=False)
    fl, fy = QFontMetrics(lab), QFontMetrics(ys)
    years = blk.get("years_label") or ""

    rank = blk["face"]["rank_display"]
    rank_px = h * SPAN["rank"]
    f = _serif(rank_px, serif_families)
    fm = QFontMetrics(f)
    rank_w = fm.horizontalAdvance(rank)
    pip_px = h * SPAN["cell_pip"]

    face_w = max(rank_w, pip_px)
    tx = body.left() + pad + face_w + h * 0.034
    tw = body.right() - h * 0.026 - tx
    room = body.height() - h * 0.030 - h * SPAN["comb_sub"] - h * 0.016

    show_ages = (tw >= fl.horizontalAdvance(blk["ages_label"])
                 and room >= fl.height() + fy.height())
    show_years = show_ages and bool(years) and tw >= fy.horizontalAdvance(years)

    if not show_ages:
        # Nothing but the face fits, so the face takes the whole cell. STACKED,
        # rank over pip, which is what the Deck Rail mockup does and the only
        # thing that works at the rail's 16.6px: side by side, a 7px rank plus a
        # 5px pip plus a gap is wider than the cell and the two collide.
        #
        # Sized from the CELL rather than from h, because the same code serves a
        # 16px rail cell and a 124px seven-cell one.
        rank_px = min(h * 0.11, body.height() * 0.42, body.width() * 0.62)
        pip_px = min(h * 0.075, body.height() * 0.26, body.width() * 0.34)
        f = _serif(rank_px, serif_families)
        fm = QFontMetrics(f)
        gap = max(0.5, h * 0.004)
        stack = fm.height() + gap + pip_px
        top = body.center().y() - stack / 2

        p.setFont(f)
        p.setPen(QPen(ink))
        p.drawText(QRectF(body.left(), top, body.width(), fm.height()),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   rank)
        pix = suit_pixmap(blk["face"]["suit_name"], pip_px, ink, dpr)
        if pix is not None:
            p.drawPixmap(QPointF(body.center().x() - pip_px / 2,
                                 top + fm.height() + gap), pix)
        return

    # rank and pip stacked at the left, then the two text lines beside them
    x = body.left() + pad
    p.setFont(f)
    p.setPen(QPen(ink))
    p.drawText(QRectF(x, body.top() + h * 0.030, rank_w + 2, fm.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, rank)
    pix = suit_pixmap(blk["face"]["suit_name"], pip_px, ink, dpr)
    if pix is not None:
        p.drawPixmap(QPointF(x + (rank_w - pip_px) / 2 - 1,
                             body.top() + h * 0.030 + fm.height() - h * 0.004),
                     pix)

    ty = body.top() + h * 0.030
    p.setFont(lab)
    p.setPen(QPen(pal["ink"] if selected else pal["ink_soft"]))
    p.drawText(QRectF(tx, ty, tw, fl.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               blk["ages_label"])
    if show_years:
        p.setFont(ys)
        p.setPen(QPen(accent))
        p.drawText(QRectF(tx, ty + fl.height() + h * 0.008, tw, fy.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, years)

    # the comb: seven notches, one per part waiting inside this cell. It is
    # what tells the reader there IS another level before they click, which
    # is why the floor level does not draw one (INV-1d).
    # A comb needs a cell wide enough to hold eight lines and still read as a
    # comb rather than as hatching, so it is measured, not assumed.
    if model["comb"] and body.width() >= h * 0.26:
        teeth = model["comb_teeth"]
        comb_y = body.bottom() - h * 0.013
        cl, cr = body.left() + h * 0.026, body.right() - h * 0.026
        for k in range(teeth + 1):
            nx = cl + (cr - cl) * k / float(teeth)
            tall = k in (0, teeth)
            p.setPen(QPen(_alpha(accent, .55) if tall
                          else _alpha(pal["ink"], .18), 1))
            nh = h * (SPAN["comb_sub"] if tall else SPAN["comb"])
            p.drawLine(QPointF(nx, comb_y - nh), QPointF(nx, comb_y))

    if is_today:
        tri = QPainterPath()
        t = h * 0.024
        cx = body.center().x()
        tri.moveTo(cx - t, body.top() + h * 0.014)
        tri.lineTo(cx + t, body.top() + h * 0.014)
        tri.lineTo(cx, body.top() + h * 0.014 + h * 0.030)
        tri.closeSubpath()
        p.fillPath(tri, QBrush(accent))


# ---- the caption line -------------------------------------------- #

def _paint_caption(p, pal, geo, model):
    """The one line of prose in the band, in the berth between map and years.

    That berth is 0.058h and the font floors at 8px, so at the sizes this view
    actually runs the text is nearly as tall as the space it has. Hence the
    berth, not a fixed offset: anchoring to ``cap_top`` and letting the glyphs
    fall where they may is what put this sentence through the middle of the
    year row on the first render.
    """
    h = geo["h"]
    accent = QColor(pal["accent"])
    # Nothing to say, and the berth is somebody else's: the year marks take it
    # on a row that has them, and the model blanks both strings to say so. An
    # empty string drawn here is not harmless — it is the pair of them fighting
    # over the same fourteen pixels.
    if not model["caption_left"] and not model["caption_right"]:
        return
    # The berth runs from whatever sits above the caption down to the year row.
    # On a magnified level that is the map; on every other level the cell row is
    # the lowest thing the band draws.
    above = geo["map"].bottom() if "map" in geo else geo["carriage"].bottom()
    berth = QRectF(geo["left"], above, geo["width"],
                   max(h * 0.03, geo["year_y"] - above))

    left_f = _label(max(6.0, h * 0.025), spacing=140)
    fm = QFontMetrics(left_f)
    right_f = _label(max(6.0, h * 0.023), spacing=170)
    right_w = QFontMetrics(right_f).horizontalAdvance(model["caption_right"])

    # Below this there is no berth left and the line would be drawn through the
    # map or through the year figures. Drop it whole rather than draw it into
    # something else: the counts it carries are stated again by the window
    # bracket and by the cells themselves.
    if berth.height() < fm.height():
        return

    # The left sentence is long and optional; the right one is a count and is
    # not. Give the count its width first and drop the sentence if what is left
    # cannot hold it, rather than letting the two overrun each other.
    avail = geo["width"] - right_w - h * 0.12
    if fm.horizontalAdvance(model["caption_left"]) <= avail:
        p.setFont(left_f)
        p.setPen(QPen(pal["ink_faint"]))
        p.drawText(QRectF(berth.left() + h * 0.014, berth.top(), avail, berth.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   model["caption_left"])

    p.setFont(right_f)
    p.setPen(QPen(_alpha(accent, .85)))
    p.drawText(QRectF(berth.right() - right_w - h * 0.014, berth.top(),
                      right_w, berth.height()),
               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
               model["caption_right"])


# ---- breadcrumb and the convergence legend ----------------------- #

def _paint_crumb(p, pal, geo, model, room):
    """The breadcrumb. Returns whether there was room to draw it.

    The answer gates the legend too: both live on the same line, and half a
    line of chrome is worse than none — at the app minimum it lands on top of
    the birth card, which is how the first version of this looked.
    """
    h = geo["h"]
    f = _label(max(6.0, h * SPAN["crumb_txt"]), spacing=140)
    fm = QFontMetrics(f)
    need = fm.height() + h * 0.052
    if room is not None and room < need:
        return False
    p.setFont(f)
    p.setPen(QPen(pal["ink"]))
    p.drawText(QRectF(geo["left"], geo["carriage"].top() - h * 0.026 - fm.height(),
                      geo["width"] * .58, fm.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               model["crumb"])
    return True


def _paint_legend(p, pal, geo, model, serif_families, room=None):
    """PROGRESSION 52 x 7  !=  QUADRATION 7 x 52.

    The one place the two families are named. They are told apart by which side
    of the box carries its gold bar, never by colour, and the joining glyph is
    the state: ``!=`` while the grids disagree, ``=`` at the level where they
    draw the same seven divisions.
    """
    h = geo["h"]
    accent = QColor(pal["accent"])
    lab = _label(max(6.0, h * SPAN["legend_txt"]), spacing=190)
    num = _serif(max(6.0, h * SPAN["legend_num"]), serif_families, bold=False)
    fl, fn = QFontMetrics(lab), QFontMetrics(num)

    boxes = []
    for title, formula, side in (("PROGRESSION", model["prog_formula"], "left"),
                                 ("QUADRATION", model["quad_formula"], "right")):
        w = max(fl.horizontalAdvance(title), fn.horizontalAdvance(formula))
        w += 2 * h * SPAN["legend_pad"]
        boxes.append([title, formula, side, w])

    join = "=" if model["converged"] else "≠"
    fj = _serif(max(7.0, h * SPAN["join"]), serif_families)
    jw = QFontMetrics(fj).horizontalAdvance(join) + h * 0.05

    total = boxes[0][3] + boxes[1][3] + jw
    x = geo["right"] - total
    box_h = fl.height() + fn.height() + 2.6 * h * SPAN["legend_padv"]
    # Sit the boxes ON the crumb line by their BOTTOM edge: their height comes
    # from two font metrics that do not scale below 8px, so anchoring the top
    # would push them down into the carriage at small sizes.
    y = geo["carriage"].top() - h * 0.026 - box_h
    if room is not None and room < box_h + h * 0.026:
        return
    if total > geo["width"] * 0.52:
        return                       # it would run into the breadcrumb

    for i, (title, formula, side, w) in enumerate(boxes):
        r = QRectF(x, y, w, box_h)
        p.setPen(QPen(_alpha(pal["ink"], .14), 1))
        p.setBrush(QBrush(_alpha(pal["face_up"][0], .55)))
        p.drawRoundedRect(r, h * 0.022, h * 0.022)
        bar = h * SPAN["legend_bar"]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(accent))
        p.drawRect(QRectF(r.left() if side == "left" else r.right() - bar,
                          r.top() + 1, bar, r.height() - 2))
        p.setFont(lab)
        p.setPen(QPen(pal["ink_faint"]))
        p.drawText(r.adjusted(0, h * SPAN["legend_padv"], -h * 0.02, 0),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, title)
        p.setFont(num)
        p.setPen(QPen(accent))
        p.drawText(r.adjusted(0, 0, -h * 0.02, -h * SPAN["legend_padv"]),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, formula)
        if i == 0:
            p.setFont(fj)
            p.setPen(QPen(accent if model["converged"] else pal["ink_faint"]))
            p.drawText(QRectF(r.right(), y, jw, box_h),
                       Qt.AlignmentFlag.AlignCenter, join)
            x = r.right() + jw
        else:
            x = r.right()
