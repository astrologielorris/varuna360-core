# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Where each sign rises: Ascendant sign bands across the map (SPEC-MAP-002 §4.3).

For ONE fixed UTC instant, the Ascendant is a function of (longitude, latitude).
This module finds the curves that separate the twelve Ascendant sign bands.

THE CLOSED FORM IS THE ENGINE'S OWN ANSWER
------------------------------------------
The Ascendant has a closed form in RAMC and latitude. Measured against
`ascendant_probe` over a latitude/longitude grid it agrees to **0.00000
degrees** at every latitude out to 89 (`test_map_design.py` locks this). It is
not an approximation of the engine; for this one quantity it is the engine's
answer, reachable without an ephemeris call.

That is what makes a fine longitude walk affordable. Enumerating the crossings
along a latitude row costs no probes at all, so this module can afford to walk
finely enough to find *every* crossing — including the extra ones above the
polar circle that a per-boundary solve cannot even represent. The engine then
confirms the identity of every band that gets drawn (one probe per band per
row), so no band is ever painted with a sign the engine did not agree to. That
is SPEC-MAP-002 INV-2, and Rule 26 with it.

WHY A ROW WALK AND NOT TWELVE BOUNDARY SOLVES
---------------------------------------------
The first implementation solved for each of the twelve boundaries independently
and assumed each one existed exactly once per latitude. Below the polar circle
that is true. Above it, it is false in three different ways at once, and the
code had no way to say so:

  * some signs never rise at all (at 80 N, eight of the twelve do not);
  * others rise in TWO disjoint longitude intervals;
  * the ascending point moves RETROGRADE for part of the rotation, so
    longitude is not even a monotonic parameter for it.

A per-boundary Newton solve met that with the only answer it had: it kept
stepping. Seeded from the row below, it skipped the existence test entirely and
returned whatever it reached after the step cap — values that climbed by
exactly `MAX_STEPS * clamp` per row and looked perfectly plausible. Walking the
row instead makes all three cases representable, and every longitude this
module returns is now checked before it is returned (`_refine`).

WHY NOTHING IS EVER WRAPPED
---------------------------
Longitudes here stay UNWRAPPED. A boundary curve crosses the antimeridian as
*latitude* varies -- east of Australia at 60 N and west of Peru at 60 S can be
one curve -- so any code that wraps a curve into -180..180 and later tries to
reassemble it has to guess which side each piece belongs to. The eclipse
overlay guessed by the average sign of a curve's longitudes, and when a curve
straddled the seam that guess produced a 30-degree zone rendered as a
355-degree slab across the whole globe (54 such slabs in a 12-hour sweep).

There is no seam to cross if you never introduce one. Curves are built
continuous, in whatever longitude range they occupy, and the view layer tiles
the finished band at -360/0/+360 and clips.

WHY THE ZODIAC MODE NEEDS NO CONVERSION TABLE
---------------------------------------------
The closed form is tropical-of-date. The app draws in three frames (aditya,
tropical_classic, sidereal), and hand-converting between them is forbidden --
the software owns that relationship.

