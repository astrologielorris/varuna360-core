# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_chart_retinue_rings``: the retinue beings drawn ON the chart
(AIC plan 2 W7, wave 1 row 1b).

The South Indian vector view draws its Hora and Trimsamsa rings from
``core/south_indian_retinue_data.retinue_records`` on the shown chart body
(rashi or the chosen varga), for the shown planets (the 9 grahas, the outer
planets when shown, and the optional bodies enabled in Settings), plus the
Ascendant. This tool calls the same function on the same body; the anchors
(scene pixel positions) are drawing data and are left out.

Different from ``get_retinue`` (the D-1 sidebar panels, ``get_chart_retinue``).
"""
from __future__ import annotations

from typing import Any, Dict

BASE_NAMES = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
              "Rahu", "Ketu", "Uranus", "Neptune", "Pluto")


def ring_records(chart, varga: int, show_outer: bool, extra_bodies=()) -> Dict[str, Any]:
    from core.capabilities.chart import varga_source
    from core.south_indian_retinue import ADITYA_SIGN_ORDER, house_connections
    from core.south_indian_retinue_data import retinue_records
    from libaditya.optional_bodies import BODIES
    source = varga_source(chart, varga)
    enabled = tuple(b.name for b in BODIES if b.name in set(extra_bodies or ()))
    names = tuple(dict.fromkeys((*BASE_NAMES, *enabled)))
    code = None
    if (varga or 1) != 1:
        try:
            from core.varga_codes import to_libaditya_varga_code
            code = to_libaditya_varga_code(varga)
        except Exception:
            code = varga
    records, omissions = retinue_records(source.planets(), source.cusps(), code,
                                         {}, names, show_outer)
    out = []
    for p in records:
        hora, trim = p.hora, p.trim
        out.append({
            "body": p.identity, "sign_index": p.sign,
            "aditya_sign": ADITYA_SIGN_ORDER[p.sign],
            "degree_in_sign": p.degree, "label": p.label,
            "hora": {"being_name": hora.get("being_name"), "side": hora.get("side"),
                     "lord": hora.get("lord"),
                     "house_connection": hora.get("house_connection")},
            "trimsamsa": {"being_name": trim.get("being_name"),
                          "being_type": trim.get("being_type"),
                          "element": trim.get("element"),
                          "house_connections": list(trim.get("house_connections", ()))},
            "houses": [{"ring": h.ring, "house": h.house, "sign_index": h.sign}
                       for h in house_connections(p)],
        })
    return {"varga": varga or 1, "records": out, "omissions": list(omissions)}


def _run(inp, options):
    unknown = set(options["additional_bodies"]) - _BODY_NAMES()
    if unknown:
        raise ValueError(f"unknown optional bodies: {sorted(unknown)}")
    # The rings are drawn on the MAIN chart surface: with
    # display.varga_in_center the GUI keeps that surface (and its rings) on
    # D-1 and draws the varga in the center box / outer ring
    # (ChartGUI._apply_current_varga; the shared varga_surfaces rule).
    from core.capabilities.chart import main_surface_varga
    selected = inp.view.varga or 1
    varga = main_surface_varga(selected, options["varga_in_center"])
    out = ring_records(inp.build_chart(), varga,
                       inp.frame.show_outer_planets, options["additional_bodies"])
    if varga != selected:
        out["selected_varga"] = selected
        out["varga_in_center"] = True
    return out


def _BODY_NAMES():
    from libaditya.optional_bodies import BODIES
    return {b.name for b in BODIES}


def _register():
    from core.capabilities.catalog import Capability, register
    from core.capabilities.setting_args import setting
    from core.settings_registry import option_schema
    register(Capability(
        id="get_chart_retinue_rings", title="Chart retinue rings",
        description=("The Hora and Trimsamsa beings the chart draws for each "
                     "shown body (and the Ascendant) in the chosen varga, with "
                     "the houses each being connects to. Follows the saved "
                     "outer planets and optional bodies settings unless given. "
                     "With the varga shown in the chart's center "
                     "(display.varga_in_center) the rings stay on D-1, as the "
                     "chart draws them; selected_varga then names the varga."),
        run=_run,
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"additional_bodies": option_schema(
                            "chart.additional_bodies", "additional_bodies",
                            items={"type": "string"},
                            description=("Optional bodies to include, e.g. "
                                         "[\"Chiron\", \"Ceres\"].")),
                            "varga_in_center": option_schema(
                                "display.varga_in_center", "varga_in_center",
                                description=("The varga drawn in the chart's "
                                             "center box / outer ring while the "
                                             "main chart, and its rings, stay "
                                             "D-1."))}},
        setting_args={"additional_bodies": setting("chart.additional_bodies"),
                      "varga_in_center": setting("display.varga_in_center")},
        output_schema={"type": "object", "required": ["varga", "records", "omissions"]},
        sources=(("core/south_indian_retinue_data.py", "retinue_records"),
                 ("core/capabilities/chart_retinue.py", "ring_records"))))


_register()
