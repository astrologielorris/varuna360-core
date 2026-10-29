# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Sign ingresses and body tracks in the chart's own frame (SPEC-COACH-001 §4.4).

Every position is a libaditya ``Planet`` built by the same constructor and the
same ``EphContext`` arguments a Chart uses (``core.chart_factory``), one body at
a time: the sign index, in-sign degree, nakshatra and pada are the Chart
planet's own, bit for bit (``test/test_ingress.py`` locks the parity), at about
0.1 ms per position instead of about 70 ms for a whole Chart. So the sign a
coach story names at an ingress is the sign the chart shows a minute later.

Qt-free and Pro-free: every edition can call it.
"""
from __future__ import annotations

import math

from typing import Dict, List, Optional

from core.transit_contacts import MAX_DAILY_MOTION

BODIES = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
          "Rahu", "Ketu", "Uranus", "Neptune", "Pluto")

# Scan step (days). The Moon moves about 0.6 degree an hour; every other body
# needs weeks near a station to cross a boundary and come back, so six hours
# can never hide a double crossing.
_STEP_DAYS = {"Moon": 1.0 / 24.0}
_DEFAULT_STEP = 0.25
_BISECT_DAYS = 1.0 / 86400.0      # one second
MAX_SCAN_SAMPLES = 20000          # Moon: about 833 days; others: about 13 years
MAX_TRACK_SAMPLES = 2000


class IngressError(ValueError):
    """A request the engine refuses (unknown body, range too long...)."""


def _check_body(body: str) -> str:
    if body not in BODIES:
        raise IngressError(f"unknown body {body!r}; one of {', '.join(BODIES)}")
    return body


def _context(jd: float, mode: str, ayanamsa: int, lat: float, lon: float):
    """The EphContext ``build_chart_from_params`` builds, at UT ``jd``."""
    from core.chart_factory import mode_to_circle_sysflg
    from libaditya.objects.context import EphContext
    from libaditya.objects.julian_day import JulianDay
    from libaditya.objects.location import Location

    circle, sysflg, sign_names = mode_to_circle_sysflg(mode, ayanamsa)
    return EphContext(
        timeJD=JulianDay(jd, utcoffset=0.0),
        location=Location(lat=lat, long=lon, alt=0, utcoffset=0.0),
        sysflg=sysflg, amsha=1, ayanamsa=ayanamsa, hsys="C", circle=circle,
        signize=True, toround=(True, 3), names_type="mixed", sign_names=sign_names,
    )


def body_at(jd: float, body: str, *, mode: str, ayanamsa: int,
            lat: float = 0.0, lon: float = 0.0):
    """The libaditya Planet for ``body`` at UT ``jd``, as a Chart in ``mode``
    would hold it (same constructor, master ``None``)."""
    from libaditya.objects.planets import natural_planets
    return natural_planets[_check_body(body)](
        _context(jd, mode, ayanamsa, lat, lon), None)


def _sign_index(jd, body, mode, ayanamsa, lat, lon) -> int:
    return int(body_at(jd, body, mode=mode, ayanamsa=ayanamsa, lat=lat, lon=lon).sign()) - 1


def _scan_step(body: str) -> float:
    return _STEP_DAYS.get(body, _DEFAULT_STEP)


_J2000 = 2451545.0


def _first_second(lo: float, before: int, sign) -> float:
    """The first whole UT second in the new sign, given ``lo`` (still in sign
    ``before``) less than one second before the change: ceil(lo) when the
    change is already behind it, else the second after."""
    sec = math.ceil(round((lo - _J2000) * 86400.0, 6))
    jd = _J2000 + sec / 86400.0
    if sign(jd) == before:
        jd = _J2000 + (sec + 1) / 86400.0
    return jd


def find_ingresses(start_jd: float, end_jd: float, body: str, *, mode: str,
                   ayanamsa: int, lat: float = 0.0, lon: float = 0.0) -> List[Dict]:
    """Every sign change of ``body`` in [start_jd, end_jd] (UT), in time order.

    Each item: body, jd (the first second in the new sign), from_index,
    to_index (wheel ordinals, 0 = Dhata = Aries), retrograde (True when the
    body enters the previous sign). Refined by bisection to one second."""
    _check_body(body)
    if end_jd <= start_jd:
        raise IngressError("end must be after start")
    step = _scan_step(body)
    if (end_jd - start_jd) / step > MAX_SCAN_SAMPLES:
        raise IngressError(
            f"range too long for {body}: at most {MAX_SCAN_SAMPLES * step:.0f} days")

    def sign(jd):
        return _sign_index(jd, body, mode, ayanamsa, lat, lon)

    out: List[Dict] = []
    t0, s0 = start_jd, sign(start_jd)
    while t0 < end_jd:
        t1 = min(t0 + step, end_jd)
        s1 = sign(t1)
        if s1 != s0:
            lo, hi = t0, t1
            while hi - lo > _BISECT_DAYS:
                mid = (lo + hi) / 2.0
                if sign(mid) == s0:
                    lo = mid
                else:
                    hi = mid
            first = _first_second(lo, s0, sign)
            if first > end_jd:      # its first whole second falls after the span
                t0, s0 = t1, s1
                continue
            out.append({"body": body, "jd": first,
                        "from_index": s0, "to_index": s1,
                        "retrograde": (s1 - s0) % 12 == 11})
        t0, s0 = t1, s1
    return out


def body_track(start_jd: float, end_jd: float, step_days: float, body: str, *,
               mode: str, ayanamsa: int, lat: float = 0.0,
               lon: float = 0.0) -> List[Dict]:
    """Positions of ``body`` from start to end (both included) every
    ``step_days``. Each sample: jd, longitude, sign_index, in_sign_degree,
    nakshatra, nakshatra_pada, speed, retrograde (the Chart planet's values,
    ``core.capabilities.chart.planet_snapshot``)."""
    from core.capabilities.chart import planet_snapshot
    _check_body(body)
    if end_jd < start_jd:
        raise IngressError("end must not be before start")
    if step_days <= 0:
        raise IngressError("step must be positive")
    count = int((end_jd - start_jd) / step_days + 1e-9) + 1
    times = [start_jd + i * step_days for i in range(count)]
    if end_jd - times[-1] > 1.0 / 86400.0:     # the end is always a sample
        times.append(end_jd)
    if len(times) > MAX_TRACK_SAMPLES:
        raise IngressError(f"too many samples ({len(times)}); at most {MAX_TRACK_SAMPLES}")
    out = []
    for jd in times:
        snap = planet_snapshot(body, body_at(jd, body, mode=mode, ayanamsa=ayanamsa,
                                             lat=lat, lon=lon))
        out.append({"jd": jd, "longitude": snap["longitude"],
                    "sign_index": snap["sign_index"],
                    "in_sign_degree": snap["in_sign_degree"],
                    "nakshatra": snap["nakshatra"],
                    "nakshatra_pada": snap["nakshatra_pada"],
                    "speed": snap["speed"], "retrograde": snap["retrograde"]})
    return out


def sign_label(index: int, mode: str, use_western_names: bool,
               sign_language: str = "en") -> str:
    """The label the app shows for wheel ordinal ``index``."""
    from core.aditya_mode import displayed_sign_name
    return displayed_sign_name(index, mode, use_western_names, sign_language)


__all__ = ["BODIES", "IngressError", "MAX_SCAN_SAMPLES", "MAX_TRACK_SAMPLES",
           "body_at", "body_track", "find_ingresses", "sign_label"]