So this module never converts. It measures. One probe at a reference point
returns the Ascendant in the ACTIVE frame; the closed form gives the same
Ascendant in the tropical frame; the difference is the frame offset. For a
fixed instant it is constant to 0.00000 degrees across the whole grid (also
locked by test). Change the mode or the ayanamsa and the measurement simply
comes back different. There is no table here to go stale.
"""

import math
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "julian_day_utc",
    "frame_offset_deg",
    "boundary_longitude",
    "polar_limit_deg",
    "latitude_rows",
    "compute_bands",
    "zone_strips",
    "tiled_polygons",
    "zone_of_active",
    "row_intervals",
    "SIGN_THRESHOLDS",
    "probe_count",
    "reset_probe_count",
    "BandResult",
    "BandScan",
    "LAT_LIMIT",
]

#: Latitude limit for band drawing. This is the Web Mercator tile limit, not a
#: limit of the mathematics: `lat_lon_to_pixel` uses asinh(tan(lat)), which
#: diverges at the pole, and no tile exists past 85.05.
#:
#: It used to be 66, on the grounds that the Ascendant "stops being a
#: well-behaved function of longitude" past the polar circle. It does stop being
#: well behaved -- but that is a fact to REPRESENT, not a reason to stop
#: drawing. Greenland, Iceland and northern Norway are inhabited, and a hard cut
#: at 66 left them blank under a horizontal line that read as a boundary.
LAT_LIMIT = 85.0

#: Coarse longitude step of the crossing walk, before adaptive subdivision.
WALK_STEP_DEG = 2.0

#: The walk subdivides until the Ascendant moves no more than this per step.
#: Because a sign is 30 degrees wide, a step whose NET movement is under 30
#: cannot pass entirely through a sign, so no sign is skipped. 20 leaves margin.
#: This is what makes a coarse walk safe: the fine sampling goes only where the
#: field is actually steep, which above the polar circle is a fraction of a
#: degree of longitude and everywhere else is nowhere.
#:
#: 20 is the CAP, not the rule. The rule is "under the narrowest zone", and the
#: eclipse overlay passes thresholds narrower than a sign -- trimsamsa fifths
#: are five to eight degrees. `max_asc_step_for` derives the bound from the
#: threshold spacing actually in use; only the 30-degree sign grid reaches 20.
#:
#: The guarantee is about NET movement, so it is not absolute: inside the polar
#: retrograde region the ascending point reverses, and a step straddling a
#: turning point could in principle advance and come back with little net
#: displacement, hiding a zone between two samples. Hence
#: `test_row_intervals_match_a_dense_engine_walk`, which compares the interval
#: list against a dense `ascendant_probe` walk at latitudes on both sides of the
#: polar circle rather than trusting the argument.
MAX_ASC_STEP_DEG = 20.0

#: Floor on subdivision width. At the polar circle the ascending point's motion
#: becomes a genuine discontinuity in the limit, so the "20 degrees per step"
#: rule cannot always be met; recursion stops here instead. A band narrower than
#: this is far narrower than a pixel at any zoom the picker allows.
WALK_FLOOR_DEG = 1e-4

#: Newton tolerance in degrees of ecliptic longitude (`boundary_longitude`).
TOL_DEG = 0.01

#: Hard cap on refinement steps per boundary point.
MAX_STEPS = 6

#: Bisection steps used to place a crossing found by the walk. 40 halvings of
#: WALK_STEP_DEG reaches far below float longitude resolution; 24 is ample.
BISECT_STEPS = 24

#: Rows per `BandScan.step()`. One row costs ~1440 free evaluations plus ~13
#: probes, so a slice stays well inside a 16 ms frame.
CHUNK_ROWS = 2

_probe_count = 0


def probe_count() -> int:
    """How many `ascendant_probe` calls this module has made (T-3/T-6 probe)."""
    return _probe_count


def reset_probe_count() -> None:
    global _probe_count
    _probe_count = 0


def julian_day_utc(dt_utc) -> float:
    """Julian Day from a UTC datetime, on the CHART's road.

    Deliberately `core.time_utils.julday`, not a bare `swe.julday`. Swiss
    Ephemeris defaults to the Gregorian calendar; the app selects Julian for
    dates before the 1582 reform. For 1500-03-12 the two answers are
    2268994.0 and 2269004.0 — **ten days apart**. A preview built on the bare
    call would put every pre-1582 chart's Ascendant a third of a sign out while
    looking perfectly plausible, which is precisely the silent kind of wrong
    INV-2 exists to forbid.
    """
    from core.time_utils import julday
    hd = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return julday(dt_utc.year, dt_utc.month, dt_utc.day, hd)


def _gst_deg(jd: float) -> float:
    """Greenwich sidereal time in DEGREES."""
    from libaditya import swe
    return (swe.sidtime(jd) * 15.0) % 360.0


def _obliquity_deg(jd: float) -> float:
    """True obliquity of date."""
    from libaditya import swe
    try:
        values, _flag = swe.calc_ut(jd, swe.ECL_NUT, 0)
        return float(values[0])
    except Exception:
        # Mean obliquity is good to arcseconds here and this is only a seed.
        return 23.4392911


def polar_limit_deg(eps_deg: float) -> float:
    """Latitude past which some ecliptic degrees never rise at all.

    The ecliptic's declination runs to +-eps, and a body is circumpolar when
    |dec| > 90 - |lat|. So past |lat| = 90 - eps (about 66.56, the polar circle,
    which is what the polar circle IS) some ecliptic degrees never touch the
    horizon: those signs never rise, and the ones that do can rise twice.

    Derived from the obliquity of date rather than hardcoded, because the
    obliquity is what the geometry actually depends on.
    """
    return 90.0 - eps_deg


def _is_rising(lam_deg: float, ramc_deg: float, eps_deg: float) -> bool:
    """True when ecliptic longitude `lam` is EAST of the meridian, i.e. rising.

    The ecliptic and the horizon are both great circles, so they meet at exactly
    two antipodal points: one rising, one setting. Telling them apart needs no
    latitude at all -- only the sign of the hour angle. A point east of the
    meridian has not culminated yet, so its hour angle is negative.

    This is the fix for a silent 180-degree error. `_tropical_asc`'s atan2 form
    returns whichever of the pair its denominator's sign selects, and past the
    polar circle that is the DESCENDANT. Measured against the engine the closed
    form was out by exactly 180.00000 degrees at every latitude above 66.56 and
    exact below it -- the signature of a quadrant fault, not an accuracy limit.
    """
    lam = math.radians(lam_deg)
    e = math.radians(eps_deg)
    ra = math.degrees(math.atan2(math.sin(lam) * math.cos(e),
                                 math.cos(lam))) % 360.0
    hour_angle = (ramc_deg - ra + 180.0) % 360.0 - 180.0
    return hour_angle < 0.0


def _tropical_asc(ramc_deg: float, lat_deg: float, eps_deg: float) -> float:
    """Closed-form tropical Ascendant. Exact against the engine at every
    latitude out to 89 (locked by `test_closed_form_matches_the_engine`)."""
    r = math.radians(ramc_deg)
    e = math.radians(eps_deg)
    phi = math.radians(max(-89.9, min(89.9, lat_deg)))
    y = math.cos(r)
    x = -(math.sin(r) * math.cos(e) + math.tan(phi) * math.sin(e))
    lam = math.degrees(math.atan2(y, x)) % 360.0
    if not _is_rising(lam, ramc_deg, eps_deg):
        lam = (lam + 180.0) % 360.0
    return lam


def _solve_ramc(target_lon_deg: float, lat_deg: float,
                eps_deg: float) -> Optional[float]:
    """RAMC at which `target_lon_deg` is rising, or None if it never does.

    Rearranging the closed form and multiplying by cos(Asc) — which removes the
    tan(Asc) singularity at 90 and 270 degrees — gives

        cos(L)*cos(R) + sin(L)*cos(eps)*sin(R) = -sin(L)*tan(phi)*sin(eps)

    i.e. `A*cos(R) + B*sin(R) = C`, whose solution is
    `R = atan2(B, A) +- acos(C / hypot(A, B))`.

    Two roots come back: the Ascendant and the Descendant. They are told apart
    by evaluating the forward formula, never by assuming which sign of the
    +- branch is which — that assumption flips with latitude.
    """
    lam = math.radians(target_lon_deg)
    e = math.radians(eps_deg)
    phi = math.radians(max(-89.9, min(89.9, lat_deg)))

    a = math.cos(lam)
    b = math.sin(lam) * math.cos(e)
    c = -math.sin(lam) * math.tan(phi) * math.sin(e)

    hyp = math.hypot(a, b)
    if hyp < 1e-12:
        return None
    ratio = c / hyp
    if ratio > 1.0 or ratio < -1.0:
        # This ecliptic degree never rises at this latitude (circumpolar case).
        return None

    base = math.atan2(b, a)
    delta = math.acos(ratio)
    for root in (base + delta, base - delta):
        ramc = math.degrees(root) % 360.0
        if abs(_signed_delta(_tropical_asc(ramc, lat_deg, eps_deg),
                             target_lon_deg)) < 1e-6:
            return ramc
    return None


def _signed_delta(a_deg: float, b_deg: float) -> float:
    """a - b wrapped into (-180, 180]."""
    return (a_deg - b_deg + 180.0) % 360.0 - 180.0


def _wrap180(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def _probe_mode_longitude(jd: float, lat: float, lon: float,
                          mode: str, ayanamsa: int) -> float:
    """Ascendant in the ACTIVE frame as a single 0-360 longitude.

    `ascendant_probe` returns (sign index, degree in sign) on exactly the basis
    `get_planet_sign_index`/`get_planet_in_sign_longitude` read off a full
    chart, so recombining them is the chart's own Ascendant longitude — not a
    reconstruction of it.
    """
    global _probe_count
    from core.chart_helpers import ascendant_probe
    idx, deg = ascendant_probe(jd, lat, lon, mode, ayanamsa)
    _probe_count += 1
    return (idx * 30.0 + deg) % 360.0


def frame_offset_deg(jd: float, mode: str, ayanamsa: int,
                     ref_lat: float = 45.0, ref_lon: float = 0.0) -> float:
    """tropical - active-frame longitude, measured from the engine.

    Constant across the map for a fixed instant, so one probe fixes it for the
    whole band set. Measured, never tabulated: see the module docstring.
    """
    eps = _obliquity_deg(jd)
    ramc = (_gst_deg(jd) + ref_lon) % 360.0
    tropical = _tropical_asc(ramc, ref_lat, eps)
    active = _probe_mode_longitude(jd, ref_lat, ref_lon, mode, ayanamsa)
    return (tropical - active) % 360.0


def boundary_longitude(jd: float, lat: float, boundary_index: int,
                       mode: str, ayanamsa: int, offset_deg: float,
                       gst_deg: float, eps_deg: float,
                       seed_hint: Optional[float] = None) -> Optional[float]:
    """Longitude where the Ascendant crosses into sign `boundary_index`.

    Returns an UNWRAPPED longitude in degrees (may fall outside -180..180; the
    caller anchors it). None when the boundary does not exist at this latitude
    OR when refinement did not converge.

    Never returns an unconverged value. It used to: with `seed_hint` set it
    skipped the existence test and returned whatever the step cap reached, which
    above the polar circle meant longitudes climbing by exactly
    `MAX_STEPS * clamp` per row -- confidently wrong and impossible to spot by
    eye. An absent boundary is a drawing gap; a plausible wrong one is a lie.
    """
    target_tropical = (boundary_index * 30.0 + offset_deg) % 360.0
    target_active = (boundary_index * 30.0) % 360.0

    seeds: List[float] = []
    if seed_hint is not None:
        seeds.append(seed_hint)
    ramc = _solve_ramc(target_tropical, lat, eps_deg)
    if ramc is not None:
        # Anchor the closed-form seed near the hint so a continued curve keeps
        # its branch instead of jumping a whole revolution.
        raw = _signed_delta(ramc, gst_deg)
        if seed_hint is not None:
            raw = seed_hint + _signed_delta(raw, seed_hint)
        seeds.append(raw)

    for seed in seeds:
        got = _newton_boundary(jd, lat, seed, target_active, mode, ayanamsa,
                               gst_deg, eps_deg)
        if got is not None:
            return got
    return None


def _newton_boundary(jd: float, lat: float, seed: float, target_active: float,
                     mode: str, ayanamsa: int, gst_deg: float,
                     eps_deg: float) -> Optional[float]:
    """Newton refinement of one boundary, probe-driven. None if it misses."""
    lon = seed
    for _ in range(MAX_STEPS):
        actual = _probe_mode_longitude(jd, lat, _wrap180(lon), mode, ayanamsa)
        err = _signed_delta(actual, target_active)
        if abs(err) < TOL_DEG:
            return lon

        # Local slope of Ascendant vs longitude, from the closed form. Free
        # (no probe) and accurate enough to drive Newton; the probe still
        # decides when to stop.
        h = 0.05
        ramc0 = (gst_deg + lon - h) % 360.0
        ramc1 = (gst_deg + lon + h) % 360.0
        slope = _signed_delta(_tropical_asc(ramc1, lat, eps_deg),
                              _tropical_asc(ramc0, lat, eps_deg)) / (2 * h)
        if abs(slope) < 1e-6:
            return None

        step = max(-30.0, min(30.0, err / slope))
        lon -= step

    return None


# ---------------------------------------------------------------------------
# Row walk: every crossing along one latitude
# ---------------------------------------------------------------------------

#: The twelve sign boundaries, in degrees of ACTIVE-frame Ascendant longitude.
SIGN_THRESHOLDS: Tuple[float, ...] = tuple(float(i * 30) for i in range(12))


def zone_of_active(active_lon_deg: float,
                   thresholds: Sequence[float] = SIGN_THRESHOLDS) -> int:
    """Which zone an ACTIVE-frame Ascendant longitude falls in.

    `thresholds` is ascending in [0, 360): zone i runs from thresholds[i] to
    thresholds[i+1], and the last zone wraps through 360 back to thresholds[0].

    Generalising past sign boundaries is what lets the eclipse overlay share
    this module. Its hora and trimsamsa zones split INSIDE a sign — at 15
    degrees, or at 5/10/18/25 — so they are not sign boundaries at all, but they
    are still thresholds on the same quantity. One geometry, three features.
    """
    from bisect import bisect_right
    x = active_lon_deg % 360.0
    i = bisect_right(thresholds, x) - 1
    return i if i >= 0 else len(thresholds) - 1


def max_asc_step_for(thresholds: Sequence[float] = SIGN_THRESHOLDS,
                     cap: float = MAX_ASC_STEP_DEG) -> float:
    """Largest safe per-step Ascendant movement for THIS threshold set.

    The walk places one crossing per segment by bisection, so a segment that
    steps clean over a whole zone loses that zone entirely -- and `verify_zones`
    cannot catch it, because a zone that was never emitted is never verified.
    The only thing that prevents it is a step shorter than the narrowest zone.

    For the 30-degree sign grid that bound is 30, and the cap of 20 leaves
    margin. For the eclipse overlay's thresholds it is much tighter: trimsamsa
    fifths of a sign are 5, 5, 8, 7 and 5 degrees wide, so a 20-degree step
    could jump two of them at once. Two thirds of the narrowest gap keeps the
    same margin the sign grid has. Extra samples cost nothing measurable --
    they are closed-form evaluations, not engine probes.
    """
    xs = sorted(float(t) % 360.0 for t in thresholds)
    if len(xs) < 2:
        return float(cap)
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    gaps.append(360.0 - xs[-1] + xs[0])
    narrowest = min(g for g in gaps if g > 0.0)
    return min(float(cap), narrowest * 2.0 / 3.0)


def _zone_of_tropical(lam_deg: float, offset: float,
                      thresholds: Sequence[float]) -> int:
    return zone_of_active((lam_deg - offset) % 360.0, thresholds)


def _active_sign_index(ramc_deg: float, lat: float, eps: float,
                       offset: float,
                       thresholds: Sequence[float] = SIGN_THRESHOLDS) -> int:
    """Zone index in the ACTIVE frame, from the closed form. No probe."""
    return _zone_of_tropical(_tropical_asc(ramc_deg, lat, eps), offset,
                             thresholds)


def _bisect_crossing(lon_a: float, lon_b: float, idx_a: int, lat: float,
                     gst: float, eps: float, offset: float,
                     thresholds: Sequence[float]) -> float:
    """Longitude of the index change bracketed by (lon_a, lon_b)."""
    for _ in range(BISECT_STEPS):
        mid = (lon_a + lon_b) / 2.0
        if _active_sign_index((gst + mid) % 360.0, lat, eps, offset,
                              thresholds) == idx_a:
            lon_a = mid
        else:
            lon_b = mid
    return (lon_a + lon_b) / 2.0


def _subdivide(out: List[Tuple[float, float]], lon_a: float, lam_a: float,
               lon_b: float, lam_b: float, lat: float, gst: float, eps: float,
               max_step: float, floor: float) -> None:
    """Append samples between a and b until the Ascendant moves <= max_step.

    Appends (lon_b, lam_b) last, so the caller gets a monotonically increasing
    longitude sequence.
    """
    if (abs(_signed_delta(lam_b, lam_a)) <= max_step
            or (lon_b - lon_a) <= floor):
        out.append((lon_b, lam_b))
        return
    lon_m = (lon_a + lon_b) / 2.0
    lam_m = _tropical_asc((gst + lon_m) % 360.0, lat, eps)
    _subdivide(out, lon_a, lam_a, lon_m, lam_m, lat, gst, eps, max_step, floor)
    _subdivide(out, lon_m, lam_m, lon_b, lam_b, lat, gst, eps, max_step, floor)


def _row_samples(lat: float, gst: float, eps: float, coarse: float,
                 max_step: float, floor: float) -> List[Tuple[float, float]]:
    """(longitude, tropical Ascendant) over one full period, adaptively dense."""
    n = max(8, int(round(360.0 / coarse)))
    step = 360.0 / n
    lon_a = -180.0
    lam_a = _tropical_asc((gst + lon_a) % 360.0, lat, eps)
    out: List[Tuple[float, float]] = [(lon_a, lam_a)]
    for i in range(1, n + 1):
        lon_b = -180.0 + i * step
        lam_b = _tropical_asc((gst + lon_b) % 360.0, lat, eps)
        _subdivide(out, lon_a, lam_a, lon_b, lam_b, lat, gst, eps, max_step,
                   floor)
        lon_a, lam_a = lon_b, lam_b
    return out


def row_intervals(jd: float, lat: float, gst: float, eps: float, offset: float,
                  mode: str, ayanamsa: int, step_deg: float = WALK_STEP_DEG,
                  verify: bool = True,
                  max_asc_step: Optional[float] = None,
                  thresholds: Sequence[float] = SIGN_THRESHOLDS,
                  verify_zones: Optional[set] = None
                  ) -> List[Tuple[int, float, float]]:
    """Every Ascendant zone interval along one latitude, as (zone, lo, hi).

    Walks one full period of longitude with the closed form -- free, so it costs
    no probes -- subdividing wherever the Ascendant moves fast enough that a
    whole sign could hide between two samples, and places each index change by
    bisection.

    Intervals come back in ascending longitude and may extend past +180: the
    last one wraps into the next period, which is correct and is why nothing
    here is normalised. A sign may appear zero, one or two times.

    With `verify`, the ENGINE confirms the identity of every interval returned
    (one probe at its midpoint) and an interval the engine disagrees with is
    dropped rather than drawn. That is the run-time half of INV-2; the other
    half is the test that locks the closed form to the engine.
    """
    if max_asc_step is None:
        max_asc_step = max_asc_step_for(thresholds)
    samples = _row_samples(lat, gst, eps, step_deg, max_asc_step,
                           WALK_FLOOR_DEG)

    idx_prev = _zone_of_tropical(samples[0][1], offset, thresholds)
    crossings: List[Tuple[float, int]] = []   # (lon, index AFTER the crossing)
    for i in range(1, len(samples)):
        lon, lam = samples[i]
        idx = _zone_of_tropical(lam, offset, thresholds)
        if idx != idx_prev:
            crossings.append((_bisect_crossing(samples[i - 1][0], lon,
                                               idx_prev, lat, gst, eps,
                                               offset, thresholds), idx))
            idx_prev = idx

    if len(crossings) < 2:
        # No index change anywhere on the row: one zone owns the whole period.
        # Real only in degenerate cases; represent it rather than drop it.
        if verify:
            probed = zone_of_active(
                _probe_mode_longitude(jd, lat, 0.0, mode, ayanamsa), thresholds)
            if probed != idx_prev:
                return []
        return [(idx_prev, -180.0, 180.0)]

    intervals: List[Tuple[int, float, float]] = []
    for i, (lon, _idx) in enumerate(crossings):
        if i + 1 < len(crossings):
            hi = crossings[i + 1][0]
        else:
            # Periodic: the last interval closes on the first crossing of the
            # NEXT period. Left unwrapped on purpose.
            hi = crossings[0][0] + 360.0
        if hi - lon <= 0.0:
            continue
        mid = (lon + hi) / 2.0
        zone = _active_sign_index((gst + mid) % 360.0, lat, eps, offset,
                                  thresholds)
        # `verify_zones` skips the confirming probe for zones the caller is
        # going to throw away. The eclipse overlay wants one sign out of twelve,
        # so confirming the other eleven costs eleven twelfths of the scan and
        # buys nothing: what is never drawn needs no guarantee.
        if verify and (verify_zones is None or zone in verify_zones):
            probed = zone_of_active(
                _probe_mode_longitude(jd, lat, _wrap180(mid), mode, ayanamsa),
                thresholds)
            if probed != zone:
                continue
        intervals.append((zone, lon, hi))

    return intervals


#: Row spacing away from the polar circles, in degrees of latitude.
ROW_COARSE_DEG = 6.0

#: Row spacing inside `ROW_FINE_MARGIN` of a polar circle, and above it.
ROW_FINE_DEG = 1.5

#: How far below a polar circle the fine spacing starts. The bands do not just
#: stop at the polar circle -- four of them pinch from 7 degrees wide at 60 to
#: under one degree at 66 and close at 66.56. Coarse rows step over that taper
#: and leave a visible hole where narrow bands really exist.
ROW_FINE_MARGIN = 12.0


def latitude_rows(lat_limit: float = LAT_LIMIT,
                  polar_limit: float = 66.5583) -> List[float]:
    """Latitudes to sample, denser where the curves bend hardest.

    Away from the polar circles the boundary curves are smooth and coarse rows
    are plenty. Approaching one they pinch, and above it they bend sharply,
    split, reorder and vanish -- so the rows tighten from `ROW_FINE_MARGIN`
    below each circle all the way to the limit. A uniform schedule fine enough
    for the Arctic would spend most of its probes where nothing happens.
    """
    lat_limit = min(abs(lat_limit), LAT_LIMIT)
    polar = min(abs(polar_limit), lat_limit)
    fine_from = max(0.0, polar - ROW_FINE_MARGIN)

    rows = {0.0}
    lat = ROW_COARSE_DEG
    while lat < fine_from - 1e-9:
        rows.update((lat, -lat))
        lat += ROW_COARSE_DEG

    lat = fine_from
    while lat < lat_limit - 1e-9:
        rows.update((lat, -lat))
        lat += ROW_FINE_DEG
    rows.update((polar, -polar, lat_limit, -lat_limit))

    return sorted(round(v, 6) for v in rows)


# ---------------------------------------------------------------------------
# Band assembly
# ---------------------------------------------------------------------------

class BandResult:
    """One Ascendant sign band.

    `coords` is the closed polygon (left edge south-to-north, then the right
    edge back down) and is what the fill is built from.

    `left` and `right` are the same two edges as OPEN polylines. They exist
    because only they are real Ascendant boundaries: the segments that close the
    polygon at its top and bottom are where the DATA stops, not where a sign
    changes. Stroking the closed polygon drew those terminators as a crisp
    horizontal line right across the map, which read as a boundary and was not
    one. The view layer fills `coords` with no pen and strokes `left`/`right`.
    """

    __slots__ = ("sign_index", "coords", "left", "right")

    def __init__(self, sign_index: int, coords: List[Tuple[float, float]],
                 left: Optional[List[Tuple[float, float]]] = None,
                 right: Optional[List[Tuple[float, float]]] = None):
        self.sign_index = sign_index
        self.coords = coords
        self.left = left if left is not None else []
        self.right = right if right is not None else []


class _Strip:
    """A band under construction: one connected component of one sign."""

    __slots__ = ("sign", "left", "right", "first_i", "last_i")

    def __init__(self, sign: int, lat: float, lo: float, hi: float,
                 row_index: int = 0):
        self.sign = sign
        self.left: List[Tuple[float, float]] = [(lat, lo)]
        self.right: List[Tuple[float, float]] = [(lat, hi)]
        self.first_i = row_index
        self.last_i = row_index

    @property
    def lo(self) -> float:
        return self.left[-1][1]

    @property
    def hi(self) -> float:
        return self.right[-1][1]

    def extend(self, lat: float, lo: float, hi: float,
               row_index: Optional[int] = None) -> None:
        self.left.append((lat, lo))
        self.right.append((lat, hi))
        if row_index is not None:
            self.last_i = row_index

    def taper(self, lats: Sequence[float]) -> None:
        """Close the ends where the zone stops existing, tapering to a point.

        A band does not end bluntly at a sampled latitude. It ends where its two
        boundaries MEET, somewhere between the last row that has it and the first
        that does not, and drawing it flat-topped both overstates its extent and
        leaves the neighbouring rows short of a full 360 degrees of coverage.

        The meeting latitude is placed halfway to the empty row — a linear
        interpolation, so the error is bounded by half a row (0.75 degrees in the
        polar band). Deliberately NOT applied at the outermost rows: there the
        data stops because the map does, and a taper would invent a pinch that
        the geometry does not have.
        """
        if self.last_i + 1 < len(lats):
            lat = (lats[self.last_i] + lats[self.last_i + 1]) / 2.0
            mid = (self.left[-1][1] + self.right[-1][1]) / 2.0
            self.left.append((lat, mid))
            self.right.append((lat, mid))
        if self.first_i - 1 >= 0:
            lat = (lats[self.first_i] + lats[self.first_i - 1]) / 2.0
            mid = (self.left[0][1] + self.right[0][1]) / 2.0
            self.left.insert(0, (lat, mid))
            self.right.insert(0, (lat, mid))

    def finish(self) -> Optional[BandResult]:
        if len(self.left) < 2:
            return None
        # ONE multiple-of-360 shift for the whole strip, anchored on its middle
        # row, so the band lands in view with every row still on the same
        # branch. Wrapping row by row is what turned a 30-degree band into a
        # 357-degree diagonal slab: Qt joined 179.8 to -177.1 straight across
        # the globe.
        mid = len(self.left) // 2
        shift = _wrap180(self.left[mid][1]) - self.left[mid][1]
        left = [(lat, lon + shift) for lat, lon in self.left]
        right = [(lat, lon + shift) for lat, lon in self.right]
        return BandResult(self.sign, left + list(reversed(right)), left, right)


def _link_rows(rows: Sequence[Tuple[float, List[Tuple[int, float, float]]]]
               ) -> List[BandResult]:
    """Stitch per-row intervals into bands, south to north.

    An interval continues the strip it overlaps most in longitude. A strip that
    two intervals both overlap has SPLIT — which happens where the field tears
    just above the polar circle — and it forks: the extra interval starts a new
    strip whose first row is the parent's last, so the two pieces meet instead
    of leaving a wedge unpainted. Anything still unmatched opens a fresh strip,
    and a strip nothing matched is closed.

    Without forking, the split interval was simply dropped (a one-row strip has
    no area), and the bands at those rows covered 332 of the 360 degrees they
    should — a visible unpainted wedge exactly where the interesting thing was
    happening.
    """
    open_strips: List[_Strip] = []
    done: List[BandResult] = []
    lats = [lat for lat, _iv in rows]

    def _close(strip: _Strip) -> None:
        strip.taper(lats)
        band = strip.finish()
        if band is not None:
            done.append(band)

    for row_i, (lat, intervals) in enumerate(rows):
        # Score every (strip, interval) pair of the same sign, best overlap wins.
        candidates = []
        for si, strip in enumerate(open_strips):
            s_mid = (strip.lo + strip.hi) / 2.0
            for ii, (sign, lo, hi) in enumerate(intervals):
                if sign != strip.sign:
                    continue
                # Bring the interval onto the strip's branch before comparing.
                shift = round((s_mid - (lo + hi) / 2.0) / 360.0) * 360.0
                a, b = lo + shift, hi + shift
                overlap = min(b, strip.hi) - max(a, strip.lo)
                if overlap > 0.0:
                    candidates.append((overlap, si, ii, a, b))

        extend: dict = {}                      # strip index -> (lo, hi)
        fork: List[Tuple[int, float, float]] = []
        used_intervals = set()
        for _overlap, si, ii, a, b in sorted(candidates, reverse=True):
            if ii in used_intervals:
                continue
            used_intervals.add(ii)
            if si in extend:
                fork.append((si, a, b))        # the strip splits here
            else:
                extend[si] = (a, b)

        # Forks are built BEFORE the parents advance: a child's first row is the
        # parent's last, which is the row they still shared.
        children: List[_Strip] = []
        for si, a, b in fork:
            parent = open_strips[si]
            p_lat, p_lo = parent.left[-1]
            p_hi = parent.right[-1][1]
            # parent.last_i, not row_i - 1: a strip is extended at every row it
            # survives, so the two are equal today — but reading it off the
            # parent stays correct if that ever stops being true.
            child = _Strip(parent.sign, p_lat, p_lo, p_hi, parent.last_i)
            child.extend(lat, a, b, row_i)
            children.append(child)

        still_open: List[_Strip] = []
        for si, strip in enumerate(open_strips):
            if si in extend:
                a, b = extend[si]
                strip.extend(lat, a, b, row_i)
                still_open.append(strip)
            else:
                _close(strip)
        still_open.extend(children)
        open_strips = still_open

        for ii, (sign, lo, hi) in enumerate(intervals):
            if ii not in used_intervals:
                open_strips.append(_Strip(sign, lat, lo, hi, row_i))

    for strip in open_strips:
        _close(strip)

    return done


#: Kept for callers that still speak of a single default row count.
DEFAULT_ROWS = len(latitude_rows())


class BandScan:
    """An Ascendant band scan you can run a slice at a time.

    WHY THIS IS NOT A WORKER THREAD
    -------------------------------
    It was one, and that was a correctness bug. Swiss Ephemeris keeps GLOBAL
    mutable state: `swe.set_sid_mode()` is called immediately before
    `swe.houses_ex2()` in `libaditya/objects/cusps.py`, and from eleven other
    places across the engine, with no lock anywhere. A band scan running on a
    worker while the GUI thread builds a chart can interleave between those two
    calls — so the scan can draw the wrong frame, or, far worse, the CHART the
    user is saving can be computed under the scan's ayanamsa.

    Locking one corner of a globally-unsafe library does not make it safe, and
    wrapping all twelve call sites in a vendored engine is a different piece of
    work. So the concurrency is removed instead: the scan runs on the GUI
    thread in slices small enough that no single slice costs a frame, driven by
    a timer rather than by `processEvents()` (which would re-enter the event
    loop mid-scan). INV-1 says the GUI thread may compute but may not wait —
    this computes, in pieces, and never waits.
    """

    def __init__(self, jd: float, mode: str, ayanamsa: int = 1,
                 rows: Optional[int] = None, lat_limit: float = LAT_LIMIT,
                 chunk_rows: int = CHUNK_ROWS,
                 step_deg: float = WALK_STEP_DEG, verify: bool = True,
                 thresholds: Sequence[float] = SIGN_THRESHOLDS,
                 verify_zones: Optional[set] = None,
                 max_asc_step: Optional[float] = None):
        self.jd = jd
        self.mode = mode
        self.ayanamsa = ayanamsa
        self.chunk_rows = max(1, int(chunk_rows))
        self.step_deg = step_deg
        self.verify = verify
        self.thresholds = tuple(thresholds)
        self.verify_zones = set(verify_zones) if verify_zones is not None else None
        #: Derived, never assumed: narrow thresholds need a shorter step or the
        #: walk skips a zone outright (see `max_asc_step_for`).
        self.max_asc_step = (float(max_asc_step) if max_asc_step is not None
                             else max_asc_step_for(self.thresholds))

        self._gst = _gst_deg(jd)
        self._eps = _obliquity_deg(jd)
        self._offset = frame_offset_deg(jd, mode, ayanamsa)

        polar = polar_limit_deg(self._eps)
        if rows:
            # Explicit row count: uniform, for tests and CLI reproducibility.
            # One row spans no latitude, so it cannot make a band; treat it as
            # the smallest scan that can, rather than dividing by zero.
            n = max(2, int(rows))
            limit = min(abs(lat_limit), LAT_LIMIT)
            self._lats = [(-limit + (2 * limit) * i / (n - 1))
                          for i in range(n)]
        else:
            self._lats = latitude_rows(lat_limit, polar)

        self._rows: List[Tuple[float, List[Tuple[int, float, float]]]] = []
        self._i = 0
        self.done = False

    def step(self) -> bool:
        """Compute one slice. Returns True when the whole scan is finished."""
        if self.done:
            return True

        for _ in range(self.chunk_rows):
            if self._i >= len(self._lats):
                break
            lat = self._lats[self._i]
            self._rows.append((lat, row_intervals(
                self.jd, lat, self._gst, self._eps, self._offset, self.mode,
                self.ayanamsa, step_deg=self.step_deg, verify=self.verify,
                max_asc_step=self.max_asc_step,
                thresholds=self.thresholds, verify_zones=self.verify_zones)))
            self._i += 1

        if self._i >= len(self._lats):
            self.done = True
        return self.done

    def result(self) -> List[BandResult]:
        """Assemble the bands. Meaningless before `done`."""
        return _link_rows(self._rows)


def compute_bands(jd: float, mode: str, ayanamsa: int = 1,
                  rows: Optional[int] = None, lat_limit: float = LAT_LIMIT,
                  should_cancel=None, step_deg: float = WALK_STEP_DEG,
                  verify: bool = True,
                  thresholds: Sequence[float] = SIGN_THRESHOLDS,
                  verify_zones: Optional[set] = None
                  ) -> List[BandResult]:
    """Ascendant bands for one instant, computed in one go.

    Returns AT LEAST twelve bands below the polar circle, and more when a sign
    rises in two separate places -- which above the polar circle it does. For
    CLI and test use; interactive callers drive a `BandScan` a slice at a time
    so the GUI thread is never held (see that class for why not a worker).
    """
    scan = BandScan(jd, mode, ayanamsa, rows=rows, lat_limit=lat_limit,
                    step_deg=step_deg, verify=verify, thresholds=thresholds,
                    verify_zones=verify_zones)
    while not scan.step():
        if should_cancel is not None and should_cancel():
            return []
    return scan.result()


def zone_strips(jd: float, zones: Sequence[int], mode: str = "aditya",
                ayanamsa: int = 1, thresholds: Sequence[float] = SIGN_THRESHOLDS,
                lat_limit: float = LAT_LIMIT, rows: Optional[int] = None,
                should_cancel=None, verify: bool = True
                ) -> List[BandResult]:
    """The strips for SOME zones only — the eclipse overlay's entry point.

    The eclipse panel wants one sign's Ascendant zone, or that sign split into
    hora halves or trimsamsa fifths. All three are the same question with
    different `thresholds`, and all three used to be answered by a private
    5-degree longitude scan plus a bisection, whose results were then wrapped
    into -180..180 and reassembled by guessing which side of the antimeridian
    each piece belonged on. That guess produced 54 globe-spanning slabs in a
    12-hour sweep (SPEC-MAP-002 §4.3.1).

    Here the strips come back unwrapped and continuous, and a caller draws them
    tiled at -360/0/+360. Above the polar circle a zone may come back as two
    strips or none, which is the truth and which the old scan could not express.
    """
    wanted = set(int(z) for z in zones)
    bands = compute_bands(jd, mode, ayanamsa, rows=rows, lat_limit=lat_limit,
                          should_cancel=should_cancel, verify=verify,
                          thresholds=thresholds, verify_zones=wanted)
    return [b for b in bands if b.sign_index in wanted]


def tiled_polygons(coords: Sequence[Tuple[float, float]],
                   shifts: Sequence[float] = (-360.0, 0.0, 360.0)
                   ) -> List[List[Tuple[float, float]]]:
    """One polygon as its wrap copies, for a view that clips.

    The replacement for splitting a polygon at the antimeridian. Splitting has
    to decide which side each vertex belongs on, and for a curve that crosses
    the seam as LATITUDE varies there is no such answer. Drawing the whole thing
    three times, one period apart, needs no decision at all: whichever copy the
    viewport contains is the right one, and the others are off-screen.
    """
    pts = list(coords)
    return [[(lat, lon + s) for lat, lon in pts] for s in shifts]
