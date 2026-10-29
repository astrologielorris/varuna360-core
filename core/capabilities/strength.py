# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_strength``: the Strength table (AIC plan 2 W7, wave 1 row 3).

``strength_rows`` is the panel's data model: the Strength controller renders
exactly these rows (cells, retrograde marker, highlights), and the tool
returns them. The calculation is ``core.bala_calculator.get_all_bala_data``
called with the chart and the DUC method (setting ``strength.duc_method``,
SPEC-STR-001 §7.5; the panel passes the saved value, the tool resolves it
like every setting), as the panel does (sidereal charts are rebuilt as
tropical_classic inside it, SPEC-STR-001 §6.3; ``hsys`` only matters on the
deprecated dict path).
"""
from __future__ import annotations

from typing import Any, Dict, List

PLANET_ORDER = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
_CAN_RETRO = ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")


def strength_rows(chart, duc_method=None) -> List[Dict[str, Any]]:
    """One row per classical planet, in panel order, with raw values, the
    panel's cell texts and which cells the panel highlights. ``duc_method``:
    the DUC Bala method (None: "equal")."""
    from core.bala_calculator import STRENGTH_THRESHOLD, get_all_bala_data
    bala = get_all_bala_data(chart, duc_method=duc_method)
    rows = []
    for planet in PLANET_ORDER:
        if planet not in bala:
            continue
        data = bala[planet]
        dig = data.get("digbala", 0)
        uccha = data.get("uccha", 0)
        chesta = data.get("chesta", 0)
        duc = data.get("duc_bala", 0)
        retro = False
        if planet in _CAN_RETRO:
            try:
                retro = bool(chart.rashi().planets()[planet].retrograde())
            except (KeyError, AttributeError):
                retro = False
        rows.append({
            "planet": planet,
            "digbala": dig, "uccha": uccha, "chesta": chesta, "duc_bala": duc,
            "retrograde": retro,
            "text": {"digbala": f"{dig:.1f}", "uccha": f"{uccha:.1f}",
                     "chesta": f"{chesta:.1f} R*" if retro else f"{chesta:.1f}",
                     "duc_bala": f"{duc:.1f}"},
            "strong": {"digbala": dig > STRENGTH_THRESHOLD,
                       "uccha": uccha > STRENGTH_THRESHOLD,
                       "chesta": chesta > STRENGTH_THRESHOLD,
                       "duc_bala": duc > STRENGTH_THRESHOLD},
        })
    return rows


def _run(inp, options):
    from core.bala_calculator import STRENGTH_THRESHOLD
    return {"threshold": STRENGTH_THRESHOLD,
            "rows": strength_rows(inp.build_chart(), options["duc_method"])}


def _register():
    from core.capabilities.catalog import Capability, register
    from core.capabilities.setting_args import setting
    from core.settings_registry import option_schema
    register(Capability(
        id="get_strength",
        title="Strength",
        description=("The Strength table for the 7 classical planets: Dig Bala, "
                     "Uccha Bala, Chesta Bala and DUC Bala (combined by the "
                     "DUC Bala method setting), with "
                     "the retrograde marker and which values pass the strength "
                     "threshold, exactly as the Strength panel shows them."),
        run=_run,
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"duc_method": option_schema(
                            "strength.duc_method", "duc_method",
                            description=("How DUC Bala combines Dig, Uccha and "
                                         "Chesta: equal thirds, or Ernst Wilhelm "
                                         "(Dig 1/2, Uccha 1/4, Chesta 1/4)."))}},
        setting_args={"duc_method": setting("strength.duc_method")},
        output_schema={"type": "object", "required": ["threshold", "rows"],
                       "properties": {"rows": {"type": "array", "items": {
                           "type": "object",
                           "required": ["planet", "digbala", "uccha", "chesta",
                                        "duc_bala", "retrograde", "text",
                                        "strong"]}}}},
        sources=(("core/bala_calculator.py", "get_all_bala_data"),
                 ("core/capabilities/strength.py", "strength_rows")),
    ))


_register()
