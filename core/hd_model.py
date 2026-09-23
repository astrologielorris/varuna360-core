# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Pure Human Design model (no GUI deps) — WI-2, SPEC-HD-001.

``build_hd_model(context, frame)`` turns a libaditya ``EphContext`` into one
plain, JSON-serializable dict: the frozen HDModel field contract
(SPEC-HD-001, HDMODEL_CONTRACT v1.0).
The GUI view, the ``show_human_design.py --json`` CLI and the remote ``read_hd``
command all consume THIS function's output, so the three surfaces cannot diverge
(Rule 24; pre-mortem F7 = the byte-identical-JSON DONE gate).

Design decisions baked in (pre-mortem 2026-08-29):
- F1: ``design_datetime`` is the instant the DESIGN planets are computed at
  (``Bodygraph._unconscious_context.timeJD``), never the legacy tropical
  ``calculate_design_jd``. It is therefore consistent with the design activations
  under every frame.
- F3: centres are exposed in the GEOMETRY vocabulary (``g``, not the engine's
  ``ji``); the rename happens ONCE here so the view indexes ``CENTER_SHAPE``
  directly.
- F9: ``frame`` is validated against ``VALID_FRAMES`` with a Standard default.

Nothing here imports Qt.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import libaditya.constants as _const
from libaditya.charts.bodygraph import Bodygraph
from libaditya.hd import constants as hdc
from libaditya.hd import definition as hddef
from libaditya.objects.context import EphContext
from libaditya.objects.julian_day import JulianDay
from libaditya.objects.location import Location

SCHEMA_VERSION = "hd-model-1"

#: The three frames the app offers (main-zodiac parity). Standard is the locked
#: default; the app bakes in no opinion about which is "true".
VALID_FRAMES = ("standard", "aditya", "sidereal")
DEFAULT_FRAME = "standard"

_STANDARD_GATE_ONE = 223.25          # Josh's ecliptic anchor (13:15 tropical Scorpio)
_ADITYA_GATE_ONE = 193.25            # Standard - 30 (Aditya shift)

#: hd13 engine key -> contract planet key, in HD row order. Chiron is appended
#: separately as the 14th body (activates no gate).
_PLANET_ORDER = (
    ("Sun", "sun"), ("Earth", "earth"), ("Moon", "moon"),
    ("Rahu", "north_node"), ("Ketu", "south_node"),
    ("Mercury", "mercury"), ("Venus", "venus"), ("Mars", "mars"),
    ("Jupiter", "jupiter"), ("Saturn", "saturn"),
    ("Uranus", "uranus"), ("Neptune", "neptune"), ("Pluto", "pluto"),
)

#: geometry <-> engine centre key (only the G centre differs: engine "ji").
_ENGINE_TO_GEOM = {"ji": "g"}
_GEOM_TO_ENGINE = {"g": "ji"}
#: canonical centre order for the exposed dict (geometry vocabulary).
CENTER_ORDER = ("head", "ajna", "throat", "g", "will",
                "spleen", "solar", "sacral", "root")

#: the four motor centres (geometry keys). Solar = Solar Plexus.
MOTORS = frozenset({"sacral", "solar", "will", "root"})

_STRATEGY = {
    "Manifestor": "Inform before acting",
    "Generator": "Wait to respond",
    "Manifesting Generator": "Respond, then inform",
    "Projector": "Wait for the invitation",
    "Reflector": "Wait a lunar cycle",
}
_DEFINITION_NAME = {0: "No Definition", 1: "Single", 2: "Split",
                    3: "Triple", 4: "Quadruple"}

# Profile line archetype names (HDMODEL contract v1.1, additive). Keyed by the
# HD line number 1-6 the Sun falls on. profile_name pairs the Personality Sun
# line name with the Design Sun line name, in the same order as ``profile``
# ("4/2" -> "Opportunist · Hermit"), so a view can render "4/2 (Opportunist · Hermit)".
_PROFILE_LINE_NAME = {1: "Investigator", 2: "Hermit", 3: "Martyr",
                      4: "Opportunist", 5: "Heretic", 6: "Role Model"}

