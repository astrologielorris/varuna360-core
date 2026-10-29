# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dasha settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["dasha"] and
settings_defaults_ext.EXT_DEFAULTS["dasha"]; values unchanged."""
from dataclasses import replace

from core.settings_registry.rules import CALC, CALC_AI
from core.settings_registry.schema import Choice, ChoicesRef, Setting

_ZC = "zodiac_calculation"
_YEARS = ChoicesRef("core.vimshottari_dasha:YEAR_LENGTH_LABELS")
_AYANAMSAS = ChoicesRef("core.ayanamsa_data:AYANAMSA_OPTIONS")
_MODES = ChoicesRef("managers.dasha.modes:MODES")
_V = "core.settings_registry.validators:"

SETTINGS = (
    Setting("dasha.left.mode", str, "vimshottari", label="Left panel mode:",
            widget="combo", section=_ZC, choices=_MODES,
            live=True, live_reader="dasha_state.left.mode", watch="dasha.", rules=CALC_AI,
            help=("The dasha shown in the left panel: Vimshottari, Planetary Ages, Zodiacal"
                  " Releasing or another available system.")),
    Setting("dasha.left.ayanamsa_id", int, 100, label="Left ayanamsa (Vimshottari):",
            widget="combo", section=_ZC, choices=_AYANAMSAS,
            live=True, live_reader="dasha_state.left.ayanamsa", watch="dasha.", rules=CALC_AI,
            help=("The ayanamsa the left panel's Vimshottari uses to place the Moon in a "
                  "nakshatra. Changes the starting dasha and every date after it.")),
    Setting("dasha.right.mode", str, "nisarga", label="Right panel mode:",
            widget="combo", section=_ZC, choices=_MODES,
            live=True, live_reader="dasha_state.right.mode", watch="dasha.", rules=CALC_AI,
            help="The dasha shown in the right panel. Same choices as the left panel."),
    Setting("dasha.right.ayanamsa_id", int, 98, label="Right ayanamsa (Vimshottari):",
            widget="combo", section=_ZC, choices=_AYANAMSAS,
            live=True, live_reader="dasha_state.right.ayanamsa", watch="dasha.", rules=CALC_AI,
            help=("The ayanamsa the right panel's Vimshottari uses. Same effect as the left"
                  " one.")),
    # SPEC-DSH-003: dasha year length, per family as in Kala's "Dasa Length"
    # (saura | savana | nakshatra | sidereal). `nakshatra` drives Vimshottari on
    # both panels (Zodiacal Releasing keeps its aries-parity arithmetic). Saura is
    # Kala's default and ours.
    Setting("dasha.year_length.nakshatra", str, "saura",
            label="Dasha year (nakshatra dashas):", widget="combo", section=_ZC,
            choices=_YEARS, live=True, live_reader="dasha_state.year_length",
            watch="dasha.", rules=CALC_AI,
            help=("The length of a year for the nakshatra dashas (Vimshottari): Saura "
                  "365.2422 days, Savana 360, Nakshatra 359.0167, Sidereal 365.2564, "
                  "Chandra 364.2888, Lunar 354.367. Longer years push every dasha date "
                  "later.")),
    # Zodiacal Releasing (SPEC-ZR-001 W5b, DESIGN DECISION 6). anchor has no
    # GUI control in v1 (CLI --anchor and settings file only, D-2 open).
    # releaser: spirit | fortune | sign:<0..11> | lot:<name>; the combo's sign
    # labels follow the zodiac display, so the tab builds it (validated, no list).
    Setting("dasha.zr.releaser", str, "spirit", label="Releasing: releaser:",
            widget="combo", section=_ZC, live=True, watch="dasha.",
            rules=replace(CALC_AI, validate=_V + "zr_releaser"),
            help=("The point Zodiacal Releasing starts from: the Lot of Spirit, the Lot of "
                  "Fortune, another lot, or a fixed sign.")),
    Setting("dasha.zr.spirit_shift", bool, True, label="Shift Spirit out of Fortune's sign",
            widget="check", section=_ZC,
            live=True, watch="dasha.", rules=CALC_AI,
            help=("When the Lot of Spirit falls in the same sign as the Lot of Fortune, "
                  "start the releasing from the next sign instead.")),
    Setting("dasha.zr.show_age", bool, False, live=True, watch="dasha.", rules=CALC),
    # No row yet: held in the Zodiac tab's Reset list (D-11 candidate).
    Setting("dasha.zr.anchor", str, "birth", section=_ZC,
            choices=(Choice("birth"), Choice("midnight")), live=True, watch="dasha.", rules=CALC),
)
