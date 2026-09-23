"""The 36 channel names, and the glyphs the two planet columns print.

Neither is available at runtime from the engine. ``libaditya.hd.constants.channels``
carries each channel's name in a trailing COMMENT, which no import can reach, so the
table is transcribed here and ``test_hd_view.py`` parses those comments and asserts the
two agree. If Josh renames a channel upstream, that test fails rather than the view
quietly printing a stale name.
"""

from __future__ import annotations

#: The 36 channels in ANATOMICAL order, head to root, as ``(upper gate, lower gate,
#: name)``. This is the reading order and the display order: the list beside the graph is
#: an index a reader scans downward, so it follows the body, not the gate numbers. The
#: pair here is written the way the chart says it aloud -- "64-47", upper gate first --
#: which is NOT the geometry pack's lo-first key. Transcribed from the mockup round's
#: ``_shared_data.js``; ``test_hd_view.py`` asserts the set matches the engine's.
CHANNEL_ORDER: tuple[tuple[int, int, str], ...] = (
    (64, 47, "Abstraction"),
    (61, 24, "Awareness"),
    (63, 4, "Logic"),
    (17, 62, "Acceptance"),
    (43, 23, "Structuring"),
    (11, 56, "Curiosity"),
    (31, 7, "The Alpha"),
    (8, 1, "Inspiration"),
    (33, 13, "The Prodigal"),
    (15, 5, "Rhythm"),
    (2, 14, "The Beat"),
    (46, 29, "Discovery"),
    (42, 53, "Maturation"),
    (3, 60, "Mutation"),
    (9, 52, "Concentration"),
    (16, 48, "The Wavelength"),
    (20, 57, "The Brainwave"),
    (35, 36, "Transitoriness"),
    (12, 22, "Openness"),
    (45, 21, "Money"),
    (25, 51, "Initiation"),
    (37, 40, "Community"),
    (44, 26, "Surrender"),
    (59, 6, "Mating"),
    (27, 50, "Preservation"),
    (34, 57, "Power"),
    (34, 10, "Exploration"),
    (34, 20, "Charisma"),
    (57, 10, "Perfected Form"),
    (10, 20, "Awakening"),
    (32, 54, "Transformation"),
    (28, 38, "Struggle"),
    (18, 58, "Judgment"),
    (49, 19, "Synthesis"),
    (55, 39, "Emoting"),
    (30, 41, "Recognition"),
)


#: ``(low gate, high gate) -> name``. Keys are gate-number sorted, matching
#: ``libaditya.hd.constants.channels``, NOT the geometry pack's key order.
CHANNEL_NAMES: dict[tuple[int, int], str] = {
    (1, 8): "Inspiration",
    (2, 14): "The Beat",
    (3, 60): "Mutation",
    (4, 63): "Logic",
    (5, 15): "Rhythm",
    (6, 59): "Mating",
    (7, 31): "The Alpha",
    (9, 52): "Concentration",
    (10, 20): "Awakening",
    (10, 34): "Exploration",
    (10, 57): "Perfected Form",
    (11, 56): "Curiosity",
    (12, 22): "Openness",
    (13, 33): "The Prodigal",
    (16, 48): "The Wavelength",
    (17, 62): "Acceptance",
    (18, 58): "Judgment",
    (19, 49): "Synthesis",
    (20, 34): "Charisma",
    (20, 57): "The Brainwave",
    (21, 45): "Money",
    (23, 43): "Structuring",
    (24, 61): "Awareness",
    (25, 51): "Initiation",
    (26, 44): "Surrender",
    (27, 50): "Preservation",
    (28, 38): "Struggle",
    (29, 46): "Discovery",
    (30, 41): "Recognition",
    (32, 54): "Transformation",
    (34, 57): "Power",
    (35, 36): "Transitoriness",
    (37, 40): "Community",
    (39, 55): "Emoting",
    (42, 53): "Maturation",
    (47, 64): "Abstraction",}


def channel_name(gate_a: int, gate_b: int) -> str:
    """The channel's name, or an empty string if the pair is not a channel."""
    return CHANNEL_NAMES.get((min(gate_a, gate_b), max(gate_a, gate_b)), "")
