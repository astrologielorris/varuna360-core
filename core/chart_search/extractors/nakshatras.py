# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Nakshatras: nakshatra with its pada as q1 (domain Positions, build step 1; D2).

The pada is a qualifier of the nakshatra row, not a property of its own, so
"any planet in Bharani pada 2" cannot match Moon in Bharani plus Mars in some
pada 2 (filter-redesign.md §1).

A separate extractor from ``positions`` because it reads different fields
(never the mode): switching Aditya <-> Tropical recomputes nothing here. It
reads the house system for cusps 2-12 only; their ecliptic longitudes are the
same in every mode, Whole Sign included (the tropical chart's cusps).

One function, ``f(tropical_long, jd, ayanamsa_id)``: the ayanamsa id names
the division (``system.EQUATORIAL_NAKSHATRA_IDS``, ``ECLIPTIC_GC_MID_MULA_ID``),
so there is no coordinates field. Delegating, copying neither: for an
equatorial id the Vimshottari Moon seed's libaditya path (planets by their
right ascension); for every other id the F2 wheel's
``core.vimshottari_dasha.get_nakshatra_for_longitude`` (equal ecliptic
nakshatras), whose 98 branch is the ecliptic GC mid-Mula division. Pada is the
nakshatra pada, not the arudha pada.

Both paths take tropical longitudes, so the chart is built tropical (the F2
wheel's ``as_tropical_chart``), with the ``NEUTRAL`` ayanamsa on the ecliptic
path: the wheel applies the ayanamsa itself. The Ascendant is the true
Ascendant (``chart_helpers``), not ``cusps[1]``, as the wheel reads it; cusps
2-12 are ``cusps[n]`` as the wheel's ``get_house_cusp_nakshatras`` reads them
(on the equatorial path, libaditya's ``Cusp.nakshatra()``, as for the Ascendant).
"""

from __future__ import annotations

from AI_tools.AI_main_function.nakshatra import (
    get_planet_nakshatra,
    nakshatra_degrees_and_pada,
)
from core.chart_helpers import get_planet_decimal_degrees, has_planet
from core.chart_search.errors import InvariantError
from core.chart_search.extractors.base import Charts, Extractor, LibChart, Row
from core.chart_search.extractors.subjects import BODIES, HOUSE_CUSPS, LAGNA
from core.chart_search.sources import Moment
from core.chart_search.system import (
    ECLIPTIC_GC_MID_MULA_ID,
    EQUATORIAL_DHRUVA_ID,
    EQUATORIAL_NAKSHATRA_IDS,
    NEUTRAL,
    Field,
    Mode,
    Projection,
)
from core.chart_search.taxonomy import Codec, PropertySpec, Qualifier, ValueKind

#: Nakshatra pada qualifier values (q1), not the arudha pada.
PADAS: tuple[str, ...] = ("1", "2", "3", "4")
SUBJECTS: tuple[str, ...] = (*BODIES, *HOUSE_CUSPS)
#: Cusp subject -> cusp number (``cusps[n]``).
_CUSP_NUMBERS = {name: number for number, name in enumerate(HOUSE_CUSPS, start=2)}
#: Search id -> the id ``get_nakshatra_for_longitude`` computes its division with.
_ECLIPTIC_FUNCTION_IDS = {ECLIPTIC_GC_MID_MULA_ID: EQUATORIAL_DHRUVA_ID}

PROPERTIES = (
    PropertySpec(
        "nakshatra",
        SUBJECTS,
        ValueKind.ORDINAL,
        tuple(range(1, 28)),
        Codec.NAKSHATRA,
        qualifiers=(Qualifier("pada", PADAS),),
    ),
)


def _require(chart: LibChart, name: str) -> None:
    # chart_helpers answers 0.0 for a missing body; a row must never come of it.
    if not has_planet(chart, name):
        raise InvariantError(f"invariant: the chart has a {name}")


def _ecliptic(
    tropical: LibChart, jd_ut: float, ayanamsa_id: int, name: str
) -> tuple[int, int]:
    """(index 0-26, pada) as the F2 wheel computes them (``get_all_nakshatras``,
    ``get_house_cusp_nakshatras``)."""
    if name in _CUSP_NUMBERS:
        longitude = float(
            tropical.rashi().cusps()[_CUSP_NUMBERS[name]].ecliptic_longitude()
        )
    else:
        _require(tropical, name)
        longitude = get_planet_decimal_degrees(tropical, name)
    found = get_planet_nakshatra(
        longitude, jd_ut, _ECLIPTIC_FUNCTION_IDS.get(ayanamsa_id, ayanamsa_id)
    )
    return int(found["index"]), int(found["pada"])


def _equatorial(tropical: LibChart, name: str) -> tuple[int, int]:
    """(index 0-26, pada) from libaditya's ``Nakshatra``, as the Vimshottari
    Moon seed reads it (``dasha_moon_seed``)."""
    rashi = tropical.rashi()
    if name == LAGNA:
        body = rashi.cusps().ascendant()
    elif name in _CUSP_NUMBERS:
        body = rashi.cusps()[_CUSP_NUMBERS[name]]
    else:
        _require(tropical, name)
        body = rashi.planets()[name]
    nakshatra = body.nakshatra()
    index = int(nakshatra.index())
    _degrees, pada = nakshatra_degrees_and_pada(
        nakshatra.ashvini_longitude(), index, nakshatra.naksize()
    )
    return index, int(pada)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    ayanamsa_id = int(projection.value(Field.AYANAMSA_ID.value))
    house_system = str(projection.value(Field.HOUSE_SYSTEM.value))
    if ayanamsa_id in EQUATORIAL_NAKSHATRA_IDS:
        # libaditya reads the ayanamsa from the chart's context
        tropical = charts.chart(
            mode=Mode.TROPICAL_CLASSIC.value,
            ayanamsa_id=ayanamsa_id,
            house_system=house_system,
        )
        found = {name: _equatorial(tropical, name) for name in SUBJECTS}
    else:
        tropical = charts.chart(
            mode=Mode.TROPICAL_CLASSIC.value,
            ayanamsa_id=int(NEUTRAL[Field.AYANAMSA_ID]),
            house_system=house_system,
        )
        found = {
            name: _ecliptic(tropical, moment.jd_ut, ayanamsa_id, name)
            for name in SUBJECTS
        }
    return tuple(
        Row(name, "nakshatra", index + 1, str(pada))
        for name, (index, pada) in found.items()
    )


EXTRACTOR = Extractor(
    id="nakshatras",
    label="Nakshatras",
    version=3,
    domain="Positions",
    reads=frozenset({Field.AYANAMSA_ID, Field.HOUSE_SYSTEM}),
    normalisers=(),
    properties=PROPERTIES,
    extract=extract,
)
