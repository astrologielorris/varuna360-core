# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Microphone level and the "no voice" watch (SPEC-REC-001 §4.9;
SPEC-RECMETER-MOBILE-001 §3, desktop translation).

The microphone branch (before mixing) goes through ``astats`` every 250 ms
and ``ametadata=print`` logs two lines per window on stderr:
``[Parsed_ametadata_7 @ 0x..] frame:3    pts:36000   pts_time:0.75`` then
``[Parsed_ametadata_7 @ 0x..] lavfi.astats.Overall.RMS_level=-41.2``.
The level is RMS in dBFS, as on mobile.
"""
from __future__ import annotations

import re
from typing import Optional

_PTS = re.compile(r"\bpts_time:\s*(-?[0-9.]+)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[0-9.]+|-inf|inf|nan)")

VOICE_LEVEL = -40.0          # a window louder than this counts as voice
QUIET_SECONDS = 30.0         # mobile: 30 s
VOICE_SHARE = 0.10           # mobile: fewer than 10 % of windows


class LevelParser:
    """Stateful: a ``pts_time`` line, then its ``RMS_level`` line. ``feed``
    returns (t, dBFS) when a level line completes a pair, else None; a line
    that is neither returns None and is left to the caller's log."""

    def __init__(self):
        self._t: Optional[float] = None

    @staticmethod
    def is_meter_line(line: str) -> bool:
        return "Parsed_ametadata" in line

    def feed(self, line: str):
        m = _PTS.search(line)
        if m:
            self._t = float(m.group(1))
            return None
        m = _RMS.search(line)
        if m and self._t is not None:
            raw = m.group(1)
            level = -120.0 if raw in ("-inf", "nan") else min(0.0, float(raw)) if raw != "inf" else 0.0
            t, self._t = self._t, None
            return t, level
        return None


def meter_percent(level: float) -> int:
    """-60 empty, -10 full (mobile scale)."""
    return int(max(0, min(100, (level + 60.0) * 2)))


class QuietWatch:
    """Windows of 1 s; quiet when, over the last 30 s, fewer than 10 % passed
    the voice level. Clears as soon as a voice window arrives."""

    def __init__(self):
        self._windows = []           # (second, loud) per whole second
        self._current: Optional[int] = None
        self._current_peak = -120.0

    def feed(self, t: float, level: float) -> None:
        second = int(t)
        if self._current is None:
            self._current = second
        if second != self._current:
            self._windows.append((self._current, self._current_peak > VOICE_LEVEL))
            self._windows = self._windows[-int(QUIET_SECONDS):]
            self._current, self._current_peak = second, -120.0
        self._current_peak = max(self._current_peak, level)

    @property
    def quiet(self) -> bool:
        if len(self._windows) < int(QUIET_SECONDS):
            return False
        if self._windows[-1][1]:
            return False
        loud = sum(1 for _, v in self._windows if v)
        return loud < VOICE_SHARE * len(self._windows)
