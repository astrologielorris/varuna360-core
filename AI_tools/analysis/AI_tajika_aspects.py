#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""
AI Tajika Aspects - Western-style Orb-based Aspect Calculator
==============================================================
Calculate Tajika aspects (conjunction, sextile, square, trine, opposition)
for 11 bodies (Lg + 7 traditional + 3 outer planets) with planet-specific
Deeptamsa orbs.

Key Concept: Tajika Aspect System
----------------------------------
Tajika is a preserved branch of Turkish/Arabic astrology in India. Unlike
Vedic Graha Sphuta Drishti (continuous strength curves), Tajika uses:
- 5 discrete aspect types with orb-based "within aspect" logic
- Planet-specific Deeptamsas (orbs) averaged between pairs
- Sign-based relationship classification (Openly/Secretly Friendly/Inimical)
- 12-segment piecewise strength interpolation (0-60 virupas)

Usage (single chart):
    python AI_tools/analysis/AI_tajika_aspects.py                       # Default (Lorris.chtk)
    python AI_tools/analysis/AI_tajika_aspects.py "Sandra P.chtk"       # Specific chart
    python AI_tools/analysis/AI_tajika_aspects.py --screen 1            # Aspects matrix (default)
    python AI_tools/analysis/AI_tajika_aspects.py --screen 2            # Relationships
    python AI_tools/analysis/AI_tajika_aspects.py --screen 3            # Tajika yogas
    python AI_tools/analysis/AI_tajika_aspects.py --json                # JSON output
    python AI_tools/analysis/AI_tajika_aspects.py --date 1991-02-22 --time 10:30 --lat 48.98 --lon 2.27

Usage (transit mode — aspects between two charts):
    python AI_tools/analysis/AI_tajika_aspects.py "natal.chtk" --transit "eclipse.chtk"
    python AI_tools/analysis/AI_tajika_aspects.py "natal.chtk" --transit-date 2026-02-17
    python AI_tools/analysis/AI_tajika_aspects.py "natal.chtk" --transit-date 2026-02-17 --transit-time 12:00 --transit-lat 49.9 --transit-lon 2.3
    python AI_tools/analysis/AI_tajika_aspects.py "natal.chtk" --transit "eclipse.chtk" --json

Aspect Symbols:
    ☌ = Conjunction (0°)    ✶ = Sextile (60°/300°)    □ = Square (90°/270°)
    △ = Trine (120°/240°)   ☍ = Opposition (180°)
