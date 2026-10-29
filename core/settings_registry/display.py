# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Display settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["display"],
settings_defaults_ext and RENDERER_FALLBACKS; values unchanged.
The four typed display sections are declared as section entries (APP_SECTION) naming the
SettingsManager getter that merges and normalises them; their defaults stay with
that getter."""
from dataclasses import replace

from core.settings_registry.rules import APP_AI, APP_SECTION, CALC_AI
from core.settings_registry.schema import Choice, ChoicesRef, Setting

_CD = "chart_display"
_DS = "display_scale"
_FONTS = "fonts"
_V = "core.settings_registry.validators:"
_CAL = (Choice("astronomical", "Astronomy standard (Julian before 1582)"),
        Choice("proleptic_gregorian", "Proleptic Gregorian (Kala)"))
_DATES = (Choice("MM/DD/YYYY", "Month/Day/Year (US)"), Choice("DD/MM/YYYY", "Day/Month/Year"))

from core.settings_registry.font_defaults import FONT_DEFAULTS as _FONT_DEFAULTS, LARGE_FONT_AREAS

SETTINGS = (
    Setting("display.background", str, "stone_06", rules=replace(APP_AI, validate=_V + "free_text")),
    # Bounds: the Display Scale slider's 60-160 % range.
    Setting("display.font_scale", float, 1.0, label="Scale:", bounds=(0.6, 1.6),
            widget="spin", section=_DS,
            live=True, live_reader="qt_theme.get_scale_factor", watch="display.", rules=APP_AI),
    # SPEC-SAT-001: global UI color saturation, 0-100 (100 = full color,
    # a no-op). Desaturates the WHOLE UI live — theme chrome, semantic
    # palettes and planet/sign icon images — for taming oversaturated
    # displays. The boot deep-merge propagates this key to existing
    # settings files. DISPLAY-ONLY: never affects any calculation.
    Setting("display.color_saturation", int, 100, label="Saturation:", widget="spin",
            section=_DS,
            bounds=(0, 100), rules=APP_AI),
    # SPEC-SIC-002: which South Indian implementation renders the SI chart.
    # "vector" (default since the 4.0 macOS test round) = the Conventional
    # clean vector theme; "classic" = the image-backed view. Fresh installs
    # get vector; existing settings files already carry their stored choice
    # and the boot deep-merge never overwrites present keys.
    # SPEC-SIC-002 §4.7: stored values stay "classic"/"vector"; only the labels changed.
    Setting("display.south_indian_style", str, "vector", label="Theme:",
            help="Conventional: the clean vector theme, in the North Indian design "
                 "language. Artistic: the image-backed chart, a bolder and more "
                 "decorative look. Applies to every South Indian view.", widget="combo",
            section=_CD, choices=(Choice("classic", "Artistic (image-backed)"),
                                  Choice("vector", "Conventional (vector)")),
            live=True, watch="display.", rules=APP_AI),
    Setting("display.south_indian_vector_finish", str, "ash", label="Vector finish:",
            help="Material for the South Indian vector chart.", widget="combo", section=_CD,
            choices=(Choice("standard", "Classique"), Choice("santal", "Santal doux"),
                     Choice("ash", "Frêne blanchi")), live=True, watch="display.", rules=APP_AI),
    # td-iaqm.5 (CP5): SI sign display folded into app-wide display.sign_display; retired key never shipped.
    # SPEC-CAL-001: calendar convention for DISPLAYING pre-1582 dates.
    # 'astronomical' = Julian calendar pre-1582 (current behaviour, matches
    # NASA/Swiss Ephemeris). 'proleptic_gregorian' = Gregorian extended
    # backwards (Kala norm). DISPLAY-ONLY: never affects JD/computation.
    Setting("display.calendar_convention", str, "astronomical", label="Historical dates:",
            widget="combo",
            section=_CD, choices=_CAL, live=True, watch="display.", rules=CALC_AI,
            help=("How dates before 15 October 1582 are counted: the astronomical calendar "
                  "(Julian before that date, as historians write them) or the proleptic "
                  "Gregorian calendar extended backwards.")),
    # td-okit c0-2 (decision 7): the numeric date order for the dasha rows
    # (Vedanga/Vimshottari, Planetary Ages, Zodiacal Releasing). US English
    # default "MM/DD/YYYY"; "DD/MM/YYYY" for the rest of the world. DISPLAY-
    # ONLY: the age column and remote ISO derive from the JD, never from this
    # text, so the setting can never change a calculation. Lockable like
    # every display.* key. Follow-up td-fwj1 adopts it on the other surfaces
    # (chart title, overlay, New/Edit form, transit panel).
    Setting("display.date_format", str, "MM/DD/YYYY", label="Date format:",
            widget="combo", section=_CD,
            choices=_DATES, live=True, watch="display.", rules=CALC_AI,
            help=("How dates are written everywhere: month first (MM/DD/YYYY) or day first "
                  "(DD/MM/YYYY).")),
    # Bounds: the Font Sizes spinboxes' range, 7-24 (7-48 for the large chart areas).
    *(Setting(f"display.fonts.{area}", int, size, widget="spin",
              bounds=(7, 48 if area in LARGE_FONT_AREAS else 24),
              section=_FONTS,
              live=True, live_reader="qt_theme.get_area_font_size", watch="display.", rules=APP_AI)
      for area, size in _FONT_DEFAULTS),
    # Fallback-only (absent from DEFAULT_SETTINGS; renderers' own fallback).
    Setting("display.sign_display", str, "zodiac", persisted=False, section=_CD,
            label="Sign display:", widget="combo",
            help="How signs are marked: sign names only, sign names with zodiac icons, "
                 "sign names with Josh's Aditya glyphs, Josh glyph only, sign names with "
                 "simple zodiac symbols, or the simple symbol only. Applies to every "
                 "chart view except Cards of Truth and Human Design.",
            choices=(Choice("names", "Sign names only"),
                     Choice("zodiac", "Sign names + zodiac icons"),
                     Choice("josh", "Sign names + Josh glyphs"),
                     Choice("josh_only", "Josh glyph only"),
                     Choice("vector", "Sign names + simple symbols"),
                     Choice("vector_only", "Simple symbol only")),
            live=True, watch="display.", rules=APP_AI),
    Setting("display.sign_number_views", list, [], persisted=False, section=_CD, label="Signs as numbers:",
            help="Show each sign as its number (1 for Aries/Dhata, 2 for Taurus/Aryama, up to 12) instead of "
                 "its name or symbol, in the views you tick. The other views keep the Sign display above.",
            live=True, watch="display.", rules=replace(APP_AI, validate=_V + "text_list")),
    Setting("display.zodiac_variations", dict, {}, persisted=False, live=True,
            watch="display.", rules=replace(APP_AI, validate=_V + "variation_map")),
    Setting("display.planet_variations", dict, {}, persisted=False, live=True,
            watch="display.", rules=replace(APP_AI, validate=_V + "variation_map")),
    Setting("display.planet_icon_set", str, "artistic", persisted=False, section=_CD,
            label="Planet appearance:", widget="combo",
            choices=(Choice("artistic", "Artistic"), Choice("simple_svg", "Simple SVG")),
            live=True, watch="display.", rules=APP_AI),
    Setting("display.planet_svg_colors", dict, {}, persisted=False, section=_CD,
            live=True, watch="display.", rules=replace(APP_AI, validate=_V + "color_schemes")),
    Setting("display.additional_body_icon_set", str, "current", persisted=False,
            section=_CD, label="Additional-body symbols:", widget="combo",
            choices=(Choice("current", "Current"), Choice("custom_svg", "Custom SVG")), live=True, watch="display.", rules=APP_AI),
    Setting("display.varga_in_center", bool, False, persisted=False, live=True,
            live_reader="varga_in_center", watch="display.", rules=APP_AI),
    # SPEC-NAK-LITE-001: the nakshatra outer ring's property ("none" = dasha numbers).
    Setting("display.nakshatra.property_mode", str, "none", persisted=False, rules=APP_AI,
            choices=ChoicesRef("core.nakshatra_properties:PROPERTY_OPTIONS")),
    # Typed sections (published whole through their getter).
    Setting("chart_display", dict, None, rules=APP_SECTION, persisted=False,
            live=True, live_reader="get_chart_display", watch="chart_display"),
    Setting("south_indian_display", dict, None, rules=APP_SECTION, persisted=False,
            live=True, live_reader="get_south_indian_display",
            watch="south_indian_display"),
    Setting("wheel_display", dict, None, rules=APP_SECTION, persisted=False,
            live=True, live_reader="get_wheel_display", watch="wheel_display"),
    Setting("north_indian_display", dict, None, rules=APP_SECTION, persisted=False,
            live=True, live_reader="get_north_indian_display",
            watch="north_indian_display"),
)
