# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Appearance, general UI and legacy font-size settings (SPEC-SET-003). Defaults
moved from DEFAULT_SETTINGS["appearance"], ["font_sizes"], ["ui"], ["windows"],
["defaults"] and RENDERER_FALLBACKS; values unchanged."""
from dataclasses import replace

from core.settings_registry.rules import APP, APP_AI, APP_PROTECTED, CALC_AI
from core.settings_registry.schema import Choice, Setting

_AP = "appearance"
_ZC = "zodiac_calculation"
_LEVELS = (Choice("beginner", "Beginner"), Choice("advanced", "Advanced"))
_V = "core.settings_registry.validators:"

_LEGACY_FONT_SIZES = (("chart_title", 12), ("chart_degree", 8), ("chart_planet", 10),
                      ("dasha_header", 14), ("dasha_body", 11), ("button", 11),
                      ("label", 10), ("heading", 16), ("body", 13), ("small", 11),
                      ("tiny", 10))

SETTINGS = (
    # The theme cards list the installed themes (ui.qt_theme): a run-time catalog.
    # Lorris, 2026-10-29: a fresh install opens in Light Blue (more professional
    # than the dark look). Every boot fallback reads this via ui.themes.
    Setting(
        "appearance.theme",
        str,
        "Light Blue",
        widget="custom",
        section=_AP,
        rules=replace(APP_AI, validate=_V + "catalog_name"),
    ),
    Setting(
        "appearance.font_family",
        str,
        "Inter",
        rules=replace(APP, validate=_V + "free_text"),
    ),
    Setting(
        "appearance.font_size_preset",
        str,
        "medium",
        rules=replace(APP, validate=_V + "free_text"),
    ),
    Setting(
        "appearance.deep_dark",
        bool,
        False,
        persisted=False,
        label="Deeper background (near-black)",
        help="Deepens the background of the selected DARK theme toward black, "
        "keeping its accent colour and text. No effect on light themes.",
        widget="check",
        section=_AP,
        live=True,
        watch="appearance.deep_dark",
        rules=APP_AI,
    ),
    *(
        Setting(
            f"font_sizes.{name}",
            int,
            size,
            rules=replace(APP, validate=_V + "free_number"),
        )
        for name, size in _LEGACY_FONT_SIZES
    ),
    Setting(
        "ui.restore_last_tab",
        bool,
        True,
        label="Restore last tab:",
        widget="check",
        section=_AP,
        rules=APP_AI,
    ),
    # SPEC-FIND-004 §5.2: "Don't ask again" on the Find Chart compute
    # confirmation. Protected (INV-17): only that dialog's checkbox writes it.
    # Fallback-only, so saved settings files do not change.
    Setting(
        "ui.find_chart_compute_dont_ask",
        bool,
        False,
        persisted=False,
        label="Find Chart: compute without asking",
        rules=APP_PROTECTED,
    ),
    # Lorris, 2026-10-18: the CPU share a Find Chart background compute keeps
    # to (core/chart_search/compute_process.py), so the app stays usable.
    Setting(
        "ui.find_chart_compute_cpu_percent",
        int,
        40,
        label="Find Chart compute CPU (%):",
        help="How much of one processor core a Find Chart compute may use while "
        "it runs in the background. Lower keeps the app faster while it "
        "computes; higher finishes sooner.",
        bounds=(10, 100),
        widget="spin",
        section="folders",
        rules=APP_AI,
    ),
    # varuna/45: the Find Chart system bar's pinned fields ({field: value},
    # SearchSystem.with_values), so the bar reopens where the user left it.
    # Find Chart's own, never the app's zodiac settings; only the bar writes it.
    Setting(
        "ui.find_chart_system_pins",
        dict,
        {},
        persisted=False,
        label="Find Chart: pinned search system",
        rules=replace(APP_PROTECTED, validate=_V + "text_map"),
    ),
    # varuna/47: the Find Chart panel's sign-name switcher (SignNames values):
    # "system" names the signs after the search system. Find Chart's own,
    # never the app's naming; only the switcher writes it.
    Setting(
        "ui.find_chart_sign_names",
        str,
        "system",
        persisted=False,
        label="Find Chart: sign names",
        choices=(
            Choice("system", "By system"),
            Choice("aditya", "Aditya names"),
            Choice("zodiac", "Zodiac names"),
        ),
        rules=APP_PROTECTED,
    ),
    # SPEC-FIND-005 §3.2: the Find Chart panel's Easy / Advanced switch.
    # Easy offers the common search with the app's own frame and names;
    # Advanced adds the scope bar, the system pins and the full picker. Only
    # the panel's switch writes it.
    Setting(
        "ui.find_chart_search_level",
        str,
        "easy",
        persisted=False,
        label="Find Chart: search level",
        choices=(
            Choice("easy", "Easy"),
            Choice("advanced", "Advanced"),
        ),
        rules=APP_PROTECTED,
    ),
    # SPEC-FIND-005 §3.5: the Find Chart result columns (PLACEMENTS 3 / ALL
    # and the column groups). Only the panel's results bar writes it.
    Setting(
        "ui.find_chart_result_columns",
        dict,
        {"all_placements": False, "groups": []},
        persisted=False,
        label="Find Chart: result columns",
        rules=APP_PROTECTED,
    ),
    # SPEC-FIND-005 §3.7 (review r10): folders taken off the chart folder
    # list whose files the index has not let go yet (the forget runs in the
    # background and can fail). Find Chart leaves their files out of every
    # search meanwhile and asks again when it opens. Only the panel writes it.
    Setting(
        "ui.find_chart_forget_owed",
        list,
        [],
        persisted=False,
        label="Find Chart: removed folders still in the index",
        rules=replace(APP_PROTECTED, validate=_V + "text_list"),
    ),
    # SPEC-FIND-005 §4.9: Sort with AI, off by default (INV-8). Only the
    # Library's switch writes it.
    Setting(
        "ui.find_chart_sort_with_ai",
        bool,
        False,
        persisted=False,
        label="Find Chart: Sort with AI",
        rules=APP_PROTECTED,
    ),
    # SPEC-LIB-002 §3.6, D-11: charts offered per Rate and Sort visit.
    Setting(
        "ui.library_visit_size",
        int,
        5,
        label="Charts per rating visit:",
        help="How many charts the Library's Rate and Sort offers at a time.",
        bounds=(1, 50),
        widget="spin",
        section="folders",
        rules=APP_AI,
    ),
    # SPEC-LIB-002 §4.12: the Library's COVERAGE fold is open.
    Setting(
        "ui.find_chart_coverage_open",
        bool,
        False,
        persisted=False,
        label="Find Chart: coverage details open",
        rules=APP,
    ),
    # SPEC-BAR-001: Vibrancy Segmented is the migrated default.
    Setting("ui.action_bar_v2", bool, True, widget="check", section=_AP, rules=APP_AI),
    # SPEC-BAR-001 D-5: hide the Human Design button; the Sidereal zodiac
    # segment takes its tray slot. Typed contract in spec §4.
    Setting("ui.hide_human_design", bool, False, rules=APP_AI),
    # SPEC-BAR-001 M4 (Dm4-48/49): the mockup's prefers-reduced-motion
    # reading — the breathing NOW dot pins at 0.85, the 160/180 ms
    # transitions KEEP running. Same typed contract as hide_human_design.
    Setting("ui.reduce_motion", bool, False, label="Reduce motion:",
            help="Stops the breathing \"live\" indicator on the chart bar's NOW "
                 "button. Short fades on hover and state changes are kept.",
            widget="check", section=_AP, rules=APP_AI),
    # SPEC-MODE-001: Beginner hides alternative sign-naming; Advanced exposes
    # all 6 zodiac/label combinations. Default Beginner on fresh + upgraded
    # installs (injected in the factory table so _deep_merge propagates it to
    # existing files).
    Setting("ui.experience_level", str, "beginner", label="Experience level:",
            help="Shows only the 3 main zodiac systems. Switch to Advanced to "
                 "access alternative sign naming.", widget="radio", section=_ZC,
            choices=_LEVELS, live=True, watch="ui.experience_level", rules=APP_AI),
    Setting("ui.hd_experience_level", str, "beginner", persisted=False,
            label="Experience level:",
            help="Human Design charts are built from planetary positions, so the "
                 "zodiac frame you pick changes which gates light up. The bodygraph "
                 "and the Design chart (the chart calculated 88 degrees of the Sun "
                 "before birth) can both be read in the Tropical Classic frame, the "
                 "Aditya Circle frame or the Sidereal frame.", widget="radio", section=_ZC, choices=_LEVELS, live=True,
            watch="ui.hd_experience_level", rules=CALC_AI),
    # Panel default sub-tabs: values and labels from the Chart Display radios. The
    # Aspects radio is one composite row writing (aspects_mode, aspects_tab) pairs
    # (ui.settings_tab.ASPECTS_RADIO).
    Setting("ui.panel.karakas_tab", int, 0, label="Karakas panel:", widget="radio",
            choices=(Choice(0, "Karakas"), Choice(1, "Hora"), Choice(2, "Trimsamsa"),
                     Choice(3, "Houses")), section="chart_display", rules=APP_AI),
    Setting("ui.panel.strength_tab", int, 0, label="Strength panel:", widget="radio",
            choices=(Choice(0, "Strength"), Choice(1, "Elements"), Choice(2, "Modes"),
                     Choice(3, "Varga")), section="chart_display", rules=APP_AI),
    Setting("ui.panel.aspects_mode", str, "vedic", label="Aspects panel:", widget="custom",
            choices=(Choice("vedic"), Choice("tajika")), section="chart_display", rules=APP_AI),
    Setting("ui.panel.aspects_tab", int, 0, widget="custom",
            choices=tuple(Choice(i) for i in range(4)), section="chart_display", rules=APP_AI),
    # SPEC-TAW-001 S12: the birth time popup's own size state and spot (x, y as
    # fractions 0..1 of the free room in the app window; -1 = not placed yet).
    # UI memory only, no Settings row; the popup's Compact scale never writes
    # the font settings.
    Setting("ui.time_adjust.size", str, "full",
            choices=(Choice("full"), Choice("compact"), Choice("mini")), rules=APP_AI),
    Setting("ui.time_adjust.x", float, -1.0, bounds=(-1.0, 1.0), rules=APP_AI),
    Setting("ui.time_adjust.y", float, -1.0, bounds=(-1.0, 1.0), rules=APP_AI),
    Setting("windows.remember_geometry", bool, True, label="Remember window geometry:",
            widget="check", section=_AP, rules=APP_AI),
    Setting("defaults.auto_restore_session", bool, True, label="Auto-restore session:",
            widget="check", section=_AP, rules=APP_AI),
)
