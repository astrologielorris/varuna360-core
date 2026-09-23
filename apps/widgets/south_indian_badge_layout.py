"""Dispatch sign badge layout without coupling glyph-only to name geometry."""

from PySide6.QtCore import Qt
from apps.widgets.south_indian_geometry import (
    CONTENT_PADDING, SIGN_ICON_SIZE, TAG_SIGN_NAME, cell_rect)


def draw_sign_badge_layout(scene, snapshot, style, layout, signals, sign_index,
                           icon_draw, text_build, pill_draw):
    rect = cell_rect(sign_index)
    pad = CONTENT_PADDING
    icon_item, icon_w, icon_h, icon_x, icon_y = icon_draw(
        scene, style, signals, sign_index, rect)
    if style.sign_display == 'josh_only':
        layout.badge_band[sign_index] = (
            rect.left() + pad, icon_x - 8, icon_y, icon_h)
        return
    label, lx, ly, pill_rect, fits_beside, emphasise = text_build(
        snapshot, style, sign_index, rect, icon_item, icon_w, icon_h,
        icon_x, icon_y)
    pill_draw(scene, style, sign_index, rect, pill_rect, emphasise)
    layout.pill_bottom[sign_index] = pill_rect.bottom()
    label.setPos(lx, ly)
    label.setZValue(5)
    label.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_NAME)
    label.setData(Qt.ItemDataRole.UserRole + 1, sign_index)
    scene.addItem(label)
    gap_left = pill_rect.right() + 8 if fits_beside else rect.left() + pad
    gap_right = icon_x - 8 if icon_item else rect.right() - pad
    band_top = icon_y if icon_item else rect.top() + pad
    band_h = icon_h if icon_item else SIGN_ICON_SIZE
    layout.badge_band[sign_index] = (gap_left, gap_right, band_top, band_h)
