"""The BodyGraph layout: gate seats, centre outlines, channel curves.

Canvas coordinates only. No Qt, no theme, no chart -- the view scales this 560x960 box to
fit and asks a chart model which gates are lit; the shapes never change with either.

The tables come from ``hd_geometry_data``, which is generated from the mockups'
``_geometry_v4.js`` by ``tools/gen_hd_geometry.py``. Read the Gate Layout Canon
(SPEC-HD-001) before
changing any of it: every coordinate there was measured against five reference charts, and
several of the odder-looking ones (the re-seated spine anchors, the Will's three-gates-on-
one-edge, stem10's 30px bend) are deliberate and recorded.

Two shapes of path come out of here:

    ("cubic", [(p0, p1, p2, p3), ...])   the 30 ordinary channels
    ("poly",  [(x, y), ...])             the 5 braid tracks and the 6 braid composites

The braid must not be splined. Its polylines are the finished curve, and running them
back through the Catmull-Rom smoother reintroduces exactly the overshoot the geometric
construction removes.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from . import hd_curves
from .hd_curves import KIND_CUBIC, KIND_POLY, Cubic, Point
from .hd_geometry_data import (
    CANVAS,
    CENTER_FACES,
    CENTER_POLYGON,
    CENTER_SHAPE,
    CENTERS,
    CHANNEL_ENDS,
    CHANNEL_GATES,
    CHANNEL_HALVES,
    CHANNEL_KEYS,
    FAN_CENTRE,
    MIRROR_AXIS_X,
    GATE_ANCHOR,
    GATE_CENTER,
    GATE_LABEL,
    INTEG_JUNCTION,
    INTEG_KEYS,
    INTEG_ROUTE,
    PARALLEL_GROUPS,
    ROUTE_POLYLINE,
    STRAIGHT_KEYS,
    TRACK_NAMES,
    TRACK_POLYLINE,
    VIA_POINT,
)

__all__ = [
    "CANVAS", "CENTERS", "CENTER_FACES", "CENTER_POLYGON", "CENTER_SHAPE",
    "CHANNEL_ENDS", "CHANNEL_GATES", "CHANNEL_HALVES", "CHANNEL_KEYS", "FAN_CENTRE",
    "GATE_ANCHOR", "GATE_CENTER", "GATE_LABEL", "GATES",
    "INTEG_JUNCTION", "INTEG_KEYS", "INTEG_ROUTE", "MIRROR_AXIS_X", "MOTORS",
    "PARALLEL_GROUPS", "ROUTE_POLYLINE", "STRAIGHT_KEYS", "parallel_group_of",
    "TRACK_NAMES", "TRACK_POLYLINE", "VIA_POINT",
    "KIND_CUBIC", "KIND_POLY", "Cubic", "Point",
    "centre_of_gate", "centre_polygon", "channel_flat", "channel_halves",
    "channel_key", "channels_on_track", "gate_anchor", "gate_label",
    "gates_of_channel", "half_for_gate", "is_braid", "is_straight",
    "spine_lanes", "track_flat", "track_polyline", "track_traversal",
    "tracks_of_channel", "via_point",
]

#: The 64 gates, ascending. Iteration order matters for painting: pads are drawn in this
#: order so a chart always stacks its overlapping discs the same way.
GATES: tuple[int, ...] = tuple(sorted(GATE_CENTER))

#: The four motor centres. Not geometry, but every consumer of this module needs them and
#: they are a property of the layout's vocabulary rather than of any one chart.
MOTORS: frozenset[str] = frozenset({"sacral", "solar", "will", "root"})

#: The five spine trios and the lane x each must hold. Fifteen vertical lanes: a slot's x
#: on the upper centre's face must equal its x on the lower one. Seven of these were
#: slanted (worst 11px) before the rule existed, and nine anchors were re-seated to fix
#: it. A "deviation from the chord" check does not catch a slant -- a slanted straight
#: line is still perfectly straight -- so verticality is asserted separately.
SPINE_TRIOS: tuple[tuple[str, tuple[str, str, str], tuple[float, float, float]], ...] = (
    ("head to ajna", ("64-47", "61-24", "63-4"), (250.0, 280.0, 310.0)),
    ("ajna to throat", ("17-62", "43-23", "11-56"), (256.0, 280.0, 304.0)),
    ("throat to g", ("31-7", "8-1", "33-13"), (256.0, 280.0, 304.0)),
    ("g to sacral", ("15-5", "2-14", "46-29"), (256.0, 280.0, 304.0)),
    ("sacral to root", ("42-53", "3-60", "9-52"), (256.0, 280.0, 304.0)),
)

#: Bends tighter than 40px radius that the canon accepts by name. Both are braid feeders
#: whose turn cannot be spread further without the stem shadowing the rail or touching the
#: Spleen; they were measured, argued and signed off, not overlooked.
ACCEPTED_TIGHT_BENDS: dict[str, float] = {"stem10": 30.0, "stem34": 36.0}

_PAIR_TO_KEY: Mapping[frozenset[int], str] = MappingProxyType({
    frozenset(gates): key for key, gates in CHANNEL_GATES.items()
})
_TRACK_TO_CHANNELS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    name: tuple(k for k, route in INTEG_ROUTE.items() if name in route)
    for name in TRACK_NAMES
})

# The lookups above are built once at import. Handing out the underlying dictionaries as
# well would let a caller mutate a table and leave the two disagreeing -- a class of bug
# that shows up as one panel drawing a channel the rest of the view thinks is elsewhere.
# Read-only views cost nothing and make that impossible; the generated module keeps the
# real dictionaries for the generator and for mutation testing.
CENTER_FACES = MappingProxyType(dict(CENTER_FACES))
CENTER_POLYGON = MappingProxyType(dict(CENTER_POLYGON))
CENTER_SHAPE = MappingProxyType(dict(CENTER_SHAPE))
CHANNEL_ENDS = MappingProxyType(dict(CHANNEL_ENDS))
CHANNEL_GATES = MappingProxyType(dict(CHANNEL_GATES))
CHANNEL_HALVES = MappingProxyType(dict(CHANNEL_HALVES))
GATE_ANCHOR = MappingProxyType(dict(GATE_ANCHOR))
GATE_CENTER = MappingProxyType(dict(GATE_CENTER))
GATE_LABEL = MappingProxyType(dict(GATE_LABEL))
INTEG_JUNCTION = MappingProxyType(dict(INTEG_JUNCTION))
INTEG_ROUTE = MappingProxyType(dict(INTEG_ROUTE))
PARALLEL_GROUPS = MappingProxyType(dict(PARALLEL_GROUPS))

#: The same table read the other way: channel key -> the name of the parallel group it
#: belongs to. Members of a group are drawn as concentric arcs sharing a fan centre, so
#: "which group" is the answer to "why does this line bow the way it does".
_PARALLEL_OF = MappingProxyType(
    {key: name for name, keys in PARALLEL_GROUPS.items() for key in keys})
ROUTE_POLYLINE = MappingProxyType(dict(ROUTE_POLYLINE))
TRACK_POLYLINE = MappingProxyType(dict(TRACK_POLYLINE))
VIA_POINT = MappingProxyType(dict(VIA_POINT))


def _require_channel(key: str) -> str:
    """Reject anything that is not one of the 36 canonical channel keys.

    Returning a bland empty answer for an unknown key is the failure this prevents. The
    keys are not consistently low-gate-first, so ``"20-34"`` looks entirely reasonable and
    is not a key -- the channel is stored as ``"34-20"``. A caller that spelled one by hand
    would otherwise get ``()`` from ``tracks_of_channel`` and conclude, wrongly, that the
    channel is not part of the braid. Build keys with ``channel_key(a, b)``.
    """
    if key not in CHANNEL_HALVES:
        swapped = "-".join(reversed(key.split("-")))
        hint = f"; did you mean {swapped!r}?" if swapped in CHANNEL_HALVES else ""
        raise KeyError(f"{key!r} is not a channel key{hint}")
    return key


def _require_track(name: str) -> str:
    if name not in TRACK_POLYLINE:
        raise KeyError(f"{name!r} is not a braid track; expected one of {TRACK_NAMES}")
    return name


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def channel_key(gate_a: int, gate_b: int) -> str | None:
    """The pack's key for a gate pair, or None if the two gates share no channel.

    Keys are not consistently low-gate-first -- ``34-20`` is a key and ``20-34`` is not --
    so never format one by hand.
    """
    return _PAIR_TO_KEY.get(frozenset((gate_a, gate_b)))


def gates_of_channel(key: str) -> tuple[int, int]:
    """The two gates a channel joins, in the key's own order."""
    return CHANNEL_GATES[_require_channel(key)]


