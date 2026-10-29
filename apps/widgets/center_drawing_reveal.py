# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The finished front of a center drawing's switch-on reveal, painted once (SPEC-VAC-001 W6 S2).

During the switch-on animation every frame repaints the whole drawing item (each
``update`` drops its DeviceCoordinateCache). The layers paint in a fixed order and the
reveal only ever finishes a leading run of them: the frame first, then (after the stud
pop) the Yutis and the casts or thread bundles, weakest first, each final once its fade is
done. ``RevealCache`` paints that finished run ONCE into an image at the painter's device
geometry, copies it into each frame, and the caller's remaining layers follow.

The copy lands on the item's freshly cleared cache pixmap, so the pixels are exactly the
ones a direct paint gives. Separate cached child items for the static layers would not be:
the viewport would composite three pixmaps instead of one, which rounds differently (W6
measured up to 5 % of the pixels changed, by up to 7 / 255). The cache works only while the
reveal runs, on a raster device at device pixel ratio 1; it is dropped when the reveal ends
or the geometry changes.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence, Tuple

from PySide6.QtGui import QImage, QPainter, QPixmap

Layer = Tuple[float, Callable[[QPainter], None]]     # (alpha, paint(painter) at that alpha)


def leading_final(alphas: Iterable[float]) -> int:
    """How many leading ``alphas`` (paint order) have reached their final value 1."""
    count = 0
    for alpha in alphas:
        if alpha < 1.0:
            break
        count += 1
    return count


def paint_layers(painter: QPainter, layers: Sequence[Layer]):
    """Each layer in order; a layer at alpha 0 is not painted."""
    for alpha, paint in layers:
        if alpha > 0.0:
            paint(painter)


class RevealCache:
    """One drawing item's image of the finished layers of its running reveal."""

    def __init__(self):
        self._key: Optional[tuple] = None
        self._image: Optional[QImage] = None
        self._done = 0

    def drop(self):
        self._key = self._image = None
        self._done = 0

    def paint(self, painter: QPainter, layers: Sequence[Layer], revealing: bool):
        """Paint ``layers``; while ``revealing``, the leading run at alpha 1 is copied from
        the image (painted into it once, as it grows)."""
        final = leading_final(alpha for alpha, _paint in layers) if revealing else 0
        key = self._key_of(painter) if final else None
        if key is None:
            self.drop()
            paint_layers(painter, layers)
            return
        if key != self._key:
            self.drop()
            self._key = key
            self._image = QImage(key[0], key[1], QImage.Format.Format_ARGB32_Premultiplied)
            self._image.fill(0)
        if final > self._done:
            out = QPainter(self._image)
            out.setRenderHints(painter.renderHints())
            out.setWorldTransform(painter.worldTransform())
            paint_layers(out, layers[self._done:final])
            out.end()
            self._done = final
        painter.save()
        painter.resetTransform()
        painter.drawImage(0, 0, self._image)
        painter.restore()
        paint_layers(painter, layers[final:])

    @staticmethod
    def _key_of(painter: QPainter) -> Optional[tuple]:
        """The device geometry the image must match; None off a raster device at device
        pixel ratio 1 (the item then paints directly)."""
        device = painter.device()
        if not isinstance(device, (QPixmap, QImage)) or device.devicePixelRatio() != 1.0:
            return None
        t = painter.worldTransform()
        return (device.width(), device.height(), t.m11(), t.m12(), t.m21(), t.m22(), t.dx(),
                t.dy(), painter.renderHints().value)
