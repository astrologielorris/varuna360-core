# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The text under each planet glyph on the charts (SPEC-PLM-001 v2, §12).

F11 cycles four modes: degrees in the sign, planet name, Human Design gate
(libaditya ``HDLongitude``, gate 1 where the Human Design page puts it) and
nakshatra (the nakshatra wheel's engine call and three letters). Gates and
nakshatras read the body's D1 position and its own chart context; one
``PlanetCaptions`` per draw does the per-chart work once. Qt-free.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

LABEL_KEY = "chart.planet_label"
LEGACY_NAMES_KEY = "chart.show_planet_names"   # bool, before the four modes
MODES = ("degrees", "names", "gates", "nakshatra")
DEFAULT_MODE = "degrees"
MODE_LABELS = {"degrees": "Degrees", "names": "Planet names",
               "gates": "Human Design gates", "nakshatra": "Nakshatras"}


def normalized(mode) -> str:
    return mode if mode in MODES else DEFAULT_MODE


def next_mode(mode) -> str:
    """The mode after ``mode`` in the F11 cycle."""
    return MODES[(MODES.index(normalized(mode)) + 1) % len(MODES)]


def saved_mode(get) -> str:
    """The mode from a settings getter (``settings.get``). A file from before
    the four modes has only the legacy flag: names when it was on."""
    mode = normalized(get(LABEL_KEY, DEFAULT_MODE))
    if mode == DEFAULT_MODE and get(LEGACY_NAMES_KEY, False) is True:
        return "names"
    return mode


def degree_text(deg_in_sign: float) -> str:
    """12.2 -> "12°12'": degrees and arcminutes in the sign, truncated like
    Kala. Counted in whole arcminutes, so a float just under a minute
    (12.2 - 12 = 0.19999...) never loses one; capped at 29°59'."""
    total = min(math.floor(deg_in_sign * 60 + 1e-7), 30 * 60 - 1)
    return f"{total // 60}°{total % 60:02d}'"


def _context_mode(ctx) -> str:
    """The zodiac mode a chart context was built in (``chart_factory``)."""
    from libaditya import swe
    from libaditya.objects.context import Circle
    if int(getattr(ctx, "sysflg", 0) or 0) & swe.FLG_SIDEREAL:
        return "sidereal"
    return "aditya" if ctx.circle == Circle.ADITYA else "tropical_classic"


def _hd_level():
    """The Human Design experience level (its stored or factory value);
    ``hd_frame_for`` reads anything but "advanced" as Beginner."""
    try:
        from managers.settings_manager import get_settings
        from core.hd_model import HD_EXPERIENCE_KEY
        return get_settings().get(HD_EXPERIENCE_KEY)
    except Exception:
        return None


def caption_key(mode):
    """What a cached drawing of ``mode`` captions depends on beyond the chart:
    gates also on the Human Design level (it moves gate 1)."""
    mode = normalized(mode)
    return (mode, _hd_level()) if mode == "gates" else mode


class _Frame:
    """What one chart context needs for gates and nakshatras, read once."""

    def __init__(self, ctx, hd_level):
        from core.hd_model import _apply_frame, hd_frame_for
        self.ctx = ctx
        self.jd, self.ayanamsa = ctx.timeJD.jd, ctx.ayanamsa
        mode = _context_mode(ctx)
        self.to_tropical = 0.0          # added to the chart's longitude
        if mode == "sidereal":
            from core.ayanamsa_offset import birth_ayanamsa_offset
            self.to_tropical = birth_ayanamsa_offset(self.jd, self.ayanamsa)
        frame = hd_frame_for(mode, hd_level)
        # the Human Design page's sidereal frame measures sidereal longitudes
        self.gate_shift = 0.0 if frame == "sidereal" else self.to_tropical
        # the Human Design page's own frame -> gate 1 anchor (only the anchor
        # is read here: the longitude above is already in the frame's zodiac)
        self.gate_ctx = _apply_frame(ctx, frame)


class PlanetCaptions:
    """The caption under each planet glyph, for one draw.

    ``text(name, planet, deg_in_sign)``: ``planet`` is the view's libaditya
    planet (natal, transit or overlay; rashi or varga, its ecliptic longitude
    is the D1 one) and carries its chart's context, so a transit ring gets
    its own moment and frame. ``deg_in_sign`` is the degree the view shows
    (varga-aware). The per-chart work is done once per context."""

    def __init__(self, mode, language="en"):
        self.mode = normalized(mode)
        self.language = language
        self._hd_level = False      # read once, on the first gate or nakshatra
        self._frames = {}

    @property
    def wide(self) -> bool:
        """True when the captions are names, wider than a degree."""
        return self.mode == "names"

    def text(self, name, planet, deg_in_sign) -> str:
        if self.mode == "names":
            from core.aditya_mode import get_planet_display_name
            return get_planet_display_name(self.language, name)
        if self.mode == "degrees":
            return degree_text(deg_in_sign)
        try:
            frame = self._frame(planet.context)
            lon = planet.ecliptic_longitude()
            if self.mode == "gates":
                from libaditya.hd.longitude import HDLongitude
                return str(HDLongitude((lon + frame.gate_shift) % 360,
                                       frame.gate_ctx).gate_number())
            from core.vimshottari_dasha import get_nakshatra_for_longitude
            from visualizations.wheel_constants import NAKSHATRA_ABBREV
            _, index = get_nakshatra_for_longitude(
                (lon + frame.to_tropical) % 360, frame.jd, ayanamsa=frame.ayanamsa)
            return NAKSHATRA_ABBREV[index]
        except Exception:
            return ""        # never a wrong caption; the glyph stays

    def _frame(self, ctx):
        frame = self._frames.get(id(ctx))
        if frame is None or frame.ctx is not ctx:
            if self._hd_level is False:
                self._hd_level = _hd_level()
            frame = self._frames[id(ctx)] = _Frame(ctx, self._hd_level)
        return frame


@dataclass(frozen=True)
class CaptionSet:
    """The captions of one South Indian snapshot, by planet name."""
    mode: str = DEFAULT_MODE
    texts: dict = field(default_factory=dict)

    @property
    def wide(self) -> bool:
        return self.mode == "names"


def caption_set(mode, language, records, planets) -> CaptionSet:
    """The captions of South Indian render records (``name``, ``degree``: the
    degree shown), the libaditya planets looked up by name."""
    captions = PlanetCaptions(mode, language)
    return CaptionSet(captions.mode, {r.name: captions.text(r.name, planets[r.name], r.degree)
                                      for r in records})

