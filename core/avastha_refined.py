# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Pure avastha strength-refinement math (SPEC-AVA-001).

GUI-free / engine-free sibling of ``core/avastha_totals.py``. It refines the raw
drishti/yuti matrix by scaling every influence by the INFLUENCER's strength bala
(Dig / Uccha / Cheshta, plus the Duc mean), producing the Duc/Dig/Uccha/Cheshta
"refined views" the desktop Avastha panel cycles through.

It operates purely on the plain dicts returned by
``AI_tools.AI_main_function.avastha.get_drishti_yuti_data`` (matrix, dignity_data,
shame_pairs) plus a ``{planet: {digbala,uccha,chesta,duc_bala}}`` bala map (the
Strength panel's ``core.bala_calculator.get_all_bala_data`` output), so the GUI,
the show_avastha CLI, and any future web export share one implementation.

Normative math (SPEC-AVA-001 section 3, rev3 diagonal + rev4.1 §13 DUAL +
rev5 §3 shame), per refinement key K. Every cell resolves to a GIVE side and a
TAKE side, and which sides are switched on is the whole classification:

    S_K(actor) = bala_K(actor)              # subha (0..60), what it HAS
    A_K(actor) = 60 - S_K(actor)            # asubha, what it LACKS
    give = virupas * S_K(actor) / 60   when the actor is benevolent to the target
    take = virupas * A_K(actor) / 60   when the actor drains the target
    net  = give - take                 -> flows into the target's TOTAL

    FRIEND  (+)  give on,  take off
    ENEMY   (-)  give off, take on
    DUAL    (±)  give on,  take on   (rev4.1 §13; they cancel ONLY at bala 30)
    NEUTRAL (~)  both off           -> shown at S-scale, contributes 0
    shame   (!)  FORCES take on, whatever the base relationship (rev5, 2026-08-02)

Shame subtracts EXACTLY what a starved (ENEMY) affliction subtracts — no more,
no less. That is what "shame is a visual marker" always meant (Lorris,
restated 2026-08-02): the ``!`` marks a psychological layer the astrologer
reads on top, so shame does not remove MORE than starved. It was mis-read as
"removes nothing", which is what rev5 corrects.

So a shaming planet drains by its LACK, on the starved scale: a Mars at Dig
18.5 removes 60-18.5 = 41.5, not 18.5 — being weak is what makes the shame
bite. Two consequences fall out of routing it through ``take``:
  - a NEUTRAL shamer, which used to contribute 0, now subtracts. Neutrality
    means it does not HELP; it never meant the shame stops hurting.
  - a FRIEND or DUAL shamer gives and takes at once, exactly like a DUAL: the
    friendship still hands strength over while the shame drains it.
  - an ENEMY shamer is unchanged — its take was already the starved amount, and
    shame switches on a side that is already on rather than stacking a second
    drain. Shame never exceeds starved; that is the whole point.

    diagonal       = bala_K(target) * dignity multiplier
                     (EX x2, MK x1.75, OH x1.5, none/debilitated x1 —
                      core.avastha_totals.dignity_multiplier; dignity AMPLIFIES
                      the planet's own strength, it is no longer a fixed 60/45/30)
    total(target)  = diagonal + sum(give) - sum(take)

TOKEN DIRECTION (same trap as avastha_totals): matrix is keyed
(aspecting=ACTOR, aspected=TARGET); the relationship stored is what the TARGET
receives from the ACTOR. A cell's refined value scales by the ACTOR's bala.
"""

# Both modules are pure/GUI-free, so this import keeps the multiplier single-sourced.
from core.avastha_totals import dignity_multiplier

# The 7 aspecting planets that form the avastha matrix, in canonical order.
AVASTHA_7 = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# Relationship -> display symbol. Hardcoded here (NOT imported from
# AI_tools.AI_main_function.avastha) to keep this module engine-free / pure, the
# same discipline core/avastha_totals.py follows. Must stay byte-identical to
# avastha.REL_SYMBOL; a drift test in test_avastha_refined guards it.
REL_SYMBOL = {"FRIEND": "+", "ENEMY": "-", "NEUTRAL": "~", "DUAL": "±", "N/A": " "}

# Refinement key -> the field name in a get_all_bala_data() per-planet dict.
REFINE_KEYS = {
    "dig": "digbala",
    "uccha": "uccha",
    "cheshta": "chesta",
    "duc": "duc_bala",
}


def _bala_for(planet, balas, key):
    """The bala value (0..60) of ``planet`` for refinement key ``key``.

    Missing planet or field -> 0.0 (treated as fully immature: helps nothing,
    harms fully), which is the safe conservative default.
    """
    field = REFINE_KEYS[key]
    entry = (balas or {}).get(planet) or {}
    try:
        val = float(entry.get(field, 0.0))
    except (TypeError, ValueError):
        return 0.0
    # Balas are defined on 0..60; clamp defensively so subha/asubha stay complementary.
    if val < 0.0:
        return 0.0
    if val > 60.0:
        return 60.0
    return val


def refine_value(virupas, actor_bala, is_help):
    """Scale a raw yuti ``virupas`` by the actor's strength.

    help  -> virupas * subha / 60   (a strong benefic helps more)
    harm  -> virupas * asubha / 60  (a weak malefic harms more), asubha = 60 - bala
    """
    if is_help:
        return virupas * actor_bala / 60.0
    return virupas * (60.0 - actor_bala) / 60.0


def refined_diag_value(target, dignity_data, balas, key):
    """Diagonal for ``target``: own bala_K x dignity multiplier.

    Dignity amplifies the planet's own strength instead of replacing it with a
    fixed virupa (SPEC-AVA-001 rev3): exaltation x2, mulatrikona x1.75, own sign
    x1.5. ``dignity_data`` contains ONLY those three dignities (debilitation is
    filtered out by get_drishti_yuti_data), so dignity-less / debilitated planets
    get their bare bala (x1).

    Returns (value: float, dignity_type: str | None).
    """
    dig = dignity_data.get(target) or {}
    mult = dignity_multiplier(dig.get("virupas", 0))
    return _bala_for(target, balas, key) * mult, dig.get("type")


def refine_cell(actor, target, matrix, shame_pairs, balas, key):
    """Refined value for one off-diagonal cell (actor -> target).

    Returns None for an empty cell, else a dict:
        {value, symbol, relationship, category, is_shame, in_total, signed,
         give, take, two_sided}
    where ``signed`` is the +/-/0 contribution to the target's column total,
    ``give`` the amount added to the target's POS row, and ``take`` the amount
    subtracted via the target's NEG row (both >= 0). By construction
    ``signed == give - take``. ``two_sided`` is True when both sides are switched
    on — a DUAL (rev4.1 §13) or a shame cast over a FRIEND/DUAL base (rev5) —
    and those are the cells whose ``value`` is the NET rather than a magnitude.

    ``symbol`` reports the cell's ARITHMETIC, not its raw relationship, because a
    shame cast changes the arithmetic: a NEUTRAL that shames renders "-" (it
    subtracts) and a FRIEND that shames renders "±" (it does both). The raw
    relationship stays available under ``relationship`` for callers that need it.
    """
    entry = matrix.get((actor, target))
    if entry is None:
        return None
    virupas = entry.get("virupas", 0)
    is_yuti = entry.get("is_yuti", False)
    if not is_yuti and virupas <= 0:
        return None

    rel = entry["relationship"]
    is_shame = (actor, target) in shame_pairs
    actor_bala = _bala_for(actor, balas, key)

    # Which of the two sides is switched on. Classified STRUCTURALLY (from the
    # relationship and the shame flag) rather than by testing give/take against
    # zero: at the extremes of the bala range a live side can legitimately
    # compute to 0.0 (a FRIEND at bala 0 gives nothing, a shamer at bala 60
    # takes nothing) and a value test would silently reclassify the cell and
    # flip its symbol there.
    gives = rel in ("FRIEND", "DUAL")
    # rev5 (2026-08-02): shame FORCES the take side on. Over an ENEMY this is a
    # no-op (already on, and it is the same A-scaled amount — shame does not
    # stack a second drain); over a NEUTRAL it is the whole fix.
    takes = rel in ("ENEMY", "DUAL") or is_shame

    give = refine_value(virupas, actor_bala, is_help=True) if gives else 0.0
    take = refine_value(virupas, actor_bala, is_help=False) if takes else 0.0
    signed = give - take
    in_total = gives or takes
    two_sided = gives and takes

    if two_sided:
        # DUAL, or a shame cast over a FRIEND/DUAL base: the cell displays the
        # NET (D13, may be negative); the two sides cancel only at bala 30.
        value = signed
        symbol = REL_SYMBOL["DUAL"]
    elif gives:
        value = give
        symbol = REL_SYMBOL["FRIEND"]
    elif takes:
        # Magnitude; the "-" symbol carries the sign, as it always has for ENEMY.
        value = take
        symbol = REL_SYMBOL["ENEMY"]
    else:  # NEUTRAL, N/A and not shaming — shown at S-scale, contributes 0
        value = refine_value(virupas, actor_bala, is_help=True)
        symbol = REL_SYMBOL.get(rel, " ")

    if is_shame:
        category = "SHAME"
    elif two_sided:
        category = "DUAL"
    elif gives:
        category = "FRIEND"
    elif takes:
        category = "ENEMY"
    else:
        category = "NEUTRAL"

    return {
        "value": value,
        "symbol": symbol,
        "relationship": rel,
        "category": category,
        "is_shame": is_shame,
        "in_total": in_total,
        "signed": signed,
        "give": give,
        "take": take,
        "two_sided": two_sided,
    }


def refined_total(target, planet_order, matrix, dignity_data, shame_pairs, balas, key):
    """Net refined column total for ``target`` = pos + neg from ``refined_split``.

    diagonal (own bala_K x dignity multiplier) + sum(give) - sum(take).
    NEUTRAL contributes 0 unless it shames. A shame cast subtracts the shamer's
    A-scaled LACK (rev5), which is the same amount an ENEMY subtracts — so a
    shame-marked ENEMY is unchanged, while a shame-marked NEUTRAL, which used to
    contribute nothing, now subtracts. The flat -60 remains exclusive to the
    pure view.

    Derived from the SAME accumulators as ``refined_split`` — an independent
    one-pass summation groups the floats differently and can diverge in the
    last bits, breaking the TOTAL = POS + NEG float-exact invariant (§12.3)
    for callers that use the two standalone functions together.
    """
    pos, neg = refined_split(target, planet_order, matrix, dignity_data,
                             shame_pairs, balas, key)
    return pos + neg


def refined_split(target, planet_order, matrix, dignity_data, shame_pairs, balas, key):
    """Split a refined column total into (pos, neg) — SPEC-AVA-001 §12.3 + §13.

    pos = diagonal (own bala_K x dignity multiplier) + Σ cell gives (S-scaled).
    neg = − Σ cell takes (A-scaled).
    There is still NO flat −60 term here (unlike the pure split_expression); a
    refined shame subtracts the shamer's A-scaled lack instead (rev5). A plain
    NEUTRAL contributes to NEITHER side; a DUAL, and a shame over a FRIEND/DUAL,
    contribute to BOTH and cancel only at bala 30. By construction
    pos + neg == refined_total, which is why the caller uses this pair as the
    exact source for the TOTAL row.
    """
    diag, _ = refined_diag_value(target, dignity_data, balas, key)
    pos = diag
    neg = 0.0
    for actor in planet_order:
        if actor == target:
            continue
        cell = refine_cell(actor, target, matrix, shame_pairs, balas, key)
        if cell is None:
            continue
        # give (FRIEND help + DUAL give) raises POS; take (ENEMY harm + DUAL
        # take) lowers NEG. NEUTRAL has give == take == 0. This keeps
        # pos + neg == diag + Σ(give - take) == refined_total, float-exact.
        pos += cell["give"]
        neg -= cell["take"]
    return pos, neg


def refined_matrix(planet_order, matrix, dignity_data, shame_pairs, balas, key):
    """Full refined view for one key.

    Returns:
        {
          "diagonal": {planet: (bala_K x dignity multiplier, dignity_type|None)},
          "cells":    {(actor, target): cell_dict},   # off-diagonal, non-empty only
          "pos":      {target: float},   # SPEC-AVA-001 §12.3 positive-only total
          "neg":      {target: float},   # SPEC-AVA-001 §12.3 negative-only total
          "totals":   {target: float},   # == pos + neg (float-exact invariant)
          "cast_pos": {actor: float},    # SPEC-AVA-002: the ROW direction
          "cast_neg": {actor: float},
          "cast_totals": {actor: float}, # == cast_pos + cast_neg (float-exact)
        }

    The cast_* dicts are keyed by ACTOR and the others by TARGET, and both use
    the same seven planet names — a consumer that reads the wrong one gets
    plausible numbers and no error, which is why the names carry the axis.
    They are regrouped from the SAME ``cells`` dict rather than recomputed: a
    cell already carries the actor-scaled ``give``/``take``, so summing by first
    key instead of second is bit-identical to a per-actor recompute and costs no
    second bala lookup (SPEC-AVA-002 T-5c).

    Note the refined row is scaled by ONE bala throughout (the actor's), where a
    refined column mixes seven. That is why the cast total is strictly increasing
    in the planet's own bala and the received total is monotone in nothing
    (SPEC-AVA-002 INV-3).
    """
    if key not in REFINE_KEYS:
        raise ValueError(f"unknown refinement key {key!r}; expected one of {list(REFINE_KEYS)}")

    diagonal = {
        p: refined_diag_value(p, dignity_data, balas, key) for p in planet_order
    }

    cells = {}
    for actor in planet_order:
        for target in planet_order:
            if actor == target:
                continue
            cell = refine_cell(actor, target, matrix, shame_pairs, balas, key)
            if cell is not None:
                cells[(actor, target)] = cell

    pos = {}
    neg = {}
    totals = {}
    for target in planet_order:
        p, n = refined_split(target, planet_order, matrix, dignity_data,
                             shame_pairs, balas, key)
        pos[target] = p
        neg[target] = n
        # TOTAL is defined as POS + NEG so the rev4 invariant holds float-exact.
        totals[target] = p + n

    # SPEC-AVA-002: the ROW direction, regrouped from the cells already built.
    # The diagonal seeds POS exactly as it does in the column direction (D-5).
    cast_pos = {a: diagonal[a][0] for a in planet_order}
    cast_neg = {a: 0.0 for a in planet_order}
    for (actor, _target), cell in cells.items():
        cast_pos[actor] += cell["give"]
        cast_neg[actor] -= cell["take"]
    cast_totals = {a: cast_pos[a] + cast_neg[a] for a in planet_order}

    return {"diagonal": diagonal, "cells": cells,
            "pos": pos, "neg": neg, "totals": totals,
            "cast_pos": cast_pos, "cast_neg": cast_neg,
            "cast_totals": cast_totals}
