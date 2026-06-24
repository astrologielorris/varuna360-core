# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Proprietary software — All rights reserved.
# Part of Varuna360 Pro. Not covered by AGPL-3.0.
"""
Dignities in Vargas — Kala-style table showing planetary dignities across all 16 vargas.

Usage:
    python -m AI_tools.AI_main_function.dignities_in_vargas Lorris.chtk
    python -m AI_tools.AI_main_function.dignities_in_vargas /path/to/chart.chtk --json
"""

import sys
import os
import json
import argparse
from pathlib import Path
from prettytable import PrettyTable

from core.varga_codes import (
    VARGA_NAMES, _GUI_TO_LIBADITYA_VARGA, to_libaditya_varga_code,
    VARGA_STYLE_ORDER, VARGA_STYLES,
    to_libaditya_varga_code_styled, get_varga_display_label,
)

CHTK_DIR = Path.home() / "Documents" / "Kala" / "Charts"

STANDARD_VARGA_ORDER = [1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]

PLANET_HEADERS = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"]

DIGNITY_COLORS = {
    "EX": "\033[1;31m",
    "MT": "\033[1;35m",
    "OH": "\033[1;34m",
    "GF": "\033[32m",
    "F":  "\033[32m",
    "N":  "\033[0m",
    "E":  "\033[33m",
    "GE": "\033[1;33m",
    "DB": "\033[1;31m",
}
RESET = "\033[0m"


def load_chart(chtk_path, mode="aditya"):
    """Load a libaditya Chart from a CHTK file."""
    from core.aditya_mode import load_chart_from_chtk
    return load_chart_from_chtk(chtk_path, mode=mode)


def compute_dignities_table(chart, varga_order=None, varga_style="classical"):
    """Compute dignities for all standard vargas using the GUI's canonical varga mappings.

    Args:
        chart: libaditya Chart object (mode already baked into its context).
        varga_order: list of GUI varga numbers to include (default: STANDARD_VARGA_ORDER).
        varga_style: one of VARGA_STYLE_ORDER keys. Controls which libaditya
            amsha code is used for vargas that have alternative calculations
            (e.g. Parivritti D2/D3/D4, Reversed D10/D24).
    """
    from libaditya.calc.varga import Varga
    from core.varga_codes import get_varga_overrides

    if varga_style not in VARGA_STYLE_ORDER:
        raise ValueError(f"Unknown varga_style: {varga_style!r}. Must be one of {VARGA_STYLE_ORDER}")

    if varga_order is None:
        varga_order = STANDARD_VARGA_ORDER

    overrides = get_varga_overrides(varga_style)
    rows = []
    for gui_code in varga_order:
        lib_amsha = to_libaditya_varga_code_styled(gui_code, varga_style)
        display_label = get_varga_display_label(gui_code, varga_style)
        varga = Varga(chart.context, amsha=lib_amsha)
        dignities = varga.dignities()

        if gui_code in overrides:
            name = varga.varga_name()
        else:
            name = VARGA_NAMES.get(gui_code, f"D-{gui_code}")

        rows.append({
            "amsha": gui_code,
            "label": display_label,
            "name": name,
            "dignities": dignities,
        })
    return rows


def _colorize(dignity, use_color=True):
    """Wrap a dignity abbreviation in ANSI color if enabled."""
    if not use_color:
        return dignity
    color = DIGNITY_COLORS.get(dignity, "")
    return f"{color}{dignity}{RESET}"


def print_table(rows, chart_name="", use_color=True):
    """Print dignities table matching Kala's layout."""
    title = "Dignities in Vargas"
    if chart_name:
        title = f"{title} ({chart_name})"

    table = PrettyTable()
    table.field_names = [""] + PLANET_HEADERS
    table.title = title
    table.align = "c"
    table.align[""] = "r"

    for row in rows:
        cells = [_colorize(d, use_color) for d in row["dignities"]]
        table.add_row([row["label"]] + cells)

    print(table)
    print()
    print("  EX=Exaltation  MT=Moolatrikona  OH=Own House  GF=Great Friend")
    print("  F=Friend  N=Neutral  E=Enemy  GE=Great Enemy  DB=Debilitation")
    print()


def to_json(rows, chart_name=""):
    """Return JSON representation."""
    return {
        "chart": chart_name,
        "table": [
            {
                "varga": row["label"],
                "amsha": row["amsha"],
                "name": row["name"],
                "dignities": dict(zip(PLANET_HEADERS, row["dignities"])),
            }
            for row in rows
        ],
    }


def resolve_chtk_path(name):
    """Resolve a chart name or path to an actual CHTK file."""
    p = Path(name)
    if p.exists():
        return p
    if not p.suffix:
        p = p.with_suffix(".chtk")
    if p.exists():
        return p
    candidate = CHTK_DIR / p.name
    if candidate.exists():
        return candidate
    candidate = CHTK_DIR / name
    if candidate.exists():
        return candidate
    candidate = CHTK_DIR / (name + ".chtk")
    if candidate.exists():
        return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="Dignities in Vargas (Kala-style table)")
    parser.add_argument("chart", help="CHTK file name or path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--mode", default="aditya",
                        choices=["aditya", "tropical_classic", "sidereal"],
                        help="Zodiac mode (default: aditya)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output")
    parser.add_argument("--varga-style", default="classical",
                        choices=VARGA_STYLE_ORDER,
                        help="Varga calculation style (default: classical)")
    args = parser.parse_args()

    chtk_path = resolve_chtk_path(args.chart)
    if not chtk_path:
        print(f"Error: Cannot find chart '{args.chart}'", file=sys.stderr)
        print(f"Searched: current dir, {CHTK_DIR}", file=sys.stderr)
        sys.exit(1)

    chart = load_chart(chtk_path, mode=args.mode)
    chart_name = chtk_path.stem

    rows = compute_dignities_table(chart, varga_style=args.varga_style)

    if args.json:
        print(json.dumps(to_json(rows, chart_name), indent=2))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print_table(rows, chart_name, use_color=use_color)


if __name__ == "__main__":
    main()
