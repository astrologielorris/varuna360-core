# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Tajika aspects drawn in the South Indian center: the Qt-free model (SPEC-TJK-003).

The geometry (track, studs, precedence) is ``core.center_geometry``'s (SPEC-VAC-001
§4.0), re-exported here under its old names. Bundles, beads and filters: §3.4-§3.5.

``build_full_model`` is the expensive part and is cached per chart by the caller;
``select`` applies min_virupas and the lit set and places the beads (cheap).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.center_geometry import (  # noqa: F401  (re-exported: SPEC-VAC-001 §4.0)
    BOUNDARY_NAIL_R, EMPTY, FADED_OPACITY, FRAME_INSET, FRAME_NAIL_R, FRAME_RADIUS,
    PIN_R, R_MIN, SCENE_CENTER, STUD_GAP, STUD_R, STUD_STEP, TICK_IN, TICK_OUT, TRACK_N,
    TRACK_R, TRANSIT, VARGA, Body, Curve, Point, central_angle, point_on_ray, ray,
    separation, theta_of, track_radius)
from core import center_geometry as _geometry

# --- §3.4 bundles and beads --------------------------------------------------------
THREAD_WIDTH = 3.6
BOW = {"opposition": 0.0, "square": 0.09, "trine": 0.15, "sextile": 0.21}
LOOP_DEPTH = 190.0
LOOP_SPREAD = 50.0
CONJ_SPACING = 8.0
BEAD_R = 19.0
BEAD_GAP = 2 * BEAD_R + 6       # 44 between beads
BEAD_STUD_GAP = STUD_R + BEAD_R + 5   # 54 between a bead and a stud
BEAD_TRIES = (.5, .44, .56, .38, .62, .32, .68, .26, .74, .2, .8)
STRONG_VIRUPAS = 45.0

# Placement priority and the body set (TAJIKA_PLANETS order).
BODY_ORDER = ("Ascendant", "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus",
              "Saturn", "Uranus", "Neptune", "Pluto")
OUTER_BODIES = frozenset({"Uranus", "Neptune", "Pluto"})

_ASPECT_TYPE = {"Conjunction": "conjunction", "Sextile": "sextile", "Square": "square",
                "Trine": "trine", "Opposition": "opposition"}
_REL_CATEGORY = {
    "Openly Friendly": "FRIENDLY_OPEN",
    "Secretly Friendly": "FRIENDLY_SECRET",
    "Neutral": "NEUTRAL",
    "Secretly Inimical": "INIMICAL_SECRET",
    "Openly Inimical": "INIMICAL_OPEN",
}


# ============================================================== Tajika values
def thread_count(virupas: float) -> int:
    """1 thread per 12 virupas, half-up, 1 to 5 (§3.4; not banker's rounding)."""
    return max(1, min(5, int(math.floor(virupas / 12.0 + 0.5))))


def category_of(virupas: float, relationship: str) -> str:
    if virupas >= STRONG_VIRUPAS:
        return "STRONG"
    return _REL_CATEGORY.get(relationship, "NEUTRAL")


# ====================================================================== model
@dataclass(frozen=True)
class Aspect:
    body1: str
    body2: str
    kind: str                 # conjunction | sextile | square | trine | opposition
    virupas: float
    orb: float
    relationship: str
    motion: str
    category: str
    secret: bool
    curve: Curve
    threads: int
    spacing: float

    def touches(self, names: Iterable[str]) -> bool:
        s = set(names)
        return self.body1 in s or self.body2 in s

    def thread_offsets(self) -> List[float]:
        n = self.threads
        return [(i - (n - 1) / 2.0) * self.spacing for i in range(n)]

    @property
    def underlay_width(self) -> float:
        return self.threads * self.spacing * 0.55 + 16.0

    @property
    def opacity(self) -> float:
        return 0.62 + 0.38 * max(0.0, min(60.0, self.virupas)) / 60.0


@dataclass(frozen=True)
class FullModel:
    bodies: Dict[str, Body]
    aspects: Tuple[Aspect, ...]          # every aspect within orb, strongest first

    @property
    def total(self) -> int:
        return len(self.aspects)


