"""The Age-N Quadration's seven periods inside one year of life.

SPEC-COT-004. Qt-free, engine-free, ephemeris-free: this whole module is
calendar arithmetic, which is the point.

**The Age-N Quadration screen is not a solar return.** Neither its
dates nor its planets are. This module owns the dates; the planets belong to a
chart cast for the calendar birthday at the birth time and place, which is a
separate concern and a separate (still open) engine defect.

The rule
--------

A **card day** is any calendar day except **31 December** and **29 February**.
The manual is explicit that those two get no spread and continue the previous
day's themes. Every birthday-to-birthday span therefore contains exactly **364
card days**, whether the calendar span is 365 or 366, and 364 = 7 x 52 exactly.

Boundary ``k`` is ``52 * k`` card days after the calendar birthday.

Why not the obvious rules
-------------------------

Three simpler rules reproduce most of the evidence, which is what makes them
dangerous rather than merely wrong:

* **52 CALENDAR days.** Passes six of seven boundaries on a 22 February
  birthday and fails only at ``k=6`` (``11/9 + 52 = 12/31``, but the screen
  shows ``1/1``). A developer hand-checking one chart sees 86% agreement.
* **floor(k * 365.2422 / 7) calendar days.** Fits a 22 February birthday
  *exactly*, on all seven boundaries, in every non-leap year — because from
  22 February the 31 December skip lands at calendar offset exactly
  ``312 = 52 * 6``, so the two rules coincide. It is a curve fit to one
  birthday. Gene Kelly (23 August) separates them in one line.
* **Seven equal arcs of solar longitude (360/7).** The intuitive guess, since
  the screen feels like a solar return. Residuals ``0,-1,0,+2,+3,+3,+1`` days.

The evidence that settles it is 16 spreads / 112 boundaries across 8 charts,
104 exact; see the spec. ``test/reference_charts/kala_cot_agen_2026-07-27/``
holds the Lorris half.
"""

from __future__ import annotations

from datetime import date, timedelta

# The ONE engine import this module is allowed, and the reason it is allowed:
# ``day_card`` answers "which card does this calendar day carry", and the answer
# lives in exactly these two tables. SPEC-COT-001 INV-1 forbids app code
# *composing* a face out of engine internals; re-typing 52 card codes and twelve
# month offsets here would be precisely that, and it would drift silently the
# first time the engine corrects one (it corrected November on 2026-07-27 —
# E-4). Reading the engine's own tables cannot drift in CONTENT; only the index
# arithmetic below is ours, and it is a line-for-line mirror of
# ``CardsOfTruth._get_birth_card``'s post-sunrise branch, pinned by Q-1/Q-3.
from libaditya.cards.cards_constants import (
    birth_card_order as _BIRTH_CARD_ORDER,
    first_card_of_the_month as _FIRST_CARD_OF_THE_MONTH,
)

#: Seven planetary periods per year of life.
PERIODS_PER_YEAR = 7

#: Card days per period. 7 x 52 = 364, the manual's year.
CARD_DAYS_PER_PERIOD = 52

#: Card days in any year of life, leap or not.
CARD_DAYS_PER_YEAR = PERIODS_PER_YEAR * CARD_DAYS_PER_PERIOD


def is_card_day(d: date) -> bool:
    """Whether ``d`` carries a card.

    31 December and 29 February do not. Everything else does.
    """
    if d.month == 12 and d.day == 31:
        return False
    if d.month == 2 and d.day == 29:
        return False
    return True