def centre_of_gate(gate: int) -> str:
    return GATE_CENTER[gate]


def centre_polygon(centre: str) -> tuple[Point, ...]:
    """The centre's outline as a closed polygon, squares expanded to four corners."""
    return CENTER_POLYGON[centre]


def gate_anchor(gate: int) -> Point:
    """The gate's seat on its centre's boundary, where its channels arrive."""
    return GATE_ANCHOR[gate]


def gate_label(gate: int) -> Point:
    """Where the gate's numeral is drawn: inside its centre, on the correct face."""
    return GATE_LABEL[gate]


def is_braid(key: str) -> bool:
    """True for the six integration channels, which share five physical tracks.

    A renderer must draw those five tracks once each and colour every track by its own
    gate's state. Looping the six channels instead is geometrically correct but paints
    the shared track six times, and then a Personality-20 that should stop at the junction
    runs the whole rail.
    """
    return _require_channel(key) in INTEG_KEYS


def is_straight(key: str) -> bool:
    """True where the channel is an exact chord between its two seats."""
    return _require_channel(key) in STRAIGHT_KEYS


def tracks_of_channel(key: str) -> tuple[str, ...]:
    """The braid tracks a braid channel travels. Empty for the 30 ordinary channels.

    These are track NAMES, not a traversal: the sequence carries no direction, and for a
    merge channel such as ``10-20`` both named stems point toward junction A, so
    concatenating them in this order gives a discontinuous path. Use
    ``track_traversal(key)`` when you need to walk the channel.
    """
    return INTEG_ROUTE.get(_require_channel(key), ())


