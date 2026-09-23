"""Curve helpers for the Human Design BodyGraph geometry.

A line-by-line transcription of the ``v4*`` helpers in ``_geometry_v4.js`` (the file the
mockups were rendered from). The transcription is deliberate and literal, down to the
sampling constants, because the sampled arc-length midpoint decides where every channel's
via disc sits: a "better" integrator here would move 30 discs a fraction of a pixel away
from the approved mockup. ``tools/gen_hd_geometry.py`` re-runs the JavaScript under Node
and refuses to emit if this module disagrees with it.

Vocabulary
    point       ``(x, y)``
    cubic       ``(p0, p1, p2, p3)`` -- a cubic Bezier, control points included
    polyline    a sequence of points, drawn with straight segments and round joins
    path        ``("cubic", [cubic, ...])`` or ``("poly", [point, ...])``

Why two path kinds: the 30 ordinary channels ship as dense centrelines that are smoothed
into cubics, while the braid ships as finished polylines. Running the braid back through
the smoother would reintroduce exactly the Catmull-Rom overshoot its geometric
construction removes, so the braid is never splined (canon, "Drawing rule for the braid").
"""

from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]
Cubic = tuple[Point, Point, Point, Point]

KIND_CUBIC = "cubic"
KIND_POLY = "poly"

#: Samples per segment when measuring a cubic's arc length (JS ``v4Halves`` passes 16).
SEG_LENGTH_SAMPLES = 16
#: Samples used to walk into the segment that straddles the halfway point (JS ``N``).
SPLIT_WALK_SAMPLES = 64


def smooth_segments(points: Sequence[Point]) -> list[Cubic]:
    """The cubic list ``v4Smooth`` would draw: Catmull-Rom converted to Beziers.

    Transcribes ``v4Segs``. Note it has no ``length < 3`` guard, unlike ``v4Smooth``: a
    two-point centreline yields the single cubic whose control points sit at the 1/3 and
    2/3 marks of the chord, which is the straight line, so straight channels stay exact.
    """
    segs: list[Cubic] = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[i - 1] if i else points[0]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < n else points[n - 1]
        segs.append((
            (p1[0], p1[1]),
            (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0),
            (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0),
            (p2[0], p2[1]),
        ))
    return segs


def seg_length(c: Cubic, n: int = SEG_LENGTH_SAMPLES) -> float:
    """Chord-sum arc length of one cubic over ``n`` samples (``v4SegLen``)."""
    total = 0.0
    px, py = c[0]
    for i in range(1, n + 1):
        t = i / n
        u = 1.0 - t
        x = u * u * u * c[0][0] + 3 * u * u * t * c[1][0] + 3 * u * t * t * c[2][0] + t * t * t * c[3][0]
        y = u * u * u * c[0][1] + 3 * u * u * t * c[1][1] + 3 * u * t * t * c[2][1] + t * t * t * c[3][1]
        total += math.hypot(x - px, y - py)
        px, py = x, y
    return total


def cubic_point(c: Cubic, t: float) -> Point:
    """The point at parameter ``t`` on a cubic."""
    u = 1.0 - t
    return (
        u * u * u * c[0][0] + 3 * u * u * t * c[1][0] + 3 * u * t * t * c[2][0] + t * t * t * c[3][0],
        u * u * u * c[0][1] + 3 * u * u * t * c[1][1] + 3 * u * t * t * c[2][1] + t * t * t * c[3][1],
    )


def split_cubic(c: Cubic, t: float) -> tuple[Cubic, Cubic]:
    """de Casteljau split (``v4Split``): exact, invents no geometry.

    This is why a coloured half lies exactly on its own tube. Cutting the point list and
    re-running the spline instead feeds Catmull-Rom a duplicated end point at the cut,
    inventing a tangent the parent never had (canon, curve rule 4).
    """
    def lerp(a: Point, b: Point) -> Point:
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    a = lerp(c[0], c[1])
    b = lerp(c[1], c[2])
    d = lerp(c[2], c[3])
    e = lerp(a, b)
    f = lerp(b, d)
    g = lerp(e, f)
    return (c[0], a, e, g), (g, f, d, c[3])


def polyline_length(points: Sequence[Point]) -> float:
    """Total length of a polyline."""
    return sum(
        math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        for i in range(1, len(points))
    )


def split_polyline_at_midpoint(points: Sequence[Point]) -> tuple[list[Point], list[Point]]:
    """Cut a polyline at its arc-length midpoint (the braid branch of ``v4Halves``)."""
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[i - 1] + math.hypot(points[i][0] - points[i - 1][0],
                                           points[i][1] - points[i - 1][1]))
    half = cum[-1] / 2.0
    i = 1
    while i < len(cum) - 1 and cum[i] < half:
        i += 1
    denom = (cum[i] - cum[i - 1]) or 1.0
    f = (half - cum[i - 1]) / denom
    m = (points[i - 1][0] + (points[i][0] - points[i - 1][0]) * f,
         points[i - 1][1] + (points[i][1] - points[i - 1][1]) * f)
    return list(points[:i]) + [m], [m] + list(points[i:])


