"""Planet and caption layout for one North Indian cell (SPEC-NIC-001).

Measures the F11 captions, asks north_indian_planet_zone for the room; a
crowded cell drops its Cards of Truth plaque, then shrinks its captions.
"""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGraphicsTextItem

from apps.widgets.north_indian_degree_grid import LABEL_WIDTH_PER_PT, NAME_WIDTH_PER_PT
from apps.widgets.north_indian_planet_zone import plan_cell

LABEL_GAP = 4               # px between a planet and its caption
MIN_CAPTION = 8             # smallest caption point size a crowded cell shrinks to
MIN_PLANET_SIZE = 48        # floor, where it fits
HARD_MIN_PLANET_SIZE = 16   # floor of last resort


def measure_captions(texts, font_size, font_weight="normal"):
    """(width, height) of the widest, tallest PlanetDegreeLabel of ``texts``."""
    probe = QGraphicsTextItem()
    font = QFont("Inter", font_size)
    if font_weight == "bold":
        font.setWeight(QFont.Weight.Bold)
    probe.setFont(font)
    w = h = 0.0
    for text in texts:
        probe.setPlainText(text)
        rect = probe.boundingRect()
        w, h = max(w, rect.width()), max(h, rect.height())
    return w, h


def caption_cap(column_w, size, base_size, names):
    """An enlarged caption capped to its column, never below base (§11.9)."""
    if size <= base_size:
        return size
    per_pt = NAME_WIDTH_PER_PT if names else LABEL_WIDTH_PER_PT
    return max(base_size, min(size, int(column_w * 0.9 / per_pt)))


def _better(current, other):
    return other is not None and (current is None or (other["fits"], other["max_fit"])
                                  > (current["fits"], current["max_fit"] * 1.25))


def _yield_plaque(plan, reserved, plaque, font_size):
    """(layout, reserved, dropped): the plaque yields only when it helps."""
    layout = plan(reserved, font_size)
    if plaque is None or (layout is not None and layout["fits"]
                          and layout["max_fit"] >= MIN_PLANET_SIZE):
        return layout, reserved, False
    freed_rects = [r for r in reserved if r is not plaque]
    freed = plan(freed_rects, font_size)
    if _better(layout, freed):
        return freed, freed_rects, True
    return layout, reserved, False


def layout_cell(points, reserved, plaque, wanted, texts, font_size, base_size,
                font_weight, names, margin, offset=(0, 0)):
    """plan_cell's dict plus ``font_size``, ``label_w``, ``label_h`` (captions
    as drawn) and ``drop_plaque`` (remove the cell's plaque). ``reserved``
    holds every drawn rect, ``plaque`` among them or None; ``offset`` is the
    caption Offset X/Y, planned for. None when the cell has no free room."""
    ox, oy = abs(offset[0]), abs(offset[1])

    def plan(avoid, size):
        w, h = measure_captions(texts, size, font_weight)
        return plan_cell(tuple(points), tuple(map(tuple, avoid)), len(texts),
                         round(wanted, 2), round(w + 2 * ox, 2),
                         round(h + LABEL_GAP + oy, 2), margin, HARD_MIN_PLANET_SIZE)

    layout, reserved, drop = _yield_plaque(plan, reserved, plaque, font_size)
    # Captions too big to keep apart fall back to the base size (§11.9), and
    # below it only when the base cannot fit: the largest size that fits.
    if layout is not None and not layout["fits"] and font_size > base_size:
        font_size = base_size
        layout = plan(reserved, font_size)
    while layout is not None and not layout["fits"] and font_size > MIN_CAPTION:
        font_size -= 1
        layout = plan(reserved, font_size)
    if layout is None:
        return None
    font_size = caption_cap(layout["column_w"], font_size, base_size, names)
    label_w, label_h = measure_captions(texts, font_size, font_weight)
    return dict(layout, font_size=font_size, label_w=label_w, label_h=label_h,
                drop_plaque=drop)
