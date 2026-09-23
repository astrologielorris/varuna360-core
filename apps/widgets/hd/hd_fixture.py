"""A sample HDModel, so the view can be built and tested before the engine lands.

The chart is the mockup round's own sample -- the one every mockup rendered and the one
in ``shot_27_dark.png`` -- transcribed from ``_shared_data.js`` and reshaped into the
HDModel contract v1.0 that ``core/hd_model.py`` will emit. Nothing here computes
anything: the gates and lines are the fixed values the mockups were drawn from, and the
derived fields (type, authority, profile, the channel and centre tables) come from
``libaditya.hd.definition`` so the fixture cannot drift from the engine's own topology.

Two uses:

  * building and screenshotting the view against a known chart while WI-2 is in flight;
  * a stable input for the view tests, which must not depend on an ephemeris.

When the real model arrives this file stays, as the tests' fixture. It is NOT a fallback:
the view must never quietly render sample data in front of a user, so nothing in the view
imports it outside a test or an explicit demo flag.
"""

from __future__ import annotations

from typing import Any

#: Contract v1.0. Bumped by ``core/hd_model.py``, never here.
SCHEMA_VERSION = "hd-model-1"

#: The 14 rows, in the contract's stated order (Josh's ``hd13()`` plus Chiron).
PLANETS = (
    "sun", "earth", "moon", "north_node", "south_node", "mercury", "venus",
    "mars", "jupiter", "saturn", "uranus", "neptune", "pluto", "chiron",
)

#: Display glyphs, index-aligned with PLANETS. From ``_shared_data.js``.
GLYPHS = ("⨀", "⨁", "☾", "☊", "☋", "☿", "♀",
          "♂", "♃", "♄", "⛢", "♆", "⯓", "⚷")

#: Display names, index-aligned with PLANETS.
NAMES = ("Sun", "Earth", "Moon", "Rahu", "Ketu", "Mercury", "Venus", "Mars",
         "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron")

#: Chiron prints in both columns but activates no gate: the engine strips it before
#: definition. That is why gate 15 stays undefined on this chart despite appearing
#: at 15.4 and 15.1 in the two columns.
CHIRON_INDEX = 13

#: gate.line as the mockups carry them, index-aligned with PLANETS.
_PERSONALITY = (22.4, 47.4, 34.2, 57.6, 51.6, 63.1, 30.3, 41.5, 42.2, 20.1,
                10.6, 1.3, 59.2, 15.4)
_DESIGN = (20.2, 34.2, 5.4, 57.1, 51.1, 26.4, 11.6, 6.3, 42.5, 19.3,
           10.2, 1.1, 18.6, 15.1)

PERSONALITY_DATETIME = "1985-03-14T09:42:00Z"
DESIGN_DATETIME = "1984-12-16T03:07:00Z"


def _split(value: float) -> tuple[int, int]:
    """``22.4`` -> gate 22, line 4. The mockups carry one decimal, so line is exact."""
    gate = int(value)
    line = int(round((value - gate) * 10))
    return gate, line


def _rows(values: tuple[float, ...]) -> list[dict[str, Any]]:
    rows = []
    for index, value in enumerate(values):
        gate, line = _split(value)
        activates = index != CHIRON_INDEX
        rows.append({
            "planet": PLANETS[index],
            "available": True,
            "activates": activates,
            "gate": gate,
            "line": line,
            # the mockups carry no colour/tone/base, and the view does not draw them
            "color": None,
            "tone": None,
            "base": None,
            "elapsed_pct": None,
        })
    return rows


def build_fixture() -> dict[str, Any]:
    """The sample chart as an HDModel dict.

    Gates, channels and centres are derived through ``libaditya.hd.definition`` rather
    than hard-coded, so if the engine's topology ever changes this fixture changes with
    it and the view's tests notice. The narrative fields are the mockup's own.
    """
    from libaditya.hd import constants as hdc
    from libaditya.hd import definition as hddef

    personality = _rows(_PERSONALITY)
    design = _rows(_DESIGN)

    p_gates = {r["gate"] for r in personality if r["activates"]}
    d_gates = {r["gate"] for r in design if r["activates"]}

    gates = {}
    for gate in range(1, 65):
        in_p, in_d = gate in p_gates, gate in d_gates
        gates[str(gate)] = ("both" if in_p and in_d else
                            "personality" if in_p else
                            "design" if in_d else "none")

    defined = {tuple(sorted(pair)) for pair in
               hddef.defined_channels(sorted(p_gates | d_gates))}
    channels = {}
    for low, high in sorted(hdc.channels):
        channels[f"{low}-{high}"] = {
            "defined": (low, high) in defined,
            "low_gate_state": gates[str(low)],
            "high_gate_state": gates[str(high)],
        }

    # the engine names the G centre "ji"; the view's vocabulary is the geometry's "g",
    # and the rename happens exactly here, at the model boundary
    raw_centers = hddef.defined_centers(sorted(p_gates | d_gates))
    centers = {("g" if k == "ji" else k): bool(v) for k, v in raw_centers.items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "frame": "standard",
        "gate_one": 223.25,
        "personality_datetime": PERSONALITY_DATETIME,
        "design_datetime": DESIGN_DATETIME,
        "activations": {"personality": personality, "design": design},
        "gates": gates,
        "channels": channels,
        "centers": centers,
        "type": "Manifesting Generator",
        # Contract v1.1. A Manifesting Generator responds first and then informs, which
        # is a different instruction from a pure Generator's "Wait to respond"; v1.0 gave
        # both the same string and mockup 27 was right.
        "strategy": "Respond, then inform",
        "authority": "Sacral",
        "profile": "4/2",
        # contract v1.1, additive: the two line archetypes in profile order. The view
        # prints "4/2 (Opportunist \u00b7 Hermit)" by joining them; when the field is
        # absent -- an older model -- it prints the bare profile and nothing is lost.
        "profile_name": "Opportunist \u00b7 Hermit",
        "definition": "Single",
        "incarnation_cross": {"label": "RAX of Contagion", "gates": [22, 47, 20, 34],
                              "named": True},
        "errors": [],
    }
