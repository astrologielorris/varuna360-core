"""Which way planets run inside a South Indian vector card (stateless).

Planets follow the direction the zodiac advances on screen (SPEC-SIC-001 §1).
Top row: left to right. Bottom row (Vivasvan, Tvasta, Vishnu, Amzu): right to
left, so 0° sits on the right and 29° on the left, lone-planet thirds mirrored
too (Lorris, 2026-10-09). Side columns keep left to right."""
from apps.widgets.south_indian_geometry import CONTENT_PADDING, ZODIAC_POSITIONS, lone_planet_zone

_BOTTOM_ROW = frozenset(sign for (row, _col), sign in ZODIAC_POSITIONS.items() if row == 3)


def cell_runs_right_to_left(sign_index):
    """True for the bottom-row cards, where the zodiac advances right to left."""
    return sign_index in _BOTTOM_ROW


def planet_x(rect, sign_index, slot, count, degree):
    """Scene x of the planet at degree-sorted position slot (0 = lowest degree)."""
    width = rect.width() - 2 * CONTENT_PADDING
    if count == 1:
        slot, count = lone_planet_zone(degree), 3
    if cell_runs_right_to_left(sign_index):
        slot = count - 1 - slot
    return rect.left() + CONTENT_PADDING + (slot + 0.5) * width / count
