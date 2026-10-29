"""Where the text under a planet goes in a South Indian vector card (stateless).

Abbreviation + degree under the glyph; house number + cusps at the card's foot.
Planet Degrees >= 1.5x its default drops the abbreviation (the glyph names the
planet); enlarged degrees are capped to the slot and lifted clear of the foot.
At the default area nothing moves (parity), whatever the Display Scale."""
from PySide6.QtGui import QFont, QFontMetricsF
from ui.qt_theme import AREA_DEFAULTS, get_area_font_size
from apps.widgets.chart_area_size import chart_area_size
from apps.widgets.south_indian_geometry import CONTENT_PADDING, HOUSE_NUMBER_FONT_SIZE

BIG_DEGREES_FACTOR = 1.5
_TEXT_MARGIN, _GAP = 4, 2   # QGraphicsTextItem document margin; gap above the foot
WIDEST_DEGREE = "28°58'"   # the widest "dd°mm'" label
WIDEST_NAME = "Mercury"     # the widest English planet name (F11 names mode)
SLOT_FILL = 0.92           # share of a planet's slot a degree label may use


def area_ratio():
    """Planet Degrees / its default (no Display Scale): rules fire only when enlarged."""
    return get_area_font_size('planet_degrees') / AREA_DEFAULTS['planet_degrees']


def footer_top(rect, house_number_font):
    """Scene y where the footer text (house number, cusp degrees) begins."""
    heights = (QFontMetricsF(QFont('Inter', chart_area_size(house_number_font, 'house_numbers'))).height(),
               QFontMetricsF(QFont('Inter', chart_area_size(HOUSE_NUMBER_FONT_SIZE, 'cusp_degrees'))).height())
    return rect.bottom() - CONTENT_PADDING - max(heights) + _TEXT_MARGIN


def degree_font_size(base, slot_width, weight, names=False):
    """Degree label size: ``base`` by Planet Degrees; enlarged, capped to the slot
    (widest degree, or name with ``names``), never below its default-area size."""
    size = chart_area_size(base, 'planet_degrees')
    sample, floor = WIDEST_NAME if names else WIDEST_DEGREE, round(size / area_ratio())
    while size > floor and QFontMetricsF(QFont('Inter', size, weight)).horizontalAdvance(
            sample) > slot_width * SLOT_FILL:
        size -= 1
    return size


def planet_label_rows(abbrev, degrees_text, icon_bottom, line_h, footer_y):
    """[(text, item y)] for the labels under one planet glyph."""
    top = icon_bottom + 4
    factor = area_ratio()
    if factor >= BIG_DEGREES_FACTOR:
        rows = [(degrees_text, top)]
    else:
        rows = [(abbrev, top), (degrees_text, top + line_h + 2)]
    overflow = rows[-1][1] + _TEXT_MARGIN + line_h + _GAP - footer_y
    if factor > 1.0 and overflow > 0:
        rows = [(text, y - overflow) for text, y in rows]
    return rows
