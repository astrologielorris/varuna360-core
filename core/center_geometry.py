# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The geometry shared by the drawings in the South Indian center (SPEC-VAC-001 §3.2, §4.0).

Pure geometry in the 2048 scene of the vector South Indian view, Qt-free. Each body sits
on the ray of its true degree (theta = L - 30, clockwise from 12 o'clock) where that ray
meets a squircle track, so the angle at the center between two bodies is their real
angular separation (SPEC-TJK-003 §3.2). Studs that would overlap move INWARD along their
own ray, never sideways (§3.3). ``center_choice`` is the ONE center precedence for any
drawing whose state has an ``on`` field (SPEC-TJK-003 §4.3).

``core.tajika_center`` re-exports every name here that it held before (``Body``,
``Curve``, the constants) and keeps ``place_bodies(positions)``, so its callers are
unchanged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

Point = Tuple[float, float]

# --- geometry (SPEC-TJK-003 §3.2) ------------------------------------------------------
SCENE_CENTER: Point = (1024.0, 1024.0)
TRACK_R = 420.0                 # squircle |x|^4 + |y|^4 = R^4
TRACK_N = 4.0
FRAME_INSET = 20.0              # loom frame inset from center_rect()
FRAME_RADIUS = 30.0
FRAME_NAIL_R = 3.5
BOUNDARY_NAIL_R = 5.0

# --- studs (SPEC-TJK-003 §3.3) ----------------------------------------------------------
STUD_R = 30.0
STUD_GAP = 2 * STUD_R + 6       # closer than this = collision
STUD_STEP = 2 * STUD_R + 8      # one radial push step
R_MIN = 150.0                   # a pushed stud never goes nearer the center than this
PIN_R = 7.0
TICK_IN = 8.0
TICK_OUT = STUD_R + 13.0
FADED_OPACITY = 0.45            # a stud no drawn mark uses while a key is lit


# =================================================================== geometry
def theta_of(longitude: float) -> float:
    """Bearing of a chart longitude, degrees clockwise from 12 o'clock (§3.2)."""
    return (longitude - 30.0) % 360.0


def ray(theta: float) -> Point:
    """Unit ray for a bearing; scene y grows downward."""
    r = math.radians(theta)
    return (math.sin(r), -math.cos(r))


def track_radius(theta: float) -> float:
    """Distance from the center to the squircle along the ray of ``theta``."""
    ux, uy = ray(theta)
    return TRACK_R / (abs(ux) ** TRACK_N + abs(uy) ** TRACK_N) ** (1.0 / TRACK_N)


def point_on_ray(theta: float, radius: float, center: Point = SCENE_CENTER) -> Point:
    ux, uy = ray(theta)
    return (center[0] + ux * radius, center[1] + uy * radius)


def separation(l1: float, l2: float) -> float:
    """Unsigned angular separation in [0, 180]."""
    d = abs(l1 - l2) % 360.0
    return min(d, 360.0 - d)


def central_angle(a: Point, b: Point, center: Point = SCENE_CENTER) -> float:
    """Angle at the center between two points, numerically stable (atan2)."""
    ax, ay = a[0] - center[0], a[1] - center[1]
    bx, by = b[0] - center[0], b[1] - center[1]
    return math.degrees(math.atan2(abs(ax * by - ay * bx), ax * bx + ay * by))


def toward_center(p: Point) -> Point:
    """Unit vector from ``p`` to the scene center; (0, 0) at the center itself."""
    dx, dy = SCENE_CENTER[0] - p[0], SCENE_CENTER[1] - p[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (0.0, 0.0)


# ====================================================================== model
@dataclass(frozen=True)
class Body:
    name: str
    longitude: float
    theta: float
    track_r: float
    exact: Point
    stud: Point
    push_level: int
    pewter: bool                       # painted in pewter (outer planets, the nodes)
    cluster: Tuple[str, ...] = ()      # other bodies drawn within STUD_GAP of this stud

    @property
    def outer(self) -> bool:
        """The Tajika name of ``pewter`` (Uranus, Neptune, Pluto; SPEC-TJK-003 JSON)."""
        return self.pewter


@dataclass(frozen=True)
class Curve:
    """A quadratic (``q``: A, Q, B) or cubic (``c``: A, c1, c2, B) Bezier, plus the
    unit direction thread offsets move along and the chord length."""
    kind: str
    a: Point
    b: Point
    c1: Point
    c2: Optional[Point]
    offset_dir: Point
    chord: float

    def at(self, t: float) -> Point:
        u = 1.0 - t
        if self.kind == "q":
            return (u * u * self.a[0] + 2 * u * t * self.c1[0] + t * t * self.b[0],
                    u * u * self.a[1] + 2 * u * t * self.c1[1] + t * t * self.b[1])
        c2 = self.c2
        return (u ** 3 * self.a[0] + 3 * u * u * t * self.c1[0] + 3 * u * t * t * c2[0] + t ** 3 * self.b[0],
                u ** 3 * self.a[1] + 3 * u * u * t * self.c1[1] + 3 * u * t * t * c2[1] + t ** 3 * self.b[1])

    def offset(self, o: float) -> "Curve":
        """The same curve with its control point(s) moved by ``o`` along ``offset_dir``."""
        dx, dy = self.offset_dir[0] * o, self.offset_dir[1] * o
        c1 = (self.c1[0] + dx, self.c1[1] + dy)
        c2 = None if self.c2 is None else (self.c2[0] + dx, self.c2[1] + dy)
        return Curve(self.kind, self.a, self.b, c1, c2, self.offset_dir, self.chord)


# ================================================================ placement
def _stud_for(theta: float, track: float, placed: Sequence[Tuple[str, Point]]) -> Tuple[int, Point]:
    """The first radial push level whose stud clears every placed stud (§3.3)."""
    exact = point_on_ray(theta, track)
    max_level = max(0, int(math.floor((track - R_MIN) / STUD_STEP)))
    level, stud = 0, exact
    for lvl in range(max_level + 1):
        cand = point_on_ray(theta, track - lvl * STUD_STEP)
        level, stud = lvl, cand
        if all(math.hypot(cand[0] - q[0], cand[1] - q[1]) >= STUD_GAP for _, q in placed):
            break
    return level, stud


def place_bodies(positions: Mapping[str, float], order: Sequence[str],
                 pewter=frozenset(), bearing=theta_of) -> Dict[str, Body]:
    """Exact points and studs in priority ``order`` (the drawing's body set), radial
    push only (§3.3); a body in ``pewter`` is painted in pewter. ``bearing`` maps a
    longitude to theta (a drawing module passes its own re-exported ``theta_of``, so a
    test that replaces that name reaches the placement). The drawing modules hold their
    body names (``core.tajika_center.place_bodies(positions)`` keeps its one-argument
    call), so this module holds no display text (SPEC-LOC-002 census)."""
    placed: List[Tuple[str, Point]] = []
    raw = {}
    for name in order:
        if name not in positions:
            continue
        lon = float(positions[name])
        th = bearing(lon)
        t = track_radius(th)
        level, stud = _stud_for(th, t, placed)
        placed.append((name, stud))
        raw[name] = (lon, th, t, point_on_ray(th, t), stud, level)
    bodies = {}
    for name, (lon, th, t, exact, stud, level) in raw.items():
        cluster = tuple(o for o, q in placed
                        if o != name and math.hypot(stud[0] - q[0], stud[1] - q[1]) < STUD_GAP)
        bodies[name] = Body(name, lon, th, t, exact, stud, level, name in pewter, cluster)
    return bodies


# ================================================================ precedence
# center_choice kinds and reasons (SPEC-TJK-003 §3.1, §4.3; SPEC-VAC-001 §3.1)
DRAWING, TRANSIT, VARGA, EMPTY = "drawing", "transit", "varga", "empty"


def center_choice(*, time_adjust: bool, guide_active: bool, has_chart: bool, state,
                  varga_code, compass_active: bool, transit_active: bool, center_varga,
                  drawn: str = DRAWING) -> Tuple[str, str]:
    """The ONE center precedence (SPEC-TJK-003 §4.3, D-3, D-4): returns (kind, reason).

    ``state`` is any object with an ``on`` field, or None on a view that never received
    one. ``drawn`` is the kind returned when the drawing is shown. ``reason`` explains
    the drawing: ``shown``, ``off``, or why it is hidden (``time_adjust``, ``guide``,
    ``no_chart``, ``varga``, ``compass``)."""
    on = bool(state is not None and state.on)
    # The first true condition wins: before the drawing, it hides everything.
    for held, reason in ((time_adjust, "time_adjust"), (guide_active, "guide"),
                         (not has_chart, "no_chart")):
        if held:
            return EMPTY, reason if on else "off"
    reason = drawing_reason(on, varga_code, compass_active)
    if reason == "shown":
        return drawn, reason
    if transit_active:
        return TRANSIT, reason
    return (VARGA if center_varga is not None else EMPTY), reason


def drawing_reason(on: bool, varga_code, compass_active: bool) -> str:
    """Why the drawing is (not) shown once a chart is on screen: D1 only (D-4), never
    on the Compass."""
    if not on:
        return "off"
    if varga_code not in (None, 1):
        return "varga"
    return "compass" if compass_active else "shown"
