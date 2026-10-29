# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Nakshatra compatibility (Kuta) rule options (SPEC-SET-003). Defaults moved from
DEFAULT_SETTINGS["nakshatra_compat"]; values unchanged. The row lives on the
Appearance / General section (OWNED_COMPAT_KEYS) and the Compatibility page.
Pro edition (D-24): only the Pro General section shows the block."""
from core.settings_registry.rules import CALC_AI
from core.settings_registry.schema import Choice, Setting

_AP = "appearance"

SETTINGS = (
    # Nakshatra Compatibility (Kuta) rule toggles. Defaults = Ernst/Kala values
    # (golden-tested). These are GENUINE cross-tradition variants only, each with two
    # documented classical sources — NOT Ernst-vs-Ernst readings.
    # Stree Deergha threshold: "14_9" = Ernst/Kala (man >=14, secondary 9);
    # "9_7" = mainstream South-Indian Porutham (man >=9, secondary 7).
    Setting("nakshatra_compat.stree_deergha_scale", str, "14_9",
            label="Stree Deergha threshold:", widget="combo", section=_AP,
            choices=(Choice("14_9", "14 / 9  (Ernst / Kala)"),
                     Choice("9_7", "9 / 7  (South-Indian Porutham)")), live=True,
            watch="nakshatra_compat.", edition="pro",
            rules=CALC_AI,
            help=("The Stree Deergha rule in Nakshatra Compatibility: the man's nakshatra "
                  "counted from the woman's must reach 14, with 9 as the secondary mark "
                  "(Ernst Wilhelm), or 9 with 7 as the secondary mark (South Indian "
                  "Porutham).")),
    # Mahendra offset set: True = Kala full 3-step series incl. 19th;
    # False = some Tamil sources omit the 19th.
    Setting("nakshatra_compat.mahendra_include_19th", bool, True, label="Mahendra offsets:",
            widget="combo", section=_AP,
            choices=(Choice(True, "Include 19th  (Kala)"),
                     Choice(False, "Omit 19th  (some Tamil sources)")),
            live=True, watch="nakshatra_compat.", edition="pro",
            rules=CALC_AI,
            help=("Whether the 19th nakshatra from the woman's counts as a Mahendra "
                  "position. Included by default; some Tamil sources omit it.")),
    # Total-points thresholds: "17_20" = Ernst/Kala (17 avg / 20 ideal);
    # "18_36" = North-Indian Guna Milan (18/36 minimum).
    Setting("nakshatra_compat.total_threshold", str, "17_20",
            label="Total-points thresholds:", widget="combo", section=_AP,
            choices=(Choice("17_20", "17 avg / 20 ideal  (Ernst / Kala)"),
                     Choice("18_36", "18 / 36 minimum  (North-Indian Guna Milan)")), live=True,
            watch="nakshatra_compat.", edition="pro",
            rules=CALC_AI,
            help=("The marks the total score is judged against: 17 average and 20 ideal "
                  "(Ernst Wilhelm), or the North Indian Guna Milan minimum of 18 out of 36.")),
)
