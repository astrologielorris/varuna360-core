# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Core positions-only nakshatra CLI (td-p85s).

CLI parity (Rule 24) for the Core/Lite F2 Nakshatra wheel
(SPEC-NAK-LITE-001): prints each body's nakshatra index/name/pada and longitude,
plus the Lagna. POSITIONS ONLY — no Vimshottari lord, deity, yoni, gana, symbol
or any interpretive text (that descriptive layer stays Pro-only, in
pro/AI_tools/cli/show_nakshatra.py).

Frame contract (matches the F2 wheel exactly):
  * default frame = sidereal, ayanamsa = zodiac.ayanamsa_id from settings. The F2
    wheel computes from that id and IGNORES zodiac.nakshatra_coords (td-bu8s
    BUG4); nakshatra_coords only names a pill label, never the numbers, so it
    does not drive this CLI either.
  * --ayanamsa <id|name> overrides the sidereal ayanamsa id.
  * --frame tropical is a CLI-only override (ayanamsa 0, no ayanamsa applied). It
    has NO F2-wheel counterpart, so Rule-24 parity is asserted on the default
    sidereal path only.

The nakshatra ENGINE (get_all_nakshatras) expects TROPICAL input and applies the
ayanamsa itself; feeding a sidereal chart would double-subtract. The engine now
self-guards via the shared nakshatra.as_tropical_chart helper (td-lgiq), and this
CLI builds the chart tropical and routes it through that same helper, so both the
CLI and the F2 wheel share one definition of the engine's tropical frame
(td-bu8s BUG2).

Usage:
    python -m AI_tools.cli.show_nakshatra_positions chart.chtk --json
    python -m AI_tools.cli.show_nakshatra_positions chart.toml --frame tropical
    python -m AI_tools.cli.show_nakshatra_positions chart.chtk --ayanamsa lahiri

Exit codes:
    0  success
    2  bad usage / file not found / read error
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

SUPPORTED_EXTS = (".chtk", ".toml")
DEFAULT_AYANAMSA_ID = 100  # settings default (zodiac.ayanamsa_id), if unreadable


def _settings_ayanamsa_id() -> int:
    """The sidereal ayanamsa id the F2 wheel uses (zodiac.ayanamsa_id)."""
    try:
        from managers.settings_manager import get_settings
        return int(get_settings().get("zodiac.ayanamsa_id", DEFAULT_AYANAMSA_ID))
    except Exception:  # noqa: BLE001 - headless / no settings file
        return DEFAULT_AYANAMSA_ID


def resolve_engine_ayanamsa(frame: str, ayanamsa_arg=None) -> int:
    """The ayanamsa id fed to the engine for the chosen frame.

    tropical -> 0 (no ayanamsa; --ayanamsa is ignored). sidereal -> the
    --ayanamsa override if given, else zodiac.ayanamsa_id from settings.
    """
    if frame == "tropical":
        return 0
    if ayanamsa_arg is not None:
        from AI_tools.AI_main_function.dasha import resolve_ayanamsa
        return int(resolve_ayanamsa(ayanamsa_arg))
    return _settings_ayanamsa_id()


def _build_tropical_chart(birth_data):
    """Build the engine chart from a canonical birth_data dict.

    The chart is constructed tropical and then handed through the single shared
    frame guard ``AI_tools.AI_main_function.nakshatra.as_tropical_chart``
    (td-lgiq) — the same helper the F2 wheel and the engine batch calls use — so
    the CLI shares one definition of the engine's tropical frame instead of
    reimplementing it. (get_all_nakshatras also self-guards, so this is belt and
    suspenders; the pass-through keeps the longitudes byte-identical to the wheel.)
    """
    from libaditya import swe
    from core.chart_factory import build_chart_from_params
    from AI_tools.AI_main_function.nakshatra import as_tropical_chart
    hour = (birth_data["utc_hour"] + birth_data["utc_minute"] / 60.0
            + birth_data["utc_second"] / 3600.0)
    jd = swe.julday(birth_data["utc_year"], birth_data["utc_month"],
                    birth_data["utc_day"], hour)
    chart = build_chart_from_params(
        jd=jd, lat=birth_data["latitude"], lon=birth_data["longitude"],
        mode="tropical_classic", ayanamsa=0,
        utcoffset=birth_data.get("utc_offset_hours", 0.0),
        name=birth_data.get("name", ""),
    )
    return as_tropical_chart(chart), jd