def split_cubics_at_midpoint(segs: Sequence[Cubic]) -> tuple[list[Cubic], list[Cubic]]:
    """Cut a cubic chain at its arc-length midpoint (the ordinary branch of ``v4Halves``).

    The walk into the straddling segment is the JavaScript's own: 64 uniform-``t`` samples,
    linear interpolation inside the sample that crosses the target length. It is an
    approximation, and reproducing it exactly is the point.
    """
    lengths = [seg_length(c) for c in segs]
    half = sum(lengths) / 2.0

    acc = 0.0
    i = 0
    while i < len(segs) - 1 and acc + lengths[i] < half:
        acc += lengths[i]
        i += 1

    c = segs[i]
    want = half - acc
    n = SPLIT_WALK_SAMPLES
    t = 1.0
    run = 0.0
    px, py = c[0]
    for k in range(1, n + 1):
        tt = k / n
        u = 1.0 - tt
        x = u * u * u * c[0][0] + 3 * u * u * tt * c[1][0] + 3 * u * tt * tt * c[2][0] + tt * tt * tt * c[3][0]
        y = u * u * u * c[0][1] + 3 * u * u * tt * c[1][1] + 3 * u * tt * tt * c[2][1] + tt * tt * tt * c[3][1]
        seg = math.hypot(x - px, y - py)
        if run + seg >= want:
            t = (k - 1 + (want - run) / (seg or 1.0)) / n
            break
        run += seg
        px, py = x, y

    first, second = split_cubic(c, max(0.0, min(1.0, t)))
    return list(segs[:i]) + [first], [second] + list(segs[i + 1:])


# ---------------------------------------------------------------------------
# sampling helpers used by the invariant probes and by hit testing
# ---------------------------------------------------------------------------

def flatten_cubics(segs: Sequence[Cubic], spacing: float = 1.0) -> list[Point]:
    """Flatten a cubic chain to points at roughly ``spacing`` px.

    The canon is explicit that a check must measure *what ships*: curvature read off the
    builder's own control points was optimistic by a third (45.8px builder against 33px
    rendered). Probes therefore flatten first and measure the flattened path.
    """
    out: list[Point] = []
    for c in segs:
        n = max(2, int(math.ceil(seg_length(c, 32) / spacing)))
        start = 0 if not out else 1
        for k in range(start, n + 1):
            out.append(cubic_point(c, k / n))
    return out


def resample(points: Sequence[Point], spacing: float = 1.0) -> list[Point]:
    """Resample a polyline to uniform ``spacing`` along its arc length."""
    if len(points) < 2:
        return list(points)
    out = [tuple(points[0])]
    carry = 0.0
    for i in range(1, len(points)):
        ax, ay = points[i - 1]
        bx, by = points[i]
        d = math.hypot(bx - ax, by - ay)
        if d == 0:
            continue
        pos = spacing - carry
        while pos <= d:
            f = pos / d
            out.append((ax + (bx - ax) * f, ay + (by - ay) * f))
            pos += spacing
        carry = d - (pos - spacing)
    last = tuple(points[-1])
    if math.hypot(out[-1][0] - last[0], out[-1][1] - last[1]) > 1e-9:
        out.append(last)
    return out


def curvature_radii(points: Sequence[Point], stencil: int = 12) -> list[float]:
    """Radius of the circle through samples ``i-stencil``, ``i``, ``i+stencil``.

    A wide stencil is mandatory. Differencing adjacent samples at 1px is dominated by
    coordinate rounding and invents knees that are not there -- the concentric root fans,
    which are true circular arcs, were once reported as 31.9px knees by a narrow stencil
    (canon, curve rule 3).
    """
    radii: list[float] = []
    n = len(points)
    for i in range(stencil, n - stencil):
        (x1, y1), (x2, y2), (x3, y3) = points[i - stencil], points[i], points[i + stencil]
        # circumradius = abc / 4A
        a = math.hypot(x2 - x1, y2 - y1)
        b = math.hypot(x3 - x2, y3 - y2)
        c = math.hypot(x3 - x1, y3 - y1)
        area2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
        if area2 < 1e-12:
            radii.append(math.inf)
        else:
            radii.append(a * b * c / (2.0 * area2))
    return radii


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Even-odd point-in-polygon test. Points exactly on an edge are not guaranteed."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def distance_to_polyline(pt: Point, line: Sequence[Point]) -> float:
    """Shortest distance from a point to an open polyline."""
    best = math.inf
    for i in range(len(line) - 1):
        ax, ay = line[i]
        bx, by = line[i + 1]
        dx, dy = bx - ax, by - ay
        dd = dx * dx + dy * dy
        t = 0.0 if dd == 0 else max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / dd))
        best = min(best, math.hypot(pt[0] - (ax + dx * t), pt[1] - (ay + dy * t)))
    return best


def distance_to_polygon(pt: Point, poly: Sequence[Point]) -> float:
    """Shortest distance from a point to a polygon's outline (not its interior)."""
    best = math.inf
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        dd = dx * dx + dy * dy
        t = 0.0 if dd == 0 else max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / dd))
        best = min(best, math.hypot(pt[0] - (ax + dx * t), pt[1] - (ay + dy * t)))
    return best