def track_traversal(key: str) -> tuple[tuple[str, bool], ...]:
    """``((track, reversed), ...)`` walking a braid channel from its first gate to its second.

    ``reversed`` is True where the track must be traversed backwards to stay joined.
    Reading ``tracks_of_channel`` as if it were already a traversal is the mistake this
    exists to prevent: for a merge channel both named stems leave the same junction, so
    the stored order jumps across the canvas.

    The ORDER can also differ from ``INTEG_ROUTE``. ``34-20`` lists its tracks as stem20,
    trunk, stem34 -- which runs 20 to 34 -- while its stored centreline runs 34 to 20. The
    walk follows the centreline, so it returns those three tracks reversed and flipped.

    Empty for an ordinary channel, which is one curve and has no tracks.
    """
    names = tracks_of_channel(key)
    if not names:
        return ()

    # Orient the first track by whichever of its ends meets the second track, then chain.
    # Doing it from the channel's start gate instead is wrong for a merge channel, whose
    # first named stem need not touch that gate at all.
    first_pts = TRACK_POLYLINE[names[0]]
    second_pts = TRACK_POLYLINE[names[1]]
    ends = (second_pts[0], second_pts[-1])
    backwards = min(hypot(first_pts[0], e) for e in ends) < \
        min(hypot(first_pts[-1], e) for e in ends)

    walk: list[tuple[str, bool]] = [(names[0], backwards)]
    cursor = first_pts[0] if backwards else first_pts[-1]
    for name in names[1:]:
        points = TRACK_POLYLINE[name]
        backwards = hypot(points[-1], cursor) < hypot(points[0], cursor)
        walk.append((name, backwards))
        cursor = points[0] if backwards else points[-1]

    # The chain is joined but may run against the channel's own direction; turn it round.
    start_pts = TRACK_POLYLINE[walk[0][0]]
    head = start_pts[-1] if walk[0][1] else start_pts[0]
    if hypot(head, gate_anchor(CHANNEL_ENDS[key][0])) > 0.01:
        walk = [(name, not backwards) for name, backwards in reversed(walk)]
    return tuple(walk)


