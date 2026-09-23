"""Resolution-independent optional-body glyphs, including recorded miniatures."""
from functools import lru_cache

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from libaditya.optional_bodies import BODY_BY_NAME
from apps.widgets.planet_icon_style import ICON_NAMES, paint_item, SVGEffects


def _centaur(p, name, line):
    p.addEllipse(QRectF(32, 65, 30, 25))
    line((47, 65), (47, 12))
    if name == 'Chiron':
        line((70, 12), (47, 35), (70, 53))
    elif name == 'Pholus':
        line((47, 12), (72, 12), (72, 38), (47, 38))
    else:
        line((47, 45), (25, 12), (25, 48))
        line((47, 12), (70, 45), (70, 12))


@lru_cache(maxsize=10)
def glyph_path(name):
    p = QPainterPath()

    def line(*points):
        p.moveTo(*points[0])
        for point in points[1:]:
            p.lineTo(*point)

    if name in ('Chiron', 'Pholus', 'Nessus'):
        _centaur(p, name, line)
    elif name == 'Lilith':
        p.moveTo(59, 10)
        p.cubicTo(10, 10, 10, 62, 59, 62)
        p.cubicTo(30, 52, 30, 20, 59, 10)
        line((43, 62), (43, 91))
        line((29, 78), (58, 78))
    elif name == 'Ceres':
        p.moveTo(30, 16)
        p.cubicTo(81, -2, 85, 49, 48, 49)
        line((48, 25), (48, 90))
        line((31, 72), (65, 72))
    elif name == 'Pallas':
        line((50, 8), (72, 33), (50, 58), (28, 33), (50, 8))
        line((50, 58), (50, 92))
        line((33, 76), (67, 76))
    elif name == 'Juno':
        for a, b in (((50, 8), (50, 60)), ((25, 34), (75, 34)),
                     ((32, 16), (68, 52)), ((32, 52), (68, 16))):
            line(a, b)
        line((50, 60), (50, 92))
        line((34, 77), (66, 77))
    elif name == 'Vesta':
        line((20, 52), (32, 80), (68, 80), (80, 52))
        line((25, 91), (75, 91))
        p.moveTo(50, 8)
        p.cubicTo(20, 43, 72, 45, 50, 65)
        p.cubicTo(83, 37, 43, 36, 50, 8)
    else:
        # Eros and Psyche have no universally adopted glyph. Distinct, honest
        # vector monograms avoid inventing an astronomical symbol.
        font = QFont('DejaVu Sans')
        font.setPixelSize(48)
        p.addText(0, 0, font, BODY_BY_NAME[name].abbreviation)
        from PySide6.QtGui import QTransform
        rect = p.boundingRect()
        p = QTransform.fromTranslate(50 - rect.center().x(), 50 - rect.center().y()).map(p)
    return p


def optional_pixmap(name, size):
    """Geometry carrier only; the item paints vector paths, never this raster."""
    if name not in BODY_BY_NAME:
        return None
    pixmap = QPixmap(max(1, int(size)), max(1, int(size)))
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


class _VectorPaint:
    def paint(self, painter, option, widget=None):
        return paint_item(self, painter, option, widget)


@lru_cache(maxsize=None)
def _vector_type(base):
    return type('Additional' + base.__name__, (SVGEffects, _VectorPaint, base), {})


def make_planet_item(base, name, *args, **kwargs):
    """Keep renderer-specific hit testing and click payloads intact."""
    cls = _vector_type(base) if name in ICON_NAMES else base
    item = cls(*args, **kwargs)
    if name in ICON_NAMES:
        item.planet_name = name
        item.setToolTip(BODY_BY_NAME[name].label if name in BODY_BY_NAME else item.toolTip())
        item.setCacheMode(item.CacheMode.NoCache)
        item.setShapeMode(item.ShapeMode.BoundingRectShape)
    return item
