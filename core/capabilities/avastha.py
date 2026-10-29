# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_avastha``: the Avastha panel grid (AIC plan 2 W7, wave 1 row 4).

``avastha_grid`` is ``AvasthaController``'s table as data (moved out of
``_refresh_pure`` / ``_refresh_refined`` / ``_render_bottom_rows``): the 7x7
drishti/yuti matrix with the dignity diagonal, then the TOTAL, POS, NEG, SIGN,
HORA and TRIMSAMSA rows, each cell with its text, colour category and tooltip.

Two charts, as in the panel: the matrix and sign rows read the chart rebuilt in
the sidereal frame when the mode is sidereal; the balas of a refined view read
the active chart (SPEC-AVA-001 §6, like the Strength panel).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

VIEWS = ["pure", "duc", "dig", "uccha", "cheshta"]
ROW_LABELS = ["TOTAL", "POS", "NEG", "SIGN", "HORA", "TRIMSAMSA"]
_DIGNITY_ABBR = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}


def _cell(text, category=None, tooltip=None):
    return {"text": text, "category": category, "tooltip": tooltip}


def _pure_matrix(order, matrix, dignity_data, shame_pairs):
    from AI_tools.AI_main_function.avastha import REL_SYMBOL
    from core.avastha_totals import SELF_BASE, dignity_multiplier, split_expression
    grid = []
    for aspecting in order:
        row = []
        for aspected in order:
            if aspecting == aspected:
                dig = dignity_data.get(aspecting)
                val = SELF_BASE * dignity_multiplier(dig["virupas"] if dig else 0)
                if dig:
                    row.append(_cell(f"{_DIGNITY_ABBR.get(dig['type'], '?')}{val:.0f}",
                                     "PROUD"))
                else:
                    row.append(_cell(f"{val:.0f}"))
                continue
            entry = matrix.get((aspecting, aspected))
            if entry is None or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                row.append(_cell("."))
                continue
            vr, rel = entry["virupas"], entry["relationship"]
            sym = REL_SYMBOL.get(rel, " ")
            if (aspecting, aspected) in shame_pairs:
                if rel in ("NEUTRAL", "N/A"):
                    sym = "-"
                row.append(_cell(f"{vr:.0f}{sym}!", "SHAME"))
            elif rel == "DUAL":
                row.append(_cell(f"{vr:.0f}±", "DUAL"))
            else:
                row.append(_cell(f"{vr:.0f}{sym}",
                                 rel if rel in ("FRIEND", "ENEMY", "NEUTRAL") else None))
        grid.append(row)
    pos, neg = [], []
    for aspected in order:
        up, aff = split_expression(aspected, order, matrix, dignity_data, shame_pairs)
        pos.append(up)
        neg.append(aff)
    return grid, pos, neg


def _refined_matrix(order, matrix, dignity_data, shame_pairs, balas, key):
    from core.avastha_refined import refined_matrix
    rm = refined_matrix(order, matrix, dignity_data, shame_pairs, balas, key)
    grid = []
    for actor in order:
        row = []
        for target in order:
            if actor == target:
                val, dtype = rm["diagonal"][actor]
                row.append(_cell(f"{_DIGNITY_ABBR.get(dtype, '?')}{val:.0f}", "PROUD")
                           if dtype else _cell(f"{val:.1f}"))
                continue
            c = rm["cells"].get((actor, target))
            if c is None:
                row.append(_cell("."))
                continue
            tip = None
            if c["is_shame"] and c["relationship"] == "FRIEND":
                tip = f"friendship gives {c['give']:.1f} / shame takes {c['take']:.1f}"
            elif c["two_sided"]:
                tip = f"dual gives {c['give']:.1f} / takes {c['take']:.1f}"
            elif c["is_shame"]:
                tip = f"shames: takes {c['take']:.1f} ({actor}'s bala lack)"
            row.append(_cell(f"{c['value']:.1f}{c['symbol']}{'!' if c['is_shame'] else ''}",
                             c["category"], tip))
        grid.append(row)
    return grid, [rm["pos"][t] for t in order], [rm["neg"][t] for t in order], \
        [rm["totals"][t] for t in order]


def retinue_cells(sign_chart, body, mode, total=None):
    """The SIGN, HORA and TRIMSAMSA cells of one body, as the panel shows them
    (sign named by the mode: Aditya names in aditya mode, Western names
    otherwise; an Aditya-side hora shows the sign, a Naga-side hora its
    being), plus the retinue column a cell click opens. ``total`` colours the
    SIGN cell (None: no category). Shared with the show_avastha CLI so its
    text output cannot drift from the panel."""
    from AI_tools.AI_main_function.retinue import (
        ADITYA_SIGN_ORDER, get_hora, get_trimsamsa_being)
    from core.avastha_totals import sign_total_category
    from core.chart_helpers import (
        ADITYA_NAMES, TROPICAL_NAMES, get_planet_in_sign_longitude,
        get_planet_sign_index)
    names = ADITYA_NAMES if mode == "aditya" else TROPICAL_NAMES
    idx = get_planet_sign_index(sign_chart, body, default=-1)
    ok = 0 <= idx < 12
    sign_text = names[idx] if ok else "?"
    aditya_sign = ADITYA_SIGN_ORDER[idx] if ok else None
    sign_cell = _cell(sign_text,
                      sign_total_category(total) if total is not None else None,
                      f"{aditya_sign} / {TROPICAL_NAMES[idx]}" if aditya_sign else None)
    col = {"aditya_sign": aditya_sign, "hora_type": None, "trim_type": None}
    if not aditya_sign:
        return sign_cell, _cell("?"), _cell("?"), col
    deg = get_planet_in_sign_longitude(sign_chart, body)
    hora = get_hora(aditya_sign, deg)
    trim = get_trimsamsa_being(aditya_sign, deg)
    side = hora.get("side", "?")
    hora_cell = _cell(
        sign_text if side == "Aditya" else hora.get("being_name", "?"),
        "HORA_ADITYA" if side == "Aditya" else "HORA_NAGA",
        f"{hora.get('being_name', '?')} ({side} side, {hora.get('lord', '?')} hora)")
    col["hora_type"] = "aditya" if side == "Aditya" else "naga"
    btype = trim.get("being_type", "")
    col["trim_type"] = str(btype).lower()
    tname = trim.get("being_name", "?")
    trim_cell = _cell(tname, "TRIM_" + str(btype).upper(),
                      f"{tname} ({btype}, {trim.get('element', '?')})")
    return sign_cell, hora_cell, trim_cell, col


