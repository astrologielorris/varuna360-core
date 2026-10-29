# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_ascendant_guide``: the Ascendant Guide read from several lagnas.

The natal Ascendant first (the South Indian guide's own model,
``core.ascendant_guide.frame_guide``), then, on request, houses counted from
the Sun (Surya Lagna), the Moon (Chandra Lagna) or a Chara karaka (the
Karakas table's ranking, ``karaka_rows``). Each lagna gives its sector and
Aditya, the Aditya teaching, the occupants, the twelve houses with their
Aditya and planets, and Lorris's wording for that lagna. No verdicts: the
model reads the placements.

The guide reads Aditya sectors under the Aditya names, in the Aditya Circle,
Tropical Classic or Sidereal zodiac; with the Western names it refuses
(``not_applicable``). It reads the D1 birth chart whatever the view.
"""
from __future__ import annotations

from core.ascendant_guide_lagnas import LAGNAS

# The tool chooser shows DESCRIPTION to the user (draft wording for Lorris's
# review); GUIDANCE is for the model only.
DESCRIPTION = (
    "The Ascendant Guide by Lorris Turpin, read from the natal Ascendant, Surya "
    "Lagna, Chandra Lagna or a Chara karaka: the Aditya of that sector and its "
    "teaching, the planets in it and the twelve houses counted from it.")

GUIDANCE = (
    "Each lagna also carries Lorris's meaning of it. lagnas picks the viewpoints; "
    "the natal Ascendant always comes first. "
    "How to use it: start simple, with the Ascendant reading only. If the user's "
    "question is vague, give that reading, then ask what they want to know and offer "
    "to read the chart from other viewpoints: Surya Lagna, houses from the Sun "
    "(consistency, career, dharma, reliability as a partner); Chandra Lagna, houses "
    "from the Moon (feelings, self-love, how they feel about their partner); karaka "
    "lagnas (the Atmakaraka, karaka:AK, near the Sun for career and the soul; the "
    "Darakaraka, karaka:DK, for the partner). If the question is already precise, "
    "go straight to the right lagnas without asking: career to sun and karaka:AK; "
    "relationships and feelings to moon and karaka:DK; everything or a first look "
    "to asc. Read the planets and houses yourself, starting from Dhata; the guide "
    "gives the placements and you give the reading. A lagna without a meaning field (the Amatyakaraka, Bhratrukaraka, "
    "Matrukaraka, Pitrukaraka and Gnatikaraka lagnas, karaka:AmK, karaka:BK, "
    "karaka:MK, karaka:PiK, karaka:GK) has no lesson written for it yet: when the "
    "user asks about one, read it from your general knowledge of what that karaka "
    "signifies and say that no specific lesson is written for it yet. Never refuse, "
    "and never present your own words as Lorris's teaching. Applies only to charts "
    "shown with the Aditya names. "
    "Frame: use the zodiac the user names (Aditya Circle, Tropical Classic or "
    "Sidereal); when they name none, the reply's frame is the app's own setting: "
    "say which one it is. If the user names a zodiac other than the reply's, say "
    "so before reading and do not read the other frame's data as theirs. Speak only "
    "the Aditya sector names the reply gives: an Aditya is a sector of this frame, "
    "never a Western sign unless it is asked explicitly, so never write 'Virgo/Tvasta' or give a Western sign's "
    "ruler for a sector. "
    "Lords: every house row gives its lord and where the lord stands (lord_house "
    "from this lagna, lord_aditya); use them, never work out a lord yourself. "
    "Foundation: from every lagna, Dhata is the foundation (the 'foundation' block: "
    "its house, the planets in it, its lord Mars and Mars's house). Always read "
    "both: the planets in Dhata and the lord Mars. When Dhata is empty, Mars "
    "carries the foundation alone; never skip it. "
    "Relationship: Tvasta, always the 7th from Dhata, is the relationship with "
    "the foundation, you and others (the 'relationship' block, lord Venus, read "
    "the same way: its planets and Venus, Venus alone when it is empty). Read it "
    "right after the foundation, first when the question is about relationships, "
    "clients, how the person meets others or value exchanged; otherwise offer it "
    "as the next step. Each block's meaning is Lorris's wording; an example in it "
    "shows how to read. You read as an astrologer: when the chart matches a "
    "meaning, say plainly that it fits and make the prediction; never hedge it "
    "away or refuse to predict.")

OPTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "lagnas": {"type": "array", "items": {"type": "string", "enum": list(LAGNAS)},
                   "default": ["asc"],
                   "description": ("Viewpoints: asc (natal Ascendant, always first), "
                                   "sun (Surya Lagna), moon (Chandra Lagna), "
                                   "karaka:AK ... karaka:DK (Chara karaka lagnas).")},
    },
}

from core.capabilities.setting_args import INPUT  # noqa: E402

SETTING_ARGS = {"get_ascendant_guide": {"lagnas": INPUT}}


def _run(inp, options):
    from core.ascendant_guide_lagnas import GuideNotApplicable, lagna_guides
    from core.capabilities.catalog import OptionError
    try:
        return lagna_guides(inp.build_chart(natal=True), inp.frame.mode,
                            inp.frame.use_western_names, options.get("lagnas") or ["asc"],
                            inp.frame.show_outer_planets)
    except GuideNotApplicable as exc:
        raise OptionError(str(exc), error_type=exc.error_type) from exc


def _register():
    from core.capabilities.catalog import Capability, register
    register(Capability(
        id="get_ascendant_guide", title="Ascendant guide",
        description=DESCRIPTION, guidance=GUIDANCE,
        run=_run, options_schema=OPTIONS_SCHEMA,
        setting_args=SETTING_ARGS["get_ascendant_guide"],
        output_schema={"type": "object",
                       "required": ["applies", "mode", "lagnas", "available_lagnas"]},
        sources=(("core/ascendant_guide.py", "frame_guide"),
                 ("core/ascendant_guide_lagnas.py", "lagna_guides"),
                 ("core/capabilities/karakas_aspects.py", "karaka_rows"),
                 ("core/data/ascendant_guide.json", "lagnas"))))


_register()