@dataclass(frozen=True)
class CenterModel:
    full: FullModel
    drawn: Tuple[Aspect, ...]            # strongest first
    beads: Dict[Tuple[str, str], Point]
    lit: FrozenSet[str]
    faded: FrozenSet[str]
    min_virupas: int

    @property
    def shown(self) -> int:
        return len(self.drawn)

    @property
    def total(self) -> int:
        return self.full.total


# ================================================================ placement
def place_bodies(positions: Mapping[str, float]) -> Dict[str, Body]:
    """Exact points and studs in priority order, radial push only (§3.3)."""
    return _geometry.place_bodies(positions, BODY_ORDER, OUTER_BODIES, bearing=theta_of)


def curve_for(kind: str, a: Body, b: Body) -> Curve:
    """Bundle centre-line between two exact points (§3.4)."""
    A, B = a.exact, b.exact
    dx, dy = B[0] - A[0], B[1] - A[1]
    chord = math.hypot(dx, dy)
    if kind == "conjunction":
        if chord < 1e-6:
            # exact conjunction: tangent = the ray turned 90 deg clockwise, normal = inward
            ux, uy = ray(a.theta)
            d = (-uy, ux)
            n = (-ux, -uy)
        else:
            d = (dx / chord, dy / chord)
            mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
            n = _geometry.toward_center(mid)
            if n == (0.0, 0.0):
                n = (-d[1], d[0])
        c1 = (A[0] + n[0] * LOOP_DEPTH - d[0] * LOOP_SPREAD, A[1] + n[1] * LOOP_DEPTH - d[1] * LOOP_SPREAD)
        c2 = (B[0] + n[0] * LOOP_DEPTH + d[0] * LOOP_SPREAD, B[1] + n[1] * LOOP_DEPTH + d[1] * LOOP_SPREAD)
        return Curve("c", A, B, c1, c2, d, max(chord, 80.0))
    d = (dx / chord, dy / chord) if chord > 1e-9 else (1.0, 0.0)
    mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
    if kind == "opposition":
        n = (-d[1], d[0])            # the chord passes through C: A->B turned 90 deg clockwise
    else:
        n = (-d[1], d[0])
        if n[0] * (SCENE_CENTER[0] - mid[0]) + n[1] * (SCENE_CENTER[1] - mid[1]) < 0:
            n = (-n[0], -n[1])
    f = BOW.get(kind, 0.0)
    q = (mid[0] + n[0] * 2 * f * chord, mid[1] + n[1] * 2 * f * chord)
    return Curve("q", A, B, q, None, n, chord)


def build_full_model(positions: Mapping[str, float], aspects: Sequence[Mapping]) -> FullModel:
    """Bodies and every aspect within orb (minor aspects excluded), strongest first."""
    bodies = place_bodies(positions)
    out = []
    for rec in aspects:
        kind = _ASPECT_TYPE.get(rec.get("aspect", ""))
        b1, b2 = rec.get("body1"), rec.get("body2")
        if kind is None or rec.get("is_minor") or b1 not in bodies or b2 not in bodies:
            continue
        v = float(rec.get("virupas", 0.0))
        rel = rec.get("relationship", "") or ""
        curve = curve_for(kind, bodies[b1], bodies[b2])
        spacing = CONJ_SPACING if kind == "conjunction" else min(22.0, 0.024 * curve.chord)
        out.append(Aspect(b1, b2, kind, v, float(rec.get("distance_from_exact", 0.0)), rel,
                          rec.get("applying_status", "") or "", category_of(v, rel),
                          rel.startswith("Secretly"), curve, thread_count(v), spacing))
    out.sort(key=lambda a: -a.virupas)
    return FullModel(bodies, tuple(out))


def place_beads(drawn: Sequence[Aspect], bodies: Mapping[str, Body]) -> Dict[Tuple[str, str], Point]:
    """One bead per drawn aspect, strongest first, slid along its own curve (§3.4)."""
    studs = [b.stud for b in bodies.values()]
    placed: List[Point] = []
    out = {}
    for asp in drawn:
        best, best_clear = None, -math.inf
        for t in BEAD_TRIES:
            p = asp.curve.at(t)
            clear = math.inf
            for q in placed:
                clear = min(clear, math.hypot(q[0] - p[0], q[1] - p[1]) - BEAD_GAP)
            for q in studs:
                clear = min(clear, math.hypot(q[0] - p[0], q[1] - p[1]) - BEAD_STUD_GAP)
            if clear >= 0:
                best = p
                break
            if clear > best_clear:
                best, best_clear = p, clear
        placed.append(best)
        out[(asp.body1, asp.body2)] = best
    return out