def hypot(a: Point, b: Point) -> float:
    """Distance between two points. Local so this module needs no math import elsewhere."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def channels_on_track(name: str) -> tuple[str, ...]:
    """Every braid channel routed over a track.

    The track is the pointer target, not the channel: six overlapping hit paths on shared
    track make "which channel is under the cursor" arbitrary. A track's tooltip therefore
    names all of these, and the six channels stay individually selectable from the channel
    list in the side column.
    """
    return _TRACK_TO_CHANNELS[_require_track(name)]


def via_point(key: str) -> Point:
    """The channel's route midpoint, where the small ringed via is drawn."""
    return VIA_POINT[_require_channel(key)]


def track_polyline(name: str) -> tuple[Point, ...]:
    """One braid track as its finished polyline."""
    return TRACK_POLYLINE[_require_track(name)]


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def channel_halves(key: str) -> tuple[str, Sequence, Sequence]:
    """``(kind, first_half, second_half)`` for a channel.

    The first half touches ``CHANNEL_ENDS[key][0]``, which is not always the key's first
    gate. Each half is an exact sub-curve of the parent, cut with de Casteljau, so a
    coloured half lies on its own tube instead of drifting off it.
    """
    return CHANNEL_HALVES[_require_channel(key)]


def half_for_gate(key: str, gate: int) -> tuple[str, Sequence]:
    """``(kind, path)`` for the half of ``key`` that reaches ``gate``.

    This is the unit of colour: each half takes the colour of its own gate's state, so a
    channel with one gate in Design and the other in Personality shows both.

    Which end is which comes from ``CHANNEL_ENDS``, never from the key. The composite for
    ``10-20`` runs 20 to 10, so keying off the name would paint its two halves swapped.
    """
    _require_channel(key)
    start, end = CHANNEL_ENDS[key]
    kind, first, second = CHANNEL_HALVES[key]
    if gate == start:
        return kind, first
    if gate == end:
        return kind, second
    raise KeyError(f"gate {gate} is not on channel {key}")


def channel_flat(key: str, spacing: float = 1.0) -> list[Point]:
    """The whole channel as a flattened polyline, for hit testing and for the probes.

    Built from CHANNEL_HALVES on both path kinds, never from ROUTE_POLYLINE. The halves
    are what a chart actually colours, so they are what any measurement must read: while
    this fell back to the parent route for braid channels, a braid half could be replaced
    by a line straight across the canvas and every probe still passed.

    Flattened from the shipped curve rather than read off the builder's control points.
    Builder-space curvature is optimistic -- it once reported 45.8px where the rendered
    path was 33px -- so anything that measures this geometry measures what ships.
    """
    _require_channel(key)
    kind, first, second = CHANNEL_HALVES[key]
    if kind == KIND_POLY:
        return hd_curves.resample(list(first) + list(second)[1:], spacing)
    return hd_curves.flatten_cubics(list(first) + list(second), spacing)


def track_flat(name: str, spacing: float = 1.0) -> list[Point]:
    """A braid track as a flattened polyline."""
    return hd_curves.resample(TRACK_POLYLINE[_require_track(name)], spacing)


def spine_lanes() -> Iterable[tuple[str, str, float]]:
    """``(trio, channel key, required lane x)`` for each of the fifteen spine lanes."""
    for trio, keys, xs in SPINE_TRIOS:
        for key, x in zip(keys, xs):
            yield trio, key, x


def parallel_group_of(key: str) -> str:
    """The parallel group ``key`` is drawn in, or ``""`` if it is not in one."""
    return _PARALLEL_OF.get(_require_channel(key), "")
