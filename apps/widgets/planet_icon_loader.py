"""Shared variation-aware icon loading; optional bodies paint vector paths."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from ui.qt_theme import desat_image, get_ui_saturation
from apps.widgets.additional_body_glyphs import optional_pixmap

_ROOT = Path(__file__).resolve().parents[2]
_FILES = {'Mars': 'Mars', 'Mercury': 'Mercury', 'Jupiter': 'Jupiter',
          'Venus': 'Venus', 'Saturn': 'Saturn'}


def load_planet_icon(name, size, variation):
    return _load(name, int(size), variation, get_ui_saturation())


@lru_cache(maxsize=256)
def _load(name, size, variation, saturation):
    optional = optional_pixmap(name, size)
    if optional is not None:
        return optional
    filename = _FILES.get(name, name.lower())
    suffix = str(variation) if variation > 1 else ''
    path = _ROOT / 'img' / 'planets' / f'{filename}{suffix}.webp'
    if not path.exists():
        path = _ROOT / 'img' / 'planets' / f'{filename}.webp'
    image = QImage(str(path))
    if image.isNull():
        return None
    image = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(desat_image(image))
