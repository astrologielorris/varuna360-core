"""Shared live-theme treatment for Josh glyphs and the Wheel sign ring."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen, QRadialGradient
from PySide6.QtWidgets import QGraphicsEllipseItem

from ui.qt_theme import get_theme_colors, is_light_theme


def theme_glyph_ink():
    """Return the qt-material on-surface foreground for the active theme."""
    return get_theme_colors()['secondary_text']


def themed_wheel_background(center_x, center_y, radius):
    """Build the Wheel ground: light with dark ink, or dark with light ink."""
    item = QGraphicsEllipseItem(
        center_x - radius, center_y - radius, radius * 2, radius * 2,
    )
    gradient = QRadialGradient(center_x, center_y, radius)
    if is_light_theme():
        theme = get_theme_colors()
        gradient.setColorAt(0, QColor(theme['secondary_light']))
        gradient.setColorAt(0.5, QColor(theme['secondary']))
        gradient.setColorAt(1.0, QColor(theme['secondary_dark']))
        edge = QColor(theme['secondary_text'])
        edge.setAlpha(80)
    else:
        gradient.setColorAt(0, QColor('#3a3a3e'))
        gradient.setColorAt(0.5, QColor('#2a2a2e'))
        gradient.setColorAt(1.0, QColor('#1a1a1e'))
        edge = QColor('#4a4a4e')
    item.setBrush(QBrush(gradient))
    item.setPen(QPen(edge, 4))
    item.setZValue(-10)
    item.setData(Qt.ItemDataRole.UserRole, 'background')
    return item
