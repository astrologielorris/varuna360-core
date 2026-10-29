# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_dasha``: a Vimshottari dasha side (AIC plan 2 W7, wave 1 row 5).

``dasha_side_rows`` is the side's list as the panel shows it: the same compute
decision (``managers/dasha/engine.decide_compute``: full list, the sub-periods
of a drilled parent, or a probe), the same filter walk, row text, age column,
cycle-offset date shift and current-period highlight. The Qt side controller
renders its rows; the tool returns them with the raw JDs.

Every preference is an explicit argument (resolved by the catalog from the
saved settings, like the panel's own readers): side ayanamsa, year length,
nakshatra coordinates, date format, calendar convention. The panel's view
state (level, drilled parent chain, cycle offset, Human Design) and the
reference instant ("now", for the current period) are explicit too.

The dasha is seeded from the chart's civil data built the panel's way
(``recipe_from_chart`` -> ``chart_data_from_recipe``, the path of
``ChartGUI.current_chart_data``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

LEFT, RIGHT = "left", "right"
SIDE_DEFAULT_AYANAMSA = {LEFT: 100, RIGHT: 98}    # managers/dasha_state.py:33-34


def chart_civil_data(chart, title: str = "") -> Dict[str, Any]:
    """The ``current_chart_data`` dict the panel reads, from a Chart."""
    from core.chart_factory import chart_data_from_recipe, recipe_from_chart
    return chart_data_from_recipe(recipe_from_chart(chart, name=title))


def compute_side(params: Dict[str, Any], *, ayanamsa: int, year_length: str,
                 nak_mode: str, level: int, chain: List, cached_rows=None,
                 date_format: Optional[str] = None, convention: Optional[str] = None,
                 now_jd_ut: Optional[float] = None, on_reset=None):
    """The rows one Vimshottari side lists: THE dasha calculation of the Dasha
    panel (both sides, VimshottariSideController.update) and of get_dasha.

    ``params`` is ``get_dasha_params(chart_data, is_human_design=...)``. The
    engine decides the step (full list, sub-periods of the drilled parent, or a
    probe); ``None`` for date_format / convention / now means the app's own
    reading (settings in memory, the clock), which the panel keeps.

    Returns ``(rows, used_focused, reset)``; ``reset`` True means the drilled
    parent no longer exists and the side must go back to level 1, no chain.
    ``on_reset`` (optional) runs BEFORE that fallback compute, the order the
    panel pins (sol r1-4: level/chain/buttons reset, then compute).
    """
    from core.vimshottari_dasha import (
        calculate_dasha_from_birth_data, calculate_sub_dashas_for_period)
    from managers.dasha import engine

    y, mo, d = params["year"], params["month"], params["day"]
    h, mi, s = params["hour"], params["minute"], params["second"]
    tz = params["tz_offset"]
    moon_override = params["moon_jd_override"]

    def full(dlevels):
        return calculate_dasha_from_birth_data(
            y, mo, d, h, mi, s, dlevels=dlevels, ayanamsa=ayanamsa,
            tz_offset_hours=tz, moon_jd_override=moon_override,
            nak_mode=nak_mode, year_length=year_length,
            date_format=date_format, convention=convention,
            now_jd_ut=now_jd_ut)

    def sub(parent, lord):
        return calculate_sub_dashas_for_period(
            parent["jd"], parent["end_jd"], lord, ayanamsa=ayanamsa,
            tz_offset_hours=tz, date_format=date_format,
            convention=convention, now_jd_ut=now_jd_ut, birth_ymd=(y, mo, d))

    step = engine.decide_compute(level, chain, cached_rows)
    if step.kind == "full":
        return full(step.dlevels), False, False
    if step.kind == "sub":
        return sub(step.parent, step.parent_lord), True, False
    step2 = engine.decide_after_probe(full(step.dlevels), step.parent_lord)
    if step2.kind == "sub":
        return sub(step2.parent, step2.parent_lord), True, False
    if on_reset is not None:
        on_reset()
    return full(step2.dlevels), False, True


def dasha_side_rows(chart_data: Dict[str, Any], *, ayanamsa: int,
                    year_length: str, nak_mode: str, level: int = 1,
                    drill: Optional[List[str]] = None, cycle_offset: int = 0,
                    human_design: bool = False, date_format: str,
                    convention: str, now_jd_ut: Optional[float] = None
                    ) -> Dict[str, Any]:
    """The visible rows of one dasha side, as the panel computes them."""
    from AI_tools.AI_main_function.dasha import get_dasha_params
    from managers.dasha import engine

    params = get_dasha_params(chart_data, is_human_design=human_design)
    kw = dict(ayanamsa=ayanamsa, year_length=year_length, nak_mode=nak_mode,
              date_format=date_format, convention=convention, now_jd_ut=now_jd_ut)

    # set_level: trim the drill to the level; an empty chain at level >= 2 is
    # built from the current periods (SideController.set_level/auto_build_chain).
    chain = engine.trim_chain_for_level(list(drill or []), level)
    if not chain and level >= 2:
        first, _f, _r = compute_side(params, level=level - 1, chain=[], **kw)
        chain = engine.auto_chain(first, level - 1)
    rows, used_focused, reset = compute_side(params, level=level, chain=chain, **kw)
    if reset:
        chain, level = [], 1

    years = engine.shift_years(cycle_offset)
    visible, capped = engine.filter_rows(rows, chain, level, used_focused)
    birth_ymd = (chart_data.get("year"), chart_data.get("month"), chart_data.get("day"))
    out = []
    for display_idx, (_src, entry) in enumerate(visible):
        jd = entry.get("jd")
        date_str = entry["date"]
        if years != 0 and jd:
            date_str = engine.display_date_at_offset(
                jd, years, date_format=date_format, convention=convention)
        age = engine.age_text(jd, birth_ymd, years)
        marked = entry.get("is_current", False) and cycle_offset == 0
        out.append({"lord": entry["lord"], "jd": jd, "end_jd": entry.get("end_jd"),
                    "date": date_str, "time": entry.get("time"), "age": age,
                    "is_current": bool(entry.get("is_current", False)),
                    "depth": entry["lord"].count("/") + 1,
                    "text": engine.row_text(entry, date_str, age, marked)})
    return {"level": level, "drill": chain, "cycle_offset": cycle_offset,
            "capped": capped,
            "current_rows": sorted(engine.highlight_rows(visible, cycle_offset)),
            "rows": out}


def _run(inp, options):
    side = options["side"]
    ayanamsa = options["dasha_ayanamsa_id"]
    if ayanamsa is None:
        ayanamsa = options[f"{side}_ayanamsa_id"]
    chart = inp.build_chart(natal=True)     # current_chart_data: birth data
    data = dasha_side_rows(
        chart_civil_data(chart, inp.chart.title),
        ayanamsa=ayanamsa, year_length=options["year_length"],
        nak_mode=inp.frame.nakshatra_coords, level=options["level"],
        drill=options["drill"] or [], cycle_offset=options["cycle_offset"],
        human_design=inp.view.human_design, date_format=options["date_format"],
        convention=options["calendar_convention"],
        now_jd_ut=inp.view.reference_jd)
    data.update({"side": side, "dasha_ayanamsa_id": ayanamsa,
                 "year_length": options["year_length"],
                 "nakshatra_coords": inp.frame.nakshatra_coords,
                 "reference_jd": inp.view.reference_jd})
    return data


# Settings-following properties come from the settings registry (SPEC-SET-003
# §4.4): type, values and default declared once, in the registry entry.
from core.settings_registry import OMIT as _OMIT, option_schema as _setting  # noqa: E402
from core.capabilities.setting_args import (  # noqa: E402
    INPUT, setting, side_setting)

OPTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "side": {"type": "string", "enum": [LEFT, RIGHT], "default": LEFT,
                 "description": "Dasha panel side; sets the default ayanamsa."},
        "dasha_ayanamsa_id": {"type": "integer",
                              "description": "Override the side's dasha ayanamsa."},
        "left_ayanamsa_id": _setting("dasha.left.ayanamsa_id", "left_ayanamsa_id",
                                     enum=_OMIT),
        "right_ayanamsa_id": _setting("dasha.right.ayanamsa_id", "right_ayanamsa_id",
                                      enum=_OMIT),
        "year_length": _setting("dasha.year_length.nakshatra", "year_length"),
        "level": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1},
        "drill": {"type": "array", "items": {"type": "string"}, "default": [],
                  "description": ("Opened parent periods, e.g. [\"Ju\", "
                                  "\"Ju/Me\"]; empty = the current periods.")},
        "cycle_offset": {"type": "integer", "default": 0,
                         "description": "120-year cycle shift of the dates."},
        "date_format": _setting("display.date_format", "date_format"),
        "calendar_convention": _setting("display.calendar_convention",
                                        "calendar_convention"),
    },
}

