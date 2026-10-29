# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Planet dignity for the chart overlay and the VARGA panel (SPEC-DIG-001, td-m6xyo). Qt-free.

Each of the seven classical planets gets its dignity in the varga the chart (or the
panel) shows, from libaditya's own engine (``Varga.dignities()``, the same call as
``AI_tools.AI_main_function.dignities_in_vargas``). A Debilitated planet is split by
its NATURAL (naisargika) relationship to the lord of the sign it occupies in that
varga (libaditya ``Planet.natural_relationship_from``): friend, neutral or enemy.

The overlay ("Burnish Clear") is drawn in ``apps/widgets/dignity_overlay_items.py``
from the parameters here: ``SHEEN`` per step and the tapered crescent maths.
"""
from __future__ import annotations

import math
import weakref
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from libaditya.calc.avasthas import KARAKAS
from libaditya.custom_ayanamsa import get_custom_ayanamsa, on_change as _on_custom_ayanamsa

KEY_MODE = "chart.planet_glow_mode"     # shared with core.planet_strength_glow
DIGNITY = "dignity"
PLANETS = tuple(KARAKAS)    # engine ids, Sun..Saturn (display text: varga_panel.py, i18n)
ABBR = {p: p[:2] for p in PLANETS}          # "Su", "Mo", ... (the CLI table columns)

FRIEND, NEUTRAL, ENEMY = "friend", "neutral", "enemy"
_RELATION_KIND = {"F": FRIEND, "N": NEUTRAL, "E": ENEMY}
# the overlay step of a Debilitated planet, by kind (DB = Burnish Clear's ash look)
_KIND_OF_DB_STEP = {"DBF": FRIEND, "DBN": NEUTRAL, "DB": ENEMY}
DB_STEP = {kind: step for step, kind in _KIND_OF_DB_STEP.items()}


def dignity_on(get: Callable) -> bool:
    """The overlay is on: ``chart.planet_glow_mode`` is "dignity"."""
    from core import settings_registry as registry
    return get(KEY_MODE, registry.default(KEY_MODE)) == DIGNITY


def db_kind(relationship) -> Optional[str]:
    """libaditya's natural relationship code ("F", "N", "E") -> the DB kind.
    Anything else (own sign: None / "OH") is no kind."""
    return _RELATION_KIND.get(relationship)


def step_of(code: str, kind: Optional[str]) -> str:
    """The overlay step: the code, or DBF / DBN / DB (unknown kind: DB) when Debilitated."""
    return DB_STEP.get(kind, "DB") if code == "DB" else code


@dataclass(frozen=True)
class PlanetDignity:
    planet: str
    code: str                 # EX .. DB
    kind: Optional[str]       # DB only: friend / neutral / enemy
    sign_index: int           # 0..11 in the varga
    degree: float             # degrees within the varga sign
    lord: str                 # the lord of that sign

    @property
    def step(self) -> str:
        return step_of(self.code, self.kind)


def _varga(chart, lib_code):
    from libaditya.calc.varga import Varga
    return Varga(chart.context, amsha=1 if lib_code in (None, 1) else lib_code)


_BUILT = weakref.WeakKeyDictionary()   # chart -> rows per varga: ONE build for 3 views + panel
_on_custom_ayanamsa(_BUILT.clear)      # a new custom ayanamsa (id 255) changes every build


def varga_dignities(chart, lib_code=None) -> List[PlanetDignity]:
    """The seven classical planets' dignities in the varga ``lib_code`` (libaditya
    amsha code; None or 1 = the rashi), in natural order Sun..Saturn."""
    rashi, ctx, memo = lib_code in (None, 1), chart.context, _BUILT.setdefault(chart, {})
    key = (1 if rashi else lib_code, getattr(ctx.timeJD, "jd", None), ctx.ayanamsa, ctx.circle,
           ctx.sysflg, ctx.rashi_temporary_friendships)   # all the build reads from the context
    key += (get_custom_ayanamsa(),) if ctx.ayanamsa == 255 else ()
    if key not in memo:
        memo[key] = tuple(dignities_of_varga(_varga(chart, lib_code), rashi))
    return list(memo[key])


def dignities_of_varga(varga, rashi=False) -> List[PlanetDignity]:
    """``varga_dignities`` for a libaditya ``Varga`` already built (the table
    builder reuses its own)."""
    codes = list(varga.dignities())
    karakas = varga.planets().karakas()
    out = []
    for planet, code in zip(PLANETS, codes):
        p = karakas[planet]
        lord_name = p.lord()
        lord = karakas.get(lord_name)
        kind = None
        if code == "DB" and lord is not None:
            kind = db_kind(p.natural_relationship_from(lord))
        try:
            degree = float(p.real_in_sign_longitude() if rashi else p.amsha_raw_in_sign_longitude())
        except Exception:
            degree = float(p.in_sign_longitude())
        out.append(PlanetDignity(planet, code, kind, int(p.sign()) - 1, degree, lord_name))
    return out


def overlay_steps(chart, lib_code=None) -> Dict[str, str]:
    """``{planet: step}`` for the overlay of the varga ``lib_code``."""
    return {d.planet: d.step for d in varga_dignities(chart, lib_code)}


def format_degree(degree: float) -> str:
    """``3°15'`` (degrees and arc minutes, truncated like the chart labels)."""
    d = int(degree)
    m = min(59, int((degree - d) * 60 + 1e-9))
    return f"{d}°{m:02d}'"


