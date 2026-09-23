# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Scene-anchored wood and carved vector surfaces shared by SI consumers."""
from functools import lru_cache
from math import hypot, sin, pi, ceil
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, QRectF, QPointF, QByteArray
from PySide6.QtGui import (QColor, QImage, QPainterPath, QPen, QBrush,
                          QLinearGradient, QPainter, QPicture)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem
from ui.qt_theme import desat_hex, desat_image, get_ui_saturation
from ui.south_indian_finishes import WOOD, JOSH_FILES

ROOT = Path(__file__).resolve().parents[2]
STAGE = QRectF(-1024, -1024, 4096, 4096)
TAG_TEXTURE = 'si.vector.wood'


def pigment(value, opacity=1.0):
    color = QColor(desat_hex(value))
    color.setAlphaF(opacity)
    return color


@lru_cache(maxsize=2)
def texture(finish, saturation):
    """At most two decoded images; QImage remains valid across Qt apps."""
    path = ROOT / 'img' / 'background' / f'wood-{finish}.webp'
    image = QImage(str(path))
    if image.isNull():
        print(f'[SI WOOD] Missing or unreadable texture: {path}')
        return image
    return desat_image(image, fast=True)


def paint_texture(painter, path, finish):
    painter.save()
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    image = texture(finish, get_ui_saturation())
    if image.isNull():
        painter.fillPath(path, pigment(WOOD[finish]['ink']['plate']))
    else:
        # Fixed source-to-scene transform, independent of visible sceneRect/F5.
        painter.drawImage(STAGE, image)
    painter.restore()


class WoodBoardItem(QGraphicsPathItem):
    def __init__(self, path, finish, parent=None):
        super().__init__(path, parent)
        self.finish = finish
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setData(Qt.ItemDataRole.UserRole, TAG_TEXTURE)
        self.setZValue(-2)

    def paint(self, painter, option, widget=None):
        paint_texture(painter, self.path(), self.finish)


def rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def bevel(rect, finish, kind):
    mat = WOOD[finish]['carve']
    light, dark, strength = mat['lit'], mat['dark'], mat['relief']
    stops = {
        'face': [(0, light, .54), (.34, light, .05), (.66, dark, .05), (1, dark, .36)],
        'glow': [(0, light, .20), (.4, light, .015), (.68, dark, .015), (1, dark, .15)],
        'groove': [(0, dark, .42), (.36, dark, .04), (.68, light, .04), (1, light, .34)],
        'pocket': [(0, dark, .40), (.4, dark, .04), (.68, light, .06), (1, light, .26)],
    }
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    for at, color, opacity in stops[kind]:
        gradient.setColorAt(at, pigment(color, opacity * strength))
    return QBrush(gradient)


@lru_cache(maxsize=512)
def relief_picture(bounds, finish, radius, pocket, scale, saturation):
    """Bounded, shared vector commands for immutable material geometry.

    Saturation is part of the key because pigment reads the live theme. No
    raster is recorded: miniature replay and zoom remain resolution-independent.
    Callers only replay the cached picture and never mutate it.
    """
    rect = QRectF(*bounds)
    picture = QPicture()
    painter = QPainter(picture)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    layers = ((1, 3, 'pocket'),) if pocket else (
        (0, 3.4, 'groove'), (2.6, 3.6, 'face'), (8, 15, 'glow'))
    try:
        for inset, width, kind in layers:
            painter.setPen(QPen(bevel(rect, finish, kind), width * scale))
            painter.drawPath(rounded(
                rect.adjusted(inset * scale, inset * scale,
                              -inset * scale, -inset * scale),
                max(1, radius - inset * scale)))
    finally:
        painter.end()
    return picture


