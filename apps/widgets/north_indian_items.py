#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
North Indian Chart Graphics Items
Custom QGraphicsItem subclasses for the diamond-style North Indian chart.

Contains:
- NorthIndianPlanetClickSignal - Signal emitter for planet clicks
- DiamondCellItem - Diamond/triangle shaped cell for each house
- NorthIndianPlanetItem - Planet icon with click signal
- NorthIndianZodiacItem - Zodiac icon for house display
"""
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsPolygonItem, QGraphicsPixmapItem, QGraphicsTextItem,
    QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsRectItem
)
from PySide6.QtCore import Qt, Signal, QObject, QPointF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QFont, QPixmap, QPolygonF,
    QLinearGradient, QRadialGradient
)

# Project root for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Import theme for consistent colors
from ui.qt_theme import TEXT_PRIMARY, ACCENTS, get_theme_colors, GOLD


class NorthIndianPlanetClickSignal(QObject):
    """Signal emitter for planet click events on the North Indian chart."""
    clicked = Signal(str, dict)  # Emits (planet_name, planet_info)


class NorthIndianSignClickSignal(QObject):
    clicked = Signal(int, int)  # (zodiac_index, current_variation)


class DiamondCellItem(QGraphicsPolygonItem):
    """
    Diamond or triangular cell for a house in the North Indian chart.

    Features:
    - Diamond shape for houses 1,2,4,5,7,8,10,11
    - Triangular shape for corner houses 3,6,9,12
    - Element-based color fill (Fire/Earth/Air/Water)
    - Subtle gradient for 3D effect
    """

    # Element colors (matching wheel_items.py for consistency)
    ELEMENT_COLORS = {
        "Fire": "#E57373",      # Coral red
        "Earth": "#A67C52",     # Brown/tan
        "Air": "#F0C75E",       # Golden yellow
        "Water": "#1E4D8C",     # Deep blue
    }

    ELEMENT_CYCLE = ["Fire", "Earth", "Air", "Water"]

    def __init__(self, house_number: int, polygon: QPolygonF,
                 sign_index: int = 0, parent=None):
        """
        Create a house cell.

        Args:
            house_number: 1-12 (house number)
            polygon: QPolygonF defining the cell shape
            sign_index: 0-11 (zodiac sign index for element coloring)
        """
        super().__init__(polygon, parent)

        self.house_number = house_number
        self.sign_index = sign_index

        # Get element color based on sign
        element = self.ELEMENT_CYCLE[sign_index % 4]
        self.base_color = QColor(self.ELEMENT_COLORS[element])

        # Apply fill with gradient
        self._apply_gradient_fill()

        # Border styling - gold like the South Indian grid
        self.setPen(QPen(QColor(GOLD), 3))

        # Set Z-value (cells are background)
        self.setZValue(1)

        # Store house number for identification
        self.setData(Qt.ItemDataRole.UserRole, f"house_{house_number}")

    def _apply_gradient_fill(self):
        """Apply gradient fill based on element color."""
        # Get bounding rect for gradient calculation
        rect = self.boundingRect()
        center_x = rect.center().x()
        center_y = rect.center().y()
        radius = max(rect.width(), rect.height()) / 2

        # Create radial gradient for 3D effect
        gradient = QRadialGradient(center_x, center_y, radius)
        lighter = self.base_color.lighter(120)
        darker = self.base_color.darker(115)

        gradient.setColorAt(0.0, lighter)
        gradient.setColorAt(0.5, self.base_color)
        gradient.setColorAt(1.0, darker)

        self.setBrush(QBrush(gradient))

    def set_sign_index(self, sign_index: int):
        """Update the sign index and recolor the cell."""
        self.sign_index = sign_index
        element = self.ELEMENT_CYCLE[sign_index % 4]
        self.base_color = QColor(self.ELEMENT_COLORS[element])
        self._apply_gradient_fill()


class NorthIndianZodiacItem(QGraphicsPixmapItem):
    """
    Zodiac sign icon placed in a house cell.

    Accepts a PRE-LOADED pixmap (same pattern as other views).
    """

    def __init__(self, pixmap, x: float, y: float, sign_index: int, parent=None):
        """
        Create a zodiac icon from a pre-loaded pixmap.

        Args:
            pixmap: Pre-loaded QPixmap
            x, y: Center position for the icon
            sign_index: 0-11 (for identification)
        """
        super().__init__(pixmap, parent)

        self.sign_index = sign_index

        # Center on position using pixmap dimensions
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        self.setPos(x, y)

        # Set Z-value (above cells, below planets)
        self.setZValue(4)

        self.setData(Qt.ItemDataRole.UserRole, f"zodiac_{sign_index}")


class NorthIndianPlanetItem(QGraphicsPixmapItem):
    """
    Planet icon with click signal for the North Indian chart.

    Features:
    - Drop shadow effect for 3D look
    - Click to show planet info dialog
    - Hover cursor change
    """

    def __init__(self, pixmap, x: float, y: float, planet_name: str,
                 planet_info: dict, signal_emitter: NorthIndianPlanetClickSignal,
                 parent=None):
        """
        Create a planet icon from a pre-loaded pixmap.

        Args:
            pixmap: Pre-loaded QPixmap
            x, y: Center position for the planet
            planet_name: Name of the planet
            planet_info: Dictionary with planet data
            signal_emitter: Signal emitter for click events
        """
        super().__init__(pixmap, parent)

        self.planet_name = planet_name
        self.planet_info = planet_info
        self.signal_emitter = signal_emitter

        # Center on position using pixmap dimensions
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        self.setPos(x, y)

        # Don't accept mouse buttons - view handles clicks via mouseDoubleClickEvent
        # This prevents items from consuming events before the view can detect double-clicks
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)

        # Add drop shadow from shared settings (Rule #18: del after setGraphicsEffect)
        from apps.widgets.planet_shadow import create_planet_shadow
        shadow = create_planet_shadow(planet_name=planet_name)
        if shadow:
            self.setGraphicsEffect(shadow)
            del shadow  # Release Python reference - Qt owns it now

        # Set Z-value (planets on top)
        self.setZValue(6)

        self.setData(Qt.ItemDataRole.UserRole, f"planet_{planet_name}")


class PlanetDegreeLabel(QGraphicsTextItem):
    """
    Degree label displayed below a planet icon.
    Shows degrees and minutes within the sign.
    """

    def __init__(self, x: float, y: float, deg_in_sign: float,
                 font_size: int = 16, font_color: str = "#CCCCCC",
                 font_weight: str = "normal", label_override: str = "",
                 parent=None):
        """
        Create a degree label.

        Args:
            x, y: Center position
            deg_in_sign: Degrees within sign (0-30)
            font_size: Font size in points
            font_color: Hex color string for font
            font_weight: "normal" or "bold"
        """
        super().__init__(parent)

        if label_override:
            self.setPlainText(label_override)
        else:
            degrees = int(deg_in_sign)
            minutes = int((deg_in_sign - degrees) * 60)
            self.setPlainText(f"{degrees}°{minutes:02d}'")

        # Set font with weight
        font = QFont("Inter", font_size)
        if font_weight == "bold":
            font.setWeight(QFont.Weight.Bold)
        self.setFont(font)

        # Set color from parameter
        self.setDefaultTextColor(QColor(font_color))

        # Center the text on the position
        self.setPos(x - self.boundingRect().width() / 2,
                   y - self.boundingRect().height() / 2)

        # Set Z-value
        self.setZValue(7)

        self.setData(Qt.ItemDataRole.UserRole, "degree_label")