def card_days_between(start: date, end: date) -> int:
    """Card days from ``start`` (inclusive) to ``end`` (exclusive).

    Counted by walking, not by a closed form. A closed form has to special-case
    the leap rule, the December boundary and spans that contain neither, and the
    walk is a few hundred iterations for the longest span this module is ever
    asked about (one year of life). Correctness is worth more than the
    microseconds here, and the whole screen costs well under a millisecond.

    Negative when ``end`` precedes ``start``, so the function composes.
    """
    if end < start:
        return -card_days_between(end, start)
    n, d = 0, start
    while d < end:
        if is_card_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def add_card_days(start: date, count: int) -> date:
    """The date reached by advancing ``count`` card days from ``start``.

    ``start`` itself is not counted, so ``add_card_days(d, 0) is d``. Skipped
    days are stepped over silently: advancing one card day from 30 December
    lands on 1 January, never on the 31st.
    """
    if count < 0:
        raise ValueError("count must not be negative")
    d, remaining = start, count
    while remaining > 0:
        d += timedelta(days=1)
        if is_card_day(d):
            remaining -= 1
    return d


def day_card(d: date) -> str:
    """The card a calendar day carries, as a two-letter engine code.

    SPEC-COT-007 §3.1. Pure table lookup: no chart, no ephemeris, no sunrise.
    Only the month and the day are read — the year never enters, which is why
    the seven period dates of INV-2 are fixed for a person and why the Year Card
    walk is leap-invariant.

    This is the ``_get_birth_card`` calculation with the sunrise question
    already answered. The engine has to ask it because a birth before sunrise
    takes the PREVIOUS day's card; a date has no clock and takes its own.
    Consequence worth stating: ``day_card(birth_date)`` equals the chart's birth
    card for every birth after sunrise, and is one card early for a birth
    before it. Callers that need the chart's card must read the chart.

    31 December and 29 February are not card days (:func:`is_card_day`), and
    neither is given a card of its own here either. 31 December runs one past
    the 52-card sequence and clamps onto 30 December's Ace of Hearts, exactly as
    the published table shows and exactly as the engine does. 29 February keeps
    the raw table row the engine gives it, which is NOT 28 February's card; that
    row is the trap behind INV-6 (see :func:`year_card`), and it is preserved
    rather than smoothed over so that ``day_card`` and the engine's birth card
    agree for a 29 February birth.
    """
    index = _FIRST_CARD_OF_THE_MONTH[d.month - 1] + (d.day - 1)
    if index >= len(_BIRTH_CARD_ORDER):
        index = len(_BIRTH_CARD_ORDER) - 1
    return _BIRTH_CARD_ORDER[index]


def year_card(birth: date, age: int) -> str:
    """The Year Card of the Age-``age`` year: ONE card day per year of life.

    SPEC-COT-004 §3.6, SPEC-COT-007 §3.1. ``day_card(add_card_days(birth, age))``
    and nothing else.

    **INV-2 / SPEC-COT-004 INV-6 — advance by DATE, never by deck index.** The
    Year Card appears to retreat one Solar Value per age, and for a February
    birthday it does so for seven ages running, so walking
    ``birth_card_order`` by index looks right and is wrong. That table has its
    own 29 February row holding ``9C``, so the index walk returns ``9C`` at
    age 7 where the calendar walk crosses into March and returns ``9S``. The
    Solar Value jumps 23 -> 48 there because ``SV = 55 - (2*month + day)`` and
    the month term steps by 2: "one step backward per age" is a description of
    a February birthday, not an invariant, and must not be implemented as one.

    Frozen oracle, Lorris (1991-02-22, birth card ``3D``), ages 0-10::

        3D 2D AD KC QC JC TC 9S 8S 7S 6S
                             ^^ age 7, the discriminator

    ``year_card(birth, 0) == day_card(birth)`` by construction, which is why the
    Age 0 screen shows the birth card twice. That duplicate is correct and must
    not be suppressed; it is also that person's first rank-2 match.

    **Sunrise (WI-6).** This is pure calendar: it has no clock and cannot see
    sunrise. For a birth BEFORE sunrise the chart's birth card is the PREVIOUS
    day's card, so passing the raw calendar ``birth`` here reads one card too
    far along the retreating walk at EVERY age — the whole life is displaced,
    not only age 0 (Kala, Alain Delon 1935-11-08 03:25, eleven ages). A caller
    that has the chart's sunrise-aware birth card must pass
    :func:`year_card_anchor` ``(birth, birth_card)`` as ``birth`` here so the
    walk starts from the right card. After sunrise the anchor is ``birth`` and
    this is a no-op; the pure-calendar signature stays for callers with no
    chart.
    """
    return day_card(add_card_days(birth, age))


