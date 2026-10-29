# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sign numbers on the Wheel's second-zodiac (tropical) rim, for Settings >
Chart Display > Signs as numbers (ui.sign_numbers, SPEC-NIC-001 §3.7)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGraphicsSimpleTextItem

from ui.qt_theme import get_theme_colors
from ui.sign_numbers import sign_number

TAG_RIM_NUMBER = "wheel.rim_sign_number"


def add_rim_number(scene, sign_index, x, y, icon_size):
    """The number of ``sign_index`` centred on (x, y), sized to the rim icon
    it replaces, in the theme foreground (the rim ground is themed dark/light)."""
    item = QGraphicsSimpleTextItem(sign_number(sign_index))
    font = QFont("Inter", max(8, int(icon_size * 0.32)))
    font.setBold(True)
    item.setFont(font)
    item.setBrush(QColor(get_theme_colors()['primary_text']))
    rect = item.boundingRect()
    item.setPos(x - rect.width() / 2, y - rect.height() / 2)
    item.setZValue(5)
    item.setData(Qt.ItemDataRole.UserRole, TAG_RIM_NUMBER)
    scene.addItem(item)
    return item