# --- Incarnation cross naming (HDMODEL contract v1.2, additive) -------------
# The cross is fully determined by (Personality Sun gate, geometry angle); the
# angle is fixed by the profile. Name themes live in the shipped reference table
# core/data/hd_crosses.json (see its own _source/_normalized provenance). Full
# label is "<Angle> Cross of <theme>", short is "<CODE> of <theme>".
_ANGLE_OF_PROFILE = {
    (1, 3): "right", (1, 4): "right", (2, 4): "right", (2, 5): "right",
    (3, 5): "right", (3, 6): "right", (4, 6): "right",
    (4, 1): "juxtaposition",
    (5, 1): "left", (5, 2): "left", (6, 2): "left", (6, 3): "left",
}
_ANGLE_LABEL = {"right": ("Right Angle Cross of", "RAX of"),
                "left": ("Left Angle Cross of", "LAX of"),
                "juxtaposition": ("Juxtaposition Cross of", "JXT of")}
_ANGLE_TABLE_KEY = {"right": "right_angle", "left": "left_angle",
                    "juxtaposition": "juxtaposition"}

_CROSSES_CACHE = None


def _load_crosses():
    """Load and memoize the incarnation-cross theme table. Never raises: a
    missing/corrupt asset yields {} and callers fall back to the gate string."""
    global _CROSSES_CACHE
    if _CROSSES_CACHE is None:
        try:
            path = Path(__file__).resolve().parent / "data" / "hd_crosses.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            # Valid JSON with the wrong ROOT type (a bare list/string from a
            # corrupted save) would make the .get() in _incarnation_cross raise;
            # coerce anything but an object to {} so the fallback still holds.
            _CROSSES_CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _CROSSES_CACHE = {}
    return _CROSSES_CACHE


def _incarnation_cross(p_line, d_line, psun, pearth, dsun, dearth):
    """Build the incarnation_cross dict. ``label``/``short`` carry the named
    cross when (profile-angle, Personality Sun gate) resolves in the table;
    otherwise they fall back to the gate quartet string and ``angle``/``named``
    report the miss. Never raises — an unknown profile or gate must not break
    the model for any of the four surfaces."""
    gates = [psun, pearth, dsun, dearth]
    fallback = f"Gates {psun}/{pearth} | {dsun}/{dearth}"
    angle = _ANGLE_OF_PROFILE.get((p_line, d_line))
    theme = None
    if angle is not None:
        table = _load_crosses().get(_ANGLE_TABLE_KEY[angle], {})
        theme = table.get(str(psun))
    if angle is None or not theme:
        return {"label": fallback, "short": fallback, "angle": angle,
                "named": False, "gates": gates}
    full_pre, short_pre = _ANGLE_LABEL[angle]
    return {"label": f"{full_pre} {theme}", "short": f"{short_pre} {theme}",
            "angle": angle, "named": True, "gates": gates}


def _geom(center: str) -> str:
    return _ENGINE_TO_GEOM.get(center, center)


class HDModelError(ValueError):
    """Raised for invalid inputs (e.g. an unknown frame)."""


# --------------------------------------------------------------------------- frames

def _apply_frame(context: EphContext, frame: str) -> EphContext:
    """Return ``context`` adjusted for ``frame``. Only the gate mapping changes;
    the layout never does."""
    # sysflg is forced on EVERY branch, not only sidereal: an incoming context
    # may already carry sysflg=SID (a sidereal chart in WI-6), and standard/aditya
    # are BOTH tropical (they differ only by the gate-1 anchor). Leaving sysflg
    # untouched would compute a "standard" frame against sidereal longitudes while
    # reporting frame=standard/gate_one=223.25 (review 2026-08-29). _apply_frame
    # is therefore a total normalisation, order-independent of the input context.
    if frame == "standard":
        return replace(context, sysflg=_const.ECL, hd_gate_one=_STANDARD_GATE_ONE)
    if frame == "aditya":
        return replace(context, sysflg=_const.ECL, hd_gate_one=_ADITYA_GATE_ONE)
    if frame == "sidereal":
        # sidereal longitudes, gate 1 kept at the Standard ecliptic anchor;
        # ayanamsa carried from the chart's own zodiac settings.
        return replace(context, sysflg=_const.SID, hd_gate_one=_STANDARD_GATE_ONE)
    raise HDModelError(f"unknown frame {frame!r}; expected one of {VALID_FRAMES}")


# --------------------------------------------------------------------------- helpers

