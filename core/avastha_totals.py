# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Pure avastha totals math (SPEC-AVW-001 T1).

GUI-free extraction of the avastha uplifted/afflicted/total/SIGN-color logic
that previously lived only inside the Qt files
(apps/widgets/info_panel_dialog.py, apps/widgets/panel_controllers/avastha_controller.py).

This module has NO Qt and NO engine dependencies. It operates purely on the
plain dicts returned by AI_tools.AI_main_function.avastha.get_drishti_yuti_data
(matrix, dignity_data, shame_pairs), so it can be imported verbatim by:
  - the desktop GUI (info_panel_dialog, avastha_controller, ...),
  - the FastAPI backend (backend/astrology-api),
  - the show_avastha CLI,
guaranteeing byte-for-byte total parity across all three surfaces.

TOKEN DIRECTION (SPEC-AVW-001 2.2, the classic transposition trap):
  matrix is keyed (aspecting=actor, aspected=target); the relationship stored is
  what the TARGET receives from the ACTOR. A planet's total sums, over every other
  planet, the contribution of matrix[(other, target)]. In the web grid the row is
  the TARGET, so a web cell reads matrix[(column, row)]; the per-row Total is
  planet_total(target=row).
"""

# The 7 aspecting planets that form the avastha matrix, in canonical order.
AVASTHA_7 = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# A planet always aspects its own position at zero distance, which is worth the
# full 60 virupas — the diagonal "self-conjunction" every planet starts from
# (SPEC-AVA-001 rev3, 2026-07-18). Before this, the pure total was only the net
# of received aspects, so a planet with no dignity started from a void.
SELF_BASE = 60.0


def dignity_multiplier(virupas):
    """Dignity as a multiplier on the planet's own base strength.

    multiplier = 1 + virupas/60: exaltation(60) -> x2, mulatrikona(45) -> x1.75,
    own sign(30) -> x1.5, no dignity / debilitation(0) -> x1. On the pure-view
    base of 60 this is identical to adding the virupas (60 x 2 = 60 + 60); on a
    refined-view bala it scales proportionally instead of adding a flat bonus.
    """
    return 1.0 + float(virupas or 0) / 60.0


def split_expression(target, planet_order, matrix, dignity_data, shame_pairs):
    """Split avastha into uplifted (positive) and afflicted (negative) totals.

    Shared by the desktop panel, popup dialogs, karakas / planetary-condition
    panels, the web payload, and the CLI (SPEC-AVW-001 T1 parity spine).
    - uplifted = SELF_BASE x dignity multiplier (the planet's own strength:
      60 alone, 120 exalted, 105 mulatrikona, 90 own sign),
      + FRIEND virupas cast onto it.
    - afflicted = - ENEMY virupas cast onto it, - 60 per shame pair.
    - DUAL and NEUTRAL relationships contribute 0.
    - Only entries with virupas > 0 count.
    A total below zero therefore means the afflictions exceeded the planet's
    entire own strength, not merely that enemies outweighed friends.
    """
    dig = dignity_data.get(target)
    up = SELF_BASE * dignity_multiplier(dig["virupas"] if dig else 0)
    aff = 0.0
    for other in planet_order:
        if other == target:
            continue
        entry = matrix.get((other, target))
        if not entry or entry["virupas"] <= 0:
            continue
        if (other, target) in shame_pairs:
            aff -= 60
        elif entry["relationship"] == "DUAL":
            pass
        elif entry["relationship"] == "FRIEND":
            up += entry["virupas"]
        elif entry["relationship"] == "ENEMY":
            aff -= entry["virupas"]
    return up, aff


def planet_total(target, planet_order, matrix, dignity_data, shame_pairs):
    """The planet's net avastha total = uplifted + afflicted.

    Equal to the desktop Avastha panel's TOTALS-row value for the planet's column
    (avastha_controller.py col_total math), by construction.
    """
    up, aff = split_expression(target, planet_order, matrix, dignity_data, shame_pairs)
    return up + aff


def split_expression_cast(actor, planet_order, matrix, dignity_data, shame_pairs):
    """Split what ACTOR casts out into (uplifted, afflicted) — the ROW direction.

    The exact mirror of ``split_expression``: the only change is which key of the
    (actor, target) matrix is held fixed. ``split_expression`` fixes the TARGET
    and sums a column (what a planet RECEIVES); this fixes the ACTOR and sums a
    row (what a planet CASTS at the other six). Every classification rule —
    shame precedence, DUAL cancelling, NEUTRAL contributing nothing, the
    virupas > 0 gate — is byte-identical, which is what makes the grand totals
    of the two directions agree (SPEC-AVA-002 INV-1b).

    The diagonal is included, exactly as in the received direction (D-5). It is
    not double-counted: a planet's own base enters its row total once and its
    column total once, and those are two different numbers. The GRAND total
    counts each of the seven diagonals exactly once whichever way it is summed.

    Shame is stored as a DIRECTED (shamer, target) pair, so in this direction the
    -60 falls on the cruel planet that inflicts it (D-8, "cruel costs cruel") and
    a shamed benefic carries nothing in its row.

    Structurally incomplete by construction (INV-6): only the seven aspecting
    planets have rows, but Rahu and Ketu ARE matrix targets. A row total is
    therefore "what this planet casts at the other six", not "what it casts".
    """
    dig = dignity_data.get(actor)
    up = SELF_BASE * dignity_multiplier(dig["virupas"] if dig else 0)
    aff = 0.0
    for target in planet_order:
        if target == actor:
            continue
        entry = matrix.get((actor, target))
        if not entry or entry["virupas"] <= 0:
            continue
        if (actor, target) in shame_pairs:
            aff -= 60
        elif entry["relationship"] == "DUAL":
            pass
        elif entry["relationship"] == "FRIEND":
            up += entry["virupas"]
        elif entry["relationship"] == "ENEMY":
            aff -= entry["virupas"]
    return up, aff


def planet_cast_total(actor, planet_order, matrix, dignity_data, shame_pairs):
    """The planet's net CAST total = uplifted + afflicted, summed along its row.

    The right-hand TOTAL column of the expanded fullscreen Avastha table
    (SPEC-AVA-002), as ``planet_total`` is to the bottom TOTAL row.
    """
    up, aff = split_expression_cast(actor, planet_order, matrix, dignity_data, shame_pairs)
    return up + aff


def display_split(pos, neg, decimals):
    """Display-layer rounding of the POS/NEG/TOTAL trio that keeps them adding up.

    Rounding pos, neg, and total independently can break the on-screen
    invariant TOTAL = POS + NEG (e.g. pos 1.26 -> 1.3, neg -0.04 -> -0.0,
    total 1.22 -> 1.2, and 1.3 - 0.0 != 1.2). Rule: POS and TOTAL are rounded
    normally, and the displayed NEG is derived as displayed TOTAL - displayed
    POS, absorbing the residue (at most one display unit). TOTAL keeps its
    canonical rounding because every other surface (karakas, popups, batch
    reports, website) quotes it; when neg == 0 the derivation is exact.
    A zero NEG renders unsigned ("0", never "-0"), per SPEC-AVA-001 §12.4.

    Returns (pos_str, neg_str, total_str). Shared by the GUI panel and the
    show_avastha CLI text renderers (Rule 24 parity).
    """
    fmt = f"{{:.{int(decimals)}f}}"
    pos_s = fmt.format(pos)
    total_s = fmt.format(pos + neg)
    neg_s = fmt.format(float(total_s) - float(pos_s))
    if float(neg_s) == 0.0:
        neg_s = fmt.format(0.0)
    if float(pos_s) == 0.0:
        pos_s = fmt.format(0.0)
    if float(total_s) == 0.0:
        total_s = fmt.format(0.0)
    return pos_s, neg_s, total_s


def sign_total_category(total):
    """SIGN-row color category from the planet total.

    Mirrors avastha_controller.py: positive total -> "FRIEND" (green),
    negative -> "ENEMY" (red), zero -> "NEUTRAL". These are the same category
    keys the AvasthaHighlightDelegate colors by.
    """
    if total > 0:
        return "FRIEND"
    if total < 0:
        return "ENEMY"
    return "NEUTRAL"
