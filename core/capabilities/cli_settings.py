# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Shared helpers of the command-line tools (AIC plan 2 v1.2, SPEC-SET-003).

Settings come from the registry, never from a tool's own flags (D-13): a CLI
names the settings it uses with ``core.settings_registry.cli.use_settings``
and reads them with ``resolve_settings`` (``--set``, the tools' settings file,
the running app, the saved Settings tab file, the factory default;
``--factory-defaults`` keeps the factory layer only). This module keeps what
those CLIs share on top of that: the ``--factory-defaults`` flag, the settings
view (``settings_view``), the view options (``--human-design``, ``--varga``)
and the chart builds that follow the app's view, the sign-name relabelling,
and the read-only settings manager for widget-backed renderers:

    from core.settings_registry.cli import use_settings, resolve_settings
    from core.capabilities.cli_settings import add_view_flags, cli_chart
    from core.capabilities.inputs import ChartFrame
    use_settings(parser, USES)
    add_view_flags(parser)
    args = parser.parse_args()
    cfg = resolve_settings(args)
    frame = ChartFrame.resolve(cfg.view)
    chart, inp = cli_chart(path, args, frame)

The W6 shims (``add_frame_args``, ``cli_frame``, ``cli_setting`` and their
explicit-value parameters) were removed in W12 once no caller was left
(test/test_cli_settings_migration.py).

