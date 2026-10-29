# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sidebar retinue family: ``get_retinue``, ``get_hora``, ``get_trimsamsa``,
``get_houses`` (AIC plan 2 W7, wave 1 rows 1 and 6).

These are the D-1 sidebar panels (Hora, Trimsamsa, the Houses tally), which
all read ``get_chart_retinue``. The beings drawn ON the chart (South Indian and
wheel rings, any varga) are a different path: ``get_chart_retinue_rings``
(``core/capabilities/chart_retinue.py``).

``sidebar_retinue`` is the one call the three controllers and the tools share:
same chart, same mode flags, same ayanamsa offset as
``ChartGUI._compute_chart_ayanamsa_offset`` (labels only: sign resolution
reads the Chart, ``retinue.py:176-183``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def sidebar_retinue(chart, mode: str, jd: float = None,
                    ayanamsa_id: int = None, ayanamsa_offset: float = None) -> Dict:
    """``get_chart_retinue`` with the panels' flags. ``ayanamsa_offset`` may be
    given (the GUI's cached value); otherwise it is computed the GUI's way."""
    from AI_tools.AI_main_function.retinue import get_chart_retinue
    offset = 0.0
    if mode == "sidereal":
        if ayanamsa_offset is None:
            from core.ayanamsa_offset import birth_ayanamsa_offset
            ayanamsa_offset = (birth_ayanamsa_offset(jd, ayanamsa_id)
                               if jd is not None and ayanamsa_id is not None else 0.0)
        offset = ayanamsa_offset
    return get_chart_retinue(chart, ayanamsa_offset=offset,
                             tropical_mode=(mode == "tropical_classic"))


def house_tally(planets: List[Dict]) -> Tuple[List, List[int]]:
    """The Houses graph data: active houses (house, count, [(planet, ring)])
    sorted by count then house, and the absent houses."""
    from AI_tools.AI_main_function.retinue import _build_house_tally
    tally = _build_house_tally(planets)
    active, absent = [], []
    for h in range(1, 13):
        entries = tally[h]
        if entries:
            active.append((h, len(entries), [(e["planet"], e["ring"]) for e in entries]))
        else:
            absent.append(h)
    active.sort(key=lambda x: (-x[1], x[0]))
    return active, absent


def _retinue_for(inp) -> Dict[str, Any]:
    return sidebar_retinue(inp.build_chart(), inp.frame.mode, inp.chart.jd_ut,
                           inp.frame.ayanamsa_id)


def _run_retinue(inp, options):
    data = _retinue_for(inp)
    return {"chart_name": data["chart_name"], "mode_label": data["mode"],
            "planets": data["planets"], "summary": data["summary"]}


def _run_hora(inp, options):
    data = _retinue_for(inp)
    rows = [{"planet": r["planet"], "being_name": r["hora"]["being_name"],
             "side": r["hora"]["side"]} for r in data["planets"]]
    hs = data["summary"]["hora"]
    return {"rows": rows,
            "summary": {"aditya_side": hs["aditya_side"]["count"],
                        "naga_side": hs["naga_side"]["count"]},
            "detail": data["summary"]["hora"]}


def _run_trimsamsa(inp, options):
    data = _retinue_for(inp)
    rows = [{"planet": r["planet"],
             "being_name": r["trimsamsa"]["being_name"],
             "being_type": r["trimsamsa"]["being_type"],
             "element": r["trimsamsa"].get("element")} for r in data["planets"]]
    return {"rows": rows, "summary": data["summary"].get("trimsamsa")}


def _run_houses(inp, options):
    data = _retinue_for(inp)
    active, absent = house_tally(data["planets"])
    return {"active": [{"house": h, "count": n,
                        "beings": [{"planet": p, "ring": ring} for p, ring in beings]}
                       for h, n, beings in active],
            "absent": absent}


def _register():
    from core.capabilities.catalog import Capability, register
    src = (("AI_tools/AI_main_function/retinue.py", "get_chart_retinue"),
           ("core/capabilities/retinue.py", "sidebar_retinue"))
    register(Capability(
        id="get_retinue", title="Retinue",
        description=("Hora and Trimsamsa beings of the Aditya retinue for each "
                     "planet of the rashi chart (D-1), with the Hora and "
                     "Trimsamsa summaries, as the sidebar panels compute them."),
        run=_run_retinue,
        output_schema={"type": "object",
                       "required": ["chart_name", "mode_label", "planets", "summary"]},
        sources=src))
    register(Capability(
        id="get_hora", title="Hora",
        description=("The Hora panel: each planet's Hora being and side "
                     "(Aditya or Naga) and the count on each side."),
        run=_run_hora,
        output_schema={"type": "object", "required": ["rows", "summary"]},
        sources=src))
    register(Capability(
        id="get_trimsamsa", title="Trimsamsa",
        description=("The Trimsamsa panel: each planet's Trimsamsa being, its "
                     "type and element, and the summary."),
        run=_run_trimsamsa,
        output_schema={"type": "object", "required": ["rows", "summary"]},
        sources=src))
    register(Capability(
        id="get_houses", title="Houses",
        description=("The Houses graph: which houses the planets' retinue beings "
                     "fall in (with ring), sorted by count, and the empty houses."),
        run=_run_houses,
        output_schema={"type": "object", "required": ["active", "absent"]},
        sources=src + (("AI_tools/AI_main_function/retinue.py", "_build_house_tally"),)))


_register()