def _bottom_rows(order, sign_chart, mode, pos, neg, totals, decimals):
    from core.avastha_totals import display_split
    rows = {k: [] for k in ROW_LABELS}
    columns = []    # per planet: the retinue beings a cell click opens (§12.5)
    for i, target in enumerate(order):
        pos_s, neg_s, total_s = display_split(pos[i], neg[i], decimals)
        rows["TOTAL"].append(_cell(total_s))
        rows["POS"].append(_cell(pos_s, "FRIEND" if float(pos_s) > 0 else "NEUTRAL"))
        rows["NEG"].append(_cell(neg_s, "ENEMY" if float(neg_s) < 0 else "NEUTRAL"))
        sign_cell, hora_cell, trim_cell, col = retinue_cells(
            sign_chart, target, mode, totals[i])
        rows["SIGN"].append(sign_cell)
        rows["HORA"].append(hora_cell)
        rows["TRIMSAMSA"].append(trim_cell)
        columns.append(col)
    rows["columns"] = columns
    return rows


def avastha_grid(active_chart, mode: str, view: str = "pure",
                 duc_method=None) -> Dict[str, Any]:
    """The Avastha panel table for ``view`` (pure or a strength-refined view);
    ``duc_method``: the DUC Bala method of the duc view (None: "equal")."""
    from AI_tools.AI_main_function.avastha import ASPECTING_PLANETS, get_drishti_yuti_data
    from core.avastha_frame import avastha_frame_chart
    matrix_chart = avastha_frame_chart(active_chart, mode)
    data = get_drishti_yuti_data(matrix_chart)
    order = list(ASPECTING_PLANETS)
    args = (order, data["matrix"], data["dignity_data"], data.get("shame_pairs", set()))
    if view == "pure":
        grid, pos, neg = _pure_matrix(*args)
        totals, decimals = [p + n for p, n in zip(pos, neg)], 0
    else:
        from core.avastha_refined import REFINE_KEYS
        from core.bala_calculator import get_all_bala_data
        key = view if view in REFINE_KEYS else "duc"
        balas = get_all_bala_data(active_chart, duc_method=duc_method)
        grid, pos, neg, totals = _refined_matrix(*args, balas, key)
        decimals = 1
    rows = _bottom_rows(order, matrix_chart, mode, pos, neg, totals, decimals)
    return {"view": view, "planets": order, "matrix": grid, **rows,
            "values": {"total": totals, "pos": pos, "neg": neg},
            # The same totals keyed by planet: an AI counting list positions
            # gave Jupiter's -84 / +90 to Mercury (AI capture tour 2026-10-20).
            "by_planet": {p: {"received_total": round(totals[i], 2),
                              "received_pos": round(pos[i], 2),
                              "received_neg": round(neg[i], 2),
                              "sign": rows["SIGN"][i]["text"]}
                          for i, p in enumerate(order)}}


def _register():
    from core.capabilities.catalog import Capability, register
    from core.capabilities.setting_args import INPUT, setting
    from core.settings_registry import option_schema
    register(Capability(
        id="get_avastha", title="Avastha",
        description=("The Avastha grid (rashi chart): how the 7 planets help or "
                     "harm each other by aspect and conjunction, the dignity "
                     "diagonal, shame and dual marks, then the TOTAL, POS, NEG, "
                     "sign, Hora and Trimsamsa rows. Matrix row = the planet that "
                     "casts, column = the planet that receives; by_planet gives "
                     "each planet's received totals by name. view 'pure' or a "
                     "strength-refined view (duc, dig, uccha, cheshta)."),
        run=lambda inp, o: avastha_grid(inp.build_chart(), inp.frame.mode, o["view"],
                                        o["duc_method"]),
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"view": {"type": "string", "enum": VIEWS,
                                                "default": "pure"},
                                       "duc_method": option_schema(
                                           "strength.duc_method", "duc_method",
                                           description=("How the duc view's DUC Bala "
                                                        "combines Dig, Uccha and "
                                                        "Chesta."))}},
        # SPEC-SET-003 §4.4: view is a view choice; duc_method a setting.
        setting_args={"view": INPUT, "duc_method": setting("strength.duc_method")},
        output_schema={"type": "object",
                       "required": ["view", "planets", "matrix", "values", *ROW_LABELS]},
        sources=(("AI_tools/AI_main_function/avastha.py", "get_drishti_yuti_data"),
                 ("core/avastha_refined.py", "refined_matrix"),
                 ("core/capabilities/avastha.py", "avastha_grid"))))


_register()