"""

import sys
import os
import argparse
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from AI_tools.AI_main_function.extraction import (
    datetime_chart_name as _datetime_name, extract_from_chtk, extract_from_datetime)
from core.capabilities.cli_settings import (
    add_view_flags, cli_chart, cli_datetime_jd, cli_moment_chart)
from core.capabilities.inputs import FRAME_KEYS, ChartFrame
from core.settings_registry.cli import echo, resolve_settings, use_settings
from AI_tools.AI_main_function.tajika import (
    calculate_all_tajika_aspects,
    calculate_transit_aspects,
    calculate_tajika_strength,
    TAJIKA_PLANETS,
    TAJIKA_SHORT_NAMES,
    DEEPTAMSAS,
    ASPECT_NAMES,
    MINOR_ASPECT_NAMES,
    HOUSE_ASPECT_MAP,
)
from AI_tools.AI_main_function.tajika_yogas import detect_all_tajika_yogas

# The chart frame and the Human Design view level (SPEC-SET-003 W11).
USES = tuple(key for _name, key in FRAME_KEYS) + ("ui.experience_level",)

# Default CHTK file
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CHTK = os.path.join(PROJECT_ROOT, "Lorris.chtk")

# CHTK database folders (searched in order)
CHTK_SEARCH_PATHS = [
    os.path.join(PROJECT_ROOT, "chtk_files"),
    os.path.expanduser(os.path.join("~", "Charts")),
]


def find_chtk(name_or_path: str) -> str:
    """
    Resolve a CHTK file from a name or path.

    Search order:
    1. Return as-is if file exists at given path
    2. Check chtk_files/{name}
    3. Recursive search in ~/Charts/
    4. Error if not found

    Args:
        name_or_path: File path or chart name (with or without .chtk extension).

    Returns:
        Absolute path to the CHTK file.

    Raises:
        FileNotFoundError: If no matching CHTK file is found.
    """
    # 1. Direct path
    if os.path.isfile(name_or_path):
        return os.path.abspath(name_or_path)

    # Ensure .chtk extension
    name = name_or_path if name_or_path.endswith(".chtk") else name_or_path + ".chtk"

    # 2. Check known folders
    for search_dir in CHTK_SEARCH_PATHS:
        if not os.path.isdir(search_dir):
            continue
        # Direct match in folder
        candidate = os.path.join(search_dir, name)
        if os.path.isfile(candidate):
            return candidate
        # Recursive search
        for root, _dirs, files in os.walk(search_dir):
            for f in files:
                if f == name or f.lower() == name.lower():
                    return os.path.join(root, f)

    raise FileNotFoundError(f"CHTK file not found: {name_or_path}")


# ============================================================================
# SCREEN 1: ASPECT MATRIX
# ============================================================================

def format_screen1(person_name: str, tajika_data: dict) -> str:
    """
    Format Tajika aspects as an 11x11 matrix showing aspect symbols within orb.

    Args:
        person_name: Chart name.
        tajika_data: Result from calculate_all_tajika_aspects().

    Returns:
        Formatted string.
    """
    matrix = tajika_data["matrix"]
    lines = []

    lines.append("\u2550" * 71)
    lines.append(f"  TAJIKA ASPECTS WITHIN ORB \u2014 {person_name}")
    lines.append("\u2550" * 71)

    # Header row
    header = "         "
    for p in TAJIKA_PLANETS:
        header += f"  {TAJIKA_SHORT_NAMES[p]:>4}"
    lines.append(header)

    # Matrix rows
    for row_planet in TAJIKA_PLANETS:
        row = f"  {TAJIKA_SHORT_NAMES[row_planet]:<5}  "
        for col_planet in TAJIKA_PLANETS:
            if row_planet == col_planet:
                row += "    \u2500\u2500"
            else:
                key = (row_planet, col_planet)
                if key in matrix:
                    symbol = matrix[key]["symbol"]
                    row += f"     {symbol}"
                else:
                    row += "      "
        lines.append(row)

    lines.append("\u2500" * 71)

    # Legend
    legend = ("  \u260c=Conjunction  \u2736=Sextile  \u25a1=Square  "
              "\u25b3=Trine  \u260d=Opposition")
    # Check if minor aspects are present
    has_minor = any(a.get("is_minor") for a in tajika_data["aspects_within_orb"])
    if has_minor:
        legend += "  \u26ba=Semi-sextile  \u26bb=Quincunx"
    lines.append(legend)

    # Orb summary
    orb_parts = []
    for p in TAJIKA_PLANETS:
        short = TAJIKA_SHORT_NAMES[p]
        orb = DEEPTAMSAS[p]
        orb_parts.append(f"{short}={orb}\u00b0")
    lines.append(f"  Orbs: {' '.join(orb_parts)}")

    lines.append("")

    # Aspects within orb detail list
    aspects = tajika_data["aspects_within_orb"]
    if aspects:
        lines.append(f"  {len(aspects)} aspects within orb (sorted by strength):")
        lines.append(f"  {'Pair':<12} {'Asp':>5} {'Dist':>7} {'VR':>6} {'%':>5}  "
                      f"{'Orb':>5}  {'From exact':>10}")
        lines.append(f"  {'-'*12} {'-'*5} {'-'*7} {'-'*6} {'-'*5}  {'-'*5}  {'-'*10}")

        for asp in aspects:
            short1 = TAJIKA_SHORT_NAMES.get(asp["body1"], asp["body1"][:2])
            short2 = TAJIKA_SHORT_NAMES.get(asp["body2"], asp["body2"][:2])
            pair = f"{short1}-{short2}"
            lines.append(
                f"  {pair:<12} {asp['symbol']:>5} {asp['distance']:>6.1f}\u00b0 "
                f"{asp['virupas']:>5.1f} {asp['strength_pct']:>4.0f}%  "
                f"{asp['orb_used']:>4.1f}\u00b0  {asp['distance_from_exact']:>5.1f}\u00b0"
            )

    lines.append("")
    lines.append("\u2550" * 71)

    return "\n".join(lines)


def _format_aspect_list(aspects: list, direction: str) -> list:
    """Format a list of transit aspect records as text lines.

    Args:
        aspects: Sorted aspect records from calculate_transit_aspects().
        direction: "transit_to_natal" or "natal_to_transit" (controls column labels).

    Returns:
        List of formatted strings (no header/footer).
    """
    lines = []
    if direction == "transit_to_natal":
        col1_label, col2_label = "Transit", "Natal"
    else:
        col1_label, col2_label = "Natal", "Transit"

    lines.append(f"  {col1_label:<18} {col2_label:<18} {'Asp':>5} {'Dist':>7} "
                 f"{'VR':>6} {'%':>5}  {'Orb':>5}  {'From exact':>10}")
    lines.append(f"  {'-'*18} {'-'*18} {'-'*5} {'-'*7} {'-'*6} {'-'*5}  "
                 f"{'-'*5}  {'-'*10}")

    for asp in aspects:
        if direction == "transit_to_natal":
            name1 = f"Transit {asp['transit_body']}"
            name2 = f"Natal {asp['natal_body']}"
        else:
            name1 = f"Natal {asp['natal_body']}"
            name2 = f"Transit {asp['transit_body']}"
        lines.append(
            f"  {name1:<18} {name2:<18} {asp['symbol']:>5} "
            f"{asp['distance']:>6.1f}\u00b0 "
            f"{asp['virupas']:>5.1f} {asp['strength_pct']:>4.0f}%  "
            f"{asp['orb_used']:>4.1f}\u00b0  {asp['distance_from_exact']:>5.1f}\u00b0"
        )
    return lines


def format_screen1_transit(transit_name: str, natal_name: str,
                           tajika_data: dict,
                           show_both: bool = False,
                           natal_to_transit_only: bool = False) -> str:
    """
    Format transit aspects with full-word labels.

    Default: Transit-to-Natal view (transit planet acts on natal planet).
    --natal-to-transit: Natal-to-Transit view (natal planet aspecting transit).
    --both-directions: Both views side by side.

    Args:
        transit_name: Transit chart name.
        natal_name: Natal chart name.
        tajika_data: Result from calculate_transit_aspects().
        show_both: If True, show both direction sections.
        natal_to_transit_only: If True, show only natal-to-transit.

    Returns:
        Formatted string.
    """
    matrix = tajika_data["matrix"]
    lines = []

    lines.append("\u2550" * 85)
    lines.append(f"  TRANSIT ASPECTS \u2014 {transit_name} \u2192 {natal_name} (natal)")
    lines.append("\u2550" * 85)

    # Matrix (always transit-to-natal layout)
    header = "  Transit\\Natal  "
    for p in TAJIKA_PLANETS:
        header += f"  {TAJIKA_SHORT_NAMES[p]:>4}"
    lines.append(header)

    for t_planet in TAJIKA_PLANETS:
        if t_planet == "Ascendant":
            continue  # Ascendant is a point, doesn't give aspects
        short = TAJIKA_SHORT_NAMES[t_planet]
        row = f"  Transit {short:<5}  "
        for n_planet in TAJIKA_PLANETS:
            key = (t_planet, n_planet)
            if key in matrix:
                symbol = matrix[key]["symbol"]
                row += f"     {symbol}"
            else:
                row += "      "
        lines.append(row)

    lines.append("\u2500" * 85)

    # Legend
    legend = ("  \u260c=Conjunction  \u2736=Sextile  \u25a1=Square  "
              "\u25b3=Trine  \u260d=Opposition")
    t2n = tajika_data["transit_to_natal"]
    has_minor = any(a.get("is_minor") for a in t2n)
    if has_minor:
        legend += "  \u26ba=Semi-sextile  \u26bb=Quincunx"
    lines.append(legend)

    orb_parts = []
    for p in TAJIKA_PLANETS:
        short = TAJIKA_SHORT_NAMES[p]
        orb = DEEPTAMSAS[p]
        orb_parts.append(f"{short}={orb}\u00b0")
    lines.append(f"  Orbs: {' '.join(orb_parts)}")

    if not t2n:
        lines.append("")
        lines.append("  No transit aspects within orb.")
        lines.append("\u2550" * 85)
        return "\n".join(lines)

    # ── SECTION 1: TRANSITING TO NATAL ──
    if not natal_to_transit_only:
        lines.append("")
        header_text = (f"  \u2500\u2500 TRANSITING TO NATAL "
                       f"({len(t2n)} aspects, sorted by strength) ")
        lines.append(header_text + "\u2500" * max(1, 85 - len(header_text)))
        lines.extend(_format_aspect_list(t2n, "transit_to_natal"))

    # ── SECTION 2: NATAL TO TRANSIT ──
    if show_both or natal_to_transit_only:
        n2t = tajika_data["natal_to_transit"]
        lines.append("")
        header_text = (f"  \u2500\u2500 NATAL TO TRANSIT "
                       f"({len(n2t)} aspects, sorted by strength) ")
        lines.append(header_text + "\u2500" * max(1, 85 - len(header_text)))
        lines.extend(_format_aspect_list(n2t, "natal_to_transit"))

    lines.append("")
    lines.append("\u2550" * 85)

    return "\n".join(lines)


# ============================================================================
# SCREEN 2: RELATIONSHIPS
# ============================================================================

def format_screen2(person_name: str, tajika_data: dict) -> str:
    """
    Format Tajika aspects grouped by relationship type.

    Groups: Openly Friendly, Secretly Friendly, Openly Inimical, Secretly Inimical.

    Args:
        person_name: Chart name.
        tajika_data: Result from calculate_all_tajika_aspects().

    Returns:
        Formatted string.
    """
    aspects = tajika_data["aspects_within_orb"]
    lines = []

    lines.append("\u2550" * 71)
    lines.append(f"  TAJIKA RELATIONSHIPS \u2014 {person_name}")
    lines.append("\u2550" * 71)

    # Group by relationship type
    groups = {
        "Openly Friendly": [],
        "Secretly Friendly": [],
        "Openly Inimical": [],
        "Secretly Inimical": [],
        "Neutral": [],
    }

    for asp in aspects:
        rel = asp["relationship"]
        if rel in groups:
            groups[rel].append(asp)

    # Display order and descriptions
    display_order = [
        ("Openly Friendly", "Trine \u2014 5th/9th house"),
        ("Secretly Friendly", "Sextile \u2014 3rd/11th house"),
        ("Openly Inimical", "Conjunction/Opposition \u2014 1st/7th house"),
        ("Secretly Inimical", "Square \u2014 4th/10th house"),
        ("Neutral", "Semi-sextile/Inconjunct \u2014 2nd/6th/8th/12th house"),
    ]

    has_any = False
    for group_name, description in display_order:
        group_aspects = groups[group_name]
        if not group_aspects:
            continue

        has_any = True
        lines.append("")
        lines.append(f"  {group_name.upper()} ({description}):")

        for asp in sorted(group_aspects, key=lambda x: -x["virupas"]):
            # Transit records use transit_body/natal_body; single-chart uses body1/body2
            raw1 = asp.get("transit_body") or asp.get("body1", "?")
            raw2 = asp.get("natal_body") or asp.get("body2", "?")
            short1 = TAJIKA_SHORT_NAMES.get(raw1, raw1[:2])
            short2 = TAJIKA_SHORT_NAMES.get(raw2, raw2[:2])
            # Full-word labels for transit mode
            if "transit_body" in asp:
                short1 = f"Transit {short1}"
                short2 = f"Natal {short2}"

            ordinal = _ordinal(asp["houses_apart"])

            lines.append(
                f"    {short1} {asp['symbol']} {short2}   "
                f"({asp['distance']:.1f}\u00b0)   "
                f"{asp['virupas']:.1f} VR ({asp['strength_pct']:.0f}%)   "
                f"{ordinal} house"
            )

    if not has_any:
        lines.append("")
        lines.append("  No aspects within orb found.")

    lines.append("")
    lines.append("\u2550" * 71)

    return "\n".join(lines)


# ============================================================================
# SCREEN 3: TAJIKA YOGAS
# ============================================================================

# Category display configuration
_CATEGORY_ORDER = [
    ("SUCCESS", "yogas that indicate the event will succeed"),
    ("FAILURE", "yogas that indicate the event will fail or is past"),
    ("DISRUPTION", "yogas that interfere with success"),
    ("VOID", "planets that cannot produce results"),
    ("TRANSFER", "yogas where a 3rd planet mediates the event"),
    ("SPECIAL", "rare yogas with specific conditions"),
]


def format_screen3(person_name: str, yoga_data: dict) -> str:
    """
    Format Tajika yogas grouped by outcome category.

    Args:
        person_name: Chart name.
        yoga_data: Result from detect_all_tajika_yogas().

    Returns:
        Formatted string.
    """
    lines = []
    by_cat = yoga_data["yogas_by_category"]
    summary = yoga_data["summary"]

    lines.append("\u2550" * 71)
    lines.append(f"  TAJIKA YOGAS \u2014 {person_name}")
    lines.append("\u2550" * 71)

    has_any = False
    for cat, description in _CATEGORY_ORDER:
        cat_yogas = by_cat.get(cat, [])
        if not cat_yogas:
            continue

        has_any = True
        lines.append("")
        count_word = f"yoga{'s' if len(cat_yogas) != 1 else ''}"
        label = f"{cat} ({len(cat_yogas)} {count_word})"
        dashes = "\u2500" * max(1, 55 - len(label))
        lines.append(f"  \u2500\u2500 {label} {dashes}")

        for yoga in cat_yogas:
            name = yoga["yoga_name"]
            subtype = f" ({yoga['subtype']})" if "subtype" in yoga else ""
            planets_short = yoga["planets_short"]

            lines.append("")
            lines.append(f"  {name.upper()}{subtype} \u2014 {planets_short}")
            lines.append(f"    {yoga['description']}")
            lines.append(f"    \u2192 {yoga['effect']}")

    if not has_any:
        lines.append("")
        lines.append("  No Tajika yogas detected.")

    lines.append("")
    lines.append("\u2550" * 71)

    # Summary line
    parts = []
    for cat, _ in _CATEGORY_ORDER:
        count = summary.get(f"{cat.lower()}_count", 0)
        if count > 0:
            parts.append(f"{count} {cat.capitalize()}")
    if parts:
        lines.append(f"  Summary: {' | '.join(parts)}")
    else:
        lines.append("  Summary: No yogas detected")
    lines.append("\u2550" * 71)

    return "\n".join(lines)


def _ordinal(n: int) -> str:
    """Return ordinal string for a number (1st, 2nd, 3rd, etc.)."""
    if 11 <= n <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Command-line interface for Tajika aspect analysis."""
    parser = argparse.ArgumentParser(
        description="Calculate Tajika aspects (Western-style orb-based) for a chart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (single chart):
  python AI_tajika_aspects.py                          # Default chart (Lorris.chtk)
  python AI_tajika_aspects.py "Sandra P.chtk"          # Specific chart
  python AI_tajika_aspects.py --screen 2               # Relationship groups
  python AI_tajika_aspects.py --json                   # JSON output
  python AI_tajika_aspects.py --date 1991-02-22 --time 10:30 --lat 48.98 --lon 2.27

Examples (transit mode — aspects between two charts):
  python AI_tajika_aspects.py "natal.chtk" --transit "eclipse.chtk"
  python AI_tajika_aspects.py "natal.chtk" --transit-date 2026-02-17
  python AI_tajika_aspects.py "natal.chtk" --transit-date 2026-02-17 --transit-time 12:00 --transit-lat 49.9 --transit-lon 2.3

Tajika Aspects:
  Conjunction (0°), Sextile (60°/300°), Square (90°/270°),
  Trine (120°/240°), Opposition (180°)
  --minor also shows: Semi-sextile (30°/330°), Quincunx (150°/210°)

Deeptamsas (planet-specific orbs):
  Sun=15°  Moon=12°  Mars=8°  Mercury=7°  Jupiter=9°
  Venus=7°  Saturn=9°  Uranus/Neptune/Pluto=8°  Ascendant=9°
        """
    )

    parser.add_argument("chtk_file", nargs="?", help="Path to CHTK file")
    parser.add_argument("--date", "-d", help="Birth date (YYYY-MM-DD)")
    parser.add_argument("--time", "-t", help="Birth time (HH:MM)")
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--screen", type=int, default=1, choices=[1, 2, 3],
                        help="Output screen: 1=matrix (default), 2=relationships, 3=yogas")
    parser.add_argument("--minor", action="store_true",
                        help="Include semi-sextile (30°) and quincunx (150°)")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")

    # Transit mode arguments
    center = parser.add_argument_group("South Indian center geometry (SPEC-TJK-003)")
    center.add_argument("--center-geometry", action="store_true",
                        help="Output the Tajika center drawing's model: angles, exact "
                             "and stud points, push levels, drawn aspects (use with --json)")
    center.add_argument("--min-virupas", type=int, default=0, metavar="N",
                        help="With --center-geometry: leave out aspects under N virupas (0-60)")
    center.add_argument("--bodies", type=str, default=None, metavar="CODES",
                        help="With --center-geometry: light these bodies (codes like SU,MO)")
    transit_group = parser.add_argument_group("Transit mode")
    transit_group.add_argument("--transit",
                               help="Transit CHTK file (name or path)")
    transit_group.add_argument("--transit-date",
                               help="Transit date YYYY-MM-DD (UTC)")
    transit_group.add_argument("--transit-time",
                               help="Transit time HH:MM (default: 12:00)")
    transit_group.add_argument("--transit-lat", type=float,
                               help="Transit latitude (default: the natal chart's)")
    transit_group.add_argument("--transit-lon", type=float,
                               help="Transit longitude (default: the natal chart's)")
    transit_group.add_argument("--both-directions", action="store_true", default=True,
                               help="Show both Transit-to-Natal AND Natal-to-Transit (default for transit mode)")
    transit_group.add_argument("--natal-to-transit", action="store_true",
                               help="Show Natal-to-Transit view only (JSON too)")
    transit_group.add_argument("--top", type=int, default=None, metavar="N",
                               help="Keep only the N strongest aspects (by virupas) of "
                                    "each view; text and JSON")

    # Single-chart mode mirrors the Tajika panels, which read the app's active
    # chart: the -88 Design chart in Human Design mode. Transit mode compares
    # two birth/moment charts (the Transit page's sides) and stays natal.
    add_view_flags(parser)
    use_settings(parser, USES)
    args = parser.parse_args()
    # Settings: the tools' settings (settings.py) > running app > saved
    # Settings tab > factory (SPEC-SET-003 INV-4; never writes).
    cfg = resolve_settings(args)
    frame = ChartFrame.resolve(cfg.view)
    frame_kw = dict(mode=frame.mode, ayanamsa=frame.ayanamsa_id,
                    hsys=frame.house_system_code)

    # Validate transit args
    is_transit = bool(args.transit or args.transit_date)

    # --- Load natal chart ---
    if args.date and not is_transit:
        if args.lat is None or args.lon is None:
            print("Error: --lat and --lon are required when using --date")
            sys.exit(1)
        # The same view rule as a chart file: the -88 Design chart of this
        # moment in Human Design mode (cli_moment_chart), else the birth chart.
        loaded = {}

        def _natal_dt():
            chart, loaded["name"] = extract_from_datetime(
                args.date, args.time, args.lat, args.lon, **frame_kw)
            return chart
        planets_data, inp = cli_moment_chart(
            args, frame, jd_ut=cli_datetime_jd(args.date, args.time),
            latitude=args.lat, longitude=args.lon, natal=_natal_dt)
        person_name = loaded.get("name") or _datetime_name(
            args.date, args.time, args.lat, args.lon)
    else:
        chtk_path = args.chtk_file if args.chtk_file else DEFAULT_CHTK
        try:
            chtk_path = find_chtk(chtk_path)
        except FileNotFoundError:
            print(f"Error: CHTK file not found: {chtk_path}")
            sys.exit(1)
        if is_transit:
            planets_data, person_name = extract_from_chtk(chtk_path, **frame_kw)
        else:
            loaded = {}

            def _natal():
                chart, loaded["name"] = extract_from_chtk(chtk_path, **frame_kw)
                return chart
            planets_data, inp = cli_chart(chtk_path, args, frame, natal=_natal)
            person_name = loaded.get("name", inp.chart.title)

    # --- Transit mode ---
    if is_transit:
        # Block screen 3 (yogas) for transit mode
        if args.screen == 3:
            print("Error: Yoga detection (--screen 3) not supported in transit mode")
            sys.exit(1)

        # Load transit chart
        if args.transit:
            try:
                transit_path = find_chtk(args.transit)
            except FileNotFoundError:
                print(f"Error: Transit CHTK file not found: {args.transit}")
                sys.exit(1)
            transit_data, transit_name = extract_from_chtk(transit_path, **frame_kw)
        else:
            # No place given: the transit sky over the natal place, not 0/0 (the
            # transit Ascendant and houses depend on it; AI capture review 2026-10-20).
            t_lat, t_lon = args.transit_lat, args.transit_lon
            if t_lat is None or t_lon is None:
                from core.capabilities.inputs import CalculationInput
                natal = CalculationInput.from_file(str(chtk_path)).chart
                t_lat = natal.latitude if t_lat is None else t_lat
                t_lon = natal.longitude if t_lon is None else t_lon
            transit_data, transit_name = extract_from_datetime(
                args.transit_date,
                args.transit_time or "12:00",
                t_lat,
                t_lon,
                **frame_kw,
            )

        # Calculate cross-chart aspects
        tajika_data = calculate_transit_aspects(
            planets_data, transit_data, include_minor=args.minor
        )
        if args.top is not None and args.top > 0:
            # A whole transit table is ~40K characters of JSON; an AI scanning
            # months asks for the strongest only (AI capture tour 2026-10-20).
            for view in ("transit_to_natal", "natal_to_transit"):
                rows = tajika_data.get(view) or []
                tajika_data[view] = sorted(rows, key=lambda r: -(r.get("virupas") or 0))[:args.top]

        # Output
        if args.json:
            result = {
                "natal_name": person_name,
                "transit_name": transit_name,
                "mode": "transit",
                "transit_to_natal": tajika_data["transit_to_natal"],
                "natal_to_transit": tajika_data["natal_to_transit"],
                "total_aspects": len(tajika_data["transit_to_natal"]),
            }
            if args.natal_to_transit:
                del result["transit_to_natal"]
                result["total_aspects"] = len(tajika_data["natal_to_transit"])
            print(json.dumps(echo(result, cfg), indent=2))
        elif args.screen == 2:
            print(format_screen2(
                f"{transit_name} \u2192 {person_name} (natal)", tajika_data
            ))
        else:
            print(format_screen1_transit(
                transit_name, person_name, tajika_data,
                show_both=args.both_directions,
                natal_to_transit_only=args.natal_to_transit,
            ))
        return

    # --- Single chart mode (unchanged) ---
    tajika_data = calculate_all_tajika_aspects(planets_data,
                                               include_minor=args.minor)

    if args.center_geometry:
        # The model the vector South Indian center draws (SPEC-TJK-003 §4.1, §4.7)
        from core import tajika_center as tc
        lit = set()
        codes = {code.upper(): body for body, code in TAJIKA_SHORT_NAMES.items()}
        for code in filter(None, (c.strip().upper() for c in (args.bodies or "").split(","))):
            if code not in codes:
                parser.error(f"Unknown body code '{code}'. Valid codes: {', '.join(sorted(codes))}")
            lit.add(codes[code])
        full = tc.build_full_model(tc.chart_positions(planets_data),
                                   tajika_data.get("aspects_within_orb", []))
        model = tc.select(full, max(0, min(60, args.min_virupas)), lit)
        result = {"name": person_name, "center_geometry": tc.model_to_json(model)}
        print(json.dumps(echo(result, cfg), indent=2))
        return

    # Compute yoga data if needed (screen 3 or JSON with screen 3)
    yoga_data = None
    if args.screen == 3:
        yoga_data = detect_all_tajika_yogas(planets_data, tajika_data)

    # Output
    if args.json:
        if args.screen == 3:
            # Strip non-serializable aspect_record references
            clean_yogas = []
            for y in yoga_data["all_yogas"]:
                clean = {k: v for k, v in y.items() if k != "aspect_record"}
                clean_yogas.append(clean)
            result = {
                "name": person_name,
                "yogas": clean_yogas,
                "yogas_by_category": {
                    cat: [{k: v for k, v in y.items() if k != "aspect_record"}
                          for y in ylist]
                    for cat, ylist in yoga_data["yogas_by_category"].items()
                },
                "summary": yoga_data["summary"],
            }
        else:
            result = {
                "name": person_name,
                "aspects_within_orb": tajika_data["aspects_within_orb"],
                "total_aspects": len(tajika_data["aspects_within_orb"]),
            }
        print(json.dumps(echo(result, cfg), indent=2))
    elif args.screen == 3:
        print(format_screen3(person_name, yoga_data))
    elif args.screen == 2:
        print(format_screen2(person_name, tajika_data))
    else:
        print(format_screen1(person_name, tajika_data))


if __name__ == "__main__":
    main()
