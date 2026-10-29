# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_aspects`` and ``get_karakas`` (AIC plan 2 W7, wave 1 row 2).

``aspect_matrix`` is the Aspects panel's 7x9 grid (moved out of
``AspectsController._refresh``): virupas from ``calculate_all_aspects``, a
same-sign pair shown as Yuti ("Y"), highlights on Yuti and on 45 virupas or
more. ``karaka_rows`` is the Karakas table (moved out of
``KarakasController._refresh``): the 7 grahas ranked by in-sign degree, each
role with its house lord (whole signs from the Ascendant sign), and
``karaka_enriched`` its Karakas + Avastha view.

Both read the Chart as the panels do: the active chart already carries the
zodiac frame, so sign and in-sign degree follow the mode.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

ROW_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
COL_PLANETS = ROW_PLANETS + ["Rahu", "Ketu"]
YUTI, STRONG_VIRUPAS = "Y", 45

KARAKA_ROLES = [
    ("AK", "Atma", "(Self)", "1st"),
    ("AmK", "Amatya", "(Minister)", "10th"),
    ("BK", "Bhratru", "(Brother)", "3rd"),
    ("MK", "Matru", "(Mother)", "4th"),
    ("PiK", "Pitru", "(Father)", "9th"),
    ("GK", "Gnati", "(Relatives)", "2nd"),
    ("DK", "Dara", "(Spouse)", "7th"),
]
_HOUSE_NUMS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "7th": 7, "9th": 9, "10th": 10}
_LORD_LABEL = {"1st": "Asc", "7th": "Dsc", "4th": "IC"}


def _sign_names(chart) -> Dict[str, str]:
    """The sign name of each of the 9 bodies (missing bodies left out)."""
    signs = {}
    planets = chart.rashi().planets()
    for name in COL_PLANETS:
        try:
            signs[name] = planets[name].sign_name()
        except (KeyError, TypeError):
            pass
    return signs


def yuti_pairs(chart) -> List[Tuple[str, str]]:
    """Every unordered pair of the 9 bodies in the same sign (Yuti), in matrix
    order: ``sign_name()`` equality, the rule the Aspects grid shows as "Y".
    The Vedic center drawing reads the same pairs (SPEC-VAC-001 §3.3, INV-4)."""
    signs = _sign_names(chart)
    pairs = []
    for i, a in enumerate(COL_PLANETS):
        for b in COL_PLANETS[i + 1:]:
            if signs.get(a) and signs.get(a) == signs.get(b):
                pairs.append((a, b))
    return pairs


def aspect_matrix(chart) -> Dict[str, Any]:
    """The Aspects panel grid: ``cells[row][col]`` texts, raw virupas and the
    highlighted cells, rows = casting planets, columns = receiving."""
    from AI_tools.analysis.AI_aspects import calculate_all_aspects
    lookup = {(a["aspecting"], a["aspected"]): a["virupas"]
              for a in calculate_all_aspects(chart).get("aspects", [])}
    yutis = {frozenset(pair) for pair in yuti_pairs(chart)}
    cells, virupas, highlight = [], [], []
    for r, aspecting in enumerate(ROW_PLANETS):
        row_t, row_v = [], []
        for c, aspected in enumerate(COL_PLANETS):
            vr = None
            if aspecting == aspected:
                text = "-"
            elif frozenset((aspecting, aspected)) in yutis:
                text = YUTI
                highlight.append([r, c])
            else:
                vr = lookup.get((aspecting, aspected), 0)
                text = f"{vr:.0f}" if vr > 0 else "."
                if vr >= STRONG_VIRUPAS:
                    highlight.append([r, c])
            row_t.append(text)
            row_v.append(vr)
        cells.append(row_t)
        virupas.append(row_v)
    return {"rows": ROW_PLANETS, "columns": COL_PLANETS, "cells": cells,
            "virupas": virupas, "highlight": highlight}


def vedic_chart_positions(chart) -> Dict[str, float]:
    """L = sign_index * 30 + degree in sign for each of the 9 bodies on ``chart``,
    in the chart's own zodiac frame (SPEC-VAC-001 §3.2; never converted)."""
    from core.chart_helpers import (get_planet_in_sign_longitude, get_planet_sign_index,
                                    has_planet)
    return {name: get_planet_sign_index(chart, name) * 30.0
            + get_planet_in_sign_longitude(chart, name)
            for name in COL_PLANETS if has_planet(chart, name)}


def vedic_full_model(chart):
    """The Vedic center drawing's full model from the matrix's own data: the
    engine records, the Yuti pairs and the 9 positions (SPEC-VAC-001 §4.1).
    The GUI pass and ``AI_aspects.py --center-geometry`` both call this."""
    from AI_tools.analysis.AI_aspects import calculate_all_aspects
    from core.vedic_center import build_full_model
    records = calculate_all_aspects(chart).get("aspects", [])
    return build_full_model(vedic_chart_positions(chart), records, yuti_pairs(chart))


