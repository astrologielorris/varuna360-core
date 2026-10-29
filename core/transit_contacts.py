# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Transit-to-natal contact search (td-1u8rs).

Over a date range, find the windows where a transiting planet stands within
an orb of a natal point (at a given aspect angle), with the exact moments
inside each window and the closest approach.

Transit longitudes are the Chart's own: ``transit_longitude`` issues the same
``swe.calc_ut`` call a libaditya Chart's planet issues for the chart frame
(the probe preamble of ``core.chart_helpers.planet_sign_probe``), with the
TRUE node for Rahu and Ketu as the Chart uses (not the probe's mean node, see
td-6hjbm). Natal points come from the natal Chart built in the same frame, so
transit and natal longitudes share one basis (sidereal included).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

# Upper bounds of each body's daily motion (degrees/day). The scan step keeps
# every orb window at least two samples wide, so no pass can slip between.
MAX_DAILY_MOTION = {
    "Sun": 1.03, "Moon": 15.4, "Mercury": 2.2, "Venus": 1.27, "Mars": 0.8,
    "Jupiter": 0.25, "Saturn": 0.14, "Uranus": 0.07, "Neptune": 0.04,
    "Pluto": 0.04, "Rahu": 0.3, "Ketu": 0.3,
}
TRANSIT_BODIES = tuple(MAX_DAILY_MOTION)
NATAL_ANGLES = ("Ascendant", "MC")

_BISECT_DAYS = 1.0 / 86400.0  # refine moments to one second
_ZERO_DEG = 1e-9  # a separation this small is float noise around exact


def _swe_id(swe, body):
    ids = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
           "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
           "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
           "Pluto": swe.PLUTO, "Rahu": swe.TRUE_NODE, "Ketu": swe.TRUE_NODE}
    try:
        return ids[body]
    except KeyError:
        raise ValueError(f"unknown transit body {body!r}") from None


def transit_longitude(jd, mode, ayanamsa, body):
    """Longitude of ``body`` at ``jd`` (UT) in the chart frame: tropical for
    aditya / tropical_classic, sidereal for sidereal, as the Chart planet's
    ``ecliptic_longitude()`` reads it."""
    from core.chart_factory import mode_to_circle_sysflg
    from libaditya import constants as const
    from libaditya import swe, utils

    _circle, sysflg, _names = mode_to_circle_sysflg(mode, ayanamsa)
    vedanga = sysflg == const.SID and ayanamsa in (99, 100)
    if sysflg == const.SID and not vedanga:
        eff = 36 if ayanamsa == 98 else ayanamsa
        from libaditya.custom_ayanamsa import apply_sid_mode
        apply_sid_mode(eff)
        if eff == 97:
            utils.set_swe_true_sidereal_ayanamsa()
    flags = (const.TROP if vedanga else sysflg)
    lon = swe.calc_ut(jd, _swe_id(swe, body), flags)[0][0]
    if vedanga:
        lon = (lon + utils.vedanga_ecliptic_aval(jd)) % 360.0
    if body == "Ketu":
        lon = (lon + 180.0) % 360.0
    return lon % 360.0


def natal_points(natal_chart, names: Iterable[str]) -> Dict[str, float]:
    """Longitude of each named natal point (planets, Ascendant, MC) on the
    natal Chart's own basis. Names the chart does not carry are skipped."""
    from core.chart_helpers import get_planet_decimal_degrees, has_planet
    out = {}
    for name in names:
        if name == "MC":
            out[name] = float(natal_chart.rashi().cusps().mc().ecliptic_longitude())
        elif has_planet(natal_chart, name):
            out[name] = float(get_planet_decimal_degrees(natal_chart, name))
    return out


def _wrap(x):
    """Angle to (-180, 180]."""
    x = (x + 180.0) % 360.0 - 180.0
    return 180.0 if x == -180.0 else x


def _targets(natal_lon, aspect):
    """The longitudes a transit must reach for ``aspect``: natal +/- aspect
    (one target for the conjunction and the opposition)."""
    a = aspect % 360.0
    plus, minus = (natal_lon + a) % 360.0, (natal_lon - a) % 360.0
    return [plus] if abs(_wrap(plus - minus)) < 1e-9 else [plus, minus]