def year_card_anchor(birth: date, birth_card: str) -> date:
    """The calendar day the Year Card walk must start from (WI-6 / DEF-2).

    :func:`day_card` has no clock, but the chart's birth card is sunrise-aware:
    a birth before sunrise takes the PREVIOUS day's card. So ``day_card(birth)``
    equals the chart's birth card after sunrise and is one card further along
    the retreating walk before it. Anchoring the walk on ``birth`` for a
    before-sunrise native therefore reads the wrong Year Card at every age.

    This returns the nearby day whose ``day_card`` equals the chart's own
    ``birth_card``, so ``year_card(anchor, 0) == birth_card`` structurally for
    every birth hour. The shift is zero after sunrise and one day earlier before
    it (measured, Alain Delon: birth minus one day, 11 of 11 ages against Kala).
    The direction is TAKEN from the data, not assumed: the earlier days are
    tried first because sunrise only ever moves the card earlier, and if nothing
    in the small window matches, the pure-calendar ``birth`` stands — never
    worse than the pre-WI-6 behaviour.
    """
    if not birth_card or day_card(birth) == birth_card:
        return birth
    for delta in (-1, -2, 1, 2):
        candidate = birth + timedelta(days=delta)
        if day_card(candidate) == birth_card:
            return candidate
    return birth


def birthday_for_age(birth: date, age: int) -> date:
    """The calendar birthday on which the Age-``age`` year opens.

    A 29 February birth has no birthday in three years out of four. Those charts
    take 1 March, matching the engine's own February handling and keeping the
    year a real 364 card days. (The alternative, 28 February, would put the
    birthday one day before the anniversary in the very years the question
    arises.)
    """
    if age < 0:
        raise ValueError("age must not be negative")
    year = birth.year + age
    try:
        return birth.replace(year=year)
    except ValueError:                       # 29 February in a non-leap year
        return date(year, 3, 1)


def quadration_periods(birth: date, age: int) -> list:
    """The seven periods of the Age-``age`` Quadration.

    Args:
        birth: the CALENDAR date of birth. Not the solar-return instant: the
            anchor is the birthday, decisively. Lorris's 1993 solar return falls
            on 21 February 22:05 while the Age 2 screen starts on 22 February,
            and across ages 0-7 the return instant drifts over two calendar
            dates while the screen never moves.
        age: which year of life, 0-based. Age 0 is birth to the first birthday.

    Returns:
        Seven dicts, ``index`` 0..6, in TIME order (earliest first). Note that
        the view draws row 2 RIGHT TO LEFT with the Sun rightmost, so a renderer
        maps ``index`` to a column rather than iterating in place.

        Each dict carries ``index``, ``start`` and ``end`` (``date``, end
        exclusive), ``card_days`` (always 52) and ``calendar_days`` (52 or 53).

    The seven month/day pairs are FIXED for a person and never move from one
    year of life to the next; only ``calendar_days`` changes, absorbing
    31 December every year and 29 February in a leap span. That is a
    consequence of the card-day rule rather than a rule of its own.
    """
    b0 = birthday_for_age(birth, age)
    next_b = birthday_for_age(birth, age + 1)

    bounds = [add_card_days(b0, CARD_DAYS_PER_PERIOD * k)
              for k in range(PERIODS_PER_YEAR)]
    bounds.append(next_b)

    return [{
        "index": k,
        "start": bounds[k],
        "end": bounds[k + 1],
        "card_days": card_days_between(bounds[k], bounds[k + 1]),
        "calendar_days": (bounds[k + 1] - bounds[k]).days,
    } for k in range(PERIODS_PER_YEAR)]
