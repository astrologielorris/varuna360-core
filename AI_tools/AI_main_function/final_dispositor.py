# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Final-dispositor themes (terminal-cycle analysis).
==================================================
The dispositor graph is a FUNCTIONAL graph: each of the 7 classical planets
points to its dispositor (the ruler of the sign it occupies), so every node has
out-degree 1. In such a graph every chain terminates in exactly one cycle, and
the cycles are disjoint. Each terminal cycle is a chart "theme": the planets in
the cycle are the chart's final dispositors, the houses they OCCUPY are the
theme's houses, and the "basin" (how many of the 7 planets funnel into that
cycle) measures how dominant the theme is.

A 2-planet cycle IS a Parivartana (exchange) yoga and is cross-linked to
``interchange.get_all_interchanges``. A 1-cycle is a self-disposited planet
(a planet in its own sign). Larger cycles are rarer multi-planet themes.

PURE / GUI-free (spec §3, hardening H3): every function takes an ALREADY-FRAMED
``chart`` and reads NO GUI state. Sidereal (or any other) framing is the
caller's responsibility (controller / CLI seam), exactly like the pure helpers
in ``interchange.py``. Rahu/Ketu are NOT dispositors (7 planets only).

Sourcing: the Maha/Khala/Dainya taxonomy is classical (Phaladeepika VI.32-34);
final-dispositor framing is the app author's systematisation of classical
dispositor doctrine.
"""

from AI_tools.AI_main_function.interchange import (
    PLANETS_LIST,
    dispositor,
    house_of,
    _classify_interchange,
    get_all_interchanges,
)
from AI_tools.AI_main_function.constants import DUSTHANA_HOUSES

# Internal Vedic classification -> pari_sem() severity key (ui/qt_theme.py).
_CLASS_TO_SEM = {
    "MAHA": "maha",
    "KHALA": "khala",
    "DAINYA_6": "dainya6",
    "DAINYA_8": "dainya8",
    "DAINYA_12": "dainya12",
    "DAINYA_DOUBLE": "dainya_double",
}


def classify_house_set(houses):
    """Severity of a theme from the SET of houses it occupies.

    # EXCHDISP-REVIEW: R3 multi-house-naming
    Only a TWO-house theme has a classical Parivartana name, so only then do we
    reuse the pair classifier (``_classify_interchange``). A 1-house theme
    (self-disposited planet, or a cycle whose planets share a house) and a 3+
    house theme have no classical pair name -> ``neutral`` (pending, R3). We
    NEVER feed ``(h, h)`` or three houses to the pair classifier (hardening H5).

    Returns ``(sem_key, classification)`` where ``classification`` is the
    internal MAHA/KHALA/DAINYA_* label for a 2-house theme (used to look up
    description text) or ``None`` otherwise.
    """
    ordered = sorted(set(houses))
    if len(ordered) == 2:
        cls = _classify_interchange(ordered[0], ordered[1])
        return _CLASS_TO_SEM.get(cls, "neutral"), cls
    return "neutral", None


def _terminal_cycle(start, succ):
    """Return the frozenset of planets in the terminal cycle reached from
    ``start`` in the functional graph ``succ`` (planet -> dispositor), or None
    if the chain dead-ends (a dispositor absent from the chart).
    """
    seen = {}
    order = []
    node = start
    while node is not None and node not in seen:
        seen[node] = len(order)
        order.append(node)
        node = succ.get(node)
    if node is None:
        return None  # dead-end: dispositor not present (rare; 7 planets normally all present)
    return frozenset(order[seen[node]:])  # cycle = tail from the first repeat


def get_dispositor_themes(chart):
    """Ranked final-dispositor themes for an ALREADY-FRAMED chart.

    Returns a list of theme dicts, dominant-first, each:
      - ``cycle_planets``   : sorted list of the final-dispositor planets (the cycle)
      - ``occupied_houses`` : sorted unique whole-sign houses the cycle planets OCCUPY
                              (occupied, NEVER owned — L12 R2 / hardening H5)
      - ``basin``           : how many of the 7 planets funnel into this cycle
      - ``cycle_size``      : len(cycle_planets)
      - ``is_exchange``     : True iff a 2-cycle (a Parivartana exchange)
      - ``severity_key``    : pari_sem() key (maha/khala/dainya*/dainya_double/neutral)
      - ``classification``  : internal MAHA/KHALA/DAINYA_* for a 2-house theme, else None
      - ``dusthana_houses`` : the theme's OWN houses that sit in a dusthana (6/8/12);
                              distinct from interchange.py's ``dainya_afflicted``, which
                              reports the NON-dusthana victim house of an exchange pair
      - ``exchange_record`` : the matching get_all_interchanges 7-tuple for a 2-cycle,
                              else None (present on EVERY theme)
    """
    # Functional graph: planet -> its dispositor (a planet name). Only planets
    # actually present in the chart are nodes; a dead-end is handled by _terminal_cycle.
    succ = {}
    for p in PLANETS_LIST:
        d = dispositor(chart, p)
        if d is not None:
            succ[p] = d
    present = list(succ.keys())

    # Membership: each present planet -> its terminal cycle; basin = funnel count.
    membership = {}
    basins = {}
    for p in present:
        cyc = _terminal_cycle(p, succ)
        membership[p] = cyc
        if cyc is not None:
            basins[cyc] = basins.get(cyc, 0) + 1

    exchanges = get_all_interchanges(chart)

    themes = []
    for cyc, basin in basins.items():
        cycle_planets = sorted(cyc)
        houses = sorted({house_of(chart, p) for p in cycle_planets
                         if house_of(chart, p) is not None})
        sem_key, classification = classify_house_set(houses)
        is_exchange = len(cycle_planets) == 2
        dusthana = [h for h in houses if h in DUSTHANA_HOUSES]
        themes.append({
            "cycle_planets": cycle_planets,
            "occupied_houses": houses,
            "basin": basin,
            "cycle_size": len(cycle_planets),
            "is_exchange": is_exchange,
            "severity_key": sem_key,
            "classification": classification,
            "dusthana_houses": dusthana,
        })

    # Dominant-first (hardening H4 — PINNED, deterministic sort key):
    #   1. larger basin first (more of the chart funnels here)
    #   2. an exchange (2-cycle Parivartana) before a non-exchange of equal basin
    #   3. smaller cycle first (a tighter theme reads as more focused)
    #   4. lowest occupied house first (stable final tiebreak)
    themes.sort(key=lambda t: (
        -t["basin"],
        0 if t["is_exchange"] else 1,
        t["cycle_size"],
        t["occupied_houses"][0] if t["occupied_houses"] else 99,
    ))

    # Cross-link 2-cycle themes to the matching Parivartana record's houses so a
    # theme and its exchange card never disagree (spec L11/L12 R4).
    interchange_pairs = {
        frozenset((rec[0], rec[3])): rec for rec in exchanges["interchanges"]
    }
    # A dispositor 2-cycle is ALWAYS a Parivartana (dispositor(A)==B means A sits in
    # a B-ruled sign, so a 2-cycle is exactly mutual sign rulership). exchange_record
    # is therefore None only when the chart has no Ascendant (get_all_interchanges
    # returns [] with no house frame). Set on EVERY theme for a stable schema.
    for t in themes:
        t["exchange_record"] = (
            interchange_pairs.get(frozenset(t["cycle_planets"])) if t["is_exchange"] else None
        )

    return themes
