# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The right dasha panel's other two modes: ``get_planetary_ages`` (Nisarga)
and ``get_zodiacal_releasing`` (AIC plan 2 W7, wave 1 row 5).

- Planetary Ages: ``core/nisarga_dasha.format_nisarga_level1/2`` on the
  chart's local civil birth date (the panel's ``current_chart_data`` Y/M/D),
  with an explicit "today": the input's reference instant seen as the
  COMPUTER's local date, which is what the panel's ``date.today()`` reads
  (not the chart's timezone: near midnight the two differ by a day).
- Zodiacal Releasing: ``compute_zr`` (the panel and ``show_zodiacal_releasing``
  already share it) plus ``zr_display_rows``, the drill selection the panel
  applies (now in ``core/zodiacal_releasing.py``, SPEC-DSH-004), and
  ``format_level`` for the row text.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _local_date(jd_ut: float, utc_offset_hours: float):
    from datetime import date
    from core.time_utils import display_revjul
    y, m, d, _h = display_revjul(jd_ut + (utc_offset_hours or 0.0) / 24.0,
                                 "astronomical")
    return date(int(y), int(m), int(d))


def _computer_local_date(jd_ut: float):
    """The date the computer's clock shows at the instant ``jd_ut``: the
    panel's ``date.today()`` for that instant (system timezone, DST included).
    An instant outside the platform's timestamp range falls back to its UTC
    date."""
    from datetime import datetime
    try:
        return datetime.fromtimestamp((jd_ut - 2440587.5) * 86400.0).date()
    except (OverflowError, OSError, ValueError):
        return _local_date(jd_ut, 0.0)


def planetary_age_rows(chart_data: Dict[str, Any], level: int, *,
                       date_format: str, today) -> List[Dict[str, Any]]:
    from core.nisarga_dasha import format_nisarga_level1, format_nisarga_level2
    y, m, d = chart_data.get("year"), chart_data.get("month"), chart_data.get("day")
    if not all([y, m, d]):
        return []
    fn = format_nisarga_level2 if level == 2 else format_nisarga_level1
    return fn(y, m, d, date_format=date_format, today=today)


# SPEC-DSH-004: the ZR drill selection lives in core/zodiacal_releasing.py
# (shared with the panel renderer and the LTS branch, which has no capabilities).
from core.zodiacal_releasing import zr_display_rows  # noqa: E402,F401


# ------------------------------------------------------------ capabilities

def _run_ages(inp, options):
    from core.capabilities.dasha import chart_civil_data
    chart_data = chart_civil_data(inp.build_chart(natal=True), inp.chart.title)
    today = _computer_local_date(inp.view.reference_jd)
    rows = planetary_age_rows(chart_data, options["level"],
                              date_format=options["date_format"], today=today)
    return {"level": options["level"], "today": today.isoformat(),
            "rows": rows,
            "current_rows": [i for i, r in enumerate(rows) if r.get("is_current")],
            "maturation_rows": [i for i, r in enumerate(rows) if r.get("is_maturation")]}


def _run_zr(inp, options):
    from AI_tools.AI_main_function.zodiacal_releasing import compute_zr
    from core.capabilities.dasha import chart_civil_data
    from core.zodiacal_releasing import format_level
    chart_data = chart_civil_data(inp.build_chart(natal=True), inp.chart.title)
    result = compute_zr(chart_data, mode=inp.frame.mode,
                        ayanamsa=inp.frame.ayanamsa_id,
                        releaser=options["releaser"],
                        spirit_shift=options["spirit_shift"],
                        anchor=options["anchor"], horizon_years=150, levels=1,
                        on_jd=inp.view.reference_jd)
    # Drill: indices into each shown level, e.g. [2, 0] = third L1 period, then
    # its first L2 period (the panel's parent chain, built by clicking).
    chain: List[Dict[str, Any]] = []
    for depth, index in enumerate(options["drill"] or []):
        shown = zr_display_rows(result, depth + 1, chain)
        if not 0 <= index < len(shown):
            raise ValueError(f"drill index {index} out of range at level "
                             f"{depth + 1} ({len(shown)} periods)")
        chain.append(shown[index])
    level = len(chain) + 1
    if level > 4:
        raise ValueError("Zodiacal Releasing has 4 levels")
    rows = zr_display_rows(result, level, chain)
    entries = format_level(
        rows, level, now_jd=result["target_jd"], mode=inp.frame.mode,
        use_western=inp.frame.use_western_names,
        birth_jd=result["birth_jd_utc"], tz_offset_hours=result["tz_offset_hours"],
        date_format=options["date_format"],
        convention=options["calendar_convention"])
    return {"level": level,
            "drill": [{"pos": p["pos"], "start_jd": p["start_jd"],
                       "end_jd": p["end_jd"]} for p in chain],
            "releaser": result.get("releaser"), "label_token": result.get("label_token"),
            "releaser_pos": result.get("releaser_pos"),
            "fortune_pos": result.get("fortune_pos"),
            "birth_jd_utc": result["birth_jd_utc"], "target_jd": result["target_jd"],
            "rows": entries,
            "current_rows": [i for i, e in enumerate(entries) if e.get("is_current")]}


# Settings-following properties from the settings registry (SPEC-SET-003 §4.4).
from core.settings_registry import option_schema as _setting  # noqa: E402
from core.capabilities.setting_args import INPUT, setting  # noqa: E402

_DATE_OPTS = {"date_format": _setting("display.date_format", "date_format")}

# Every property classified (SPEC-SET-003 §4.4, W0b inventory).
SETTING_ARGS = {
    "get_planetary_ages": {"level": INPUT, "date_format": setting("display.date_format")},
    "get_zodiacal_releasing": {
        "releaser": setting("dasha.zr.releaser"),
        "spirit_shift": setting("dasha.zr.spirit_shift"),
        "anchor": setting("dasha.zr.anchor"),
        "drill": INPUT,
        "date_format": setting("display.date_format"),
        "calendar_convention": setting("display.calendar_convention")},
}


def _register():
    from core.capabilities.catalog import Capability, register
    register(Capability(
        id="get_planetary_ages", title="Planetary Ages",
        description=("Planetary Ages (Nisarga dasha) as the right dasha panel "
                     "lists it: level 1 periods or level 2 sub-periods with "
                     "dates, the current period and the maturation marks, for "
                     "the input's reference date."),
        run=_run_ages,
        setting_args=SETTING_ARGS["get_planetary_ages"],
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"level": {"type": "integer", "enum": [1, 2],
                                                 "default": 1},
                                       **_DATE_OPTS}},
        output_schema={"type": "object", "required": ["level", "today", "rows"]},
        sources=(("core/nisarga_dasha.py", "format_nisarga_level1"),
                 ("core/nisarga_dasha.py", "format_nisarga_level2"))))
    register(Capability(
        id="get_zodiacal_releasing", title="Zodiacal Releasing",
        description=("Zodiacal Releasing periods as the right dasha panel lists "
                     "them, one level at a time: level 1, or the sub-periods of "
                     "the opened parent periods (drill), with the current one "
                     "marked. Follows the saved releaser settings unless given."),
        run=_run_zr,
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {
                            "releaser": _setting("dasha.zr.releaser", "releaser",
                                                 description=("spirit, fortune, sign:<0-11> "
                                                              "or lot:<name>")),
                            "spirit_shift": _setting("dasha.zr.spirit_shift",
                                                     "spirit_shift"),
                            "anchor": _setting("dasha.zr.anchor", "anchor"),
                            "drill": {"type": "array", "items": {"type": "integer",
                                                                 "minimum": 0},
                                      "default": [],
                                      "description": ("Opened periods as indices "
                                                      "into each shown level.")},
                            **_DATE_OPTS,
                            "calendar_convention": _setting(
                                "display.calendar_convention", "calendar_convention")}},
        setting_args=SETTING_ARGS["get_zodiacal_releasing"],
        output_schema={"type": "object", "required": ["level", "drill", "rows"]},
        sources=(("AI_tools/AI_main_function/zodiacal_releasing.py", "compute_zr"),
                 ("core/zodiacal_releasing.py", "zr_display_rows"),
                 ("core/zodiacal_releasing.py", "format_level"))))


_register()
