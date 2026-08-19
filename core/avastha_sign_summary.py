# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Sign-avastha grouping spine — SPEC-AVA-003 Half A (the pure half).

Groups the Avastha panel's per-planet POS/NEG/TOTAL columns by the SIGN a
planet stands in, and then, inside a sign, by its HORA half and its TRIMSAMSA
band. The three layers (sign / hora / trimsamsa) are three PARTITIONS of the
same set of occupants: hora and trimsamsa do NOT nest (the Rishi band straddles
the hora boundary), so a planet belongs to exactly one hora half and exactly
one trimsamsa band, and at every layer the sub-blocks add up to the sign
(INV-9). The layer switch is a zoom over one set of planets, never a filter.

This module is a GROUPING CONSUMER of the avastha spines: every number comes
from ``core.avastha_totals.split_expression`` (pure view) or
``core.avastha_refined.refined_split`` (the four refined views). It computes NO
avastha math of its own (INV-1); it only re-groups and formats. The sign / block
TOTAL is always ``POS + NEG`` of the two left-to-right sums, never ``Σ total_p``
(INV-2), because the two float groupings differ in the last bit.

Discipline (INV-8, T-11): NO Qt, NO engine, NO ``AI_tools`` import — the same
purity ``core/avastha_totals.py`` keeps. The engine-facing half that resolves a
chart into occupants/memberships/sectors lives in
``AI_tools/AI_main_function/avastha_sign.py`` (Half B) and calls in here.
"""

from core.avastha_totals import AVASTHA_7, split_expression, display_split
from core.avastha_refined import refined_split, REFINE_KEYS

# View key -> the label the popup prints (== the panel tab button label,
# AvasthaController.VIEW_LABEL). Insertion order MUST equal
# AvasthaController.VIEW_ORDER (T-8). "cheshta" is the canonical key; its label
# drops the h to match the panel button ("Chesta").
VIEW_POPUP_LABEL = {
    "pure": "Avastha",   # the panel button says "Avastha", never "Pure" (Lorris 2026-08-18)
    "duc": "Duc",
    "dig": "Dig",
    "uccha": "Uccha",
    "cheshta": "Chesta",
}

# The three depths, surface -> deep; also the depth-ladder step order.
LAYERS = ("sign", "hora", "trimsamsa")
LAYER_LABEL = {"sign": "Sign", "hora": "Hora", "trimsamsa": "Trimsamsa"}
LAYER_CAPTION = {
    "sign": "whole 30 degrees",
    "hora": "two halves of 15 degrees",
    "trimsamsa": "five bands",
}

# The wheel's own key vocabulary for the two hora halves and the five bands
# (lowercase). TRIM_KEYS is in TRIMSAMSA table order for an ODD sign; the actual
# per-sign degree order is carried by ``sectors`` (Half B builds it), never by
# these tuples (INV-10).
HORA_KEYS = ("aditya", "naga")
TRIM_KEYS = ("gandharva", "rakshasa", "rishi", "yaksha", "apsara")


def sector_label(ring, type_key):
    """The one public sub-sector label helper (mockup §5.1).

    ("hora", "aditya") -> "Aditya hora"; ("hora", "naga") -> "Naga hora";
    ("trimsamsa", <band>) -> the bare title-cased band name ("Yaksha").
    An unknown (ring, type) pair raises ValueError.
    """
    if ring == "hora":
        if type_key == "aditya":
            return "Aditya hora"
        if type_key == "naga":
            return "Naga hora"
        raise ValueError(f"unknown hora type {type_key!r}")
    if ring == "trimsamsa":
        if type_key in TRIM_KEYS:
            return type_key.title()
        raise ValueError(f"unknown trimsamsa band {type_key!r}")
    raise ValueError(f"unknown ring {ring!r}")


def _validate_sectors(sectors):
    """Validate the ``sectors`` shape; raise ValueError on any deviation."""
    if not isinstance(sectors, dict) or set(sectors) != {"hora", "trimsamsa"}:
        raise ValueError("sectors must have exactly 'hora' and 'trimsamsa' keys")
    hora = sectors["hora"]
    trim = sectors["trimsamsa"]
    if len(hora) != 2 or len(trim) != 5:
        raise ValueError("sectors must have 2 hora entries and 5 trimsamsa entries")
    for entries, allowed, ring in ((hora, HORA_KEYS, "hora"),
                                   (trim, TRIM_KEYS, "trimsamsa")):
        seen = set()
        for ent in entries:
            if not {"key", "label", "span"} <= set(ent):
                raise ValueError(f"{ring} sector entry missing key/label/span")
            key = ent["key"]
            if key not in allowed:
                raise ValueError(f"unknown {ring} key {key!r}")
            if key in seen:
                raise ValueError(f"duplicate {ring} key {key!r}")
            seen.add(key)
            span = ent["span"]
            if (not isinstance(span, (tuple, list)) or len(span) != 2
                    or not all(isinstance(v, int) for v in span)):
                raise ValueError(f"{ring} span must be two integers, got {span!r}")


def _sector_keys(sectors, layer):
    """Ordered list of sub-sector keys for ``layer`` from ``sectors``."""
    return [ent["key"] for ent in sectors[layer]]


def summarize_sign(sign, view, occupants, memberships, sectors, planet_order,
                   matrix, dignity_data, shame_pairs, balas=None,
                   focus=None, others=()):
    """Build the sign-avastha summary dict (SPEC-AVA-003 §3.4 Half A).

    TRUSTS the resolved lists (occupancy, memberships, sectors come from the
    engine-facing Half B) but VALIDATES their shape so a caller bug fails loudly
    instead of printing plausible-but-wrong numbers.

    Every row's ``pos``/``neg`` is the planet's full RECEIVED column in ``view``
    (INV-1); the sign trio is the left-to-right sum of the rows, TOTAL = POS +
    NEG (INV-2). ``focus`` and ``others`` are passed through untouched — the
    pure half cannot know them.
    """
    if view not in VIEW_POPUP_LABEL:
        raise ValueError(f"unknown view {view!r}; expected one of {list(VIEW_POPUP_LABEL)}")

    if list(planet_order) != AVASTHA_7:
        raise ValueError(
            "planet_order must be exactly AVASTHA_7 in order; got "
            f"{list(planet_order)!r}")

    occ = list(occupants)
    if len(set(occ)) != len(occ):
        raise ValueError(f"occupants must be unique; got {occ!r}")
    if not set(occ) <= set(AVASTHA_7):
        raise ValueError(f"occupants must be a subset of AVASTHA_7; got {occ!r}")

    _validate_sectors(sectors)
    hora_keys = set(_sector_keys(sectors, "hora"))
    trim_keys = set(_sector_keys(sectors, "trimsamsa"))

    for p in occ:
        mem = memberships.get(p)
        if not mem or "hora" not in mem or "trimsamsa" not in mem:
            raise ValueError(f"occupant {p!r} has no hora/trimsamsa membership")
        if mem["hora"] not in hora_keys:
            raise ValueError(f"occupant {p!r} hora {mem['hora']!r} not in sectors")
        if mem["trimsamsa"] not in trim_keys:
            raise ValueError(f"occupant {p!r} trimsamsa {mem['trimsamsa']!r} not in sectors")

    refined = view != "pure"
    if refined:
        key = view  # canonical key is the refined field selector (REFINE_KEYS)
        if balas is None:
            raise ValueError(f"view {view!r} is refined; balas is required")
        field = REFINE_KEYS[key]
        for name in planet_order:
            entry = (balas or {}).get(name)
            if not entry or field not in entry:
                raise ValueError(
                    f"balas missing {field!r} for {name!r} (refined view {view!r})")

    if focus is not None:
        if (not isinstance(focus, dict) or focus.get("layer") not in ("hora", "trimsamsa")
                or "key" not in focus):
            raise ValueError(f"focus must be None or {{layer,key}}; got {focus!r}")
        valid = hora_keys if focus["layer"] == "hora" else trim_keys
        if focus["key"] not in valid:
            raise ValueError(
                f"focus key {focus['key']!r} not in sectors[{focus['layer']!r}]")

    rows = []
    for p in planet_order:
        if p not in occ:
            continue
        if refined:
            pos, neg = refined_split(p, planet_order, matrix, dignity_data,
                                     shame_pairs, balas, view)
        else:
            pos, neg = split_expression(p, planet_order, matrix, dignity_data,
                                        shame_pairs)
        mem = memberships[p]
        in_focus = (focus is not None and mem[focus["layer"]] == focus["key"])
        rows.append({
            "planet": p,
            "pos": pos,
            "neg": neg,
            "total": pos + neg,
            "hora": mem["hora"],
            "trimsamsa": mem["trimsamsa"],
            "in_focus": in_focus,
        })

    pos_sum = sum((r["pos"] for r in rows), 0.0)
    neg_sum = sum((r["neg"] for r in rows), 0.0)

    return {
        "sign": sign,
        "view": view,
        "view_label": VIEW_POPUP_LABEL[view],
        "sectors": sectors,
        "focus": focus,
        "planets": rows,
        "pos": pos_sum,
        "neg": neg_sum,
        "total": pos_sum + neg_sum,  # NEVER Σ row["total"] (INV-2)
        "others": list(others),
    }


def layer_blocks(summary, layer):
    """The zoom: 1 (sign) / 2 (hora) / 5 (trimsamsa) blocks over the WHOLE row set.

    A block's ``pos``/``neg`` are the left-to-right sums of ITS rows (an empty
    block is 0.0/0.0/0.0); ``total`` = pos + neg. The sign block carries the
    summary's own trio (not a re-sum) so the surface always equals the INV-2
    sign trio. ``focused`` is set only on the focus layer's focused key.
    """
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}; expected one of {LAYERS}")

    focus = summary.get("focus")
    rows = summary["planets"]

    if layer == "sign":
        return [{
            "layer": "sign",
            "key": summary["sign"],
            "label": summary["sign"],
            "span": (0, 30),
            "pos": summary["pos"],
            "neg": summary["neg"],
            "total": summary["total"],
            "planets": list(rows),
            "focused": False,
        }]

    blocks = []
    for ent in summary["sectors"][layer]:
        key = ent["key"]
        brows = [r for r in rows if r[layer] == key]
        pos = sum((r["pos"] for r in brows), 0.0)
        neg = sum((r["neg"] for r in brows), 0.0)
        focused = (focus is not None and focus["layer"] == layer
                   and focus["key"] == key)
        blocks.append({
            "layer": layer,
            "key": key,
            "label": ent["label"],
            "span": tuple(ent["span"]),
            "pos": pos,
            "neg": neg,
            "total": pos + neg,
            "planets": brows,
            "focused": focused,
        })
    return blocks


def _decimals_for(view):
    return 0 if view == "pure" else 1


def _planets_label(n):
    return f"Sign ({n} planet{'s' if n != 1 else ''})"


def display_rows(summary):
    """Per-occupant display strings, in planet_order (SPEC-AVA-003 §11.1, INV-11).

    Each row is ``(planet, pos_s, neg_s, total_s)`` = ``display_split(pos, neg,
    decimals)`` with the SAME ``decimals`` rule as the Avastha panel (0 pure, 1
    refined), so a row equals that planet's POS/NEG/TOTAL cells in the panel
    bit-for-bit (the reader can lay the popup next to the panel and match)."""
    decimals = _decimals_for(summary["view"])
    out = []
    for r in summary["planets"]:
        pos_s, neg_s, total_s = display_split(r["pos"], r["neg"], decimals)
        out.append((r["planet"], pos_s, neg_s, total_s))
    return out


def display_sum(rows, decimals):
    """Round-then-sum of DISPLAYED rows (SPEC-AVA-003 §11.1, INV-12).

    ``rows`` is a list of ``(planet, pos_s, neg_s, total_s)`` display tuples;
    returns ``(pos_s, neg_s, total_s)`` = the arithmetic sums of ``float()`` of
    the displayed strings, formatted with the same ``decimals``. This is what a
    reader gets by adding the table's own integers, so a sum row reconciles with
    the panel column-by-column; ``POS + NEG == TOTAL`` still holds because each
    row's ``neg_s`` was derived as ``total_s − pos_s`` (display_split). The
    summary dict's float ``pos``/``neg``/``total`` (INV-2, sum-then-round) are
    UNTOUCHED and stay the CLI/JSON truth; only these displayed sums change."""
    fmt = f"{{:.{int(decimals)}f}}"

    def _f(value):
        # Normalise negative zero so a sum row never renders "-0" (matches
        # display_split; not triggerable on grid-aligned inputs, but a caller
        # summing floats that cancel could otherwise produce it). Opus review #3.
        s = fmt.format(value)
        return fmt.format(0.0) if float(s) == 0.0 else s

    pos = sum(float(r[1]) for r in rows)
    neg = sum(float(r[2]) for r in rows)
    total = sum(float(r[3]) for r in rows)
    return _f(pos), _f(neg), _f(total)


def layer_display(summary, layer):
    """The ordered display model both the dialog and the CLI render (§11.1).

    Returns ``{"status": <str>, "items": [item, ...]}`` where every item is a
    dict with a ``kind``: ``status`` (the one bold ``<View> view · <Layer>
    layer`` line), ``row`` (planet + pos/neg/total display strings), ``sum`` /
    ``subsum`` / ``sign_sum`` (a labelled round-then-sum row), ``section_header``
    (a hora half or a trimsamsa band header, label + degree span), ``empty_half``
    / ``empty_bands`` / ``empty`` / ``other`` (a muted one-line note). Numeric
    items carry a ``focused`` flag; a run of adjacent ``focused`` items is the
    clicked block (the dialog draws them as one gold card). The dialog paints
    this; ``format_sign_block_lines`` prints it verbatim (INV-7)."""
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}; expected one of {LAYERS}")

    view = summary["view"]
    decimals = _decimals_for(view)
    status = f"{summary['view_label']} view · {LAYER_LABEL[layer]} layer"
    items = [{"kind": "status", "text": status}]

    all_rows = display_rows(summary)
    by_planet = {r[0]: r for r in all_rows}
    n = len(summary["planets"])

    def _add_others():
        for name in summary["others"]:
            items.append({"kind": "other", "text": f"{name} · here, not in the matrix"})

    if not summary["planets"]:
        # An empty sign has nothing to sum: only the muted note (and any others),
        # never a "Sign (0 planets)" row. The "Sign (n)" sum row appears at every
        # layer that HAS occupants; a zero-occupant sign is the deliberate
        # exception (Opus review #5).
        items.append({
            "kind": "empty",
            "text": f"no planet of the avastha matrix in {summary['sign']}"})
        _add_others()
        return {"status": status, "items": items}

    def _sum_item(kind, label, rows_):
        ps, ns, ts = display_sum(rows_, decimals)
        return {"kind": kind, "label": label, "pos": ps, "neg": ns, "total": ts}

    if layer == "sign":
        for r in all_rows:
            items.append({"kind": "row", "planet": r[0], "pos": r[1],
                          "neg": r[2], "total": r[3], "focused": False})
        items.append({**_sum_item("sum", _planets_label(n), all_rows),
                      "focused": False})
    else:
        empty_labels = []
        empty_focused = False
        for block in layer_blocks(summary, layer):
            brows = [by_planet[r["planet"]] for r in block["planets"]]
            focused = block["focused"]
            span = f"{block['span'][0]}° to {block['span'][1]}°"
            if brows:
                items.append({"kind": "section_header", "label": block["label"],
                              "span": span, "focused": focused})
                for br in brows:
                    items.append({"kind": "row", "planet": br[0], "pos": br[1],
                                  "neg": br[2], "total": br[3], "focused": focused})
                # D-21: a section (hora half or trimsamsa band) prints a sum row
                # IFF it holds >= 2 planets. With one planet the row IS the total,
                # so a sum row would only repeat it and bloat the popup (Lorris's
                # "cut the fluff" + the <= 360 compactness AC). The bold
                # "Sign (n planets)" row below is the blocks-add-up check at every
                # layer regardless.
                if len(brows) >= 2:
                    sub_label = "Half total" if layer == "hora" else "Band total"
                    items.append({**_sum_item("subsum", sub_label, brows),
                                  "focused": focused})
            elif layer == "hora":
                items.append({"kind": "empty_half",
                              "text": f"{block['label']} · {span} · empty",
                              "focused": focused})
            else:
                empty_labels.append(block["label"])
                empty_focused = empty_focused or focused
        if layer == "trimsamsa" and empty_labels:
            items.append({"kind": "empty_bands",
                          "text": f"Empty bands: {', '.join(empty_labels)}",
                          "focused": empty_focused})
        items.append({**_sum_item("sign_sum", _planets_label(n), all_rows),
                      "focused": False})

    _add_others()
    return {"status": status, "items": items}


def _tab_line(label, pos_s, neg_s, total_s):
    return f"  {label:<18}{pos_s:>8}{neg_s:>8}{total_s:>8}"


def format_sign_block_lines(summary, layer):
    """Plain-text lines for the CLI, rendered from ``layer_display`` (§11.1).

    line 0 is the status line ``<View> view · <Layer> layer``; then a
    Planet/POS/NEG/TOTAL table with labelled round-then-sum rows, degree-span
    section headers (``▸ `` when the block is focused), a single folded
    ``Empty bands: …`` note, and the D-4 ``others`` notes last. The dialog paints
    the SAME model, so the CLI text and the popup never diverge (INV-7)."""
    model = layer_display(summary, layer)
    lines = []
    for it in model["items"]:
        kind = it["kind"]
        if kind == "status":
            lines.append(it["text"])
        elif kind == "row":
            lines.append(_tab_line(it["planet"], it["pos"], it["neg"], it["total"]))
        elif kind in ("sum", "subsum", "sign_sum"):
            lines.append(_tab_line(it["label"], it["pos"], it["neg"], it["total"]))
        elif kind == "section_header":
            prefix = "▸ " if it["focused"] else ""
            lines.append(f"{prefix}{it['label']} · {it['span']}")
        else:  # empty / empty_half / empty_bands / other
            prefix = "▸ " if it.get("focused") else ""
            lines.append(f"{prefix}{it['text']}")
    return lines
