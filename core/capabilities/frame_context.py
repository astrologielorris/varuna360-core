# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The chart frame and sign label set a moment CLI prints in, as one value.

The event CLIs (eclipses, Saros, moon phases, conjunctions, the eclipse and
Lunar New Year chart generators) build charts at event moments and print the
planets' signs. ``FrameContext`` carries what they need, passed explicitly to
every helper instead of module-global state:

    frame = FrameContext.from_frame(ChartFrame.resolve(cfg.view), language)
    chart, positions = frame.positions_at(jd, lat, lon)

A library caller that passes no frame gets ``LIBRARY_FRAME``: aditya mode,
chart ayanamsa 1, Campanus houses, and the chart's own engine sign names
(``use_western=None``), the documented default of those helpers.

Qt-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

PLANET_NAMES = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
                "Rahu", "Ketu")


@dataclass(frozen=True)
class FrameContext:
    mode: str = "aditya"
    ayanamsa: int = 1
    hsys: str = "C"
    # None = the chart's own engine sign names; True/False = Western/Aditya
    # labels (the ordinal is kept, only the label set changes).
    use_western: Optional[bool] = None
    language: str = "en"        # the sign-name language of the labels

    @classmethod
    def from_frame(cls, frame, language: str = "en") -> "FrameContext":
        """From a resolved ``ChartFrame`` (``ChartFrame.resolve``)."""
        return cls(mode=frame.mode, ayanamsa=frame.ayanamsa_id,
                   hsys=frame.house_system_code,
                   use_western=frame.use_western_names, language=language)

    def chart_kwargs(self) -> Dict[str, object]:
        """``mode``/``ayanamsa``/``hsys`` for the chart builders."""
        return {"mode": self.mode, "ayanamsa": self.ayanamsa, "hsys": self.hsys}

    def label(self, name):
        """Engine sign name -> the label set on screen (identity when unset)."""
        if self.use_western is None:
            return name
        from core.capabilities.cli_settings import relabel_sign_name
        return relabel_sign_name(name, self.use_western, self.language)

    def chart_at(self, jd: float, lat: float = 0.0, lon: float = 0.0):
        from core.chart_factory import build_chart_from_params
        return build_chart_from_params(jd=jd, lat=lat, lon=lon, **self.chart_kwargs())

    def positions_at(self, jd: float, lat: float = 0.0, lon: float = 0.0,
                     include_ascendant: Optional[bool] = None) -> Tuple[object, dict]:
        """The chart at the event moment ``jd`` (truncated to whole seconds,
        as the event tables always did) and the planet-position map
        ``{name: {sign, degrees, minutes, longitude}}``. ``include_ascendant``
        None = present when a location is given."""
        from core.time_utils import julday, revjul
        year, month, day, hour_frac = revjul(jd)
        hour = int(hour_frac)
        minute = int((hour_frac - hour) * 60)
        second = int(((hour_frac - hour) * 60 - minute) * 60)
        hour_decimal = hour + minute / 60.0 + second / 3600.0
        chart = self.chart_at(julday(year, month, day, hour_decimal), lat, lon)
        if include_ascendant is None:
            include_ascendant = (lat != 0.0 or lon != 0.0)
        names = list(PLANET_NAMES) + (["Ascendant"] if include_ascendant else [])
        return chart, self.positions(chart, names)

    def positions(self, chart, names) -> dict:
        """``{name: {sign, degrees, minutes, longitude}}`` for the bodies of
        ``names`` the chart has, signs in this label set."""
        from core.chart_helpers import (
            get_planet_decimal_degrees, get_planet_in_sign_longitude,
            get_planet_sign_name, has_planet)
        result = {}
        for planet_name in names:
            if has_planet(chart, planet_name):
                in_sign = get_planet_in_sign_longitude(chart, planet_name)
                result[planet_name] = {
                    "sign": self.label(get_planet_sign_name(chart, planet_name, default="?")),
                    "degrees": int(in_sign),
                    "minutes": int((in_sign % 1) * 60),
                    "longitude": round(get_planet_decimal_degrees(chart, planet_name), 2),
                }
        return result


LIBRARY_FRAME = FrameContext()


def frame_or_default(frame: Optional[FrameContext]) -> FrameContext:
    return LIBRARY_FRAME if frame is None else frame