def hd_context_from_birth(jd, lat, lon, utcoffset=0.0, alt=0.0,
                          name="", ayanamsa=98) -> EphContext:
    """Build the base ``EphContext`` for a birth moment. Used by the CLI and by
    tests; the GUI builds an equivalent context from the loaded chart (WI-6)."""
    return EphContext(
        name=name,
        timeJD=JulianDay(jd, utcoffset=utcoffset),
        location=Location(lat=lat, long=lon, alt=alt, placename=name,
                          utcoffset=utcoffset),
        ayanamsa=ayanamsa,
    )


def _iso_utc(time_jd: JulianDay) -> str:
    """ISO-8601 UTC (seconds resolution) for a JulianDay. ``.datetime`` is
    ``swe.revjul(jd, calendar_flag)`` -> (year, month, day, hour_decimal).

    Rollover is done with datetime+timedelta so a near-midnight fractional hour
    (common in the design date, which is an iterative 88-degree solve) carries
    correctly into the next day instead of emitting an invalid ``T24:00:00Z`` on
    the wrong calendar day (review 2026-08-29). The proleptic-Gregorian container
    is used only to format y/m/d/h:m:s; HD charts are modern so the pre-1582
    Julian-calendar boundary is not in play."""
    year, month, day, hour = time_jd.datetime
    base = datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    dt = base + timedelta(seconds=round(hour * 3600.0))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(planet_obj, planet_key, available, activates):
    if not available:
        return {"planet": planet_key, "available": False, "activates": activates,
                "gate": None, "line": None, "color": None, "tone": None,
                "base": None, "elapsed_pct": None}
    hd = planet_obj.hd()
    return {"planet": planet_key, "available": True, "activates": activates,
            "gate": hd.gate_number(), "line": hd.line(), "color": hd.color(),
            "tone": hd.tone(), "base": hd.base(), "elapsed_pct": hd.gate_elapsed()}


def _side_rows(planets):
    """Rows for one side (personality or design): the 13 hd bodies + Chiron.
    Chiron is ``available=False`` outside its ephemeris window (never a missing
    key) and always ``activates=False``."""
    hd13 = planets.hd13()
    rows = [_row(hd13[eng], key, available=True, activates=True)
            for eng, key in _PLANET_ORDER]
    chiron_available = "Chiron" in planets.planets()
    chiron_obj = planets.chiron() if chiron_available else None
    rows.append(_row(chiron_obj, "chiron",
                     available=chiron_available, activates=False))
    return rows


def _gate_numbers(planets) -> set:
    """The 13 activating gate numbers on one side (Chiron excluded)."""
    hd13 = planets.hd13()
    return {hd13[eng].hd().gate_number() for eng, _ in _PLANET_ORDER}


def _center_adjacency(active_gates):
    """Adjacency map (geometry centre keys) built from DEFINED channels only,
    plus the set of defined centres."""
    adj = {}
    for lo, hi in hddef.defined_channels(active_gates):
        a, b = hdc.channels[(lo, hi)]
        a, b = _geom(a), _geom(b)
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    defined = set(adj)  # a centre is defined iff a defined channel touches it
    return adj, defined


def _connected(adj, start, goal, defined) -> bool:
    if start not in defined or goal not in defined:
        return False
    if start == goal:
        return True
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, ()):
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _components(adj, defined) -> int:
    seen = set()
    count = 0
    for node in defined:
        if node in seen:
            continue
        count += 1
        stack = [node]
        seen.add(node)
        while stack:
            cur = stack.pop()
            for nxt in adj.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return count


def _hd_type(centers, m2t) -> str:
    sacral = centers["sacral"]
    if sacral and m2t:
        return "Manifesting Generator"
    if sacral:
        return "Generator"
    if (not sacral) and m2t:
        return "Manifestor"
    if any(centers.values()):
        return "Projector"
    return "Reflector"


def _authority(hd_type, centers, adj, defined, channel_defined, m2t) -> str:
    # first-match, per SPEC-HD-001 / plan §2. Never assign Mental to a Reflector.
    if centers["solar"]:
        return "Emotional"
    if centers["sacral"]:
        return "Sacral"
    if centers["spleen"]:
        return "Splenic"
    if hd_type == "Manifestor" and _connected(adj, "will", "throat", defined):
        return "Ego Manifested"
    if hd_type == "Projector" and channel_defined(25, 51) and not m2t:
        return "Ego Projected"
    if hd_type == "Projector" and _connected(adj, "g", "throat", defined):
        return "Self-Projected"
    if hd_type == "Projector":
        return "Mental"
    if hd_type == "Reflector":
        return "Lunar"
    # A Manifestor whose motor path reaches Throat without touching an authority
    # centre does not exist in the topology, but keep an explicit fallback.
    return "Ego Manifested"


