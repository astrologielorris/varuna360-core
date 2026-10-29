# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Avastha web payload builder (SPEC-AVW-001).

ONE shared, GUI-free function that assembles the gated avastha payload (spec 3.1)
from a libaditya Chart, reusing the SAME calculation the desktop uses:
  - retinue.get_hora / get_trimsamsa_being        (placement)
  - avastha.get_drishti_yuti_data                 (7x7 matrix, dignity, lordship, shame)
  - core.avastha_totals.split_expression          (per-planet uplifted/afflicted/total)

Consumed by:
  - the show_avastha --json CLI (AI_tools/cli/show_avastha.py),
  - the static exporter (AI_tools/analysis/export_avastha_reference.py),
  - the FastAPI backend (backend/astrology-api),
so all three return byte-for-byte identical numbers (Rule 24 parity).

TOKEN DIRECTION (the classic transposition trap): matrix is keyed
(aspecting=actor, aspected=target); a matrix entry's relationship is what the
TARGET receives from the ACTOR. The web grid puts the TARGET on the row, so a web
cell reads matrix[(column, row)] and a per-row Total is split_expression(target=row).
"""

from AI_tools.AI_main_function.avastha import (
    get_drishti_yuti_data,
    ASPECTING_PLANETS,
    SIGN_RULERS,
)
from AI_tools.AI_main_function.retinue import get_hora, get_trimsamsa_being
from core.chart_helpers import (
    get_planet_sign_index,
    get_planet_sign_name,
    get_planet_in_sign_longitude,
    has_planet,
)
from core.retinue_constants import ADITYA_SIGN_ORDER
from core.avastha_totals import split_expression

# Canonical web row order (spec 4): Ascendant + 7 aspecting planets + nodes.
WEB_PLANET_ORDER = [
    "Ascendant", "Sun", "Moon", "Mars", "Mercury",
    "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
]

# Planets that appear as rows/columns in the 7x7 matrix (have their own totals).
MATRIX_PLANETS = list(ASPECTING_PLANETS)  # Sun..Saturn


def _placement(sign_name, degree):
    """Hora + trimsamsa beings for a resolved (aditya sign, degree-in-sign).

    Returns (hora_dict|None, trimsamsa_dict|None) in the payload shape.
    """
    hora_raw = get_hora(sign_name, degree)
    trim_raw = get_trimsamsa_being(sign_name, degree)
    hora = None
    if hora_raw:
        hora = {
            "being": hora_raw["being_name"],
            "side": hora_raw["side"],       # "Aditya" | "Naga" (drives chip color + icon)
            "lord": hora_raw["lord"],       # "Sun" | "Moon" (the hora luminary)
        }
    trimsamsa = None
    if trim_raw:
        trimsamsa = {
            "being": trim_raw["being_name"],
            "beingType": trim_raw["being_type"],   # Gandharva|Rakshasa|Rishi|Yaksha|Apsara
            "element": trim_raw["element"],
        }
    return hora, trimsamsa


def build_avastha_payload(chart, mode="aditya"):
    """Assemble the spec-3.1 avastha payload dict from a libaditya Chart.

    Returns a JSON-serializable dict:
      {
        matrix:    [{from, to, virupas, relationship, is_yuti, is_lordship, is_shame}],
        perPlanet: [{planet, adityaSign, degreeInSign,
                     hora:{being,side,lord}|None, trimsamsa:{being,beingType,element}|None,
                     dignity:{type,virupas}|None, total, uplifted, afflicted,
                     shameFlags:[...], lord: <name>|None, lordOf: <planet>|None}],
        aspectingPlanets: [...7...],
        planetOrder:      [...10...],
        mode: "aditya",
      }
    """
    data = get_drishti_yuti_data(chart)
    matrix = data["matrix"]
    dignity_data = data["dignity_data"]
    shame_pairs = data.get("shame_pairs", set())

    # ---- matrix as a flat list (only meaningful cells) ----
    matrix_list = []
    for (aspecting, aspected), entry in matrix.items():
        if entry is None:
            continue
        if not entry.get("is_yuti") and entry["virupas"] <= 0:
            continue  # "." cell, skip
        matrix_list.append({
            "from": aspecting,   # actor (column in the web grid)
            "to": aspected,      # target (row in the web grid)
            "virupas": entry["virupas"],
            "relationship": entry["relationship"],
            "is_yuti": bool(entry.get("is_yuti", False)),
            "is_lordship": bool(entry.get("is_lordship", False)),
            "is_shame": (aspecting, aspected) in shame_pairs,
        })

    # ---- per-planet totals for the 7 matrix planets ----
    totals = {}
    for target in MATRIX_PLANETS:
        up, aff = split_expression(target, MATRIX_PLANETS, matrix, dignity_data, shame_pairs)
        totals[target] = {"uplifted": up, "afflicted": aff, "total": up + aff}

    # shame flags per target: which actors shame it
    shame_flags_for = {}
    for (actor, target) in shame_pairs:
        shame_flags_for.setdefault(target, []).append(actor)

    # ---- per-planet rows (all 10) ----
    per_planet = []
    for name in WEB_PLANET_ORDER:
        if not has_planet(chart, name):
            continue
        sign_name = get_planet_sign_name(chart, name, default="")
        degree = get_planet_in_sign_longitude(chart, name)
        # The retinue tables are keyed by Aditya sign; sign_name is the mode's
        # display label (Western in tropical/sidereal), so look up by index,
        # as the panel's retinue_cells does (td-7b1ev).
        idx = get_planet_sign_index(chart, name, default=-1)
        hora, trimsamsa = (_placement(ADITYA_SIGN_ORDER[idx], degree)
                           if 0 <= idx < 12 else (None, None))
        dig = dignity_data.get(name)
        row = {
            "planet": name,
            "adityaSign": sign_name,
            "degreeInSign": degree,
            "hora": hora,
            "trimsamsa": trimsamsa,
            "dignity": ({"type": dig["type"], "virupas": dig["virupas"]} if dig else None),
            "shameFlags": list(shame_flags_for.get(name, [])),
            "lord": None,
            "lordOf": None,
        }
        if name in totals:
            row["total"] = totals[name]["total"]
            row["uplifted"] = totals[name]["uplifted"]
            row["afflicted"] = totals[name]["afflicted"]
        else:
            # Ascendant / Rahu / Ketu are not in the matrix: surface their SIGN
            # LORD's avastha (spec 4.1), e.g. Asc in Varuna -> Lord Moon.
            lord = SIGN_RULERS.get(sign_name)
            if lord and lord in totals:
                row["lord"] = lord
                row["lordOf"] = name
                row["total"] = totals[lord]["total"]
                row["uplifted"] = totals[lord]["uplifted"]
                row["afflicted"] = totals[lord]["afflicted"]
            else:
                row["total"] = None
                row["uplifted"] = None
                row["afflicted"] = None
        per_planet.append(row)

    return {
        "matrix": matrix_list,
        "perPlanet": per_planet,
        "aspectingPlanets": list(ASPECTING_PLANETS),
        "planetOrder": [r["planet"] for r in per_planet],
        "mode": mode,
    }
