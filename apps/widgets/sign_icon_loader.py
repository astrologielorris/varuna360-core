# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Process-wide cache of scaled sign icons (img/sign/*.webp).

The sign art ships at 2048x2048: one decode + smooth downscale costs ~35 ms.
Each chart view used to keep its own cache, so every wheel, South Indian and
North Indian view built at boot decoded the same twelve files again (about
8 s of the 2026-10-23 boot profile). Views still choose the file (variation,
fallbacks); this module only shares the decode. Mirrors planet_icon_loader.
"""
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from ui.qt_theme import desat_image, get_ui_saturation
from apps.widgets.icon_prefetch import scaled_image


def scaled_sign_pixmap(icon_path, size):
    """The icon at ``icon_path`` scaled to ``size`` (aspect kept), desaturated
    for the current UI saturation; None when the file is unreadable.
    QPixmap is implicitly shared, so handing the same one to several views
    is safe on the GUI thread."""
    return _load(str(icon_path), int(size), get_ui_saturation())


@lru_cache(maxsize=256)
def _load(path, size, saturation):
    image = scaled_image(path, size)   # decoded off the GUI thread when prefetched
    if image is None:
        return None
    return QPixmap.fromImage(desat_image(image))
