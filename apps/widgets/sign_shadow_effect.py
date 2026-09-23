"""Element shadow whose footprint grows with the "Sign shadow size" setting.

Qt's ``QGraphicsDropShadowEffect`` only blurs: a larger radius spreads the same
ink over a wider area, so on the thin Josh glyph strokes 6 px and 12 px looked
identical on screen (the halo got fainter, not bigger). This effect first grows
the glyph silhouette by a third of the size, then softens that grown shape with
the remaining two thirds, so the size slider visibly widens the shadow.

Kept in its own module because ``sign_shadow.py`` sits on its SI-architecture
line ceiling. The size is stored in ``blurRadius`` so the factory, settings and
tests keep one accessor; size 0 is Qt's crisp offset copy.
"""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsEffect

_FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def _blank(width, height):
    image = QImage(width, height, _FORMAT)
    image.fill(Qt.GlobalColor.transparent)
    return image


def _grow(mask, radius):
    """Union of the silhouette stamped over a disk of ``radius`` pixels."""
    out = _blank(mask.width(), mask.height())
    painter = QPainter(out)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius + radius:
                painter.drawImage(dx, dy, mask)
    painter.end()
    return out


def _box_blur(image, radius, horizontal):
    """One additive box-blur pass along a single axis."""
    out = _blank(image.width(), image.height())
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setOpacity(1.0 / (2 * radius + 1))
    for k in range(-radius, radius + 1):
        painter.drawImage(k if horizontal else 0, 0 if horizontal else k, image)
    painter.end()
    return out


def render_shadow(source, color, size, dpr=1.0):
    """Tinted, grown and softened shadow image of ``source`` (physical px)."""
    mask = _blank(source.width(), source.height())
    painter = QPainter(mask)
    painter.drawImage(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(mask.rect(), QColor(color.red(), color.green(), color.blue()))
    painter.end()
    physical = size * dpr
    grow = int(round(physical / 3.0))
    soft = max(1, int(round((physical - grow) / 2.0)))
    shadow = _grow(mask, grow) if grow else mask
    for _ in range(2):  # two box passes approximate a Gaussian falloff
        shadow = _box_blur(_box_blur(shadow, soft, True), soft, False)
    painter = QPainter(shadow)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.fillRect(shadow.rect(), QColor(0, 0, 0, color.alpha()))
    painter.end()
    return shadow


class SignShadowEffect(QGraphicsDropShadowEffect):
    """Drop shadow whose ``blurRadius`` is a visible footprint size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache_key = None
        self._cache_image = None

    def boundingRectFor(self, rect):
        # Generous pad: device pixels can exceed item units when zoomed in.
        pad = 2.0 * self.blurRadius() + 2.0
        grown = rect.united(rect.translated(self.offset()))
        return grown.adjusted(-pad, -pad, pad, pad)

    def draw(self, painter):
        size = self.blurRadius()
        if size <= 0:
            super().draw(painter)
            return
        offset = QPoint()  # filled in place by PySide6 (C++ out-parameter)
        pixmap = self.sourcePixmap(
            Qt.CoordinateSystem.DeviceCoordinates, offset,
            QGraphicsEffect.PixmapPadMode.PadToEffectiveBoundingRect)
        if pixmap.isNull():
            return
        dpr = pixmap.devicePixelRatio()
        key = (pixmap.cacheKey(), self.color().rgba(), size)
        if key != self._cache_key:
            source = pixmap.toImage().convertToFormat(_FORMAT)
            source.setDevicePixelRatio(1.0)
            image = render_shadow(source, self.color(), size, dpr)
            image.setDevicePixelRatio(dpr)
            self._cache_key, self._cache_image = key, image
        painter.save()
        painter.setWorldTransform(QTransform())
        painter.drawImage(QPointF(offset) + self.offset(), self._cache_image)
        painter.drawPixmap(offset, pixmap)
        painter.restore()