# --------------------------------------------------------------------------
# Burnish Clear drawing parameters (SPEC-DIG-001 §4.1), in SI mockup pixels:
# radius 44 at s = 1. Colours raw (desaturated once at paint, SPEC-SAT-001).
SHEEN_R = 44.0
CENTRE = -135.0             # the light comes from the upper left (screen angles, y down)
SUNK_CENTRE = 168.0         # DB-friend / DB-neutral: the light has sunk to the lower left
SUNK_SPAN = 48.0
SHEEN_PER_REF = 1.08        # R / r_ref on the South Indian views (mockup 44 px vs its icons)
WHEEL_FACTOR = 1.10         # the mockup's wheel scale 0.82 against its smaller wheel glyphs
AVASTHA_SLOT = (-40.0, 62.0, 9.0)  # angle, radius, half size: kept free (INV-6)

SHEEN = {
    "EX": dict(span=240, W=8.6, tint="#D3DCFF", key="#303878", op=1.0, spine=.78, dbl=True,
               star=10, star2=True, rim=True, sweep=True),
    "MT": dict(span=207, W=7.4, tint="#EBCDF6", key="#4A1A6B", op=1.0, spine=.62, star=7,
               rim=True, sweep=True),
    "OH": dict(span=174, W=6.2, tint="#C9E4FB", key="#14406B", op=1.0, spine=.5, dot=True),
    "GF": dict(span=141, W=5.0, tint="#CDEFCD", key="#1A5C2A", op=1.0, spine=.36),
    "F": dict(span=108, W=3.8, tint="#DCEFD8", key="#2A4D2A", op=.95),
    "N": dict(span=52, W=2.4, tint="#E4E4EA", key="#3A3A42", op=.9),
    "E": dict(matte=True, span=130, band="#C9A46A", dot="#F2D196", key="#4A3508",
              cracks=(-165,), blots=2, gaps=()),
    "GE": dict(matte=True, span=140, band="#B5582A", dot="#EE9B70", key="#4A220A",
               cracks=(-178, -100), blots=4, gaps=((-162, -150), (-118, -108))),
    "DB": dict(ruin=True, ash="#564844", dark="#1E0A0A", grey_r=34.0, grey_level=0.80),
    # Sunken Sheen with the colours SWAPPED (Lorris 2026-10-13): friend = white light
    "DBF": dict(sunk=True, W=3.6, key="#3A4656",
                grad=("#FFFFFF", "#F3F6FA", "#D8E0EA"),
                glow=("#FFFFFF", .22, 13.0), glow2=("#F4F8FF", .35, 7.0), spark="#FFFFFF"),
    # neutral = yellow / ochre, unlit, at rest
    "DBN": dict(sunk_line=True, key="#5A3E08", key_alpha=.70, key_w=3.2,
                line="#F2C14E", line_w=1.5),
}
STEPS = tuple(SHEEN)         # every overlay step: EX .. GE, then DB, DBF, DBN

# animation periods, seconds
SWEEP_PERIOD = 9.0
GLINT_PERIOD = 5.5
FLAKE_PERIOD = 7.0
EMBER_PERIOD = 6.0
SPARK_PERIOD = 6.5


def sheen_scale(r_ref: float, wheel: bool = False) -> float:
    """``s`` for a view: its reference half size ``r_ref`` (the Ember Aura's) to
    the mockup's 44 px sheen radius."""
    s = max(r_ref, 1.0) * SHEEN_PER_REF / SHEEN_R
    return s * WHEEL_FACTOR if wheel else s


def polar(cx: float, cy: float, r: float, a_deg: float) -> Tuple[float, float]:
    a = math.radians(a_deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def crescent_points(cx, cy, R, W, a0, a1, n=40):
    """The tapered crescent polygon (width ``W sin(pi t)``): the outer edge from
    ``a0`` to ``a1`` then the inner edge back."""
    outer, inner = [], []
    for k in range(n + 1):
        t = k / n
        a = a0 + (a1 - a0) * t
        w = W * math.sin(math.pi * t)
        outer.append(polar(cx, cy, R + w / 2, a))
        inner.append(polar(cx, cy, R - w / 2, a))
    return outer + inner[::-1]


def segments(a0, a1, gaps=()):
    """``[a0, a1]`` split around the ``gaps``."""
    out = [(a0, a1)]
    for g0, g1 in gaps:
        nxt = []
        for b0, b1 in out:
            if g1 <= b0 or g0 >= b1:
                nxt.append((b0, b1))
                continue
            if g0 > b0:
                nxt.append((b0, g0))
            if g1 < b1:
                nxt.append((g1, b1))
        out = nxt
    return out


def in_gap(a, gaps=()) -> bool:
    return any(g0 <= a <= g1 for g0, g1 in gaps)


def rng(seed: int) -> Callable[[], float]:
    """The mockup's mulberry32: a stable random stream per planet."""
    state = [seed & 0xFFFFFFFF]

    def nxt():
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return nxt


def planet_seed(planet: str) -> int:
    """A fixed seed per planet (the marks do not jump between redraws)."""
    return 11 + 97 * (PLANETS.index(planet) + 1) if planet in PLANETS else 11


def crack_points(cx, cy, a, r0, r1, R, n=4):
    """A jagged crack from ``r0`` to ``r1`` along angle ``a`` (mockup crackD)."""
    pts = []
    for i in range(n + 1):
        r = r0 + (r1 - r0) * i / n
        j = (R() - .5) * 14 if 0 < i < n else 0.0
        pts.append(polar(cx, cy, r, a + j / (r / 40.0)))
    return pts