class WoodFaceItem(QGraphicsPathItem):
    """Vector wash + bevels. Never embeds a raster or a graphics effect."""
    def __init__(self, rect, finish, radius=28, fill=None, opacity=0,
                 pocket=False, scale=1, parent=None):
        super().__init__(rounded(rect, radius), parent)
        self.finish, self.rect, self.radius = finish, QRectF(rect), radius
        self.pocket, self.relief_scale = pocket, scale
        self.setBrush(pigment(fill, opacity) if fill else Qt.BrushStyle.NoBrush)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        relief_picture(self.rect.getRect(), self.finish, self.radius,
                       self.pocket, self.relief_scale, get_ui_saturation()).play(painter)
        painter.restore()


class WoodMiniBackground:
    """Paint texture before replaying miniature foreground vector commands."""
    def __init__(self, finish):
        self.finish = finish

    def __call__(self, painter, target):
        painter.save()
        painter.translate(target.topLeft())
        painter.scale(target.width()/2048, target.height()/2048)
        paint_texture(painter, rounded(QRectF(0, 0, 2048, 2048), 28), self.finish)
        painter.restore()


@lru_cache(maxsize=96)
def glyph_svg_passes(finish, index, saturation):
    """Cache SVG source, never raster pixels or device-sized item caches."""
    path = ROOT / 'img' / 'aditya_glyph' / (JOSH_FILES[index] + '.svg')
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f'[SI WOOD] Missing or invalid glyph {path}: {exc}')
        return None
    # Preserve original paths and explicit filled dots, applying saturation once.
    for node in root.iter():
        for attribute in ('fill', 'stroke'):
            value = node.get(attribute)
            if value and QColor(value).isValid():
                node.set(attribute, desat_hex(value))
    passes = []
    for ink, offset, alpha in ((WOOD[finish]['carve']['lit'], 1.0, .52),
                              (WOOD[finish]['carve']['dark'], 0, .88)):
        root.set('stroke', desat_hex(ink))
        root.set('stroke-width', '2.6')
        passes.append((ET.tostring(root), offset, alpha))
    return tuple(passes)


class JoshGlyphItem(QGraphicsItem):
    """Uncached SVG paint at the target transform, including QPicture recording."""
    def __init__(self, passes, size, zodiac_index, current_variation,
                 signal_emitter, parent=None):
        super().__init__(parent)
        self.size = size
        self.zodiac_index = zodiac_index
        self.current_variation = current_variation
        self.signal_emitter = signal_emitter
        self._passes = [(QSvgRenderer(QByteArray(data)), offset, alpha)
                        for data, offset, alpha in passes]
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self):
        return QRectF(0, 0, self.size, self.size)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        opacity = painter.opacity()
        for renderer, offset, alpha in self._passes:
            delta = self.size * offset / 48
            painter.setOpacity(opacity * alpha)
            renderer.render(painter, QRectF(delta, delta*1.2,
                                            self.size-delta, self.size-delta))
        painter.restore()


def outer_wood_palette(finish):
    mat, ink = WOOD[finish], WOOD[finish]['ink']
    return dict(card=ink['plate'], border=mat['carve']['dark'], header=ink['plate'],
                header_border=ink['brass'], text=ink['main'], muted=ink['soft'],
                guide=ink['soft'], asc=ink['asc'], marker=ink['marker'],
                highlight=ink['focus'],
                hora={f'{key.lower()}_{suffix}': record[field]
                      for key, record in mat['hora'].items()
                      for suffix, field in (('bg','c'), ('text','ink'))},
                trim={key:dict(bg=v['c'], text=v['ink']) for key,v in mat['stain'].items()})