def _bisect(f, lo, hi):
    """Root of f between lo and hi (f(lo), f(hi) of opposite sign)."""
    flo = f(lo)
    while hi - lo > _BISECT_DAYS:
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if (fm <= 0) == (flo <= 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


def _closest(f, lo, hi):
    """Minimum of |f| on [lo, hi] (ternary search; |f| unimodal there)."""
    while hi - lo > _BISECT_DAYS:
        m1, m2 = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
        if abs(f(m1)) <= abs(f(m2)):
            hi = m2
        else:
            lo = m1
    return (lo + hi) / 2.0


def find_contacts(start_jd, end_jd, natal: Dict[str, float], *, mode, ayanamsa,
                  bodies: Iterable[str], aspects: Iterable[float] = (0.0,),
                  orb: float = 1.0, step: Optional[float] = None) -> List[dict]:
    """Every window in [start_jd, end_jd] where a transiting body is within
    ``orb`` degrees of an aspect to a natal point.

    Each window: transit, natal, aspect, target_longitude, start_jd / end_jd
    (the orb edges; ``open_start`` / ``open_end`` when the range cut the window),
    exact_jds (moments the separation is 0, several on a retrograde pass) and
    closest_jd / closest_orb. Sorted by start."""
    if end_jd <= start_jd:
        raise ValueError("the end must come after the start")
    if not orb > 0 or orb == float("inf"):
        raise ValueError("the orb must be a positive number")
    windows = []
    for body in bodies:
        speed = MAX_DAILY_MOTION.get(body)
        if speed is None:
            raise ValueError(f"unknown transit body {body!r}")
        dt = step or min(1.0, orb / (2.0 * speed))
        n = max(1, int((end_jd - start_jd) / dt + 0.999999))
        dt = (end_jd - start_jd) / n
        jds = [start_jd + i * dt for i in range(n + 1)]
        lons = [transit_longitude(jd, mode, ayanamsa, body) for jd in jds]

        for point, natal_lon in natal.items():
            # Equivalent aspects (90 and 270, a repeated angle) name the same
            # targets: scan each target once, under the first aspect given.
            seen = set()
            for aspect in aspects:
                for target in _targets(natal_lon, aspect):
                    key = round(target % 360.0, 9) % 360.0
                    if key in seen:
                        continue
                    seen.add(key)
                    windows.extend(_scan(body, point, aspect, target, jds, lons,
                                         orb, mode, ayanamsa))
    windows.sort(key=lambda w: (w["start_jd"], w["transit"], w["natal"]))
    return windows


def _extremum(f, lo, hi, sign):
    """Minimum (sign=+1) or maximum (sign=-1) of f on [lo, hi] (ternary
    search; f unimodal there)."""
    while hi - lo > _BISECT_DAYS:
        m1, m2 = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
        if sign * f(m1) <= sign * f(m2):
            hi = m2
        else:
            lo = m1
    return (lo + hi) / 2.0


def _station_samples(sep, jds, seps, orb):
    """Extra samples at the turning points the regular step can hide.

    The step bounds a moving planet, not a station: near one, the separation
    can graze into the orb, dip out of it, or cross zero twice between two
    samples whose values say nothing about it. Each of those happens at a
    turning point of the signed separation, so at every local minimum and
    maximum of the sampled separation the true turning point is refined and
    added as a sample whenever it differs from the sample in orb status or in
    sign."""
    n = len(jds)
    extra = []
    for k in range(1, n - 1):
        s = seps[k]
        if abs(s) >= 90:
            continue
        before, after = seps[k - 1], seps[k + 1]
        if s <= before and s <= after:
            m = _extremum(sep, jds[k - 1], jds[k + 1], +1)
        elif s >= before and s >= after:
            m = _extremum(sep, jds[k - 1], jds[k + 1], -1)
        else:
            continue
        v = sep(m)
        if (abs(v) <= orb) != (abs(s) <= orb) or (v < 0) != (s < 0):
            extra.append(m)
    # A turning point between the first (or last) two samples shows as an
    # endpoint extremum: refine it on that one interval.
    for k, other in ((0, 1), (n - 1, n - 2)):
        if n < 2 or abs(seps[k]) >= 90:
            continue
        lo, hi = sorted((jds[k], jds[other]))
        for sign in (+1, -1):
            m = _extremum(sep, lo, hi, sign)
            if lo < m < hi:
                v = sep(m)
                if ((abs(v) <= orb) != (abs(seps[k]) <= orb)
                        or (v < 0) != (seps[k] < 0)):
                    extra.append(m)
    return extra


def _scan(body, point, aspect, target, jds, lons, orb, mode, ayanamsa):
    def sep(jd):
        return _wrap(transit_longitude(jd, mode, ayanamsa, body) - target)

    seps = [_wrap(lon - target) for lon in lons]
    extra = _station_samples(sep, jds, seps, orb)
    if extra:
        merged = sorted(set(zip(jds, seps)) | {(x, sep(x)) for x in extra})
        jds = [p[0] for p in merged]
        seps = [p[1] for p in merged]
    inside = [abs(s) <= orb for s in seps]
    out = []
    i, n = 0, len(jds)
    while i < n:
        if not inside[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and inside[j + 1]:
            j += 1
        # Orb edges: bisect |sep| - orb between the outside and inside samples.
        edge = lambda jd: abs(sep(jd)) - orb  # noqa: E731
        start = jds[i] if i == 0 else _bisect(edge, jds[i - 1], jds[i])
        end = jds[j] if j == n - 1 else _bisect(edge, jds[j], jds[j + 1])
        # A sample within float noise of the target is an exact moment itself.
        exact = [jds[k] for k in range(i, j + 1) if abs(seps[k]) < _ZERO_DEG]
        for k in range(max(i - 1, 0), min(j + 1, n - 1)):
            a, b = seps[k], seps[k + 1]
            if (a * b < 0 and abs(a) < 90 and abs(b) < 90
                    and abs(a) >= _ZERO_DEG and abs(b) >= _ZERO_DEG):
                exact.append(_bisect(sep, jds[k], jds[k + 1]))
        exact = sorted(x for x in exact
                       if start - _BISECT_DAYS <= x <= end + _BISECT_DAYS)
        if exact:
            closest = min(exact, key=lambda x: abs(sep(x)))
        else:
            k = min(range(i, j + 1), key=lambda m: abs(seps[m]))
            closest = _closest(sep, jds[max(k - 1, 0)], jds[min(k + 1, n - 1)])
        out.append({
            "transit": body, "natal": point, "aspect": aspect,
            "target_longitude": target,
            "start_jd": start, "end_jd": end,
            "open_start": i == 0, "open_end": j == n - 1,
            "exact_jds": exact,
            "closest_jd": closest, "closest_orb": abs(sep(closest)),
        })
        i = j + 1
    return out
