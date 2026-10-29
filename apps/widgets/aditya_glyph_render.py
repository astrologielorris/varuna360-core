"""Aditya division ("Josh") glyphs as a view-agnostic sign representation.

WOOD-FREE renderer (wood finishes carve Josh glyphs elsewhere) for every view whose
``display.sign_display`` is a josh mode (flat themable ink) or a vector mode (the simple
symbols of ui.sign_display_modes, own colours), placed like draw_zodiac_icons' pixmaps.

Glyph selection is by DIVISION INDEX 0-11 (Dhata..Parjanya via ``JOSH_FILES``),
system-agnostic per SPEC-ZOD-001 (division #1 = Dhata in every zodiac system).
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from functools import lru_cache

from PySide6.QtCore import Qt, QRectF, QByteArray
from PySide6.QtGui import QColor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsItem

from ui.south_indian_finishes import JOSH_FILES
from ui.sign_glyph_ink import recolor_tree, sign_svg
from apps.widgets.sign_shadow import apply_sign_shadow
from visualizations.wheel_geometry import get_sector_center_angle, polar_to_cartesian
ROOT = Path(__file__).resolve().parents[2]
_GLYPH_DIR = ROOT / 'img' / 'aditya_glyph'


def glyph_svg(index, ink_hex, family='josh'):
    """Sign glyph SVG bytes: a vector symbol (user scheme or ink, read live, so
    never cached here) or the cached flat-ink Josh glyph below."""
    return sign_svg(index, ink_hex) if family == 'vector' else josh_svg(index, ink_hex)


@lru_cache(maxsize=64)
def josh_svg(index, ink_hex):
    """Aditya glyph #index recoloured to a single flat ink, as SVG bytes.

    Cached on (index, ink) — SVG SOURCE only, never a raster/pixmap, so it stays
    sharp at any zoom (same discipline as glyph_svg_passes). Returns None if the
    source glyph is missing/invalid, so callers can fall back silently."""
    if not 0 <= index < len(JOSH_FILES):
        # Out-of-range division index (a later view CP reusing this): return None
        # per the contract rather than let JOSH_FILES[index] raise IndexError.
        print(f'[ADITYA GLYPH] Division index {index} out of range 0..11')
        return None
    ink = QColor(ink_hex)
    if not ink.isValid():
        # No hardcoded theme colour (Rule 20): a bad ink is a caller error, so
        # bail and let the caller fall back rather than invent a shade.
        print(f'[ADITYA GLYPH] Invalid ink {ink_hex!r} for glyph {index}')
        return None
    ink_str = ink.name()
    path = _GLYPH_DIR / (JOSH_FILES[index] + '.svg')
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f'[ADITYA GLYPH] Missing or invalid glyph {path}: {exc}')
        return None
    # Recolour every explicit fill/stroke (and CSS currentColor) to the one ink.
    # Only a real colour stroke suppresses the document-stroke fallback; an
    # unparseable stroke (e.g. url(#grad)) must not suppress it.
    has_explicit_stroke = recolor_tree(root, ink_str)
    # Only supply a document stroke when the glyph declares no stroke of its own,
    # so pure line-art still renders in the ink but a future multi-region glyph's
    # filled shapes are not outlined (finding: root stroke pollutes fills).
    if not has_explicit_stroke:
        root.set('stroke', ink_str)
        root.set('stroke-width', '2.6')
    return ET.tostring(root)


class AdityaGlyphItem(QGraphicsItem):
    """Flat-ink Aditya glyph painted from SVG at paint time (no raster cache).

    View-agnostic: no click signal, no cursor (unlike south_indian_material's
    JoshGlyphItem, which is the wood-cell interactive variant). Bounding box is
    ``size`` square; position it with ``setPos`` to place the top-left corner."""

    def __init__(self, svg_bytes, size, parent=None):
        super().__init__(parent)
        self.size = size
        self._renderer = QSvgRenderer(QByteArray(svg_bytes))
        # Valid XML can still be rejected by Qt's SVG parser -> a blank render.
        # Expose that so drawers skip it instead of placing an invisible item.
        self.valid = self._renderer.isValid()
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return QRectF(0, 0, self.size, self.size)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._renderer.render(painter, QRectF(0, 0, self.size, self.size))
        painter.restore()


def draw_aditya_glyphs(scene, cx, cy, radius, size, rotation_offset, ink_hex,
                       z_base=4, family='josh'):
    """Place 12 Aditya (Josh) glyphs at the sector centres of a chart ring.

    Mirrors ``zodiac_renderer.draw_zodiac_icons`` (same sector geometry and
    z-order) so the ``josh`` sign-display swaps in cleanly where the zodiac
    symbols would sit. Each glyph is CENTRED on its sector centre. Missing
    glyphs are skipped, never drawn as an error placeholder."""
    for i in range(12):
        center_angle = get_sector_center_angle(i, rotation_offset)
        x, y = polar_to_cartesian(cx, cy, radius, center_angle)
        svg_bytes = glyph_svg(i, ink_hex, family)
        if not svg_bytes:
            continue
        item = AdityaGlyphItem(svg_bytes, size)
        if not item.valid:
            # Qt rejected the SVG: skip rather than place an invisible item that
            # would make a blank ring pass an item-count test.
            print(f'[ADITYA GLYPH] Qt could not render glyph {i}; skipped')
            continue
        item.setPos(x - size / 2, y - size / 2)
        item.setZValue(z_base)
        apply_sign_shadow(item, i)
        scene.addItem(item)
