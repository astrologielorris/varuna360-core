# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Cross-chart Tajika service (GUI-free).
======================================

Thin, dependency-light service layer over the cross-chart engine entry point
``calculate_transit_aspects`` (``tajika.py``). It exists so that CLI callers
now (``find_eclipse``) and GUI/web callers later consume ONE implementation of
cross-chart Tajika, without importing from ``pro/AI_tools/analysis/`` (those
analysis scripts are entry points, not libraries). See SPEC-TJK-001 (v1.6)
section 5.1.

Base / overlay mapping
----------------------
- **Base chart** = the reference chart (natal in the eclipse case). Maps to the
  engine's ``natal_chart`` parameter and to the LEFT chart in the shared
  comparison widget (SPEC-CMP-001).
- **Overlay chart** = the second chart laid over the base (eclipse, solar
  return, live transit, partner's natal). Maps to the engine's
  ``transit_chart`` parameter and the RIGHT chart.

The engine parameter names (``natal_chart`` / ``transit_chart``) are kept
as-is; this module documents the mapping instead of renaming.

Direction views
---------------
The engine computes BOTH directions in one call (the virupa curve is
asymmetric, so the two views differ in virupas for the same pair):
- ``overlay_to_base``  (engine ``transit_to_natal``): overlay planets aspect
  base planets — the astrologically primary "what does this event do to my
  chart" view.
- ``base_to_overlay``  (engine ``natal_to_transit``): base planets aspect
  overlay planets — the reverse view, for completeness.

In BOTH views the JSON/record keys denote CHART MEMBERSHIP, never role:
``overlay_body`` is always the body from the overlay chart and ``base_body``
always the body from the base chart. The ASPECTOR is given by the direction
name itself (SPEC-TJK-001 section 5.4).

Applying / separating semantics (SPEC-TJK-001 section 5.5)
---------------------------------------------------------
In BOTH direction views, ``applying_status`` is driven solely by the OVERLAY
planet's ephemeris speed; the base (natal) position is frozen at speed 0.0.
The status always describes the OVERLAY body's motion relative to the static
base point — even in the ``base_to_overlay`` view, which is easy to misread as
"the base planet applies". It does not: the base chart does not move.

Overlay Ascendant absence (SPEC-TJK-001 section 5.7)
----------------------------------------------------
The engine excludes the overlay (transit-side) Ascendant as an aspecting body
and never uses it as a receiving target: the overlay chart's Ascendant does not
appear in cross-chart results at all, in either direction, even when the caller
supplies ``--lat/--lon``. The base (natal) Ascendant DOES receive aspects.
Consequently the missing-body pre-check requires every ``TAJIKA_PLANETS`` body
on the BASE chart but all EXCEPT the Ascendant on the OVERLAY chart.

Chart-context compatibility (SPEC-TJK-001 section 5.6)
------------------------------------------------------
Both charts MUST be built in the SAME context (Circle, sysflg, ayanamsa).
Passing charts built in different contexts is UNSUPPORTED and its output is
undefined; ``cross_chart_tajika`` guards against it and raises ``ValueError``.

Rahu/Ketu (SPEC-TJK-001 D4)
---------------------------
The nodes do not cast Tajika aspects; they are absent from ``TAJIKA_PLANETS``
by doctrine, so eclipse cross-chart results carry no node aspects despite
eclipses being node events.
"""

# tajika.py has no heavy top-level imports (its core/libaditya imports are all
# lazy, inside functions), so importing it here is safe in the Lite/web tree.
# It is NOT re-exported from the package __init__ we rely on, and the Lite build
# stubs that __init__ (build_lite.py:549), so import the sibling module directly.
try:  # normal package-member import (repo root or Lite root on sys.path)
    from AI_tools.AI_main_function.tajika import (
        calculate_transit_aspects,
        TAJIKA_PLANETS,
    )
except ImportError:  # bare sys.path: only the AI_main_function dir is importable
    from tajika import (  # type: ignore
        calculate_transit_aspects,
        TAJIKA_PLANETS,
    )


# CLI (kebab-case) enum <-> JSON (snake_case) view name <-> engine result key.
# CLI mapping (kebab -> snake) is a 1:1 "-"->"_" replacement done at the CLI
# layer; this module speaks the snake_case view names only.
_VIEW_TO_ENGINE_KEY = {
    "overlay_to_base": "transit_to_natal",
    "base_to_overlay": "natal_to_transit",
}
_VALID_DIRECTIONS = tuple(_VIEW_TO_ENGINE_KEY.keys())


def _chart_context_signature(chart):
    """Return (circle, sysflg, ayanamsa) for a chart, or None if unreadable.

    These are the REAL value attributes on ``chart.context``. Note that
    ``chart.ayanamsa`` is a bound METHOD (not a value) and charts have NO
    ``.mode`` attribute — guarding on either would be a silent no-op or a
    false mismatch, so we read the context fields explicitly.
    """
    ctx = getattr(chart, "context", None)
    if ctx is None:
        return None
    try:
        return (
            getattr(ctx, "circle", None),
            getattr(ctx, "sysflg", None),
            getattr(ctx, "ayanamsa", None),
        )
    except Exception:
        return None


def cross_chart_tajika(base_chart, overlay_chart, include_minor: bool = False) -> dict:
    """Cross-chart Tajika between a base chart and an overlay chart.

    Thin wrapper over ``calculate_transit_aspects(base_chart, overlay_chart)``.
    Returns the engine dict UNCHANGED (no re-keying); callers that need the
    stable JSON/text contract go through ``cross_aspects_json`` /
    ``format_cross_aspects_text``.

    Args:
        base_chart: libaditya Chart — the reference chart (natal). Maps to the
            engine's ``natal_chart`` parameter.
        overlay_chart: libaditya Chart — the overlay chart (eclipse/transit/…).
            Maps to the engine's ``transit_chart`` parameter.
        include_minor: also detect semi-sextile (30°) and quincunx (150°).

    Returns:
        The raw engine dict (``transit_to_natal``, ``natal_to_transit``,
        ``aspects_within_orb`` alias, ``matrix``, ``speeds``, ``is_transit``).

    Raises:
        ValueError: if the two charts were built in different contexts
            (Circle/sysflg/ayanamsa mismatch — SPEC-TJK-001 section 5.6), or if a
            chart is missing a REQUIRED body (SPEC-TJK-001 sections 5.7/5.8 — the
            bodies are not silently dropped). The base chart requires every body
            in ``TAJIKA_PLANETS``; the overlay chart requires all EXCEPT the
            Ascendant, which never participates in cross-chart aspects (5.7).
    """
    # ── Context guard (SPEC-TJK-001 section 5.6) ──
    # The engine reads tropical longitudes and derives sign relationships from
    # tropical degrees; mixing contexts yields undefined output. Compare the
    # real context signature and raise on mismatch when both are readable.
    base_sig = _chart_context_signature(base_chart)
    overlay_sig = _chart_context_signature(overlay_chart)
    if base_sig is not None and overlay_sig is not None and base_sig != overlay_sig:
        raise ValueError(
            "cross_chart_tajika: base and overlay charts were built in "
            "different contexts; this is unsupported (SPEC-TJK-001 §5.6). "
            "base (circle, sysflg, ayanamsa)={base} != overlay={overlay}".format(
                base=base_sig, overlay=overlay_sig
            )
        )

    # ── Missing-body pre-check (SPEC-TJK-001 sections 5.7 + 5.8) ──
    # The engine silently SKIPS bodies a chart lacks (its has_planet gate); the
    # spec requires an ERROR instead so a mis-built chart is caught, not quietly
    # under-reported. The overlay Ascendant NEVER participates (5.7 — it does not
    # aspect and is not a receiving target), so it is not required on the overlay
    # chart; the base chart still requires every body. Import has_planet lazily so
    # this module stays importable in a bare Lite/web tree that has no `core`
    # package on the path.
    from core.chart_helpers import has_planet
    _required = {
        "base": TAJIKA_PLANETS,
        "overlay": [b for b in TAJIKA_PLANETS if b != "Ascendant"],
    }
    for label, chart in (("base", base_chart), ("overlay", overlay_chart)):
        for body in _required[label]:
            if not has_planet(chart, body):
                raise ValueError(
                    "cross_chart_tajika: {label} chart is missing body "
                    "'{body}' (required by TAJIKA_PLANETS); refusing to "
                    "silently drop it (SPEC-TJK-001 §5.8).".format(
                        label=label, body=body
                    )
                )

    # base -> engine natal, overlay -> engine transit (SPEC-TJK-001 section 3).
    return calculate_transit_aspects(base_chart, overlay_chart, include_minor)


def _remap_record(record: dict) -> dict:
    """Copy a raw engine record and apply the field map to a NEW dict.

    Engine ``transit_body`` -> contract ``overlay_body``; engine
    ``natal_body`` -> contract ``base_body``. Every other field passes through
    unchanged. The copy is essential: forward records are SHARED by the engine's
    ``transit_to_natal``, ``aspects_within_orb`` and ``matrix`` views, so a
    ``pop()`` on the original would corrupt all three (SPEC-TJK-001 review).
    """
    out = dict(record)
    out["overlay_body"] = out.pop("transit_body")
    out["base_body"] = out.pop("natal_body")
    return out


def cross_aspects_json(result: dict, base_label: str, overlay_label: str,
                       include_minor: bool, directions) -> dict:
    """Build the stable cross-chart Tajika JSON contract (SPEC-TJK-001 §5.4).

    Args:
        result: the raw engine dict from ``cross_chart_tajika`` /
            ``calculate_transit_aspects``.
        base_label: label for the base (natal) chart, e.g. "Natal".
        overlay_label: label for the overlay chart, e.g.
            "Solar Eclipse 2026-08-12".
        include_minor: passed through explicitly — the engine result does NOT
            carry this flag, so it cannot be derived from ``result``.
        directions: iterable of snake_case view names to emit, each one of
            ``overlay_to_base`` / ``base_to_overlay``. Default surfaces emit a
            single view; ``both`` emits both. The set is chosen by the caller
            (the CLI ``--tajika-direction`` flag), never defaulted here.

    Returns:
        {
          "base_label": ...,
          "overlay_label": ...,
          "include_minor": bool,
          "direction_views": { "<view>": [record, ...], ... }
        }

    Each record carries the field map applied identically in every view
    (``overlay_body`` = overlay-chart body, ``base_body`` = base-chart body, in
    BOTH views) plus every other engine field unchanged. Arrays preserve the
    engine's virupas-descending sort. An emitted view with no aspects is an
    empty array, never a missing key.
    """
    direction_views = {}
    for view in directions:
        if view not in _VIEW_TO_ENGINE_KEY:
            raise ValueError(
                "cross_aspects_json: unknown direction {view!r}; expected one "
                "of {valid}".format(view=view, valid=_VALID_DIRECTIONS)
            )
        engine_key = _VIEW_TO_ENGINE_KEY[view]
        records = result.get(engine_key, [])
        direction_views[view] = [_remap_record(r) for r in records]

    return {
        "base_label": base_label,
        "overlay_label": overlay_label,
        "include_minor": include_minor,
        "direction_views": direction_views,
    }


# Columns rendered in the text tables (engine record fields).
_TEXT_HEADERS = [
    ("overlay", "Overlay"),
    ("base", "Base"),
    ("aspect", "Aspect"),
    ("symbol", "Sym"),
    ("virupas", "Virupas"),
    ("strength_pct", "Str%"),
    ("distance_from_exact", "Orb"),
    ("applying_status", "App/Sep"),
    ("open_secret", "Open/Secret"),
    ("relationship", "Relationship"),
]


def _render_row_cells(record: dict) -> dict:
    """Turn one raw engine record into display strings keyed by column id."""
    open_secret = record.get("open_secret")
    return {
        "overlay": str(record.get("transit_body", "")),
        "base": str(record.get("natal_body", "")),
        "aspect": str(record.get("aspect", "")),
        "symbol": str(record.get("symbol", "")),
        "virupas": "{:.1f}".format(record.get("virupas", 0.0)),
        "strength_pct": "{:.1f}".format(record.get("strength_pct", 0.0)),
        "distance_from_exact": "{:.1f}".format(record.get("distance_from_exact", 0.0)),
        "applying_status": str(record.get("applying_status", "")),
        "open_secret": "-" if open_secret is None else str(open_secret),
        "relationship": str(record.get("relationship", "")),
    }


def _format_one_direction(records, header_line: str, top_n) -> str:
    """Render a single direction table (header + aligned rows)."""
    lines = [header_line]
    rows = records if top_n is None else records[:top_n]
    if not rows:
        lines.append("  (no aspects within orb)")
        return "\n".join(lines)

    cells = [_render_row_cells(r) for r in rows]
    widths = {}
    for col_id, col_title in _TEXT_HEADERS:
        widths[col_id] = max(
            len(col_title), *(len(c[col_id]) for c in cells)
        )

    def _fmt(values):
        return "  ".join(
            values[col_id].ljust(widths[col_id]) for col_id, _ in _TEXT_HEADERS
        )

    lines.append("  " + _fmt({col_id: col_title for col_id, col_title in _TEXT_HEADERS}))
    lines.append("  " + "  ".join("-" * widths[col_id] for col_id, _ in _TEXT_HEADERS))
    for c in cells:
        lines.append("  " + _fmt(c))
    return "\n".join(lines)


def format_cross_aspects_text(result: dict, base_label: str, overlay_label: str,
                              direction: str, top_n=None) -> str:
    """Human-readable cross-chart Tajika table(s).

    Args:
        result: the raw engine dict from ``cross_chart_tajika``.
        base_label: label for the base (natal) chart.
        overlay_label: label for the overlay chart.
        direction: REQUIRED — one of ``overlay_to_base`` / ``base_to_overlay``
            / ``both``. There is NO default; every caller states its direction
            explicitly (the surface default lives at the CLI/GUI layer, never
            here — SPEC-TJK-001 section 5.1).
        top_n: if given, show only the N strongest aspects per direction table
            (text only; the JSON contract is never truncated).

    Returns:
        A formatted multi-line string.

    Raises:
        ValueError: if ``direction`` is not one of the three accepted values.
    """
    if direction == "both":
        views = ("overlay_to_base", "base_to_overlay")
    elif direction in _VIEW_TO_ENGINE_KEY:
        views = (direction,)
    else:
        raise ValueError(
            "format_cross_aspects_text: direction must be one of "
            "'overlay_to_base', 'base_to_overlay', 'both'; got {d!r}".format(
                d=direction
            )
        )

    blocks = []
    for view in views:
        records = result.get(_VIEW_TO_ENGINE_KEY[view], [])
        if view == "overlay_to_base":
            header = "{ov} → {ba}  (overlay planets aspecting base planets)".format(
                ov=overlay_label, ba=base_label
            )
        else:
            header = "{ba} → {ov}  (base planets aspecting overlay planets)".format(
                ba=base_label, ov=overlay_label
            )
        blocks.append(_format_one_direction(records, header, top_n))

    # Footnote (SPEC-TJK-001 section 5.5): applying/separating always describes
    # the OVERLAY body's motion; the base position is held fixed. This is easy
    # to misread in the base_to_overlay view.
    footnote = (
        "Note: App/Sep describes the OVERLAY body's motion; the base "
        "(natal) position is held fixed (SPEC-TJK-001 §5.5)."
    )
    return "\n\n".join(blocks) + "\n\n" + footnote
