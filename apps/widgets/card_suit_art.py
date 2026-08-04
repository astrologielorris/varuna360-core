# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Bundled playing-card suit art — SPEC-COT-001 D-3/D-8, one rasteriser.

The suits are DRAWN, never typed. Relying on the system font for
U+2660..U+2666 lets fontconfig decide whether they come out as outline glyphs,
colour emoji or tofu, and that decision differs per machine. The art ships as
four black SVGs in ``img/cards/suits/`` and is recoloured at paint time with a
``SourceIn`` composite over its own alpha, because ``QSvgRenderer`` ignores
``currentColor``.

This module exists because there are now TWO consumers — the Cards of Truth
view (``cards_of_truth_view.py``) and the South Indian vector view's in-sign
card index (``south_indian_vector_view.py``). A second copy of the pipeline
would be a second place for the recolour composite, the DPR key and the cache
bound to drift apart.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SUITS_PATH = Path(__file__).resolve().parent.parent.parent / "img" / "cards" / "suits"

#: Raster-cache bound. The key space is unbounded in practice: the Cards view's
#: zoom produces a continuum of pixel sizes and a trackpad pinch walks through
#: hundreds of them. Python dicts preserve insertion order, so the oldest key is
#: the first one out.
CACHE_MAX = 192

#: The two suit inks, per theme. NOT `#FF0000` / `#000000`: a literal black pip
#: disappears on the dark card table and a literal red vibrates against it.
#: These are the tuned values SPEC-COT-001 §4.6 arrived at, and they live here
#: rather than in either view so the in-sign index and the Cards of Truth view
#: cannot end up with two different reds.
SUIT_INK = {
    "dark": {"red": "#F4746B", "black": "#BECBE2"},
    "light": {"red": "#BE2F2A", "black": "#1B222E"},
}


def suit_ink(is_red, light=None):
    """The ink for a red or black suit in the CURRENT theme, as a hex string.

    ``light`` is resolved live when omitted, so a caller that paints on every
    theme change gets the new ink without holding a palette.
    """
    if light is None:
        from ui.qt_theme import is_light_theme
        light = is_light_theme()
    return SUIT_INK["light" if light else "dark"]["red" if is_red else "black"]


_renderers = {}          # suit_name -> QSvgRenderer
_pixmaps = {}            # (suit_name, px, rgba, dpr) -> QPixmap | None
_app = None              # the QGuiApplication these caches belong to


def _cache_put(cache, key, value, bound=CACHE_MAX):
    cache[key] = value
    while len(cache) > bound:
        cache.pop(next(iter(cache)))
    return value


def _usable_application():
    """True when Qt can make a pixmap, with the caches bound to THIS app.

    Two things a per-widget cache got for free and a module-level one does not:

    * A ``QPixmap`` before a ``QGuiApplication`` exists is not merely useless,
      it is undefined — so this refuses rather than caching a null.
    * Qt GUI objects do not outlive their application. Tests create and destroy
      one repeatedly in a single process, so a pixmap cached under the previous
      application must never be handed to the next. Identity comparison catches
      that; a boolean "have we initialised" flag would not.
    """
    global _app
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        return False
    if _app is not app:
        _renderers.clear()
        _pixmaps.clear()
        _app = app
    return True


def suit_pixmap(suit_name, px, colour, dpr=1.0):
    """A ``suit_name`` pip (``spade``/``heart``/``club``/``diamond``) at ``px``
    logical pixels, tinted to ``colour``.

    ``dpr`` is part of the cache KEY, not merely of the raster: without it,
    dragging a window from a 1x display to a 2x one silently reuses the 1x
    pixmaps and every pip goes soft, with no event to invalidate on. Keying on
    it makes a DPR change an automatic miss.

    Returns ``None`` for an unknown suit, a missing file or a degenerate size —
    callers must treat a missing pip as "draw nothing", never as an error.
    """
    if not suit_name or px < 2 or not _usable_application():
        return None

    from ui.qt_theme import desat_image, sat_key
    key = (suit_name, int(px), colour.rgba(), dpr, sat_key())
    if key in _pixmaps:
        return _pixmaps[key]

    renderer = _renderers.get(suit_name)
    if renderer is None:
        path = SUITS_PATH / f"{suit_name}.svg"
        if not path.exists():
            return _cache_put(_pixmaps, key, None)
        renderer = QSvgRenderer(str(path))
        _renderers[suit_name] = renderer
    if not renderer.isValid():
        return _cache_put(_pixmaps, key, None)

    side = max(2, int(px * dpr))
    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(img.rect(), colour)
    painter.end()

    img = desat_image(img)
    pixmap = QPixmap.fromImage(img)
    pixmap.setDevicePixelRatio(dpr)
    return _cache_put(_pixmaps, key, pixmap)
