"""Sign artwork seam for the classic South Indian renderer."""

from PySide6.QtCore import Qt

from apps.widgets.aditya_glyph_render import glyph_svg
from apps.widgets.south_indian_material import JoshGlyphItem


CLASSIC_JOSH_TAG = "classic.south.josh_sign"


def add_classic_sign_art(scene, mode, sign_index, variation, signal, x2, y1,
                         offset_x, offset_y, ink, icon_loader, zodiac_item_type,
                         shadow_factory, size=192):
    """Add and return the selected zodiac/Josh art; names mode adds none."""
    if mode == 'names':
        return None
    if mode in ('josh', 'josh_only'):
        data = glyph_svg(sign_index, ink)
        if not data:
            return None
        item = JoshGlyphItem(((data, 0, 1.0),), size, sign_index, variation, signal)
        width = size
        item.setData(Qt.ItemDataRole.UserRole, CLASSIC_JOSH_TAG)
    else:
        pixmap = icon_loader(sign_index, size=size)
        if not pixmap:
            return None
        item = zodiac_item_type(pixmap, sign_index, variation, signal)
        width = pixmap.width()
    item.setPos(x2 - offset_x - width, y1 + offset_y)
    shadow = shadow_factory(sign_index)
    if shadow:
        item.setGraphicsEffect(shadow)
        del shadow
    scene.addItem(item)
    return item
