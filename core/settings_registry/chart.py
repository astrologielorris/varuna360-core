# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart view settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["chart"]
and RENDERER_FALLBACKS; values unchanged."""
from dataclasses import replace

from core.settings_registry.center_keys import TAJIKA_CENTER_KEYS, VEDIC_CENTER_KEYS
from core.settings_registry.rules import APP, APP_AI, CALC_AI
from core.settings_registry.schema import Choice, NoneType, Setting

_CD = "chart_display"
_V = "core.settings_registry.validators:"

SETTINGS = (
    # Values and labels moved verbatim from the Chart Display "Chart view" combo;
    # the tab omits human_design when Human Design is hidden (its own rule).
    Setting("chart.view_type", str, "south_indian", label="Chart view:",
            help="The view shown when a chart opens. South Indian (fixed grid), North "
                 "Indian (diamond), Wheel (circular), Body Graph (planets on a body "
                 "silhouette), Nakshatra (the 27-mansion wheel), Cards of Truth "
                 "(the 14-card birth spread), or Human Design (the nine-centre chart). "
                 "F2 cycles the views on the Chart tab and remembers where you stop.",
            choices=(Choice("south_indian", "South Indian"),
                     Choice("north_indian", "North Indian"), Choice("wheel", "Wheel"),
                     Choice("body_graph", "Body Graph"), Choice("nakshatra", "Nakshatra"),
                     Choice("cards_of_truth", "Cards of Truth"),
                     Choice("human_design", "Human Design")),
            widget="combo", section=_CD,
            live=True, live_reader="chart_stack", watch="chart.view_type", rules=APP_AI),
    Setting("chart.show_outer_planets", bool, True, label="Show outer planets:",
            help="Show Uranus, Neptune, and Pluto.", widget="check", section=_CD,
            live=True, live_reader="outer_planets_action",
            watch="chart.show_outer_planets", rules=CALC_AI),
    # SPEC-PLM-001 v2: F11 cycles the four values in this order. The legacy
    # flag below is only read when a file from before them has it on (names).
    Setting("chart.planet_label", str, "degrees", label="Under planets, show:",
            help="What to display under each planet icon on the chart: its degree in "
                 "the sign, its name, its Human Design gate or its nakshatra (the "
                 "nakshatra wheel's three letters). F11 cycles them.",
            choices=(Choice("degrees", "Degrees"), Choice("names", "Planet names"),
                     Choice("gates", "Human Design gates"), Choice("nakshatra", "Nakshatras")),
            widget="radio", section=_CD,
            live=True, live_reader="wheel_view.planet_label",
            watch="chart.planet_label", rules=APP_AI),
    Setting("chart.show_planet_names", bool, False, rules=APP),
    Setting("chart.show_retinue_rings", bool, False, label="Retinue rings:",
            help="Add the Hora and Trimsamsa outer rings. Also applies to the vector "
                 "South Indian chart.", widget="check", section=_CD,
            live=True, live_reader="retinue_rings_action",
            watch="chart.show_retinue_rings", rules=APP_AI),
    Setting("chart.show_trimsamsha_degrees", bool, False, live=True,
            live_reader="trimsamsha_degrees_action",
            watch="chart.show_trimsamsha_degrees", rules=APP_AI),
    # SPEC-RST-001 (td-9x5dr): read by every chart host when it draws; Apply delivers
    # them through the chart display tail. No key is a string prefix of another.
    Setting("chart.retinue_strength_on", bool, False, label="Show lord strength on retinue",
            help="Colour each Hora and Trimsamsa cell by the strength of its lord in the "
                 "chart on screen, with a thin ribbon filled to that strength. Strong "
                 "lords glow, weak lords fade toward the card.",
            widget="check", section=_CD, rules=APP_AI),
    Setting("chart.retinue_strength_source", str, "duc", label="Strength source:",
            help="Which strength sets the colours and ribbons: DUC Bala (the total), or "
                 "one of its parts. F10 or the column titles of the Strength table also "
                 "choose it.",
            choices=(Choice("duc", "DUC Bala"), Choice("digbala", "Digbala"),
                     Choice("uccha", "Uccha"), Choice("chesta", "Chesta")),
            widget="combo", section=_CD, rules=APP_AI),
    Setting("chart.retinue_strength_amount", int, 60, label="Colour strength:",
            help="How strongly the colours follow the strength. 60 suits every look; "
                 "lower is softer, higher is stronger. The ribbon length never changes.",
            bounds=(0, 100), widget="spin", section=_CD, rules=APP_AI),
    # td-9scg9 (SPEC-RST-001 D-32): the V2 star light (the Chesta light channel) only.
    Setting("chart.retinue_strength_light_amount", int, 50, label="Light strength:",
            help="How bright the star light of the V2 look is (the Chesta light). 60 is "
                 "the first V2 look, 0 shows no star. No effect in V1.",
            bounds=(0, 100), widget="spin", section=_CD, rules=APP_AI),
    Setting("chart.retinue_strength_sign_ribbon", bool, True,
            label="Strength ribbon in sign squares",
            help="A ribbon in each sign square of the vector South Indian chart, and in "
                 "each sign of the wheel, shows the strength of the sign's lord.",
            widget="check", section=_CD, rules=APP_AI),
    # td-w6xja: two follow-up keys, same delivery (read when a chart draws, Apply).
    # Lorris, 2026-10-29: on by default, so V1 | V2 visibly colour the sign squares.
    Setting("chart.retinue_strength_sign_colour", bool, True,
            label="Colour the sign squares too",
            help="Also colour the twelve sign squares and the wheel's sign sectors by the "
                 "strength of each sign's lord: strong lords glow, weak lords fade.",
            widget="check", section=_CD, rules=APP_AI),
    Setting("chart.retinue_strength_ribbon_style", str, "fine", label="Sign ribbon style:",
            help="Fine: a thin line. Full: as wide and detailed as the retinue ribbons.",
            choices=(Choice("fine", "Fine"), Choice("full", "Full")),
            widget="combo", section=_CD, rules=APP_AI),
    # td-9scg9 (SPEC-RST-001 D-22): the V1 | V2 switch of the Strength panel header is
    # its control (no Settings page row, so the page's Apply never writes it). Read
    # when a chart draws; CLI renders follow it.
    Setting("chart.retinue_strength_style", str, "v2", label="Strength look:",
            help="V1: Lamplight, the colour follows the lit strength and weak lords "
                 "fade. V2: Jewel Lamp, colour = Uccha, cut = Digbala, light = Chesta. "
                 "Same as the V1 | V2 switch of the Strength table.",
            choices=(Choice("v1", "V1"), Choice("v2", "V2")),
            widget="custom", section=_CD, rules=APP_AI),
    # td-e6jsp (SPEC-RST-001 D-21): the PLANET key of the Strength panel. Strength
    # works only with the strength display on; read when a chart draws.
    Setting("chart.planet_glow_mode", str, "manual", label="Planet glow:",
            help="Manual: each planet keeps its own glow. Strength: planets glow with "
                 "the strength of the lit strength key, bright when strong, faint "
                 "when weak. Same as the PLANET key of the Strength table. Dignity: "
                 "each planet shows its dignity in the varga the chart shows (the "
                 "DIGNITY key of the Varga panel); it switches the strength display off.",
            choices=(Choice("manual", "Manual"), Choice("strength", "Strength"),
                     Choice("dignity", "Dignity")),
            widget="combo", section=_CD, rules=APP_AI),
    # td-m79zy (SPEC-EXCH-002): the THREAD key of the Exchange panel draws every
    # exchange of the chart as a metal chain; read when a chart draws. On by
    # default (td-jr6cd, 4.5: exchanges are easy to miss); a Settings row with its
    # lock, and the THREAD key as the quick toggle.
    Setting("chart.exchange_chain_on", bool, True, label="Exchange chains:",
            help="Draw every exchange of the chart as a metal chain on the South Indian "
                 "chart and the wheel. Same as the THREAD key of the Exchange panel.",
            widget="check", section=_CD, rules=APP_AI),
    # SPEC-TJK-003 §4.5: the Tajika aspects drawn inside the vector South Indian centre.
    # The panel toggle and virupa rail write them; read when a chart draws (D1 only).
    Setting(TAJIKA_CENTER_KEYS[0], bool, False,
            label="Draw Tajika aspects in the South Indian center",
            help="Draw the Tajika aspects inside the center square of the vector South "
                 "Indian chart, each planet at its exact degree. Same as the woven "
                 "square button of the Aspects T panel. Shown on the D1 chart only.",
            widget="check", section=_CD, rules=APP_AI),
    Setting(TAJIKA_CENTER_KEYS[1], int, 0, label="Minimum virupas in the center",
            help="Aspects weaker than this many virupas (0 to 60) are left out of the "
                 "center drawing. The Aspects T table still lists them all. Same as the "
                 "Min. virupas slider under the table.",
            bounds=(0, 60), widget="spin", section=_CD, rules=APP_AI),
    # SPEC-VAC-001 §4.5: the Vedic aspects drawn inside the vector South Indian centre.
    # The Aspects V toggle and virupa rail write them; read when a chart draws (D1 only).
    Setting(VEDIC_CENTER_KEYS[0], bool, False,
            label="Draw Vedic aspects in the South Indian center",
            help="Draw the Vedic aspects inside the center square of the vector South "
                 "Indian chart: each planet casts its own coloured light, a lens near the "
                 "receiver shows the strength. Same as the lens button of the Aspects V "
                 "panel. Shown on the D1 chart only.",
            widget="check", section=_CD, rules=APP_AI),
    Setting(VEDIC_CENTER_KEYS[1], int, 0,
            label="Minimum virupas in the Vedic center",
            help="Casts weaker than this many virupas (0 to 60) are left out of the center "
                 "drawing. The Aspects V table still lists them all. Same as the Min. "
                 "virupas slider under the table.",
            bounds=(0, 60), widget="spin", section=_CD, rules=APP_AI),
    # SPEC-TJK-003 §4.9 D-9: how long the Tour of the center drawing shows each aspect.
    Setting("chart.aspect_tour_seconds", float, 3.0, label="Aspect tour: seconds per aspect",
            help="How long the Tour key under the aspect table shows each aspect of the "
                 "center drawing before the next one (0.5 to 10 seconds).",
            bounds=(0.5, 10.0), widget="spin", section=_CD, rules=APP_AI),
    # SPEC-VAC-001 §4.0: a degree ruler on the track of both center drawings.
    Setting("chart.center_degree_numbers", bool, False,
            label="Degree numbers in the center drawings",
            help="Mark the degrees of each sign on the track of the Tajika and Vedic "
                 "center drawings: a tick at every degree, longer at 5 and 10, and the "
                 "numbers 10 and 20.",
            widget="check", section=_CD, rules=APP_AI),
    Setting("chart.exchange_chain_style", str, "rolo", label="Exchange chain style:",
            help="How the THREAD key of the Exchange panel draws an exchange: Rolo (round "
                 "rings) or Cable (alternating oval and flat links). The metal and the "
                 "marks are the same in both.",
            choices=(Choice("rolo", "Rolo"), Choice("cable", "Cable")),
            widget="combo", section=_CD, rules=APP_AI),
    # td-m6xyo (SPEC-DIG-001 §4.3): the varga style, ONE state for the varga
    # column, the VARGA panel, the chart and render_chart. Its control is the
    # style button of the VARGA panel and, in its All vargas view, its bottom
    # style key (SPEC-DIG-001 D-10). A calculation setting (D-16): it changes the
    # vargas the CLIs compute and print (dignities_in_vargas, render_chart), so
    # a CLI follows it and --set reaches it in advanced mode (D-12/D-13).
    Setting("chart.varga_style", str, "classical", label="Varga style:",
            help="Classical: the Parashara vargas. Parivritti: the cyclic D2, D3 and D4 "
                 "(2p, 3p, 4p). Reversed: the reverse D10 and D24 (10R, 24R).",
            choices=(Choice("classical", "Classical"), Choice("parivritti", "Parivritti"),
                     Choice("reversed", "Reversed")),
            widget="custom", section=_CD, rules=CALC_AI),
    # td-m6xyo (SPEC-DIG-001 D-10): what the VARGA panel shows, kept apart from
    # the style: one varga (the planet rows) or the table of every varga.
    Setting("chart.varga_panel_view", str, "list", label="Varga panel view:",
            help="One varga: the planets of the varga the chart shows. All vargas: the "
                 "dignity table of every varga in the current style.",
            choices=(Choice("list", "One varga"), Choice("table", "All vargas")),
            widget="custom", section=_CD, rules=APP_AI),
    Setting("chart.show_element_pies", bool, False, label="Element pies:",
            help="Show the fire/earth/air/water balance as pie slices. Off by default.",
            widget="check", section=_CD,
            live=True, live_reader="wheel_view.show_element_pies",
            watch="chart.show_element_pies", rules=APP_AI),
    Setting("chart.cusp_glow_mode", int, 2, label="Cusp glow:",
            help="Highlight house cusps. Angles only = 1/4/7/10; All = every cusp (the "
                 "default).", widget="combo", section=_CD,
            choices=(Choice(0, "Off"), Choice(1, "Angles only"), Choice(2, "All")), live=True,
            live_reader="wheel_view.cusp_glow_mode", watch="chart.cusp_glow_mode", rules=APP_AI),
    Setting("chart.wheel_house_display", str, "sign_based", label="House display:",
            widget="combo", section=_CD,
            choices=(Choice("sign_based", "Sign-based (traditional)"),
                     Choice("standard_western", "Standard Western houses")), live=True,
            live_reader="wheel_view._wheel_house_display",
            watch="chart.wheel_house_display", rules=APP_AI),
    # SPEC-BODY-002: Body Graph rashi-aspect dual view.
    # rashi_aspect_system: "quadrant" | "element" | "conventional".
    # show_aspect_panel persists the Shift+F2 toggle.
    Setting("chart.rashi_aspect_system", str, "quadrant", label="Rashi aspects:",
            help="Which rashi aspect set the Body Graph aspect panel draws (Shift+F2): "
                 "Quadrant, Element, or Conventional.", widget="combo", section=_CD,
            choices=(Choice("quadrant", "Quadrant"), Choice("element", "Element"),
                     Choice("conventional", "Conventional")), rules=CALC_AI),
    Setting("chart.show_aspect_panel", bool, False, rules=APP_AI),
    # Fallback-only (absent from DEFAULT_SETTINGS; renderers' own fallback).
    Setting("chart.show_tropical_rim", bool, False, persisted=False, live=True,
            live_reader="wheel_view.show_tropical_rim", watch="chart.show_tropical_rim", rules=APP_AI),
    Setting("chart.additional_bodies", list, [], persisted=False, section=_CD,
            live=True, watch="chart.additional_bodies",
            rules=replace(CALC_AI, validate=_V + "optional_bodies"),
            help=("Extra bodies drawn and listed with the planets (for example Chiron or "
                  "the main asteroids). An empty list shows none.")),
)