def _soft_vine_path(route):
    """Round a routed polyline, then add gentle waves with continuous tangents."""
    points = [QPointF(route.elementAt(i).x, route.elementAt(i).y)
              for i in range(route.elementCount())]
    if len(points) < 2:
        return QPainterPath(route)
    base = QPainterPath(points[0])
    for i in range(1, len(points)-1):
        before, corner, after = points[i-1:i+2]
        incoming, outgoing = corner-before, after-corner
        li, lo = hypot(incoming.x(), incoming.y()), hypot(outgoing.x(), outgoing.y())
        if min(li,lo) < 1:
            base.lineTo(corner)
            continue
        radius = min(100, li*.3, lo*.3)
        base.lineTo(corner-incoming*(radius/li))
        base.quadTo(corner, corner+outgoing*(radius/lo))
    base.lineTo(points[-1])
    length = base.length()
    if length < 1:
        return base
    samples = []
    count = max(4, ceil(length/24))
    for i in range(count+1):
        distance = length*i/count
        t = base.percentAtLength(distance)
        point = base.pointAtPercent(t)
        tangent = base.pointAtPercent(min(1,t+.001))-base.pointAtPercent(max(0,t-.001))
        norm = hypot(tangent.x(),tangent.y()) or 1
        wave = 18*sin(2*pi*distance/190)*sin(pi*i/count)**2
        samples.append(point+QPointF(-tangent.y(),tangent.x())*(wave/norm))
    result = QPainterPath(samples[0])
    for i in range(len(samples)-1):
        p0, p1 = samples[max(0,i-1)], samples[i]
        p2, p3 = samples[i+1], samples[min(len(samples)-1,i+2)]
        result.cubicTo(p1+(p2-p0)/6, p2-(p3-p1)/6, p2)
    return result


class WoodRopeTraceItem(QGraphicsPathItem):
    """Earth-brown serpentine vine, with braid and leaflets following its tangent."""
    def __init__(self, path, finish, parent=None):
        super().__init__(_soft_vine_path(path), parent)
        self.finish = finish
        self.leaflets = QPainterPath()
        self.leaf_veins = QPainterPath()
        self.setPen(QPen(Qt.GlobalColor.transparent, 18))  # Include halo in bounds.
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.braid = QPainterPath()
        curve = self.path()
        length = curve.length()
        def frame(distance):
            t = curve.percentAtLength(distance)
            point = curve.pointAtPercent(t)
            tangent = curve.pointAtPercent(min(1,t+.001))-curve.pointAtPercent(max(0,t-.001))
            norm = hypot(tangent.x(),tangent.y()) or 1
            return point.x(), point.y(), tangent.x()/norm, tangent.y()/norm
        distance = 8
        while distance < length-5:
            x, y, ux, uy = frame(distance)
            self.braid.moveTo(x-ux*3-uy*3, y-uy*3+ux*3)
            self.braid.lineTo(x+ux*3+uy*3, y+uy*3-ux*3)
            distance += 13
        distance, side = 32, 1
        while distance < length-28:
            x, y, ux, uy = frame(distance)
            nx, ny = -uy*side, ux*side
            base = QPointF(x, y)
            tip = QPointF(x+ux*19+nx*20, y+uy*19+ny*20)
            self.leaflets.moveTo(base)
            self.leaflets.cubicTo(QPointF(x+nx*17, y+ny*17),
                QPointF(tip.x()-ux*10+nx*6, tip.y()-uy*10+ny*6), tip)
            self.leaflets.cubicTo(QPointF(tip.x()-nx*12+ux*2, tip.y()-ny*12+uy*2),
                QPointF(x+ux*17, y+uy*17), base)
            self.leaflets.closeSubpath()
            self.leaf_veins.moveTo(base)
            self.leaf_veins.quadTo(QPointF(x+ux*11+nx*8,y+uy*11+ny*8),tip)
            distance += 78
            side *= -1

    def boundingRect(self):
        return super().boundingRect().united(
            self.leaflets.boundingRect().adjusted(-2,-2,2,2))

    def paint(self, painter, option, widget=None):
        mat = WOOD[self.finish]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, opacity, width in ((mat['carve']['lit'], .40, 18),
                                       ('#271B10', 1, 13),
                                       ('#594027', 1, 9),
                                       ('#A18358', .65, 2.3)):
            pen = QPen(pigment(color, opacity), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen); painter.drawPath(self.path())
        pen = QPen(pigment('#271B10', .6), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen); painter.drawPath(self.braid)
        painter.setPen(QPen(pigment('#28351D'), 1.5))
        painter.setBrush(pigment('#50643A'))
        painter.drawPath(self.leaflets)
        painter.setPen(QPen(pigment('#A5AF76', .85), 1.1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.leaf_veins)
        painter.restore()
