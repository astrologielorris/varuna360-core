"""The anniversary chart behind an Age-N Quadration spread.

SPEC-COT-004 §3.3 (INV-5) and §4.2(a). The occupants and cusps of an Age-N
spread come from a chart cast for the CALENDAR BIRTHDAY of age N, at the BIRTH
TIME and BIRTH PLACE:

> "The positions of the planets are calculated each year for the individual's
>  birthday, birth place and birth time and plotted into the card spread just as
>  is done for the Life Spread." -- Time and the Little Book

This is emphatically **NOT a solar return** (§3.3 is the whole proof: at age 2 a
solar return puts the Ascendant in the Mars card and the MC in the Sun card,
while the birthday chart places them on the Mercury and Saturn cards).
And it is NOT ``birth_jd + 365.2422 * age`` in Julian-day space (§4.2(a)) -- that
reintroduces a drift the calendar screen does not have. The year is added on the
LOCAL CIVIL DATE, and the chart is then built at the birth clock time on that
date.

**Realised via the SPEC-COT-006 context-replace pattern**, not the standalone
``build_chart_from_params`` signature §4.2(a) first sketched. Replacing only the
``timeJD`` on the natal context keeps the mode, ayanamsa, house system, location
and sign labelling byte-identical to the natal chart -- which is exactly "same
place, same settings, a different time" -- and avoids reverse-mapping the mode
out of the baked Circle/sysflg. ``_progressed_chart`` (SPEC-COT-006) proved the
pattern for the progression tier; this is its calendar-anchored twin.

Verified: Lorris age 2 reproduces the §3.3 occupancy 13 of 13,
Ascendant in the Mercury card and MC in the Saturn card, the solar-return
regression fence.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from core.cot_year_periods import birthday_for_age
from core.time_utils import julday


def natal_local_birth_date(chart) -> date:
    """The chart's LOCAL calendar birth date.

    ``usr*`` accessors, which answer in the local frame -- the same date the
    Year Card walk and ``birthday_for_age`` count from.

    ``datetime.date`` rejects year 0 and negative years, so a BCE natal chart
    raises here. That is caught upstream by the broad graft ``except`` and the
    spread falls back to faces-only (``occupants_pending``) -- see
    :func:`anniversary_chart`. Age-N occupants for BCE charts are a known gap,
    not a regression: the behaviour for those charts is unchanged.
    """
    jd = chart.context.timeJD
    return date(int(jd.usryear()), int(jd.usrmonth()), int(jd.usrday()))


def _anniversary_ut_jd(anniversary: date, ut_hour: float) -> float:
    """Julian day of the anniversary date at Universal Time ``ut_hour``.

    Through :func:`core.time_utils.julday`, which auto-selects the calendar
    flag: a birthday BEFORE the 1582 Gregorian reform is named in the Julian
    calendar, the same convention the rest of the engine and ``JulianDay``
    itself use (``julian_day.py`` passes ``_cal_flag`` to every ``swe.julday``).
    A bare ``swe.julday`` defaults to Gregorian and is ~10 days wrong for a 1500
    chart, ~8 days around 1400 -- the drift grows with age of the era.
    """
    return julday(anniversary.year, anniversary.month, anniversary.day, ut_hour)


def anniversary_chart(chart, age: int):
    """The natal chart re-cast on the calendar birthday ``age`` years later.

    Same local clock time, same place, same mode / ayanamsa / house system. The
    year is added on the LOCAL CIVIL DATE (``birthday_for_age``), never by adding
    days to the Julian day, and the chart is built once with no return search.

    **Age 0 returns the natal chart unchanged**, seat for seat: the birthday of
    age 0 IS the birth date, so its occupancy and cusps equal the natal spread's
    to the body while the faces differ. That is the anchor every wrong offset
    moves off (the COT-006 W-16 analogue), and it is a real identity, not a
    special case bolted on.

    **The UTC offset is the natal chart's own, and this has a real limitation.**
    An anniversary falls on the same calendar day as the birth (22 February stays
    22 February), so it usually sits in the same DST season and carries the same
    offset. But the chart carries a NUMERIC offset, not an IANA zone name, so the
    offset that actually applied on the anniversary date cannot be recomputed here
    at all. Reusing the natal offset is exact whenever the birthday sits clear of
    its zone's DST transition, and off by the DST hour when the birthday falls
    inside the ~week-wide transition window AND the anniversary lands on the other
    side of it -- because the transition DATE drifts year to year even under an
    unchanged rule (Europe/Paris 2008-03-29 was +1, 2009-03-29 was +2). A one-hour
    error can move the Ascendant across a card boundary, so this is not cosmetic;
    it is simply unfixable without the zone, which this representation does not
    carry. SPEC-COT-004 §7.2 tracks it. Lorris's corpus (CET, birthdays clear of
    the March/October window) cannot see it, and the 13/13 oracle was
    measured with offset reuse.
    """
    if age < 0:
        raise ValueError(f"age must not be negative: {age!r}")

    jd = chart.context.timeJD
    if age == 0:
        return chart

    birth = natal_local_birth_date(chart)
    anniversary = birthday_for_age(birth, age)

    # Local decimal birth hour minus the offset gives Universal Time. A UT that
    # falls outside 0..24 needs no date fix: swe.julday adds ``hour / 24`` to the
    # day's noon-anchored count, so a negative or >24 hour rolls the Julian day
    # across midnight on its own, continuously.
    offset = jd.utcoffset
    ut_hour = jd.usrhour() - offset
    anniversary_jd = _anniversary_ut_jd(anniversary, ut_hour)

    moved = type(jd)(jd=anniversary_jd, utcoffset=offset, timezone=jd.timezone())
    return type(chart)(context=replace(chart.context, timeJD=moved))