def _body_entry(name: str, info: dict) -> dict:
    """Positions-only projection of one engine nakshatra dict. Deliberately drops
    lord / dasha_number / deg_in_nakshatra — POSITIONS ONLY."""
    return {
        "body": name,
        "longitude": round(info["sidereal_long"], 6),
        "nakshatra_index": info["index"] + 1,  # engine is 0-based; schema is 1..27
        "nakshatra": info["name"],
        "pada": info["pada"],
    }


def compute_positions(chart_path: str, frame: str = "sidereal",
                      ayanamsa_arg=None) -> dict:
    """Return the positions-only nakshatra payload for ``chart_path``.

    Shape: {"frame", "ayanamsa_id", "bodies": [ {body, longitude,
    nakshatra_index, nakshatra, pada}, ... ], "lagna": {same fields}}.
    Computed through the SAME get_all_nakshatras call the F2 wheel uses.
    """
    from managers.birth_data_manager import BirthDataManager
    from AI_tools.AI_main_function.nakshatra import get_all_nakshatras
    from AI_tools.AI_main_function.constants import PLANETS

    ext = os.path.splitext(chart_path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported chart format {ext!r} (expected one of "
            f"{', '.join(SUPPORTED_EXTS)}): {chart_path}")

    birth_data = BirthDataManager.create_birth_data_from_file(
        chart_path, canonicalize=False)
    chart, jd = _build_tropical_chart(birth_data)
    ayanamsa = resolve_engine_ayanamsa(frame, ayanamsa_arg)
    naks = get_all_nakshatras(chart, jd, ayanamsa=ayanamsa)

    bodies = [_body_entry(p, naks[p]) for p in PLANETS if p in naks]
    payload = {
        "frame": frame,
        "ayanamsa_id": ayanamsa,
        "bodies": bodies,
    }
    if "Lagna" in naks:
        payload["lagna"] = _body_entry("Lagna", naks["Lagna"])
    return payload


def _format_table(payload: dict) -> str:
    lines = []
    lines.append(f"Nakshatra positions  (frame: {payload['frame']}, "
                 f"ayanamsa_id: {payload['ayanamsa_id']})")
    lines.append("-" * 58)
    lines.append(f"  {'Body':<9} {'Nakshatra':<16} {'Pada':>4} {'Longitude':>12}")
    lines.append("-" * 58)
    rows = list(payload["bodies"])
    if "lagna" in payload:
        rows = [payload["lagna"]] + rows
    for e in rows:
        lines.append(f"  {e['body']:<9} {e['nakshatra']:<16} {e['pada']:>4} "
                     f"{e['longitude']:>11.4f}°")
    lines.append("-" * 58)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m AI_tools.cli.show_nakshatra_positions",
        description=(
            "Print each body's nakshatra (index, name, pada) and longitude, plus "
            "the Lagna, matching the Core F2 Nakshatra wheel. Positions only: "
            "no lord, deity, yoni, gana or interpretive text."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m AI_tools.cli.show_nakshatra_positions chart.chtk --json\n"
            "  python -m AI_tools.cli.show_nakshatra_positions chart.toml "
            "--frame tropical\n"
            "  python -m AI_tools.cli.show_nakshatra_positions chart.chtk "
            "--ayanamsa lahiri --json\n\n"
            "Default frame is sidereal at the settings ayanamsa (zodiac."
            "ayanamsa_id), matching the F2 wheel. --frame tropical is a CLI-only "
            "override (ayanamsa 0) with no wheel counterpart."),
    )
    parser.add_argument("chart", help="Input chart file (.chtk or .toml)")
    parser.add_argument(
        "--frame", choices=("sidereal", "tropical"), default="sidereal",
        help="Nakshatra frame. sidereal (default) applies the ayanamsa; tropical "
             "applies none (ayanamsa 0). CLI-only override.")
    parser.add_argument(
        "--ayanamsa", default=None,
        help="Sidereal ayanamsa id or name (overrides the settings default). "
             "Ignored when --frame is tropical.")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the positions as JSON instead of a table.")
    args = parser.parse_args(argv)

    if not os.path.exists(args.chart):
        print(f"Error: input file not found: {args.chart}", file=sys.stderr)
        return 2
    try:
        payload = compute_positions(args.chart, args.frame, args.ayanamsa)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface any read/calc failure cleanly
        print(f"Error: failed to compute nakshatra positions: {exc}",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_format_table(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
