# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Human Design (domain Human Design, build step 3).

Reference: ``core.hd_model.build_hd_model(context, frame)``, the dict the HD
page and ``show_human_design`` read, with the search system's ``hd_frame``
(the HD page's ``hd_frame_for(mode, level)`` when following the app).
One extractor, not a personality/design split: the reference always builds
both sides (Bodygraph), so a split would bypass it to save nothing.

Rows: per side and planet, ``gate`` (q1 = side, q2 = line), so a gate and a
line always describe one activation (filter-redesign.md §4); chart-level
``channel`` (one row per defined channel, ``"lo-hi"``) and ``center`` (one row
per center, q2 = ``defined`` / ``undefined``, so "undefined Sacral" needs no
NOT), both with q1 = ``both`` (the whole chart) / ``personality`` /
``design``, the bodygraph's P/D/Both filter: on one side a channel is defined
when both its gates are on that side, and the centres are ``hd_traits`` over
that side's gates. Then ``type``, ``authority``, ``definition``, ``profile``
and ``incarnation_cross`` (its label), whole chart only: Human Design defines
no per-side type, authority or definition.
"""

from __future__ import annotations

from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import CHART
from core.chart_search.sources import Moment
from core.chart_search.system import (
    HD_FRAME,
    Field,
    Projection,
    collapse_hd_frame,
    engine_ayanamsa_id,
)
from core.chart_search.taxonomy import Codec, PropertySpec, Qualifier, ValueKind
from core.hd_model import (
    AUTHORITIES,
    CENTER_ORDER,
    DEFINITIONS,
    HD_TYPES,
    PLANET_ORDER,
    PROFILES,
    build_hd_model,
    hd_context_from_birth,
    hd_traits,
    incarnation_crosses,
)
from libaditya.hd.constants import channels as _ENGINE_CHANNELS

#: The 13 activating bodies, libaditya identity names.
HD_BODIES: tuple[str, ...] = tuple(engine for engine, _key in PLANET_ORDER)
_BODY_OF_KEY = {key: engine for engine, key in PLANET_ORDER}
SIDES = ("personality", "design")
SIDE = Qualifier("side", SIDES)
LINE = Qualifier("line", tuple(str(n) for n in range(1, 7)))
#: The whole chart, then each side. Absent means the whole chart, not any
#: side: a centre undefined on one side may be defined in the chart. Nor is
#: ``side=*`` accepted, for the same reason.
WHOLE = "both"
CHART_SIDE = Qualifier("side", (WHOLE, *SIDES), default=WHOLE, allows_any=False)
CENTER_STATE = Qualifier("state", ("defined", "undefined"))

_CHANNEL_GATES: tuple[tuple[int, int], ...] = tuple(sorted(_ENGINE_CHANNELS))
#: The 36 channels, keyed as ``build_hd_model`` keys them (``"20-34"``).
CHANNELS: tuple[str, ...] = tuple(f"{lo}-{hi}" for lo, hi in _CHANNEL_GATES)
TYPES: tuple[str, ...] = HD_TYPES
#: The named crosses, ``build_hd_model``'s ``incarnation_cross["label"]``.
CROSSES: tuple[str, ...] = incarnation_crosses()

PROPERTIES = (
    PropertySpec(
        "gate",
        HD_BODIES,
        ValueKind.ORDINAL,
        tuple(range(1, 65)),
        Codec.NUMBER,
        qualifiers=(SIDE, LINE),
    ),
    PropertySpec(
        "channel",
        (CHART,),
        ValueKind.CODE,
        CHANNELS,
        Codec.HD,
        qualifiers=(CHART_SIDE,),
        multi=True,
    ),
    PropertySpec(
        "center",
        (CHART,),
        ValueKind.CODE,
        tuple(CENTER_ORDER),
        Codec.HD,
        qualifiers=(CHART_SIDE, CENTER_STATE),
        multi=True,
    ),
    PropertySpec("hd_type", (CHART,), ValueKind.CODE, TYPES, Codec.HD),
    PropertySpec("authority", (CHART,), ValueKind.CODE, AUTHORITIES, Codec.HD),
    PropertySpec("definition", (CHART,), ValueKind.CODE, DEFINITIONS, Codec.HD),
    PropertySpec("profile", (CHART,), ValueKind.CODE, PROFILES, Codec.HD),
    PropertySpec("incarnation_cross", (CHART,), ValueKind.CODE, CROSSES, Codec.CROSS),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    """The HD page's model for this moment. Builds its own context, as the
    ``show_human_design`` CLI does; ``charts`` is unused (the model builds
    both sides itself). The ayanamsa only reaches the engine in the sidereal
    frame; elsewhere ``build_hd_model`` makes the context tropical."""
    frame = str(projection.value(HD_FRAME))
    context = hd_context_from_birth(
        jd=moment.jd_ut,
        lat=moment.lat,
        lon=moment.lon,
        utcoffset=moment.utc_offset_hours,
        ayanamsa=engine_ayanamsa_id(
            int(projection.value_or_neutral(Field.AYANAMSA_ID))
        ),
    )
    model = build_hd_model(context, frame)
    activating = {
        side: [a for a in model["activations"][side] if a["activates"]]
        for side in SIDES
    }
    rows = [
        Row(_BODY_OF_KEY[a["planet"]], "gate", a["gate"], side, str(a["line"]))
        for side in SIDES
        for a in activating[side]
    ]
    gates = {s: {a["gate"] for a in activating[s]} for s in SIDES}
    # The whole chart is the union, as build_hd_model derives it.
    gates = {WHOLE: gates["personality"] | gates["design"], **gates}
    for side, on in gates.items():
        centers = hd_traits(on)["centers"]
        rows += [
            Row(CHART, "channel", f"{lo}-{hi}", side)
            for lo, hi in _CHANNEL_GATES
            if lo in on and hi in on
        ]
        rows += [
            Row(CHART, "center", c, side, "defined" if centers[c] else "undefined")
            for c in CENTER_ORDER
        ]
    rows += [
        Row(CHART, "hd_type", model["type"]),
        Row(CHART, "authority", model["authority"]),
        Row(CHART, "definition", model["definition"]),
        Row(CHART, "profile", model["profile"]),
        Row(CHART, "incarnation_cross", model["incarnation_cross"]["label"]),
    ]
    return tuple(rows)


EXTRACTOR = Extractor(
    id="human_design",
    label="Human Design",
    version=2,
    domain="Human Design",
    reads=frozenset({Field.HD_FRAME, Field.AYANAMSA_ID}),
    normalisers=(collapse_hd_frame,),
    properties=PROPERTIES,
    extract=extract,
)
