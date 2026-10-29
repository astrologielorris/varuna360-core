# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Subject names shared by several extractors: libaditya's identity names.
Display names come from ``core.aditya_mode.get_planet_display_name``."""

from __future__ import annotations

from collections.abc import Mapping

GRAHAS: tuple[str, ...] = (
    "Sun",
    "Moon",
    "Mars",
    "Mercury",
    "Jupiter",
    "Venus",
    "Saturn",
    "Rahu",
    "Ketu",
)
#: libaditya.calc.avasthas.KARAKAS: the planets lajjitaadi is computed for.
KARAKAS: tuple[str, ...] = GRAHAS[:7]
OUTER: tuple[str, ...] = ("Uranus", "Neptune", "Pluto")
LAGNA = "Ascendant"  # aliases Asc, Lagna (taxonomy.parse_subject)
#: Positions and Nakshatras: every body the main chart shows, outer planets
#: always stored (``show_outer_planets`` is display only).
BODIES: tuple[str, ...] = (LAGNA, *GRAHAS, *OUTER)
#: The bodies that sit in a house: the Ascendant is cusp 1, what houses are
#: counted from, so it is a value of the house properties, never a subject
#: (houses.md D25).
HOUSED: tuple[str, ...] = (*GRAHAS, *OUTER)
#: The house cusps after the first, as libaditya names them (``Cusp.identity()``):
#: "Cusp 2" ... "Cusp 12". Cusp 1 is the Ascendant (``LAGNA``), its identity
#: here; aliases ``cusp1`` ... ``cusp12`` (taxonomy.parse_subject).
HOUSE_CUSPS: tuple[str, ...] = tuple(f"Cusp {n}" for n in range(2, 13))
#: Every cusp in house order: ``CUSPS[n - 1]`` is cusp ``n``.
CUSPS: tuple[str, ...] = (LAGNA, *HOUSE_CUSPS)
#: The subject of chart-level properties (HD type, CoT birth card).
CHART = "chart"
#: Human Design's extra body (the Sun's opposite).
EARTH = "Earth"

#: Subject groups a filter may name instead of one subject (``subject IN``);
#: ``search.resolve`` narrows a group to the property's own subjects.
SUBJECT_GROUPS: Mapping[str, tuple[str, ...]] = {
    "planets": (*GRAHAS, *OUTER, EARTH),
    "cusps": CUSPS,
}