# --------------------------------------------------------------------------- traits

def hd_traits(active_gates) -> dict:
    """Derive centres / type / strategy / authority / definition from a set of
    activating gate numbers (personality + design, Chiron excluded). Pure and
    context-free so the decision tables are testable directly. Centre keys are
    the geometry vocabulary (``g``, not ``ji``)."""
    active = set(active_gates)
    eng_centers = hddef.defined_centers(active)
    centers = {name: bool(eng_centers[_GEOM_TO_ENGINE.get(name, name)])
               for name in CENTER_ORDER}
    adj, defined = _center_adjacency(active)

    def channel_defined(a: int, b: int) -> bool:
        lo, hi = (a, b) if a < b else (b, a)
        return lo in active and hi in active

    m2t = centers["throat"] and any(
        _connected(adj, motor, "throat", defined)
        for motor in MOTORS if centers[motor])

    hd_type = _hd_type(centers, m2t)
    authority = _authority(hd_type, centers, adj, defined, channel_defined, m2t)
    definition = _DEFINITION_NAME.get(_components(adj, defined), "Quadruple")
    return {
        "centers": centers,
        "type": hd_type,
        "strategy": _STRATEGY[hd_type],
        "authority": authority,
        "definition": definition,
        "motor_to_throat": m2t,
    }


# --------------------------------------------------------------------------- main

def build_hd_model(context: EphContext, frame: str = DEFAULT_FRAME) -> dict:
    """Build the HDModel dict (contract v1.0) for ``context`` in ``frame``."""
    if frame not in VALID_FRAMES:
        raise HDModelError(
            f"unknown frame {frame!r}; expected one of {VALID_FRAMES}")

    ctx = _apply_frame(context, frame)
    bg = Bodygraph(context=ctx)
    conscious = bg.conscious_planets()
    unconscious = bg.unconscious_planets()

    p_gates = _gate_numbers(conscious)
    d_gates = _gate_numbers(unconscious)
    active = p_gates | d_gates

    def gate_state(gate: int) -> str:
        in_p, in_d = gate in p_gates, gate in d_gates
        if in_p and in_d:
            return "both"
        if in_p:
            return "personality"
        if in_d:
            return "design"
        return "none"

    gates = {str(g): gate_state(g) for g in range(1, 65)}

    channels = {}
    for lo, hi in sorted(hdc.channels):
        channels[f"{lo}-{hi}"] = {
            "defined": lo in active and hi in active,
            "low_gate_state": gate_state(lo),
            "high_gate_state": gate_state(hi),
        }

    traits = hd_traits(active)
    centers = traits["centers"]

    c_hd13 = conscious.hd13()
    u_hd13 = unconscious.hd13()
    p_sun_line = c_hd13["Sun"].hd().line()
    d_sun_line = u_hd13["Sun"].hd().line()
    psun, pearth = c_hd13["Sun"].hd().gate_number(), c_hd13["Earth"].hd().gate_number()
    dsun, dearth = u_hd13["Sun"].hd().gate_number(), u_hd13["Earth"].hd().gate_number()

    return {
        "schema_version": SCHEMA_VERSION,
        "frame": frame,
        "gate_one": ctx.hd_gate_one,
        "personality_datetime": _iso_utc(bg.context.timeJD),
        "design_datetime": _iso_utc(bg._unconscious_context.timeJD),
        "activations": {
            "personality": _side_rows(conscious),
            "design": _side_rows(unconscious),
        },
        "gates": gates,
        "channels": channels,
        "centers": centers,
        "type": traits["type"],
        "strategy": traits["strategy"],
        "authority": traits["authority"],
        "profile": f"{p_sun_line}/{d_sun_line}",
        "profile_name": (f"{_PROFILE_LINE_NAME.get(p_sun_line, p_sun_line)}"
                         f" · {_PROFILE_LINE_NAME.get(d_sun_line, d_sun_line)}"),
        "definition": traits["definition"],
        "incarnation_cross": _incarnation_cross(
            p_sun_line, d_sun_line, psun, pearth, dsun, dearth),
        "errors": [],
    }
