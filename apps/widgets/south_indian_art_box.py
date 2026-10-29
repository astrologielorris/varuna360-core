"""Where a planet icon's drawing really ends inside its square pixmap (stateless).

The default icon boxes differ per planet (Moon 186, Venus 120) while the art drawn in
them is about one size, so text placed under the BOX sat at a different depth for
each planet. Text goes under the last painted row instead."""
from PySide6.QtGui import QRegion

_BOTTOM = {}


def art_bottom(pixmap):
    """Height from the pixmap's top to its last painted row (alpha), cached per pixmap."""
    key = pixmap.cacheKey()
    if key not in _BOTTOM:
        box = QRegion(pixmap.mask()).boundingRect() if pixmap.hasAlphaChannel() else None
        _BOTTOM[key] = box.bottom() + 1 if box and not box.isEmpty() else pixmap.height()
    return _BOTTOM[key]
