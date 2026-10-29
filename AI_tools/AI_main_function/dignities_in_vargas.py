# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dignities in Vargas — planetary dignities across all 16 vargas.

Usage:
    python -m AI_tools.AI_main_function.dignities_in_vargas Lorris.chtk
    python -m AI_tools.AI_main_function.dignities_in_vargas /path/to/chart.chtk --json

The varga style is the setting chart.varga_style (the app's, followed like every
setting); in advanced mode: --set chart.varga_style=reversed.
"""

import sys
import os
import json
import argparse
from pathlib import Path

from core.varga_codes import (
    VARGA_NAMES, _GUI_TO_LIBADITYA_VARGA, to_libaditya_varga_code,
    VARGA_STYLE_ORDER,
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

        # td-m6xyo (SPEC-DIG-001): a Debilitated planet's kind, by its natural
        # relationship to the lord of the sign it occupies in this varga.
        from core.planet_dignity import ABBR, dignities_of_varga
        db_kinds = {ABBR[d.planet]: d.kind for d in dignities_of_varga(varga, gui_code == 1)
                    if d.code == "DB"}

        rows.append({
            "amsha": gui_code,
            "label": display_label,
            "name": name,
            "dignities": dignities,
            "db_kinds": db_kinds,
            # SPEC-DIG-001 D-10: a styled row (D2p, D10r...) in place of its classical one
            **({"variant": varga_style} if gui_code in overrides else {}),
        })
    return rows


_KIND_MARK = {"friend": "f", "neutral": "n", "enemy": "e"}


def _cell(row, index):
    """The table cell: the code, a Debilitated one with its kind, "DB(f)"."""
    code = row["dignities"][index]
    kind = row.get("db_kinds", {}).get(PLANET_HEADERS[index])
    return f"{code}({_KIND_MARK[kind]})" if code == "DB" and kind in _KIND_MARK else code


def _colorize(dignity, use_color=True):
    """Wrap a dignity abbreviation in ANSI color if enabled."""
    if not use_color:
        return dignity
    color = DIGNITY_COLORS.get(dignity[:2].rstrip("("), "")
    return f"{color}{dignity}{RESET}"


def print_table(rows, chart_name="", use_color=True):
    """Print dignities table (standard 16-varga layout)."""
    # Function-level: prettytable is only needed by this one CLI table
    # renderer, so it stays an OPTIONAL dependency of the public artifact
    # rather than a hard install requirement for everyone (SPEC-SES-001 §8).
    from prettytable import PrettyTable
    title = "Dignities in Vargas"
    if chart_name:
        title = f"{title} ({chart_name})"

    table = PrettyTable()
    table.field_names = [""] + PLANET_HEADERS
    table.title = title
    table.align = "c"
    table.align[""] = "r"

    for row in rows:
        cells = [_colorize(_cell(row, i), use_color) if use_color else _cell(row, i)
                 for i in range(len(row["dignities"]))]
        label = f"  {row['label']}" if row.get("variant") else row["label"]   # a variant row
        table.add_row([label] + cells)

    print(table)
    print()
    print("  EX=Exaltation  MT=Moolatrikona  OH=Own House  GF=Great Friend")
    print("  F=Friend  N=Neutral  E=Enemy  GE=Great Enemy  DB=Debilitation")
    print("  DB(f/n/e) = Debilitated in a friend's / neutral's / enemy's sign (natural relationship)")
    print()


def to_json(rows, chart_name="", varga_style=None):
    """Return JSON representation (``varga_style``: the style the table used)."""
    out = {"chart": chart_name}
    if varga_style is not None:
        out["varga_style"] = varga_style
    return {
        **out,
        "table": [
            {
                "varga": row["label"],
                "amsha": row["amsha"],
                "name": row["name"],
                "dignities": dict(zip(PLANET_HEADERS, row["dignities"])),
                "db_kinds": dict(row.get("db_kinds", {})),
                **({"variant": row["variant"]} if row.get("variant") else {}),
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


# The settings this command reads (SPEC-SET-003 §4.5): the chart frame (the
# label set and the Human Design level included) and the experience level.
USES = ("zodiac.mode", "zodiac.ayanamsa_id", "zodiac.house_system",
        "zodiac.nakshatra_coords", "chart.show_outer_planets",
        "zodiac.use_western_names", "ui.hd_experience_level", "ui.experience_level",
        # td-m6xyo: the varga style shared with the app (SPEC-DIG-001 §4.3)
        "chart.varga_style")


def main():
    parser = argparse.ArgumentParser(description="Dignities in Vargas (16-varga table)")
    parser.add_argument("chart", help="CHTK file name or path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output")
    # The chart frame follows the app like the Dignities panel's active chart
    # (argument > running app > saved Settings tab > factory, AIC plan 2).
    # The Dignities panel reads the app's active chart: the -88 Design chart in
    # Human Design mode, --human-design / --no-human-design override.
    from core.capabilities.cli_settings import add_view_flags, cli_chart
    from core.capabilities.inputs import ChartFrame
    from core.settings_registry.cli import echo, resolve_settings, use_settings
    add_view_flags(parser)
    use_settings(parser, USES)
    args = parser.parse_args()
    # Settings: the tools' settings (settings.py) > running app > saved
    # Settings tab > factory (SPEC-SET-003 INV-4; never writes).
    cfg = resolve_settings(args)
    frame = ChartFrame.resolve(cfg.view)

    chtk_path = resolve_chtk_path(args.chart)
    if not chtk_path:
        print(f"Error: Cannot find chart '{args.chart}'", file=sys.stderr)
        print(f"Searched: current dir, {CHTK_DIR}", file=sys.stderr)
        sys.exit(1)

    chart, _inp = cli_chart(chtk_path, args, frame)   # the panel's chart
    chart_name = chtk_path.stem

    # The varga style is the setting chart.varga_style, like every setting
    # (SPEC-SET-003 D-12/D-13: no settings flag; --set in advanced mode).
    style = cfg["chart.varga_style"]
    if style not in VARGA_STYLE_ORDER:
        style = "classical"
    rows = compute_dignities_table(chart, varga_style=style)

    if args.json:
        # The settings echo (SPEC-SET-003 §4.5): settings: {key: {value, source}}.
        print(json.dumps(echo(to_json(rows, chart_name, style), cfg), indent=2))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print_table(rows, f"{chart_name}, {style}" if style != "classical" else chart_name,
                    use_color=use_color)


if __name__ == "__main__":
    main()
