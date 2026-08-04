# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Cards of Truth assembler — SPEC-COT-001 §4.9 INV-13.

The ONE place that turns a ``Chart`` into the 14-row birth spread. Pure Python:
no Qt, no GUI state. Both consumers go through it —
``apps/widgets/cards_of_truth_view.py`` (the F2 view) and
``AI_tools/cli/show_cards_of_truth.py`` (Rule 24 CLI parity) — so the two
surfaces cannot diverge.

Contract notes that are easy to get wrong
-----------------------------------------
* **INV-1 — nothing here computes a card.** Every card face and every occupant
  comes from ``libaditya.cards``. The only import from the engine's constants is
  ``planet_order``; importing ``symbols`` or reaching for ``birth_card_order``
  would be the first step toward re-deriving a face in app code.
* **INV-2 — the default order is ``solar_system``, NOT the library's ``vedic``.**
  Kala uses ``solar_system`` (SPEC-COT-001 §2.6, verified). Passing
  ``vedic`` silently mislabels three of the seven main cards and moves their
  occupants. Do not "restore" the library default.
* **INV-5/INV-6 — the grid is normative.** Row 2 runs RIGHT TO LEFT (index 1 =
  Sun = rightmost) and rows 3/5 are centre-anchored, not left-packed. Taken from
  the engine's own ``richDrawing()`` and confirmed against Kala.
* **D-4 — Earth and Chiron are omitted.** The engine returns them; Kala does not
  draw them, including on a card whose only occupant is Chiron (which Kala draws
  empty). Filtering here also closes the missing-icon gap.
* **INV-9 — defect transparency.** Whatever the engine returns is what ships,
  including the known-wrong November card (E-4) and the date-rollover card (E-6).
  No corrections live here.
