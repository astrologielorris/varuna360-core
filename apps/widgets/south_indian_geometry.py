"""Shared South Indian scene geometry and public item tags (SIC002/006)."""
from pathlib import Path
from PySide6.QtCore import QRectF
from apps.widgets.chart_view import SouthIndianView

ZODIAC_POSITIONS = SouthIndianView.ZODIAC_POSITIONS

SCENE_SIZE = 2048

CELL_SIZE = 512

GUTTER = 12

CARD_SIZE = CELL_SIZE - 2 * GUTTER

CARD_RADIUS = 28

CONTENT_PADDING = 24

_SIGN_CELLS = {sign: cell for cell, sign in ZODIAC_POSITIONS.items()}

def cell_rect(sign_index: int) -> QRectF:
    """Return the card rect for a sign (0-11) in scene coordinates.

    The sign's 512px grid cell inset by GUTTER on every side, yielding a
    CARD_SIZE×CARD_SIZE card.

    Raises:
        ValueError: if sign_index is not one of the 12 zodiac indices.
    """
    if sign_index not in _SIGN_CELLS:
        raise ValueError(f"unknown sign_index: {sign_index!r}")
    row, col = _SIGN_CELLS[sign_index]
    return QRectF(
        col * CELL_SIZE + GUTTER,
        row * CELL_SIZE + GUTTER,
        CARD_SIZE,
        CARD_SIZE,
    )

def center_rect() -> QRectF:
    """Return the central 2×2 medallion block, inset by GUTTER like the cards."""
    origin = CELL_SIZE + GUTTER                      # 524
    size = 2 * CELL_SIZE - 2 * GUTTER                # 1000
    return QRectF(origin, origin, size, size)

def house_number_for_sign(sign_index: int, asc_sign_index: int) -> int:
    """Return the Whole Sign house number (1-12) of a sign for an ascendant.

    INV-2: houses rotate against the fixed signs;
    ``house = (sign_index - asc_sign_index) % 12 + 1``.

    Raises:
        ValueError: if either index is not one of the 12 zodiac indices.
    """
    if sign_index not in _SIGN_CELLS:
        raise ValueError(f"unknown sign_index: {sign_index!r}")
    if not 0 <= asc_sign_index <= 11:
        raise ValueError(f"unknown asc_sign_index: {asc_sign_index!r}")
    return (sign_index - asc_sign_index) % 12 + 1

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TAG_FRAME = "si.vector.frame"

TAG_MEDALLION = "si.vector.medallion"

TAG_MEDALLION_RING = "si.vector.medallion.ring"

TAG_CARD = "si.vector.card"

TAG_SIGN_ICON = "si.vector.sign_icon"

TAG_SIGN_NAME = "si.vector.sign_name"

TAG_BADGE_PILL = "si.vector.badge_pill"

TAG_COT_CARD = "si.vector.cot_card"

TAG_HOUSE_NUMBER = "si.vector.house_number"

TAG_CUSP = "si.vector.cusp"

TAG_HOVER = "si.vector.hover"

SIGN_ICON_SIZE = 96

MIN_BADGE_FONT_SIZE = 10

HOUSE_NUMBER_FONT_SIZE = 20

BADGE_PILL_PAD_X = 18

BADGE_PILL_PAD_Y = 10

COT_INDEX_MIN_GAP = 46

TAG_PLANET = "si.vector.planet"

TAG_PLANET_TEXT = "si.vector.planet_text"

TAG_COMPASS_HOUSE = "si.vector.compass_house"

TAG_LAGNA = "si.vector.lagna"

TAG_LAGNA_LABEL = "si.vector.lagna_label"

TAG_TRANSIT = "si.vector.transit"

OUTER_PLANETS = frozenset({"Uranus", "Neptune", "Pluto"})

PLANET_ROW_HEIGHT_FRACTION = 0.60

TRANSIT_MEDALLION_INSET = 24

TRANSIT_MINI_TREATMENT = "none"

def varga_label(varga_code):
    """The name to write in the middle of a center mini, or None.

    Only a divisional chart gets one: transit is always D-1 rashi, so a
    label there would say nothing. With the main chart on D-1 and a second
    chart drawn inside it, this answers the question the feature creates —
    WHICH divisional chart is that?
    """
    if varga_code is None:
        return None
    from core.varga_codes import (
        from_libaditya_varga_code,
        varga_display_label,
    )
    return f"D-{varga_display_label(from_libaditya_varga_code(varga_code))}"

def crowded_planet_size(base_size: int, num_planets: int) -> int:
    """Crowded-sign shrink (INV-6) — behavior matches the frozen classic
    (chart_view.py:2807-2822), 64px floor included: 1-3 planets full size,
    4-5 one tier down (~75%), 6+ forced to 64px."""
    if num_planets <= 3:
        return base_size
    if num_planets <= 5:
        return int(base_size * 0.75)
    return 64

def lone_planet_zone(deg: float) -> int:
    """Degree-zone third (0/1/2) for a lone planet's in-cell degree
    (SPEC-SIC-001, classic chart_view.py:2880): 0-10° left, 10-20° middle,
    20-30° right. The degree is the placement degree (SPEC-SIC-004 INV-6): the
    in-sign degree in the sky frame, the in-band degree in the compass frame."""
    if deg < 10:
        return 0
    if deg < 20:
        return 1
    return 2