def select(full: FullModel, min_virupas: int = 0, lit: Iterable[str] = ()) -> CenterModel:
    """Apply min_virupas and the lit set (intersection; union over lit bodies) (§3.5)."""
    lit = frozenset(n for n in lit if n in full.bodies)
    drawn = tuple(a for a in full.aspects
                  if a.virupas >= min_virupas and (not lit or a.touches(lit)))
    faded = frozenset()
    if lit:
        keep = set(lit)
        for a in drawn:
            keep.add(a.body1)
            keep.add(a.body2)
        faded = frozenset(n for n in full.bodies if n not in keep)
    return CenterModel(full, drawn, place_beads(drawn, full.bodies), lit, faded, int(min_virupas))


def build_center_model(positions: Mapping[str, float], aspects: Sequence[Mapping],
                       min_virupas: int = 0, lit: Iterable[str] = ()) -> CenterModel:
    """§4.1 convenience: full model then selection."""
    return select(build_full_model(positions, aspects), min_virupas, lit)


def chart_positions(chart) -> Dict[str, float]:
    """L = sign_index * 30 + degree in sign for each Tajika body on ``chart`` (§3.2)."""
    from core.chart_helpers import (get_planet_in_sign_longitude, get_planet_sign_index,
                                    has_planet)
    out = {}
    for name in BODY_ORDER:
        if has_planet(chart, name):
            out[name] = (get_planet_sign_index(chart, name) * 30.0
                         + get_planet_in_sign_longitude(chart, name))
    return out


def model_to_json(model: CenterModel) -> dict:
    """The model as plain data (CLI ``--center-geometry``, §4.7)."""
    def pt(p):
        return [round(p[0], 4), round(p[1], 4)]
    return {
        "center": pt(SCENE_CENTER), "track_r": TRACK_R, "stud_r": STUD_R, "r_min": R_MIN,
        "bodies": {n: {"longitude": round(b.longitude, 4), "theta": round(b.theta, 4),
                       "track_r": round(b.track_r, 4), "exact": pt(b.exact),
                       "stud": pt(b.stud), "push_level": b.push_level, "outer": b.outer,
                       "cluster": list(b.cluster)} for n, b in model.full.bodies.items()},
        "drawn": [{"body1": a.body1, "body2": a.body2, "aspect": a.kind,
                   "virupas": a.virupas, "category": a.category, "secret": a.secret,
                   "threads": a.threads, "bead": pt(model.beads[(a.body1, a.body2)])}
                  for a in model.drawn],
        "lit": sorted(model.lit), "faded": sorted(model.faded),
        "min_virupas": model.min_virupas, "shown": model.shown, "total": model.total,
    }


# ================================================================ state + precedence
@dataclass(frozen=True)
class TajikaCenterState:
    """What the panel pushes into the main host (§3.1)."""
    on: bool = False
    min_virupas: int = 0
    lit: FrozenSet[str] = frozenset()


OFF_STATE = TajikaCenterState()

TAJIKA = "tajika"           # center_choice kind (§3.1, §4.3); TRANSIT, VARGA, EMPTY above


def center_choice(*, time_adjust: bool, guide_active: bool, has_chart: bool,
                  state: Optional[TajikaCenterState], varga_code, compass_active: bool,
                  transit_active: bool, center_varga) -> Tuple[str, str]:
    """The ONE center precedence (SPEC-TJK-003 §4.3, D-3, D-4), shared with every
    center drawing (``core.center_geometry.center_choice``): returns (kind, reason)."""
    return _geometry.center_choice(
        time_adjust=time_adjust, guide_active=guide_active, has_chart=has_chart,
        state=state, varga_code=varga_code, compass_active=compass_active,
        transit_active=transit_active, center_varga=center_varga, drawn=TAJIKA)
