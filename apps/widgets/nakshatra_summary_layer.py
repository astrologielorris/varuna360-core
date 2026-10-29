"""Render shared summaries inside the existing dasha-number annulus."""
import math
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsSimpleTextItem
from libaditya.constants import names
from core.nakshatra_property_ring import NakshatraSector, property_bands
from core.nakshatra_properties import PROPERTY_OPTIONS
from apps.widgets.nakshatra_ring_paint import (
    annulus_path, ring_point as _point, wrap_summary, GUNA_COLORS, GUNA_TEXT)
from ui.qt_theme import get_theme_colors, scaled_tier_size

TAG = 'nak_summary'


def draw_summaries(scene, center, inner, outer, rotation, mode):
    sectors = tuple(NakshatraSector(name, i, (rotation+i*360/27)%360, 360/27)
                    for i, name in enumerate(names['eng']['nakshatras']))
    bands = property_bands(sectors, mode)
    colors = get_theme_colors()
    height = (outer-inner)/len(bands)
    font = QFont('Inter')
    # Reserve two readable lines for summaries while keeping the annulus fixed.
    limit = height-8 if mode == 'gunas' else (height-10)/2.5
    font.setPixelSize(min(round(scaled_tier_size(18)), int(limit)))
    metrics = QFontMetricsF(font)
    if mode != 'gunas':
        while metrics.height()*2 > height-10 and font.pixelSize() > 12:
            font.setPixelSize(font.pixelSize()-1)
            metrics = QFontMetricsF(font)
    for level, runs in enumerate(bands):
        lo, hi = inner+level*height, inner+(level+1)*height
        for run in runs:
            guna = mode == 'gunas'
            label = (run.value[:3] if run.value else '—') if guna else run.label or run.value
            width = 2*lo*math.sin(math.radians(run.width)/2)-14
            label, _ = wrap_summary(label, metrics, width, max(1,int((height-10)/metrics.height())))
            wedge = QGraphicsPathItem(annulus_path(center,lo,hi,run.draw_start,run.width))
            wedge.setBrush(QColor(GUNA_COLORS[run.value] if guna else colors['secondary']))
            wedge.setPen(QPen(QColor(colors['secondary_text']), .7))
            text = QGraphicsSimpleTextItem(label)
            text.setFont(font)
            text.setBrush(QColor(GUNA_TEXT[run.value] if guna else colors['secondary_text']))
            rect=text.boundingRect();text.setTransformOriginPoint(rect.center())
            angle=90-run.midpoint
            text.setRotation(angle+180 if angle < -90 else angle)
            x,y=_point(center,(lo+hi)/2,run.midpoint)
            text.setPos(x-rect.width()/2,y-rect.height()/2)
            title=f'Guna {level+1}' if guna else dict(PROPERTY_OPTIONS)[mode]
            for item,z in ((wedge,5.8),(text,6)):
                item.setData(Qt.UserRole,TAG)
                item.setToolTip(f'{title}: {run.value or "unavailable"}\n{", ".join(run.identities)}\nDouble-click for full details.')
                item.setAcceptedMouseButtons(Qt.NoButton)
                item.setZValue(z);scene.addItem(item)
