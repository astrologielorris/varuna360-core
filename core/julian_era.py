# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Civil times before 1583, calendar-exact (SPEC-LMCP-001 D-21).

``datetime`` is proleptic Gregorian: it cannot hold the Julian date the app
reads before the reform (1500-02-29 raises) and it skips Julian Feb 29 when a
time zone moves 1500-03-01 00:30 back. ``core.time_utils`` hands every civil
time before ``JULIAN_ERA_END`` (and BCE) to ``shift_civil``, which moves it
through the Julian Day: Julian before 1582-10-15, Gregorian from then, the
reform day included, any number of days.
"""
from __future__ import annotations

from libaditya import swe

# Before this date a civil time is shifted here, not by datetime; no time
# zone had standard time yet, so it is also the founding mean-time era.
JULIAN_ERA_END = (1583, 1, 1)
GREGORIAN_REFORM_JD = 2299160.5


def _calendar(year, month, day):
    return swe.JUL_CAL if (year, month, day) < (1582, 10, 15) else swe.GREG_CAL


def shift_civil(year, month, day, hour, minute, second, delta_seconds):
    """(year, month, day, hour, minute, second) moved by ``delta_seconds``."""
    jd0 = swe.julday(year, month, day, 0.0, _calendar(year, month, day))
    total = hour * 3600 + minute * 60 + second + int(round(delta_seconds))
    days, secs = divmod(total, 86400)
    jd = jd0 + days + 0.25                 # a quarter day in: no rounding at midnight
    cal = swe.JUL_CAL if jd < GREGORIAN_REFORM_JD else swe.GREG_CAL
    y, m, d, _h = swe.revjul(jd, cal)
    return (int(y), int(m), int(d), secs // 3600, (secs % 3600) // 60, secs % 60)