def karaka_rows(chart, mode: str) -> List[Dict[str, Any]]:
    """The Karakas table rows, in role order."""
    from core.chart_helpers import get_planet_in_sign_longitude, has_planet
    from core.sidereal_helpers import ADITYA_NAMES, TROPICAL_NAMES, get_sign_ruler
    ranked = sorted(({"name": n, "degree": get_planet_in_sign_longitude(chart, n)}
                     for n in ROW_PLANETS if has_planet(chart, n)),
                    key=lambda x: x["degree"], reverse=True)
    lords = {}
    try:
        asc = (chart.rashi().cusps()[1].sign() - 1) % 12
    except (KeyError, IndexError, TypeError):
        asc = -1
    if asc >= 0:
        names = ADITYA_NAMES if mode == "aditya" else TROPICAL_NAMES
        for cusp_id, house in _HOUSE_NUMS.items():
            lords[cusp_id] = get_sign_ruler(names[(asc + house - 1) % 12])
    rows = []
    for (code, name, meaning, cusp_id), p in zip(KARAKA_ROLES, ranked):
        rows.append({"code": code, "karaka": f"{code} - {name} {meaning}",
                     "planet": p["name"], "degree_in_sign": p["degree"],
                     "lord_of": _LORD_LABEL.get(cusp_id, cusp_id),
                     "house": _HOUSE_NUMS[cusp_id],
                     "lord": lords.get(cusp_id),
                     "highlight": code in ("AK", "DK")})
    return rows


_DIGNITY_NAMES = {"exaltation": "Exalted", "mulatrikona": "Moolatrikona",
                  "own_sign": "Own House"}


def karaka_enriched(chart, mode: str, use_western: bool,
                    jd: float = None, ayanamsa_id: int = None,
                    ayanamsa_offset: float = None) -> List[Dict[str, Any]]:
    """The Karakas + Avastha enriched view as data (moved out of
    ``KarakasController._refresh_enriched``): per role, the sign and degree,
    the house connections (H = hora ring, T = trimsamsa ring), the Avastha
    total, and the condition words the panel shows."""
    from AI_tools.AI_main_function.avastha import get_drishti_yuti_data
    from AI_tools.AI_main_function.retinue import _build_house_tally
    from core.aditya_mode import displayed_sign_name
    from core.avastha_totals import split_expression
    from core.capabilities.retinue import sidebar_retinue
    from core.chart_helpers import get_planet_sign_index
    roles = karaka_rows(chart, mode)
    retinue = sidebar_retinue(chart, mode, jd, ayanamsa_id, ayanamsa_offset)
    by_name = {r["planet"]: r for r in retinue["planets"]}
    houses: Dict[str, list] = {}
    for house, entries in _build_house_tally(retinue["planets"]).items():
        for e in entries:
            houses.setdefault(e["planet"], []).append({"house": house, "ring": e["ring"]})
    from core.avastha_frame import avastha_frame_chart
    display_chart = avastha_frame_chart(chart, mode)
    data = get_drishti_yuti_data(display_chart)
    matrix, dignity = data["matrix"], data["dignity_data"]
    shame_pairs, shamed = data.get("shame_pairs", set()), data.get("shamed_planets", set())
    out = []
    for role in roles:
        name = role["planet"]
        r = by_name.get(name)
        idx = get_planet_sign_index(display_chart, name, default=-1)
        up, aff = split_expression(name, ROW_PLANETS, matrix, dignity, shame_pairs)
        total = up + aff
        dig = dignity.get(name)
        trim_type = r.get("trimsamsa", {}).get("being_type") if r else None
        condition = []
        if dig:
            condition.append(_DIGNITY_NAMES.get(dig["type"], "?"))
        if name in shamed:
            condition.append("Shamed")
        elif not dig and total < 0:
            condition.append("Starved")
        elif not dig and total > 0:
            condition.append("Supported")
        if trim_type:
            condition.append(trim_type)
        out.append({"code": role["code"], "planet": name,
                    "dignity": dig["type"] if dig else None,
                    "shamed": name in shamed,
                    "sign": displayed_sign_name(idx, mode, use_western) if idx >= 0 else "?",
                    "degree": f"{r['degrees']}°{r['minutes']:02d}'" if r else "",
                    "houses": [{"ring": e["ring"], "house": e["house"],
                                "text": f"{'H' if e['ring'] == 'H' else 'T'}{e['house']}"}
                               for e in sorted(houses.get(name, []), key=lambda x: x["house"])],
                    "avastha_total": total,
                    "avastha_text": f"{'+' if total > 0 else ''}{total:.0f}",
                    "condition": condition, "trimsamsa_type": trim_type})
    return out


def _run_karakas(inp, options):
    chart = inp.build_chart()
    return {"rows": karaka_rows(chart, inp.frame.mode),
            "enriched": karaka_enriched(chart, inp.frame.mode,
                                        inp.frame.use_western_names,
                                        inp.chart.jd_ut, inp.frame.ayanamsa_id)}


def _register():
    from core.capabilities.catalog import Capability, register
    register(Capability(
        id="get_aspects", title="Aspects",
        description=("The Aspects grid (rashi chart): virupas each of the 7 "
                     "planets casts on the 9 (with Rahu and Ketu), Yuti ('Y') "
                     "for planets in the same sign, and the cells the panel "
                     "highlights (Yuti, or 45 virupas and more)."),
        run=lambda inp, o: aspect_matrix(inp.build_chart()),
        output_schema={"type": "object",
                       "required": ["rows", "columns", "cells", "virupas", "highlight"]},
        sources=(("AI_tools/analysis/AI_aspects.py", "calculate_all_aspects"),
                 ("core/capabilities/karakas_aspects.py", "aspect_matrix"))))
    register(Capability(
        id="get_karakas", title="Karakas",
        description=("The Chara Karakas: the 7 planets ranked by degree in sign "
                     "(AK highest to DK lowest), each role with the lord of its "
                     "house counted in whole signs from the Ascendant."),
        run=_run_karakas,
        output_schema={"type": "object", "required": ["rows", "enriched"]},
        sources=(("core/capabilities/karakas_aspects.py", "karaka_rows"),
                 ("core/capabilities/karakas_aspects.py", "karaka_enriched"))))


_register()
