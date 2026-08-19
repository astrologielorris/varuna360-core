# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Sign-avastha resolver — SPEC-AVA-003 Half B (the engine-facing half).

Turns an active chart + mode + view + sign into the summary dict that the
grouping half (``core.avastha_sign_summary``) formats. This is where the engine
lives: it rebuilds the matrix chart for sidereal exactly as the Avastha panel
does, reads occupancy and sub-sector geometry from the SAME calls the panel and
the wheel use (``get_drishti_yuti_data``, ``get_planet_sign_index``,
``get_hora`` / ``get_trimsamsa_being``), and computes balas from the ACTIVE
chart for a refined view (SPEC-AVA-001 §6). It holds NO avastha math and NO copy
of the retinue boundaries (INV-10).

Still no Qt: the popup, the panel cell click, the Planetary Condition link and
the ``show_avastha`` CLI all obtain their numbers through this module, so they
cannot diverge (INV-7). Engine imports are function-local so ``core`` stays
importable without ``AI_tools`` (Half A's INV-8 is enforced there, not here).
"""

# Bodies listed under D-4 (present in the sign, never counted, never lorded),
# in a stable order. The Ascendant is a point, not a body, and is not listed.
_OTHER_BODIES = ["Rahu", "Ketu", "Uranus", "Neptune", "Pluto"]


def resolve_sign(name):
    """Resolve a sign name to ``(index 0..11, ASCII Aditya name)``.

    Accepts ASCII Aditya names ("Amzu"), Western names ("Sagittarius") and the
    IAST forms ``core.chart_helpers`` already normalises ("Aṃśu"),
    case-insensitively. The index is the SAME 0..11 space
    ``get_planet_sign_index`` returns (division #1 = Dhata = Aries). Unknown ->
    ValueError.
    """
    if not isinstance(name, str):
        raise ValueError(f"sign name must be a string; got {name!r}")
    from core.chart_helpers import ADITYA_NAMES, TROPICAL_NAMES, _IAST_TO_ASCII

    raw = name.strip()
    low = raw.lower()
    aditya_lc = {n.lower(): i for i, n in enumerate(ADITYA_NAMES)}
    trop_lc = {n.lower(): i for i, n in enumerate(TROPICAL_NAMES)}
    iast_lc = {k.lower(): v for k, v in _IAST_TO_ASCII.items()}

    if low in aditya_lc:
        idx = aditya_lc[low]
    elif low in trop_lc:
        idx = trop_lc[low]
    elif low in iast_lc:
        idx = aditya_lc[iast_lc[low].lower()]
    else:
        raise ValueError(f"unknown sign name {name!r}")
    return idx, ADITYA_NAMES[idx]


def sign_sectors(aditya_ascii):
    """Degree-ordered hora halves + trimsamsa bands for a sign's parity.

    Reads ``ADITYA_RETINUE[sign]["type"]`` (odd/even) and the SAME
    ``TRIMSAMSA_ODD`` / ``TRIMSAMSA_EVEN`` tables ``get_hora`` /
    ``get_trimsamsa_being`` use — never ``TRIMSAMSA_SECTIONS`` (odd order only)
    and never a private copy (INV-10). Odd: aditya (0,15) then naga (15,30);
    even: naga (0,15) then aditya (15,30) — the Moon hora is the lower half of
    an even sign (``get_hora``).
    """
    from AI_tools.AI_main_function.retinue import (
        ADITYA_RETINUE, TRIMSAMSA_ODD, TRIMSAMSA_EVEN,
    )
    from core.avastha_sign_summary import sector_label

    data = ADITYA_RETINUE.get(aditya_ascii)
    if not data:
        raise ValueError(f"unknown Aditya sign {aditya_ascii!r}")
    is_odd = data["type"] == "odd"

    if is_odd:
        hora = [
            {"key": "aditya", "label": sector_label("hora", "aditya"), "span": (0, 15)},
            {"key": "naga", "label": sector_label("hora", "naga"), "span": (15, 30)},
        ]
    else:
        hora = [
            {"key": "naga", "label": sector_label("hora", "naga"), "span": (0, 15)},
            {"key": "aditya", "label": sector_label("hora", "aditya"), "span": (15, 30)},
        ]

    bounds = TRIMSAMSA_ODD if is_odd else TRIMSAMSA_EVEN
    trim = [
        {"key": key, "label": sector_label("trimsamsa", key), "span": (start, end)}
        for (start, end, _lord, key, _elem) in bounds
    ]
    return {"hora": hora, "trimsamsa": trim}


def _canonical_sector(ring, being_type):
    """Lowercase + validate a (ring, being_type) pair; (None, None) when ring is None."""
    from core.avastha_sign_summary import HORA_KEYS, TRIM_KEYS

    if ring is None:
        return None, None
    ring_l = str(ring).lower()
    type_l = str(being_type).lower() if being_type is not None else None
    if ring_l == "hora":
        if type_l not in HORA_KEYS:
            raise ValueError(f"unknown hora type {being_type!r}")
    elif ring_l == "trimsamsa":
        if type_l not in TRIM_KEYS:
            raise ValueError(f"unknown trimsamsa band {being_type!r}")
    else:
        raise ValueError(f"unknown ring {ring!r}")
    return ring_l, type_l


def _hora_key(hora):
    """Map ``get_hora(...)["side"]`` ("Aditya"/"Naga") to the wheel key (lowercase)."""
    side = str((hora or {}).get("side", "")).lower()
    if side not in ("aditya", "naga"):
        raise ValueError(f"unexpected hora side {hora!r}")
    return side


def _matrix_chart(active_chart, aditya_mode):
    """The panel's matrix chart: sidereal-rebuilt iff sidereal, else the active chart."""
    if aditya_mode == "sidereal":
        from core.chart_factory import rebuild_chart
        return rebuild_chart(active_chart, mode="sidereal")
    return active_chart


def _membership(aditya, deg):
    from AI_tools.AI_main_function.retinue import get_hora, get_trimsamsa_being
    return {
        "hora": _hora_key(get_hora(aditya, deg)),
        "trimsamsa": get_trimsamsa_being(aditya, deg)["being_type"].lower(),
    }


def sign_summary_for_chart(active_chart, aditya_mode, view, sign_name,
                           ring=None, being_type=None):
    """One sign's avastha summary in the active view/frame (SPEC-AVA-003 §3.4).

    ``ring`` / ``being_type`` are the clicked sub-sector (the wheel's own
    vocabulary); they set ``focus`` and are otherwise not a filter — the summary
    always covers the whole sign at every layer.
    """
    from AI_tools.AI_main_function.avastha import get_drishti_yuti_data, ASPECTING_PLANETS
    from core.chart_helpers import get_planet_sign_index, get_planet_in_sign_longitude
    from core.avastha_sign_summary import summarize_sign

    idx, aditya = resolve_sign(sign_name)
    ring_c, type_c = _canonical_sector(ring, being_type)
    sectors = sign_sectors(aditya)

    mc = _matrix_chart(active_chart, aditya_mode)
    data = get_drishti_yuti_data(mc)
    matrix = data["matrix"]
    dignity_data = data["dignity_data"]
    shame_pairs = data.get("shame_pairs", set())
    planet_order = list(ASPECTING_PLANETS)

    occupants = [p for p in planet_order
                 if get_planet_sign_index(mc, p, default=-1) == idx]
    memberships = {
        p: _membership(aditya, get_planet_in_sign_longitude(mc, p))
        for p in occupants
    }
    others = [b for b in _OTHER_BODIES
              if get_planet_sign_index(mc, b, default=-1) == idx]

    balas = None
    if view != "pure":
        from core.bala_calculator import get_all_bala_data
        balas = get_all_bala_data(active_chart)

    focus = None if ring_c is None else {"layer": ring_c, "key": type_c}

    return summarize_sign(aditya, view, occupants, memberships, sectors,
                          planet_order, matrix, dignity_data, shame_pairs,
                          balas=balas, focus=focus, others=others)


def sign_summaries_all_views(active_chart, aditya_mode, sign_name,
                             ring=None, being_type=None):
    """All FIVE view summaries for one sign, computed in one pass (§11.2, D-20).

    The popup opens with every view ready so switching Pure/Duc/Dig/Uccha/Chesta
    is pure formatting (no engine call on a switch). One matrix build, one
    ``get_all_bala_data(active_chart)`` (SPEC-AVA-001 §6: balas from the ACTIVE
    chart, never the sidereal-rebuilt matrix chart), and five ``summarize_sign``
    over ``VIEW_POPUP_LABEL`` order (== AvasthaController.VIEW_ORDER). Shares the
    occupancy / membership / sector work across the five views. ``sign_summary_
    for_chart`` (single view) stays for the CLI-parity path."""
    from AI_tools.AI_main_function.avastha import get_drishti_yuti_data, ASPECTING_PLANETS
    from core.chart_helpers import get_planet_sign_index, get_planet_in_sign_longitude
    from core.avastha_sign_summary import summarize_sign, VIEW_POPUP_LABEL

    idx, aditya = resolve_sign(sign_name)
    ring_c, type_c = _canonical_sector(ring, being_type)
    sectors = sign_sectors(aditya)

    mc = _matrix_chart(active_chart, aditya_mode)
    data = get_drishti_yuti_data(mc)
    matrix = data["matrix"]
    dignity_data = data["dignity_data"]
    shame_pairs = data.get("shame_pairs", set())
    planet_order = list(ASPECTING_PLANETS)

    occupants = [p for p in planet_order
                 if get_planet_sign_index(mc, p, default=-1) == idx]
    memberships = {
        p: _membership(aditya, get_planet_in_sign_longitude(mc, p))
        for p in occupants
    }
    others = [b for b in _OTHER_BODIES
              if get_planet_sign_index(mc, b, default=-1) == idx]
    focus = None if ring_c is None else {"layer": ring_c, "key": type_c}

    from core.bala_calculator import get_all_bala_data
    balas = get_all_bala_data(active_chart)  # once; the pure view ignores it

    result = {}
    for view in VIEW_POPUP_LABEL:  # insertion order == VIEW_ORDER
        result[view] = summarize_sign(
            aditya, view, occupants, memberships, sectors, planet_order,
            matrix, dignity_data, shame_pairs, balas=balas, focus=focus,
            others=others)
    return result


def all_sign_summaries(active_chart, aditya_mode, view):
    """All twelve sign summaries (Aditya order), matrix + balas computed ONCE."""
    from AI_tools.AI_main_function.avastha import get_drishti_yuti_data, ASPECTING_PLANETS
    from AI_tools.AI_main_function.retinue import ADITYA_SIGN_ORDER
    from core.chart_helpers import get_planet_sign_index, get_planet_in_sign_longitude
    from core.avastha_sign_summary import summarize_sign

    mc = _matrix_chart(active_chart, aditya_mode)
    data = get_drishti_yuti_data(mc)
    matrix = data["matrix"]
    dignity_data = data["dignity_data"]
    shame_pairs = data.get("shame_pairs", set())
    planet_order = list(ASPECTING_PLANETS)

    balas = None
    if view != "pure":
        from core.bala_calculator import get_all_bala_data
        balas = get_all_bala_data(active_chart)

    sign_idx = {p: get_planet_sign_index(mc, p, default=-1) for p in planet_order}
    deg = {p: get_planet_in_sign_longitude(mc, p) for p in planet_order}
    other_idx = {b: get_planet_sign_index(mc, b, default=-1) for b in _OTHER_BODIES}

    result = {}
    for idx, aditya in enumerate(ADITYA_SIGN_ORDER):
        sectors = sign_sectors(aditya)
        occupants = [p for p in planet_order if sign_idx[p] == idx]
        memberships = {p: _membership(aditya, deg[p]) for p in occupants}
        others = [b for b in _OTHER_BODIES if other_idx[b] == idx]
        result[aditya] = summarize_sign(
            aditya, view, occupants, memberships, sectors, planet_order,
            matrix, dignity_data, shame_pairs, balas=balas, focus=None,
            others=others)
    return result
