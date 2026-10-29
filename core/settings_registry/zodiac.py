# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Zodiac frame settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["zodiac"]
and RENDERER_FALLBACKS; values unchanged."""
from dataclasses import replace

from core.settings_registry.rules import CALC, CALC_AI
from core.settings_registry.schema import Choice, ChoicesRef, Setting

_ZC = "zodiac_calculation"

SETTINGS = (
    # One composite row ("Zodiac mode:") writes mode and use_western_names.
    Setting("zodiac.mode", str, "aditya", label="Zodiac mode:", widget="custom", section=_ZC,
            choices=ChoicesRef("core.capabilities.inputs:VALID_MODES"),
            live=True, live_reader="state.aditya_mode", watch="zodiac.", rules=CALC_AI,
            help=("Which zodiac the chart is drawn in: Aditya Circle, Tropical Classic or "
                  "Sidereal. All three put Aries first; they differ only in where the first"
                  " sign starts.")),
    Setting("zodiac.ayanamsa_id", int, 27, label="Ayanamsa:", widget="combo", section=_ZC,
            choices=ChoicesRef("core.ayanamsa_data:AYANAMSA_OPTIONS"),
            live=True, live_reader="chart_sidereal_ayanamsa_id", watch="zodiac.", rules=CALC_AI,
            help=("The ayanamsa used for the Sidereal zodiac and for the sidereal nakshatra"
                  " frame. It does not move the Aditya Circle or Tropical charts.")),
    # The custom ayanamsa (id 255): a value in degrees at a reference year, carried to
    # every other date by Swiss Ephemeris precession (libaditya.custom_ayanamsa).
    Setting("zodiac.custom_ayanamsa_name", str, "Custom", label="Custom ayanamsa name:",
            widget="custom", section=_ZC, live=True, watch="zodiac.",
            rules=replace(CALC_AI, validate="core.settings_registry.validators:free_text"),
            help="The name shown for your custom ayanamsa in every ayanamsa list and title."),
    Setting("zodiac.custom_ayanamsa_value", (int, float), 23.85, bounds=(-360.0, 360.0),
            label="Custom ayanamsa value:", widget="custom", section=_ZC,
            live=True, watch="zodiac.", rules=CALC_AI,
            help=("Your custom ayanamsa in degrees at 1 January of the reference year "
                  "(12:00 UT). Precession moves it from there for every other date.")),
    Setting("zodiac.custom_ayanamsa_year", int, 2000, bounds=(-5000, 5000),
            label="Reference year:", widget="custom", section=_ZC,
            live=True, watch="zodiac.", rules=CALC_AI,
            help="The year at which the custom ayanamsa has exactly the value you entered."),
    Setting("zodiac.house_system", str, "campanus", label="House system:",
            widget="combo", section=_ZC,
            choices=ChoicesRef("core.house_systems:HOUSE_SYSTEM_LABELS"),
            live=True, live_reader="state.house_system", watch="zodiac.", rules=CALC_AI,
            help=("How the twelve houses are cut (Campanus, Whole Sign, Placidus...). "
                  "Applies to every chart view and to the house-based calculations.")),
    Setting("zodiac.use_western_names", bool, False, widget="custom", section=_ZC,
            live=True, live_reader="use_western_names", watch="zodiac.", rules=CALC_AI,
            help=("Show the Western sign names (Aries, Taurus...) instead of the Aditya "
                  "names on the Aditya Circle chart. The positions do not change.")),
    Setting("zodiac.nakshatra_coords", str, "neither", label="Nakshatra coordinates:",
            widget="combo", section=_ZC,
            choices=(Choice("neither", "Neither (ecliptic, default)"),
                     Choice("equatorial", "Equatorial")),
            live=True, live_reader="nakshatra_coords", watch="zodiac.", rules=CALC_AI,
            help=("How nakshatra positions are measured: along the ecliptic (default) or in"
                  " equatorial coordinates.")),
    Setting("zodiac.human_design", bool, False, rules=CALC),
    # SPEC-STR-001 §7.5: how DUC Bala combines Dig, Uccha and Chesta (Strength panel,
    # Avastha Duc view, retinue strength, every CLI and tool). Main and LTS (Lorris 2026-10-22).
    Setting("strength.duc_method", str, "equal", label="DUC Bala method:", widget="combo",
            section=_ZC,
            choices=(Choice("equal", "Equal: Dig, Uccha, Chesta, one third each"),
                     Choice("wilhelm", "Ernst Wilhelm: Ishta and Dig, Dig counts double")),
            live=True, watch="strength.", rules=CALC_AI,
            help=("How DUC Bala is made from the three balas. Equal: the average of Dig, "
                  "Uccha and Chesta. Ernst Wilhelm: first Ishta, the average of Uccha and "
                  "Chesta, then the average of Ishta and Dig, so Dig counts for half.")),
    Setting("zodiac.sign_language", str, "en", label="Language:", widget="combo",
            section="appearance",
            choices=ChoicesRef("core.i18n.languages:LANGUAGE_CHOICES"),
            live=True, live_reader="sign_language", watch="zodiac.", rules=CALC_AI,
            help="The language of the sign and planet names on charts and in panels."),
)
