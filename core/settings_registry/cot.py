# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Cards of Truth settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["cot"];
values unchanged."""
from core.settings_registry.rules import APP_AI, CALC_AI
from core.settings_registry.schema import Choice, Setting

_ZC = "zodiac_calculation"

SETTINGS = (
    # SPEC-COT-001: the Cards of Truth position order, shared by the Cards of
    # Truth view, the Planet Placements dialog and the Settings combo. The default is
    # solar_system because that is what Kala uses (D-5, verified) —
    # the LIBRARY default is "vedic" and it relabels three of the seven main
    # cards and moves their occupants. This key had no entry in the factory table at
    # all once, so every reader supplied its own inline fallback and they all said
    # "vedic".
    # The stored "vedic" is libaditya's own key, in every existing app_settings.json;
    # only its label says what the order is. Solar System first: the default.
    Setting("cot.planet_order", str, "solar_system", label="Planet order:",
            widget="combo", section=_ZC,
            choices=(Choice("solar_system",
                            "Solar System (Sun, Moon, Mercury, Venus, Mars...)"),
                     Choice("vedic", "Week Day (Sun, Moon, Mars, Mercury...)")),
            live=True, watch="cot.", rules=CALC_AI,
            help=("The order of the planets in the Cards of Truth layout: solar system "
                  "order or the Vedic weekday order.")),
    # SPEC-COT-001 §4.10: draw each sign's card (by lordship) inside the
    # South Indian vector chart. On by default since 2026-09-24 (Lorris):
    # fresh installs show the plaque in all twelve boxes.
    Setting("cot.show_in_chart", bool, True, label="Cards of Truth inside the chart:",
            help="Show each sign's card (rank and suit) inside the chart. The card "
                 "follows the sign's ruling planet, so Aries shows the Mars card and "
                 "Leo shows the Sun card. Works on the wheel, the North Indian square "
                 "and the South Indian vector theme, each with an Order button in its "
                 "bottom-right corner.", widget="check", section=_ZC,
            live=True, watch="cot.", rules=APP_AI),
)
