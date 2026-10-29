# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Cards of Truth (domain Cards of Truth, build step 4). D1 only.

Reference: ``core.cards_of_truth_data.assemble_spread(chart, order)``. Rows:
``birth_card`` (subject ``chart``), ``card`` per spread position (the card
face at that position) and ``in_card`` per body and per cusp (the card it
falls in, q1 the position that card holds: "Mars in the Sun card"). Faces and
the birth card come from the local birth date (hence ``utc_offset`` in the
moment key); placement reads the sign lords, hence the mode and (sidereal)
ayanamsa, and the house system for the cusps. ``CardsOfTruthUnavailable`` is a
recorded failure.

Bodies and cusps are filed under their sign lord, so only the seven
``CLASSICAL_LORDS`` positions hold any: the position follows from the sign
(Mars in the Sun card is Mars in Leo), offered because it is how CoT asks
(filter-redesign.md §3). Placements per varga are deferred.
"""

from __future__ import annotations

from core.cards_of_truth_data import (
    DECK_CODES,
    DEFAULT_ORDER,
    assemble_spread,
    planet_order,
)
from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import CHART, CUSPS
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, Qualifier, ValueKind

#: The engine's deck order (SPEC-COT-002 INV-1: never cards_constants.cards).
CARDS: tuple[str, ...] = DECK_CODES
#: libaditya.cards.cards_constants.planet_order: the same 14 positions in both orders.
POSITIONS: tuple[str, ...] = tuple(planet_order[DEFAULT_ORDER])
#: assemble_spread files these bodies (Earth and Chiron filtered out).
BODIES: tuple[str, ...] = (
    "Sun",
    "Moon",
    "Mars",
    "Mercury",
    "Jupiter",
    "Venus",
    "Saturn",
    "Rahu",
    "Ketu",
    "Uranus",
    "Neptune",
    "Pluto",
)


PROPERTIES = (
    PropertySpec("birth_card", (CHART,), ValueKind.CODE, CARDS, Codec.CARD),
    PropertySpec("card", POSITIONS, ValueKind.CODE, CARDS, Codec.CARD),
    PropertySpec(
        "in_card",
        (*BODIES, *CUSPS),
        ValueKind.CODE,
        CARDS,
        Codec.CARD,
        qualifiers=(Qualifier("position", POSITIONS),),
    ),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    """The Cards of Truth view's birth spread (natal D1) in the projection's
    order, its cusp gutters included (cusp 1 is the Ascendant, as in
    ``subjects.CUSPS``). ``CardsOfTruthUnavailable`` propagates for compute
    to record."""
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value(Field.HOUSE_SYSTEM.value)),
    )
    spread = assemble_spread(chart, str(projection.value(Field.COT_PLANET_ORDER.value)))
    rows = [Row(CHART, "birth_card", spread["birth_card"])]
    rows += [Row(card["position"], "card", card["code"]) for card in spread["cards"]]
    for card in spread["cards"]:
        rows += [
            Row(body["name"], "in_card", card["code"], card["position"])
            for body in card["bodies"]
        ]
        rows += [
            Row(CUSPS[number - 1], "in_card", card["code"], card["position"])
            for number in card["cusps"]
        ]
    return tuple(rows)


EXTRACTOR = Extractor(
    id="cards_of_truth",
    label="Cards of Truth",
    version=2,
    domain="Cards of Truth",
    reads=frozenset(
        {Field.MODE, Field.AYANAMSA_ID, Field.HOUSE_SYSTEM, Field.COT_PLANET_ORDER}
    ),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
