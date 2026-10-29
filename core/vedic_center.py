# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Vedic aspects drawn in the South Indian center: the Qt-free model (SPEC-VAC-001 §3.3).

Data in, geometry out: ``karakas_aspects.vedic_full_model(chart)`` gathers the records of
``calculate_all_aspects(chart)["aspects"]`` and the pairs of ``karakas_aspects.yuti_pairs``
(the Aspects V matrix's own data, INV-4), so this module imports no engine; the geometry is
``core.center_geometry``'s. A cast is a direction and a strength only (INV-11): ``aspect_type``
only names the house of a special aspect (D-8: the engine's ``is_special``).
``build_full_model`` (expensive) is cached per chart by the caller; ``select`` applies the
rail and the two key sets and places the lenses (cheap); ``tour_steps`` is the tour order.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from core import center_geometry as _geometry
from core.capabilities.karakas_aspects import COL_PLANETS, ROW_PLANETS, STRONG_VIRUPAS
from core.center_geometry import SCENE_CENTER, STUD_R, TRACK_R, Body, Curve, Point, ray

# --- bodies (§3.2): the matrix column order is the placement priority -----------------
BODY_ORDER: Tuple[str, ...] = tuple(COL_PLANETS)
CASTERS: Tuple[str, ...] = tuple(ROW_PLANETS)            # only the 7 planets cast
NODES: FrozenSet[str] = frozenset(BODY_ORDER) - frozenset(CASTERS)   # painted pewter
CODE_OF: Dict[str, str] = {name: name[:2].upper() for name in BODY_ORDER}
BODY_OF_CODE: Dict[str, str] = {code: name for name, code in CODE_OF.items()}

# --- §3.3 keep-right curves ----------------------------------------------------------
KEEP_RIGHT = 0.10               # control point offset, fraction of the chord
CASTER_END = 26.0               # the ray leaves the caster stud this far from its centre
RECEIVER_END = 33.0             # the cone tip stops this far from the receiver centre
COINCIDENT_REACH = 60.0         # control distance when the two studs coincide

# --- §3.3 lenses -----------------------------------------------------------------------
LENS_BASE = 6.0
LENS_PER_VIRUPA = 0.2
LENS_GAP = 4.0
LENS_TRIES = (.72, .68, .76, .64, .80, .60, .84, .56)

VEDIC = "vedic"                 # center drawing kind (SPEC-VAC-001 §3.1)
_PLANET_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


# ====================================================================== model
@dataclass(frozen=True)
class Cast:
    caster: str
    receiver: str
    virupas: float
    special: Optional[str]      # house of a special aspect ("3rd house") or None (D-8)
    back: Optional[float]       # receiver's virupas on the caster; None for a node
    curve: Curve                # quadratic A, Q, B between the two studs (§3.3)

    @property
    def strong(self) -> bool:
        return self.virupas >= STRONG_VIRUPAS

    @property
    def lens_r(self) -> float:
        return lens_radius(self.virupas)

    @property
    def key(self) -> Tuple[str, str, str]:
        """Typed tour key (§4.6): ordered, SA -> JU and JU -> SA differ."""
        return ("cast", self.caster, self.receiver)

    def touches(self, casters: FrozenSet[str], receivers: FrozenSet[str]) -> bool:
        return self.caster in casters or self.receiver in receivers


@dataclass(frozen=True)
class Yuti:
    a: str
    b: str
    sign_index: int

    @property
    def key(self) -> Tuple[str, FrozenSet[str]]:
        return ("yuti", frozenset((self.a, self.b)))


@dataclass(frozen=True)
class Lens:
    """A lens on its cast's curve, and the curve split there (de Casteljau)."""
    t: float
    center: Point
    r: float
    clearance: float                     # >= 0: clear of every placed lens and stud
    ray: Tuple[Point, Point, Point]      # A .. lens (quadratic)
    cone: Tuple[Point, Point, Point]     # lens .. B (quadratic), the tip at the receiver


@dataclass(frozen=True)
class VedicFullModel:
    bodies: Dict[str, Body]
    casts: Tuple[Cast, ...]              # every cast, strongest first
    yutis: Tuple[Yuti, ...]              # matrix order

    @property
    def total(self) -> int:
        return len(self.casts)


@dataclass(frozen=True)
class VedicModel:
    full: VedicFullModel
    drawn_casts: Tuple[Cast, ...]        # strongest first
    drawn_yutis: Tuple[Yuti, ...]
    lenses: Dict[Tuple[str, str], Lens]
    lit_casters: FrozenSet[str]
    lit_receivers: FrozenSet[str]
    faded: FrozenSet[str]
    min_virupas: int

    @property
    def shown(self) -> int:
        return len(self.drawn_casts)

    @property
    def total(self) -> int:
        return self.full.total

    @property
    def min_clearance(self) -> float:
        """The smallest lens clearance (inf without lenses): < 0 means an overlap."""
        return min((lens.clearance for lens in self.lenses.values()), default=math.inf)


# ============================================================ values and curves
def lens_radius(virupas: float) -> float:
    return LENS_BASE + LENS_PER_VIRUPA * virupas


def special_label(record: Mapping) -> Optional[str]:
    """The house of a special aspect, from the engine's flag (D-8): ``aspect_type``
    without the planet ("3rd house (Saturn)" -> "3rd house"); None otherwise."""
    if not record.get("is_special"):
        return None
    return _PLANET_SUFFIX.sub("", str(record.get("aspect_type", ""))) or None


def _unit(dx: float, dy: float) -> Point:
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (0.0, 0.0)


def cast_curve(caster: Body, receiver: Body) -> Curve:
    """Keep-right curve from the caster stud to the receiver stud (§3.3, D-2)."""
    sc, sr = caster.stud, receiver.stud
    dx, dy = sr[0] - sc[0], sr[1] - sc[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-6:
        ux, uy = ray(caster.theta)
        e = (-uy, ux)                    # the caster's ray turned 90 deg clockwise
        q = (sc[0] + COINCIDENT_REACH * e[0], sc[1] + COINCIDENT_REACH * e[1])
        a = (sc[0] + CASTER_END * e[0], sc[1] + CASTER_END * e[1])
        b = (sr[0] + RECEIVER_END * e[0], sr[1] + RECEIVER_END * e[1])
        return Curve("q", a, b, q, None, e, 0.0)
    n = (-dy / chord, dx / chord)        # right of travel on screen (scene y down)
    q = ((sc[0] + sr[0]) / 2 + KEEP_RIGHT * chord * n[0],
         (sc[1] + sr[1]) / 2 + KEEP_RIGHT * chord * n[1])
    ua, ub = _unit(q[0] - sc[0], q[1] - sc[1]), _unit(q[0] - sr[0], q[1] - sr[1])
    a = (sc[0] + CASTER_END * ua[0], sc[1] + CASTER_END * ua[1])
    b = (sr[0] + RECEIVER_END * ub[0], sr[1] + RECEIVER_END * ub[1])
    return Curve("q", a, b, q, None, n, chord)


def split_curve(curve: Curve, t: float) -> Tuple[Tuple[Point, Point, Point],
                                                 Tuple[Point, Point, Point]]:
    """De Casteljau split of the quadratic A-Q-B at ``t``: (A..M, M..B)."""
    a, q, b = curve.a, curve.c1, curve.b
    p01 = (a[0] + (q[0] - a[0]) * t, a[1] + (q[1] - a[1]) * t)
    p12 = (q[0] + (b[0] - q[0]) * t, q[1] + (b[1] - q[1]) * t)
    m = (p01[0] + (p12[0] - p01[0]) * t, p01[1] + (p12[1] - p01[1]) * t)
    return (a, p01, m), (m, p12, b)


# ================================================================ full model
def place_bodies(positions: Mapping[str, float]) -> Dict[str, Body]:
    """Exact points and studs of the 9 bodies, matrix order = priority (§3.2)."""
    return _geometry.place_bodies(positions, BODY_ORDER, NODES)


def _matrix_rank(cast: Cast) -> Tuple[float, int, int]:
    """Strongest first; ties by matrix row, then column (§3.3)."""
    return (-cast.virupas, CASTERS.index(cast.caster), BODY_ORDER.index(cast.receiver))


def _is_cast(caster: str, receiver: str, virupas: float, bodies: Mapping[str, Body],
             pairs: FrozenSet[FrozenSet[str]]) -> bool:
    """A planet's cast on another body, with virupas, not hidden by a Yuti (§3.3)."""
    if caster not in CASTERS or caster == receiver or virupas <= 0:
        return False
    return caster in bodies and receiver in bodies and frozenset((caster, receiver)) not in pairs


def _casts(bodies: Mapping[str, Body], records: Sequence[Mapping],
           pairs: FrozenSet[FrozenSet[str]]) -> Tuple[Cast, ...]:
    """Every record with virupas > 0 whose pair is not a Yuti, strongest first."""
    value = {(r.get("aspecting"), r.get("aspected")): float(r.get("virupas", 0.0))
             for r in records}
    out = []
    for rec in records:
        c, r = rec.get("aspecting"), rec.get("aspected")
        if not _is_cast(c, r, value[(c, r)], bodies, pairs):
            continue
        back = None if r in NODES else value.get((r, c), 0.0)
        out.append(Cast(c, r, value[(c, r)], special_label(rec), back,
                        cast_curve(bodies[c], bodies[r])))
    out.sort(key=_matrix_rank)
    return tuple(out)


def _yutis(bodies: Mapping[str, Body], pairs: FrozenSet[FrozenSet[str]]) -> Tuple[Yuti, ...]:
    """One Yuti per pair, bodies in priority order, matrix order (§3.3)."""
    order = {n: i for i, n in enumerate(BODY_ORDER)}
    out = []
    for pair in pairs:
        a, b = sorted(pair, key=order.get)
        out.append(Yuti(a, b, int(math.floor(bodies[a].longitude / 30.0)) % 12))
    out.sort(key=lambda y: (order[y.a], order[y.b]))
    return tuple(out)


def build_full_model(positions: Mapping[str, float], records: Sequence[Mapping],
                     yutis: Iterable[Tuple[str, str]]) -> VedicFullModel:
    """Bodies, every cast (virupas > 0, not a Yuti pair) and every Yuti (§3.3)."""
    bodies = place_bodies(positions)
    pairs = frozenset(frozenset(p) for p in yutis if all(n in bodies for n in p))
    return VedicFullModel(bodies, _casts(bodies, records, pairs), _yutis(bodies, pairs))


# ================================================================== lenses
def _clearance(p: Point, r: float, placed: Sequence[Tuple[Point, float]],
               studs: Sequence[Point]) -> float:
    clear = math.inf
    for q, rq in placed:
        clear = min(clear, math.hypot(q[0] - p[0], q[1] - p[1]) - rq - r - LENS_GAP)
    for q in studs:
        clear = min(clear, math.hypot(q[0] - p[0], q[1] - p[1]) - STUD_R - r - LENS_GAP)
    return clear


def place_lenses(drawn: Sequence[Cast], bodies: Mapping[str, Body]) -> Dict[Tuple[str, str], Lens]:
    """One lens per drawn cast, strongest first, slid along its own curve (§3.3): the first try
    clear of every lens and stud, else the clearest (ties: earliest; may overlap)."""
    studs = [b.stud for b in bodies.values()]
    placed: List[Tuple[Point, float]] = []
    out = {}
    for cast in drawn:
        r = cast.lens_r
        best_t, best_p, best_clear = None, None, -math.inf
        for t in LENS_TRIES:
            p = cast.curve.at(t)
            clear = _clearance(p, r, placed, studs)
            if clear > best_clear:
                best_t, best_p, best_clear = t, p, clear
            if clear >= 0:
                break
        ray_part, cone_part = split_curve(cast.curve, best_t)
        placed.append((best_p, r))
        # The lens sits on the split point itself, where the ray ends and the cone starts.
        out[(cast.caster, cast.receiver)] = Lens(best_t, ray_part[2], r, best_clear,
                                                 ray_part, cone_part)
    return out


# ================================================================== filters
def _faded(full: VedicFullModel, lit: FrozenSet[str], drawn: Sequence[Cast],
           yutis: Sequence[Yuti]) -> FrozenSet[str]:
    """While a key is lit, the studs no drawn cast or Yuti uses (lit ones excepted)."""
    if not lit:
        return frozenset()
    used = set(lit)
    for c in drawn:
        used.update((c.caster, c.receiver))
    for y in yutis:
        used.update((y.a, y.b))
    return frozenset(n for n in full.bodies if n not in used)


def select(full: VedicFullModel, min_virupas: int = 0, lit_casters: Iterable[str] = (),
           lit_receivers: Iterable[str] = ()) -> VedicModel:
    """The rail and the keys by role (§3.5): a cast passing the rail is drawn when no
    key is lit, or when its caster is a lit caster OR its receiver a lit receiver.
    Yutis ignore the rail; with a key lit, a Yuti shows when either body is lit."""
    casters = frozenset(n for n in lit_casters if n in CASTERS and n in full.bodies)
    receivers = frozenset(n for n in lit_receivers if n in full.bodies)
    lit = casters | receivers
    drawn = tuple(c for c in full.casts if c.virupas >= min_virupas
                  and (not lit or c.touches(casters, receivers)))
    yutis = tuple(y for y in full.yutis if not lit or y.a in lit or y.b in lit)
    return VedicModel(full, drawn, yutis, place_lenses(drawn, full.bodies), casters,
                      receivers, _faded(full, lit, drawn, yutis), int(min_virupas))


def tour_steps(model: VedicModel) -> tuple:
    """The tour sequence of a drawn model (§4.6): casts strongest first, then Yutis."""
    return tuple(c.key for c in model.drawn_casts) + tuple(y.key for y in model.drawn_yutis)


def model_to_json(model: VedicModel) -> dict:
    """The model as plain data (``AI_aspects.py --center-geometry``, §4.7)."""
    def pt(p):
        return [round(p[0], 4), round(p[1], 4)]
    return {
        "center": pt(SCENE_CENTER), "track_r": TRACK_R, "stud_r": STUD_R,
        "bodies": {n: {"longitude": round(b.longitude, 4), "theta": round(b.theta, 4),
                       "track_r": round(b.track_r, 4), "exact": pt(b.exact),
                       "stud": pt(b.stud), "push_level": b.push_level, "pewter": b.pewter,
                       "cluster": list(b.cluster)} for n, b in model.full.bodies.items()},
        "casts": [{"caster": c.caster, "receiver": c.receiver, "virupas": c.virupas,
                   "special": c.special, "back": c.back,
                   "lens": pt(model.lenses[(c.caster, c.receiver)].center),
                   "lens_r": round(c.lens_r, 4)} for c in model.drawn_casts],
        "yutis": [{"a": y.a, "b": y.b, "sign": y.sign_index} for y in model.drawn_yutis],
        "lit_casters": sorted(model.lit_casters), "lit_receivers": sorted(model.lit_receivers),
        "faded": sorted(model.faded), "min_virupas": model.min_virupas,
        "shown": model.shown, "total": model.total,
    }


# ===================================================================== state
@dataclass(frozen=True)
class VedicCenterState:
    """What the Aspects V panel pushes into the main host (§3.1, §4.1)."""
    on: bool = False
    min_virupas: int = 0
    lit_casters: FrozenSet[str] = frozenset()
    lit_receivers: FrozenSet[str] = frozenset()


OFF_STATE = VedicCenterState()


def lit_codes(text: Optional[str], casters_only: bool = False) -> FrozenSet[str]:
    """Body names from comma separated codes (``SU,ke``; case-insensitive) for the
    CLIs (§4.7). Raises ValueError on an unknown code, and on a node when
    ``casters_only`` (the nodes receive only)."""
    out = set()
    valid = CASTERS if casters_only else BODY_ORDER
    codes = ", ".join(CODE_OF[n] for n in valid)
    for code in filter(None, (c.strip().upper() for c in (text or "").split(","))):
        name = BODY_OF_CODE.get(code)
        if name is None:
            raise ValueError(f"Unknown body code '{code}'. Valid codes: {codes}")
        if name not in valid:
            raise ValueError(f"'{code}' does not cast: the nodes receive only. "
                             f"Valid codes: {codes}")
        out.add(name)
    return frozenset(out)