# Every property classified (SPEC-SET-003 §4.4, W0b inventory). dasha_ayanamsa_id
# is the untagged alias: the side's ayanamsa, absent or null = follow the side.
SETTING_ARGS = {"get_dasha": {
    "side": INPUT,
    "dasha_ayanamsa_id": side_setting("dasha.{side}.ayanamsa_id", "side"),
    "left_ayanamsa_id": setting("dasha.left.ayanamsa_id"),
    "right_ayanamsa_id": setting("dasha.right.ayanamsa_id"),
    "year_length": setting("dasha.year_length.nakshatra"),
    "level": INPUT,
    "drill": INPUT,
    "cycle_offset": INPUT,
    "date_format": setting("display.date_format"),
    "calendar_convention": setting("display.calendar_convention"),
}}
# Two properties name one key: the alias wins (``_run``), winner first.
SETTING_PRECEDENCE = {"get_dasha": {
    "dasha.left.ayanamsa_id": ("dasha_ayanamsa_id", "left_ayanamsa_id"),
    "dasha.right.ayanamsa_id": ("dasha_ayanamsa_id", "right_ayanamsa_id"),
}}


def _register():
    from core.capabilities.catalog import Capability, register
    register(Capability(
        id="get_dasha", title="Vimshottari dasha",
        description=("One Vimshottari dasha side as the Dasha panel lists it: "
                     "periods at the chosen level (1 to 5), inside an opened "
                     "parent period or around the current ones, with dates, "
                     "ages and the current period marked. Follows the saved "
                     "dasha ayanamsa, year length, nakshatra coordinates and "
                     "date settings unless given."),
        run=_run, options_schema=OPTIONS_SCHEMA,
        setting_args=SETTING_ARGS["get_dasha"],
        setting_precedence=SETTING_PRECEDENCE["get_dasha"],
        output_schema={"type": "object",
                       "required": ["side", "level", "drill", "rows",
                                    "dasha_ayanamsa_id", "year_length"]},
        sources=(("core/vimshottari_dasha.py", "calculate_dasha_from_birth_data"),
                 ("managers/dasha/engine.py", "decide_compute"),
                 ("core/capabilities/dasha.py", "dasha_side_rows"))))


_register()