"""

from dataclasses import replace
from datetime import date

# SPEC-COT-004 / SPEC-COT-007. Calendar arithmetic only: the seven period dates
# and the Year Card cost no ephemeris and no chart, which is the finding that
# collapsed the Age-N cost model from 171 ms to 60 ms.
from core.anniversary_chart import anniversary_chart
from core.cot_year_periods import (
    birthday_for_age, quadration_periods, year_card, year_card_anchor,
)

# INV-1: the only two engine-internals imports permitted in app code.
from libaditya.cards.cards_constants import planet_order
# The SAME table ``Longitude.lord()`` reads. Re-typing the twelve lords here
# would create a second source of truth that could drift from the one the
# engine places bodies with, and the in-sign card index (§4.10) would then
# disagree with the spread it is drawn from.
from libaditya import const as _const
# The engine's public entry class. Built directly rather than through
# ``Chart.cot()`` because that helper hardcodes ``master=self.rashi()``, and the
# whole point of INV-15 v2 is to be able to bind the spread to a varga instead.
from libaditya.cards import CardsOfTruth
# SPEC-COT-002. ``seat_rows`` is the engine's own three-quadration accessor, so
# the seat arithmetic stays in ``libaditya`` and SPEC-COT-001 INV-1 ("no index
# arithmetic on ``cardsc.cards`` in app code") remains literally true. ``Deck``
# gives a pip its ``symbol()`` and ``name()`` from the engine rather than having
# this module format a face by hand.
from libaditya.cards.cot import CoT
from libaditya.cards.deck import Deck


class CardsOfTruthUnavailable(RuntimeError):
    """The engine could not produce a spread for this chart.

    Raised for the reproduced upstream failures of SPEC-COT-001 §3.4 — E-1
    (``NameError`` for a birth before sunrise on the 1st of a month) and E-5
    (``IndexError`` on 30 November and 31 December) — so callers can render a
    message instead of taking down the chart tab (INV-12).
    """


#: Spread index -> (row, col), both 1-based. SPEC-COT-001 §3.2, normative.
#: Row 2 is right-to-left: index 1 sits in column 7.
GRID = {
    0:  (1, 4),
    7:  (2, 1), 6: (2, 2), 5: (2, 3), 4: (2, 4), 3: (2, 5), 2: (2, 6), 1: (2, 7),
    9:  (3, 3), 8: (3, 5),
    10: (4, 4),
    13: (5, 3), 12: (5, 4), 11: (5, 5),
}

GRID_ROWS = 5
GRID_COLS = 7

#: D-4 — Kala omits both; the engine returns them.
OMITTED_BODIES = frozenset({"Earth", "Chiron"})

#: INV-2 — the verified order. The library's own default is ``vedic`` and is wrong here.
DEFAULT_ORDER = "solar_system"

VALID_ORDERS = tuple(planet_order.keys())

#: Human-facing names for the two position orders. ONE definition, read by the
#: Cards of Truth view, the corner button on the three chart views, the
#: Settings combo, the Placements dialog and the CLI header — so a rename here
#: can never leave one surface saying something else. Lives in this Qt-free
#: module because the CLI needs it too.
#:
#: The STORED value stays ``vedic``: it is ``libaditya``'s own ``planet_order``
#: key and it is in every user's ``app_settings.json``. Renaming the value
#: would break both. Only the label moves.
#:
#: "Week Day" because that is what the order IS: the planetary rulers of the
#: days, Sunday=Sun, Monday=Moon, Tuesday=Mars, Wednesday=Mercury,
#: Thursday=Jupiter, Friday=Venus, Saturday=Saturn. "Vedic" named a tradition
#: rather than a sequence, which told a reader nothing about what they were
#: choosing between (SPEC-COT-001 D-15).
ORDER_LABELS = {"solar_system": "Solar System", "vedic": "Week Day"}

#: The names the GUI shows, mapped back to the engine keys. Someone reading
#: "Week Day" on screen must be able to type it at the CLI (Rule 24), but the
#: canonical value stays ``vedic``.
ORDER_ALIASES = {"week_day": "vedic", "weekday": "vedic",
                 "solar-system": "solar_system"}


def normalise_order(value: str) -> str:
    """An engine order key from either the engine name or the GUI name."""
    return ORDER_ALIASES.get(value, value)


#: 0-based sign index -> ruling planet, from the engine's own ``const.lords``
#: (which is 1-based). Aries/Dhata is index 0 in EVERY zodiac system this app
#: offers — division #1 does not shift — so this table is frame-independent and
#: needs no Aditya/tropical/sidereal variant.
SIGN_LORDS = tuple(_const.lords[n] for n in range(1, 13))

#: The seven planets a sign can be ruled by. Twelve signs, seven lords — and
#: since ``_place_Objects`` files every body AND every cusp under its lord, the
#: OTHER seven spread positions (Base, Rahu, Ketu, Ecliptic, Uranus, Neptune,
#: Pluto) are structurally incapable of holding either. SPEC-COT-002 §2.3.
#:
#: That is why a card carries ``can_hold_cusps``: an empty cusp gutter on one of
#: those seven means "cannot apply", not "none found", and the two must not be
#: drawn the same way. Confirmed across all five reference charts.
CLASSICAL_LORDS = frozenset(SIGN_LORDS)

#: The three quadrations, computed ONCE (SPEC-COT-002 INV-4). None of them takes
#: a chart, a date or a context — they are process constants.
#:
#: Tuples, not lists, because ``CoT.jack_quadration()`` hands out
#: ``cards_constants.jackquad`` ITSELF. One in-place mutation of that list would
#: corrupt every quadration in the process, silently and for the rest of its
#: life (INV-7).
JACK_QUAD = tuple(CoT.jack_quadration())
QUEEN_QUAD = tuple(CoT.queen_quadration())
KING_QUAD = tuple(CoT.king_quadration())

#: One deck instance; ``Card`` objects are immutable descriptions here.
_DECK = Deck()

#: A card's long period is 52 years and there are seven of them, one per row-2
#: position (SPEC-COT-002 §3.4). Verified across five reference charts.
PERIOD_LENGTH_YEARS = 52
PERIOD_POSITIONS = range(1, 8)

SUIT_NAMES = {"S": "spade", "H": "heart", "C": "club", "D": "diamond"}
RED_SUITS = frozenset({"H", "D"})

#: The engine's internal rank code for the ten is ``T``; the human-facing face
#: is ``10`` (SPEC-COT-001 §4.3).
_RANK_DISPLAY = {"T": "10"}


def rank_display(rank_code: str) -> str:
    """``'T'`` -> ``'10'``; every other rank is already its own face."""
    return _RANK_DISPLAY.get(rank_code, rank_code)


def card_for_sign(data: dict, sign_index: int):
    """The card a sign owns, by LORDSHIP — SPEC-COT-001 §4.10.

    Aries gets Mars's card, Leo gets the Sun's, Capricorn and Aquarius both get
    Saturn's. Twelve signs map onto seven planetary positions, so five cards
    appear twice; that is the system, not a bug, and it is the same relation the
    engine uses to place bodies (``planet.lord()``).

    Args:
        data: an ``assemble_spread`` result.
        sign_index: 0-based, Aries/Dhata = 0.

    Returns:
        The matching card row, or ``None`` if this order has no position for
        that lord. ``None`` is a real possibility rather than defensive noise:
        the position keys come from ``planet_order[order]`` and a future order
        is not obliged to contain all seven classical lords. Callers must draw
        nothing rather than substitute a card.
    """
    if not 0 <= sign_index <= 11:
        raise ValueError(f"sign_index must be 0-11, got {sign_index!r}")
    lord = SIGN_LORDS[sign_index]
    for card in data.get("cards", ()):
        if card["position"] == lord:
            return card
    return None


def sign_card_faces(data: dict) -> dict:
    """``{sign_index: card}`` for all twelve signs, skipping unmapped lords.

    Convenience for renderers that draw the whole grid in one pass, so they do
    not walk the 14 cards twelve times.
    """
    faces = {}
    for sign_index in range(12):
        card = card_for_sign(data, sign_index)
        if card is not None:
            faces[sign_index] = card
    return faces


def card_descriptor(code: str) -> dict:
    """The full description of a card face, from its two-letter engine code.

    Deliberately the SAME shape a spread row carries, because a pip is a card
    and every consumer of a card already knows this shape: the suit art keys off
    ``suit_name``, the CLI prints ``symbol``, the tooltip reads ``name``. A
    reduced pip dict would be a fourth card shape in a codebase that has three
    (SPEC-COT-002 INV-5).

    ``rank_display`` is what makes a ten render as ``10`` rather than the
    engine's internal ``T`` — Kala renders tens as ``10`` and three of the five
    reference charts exercise it, all of them in the pips.

    **``symbol`` is the engine's and is NOT display-safe.** ``Card.symbol()``
    prefixes the raw rank code, so the ten of hearts comes back as ``T♥``.
    ``display_symbol`` is the same glyph with the rank corrected, built by
    swapping the leading character rather than by looking up a suit table —
    reaching for ``cards_constants.symbols`` is the first step toward composing
    a face in app code, which SPEC-COT-001 INV-1 forbids. Both keys are kept:
    ``symbol`` because existing card rows carry it and callers compare against
    it, ``display_symbol`` because that is what a person should ever see.
    """
    rank, suit = code[0], code[1]
    card = _DECK[code]
    engine_symbol = card.symbol()
    return {
        "code": code,
        "rank": rank,
        "rank_display": rank_display(rank),
        "suit": suit,
        "suit_name": SUIT_NAMES.get(suit, suit),
        "is_red": suit in RED_SUITS,
        "symbol": engine_symbol,
        "display_symbol": rank_display(rank) + engine_symbol[1:],
        "name": card.name(),
    }


def _cusp_numbers(card) -> list:
    """The card's cusps as ints.

    ``Cusp.number()`` returns the integer directly; parsing it out of
    ``cusp.name()`` ("Cusp 3") would couple this to a display string for no
    reason. Guarded individually for the same reason ``_body_row`` is — one
    unreadable cusp must not cost the whole spread (INV-12).
    """
    numbers = []
    for cusp in card.cusps():
        try:
            n = int(cusp.number())
        except Exception:                        # noqa: BLE001
            continue
        if 1 <= n <= 12:
            numbers.append(n)
    return numbers


def _period_year(index: int, birth_year):
    """The calendar year this position's 52-year period opens, or ``None``.

    Keyed on the spread POSITION, never on the planet name (INV-8). The position
    order is a user setting on our side and a Kala setting on theirs, and
    ``solar_system`` is a later addition — the same seat is called
    Mercury under one order and Mars under the other. Binding the year to a name
    would make the years follow the wrong cards the moment the order is flipped.
    """
    if index not in PERIOD_POSITIONS or birth_year is None:
        return None
    return birth_year + PERIOD_LENGTH_YEARS * (index - 1)


def _birth_year(chart):
    """The LOCAL calendar year of birth.

    ``usryear()``, never ``JulianDay.year()``. ``julian_day.py:165`` reads
    ``if tz != "utc:"`` — a stray colon — so ``year()`` and ``month()`` take the
    local branch under the default ``tz="utc"`` while ``day()`` and ``hour()``
    take the UTC one, and the same object answers in two frames. That is the
    SPEC-COT-001 E-6 defect class; bead td-tvhp. This routes around it rather
    than depending on it.
    """
    try:
        return int(chart.context.timeJD.usryear())
    except Exception:                            # noqa: BLE001
        return None


def _birth_date(chart):
    """The LOCAL calendar date of birth, or ``None``.

    The three ``usr*`` accessors, for the reason spelled out in
    :func:`_birth_year`: ``JulianDay.day()`` and ``JulianDay.year()`` answer in
    different frames under the default ``tz`` (the stray-colon defect,
    SPEC-COT-001 E-6), so mixing them can build a date that exists in neither.
    The engine's own ``_get_birth_card`` reads ``usrmonth()``/``usrday()``
    together for exactly this reason.

    This date is the anchor of the whole Age-N tier: the seven period dates and
    the Year Card are both measured from the CALENDAR birthday, never from the
    solar-return instant (SPEC-COT-004 INV-4).
    """
    try:
        jd = chart.context.timeJD
        return date(int(jd.usryear()), int(jd.usrmonth()), int(jd.usrday()))
    except Exception:                            # noqa: BLE001
        return None


def _body_row(planet) -> dict:
    """Describe one occupant body.

    Every accessor is guarded individually: a single body whose position cannot
    be read must not lose the whole spread, and the only field the renderer
    actually needs is ``name``. The extra fields feed the planet dialog and the
    CLI's ``--json``, so both surfaces get them from this one place.

    **An unreadable position is ``None``, never ``0``.** A zero degree is a real
    position, so substituting one turns a read failure into a plausible false
    reading that the tooltip and the planet dialog would present as fact. The
    ``position_known`` flag lets a consumer refuse to display rather than guess.
    (The body-graph view's ``_planet_pos`` does substitute 0; that is the older
    pattern, and it is the one this avoids.)
    """
    name = planet.identity()

    try:
        sign_raw = planet.sign()
        sign_index = sign_raw - 1 if isinstance(sign_raw, int) and 1 <= sign_raw <= 12 else None
    except Exception:                            # noqa: BLE001
        sign_index = None
    try:
        sign_name = planet.sign_name()
    except Exception:                            # noqa: BLE001
        sign_name = ""
    try:
        risl = planet.real_in_sign_longitude()
        degrees, minutes = int(risl), int((risl % 1) * 60)
    except Exception:                            # noqa: BLE001
        degrees, minutes = None, None
    try:
        decimal_degrees = float(planet.ecliptic_longitude())
    except Exception:                            # noqa: BLE001
        decimal_degrees = None
    try:
        is_retrograde = bool(planet.retrograde())
    except Exception:                            # noqa: BLE001
        is_retrograde = None

    return {
        "name": name,
        "sign": sign_name,
        "sign_index": sign_index,
        "degrees": degrees,
        "minutes": minutes,
        "decimal_degrees": decimal_degrees,
        "is_retrograde": is_retrograde,
        "position_known": degrees is not None and sign_index is not None,
    }


def assemble_spread(chart, order: str = DEFAULT_ORDER, varga_code=None) -> dict:
    """Build the 14-row birth spread for ``chart``.

    Args:
        chart: a libaditya ``Chart``.
        order: ``"solar_system"`` (Kala parity, the default) or ``"vedic"``.
        varga_code: a **libaditya** varga code (``core.varga_codes
            .to_libaditya_varga_code``), or ``None``/``1`` for the natal rashi.
            The spread is then bound to ``chart.varga(code)`` and the occupants
            are placed by their DIVISIONAL sign lord (INV-15 v2).

    **What a varga does and does not change** (measured across all 18 vargas the
    GUI offers): the fourteen card FACES and the birth card are byte-identical,
    because they come from the birth date through the quadration and no varga
    touches that. What moves is WHICH CARD each body falls in —
    ``_place_Objects`` files each planet under ``planet.lord()``, and
    ``Longitude.lord()`` reads ``const.lords[self.sign()]`` where ``sign()``
    already honours the amsha. So the divisional placement is what the engine
    computes natively; nothing here re-derives it.

    Returns a dict::

        {
          "order":      "solar_system",
          "birth_card": "3D",           # never changes with the varga
          "varga_code": None,           # libaditya code, None for natal D-1
          "cards": [ {                       # always 14 rows, index 0..13
              "index":        0,             # spread index
              "position":     "Base",        # position key (the label)
              "code":         "3D",          # engine two-letter code
              "rank":         "3",           # rank code ('T' for the ten)
              "rank_display": "3",           # '10' for the ten
              "suit":         "D",           # S/H/C/D
              "suit_name":    "diamond",
              "is_red":       True,
              "symbol":       "3♦",          # engine's rank+suit string
              "name":         "Three of Diamonds",
              "bodies":       [ {"name": "Moon", "sign": ..., "sign_index": ...,
                                 "degrees": ..., "minutes": ...,
                                 "decimal_degrees": ..., "is_retrograde": ...,
                                 "position_known": True},
                                 ... ],          # Earth/Chiron filtered out
                                                 # position fields are None, NOT
                                                 # 0, when unreadable
              "row":          1,             # 1-based grid row
              "col":          4,             # 1-based grid column
              "is_base":      True,
              "occupied":     False,         # bodies after filtering
          }, ... ]
        }

    Raises:
        CardsOfTruthUnavailable: the engine failed (see the class docstring).
        ValueError: unknown ``order``.
    """
    if order not in planet_order:
        raise ValueError(
            f"Unknown Cards of Truth order {order!r}; "
            f"must be one of {sorted(planet_order)}"
        )

    try:
        context = replace(chart.context, cot_planet_order=order)
        # D-1 is the natal rashi; every other code is a divisional chart. The
        # code is the LIBADITYA one (negative for the classical vargas), so this
        # is the same navamsa the rest of the app draws, not a parivritti twin.
        master = (chart.rashi() if varga_code in (None, 1)
                  else chart.varga(varga_code))
        cot = CardsOfTruth(context=context, master=master)
        birth_card = cot.birth_card()
        spread = cot.birth_spread()
        # Materialise every card inside the try: the engine defects fire lazily
        # on some paths, and a half-built spread must not escape as success.
        cards = [spread[i] for i in range(len(planet_order[order]))]
    except CardsOfTruthUnavailable:
        raise
    except Exception as exc:                     # noqa: BLE001 — INV-12 boundary
        raise CardsOfTruthUnavailable(
            f"{type(exc).__name__}: {exc}"
        ) from exc

    # SPEC-COT-002. One seat, taken from the deck the FACES come from, read in
    # all three quadrations. The engine owns the arithmetic; see
    # ``CoT.seat_rows`` for why the obvious API call is wrong and for the three
    # birth cards on which that wrongness is invisible.
    jack_row, queen_row, king_row = CoT.seat_rows(
        birth_card, decks=(JACK_QUAD, QUEEN_QUAD, KING_QUAD))
    if [c.card() for c in cards] != list(queen_row):
        # The queen row IS the birth spread. If they ever disagree, the seat has
        # drifted from the spread and every pip on screen would be off by the
        # same amount while still looking like plausible cards.
        raise CardsOfTruthUnavailable(
            "seat_rows disagrees with the birth spread — refusing to draw pips"
        )
    birth_year = _birth_year(chart)

    positions = planet_order[order]
    rows = []
    for idx, card in enumerate(cards):
        code = card.card()
        rank, suit = code[0], code[1]
        # INV-10: keep the engine's own order so two runs are pixel-identical.
        bodies = [_body_row(p) for p in card.planets()
                  if p.identity() not in OMITTED_BODIES]
        row, col = GRID[idx]
        rows.append({
            "index": idx,
            "position": positions[idx],
            "code": code,
            "rank": rank,
            "rank_display": rank_display(rank),
            "suit": suit,
            "suit_name": SUIT_NAMES.get(suit, suit),
            "is_red": suit in RED_SUITS,
            "symbol": card.symbol(),
            "name": card.name(),
            "bodies": bodies,
            "row": row,
            "col": col,
            "is_base": idx == 0,
            "occupied": bool(bodies),
            # SPEC-COT-002 §4.2. Named for the DECK each comes from, not for a
            # screen corner: the conventional layout places the king pip in the
            # top-right and the jack pip in the bottom-left, our layout stacks
            # them both in the left gutter, and a positional name would be false
            # in one of the two.
            "pip_jack": card_descriptor(jack_row[idx]),
            "pip_king": card_descriptor(king_row[idx]),
            "cusps": _cusp_numbers(card),
            "can_hold_cusps": positions[idx] in CLASSICAL_LORDS,
            "period_year": _period_year(idx, birth_year),
        })

    return {
        "order": order,
        "birth_card": birth_card,
        "varga_code": None if varga_code in (None, 1) else varga_code,
        "cards": rows,
    }


# --------------------------------------------------------------------- #
# The 7-year progression tier (SPEC-COT-003)
# --------------------------------------------------------------------- #

#: Years per progression period.
PROGRESSION_LENGTH_YEARS = 7

#: Progressions on the 364-year line. 52 x 7 = 364 = 7 x 52.
PROGRESSION_COUNT = 52

#: The engine's own deck order, as a tuple of two-letter codes.
#:
#: It IS Solar Value order, 0-indexed: ``AH``=0 .. ``KS``=51, so Solar Value is
#: ``index + 1``. Verified against the engine rather than assumed. The ``KD``
#: (38) -> ``AS`` (39) wrap is what proves it: a suit-grouped ordering would
#: put the next diamond there, and Ernst's spoken walk of Obama's ``9D`` through
#: ``TD JD QD KD AS`` crosses exactly that boundary.
#:
#: Taken from the engine's own ``Deck``, NOT from ``cards_constants.cards``.
#: SPEC-COT-002 INV-1 forbids app code importing that table, and its T-10 checks
#: the import list by AST — it caught this on the first run. The rule is real:
#: indexing the engine's raw table in app code is where an off-by-one stops
#: being an exception and becomes a different card that still looks like a card.
#:
#: ``Deck`` is a code-keyed mapping, so ``tuple(_DECK)`` is the deck order via
#: the engine's public object. The positional arithmetic that remains is
#: confined to ``progression_base_card`` and is pinned by eight reference anchors
#: including the ``KD -> AS`` wrap, which is the only place an off-by-one in the
#: ORDER (rather than the offset) could hide.
_DECK_CODES = tuple(_DECK)


def solar_value(code: str) -> int:
    """1-based Solar Value of a card code. ``AH`` is 1, ``KS`` is 52."""
    return _DECK_CODES.index(code) + 1


def progression_base_card(birth_code: str, age: int) -> str:
    """The base card of the 7-year progression containing ``age``.

    ``base = birth card advanced (1 + age // 7) steps in Solar Value order,
    mod 52`` (SPEC-COT-003 INV-2). The spread is then the ordinary 14-card walk
    from that card in the SAME queen quadration the birth spread uses; only the
    anchor moves.

    For ``3D`` (Solar Value 29): ages 0-6 give ``4D``, ages 7-13 give ``5D``.
    The walk closes back onto the birth card at block 51.

    Note the ``+1``: the FIRST block is already one step on, so age 0 is not the
    natal card. That is the part a reimplementation gets wrong, and it is wrong
    invisibly for six of every seven ages because ``age // 7`` hides it.
    """
    if age < 0:
        raise ValueError("age must not be negative")
    i = _DECK_CODES.index(birth_code)
    return _DECK_CODES[(i + 1 + age // PROGRESSION_LENGTH_YEARS) % PROGRESSION_COUNT]


def progression_blocks(birth_code: str, birth_year) -> list:
    """All 52 progression blocks, oldest first.

    ALL 52, never a lived-only subset (INV-6). A chart stays readable after its
    native dies -- an unresolved estate, a legacy still running -- so cropping to
    a lifetime deletes real chart rather than tidying it. The view magnifies the
    lived range with its carriage; it does not remove the rest.

    Costs about 2 ms for the whole set, because these are card faces and no
    ephemeris is involved. The expensive part is occupants, which the caller
    computes for the displayed block alone.
    """
    out = []
    for n in range(PROGRESSION_COUNT):
        age_start = n * PROGRESSION_LENGTH_YEARS
        code = progression_base_card(birth_code, age_start)
        out.append({
            "index": n,
            "age_start": age_start,
            "age_end": age_start + PROGRESSION_LENGTH_YEARS - 1,
            "year_start": None if birth_year is None else birth_year + age_start,
            "year_end": None if birth_year is None
                        else birth_year + age_start + PROGRESSION_LENGTH_YEARS - 1,
            "base_card": code,
            "card": card_descriptor(code),
            "is_natal_return": code == birth_code,
        })
    return out


def year_cells(block_index: int, birth_year) -> list:
    """The seven one-year cells of one progression block (INV-3).

    Kala already draws these and already labels them BY AGE: the "Ages 0 - 6"
    screen reads ``6 5 4 3 2 1 0`` left to right and "Ages 7 - 13" reads
    ``13 12 11 10 9 8 7``. So descending a level reads a number off a cell; it
    does not derive one.

    Returned in TIME order (youngest age first) carrying an explicit ``col``,
    because row 2 is drawn RIGHT TO LEFT with the Sun rightmost
    (SPEC-COT-001 INV-5). Iterating this list in place and drawing left to right
    reverses the time axis, which looks plausible and is wrong.
    """
    if not 0 <= block_index < PROGRESSION_COUNT:
        raise ValueError(f"block_index out of range: {block_index}")
    base_age = block_index * PROGRESSION_LENGTH_YEARS
    return [{
        "index": i,
        "age": base_age + i,
        "year": None if birth_year is None else birth_year + base_age + i,
        "col": GRID_COLS - i,          # i=0 (the Sun, first age) is the RIGHTMOST
    } for i in range(PROGRESSION_LENGTH_YEARS)]


def _progressed_chart(chart, days: int):
    """The natal chart advanced by ``days`` days — a SECONDARY progression.

    1 day = 1 year (SPEC-COT-003 §4.4b), so the chart behind a block that opens
    at age N is the natal chart N days later. **Block 0 opens at age 0 and its
    chart is therefore the natal chart itself**, and that is not a special case
    bolted on: it is the anchor the offset was pinned on. At zero days this
    returns the same object and the progressed spread comes back identical to
    the natal one, seat for seat, which is the only offset that can be true of
    the ages-0-6 block.

    The other half of the pinning is Lorris's ages 49-55 block: at +49 days his
    Moon seat empties and his Saturn seat takes three bodies, which is the
    occupancy the research recorded for that block. +7, +52 and +55 all leave
    the Moon seat occupied, so the offset is the block's FIRST age and not its
    index, its midpoint or its last age.

    Built from the chart's own types rather than by importing the engine's
    ``JulianDay``: nothing in this module should have to know how a Julian day
    is spelled, and INV-1 keeps engine internals out of app code.
    """
    if not days:
        return chart
    jd = chart.context.timeJD
    moved = type(jd)(jd=jd.jd + days,
                     utcoffset=getattr(jd, "utcoffset", 0),
                     timezone=jd.timezone())
    return type(chart)(context=replace(chart.context, timeJD=moved))


def assemble_progression_spread(chart, order: str = DEFAULT_ORDER,
                                varga_code=None, block_index: int = 0) -> dict:
    """The 14-card spread of one 7-year progression block.

    Identical in shape to :func:`assemble_spread`, and identical in machinery
    apart from the anchor card, so the two cannot drift apart in layout, pip or
    cusp handling.

    The extra keys are ``progression_index``, ``age_start``/``age_end``,
    ``base_card`` and ``progressed_days``; ``birth_card`` still reports the NATAL
    card, so a consumer can always tell which spread it is holding. A progressed
    spread that reported the progressed card as ``birth_card`` would be
    indistinguishable from a natal one at every call site that checks it.

    The faces come from the progression, the **occupants and cusps come from a
    secondary progression** of the natal chart by ``age_start`` days
    (:func:`_progressed_chart`). The two halves have different sources and must:
    a progression's fourteen faces are calendar arithmetic on the birth card and
    cost no ephemeris, while where the bodies fall is a real chart.

    Each row-2 card also carries ``age`` and ``ruler_year`` (SPEC-COT-005 §3.7,
    D-4), joined on ``col`` and NOT on list position: index 0 is the base card in
    row 1, so ``cards[:7]`` — the obvious reading of "row 2" — writes age 0 onto
    the head card and shifts the whole row by one.

    The years travel in ``ruler_year`` rather than in ``period_year``, which
    stays ``None``. ``period_year`` counts 52-year periods and the view's
    ``_paint_year`` draws it in the card corner, which SPEC-COT-003 §4.4 forbids
    on a progressed card. Two different quantities behind one key is how the
    corner year would come back without anybody asking for it.

    Raises:
        ValueError: ``block_index`` outside 0..51. It used to index the block
            list raw: 52 raised a bare ``IndexError`` from inside a helper, and
            -1 silently returned block 51 — a complete, plausible spread for
            ages 357-363 with nothing anywhere saying it was not what was asked
            for (SPEC-COT-005 §2.7).
    """
    if not 0 <= block_index < PROGRESSION_COUNT:
        raise ValueError(
            f"block_index out of range: {block_index!r} "
            f"(expected 0..{PROGRESSION_COUNT - 1})")

    data = assemble_spread(chart, order=order, varga_code=varga_code)
    # The birth year, NOT ``None``. Hardcoding it here was one line and it cost
    # the whole progression tier its calendar: every one of the 52 blocks came
    # back with ``year_start`` None, so the band lost all 52 year lines, the
    # TODAY needle vanished and the ladder reset on every re-assembly. Nothing
    # downstream could recover it, because the payload carried no year at all.
    birth_year = _birth_year(chart)
    block = progression_blocks(data["birth_card"], birth_year)[block_index]
    base = block["base_card"]

    # RE-WALK the faces from the progressed anchor. Taking the base card and
    # then returning ``data`` unchanged is the defect this function shipped
    # with: every one of the 52 blocks came back holding the NATAL fourteen
    # while ``is_progressed`` said True, so the payload actively lied. It was
    # invisible because the base card -- the one thing a reader checks -- was
    # right, and no test called this function at all.
    jack_row, queen_row, king_row = CoT.seat_rows(
        base, decks=(JACK_QUAD, QUEEN_QUAD, KING_QUAD))

    # Keyed by COLUMN, because that is the join. Row 2 is spread indices 1..7 at
    # columns 7 down to 1, and ``year_cells`` returns index 0 (age 0) at column
    # 7 — the same right-to-left axis, stated the same way on both sides.
    by_col = {cell["col"]: cell for cell in year_cells(block_index, birth_year)}

    # The occupants and the cusps, from the SECONDARY progression. Grafted seat
    # by seat ON INDEX, and that is safe for the one reason worth stating: both
    # spreads are assembled under the SAME ``order``, so seat i carries the same
    # POSITION in both — ``_place_Objects`` files by ``planet.lord()`` onto the
    # position, never onto the face — and the faces we keep are the
    # progression's while the bodies we take are the progressed chart's. Join on
    # anything else and the two orders would silently disagree, because the
    # order permutes which lord owns which seat.
    #
    # A failure here empties the rail instead of raising: the fourteen FACES are
    # already correct and are what a reader mostly came for, so losing the whole
    # spread over an ephemeris problem trades a complete answer for none.
    # ``Exception``, not ``CardsOfTruthUnavailable``, and the difference is not
    # defensive taste. ``_progressed_chart`` is evaluated as an ARGUMENT, so it
    # runs before ``assemble_spread`` is entered and its INV-12 boundary never
    # sees it — and building a Chart runs Swiss Ephemeris immediately, which
    # raises its own errors. Narrowing this to the wrapper lets a raw ephemeris
    # failure escape past the fallback that INV-6 promises, losing fourteen
    # already-correct faces to a problem with the occupants.
    progressed = None
    occupants_error = None
    try:
        progressed = assemble_spread(
            _progressed_chart(chart, block["age_start"]),
            order=order, varga_code=varga_code)
    except Exception as exc:                     # noqa: BLE001 — INV-6 boundary
        occupants_error = f"{type(exc).__name__}: {exc}"

    for idx, row in enumerate(data["cards"]):
        row.update(card_descriptor(queen_row[idx]))
        row["pip_jack"] = card_descriptor(jack_row[idx])
        row["pip_king"] = card_descriptor(king_row[idx])
        # Never the NATAL bodies. Natal occupants on progressed faces are a new
        # wrong answer rather than a missing one, and they are the answer this
        # loop would produce by leaving ``data`` alone.
        source = progressed["cards"][idx] if progressed else None
        row["bodies"] = [] if source is None else source["bodies"]
        row["occupied"] = False if source is None else source["occupied"]
        row["cusps"] = [] if source is None else source["cusps"]
        # ``period_year`` counts 52-year periods and means nothing here (INV-9).
        row["period_year"] = None
        cell = by_col.get(row["col"]) if row["row"] == 2 else None
        row["age"] = None if cell is None else cell["age"]
        row["ruler_year"] = None if cell is None else cell["year"]

    data.update({
        "kind": "progression",
        "level": 1,
        "progression_index": block_index,
        "age_start": block["age_start"],
        "age_end": block["age_end"],
        "base_card": base,
        "is_progressed": True,
        # True only when the progressed chart could not be built, so the view's
        # "positions not shown yet" note appears when it is TRUE and not merely
        # when the spread happens to be a progression.
        "occupants_pending": progressed is None,
        # Why they are pending, so a failure is diagnosable from the payload
        # alone — the CLI's --json is the only view some callers get.
        "occupants_error": occupants_error,
        "progressed_days": block["age_start"],
    })
    return data


# --------------------------------------------------------------------- #
# The Age-N quadration tier (SPEC-COT-007)
# --------------------------------------------------------------------- #

#: Ages on the quadration line.
#:
#: 90, not 52 and not 364, because ``CoT.quadrate`` has order 90: the 90th
#: quadration is the last one that differs from the first and the 91st repeats
#: it. Verified against the engine, not assumed. Any ``n`` may therefore be
#: reduced mod 90 before quadrating, which is what keeps the deepest cell of the
#: rail as cheap as the shallowest.
QUADRATION_COUNT = 90

#: The two seats that outrank the rest in the Year Card scan (SPEC-COT-004
#: §3.6a). Indices into the spread, valid under BOTH position orders: the order
#: permutes which planet owns seats 1-7 and leaves 0 and 8-13 alone, so Base and
#: Ecliptic are the same seat in ``vedic`` and ``solar_system``.
BASE_SEAT = 0
ECLIPTIC_SEAT = 10

#: Ranks, strongest first. Numbers rather than names because they sort.
RANK_ECLIPTIC = 1     # "that ecliptic card is the path that you're on that year"
RANK_BASE = 2         # the birth card, or the running 52-year period card
RANK_OTHER = 3        # "a year of greater importance relevant to that card"

#: Sorts a spread with no match last without pretending it has a rank.
_RANK_NONE = 99

#: Ernst's own names for the three spreads, as the ledger prints them.
#:
#: INV-13 — the word "coincidence" is not a reader-facing term and appears nowhere on
#: screen. It is a programmer's word for an empty result. The function is called
#: :func:`coincidences` because that is what the spec names the call; every
#: string a person reads comes from here.
SPREAD_LABELS = {
    "life": "in your life spread",
    "progression": "in the seven year progression",
    "year": "in this year's own spread",
}

#: The one line under the ledger, per spread rank. INV-3/INV-7 — significance,
#: never valence. Not one of these says whether the year is good.
RANK_COPY = {
    RANK_ECLIPTIC: "The ecliptic card is the path you are on this year.",
    RANK_BASE: "An important year.",
    RANK_OTHER: "A year of greater importance for whatever {position} carries.",
}

#: Printed when nothing matches. INV-4 — an empty result is NORMAL. The King of
#: Spades turns up as a Year Card once every 364 years, so most people never see
#: it at all, and 29 of Lorris's first 90 ages are blank across all three
#: spreads the ledger scans (61 carry a hit; both figures pinned in Q-5, per
#: INV-5a — the stale two-spread count was 43 hit / 47 blank). Copy that
#: apologises for a blank state would be apologising for the technique working
#: as taught.
EMPTY_COPY = ("The Year Card does not turn up in any of these spreads. "
              "That is the ordinary case, not a gap.")

#: The two closing lines, verbatim from SPEC-COT-007 §3.7.
LEDGER_FOOTER = ("The match says the year matters. The card says how.")

#: What the ledger prints on a spread with no match.
NO_MATCH_COPY = "it does not turn up"


def period_seat_for_age(age: int):
    """The row-2 seat whose 52-year period is running at ``age``, or ``None``.

    Seat 1 (the Sun position) covers ages 0-51, seat 2 covers 52-103, and so on
    to seat 7. Past age 363 the seven periods are exhausted and there is no
    running one; ``None`` says so rather than wrapping, because a wrapped seat
    would silently give a 400-year-old chart a rank-2 match it has not earned.

    Keyed on the SEAT, never on the planet name (INV-8): ``solar_system`` and
    ``vedic`` disagree about which planet sits at seats 4, 5 and 6, and binding
    the period to a name would make it follow the wrong card the moment the
    order is flipped.
    """
    if age < 0:
        raise ValueError("age must not be negative")
    seat = 1 + age // PERIOD_LENGTH_YEARS
    return seat if seat in PERIOD_POSITIONS else None


def _seat_rank(seat: int, age):
    """Rank of a match at ``seat``, per the SPEC-COT-007 §3.2 table."""
    if seat == ECLIPTIC_SEAT:
        return RANK_ECLIPTIC
    if seat == BASE_SEAT:
        return RANK_BASE
    if age is not None and seat == period_seat_for_age(age):
        return RANK_BASE
    return RANK_OTHER


def coincidences(year_code, spreads, order: str = DEFAULT_ORDER, age=None) -> list:
    """Where the Year Card falls across several spreads, ranked.

    SPEC-COT-007 §3.2. Regarded as one of the most valuable techniques in this
    system by its author, worth learning on its own, and it is fourteen string
    comparisons per spread.

    Args:
        year_code: the Year Card's two-letter code, or ``None``. ``None``
            returns an empty list: nothing to scan for is not the same question
            as scanned-and-found-nothing, and a caller must be able to tell the
            two apart.
        spreads: ``{key: [14 card codes in SEAT order]}``. Insertion order is
            preserved among equally ranked entries, so a caller controls the
            tie-break by the order it builds the mapping.
        order: position order, used only to NAME the seats. It cannot move the
            ranks: Base and Ecliptic are the same seat under both orders.
        age: the age being scored, which promotes the running 52-year period
            card to rank 2 alongside the birth card. Optional because the rank
            table only needs it for that one clause, and because a caller
            scanning a spread that is not tied to an age has no honest value to
            pass. **Not in the spec's signature** — see the report; without it
            the second half of rank 2 is unimplementable.

    Returns:
        One dict per spread, strongest first::

            {"key": "year", "label": "in this year's own spread",
             "seats": [8], "positions": ["Rahu"],
             "rank": 3, "matched": True, "copy": "..."}

        ``seats`` is empty and ``rank`` is ``None`` when the card does not turn
        up. **INV-4 — that is normal**, not an error and not a blank state that
        apologises.

        **INV-5 — this is a LIST across spreads, never a boolean.** Ernst's
        strongest demonstration is Angelina Jolie's age 7, where ``6D`` is the
        Year Card, the Venus card and the running 52-day period at once:
        *"Six of Diamonds, Six of Diamonds, Six of Diamonds down to three
        levels"*. Depth is the finding; a boolean throws it away.

        **INV-3 — no entry carries a good/bad flag**, and none ever may. The
        match says the year matters; the card and its occupants say how
        (SPEC-AVA-001 D11).
    """
    if not year_code:
        return []

    positions = planet_order[normalise_order(order)]
    out = []
    for key, codes in spreads.items():
        seats = [i for i, code in enumerate(codes) if code == year_code]
        names = [positions[i] if i < len(positions) else str(i) for i in seats]
        rank = min((_seat_rank(i, age) for i in seats), default=None)
        if rank is None:
            copy = None
        else:
            # The named position is the FIRST seat at the winning rank, so the
            # sentence talks about the card the rank was earned by. Taking
            # ``names[0]`` instead would name a rank-3 seat under a rank-1
            # headline whenever a card appears twice in one spread.
            best = next(n for i, n in zip(seats, names)
                        if _seat_rank(i, age) == rank)
            copy = RANK_COPY[rank].format(position=best)
        out.append({
            "key": key,
            "label": SPREAD_LABELS.get(key, key),
            "seats": seats,
            "positions": names,
            "rank": rank,
            "matched": bool(seats),
            "copy": copy,
        })
    # Stable, so equal ranks keep the caller's order.
    out.sort(key=lambda entry: _RANK_NONE if entry["rank"] is None else entry["rank"])
    return out


def quadration_deck(age: int) -> list:
    """The deck the Age-``age`` quadration is dealt from, as deck INDICES.

    ``quadraten(jackquad, age + 1)`` — SPEC-COT-004 §2.1. **The ``+1`` is the
    whole trap.** ``quadraten(jack, n+1) == quadraten(queen, n)``, so the jack
    deck quadrated ``age + 1`` times is the queen deck quadrated ``age`` times,
    which is what the screen shows. It looks off by one and is not. A
    reimplementation pinned on ``age`` alone agrees at age 0 — where the deck is
    the queen quadration and the spread is the birth spread — and is wrong at
    every other age, which is exactly the shape of a bug that survives a
    hand-check.

    Reduced mod 90 first: ``quadrate`` has order 90, so nothing on the rail ever
    needs more than 89 shuffles.

    ``list(JACK_QUAD)`` because ``JACK_QUAD`` is a tuple on purpose (INV-7:
    ``jack_quadration()`` hands out the engine's own list, and one in-place
    mutation would corrupt every quadration in the process) while ``quadraten``
    calls ``.copy()`` on what it is given.
    """
    if age < 0:
        raise ValueError("age must not be negative")
    return CoT.quadraten(list(JACK_QUAD), (age + 1) % QUADRATION_COUNT)


def _quadration_decks(age: int):
    """``(deck(age-1), deck(age), deck(age+1))`` — the three pip decks.

    The birth spread's three cards per cell are ONE seat read in three
    CONSECUTIVE quadrations: jack, queen, king — that is ``quadraten(jack, 0)``,
    ``(jack, 1)`` and ``(jack, 2)``. The Age-N spread's face deck is
    ``quadraten(jack, age + 1)``, so the same relation gives it
    ``quadraten(jack, age)`` and ``quadraten(jack, age + 2)`` for its two pips.

    At age 0 that reduces to exactly the jack/queen/king triple, so the Age 0
    quadration and the birth spread come out identical card for card and pip for
    pip — which is the one thing that must be true of an Age 0 screen, and is
    the reason the relation is written this way rather than pinning the pips to
    the natal jack and king decks forever.

    Built in ONE walk. Three separate ``quadraten`` calls would shuffle a
    52-card deck ``3 * age`` times for three decks that are one shuffle apart.
    """
    start = age % QUADRATION_COUNT
    deck = CoT.quadraten(list(JACK_QUAD), start)
    lower = deck
    middle = CoT.quadrate(deck.copy())
    upper = CoT.quadrate(middle.copy())
    return lower, middle, upper


def quadration_ages(birth_card: str, birth_date) -> list:
    """All 90 ages of the quadration line, youngest first.

    Shaped like :func:`progression_blocks` so the ladder can paint either family
    from one painter (SPEC-COT-007 INV-7: the family is DATA, not a branch).

    Args:
        birth_card: the chart's birth card code.
        birth_date: the LOCAL calendar date of birth, or ``None``. Without it
            there is no Year Card and no calendar year; both come back ``None``
            and the rail still has 90 cells.

    Returns 90 dicts::

        {"index": 7, "age": 7, "age_start": 7, "age_end": 7,
         "year": 1998, "year_start": 1998, "year_end": 1998,
         "birthday": date(1998, 2, 22),
         "base_card": "3D", "card": {...},          # the BASE seat, invariant
         "year_card": "9S", "year_card_face": {...},
         "is_natal_return": False}

    **``base_card`` is the birth card at every one of the 90 ages, and that is
    not a stub.** ``get_birthspread_from_quadration`` opens each quadrated deck
    AT the birth card, so seat 0 holds it by construction however many times the
    deck has been shuffled. It is carried anyway, for shape parity with
    :func:`progression_blocks` and because a reader checking the rail needs to
    see that it does not move. What discriminates one age from the next on this
    line is the YEAR CARD; a rail painted from ``base_card`` draws ninety
    identical cells and looks like a bug in the ladder.

    ``is_natal_return`` therefore means something different here than on the
    progression line, and deliberately: it is TRUE where the **Year Card**
    returns to the birth card. On the progression line the base card moves and
    the return is a base-card event; here the base card cannot move and the Year
    Card can. Same key, same question — "is this the year the natal card comes
    back" — different mechanism.

    Costs no ephemeris and about a millisecond: 90 date walks and 90 table
    lookups.
    """
    year_zero = None if birth_date is None else birth_date.year
    # WI-6/DEF-2: anchor the Year Card walk on the day whose day_card equals the
    # chart's sunrise-aware birth card (birth minus one day before sunrise), so
    # age 0 is the birth card for EVERY birth hour, not only after sunrise. The
    # year label and the birthday stay on the calendar birthday, untouched.
    anchor = None if birth_date is None else year_card_anchor(birth_date, birth_card)
    out = []
    for age in range(QUADRATION_COUNT):
        code = None if anchor is None else year_card(anchor, age)
        year = None if year_zero is None else year_zero + age
        out.append({
            "index": age,
            "age": age,
            "age_start": age,
            "age_end": age,
            "year": year,
            "year_start": year,
            "year_end": year,
            "birthday": (None if birth_date is None
                         else birthday_for_age(birth_date, age)),
            "base_card": birth_card,
            "card": card_descriptor(birth_card),
            "year_card": code,
            "year_card_face": None if code is None else card_descriptor(code),
            "is_natal_return": code == birth_card,
        })
    return out


def assemble_quadration_spread(chart, order: str = DEFAULT_ORDER,
                               varga_code=None, age: int = 0) -> dict:
    """The 14-card spread of the Age-``age`` Quadration.

    SPEC-COT-007 §3.1-§3.3. Identical in shape to :func:`assemble_spread` and
    :func:`assemble_progression_spread`, and built through the same machinery,
    so the three cannot drift apart in layout, pip or cusp handling.

    The faces come from ``get_birthspread_from_quadration(birth_card,
    quadraten(jackquad, age + 1))`` — see :func:`quadration_deck` for why the
    ``+1`` is right and looks wrong.

    **FACES ONLY (SPEC-COT-007 §6).** ``bodies`` is empty, ``occupied`` is
    False, ``cusps`` is empty and ``occupants_pending`` is True on every card.
    That is a scope decision, not a failure: the occupants of an Age-N spread
    come from a chart cast for the CALENDAR BIRTHDAY at the birth time and place
    (SPEC-COT-004 INV-5), which is a real ephemeris call and sits behind a known
    engine defect — ``YearSpread._get_Planets`` casts a SOLAR RETURN where the
    birthday chart belongs, and on Lorris age 2 the two are on different
    calendar days and disagree on the Ascendant, the MC and every cusp. Shipping
    the engine's current occupants would put thirteen wrong bodies under
    fourteen right faces. ``occupants_error`` stays ``None`` because nothing
    failed; ``faces_only`` says why they are absent.

    Each row-2 card carries its own **period start date**, joined on ``col`` and
    NOT on list position — spread index 0 is the base card in row 1, so
    ``cards[:7]`` writes period 0 onto the head card and shifts the whole row by
    one. Row 2 runs RIGHT TO LEFT with the earliest period rightmost, which is
    why ``col`` is ``GRID_COLS - index`` on both sides of the join.

    ``period_year`` stays ``None``: it counts 52-YEAR periods and the view draws
    it in the card corner, which means nothing on a year spread. The 52-DAY
    period dates travel in ``period_start``/``period_end``. Two different
    quantities behind one key is how the corner year comes back without anybody
    asking for it (SPEC-COT-005 D-4).

    Extra keys: ``kind``, ``quadration_index``, ``age``, ``birth_date``,
    ``year_card``, ``year_card_face``, ``coincidences``, ``periods``,
    ``faces_only``. ``birth_card`` still reports the NATAL card, so a consumer
    can always tell which spread it is holding.

    Raises:
        ValueError: ``age`` outside 0..89. Not left to the modulo: age 90 IS
            age 0's deck and would return a complete, plausible spread for a
            question nobody asked, exactly the failure mode ``--block -1`` had
            on the progression tier.
        CardsOfTruthUnavailable: the engine could not build the natal spread.
    """
    if not 0 <= age < QUADRATION_COUNT:
        raise ValueError(
            f"age out of range: {age!r} (expected 0..{QUADRATION_COUNT - 1})")

    data = assemble_spread(chart, order=order, varga_code=varga_code)
    birth_card = data["birth_card"]
    # Captured BEFORE the loop below overwrites the rows. The life spread is one
    # of the three the Year Card is scored against, and it is the natal fourteen
    # this call already holds — recomputing it would be a second source for the
    # same faces.
    life_codes = [row["code"] for row in data["cards"]]
    birth_date = _birth_date(chart)

    lower, middle, upper = _quadration_decks(age)
    jack_row, queen_row, king_row = CoT.seat_rows(
        birth_card, decks=(lower, middle, upper))

    periods = [] if birth_date is None else quadration_periods(birth_date, age)
    # Keyed by COLUMN. Period index 0 (the Sun seat, the year's first 52 days)
    # is the RIGHTMOST card, the same right-to-left axis ``year_cells`` states.
    by_col = {GRID_COLS - period["index"]: period for period in periods}

    # WI-10 / SPEC-COT-004 §3.3 (INV-5): the occupants and cusps come from a
    # chart cast for the CALENDAR BIRTHDAY of age N, at the birth time and
    # place -- NOT the solar return. §3.3 is the proof: at age 2 a solar return
    # puts the Ascendant in the Mars card and the MC in the Sun card, while the
    # birthday chart and Kala both put them in the Mercury and Saturn cards
    # (13/13). ``anniversary_chart`` builds that chart with local-civil-date
    # arithmetic, one build, no return search.
    #
    # Grafted seat by seat ON INDEX, safe for the one reason worth stating: the
    # quadration spread and the anniversary spread are assembled under the SAME
    # ``order``, so seat i carries the same POSITION in both, and
    # ``_place_Objects`` files bodies and cusps by ``lord()`` onto the position,
    # never onto the face. The faces we keep are the quadration's; the bodies we
    # take are the birthday chart's. Join on anything but the seat index and the
    # two orders silently disagree, because the order permutes which lord owns
    # which seat.
    #
    # A failure empties the rail instead of raising, exactly as COT-006 INV-6
    # requires: the fourteen FACES are already correct and are what a reader
    # mostly came for, so losing the whole spread to an ephemeris problem trades
    # a complete answer for none. ``Exception``, not a narrow engine type:
    # ``anniversary_chart`` runs Swiss Ephemeris immediately and it is CALLED
    # here rather than passed as an argument, so a narrow catch would let a raw
    # ephemeris failure escape the fallback INV-6 promises.
    occupants = None
    occupants_error = None
    try:
        occupants = assemble_spread(
            anniversary_chart(chart, age), order=order, varga_code=varga_code)
    except Exception as exc:                     # noqa: BLE001 — INV-6 boundary
        occupants_error = f"{type(exc).__name__}: {exc}"

    for idx, row in enumerate(data["cards"]):
        row.update(card_descriptor(queen_row[idx]))
        row["pip_jack"] = card_descriptor(jack_row[idx])
        row["pip_king"] = card_descriptor(king_row[idx])
        # The birthday chart's bodies and cusps, grafted by seat index. Never
        # the NATAL bodies on quadrated faces (a wrong answer, not a missing
        # one); the source is the anniversary spread or nothing.
        source = occupants["cards"][idx] if occupants else None
        row["bodies"] = [] if source is None else source["bodies"]
        row["occupied"] = False if source is None else source["occupied"]
        row["cusps"] = [] if source is None else source["cusps"]
        row["period_year"] = None
        period = by_col.get(row["col"]) if row["row"] == 2 else None
        row["period_index"] = None if period is None else period["index"]
        row["period_start"] = None if period is None else period["start"]
        row["period_end"] = None if period is None else period["end"]
        row["period_days"] = None if period is None else period["calendar_days"]

    # WI-6/DEF-2: sunrise-aware Year Card anchor (see quadration_ages).
    year_code = (None if birth_date is None
                 else year_card(year_card_anchor(birth_date, birth_card), age))
    # The three spreads of the ledger, in the order §3.7 prints them. Equal
    # ranks keep this order, so a tie reads life, progression, year.
    progression_codes = CoT.seat_rows(
        progression_base_card(birth_card, age),
        decks=(JACK_QUAD, QUEEN_QUAD, KING_QUAD))[1]
    scan = coincidences(year_code, {
        "life": life_codes,
        "progression": list(progression_codes),
        "year": list(queen_row),
    }, order=order, age=age)

    data.update({
        "kind": "quadration",
        "level": 1,
        "quadration_index": age,
        "age": age,
        "age_start": age,
        "age_end": age,
        # Invariant across all 90 ages; see :func:`quadration_ages`.
        "base_card": birth_card,
        "birth_date": birth_date,
        "year_card": year_code,
        "year_card_face": None if year_code is None else card_descriptor(year_code),
        "coincidences": scan,
        "periods": periods,
        "is_progressed": False,
        # WI-10: the bodies now come from the birthday chart (§3.3), so pending
        # is TRUE only when that chart could not be built -- mirroring COT-006
        # INV-4, never a synonym for "this is a quadration". ``occupants_error``
        # says why, for the CLI's --json (the only view some callers get).
        "occupants_pending": occupants is None,
        "occupants_error": occupants_error,
        # The SPEC-COT-007 §6 faces-only non-goal is lifted; the occupants ship.
        "faces_only": False,
        # The calendar birthday the anniversary chart was cast for, so the CLI
        # can be checked against the GUI (Rule 24). None without a birth date.
        "anniversary_date": (None if birth_date is None
                             else birthday_for_age(birth_date, age).isoformat()),
    })
    return data