Qt-free; reading the settings never creates a file (SettingsView).
"""
from __future__ import annotations

from typing import Optional

FACTORY_FLAG = "--factory-defaults"

# Wording approved by Lorris, 2026-10-11 (W12-R4).
_HELP = "Use the factory settings instead of your saved ones."


def add_settings_flag(parser) -> None:
    """Add ``--factory-defaults`` to an argparse parser (idempotent)."""
    if FACTORY_FLAG not in getattr(parser, "_option_string_actions", {}):
        parser.add_argument(FACTORY_FLAG, dest="factory_defaults",
                            action="store_true", help=_HELP)

def settings_view(args_or_flag=None):
    """The settings every helper below reads (SPEC-SET-003 W6): the
    effective-settings API's TERMINAL context (the tools' settings file >
    running app > saved file > factory; ``--set`` once a CLI is moved onto
    ``use_settings``), or the APP context for a child the running app
    started with its trusted app block. ``--factory-defaults`` (or a True
    flag) keeps the factory layer only. Exits 2 on a damaged or newer tools'
    settings file, naming it."""
    from core.settings_registry.cli import view_for
    return view_for(args_or_flag)

def _frame(args_or_flag=None):
    """The chart frame of the settings ``settings_view`` resolves (a caller
    that passes no frame of its own)."""
    from core.capabilities.inputs import ChartFrame
    return ChartFrame.resolve(settings_view(args_or_flag))

# ------------------------------------------------------------------ the view
#
# A CLI that prints what a chart panel or chart view shows for the ACTIVE chart
# must also follow what is on screen: in Human Design mode the app's active
# chart is the -88 Design chart (``CalculationInput.build_chart``), and the
# chart views draw the selected varga. These helpers resolve the view with the
# one rule (``core.capabilities.inputs.resolve_view``: argument > running app
# > factory; never the saved file; ``--factory-defaults`` ignores the running
# app) and build the chart exactly as the capabilities do:
#
#     use_settings(parser, USES)
#     add_view_flags(parser)                   # --human-design (--varga)
#     args = parser.parse_args()
#     frame = ChartFrame.resolve(resolve_settings(args).view)
#     chart, inp = cli_chart(path, args, frame)
#     display_mode, western = inp.chart_display()   # the drawings' label set
#
# Every other input path of such a CLI (--date/--time, --datetime, a birth
# JSON) builds its chart with ``cli_moment_chart`` (a CalculationInput of the
# moment, then build_chart), so Human Design gives the same Design chart as the
# file path; ``cli_datetime_jd`` is the shared --date/--time parse.
#
# A CLI whose subject is the birth chart even in the app's Human Design mode
# (dasha, Zodiacal Releasing, eclipses, transits, returns) does not use them.

def add_view_flags(parser, *, varga: bool = False) -> None:
    """The view options only: ``--human-design/--no-human-design`` (plus
    ``--varga`` for a varga-aware CLI), each ``None`` by default (not given =
    what the running app shows), with ``add_view_args``'s option strings and
    help. The Human Design level is the setting ``ui.hd_experience_level``
    (no flag, D-13) and ``use_settings`` adds ``--factory-defaults``."""
    import argparse
    have = getattr(parser, "_option_string_actions", {})
    if "--human-design" not in have:
        parser.add_argument(
            "--human-design", dest="human_design",
            action=argparse.BooleanOptionalAction, default=None,
            help="the -88 Design chart (Human Design mode); --no-human-design "
                 "for the birth chart (default: what the running app shows, "
                 "else the birth chart)")
    if varga and "--varga" not in have:
        parser.add_argument(
            "--varga", type=int, default=None,
            help="divisional chart number (default: the running app's varga, "
                 "else 1)")


def cli_view(args_or_flag=None, *, varga: bool = False, **explicit):
    """The ViewState of a CLI run (``resolve_view``). ``explicit`` values
    (``human_design``, ``varga``) win over ``args``; ``varga=False`` (a CLI
    that always shows the rashi chart) pins the varga to 1."""
    from core.capabilities.inputs import resolve_view
    values = {}
    for name in ("human_design", "varga"):
        value = explicit.get(name)
        if value is None:
            value = getattr(args_or_flag, name, None)
        values[name] = value
    if not varga:
        values["varga"] = 1
    return resolve_view(settings_view(args_or_flag), **values)

def cli_input(path, args_or_flag=None, frame=None, *, varga: bool = False,
              **explicit):
    """The ``CalculationInput`` for a chart file: the file read read-only,
    ``frame`` (a ``ChartFrame``; None resolves one from ``args``) and the
    view (``cli_view``)."""
    from core.capabilities.inputs import CalculationInput
    settings = settings_view(args_or_flag)
    inp = CalculationInput.from_file(
        str(path), settings=settings,
        view=cli_view(args_or_flag, varga=varga, **explicit))
    if frame is not None:
        inp.frame = frame
    else:
        inp.frame = _frame(args_or_flag)
    return inp

def cli_chart(path, args_or_flag=None, frame=None, *, varga: bool = False,
              mode: Optional[str] = None, natal=None, **explicit):
    """``(chart, inp)``: the chart the app's panels read for this file
    (``CalculationInput.build_chart``: the -88 Design chart in Human Design
    mode, else the birth chart). ``mode`` overrides the build mode as
    ``build_chart`` does. The varga is NOT applied: a varga-aware CLI reads
    ``inp.view.varga``.

    ``natal``: a zero-argument callable returning the CLI's own birth chart,
    used outside Human Design mode so a CLI whose historical loader differs
    from the app's (``extraction.extract_from_chtk``) keeps its output
    unchanged; None builds the birth chart with ``build_chart`` too."""
    inp = cli_input(path, args_or_flag, frame, varga=varga, **explicit)
    if natal is not None and not inp.view.human_design:
        return natal(), inp
    return inp.build_chart(mode=mode), inp

def cli_datetime_jd(date_str: str, time_str: Optional[str] = None) -> float:
    """The Julian Day (UT) of a CLI's ``--date YYYY-MM-DD`` and optional
    ``--time HH:MM`` (noon when absent), with the app's calendar rule
    (``core.time_utils.julday``: Julian before 1582-10-15). The CLIs'
    historical date parsing, shared so the natal and the Design chart of a
    date input are built from the same instant."""
    from core.time_utils import julday
    year, month, day = (int(part) for part in date_str.split("-")[:3])
    hour, minute = 12, 0
    if time_str:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    return julday(year, month, day, hour + minute / 60.0)

def cli_moment_input(args_or_flag=None, frame=None, *, jd_ut: float,
                     latitude: float, longitude: float,
                     utc_offset_hours: float = 0.0, title: str = "",
                     varga: bool = False, **explicit):
    """The ``CalculationInput`` of a chart that is not a file (a CLI's
    ``--date/--time``, ``--datetime``, a birth JSON): the moment as given,
    ``frame`` (a ``ChartFrame``; None resolves one from ``args``) and the
    view (``cli_view``: argument > running app > factory). The twin of
    ``cli_input`` for a moment, so every input path of a CLI resolves the
    view, and builds the chart, one way."""
    from core.capabilities.inputs import CalculationInput, ChartMoment
    settings = settings_view(args_or_flag)
    moment = ChartMoment(
        jd_ut=float(jd_ut), latitude=float(latitude),
        longitude=float(longitude),
        # an explicit 0.0 is a valid offset: never `or` it away
        utc_offset_hours=float(utc_offset_hours) if utc_offset_hours is not None else 0.0,
        title=str(title or ""))
    return CalculationInput(
        chart=moment,
        frame=frame if frame is not None else _frame(args_or_flag),
        view=cli_view(args_or_flag, varga=varga, **explicit),
        settings=settings.describe())

def cli_moment_chart(args_or_flag=None, frame=None, *, jd_ut: float,
                     latitude: float, longitude: float,
                     utc_offset_hours: float = 0.0, title: str = "",
                     varga: bool = False, mode: Optional[str] = None,
                     natal=None, **explicit):
    """``(chart, inp)`` for a moment input: exactly ``cli_chart`` for a chart
    that is not a file. In Human Design mode the -88 Design chart of that
    moment (``CalculationInput.build_chart``), as the chart-file path builds
    it; otherwise ``natal()`` (the CLI's historical birth-chart build, so its
    output is unchanged) or, when None, ``build_chart``."""
    inp = cli_moment_input(args_or_flag, frame, jd_ut=jd_ut, latitude=latitude,
                           longitude=longitude,
                           utc_offset_hours=utc_offset_hours, title=title,
                           varga=varga, **explicit)
    if natal is not None and not inp.view.human_design:
        return natal(), inp
    return inp.build_chart(mode=mode), inp

def relabel_sign_name(sign_name, use_western_names, sign_language="en"):
    """The label shown for ``sign_name`` under the chosen label set.

    ``sign_name`` is an engine sign name from either set (a chart built in
    aditya mode names its signs Dhata..Parjanya, tropical_classic and sidereal
    charts Aries..Pisces). Its ORDINAL is kept (Dhata = Aries = 1) and only
    the label set is chosen, through ``core.aditya_mode.displayed_sign_name``:
    the chart wheel's rule. Never a longitude conversion. Anything else (None,
    "?", an unknown string) is returned unchanged. With ``frame`` a
    ``ChartFrame``: ``relabel_sign_name(name, frame.use_western_names)``; for
    the mode's own names (the Beginner label set) it is the identity.
    """
    from core.aditya_mode import ADITYA_NAMES, TROPICAL_NAMES, displayed_sign_name
    if isinstance(sign_name, str):
        for names in (ADITYA_NAMES, TROPICAL_NAMES):
            if sign_name in names:
                return displayed_sign_name(names.index(sign_name), None,
                                           use_western_names, sign_language)
    return sign_name

def use_read_only_settings(args_or_flag=None):
    """For a CLI that runs app widget code reading ``get_settings()`` (the
    chart renderers): install the process-wide SettingsManager as an in-memory
    copy of the same resolved settings (``settings_view``: the terminal
    context's layers, or factory with ``--factory-defaults``) whose saves do
    nothing, so the drawing reads exactly what the calculation read (INV-4b).

    Live values of the running app (``SettingsView``) are applied on top.
    Without it the first ``get_settings()`` creates ``app_settings.json`` (and
    a lock file) on a first run and rewrites the file for its one-time
    migrations, and a widget's runtime ``set`` (or ``set_api_key``) would
    persist. The manager is a ``ReadOnlySettingsManager``
    (read_only_settings.py). Call it before any widget is built. Returns the
    installed manager."""
    import managers.settings_manager as sm
    from core.capabilities.read_only_settings import build_read_only_settings
    mgr = build_read_only_settings(settings_view(args_or_flag))
    sm._instance = mgr
    return mgr
