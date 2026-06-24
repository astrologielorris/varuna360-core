#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Wheel Chart Graphics Items
Custom QGraphicsItem subclasses for the circular zodiac wheel.

Contains:
- ZodiacSectorItem - Colored pie slice for each zodiac sign
- ZodiacSymbolItem - Unicode zodiac symbol on outer ring
- SignNameItem - Aditya/Western sign name in middle ring
- DegreeRulerItem - Tick marks around outer edge
- PlanetItem - Planet icon with click signal
- PlanetIndicatorLine - Line from planet to degree ruler
- HouseCuspMarker - Triangle markers for house cusps
- HouseNumberItem - House numbers in center circle
- StelliumBadge - Badge for 8+ planets in same sign
"""
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsPolygonItem,
    QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsSimpleTextItem
)
from PySide6.QtCore import Qt, Signal, QObject, QPointF, QRectF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPixmap, QImage,
    QPolygonF, QLinearGradient, QConicalGradient, QRadialGradient, QPainter
)

# Project root for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Import theme for consistent colors
from ui.qt_theme import TEXT_PRIMARY, ACCENTS, get_theme_colors
from core.aditya_mode import displayed_sign_name


class WheelPlanetClickSignal(QObject):
    """Signal emitter for planet click events on the wheel."""
    clicked = Signal(str, dict)  # Emits (planet_name, planet_info)


class ZodiacSectorItem(QGraphicsPathItem):
    """
    Colored pie slice for a zodiac sign.

    Features:
    - Element-based color (Fire=red, Earth=brown, Air=yellow, Water=blue)
    - Subtle gradient for 3D effect
    - Rotation based on Ascendant position
    """

    # Element colors (Fire-Earth-Air-Water cycle)
    ELEMENT_COLORS = {
        "Fire": "#E57373",      # Coral red
        "Earth": "#A67C52",     # Brown/tan
        "Air": "#F0C75E",       # Golden yellow
        "Water": "#1E4D8C",     # Deep blue
    }

    ELEMENT_CYCLE = ["Fire", "Earth", "Air", "Water"]

    def __init__(self, center_x: float, center_y: float, inner_radius: float,
                 outer_radius: float, start_angle: float, sign_index: int, parent=None):
        """
        Create a zodiac sector.

        Args:
            center_x, center_y: Center of the wheel
            inner_radius: Inner edge of the sector
            outer_radius: Outer edge of the sector
            start_angle: Starting angle in degrees (0° = 3 o'clock)
            sign_index: 0-11 (for element color determination)
        """
        super().__init__(parent)

        self.sign_index = sign_index
        element = self.ELEMENT_CYCLE[sign_index % 4]
        base_color = QColor(self.ELEMENT_COLORS[element])

        # Create pie slice path
        path = QPainterPath()

        # Convert angles to radians (Qt uses counter-clockwise from 3 o'clock)
        start_rad = math.radians(start_angle)
        end_rad = math.radians(start_angle + 30)

        # Calculate arc points
        # Outer arc start point
        outer_start_x = center_x + outer_radius * math.cos(start_rad)
        outer_start_y = center_y - outer_radius * math.sin(start_rad)

        # Inner arc start point
        inner_start_x = center_x + inner_radius * math.cos(start_rad)
        inner_start_y = center_y - inner_radius * math.sin(start_rad)

        # Inner arc end point
        inner_end_x = center_x + inner_radius * math.cos(end_rad)
        inner_end_y = center_y - inner_radius * math.sin(end_rad)

        # Build path: start at outer arc start, arc to end, line to inner, arc back, close
        path.moveTo(outer_start_x, outer_start_y)

        # Outer arc (counter-clockwise in Qt coordinate system)
        outer_rect = QPointF(center_x - outer_radius, center_y - outer_radius)
        path.arcTo(
            center_x - outer_radius, center_y - outer_radius,
            outer_radius * 2, outer_radius * 2,
            start_angle, 30  # span angle is always positive for CCW
        )

        # Line to inner arc
        path.lineTo(inner_end_x, inner_end_y)

        # Inner arc (clockwise = negative span)
        path.arcTo(
            center_x - inner_radius, center_y - inner_radius,
            inner_radius * 2, inner_radius * 2,
            start_angle + 30, -30  # negative span for clockwise
        )

        path.closeSubpath()
        self.setPath(path)

        # Create subtle gradient for 3D effect
        gradient = QRadialGradient(center_x, center_y, outer_radius)
        lighter = base_color.lighter(115)
        darker = base_color.darker(110)
        gradient.setColorAt(0.3, lighter)
        gradient.setColorAt(0.7, base_color)
        gradient.setColorAt(1.0, darker)

        self.setBrush(QBrush(gradient))
        # Pen width scaled for 2048px coordinate system
        self.setPen(QPen(QColor("#333333"), 2))  # was 1
        self._original_pen = self.pen()

        # Set Z-value (sectors are at the back)
        self.setZValue(0)

        # Store sign index for identification
        self.setData(Qt.ItemDataRole.UserRole, f"sector_{sign_index}")

    def set_highlighted(self, highlighted: bool):
        if highlighted:
            self.setPen(QPen(QColor("#FFFFFF"), 3))
            self.setZValue(2.5)
        else:
            self.setPen(self._original_pen)
            self.setZValue(0)


class ZodiacSymbolItem(QGraphicsPixmapItem):
    """
    Zodiac sign icon on the outer ring.

    Accepts a PRE-LOADED pixmap (same pattern as SouthIndianView's ClickableZodiacItem).
    The pixmap is loaded by WheelView.load_zodiac_icon() before creating this item.
    """

    def __init__(self, pixmap, x: float, y: float, sign_index: int, parent=None):
        """
        Create a zodiac icon from a pre-loaded pixmap.

        Args:
            pixmap: Pre-loaded QPixmap from WheelView.load_zodiac_icon()
            x, y: Center position for the icon
            sign_index: 0-11 (for identification)
        """
        super().__init__(pixmap, parent)

        # Center on position using pixmap dimensions
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        self.setPos(x, y)

        # Set Z-value
        self.setZValue(4)

        self.setData(Qt.ItemDataRole.UserRole, f"zodiac_symbol_{sign_index}")


class SignNameItem(QGraphicsTextItem):
    """
    Aditya or Western sign name in the middle ring.
    """

    ADITYA_NAMES = [
        "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
        "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
    ]

    WESTERN_NAMES = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]


    def __init__(self, x: float, y: float, sign_index: int,
                 aditya_mode: str = "aditya", font_size: int = 11,
                 use_western_names: bool = False, font_color: str = None,
                 font_weight: str = "bold", offset_x: int = 0, offset_y: int = 0,
                 sign_language: str = "en", parent=None):
        """
        Create a sign name label.

        Args:
            x, y: Center position
            sign_index: 0-11
            aditya_mode: "aditya" for Aditya names, "tropical_classic" for Western
            font_size: Font size in points
            use_western_names: If True, display Western names even in zodiac mode
            font_color: Custom font color (hex). If None, uses element-based color.
            font_weight: "normal" or "bold"
            offset_x, offset_y: Additional position offset in pixels
            sign_language: ISO 639-1 code for Western sign name localization
        """
        super().__init__(parent)

        # Determine which name to display
        name = displayed_sign_name(sign_index, aditya_mode,
                                   use_western_names, sign_language)

        self.setPlainText(name)

        # Set font (CJK characters use lighter weight for readability)
        font = QFont("Inter", font_size)
        has_cjk = any('一' <= ch <= '鿿' for ch in name)
        if has_cjk:
            font.setWeight(QFont.Weight.Light)
        elif font_weight == "bold":
            font.setBold(True)
        self.setFont(font)

        # Set text color
        if font_color:
            self.setDefaultTextColor(QColor(font_color))
        else:
            # Water signs have dark blue background - need white text
            # Others need dark text for visibility on light backgrounds
            element_index = sign_index % 4
            if element_index == 3:  # Water
                self.setDefaultTextColor(QColor("#FFFFFF"))
            else:
                self.setDefaultTextColor(QColor("#1a1a1a"))

        # Center the text on the position with offset
        self.setPos(x - self.boundingRect().width() / 2 + offset_x,
                   y - self.boundingRect().height() / 2 + offset_y)

        # Set Z-value
        self.setZValue(5)

        self.setData(Qt.ItemDataRole.UserRole, f"sign_name_{sign_index}")


class DegreeTickItem(QGraphicsLineItem):
    """
    Single degree tick mark on the ruler.
    """

    def __init__(self, x1: float, y1: float, x2: float, y2: float,
                 tick_type: str = "minor", parent=None):
        """
        Create a degree tick.

        Args:
            x1, y1: Start point (inner)
            x2, y2: End point (outer)
            tick_type: "major" (10°), "minor" (5°), or "micro" (1°)
        """
        super().__init__(x1, y1, x2, y2, parent)

        # Pen widths scaled for 2048px coordinate system
        if tick_type == "major":
            self.setPen(QPen(QColor("#AAAAAA"), 4))  # was 2
        elif tick_type == "minor":
            self.setPen(QPen(QColor("#777777"), 2))  # was 1
        else:  # micro
            self.setPen(QPen(QColor("#555555"), 2))  # was 1

        self.setZValue(3)
        self.setData(Qt.ItemDataRole.UserRole, "ruler_tick")


class TrimsamshaDegreeTick(QGraphicsLineItem):
    """Tick mark + label for Trimsamsha sector boundary degrees on the outer edge."""

    def __init__(self, x1, y1, x2, y2, degree_text="",
                 label_x=0, label_y=0, rotation=0, parent=None):
        super().__init__(x1, y1, x2, y2, parent)
        self.setPen(QPen(QColor("#AAAAAA"), 2))
        self.setZValue(3.9)
        if degree_text:
            self._label = QGraphicsSimpleTextItem(degree_text, self)
            self._label.setFont(QFont("Inter", 11))
            self._label.setBrush(QBrush(QColor("#AAAAAA")))
            br = self._label.boundingRect()
            self._label.setPos(
                label_x - br.width() / 2,
                label_y - br.height() / 2,
            )
            self._label.setTransformOriginPoint(br.center())
            self._label.setRotation(rotation)


class PlanetItem(QGraphicsPixmapItem):
    """
    Planet icon with click signal.

    Accepts a PRE-LOADED pixmap (same pattern as SouthIndianView's ClickablePlanetItem).
    The pixmap is loaded by WheelView.load_planet_image() before creating this item.

    Features:
    - Drop shadow effect for 3D look
    - Click to show planet info dialog
    - Hover cursor change
    """

    def __init__(self, pixmap, x: float, y: float, planet_name: str, planet_info: dict,
                 signal_emitter: WheelPlanetClickSignal, parent=None):
        """
        Create a planet icon from a pre-loaded pixmap.

        Args:
            pixmap: Pre-loaded QPixmap from WheelView.load_planet_image()
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
        self.setZValue(9)

        self.setData(Qt.ItemDataRole.UserRole, f"planet_{planet_name}")


class PlanetIndicatorLineGroup(QGraphicsItem):
    """
    Glowing line from planet to its exact degree position on the ruler.

    Uses layered lines technique for a visible neon-like glow effect:
    - Multiple semi-transparent lines of decreasing width
    - Creates a soft glow around the main line
    - Much more visible than QGraphicsDropShadowEffect
    """

    # Element colors matching the zodiac sectors
    ELEMENT_COLORS = {
        'Fire': '#E57373',    # Coral red - signs 0, 4, 8 (Dhata, Indra, Amzu)
        'Earth': '#A67C52',   # Brown/tan - signs 1, 5, 9 (Aryama, Vivasvan, Bhaga)
        'Air': '#F0C75E',     # Golden yellow - signs 2, 6, 10 (Mitra, Tvasta, Pusha)
        'Water': '#1E4D8C',   # Deep blue - signs 3, 7, 11 (Varuna, Vishnu, Parjanya)
    }

    # Element by sign index (0-11)
    SIGN_ELEMENTS = ['Fire', 'Earth', 'Air', 'Water'] * 3

    def __init__(self, planet_x: float, planet_y: float,
                 ruler_x: float, ruler_y: float,
                 sign_index: int = None, color: str = None,
                 glow_intensity: int = 50, line_width: int = 3, parent=None):
        """
        Create an indicator line with layered glow effect.

        Args:
            planet_x, planet_y: Planet center position
            ruler_x, ruler_y: Exact degree position on ruler
            sign_index: 0-11 zodiac sign index for element color (preferred)
            color: Override color (if sign_index not provided)
            glow_intensity: 0-100, controls glow visibility (0=none, 100=max)
            line_width: Core line thickness in pixels
        """
        super().__init__(parent)

        self.planet_x = planet_x
        self.planet_y = planet_y
        self.ruler_x = ruler_x
        self.ruler_y = ruler_y
        self.glow_intensity = glow_intensity
        self.line_width = line_width

        # Determine color from sign index or fallback
        if sign_index is not None:
            element = self.SIGN_ELEMENTS[sign_index % 12]
            self.line_color = QColor(self.ELEMENT_COLORS[element])
        elif color:
            self.line_color = QColor(color)
        else:
            self.line_color = QColor("#666666")

        # Calculate bounding rect with glow margin
        self._update_bounding_rect()

        # Behind zodiac symbols (Z=4) but above sectors (Z=0)
        self.setZValue(3)
        self.setData(Qt.ItemDataRole.UserRole, "planet_indicator")

    def _update_bounding_rect(self):
        """Calculate bounding rect including glow."""
        # Max glow width
        max_glow_width = (self.glow_intensity / 100.0) * 30 + self.line_width
        margin = max_glow_width / 2 + 5

        x1, y1 = self.planet_x, self.planet_y
        x2, y2 = self.ruler_x, self.ruler_y

        self._bounding_rect = QRectF(
            min(x1, x2) - margin,
            min(y1, y2) - margin,
            abs(x2 - x1) + margin * 2,
            abs(y2 - y1) + margin * 2
        )

    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter, option, widget):
        """Paint the line with dramatic neon glow effect."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        x1, y1 = self.planet_x, self.planet_y
        x2, y2 = self.ruler_x, self.ruler_y

        # Draw glow layers (outer to inner)
        if self.glow_intensity > 0:
            # More layers = smoother glow, scale with intensity
            num_layers = max(5, int(self.glow_intensity / 8))
            # Max 80px glow spread at full intensity (visible in 2048px coords)
            max_glow_width = (self.glow_intensity / 100.0) * 80

            # Create a lighter/brighter version of the color for glow
            glow_base = QColor(self.line_color).lighter(150)

            for i in range(num_layers, 0, -1):
                ratio = i / num_layers  # 1.0 (outer) to ~0.1 (inner)
                layer_width = self.line_width + (max_glow_width * ratio)

                # HIGH alpha values: outer=100, inner=200 (visible!)
                alpha = int(100 + 100 * (1 - ratio))

                glow_color = QColor(glow_base)
                glow_color.setAlpha(alpha)

                pen = QPen(glow_color, layer_width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Draw the bright core line on top
        core_color = QColor(self.line_color).lighter(120)
        pen = QPen(core_color, self.line_width + 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Draw white highlight center for extra pop
        white_pen = QPen(QColor(255, 255, 255, 200), max(1, self.line_width - 1))
        white_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(white_pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


# Backwards compatibility alias
PlanetIndicatorLine = PlanetIndicatorLineGroup


class HouseCuspMarker(QGraphicsPolygonItem):
    """
    Triangle marker for house cusps on the outer ring.

    - Gold triangles for angular houses (ASC/1, IC/4, DSC/7, MC/10)
    - Silver triangles for other houses
    """

    def __init__(self, center_x: float, center_y: float, radius: float,
                 angle: float, house_number: int, marker_size: int = 12, parent=None):
        """
        Create a house cusp marker.

        Args:
            center_x, center_y: Center of the wheel
            radius: Radius where marker is placed
            angle: Visual angle of the cusp
            house_number: 1-12 (1=ASC, 4=IC, 7=DSC, 10=MC are angular)
            marker_size: Size of the triangle
        """
        super().__init__(parent)

        # Calculate marker position
        angle_rad = math.radians(angle)
        tip_x = center_x + radius * math.cos(angle_rad)
        tip_y = center_y - radius * math.sin(angle_rad)

        # Create triangle pointing inward
        # Calculate perpendicular direction for base
        perp_angle = angle + 90
        perp_rad = math.radians(perp_angle)

        half_base = marker_size / 2
        base_offset = marker_size * 0.8

        # Base points (outside the tip)
        base1_x = tip_x + base_offset * math.cos(angle_rad) + half_base * math.cos(perp_rad)
        base1_y = tip_y - base_offset * math.sin(angle_rad) - half_base * math.sin(perp_rad)
        base2_x = tip_x + base_offset * math.cos(angle_rad) - half_base * math.cos(perp_rad)
        base2_y = tip_y - base_offset * math.sin(angle_rad) + half_base * math.sin(perp_rad)

        # Create polygon
        triangle = QPolygonF([
            QPointF(tip_x, tip_y),
            QPointF(base1_x, base1_y),
            QPointF(base2_x, base2_y),
        ])
        self.setPolygon(triangle)

        # Color based on house type
        is_angular = house_number in [1, 4, 7, 10]
        if is_angular:
            self.setBrush(QBrush(QColor("#FFD700")))  # Gold
            self.setPen(QPen(QColor("#B8860B"), 1))   # Dark gold outline
        else:
            self.setBrush(QBrush(QColor("#C0C0C0")))  # Silver
            self.setPen(QPen(QColor("#808080"), 1))   # Gray outline

        self.setZValue(7)
        self.setData(Qt.ItemDataRole.UserRole, f"house_cusp_{house_number}")


class HouseHoverSignal(QObject):
    hover_enter = Signal(int)
    hover_leave = Signal()


class RetinueHoverSignal(QObject):
    hover_enter = Signal(object)
    hover_leave = Signal()


class RetinueClickSignal(QObject):
    clicked = Signal(str, str, str)


class WheelSignClickSignal(QObject):
    clicked = Signal(int, int)  # (zodiac_index, current_variation)


class HouseNumberItem(QGraphicsTextItem):
    """
    House number (1-12) displayed in the center circle.
    """

    def __init__(self, x: float, y: float, house_number: int,
                 font_size: int = 10, hover_signal=None, parent=None):
        super().__init__(parent)

        self._house_number = house_number
        self._hover_signal = hover_signal

        self.setPlainText(str(house_number))

        font = QFont("Inter", font_size)
        font.setBold(True)
        self.setFont(font)

        self.setDefaultTextColor(QColor("#888888"))
        self._original_color = self.defaultTextColor()

        self.setPos(x - self.boundingRect().width() / 2,
                   y - self.boundingRect().height() / 2)

        self.setZValue(6)
        self.setData(Qt.ItemDataRole.UserRole, f"house_number_{house_number}")

        if hover_signal is not None:
            self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        if self._hover_signal:
            self.setDefaultTextColor(QColor("#FF4444"))
            self._hover_signal.hover_enter.emit(self._house_number)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self._hover_signal:
            self.setDefaultTextColor(self._original_color)
            self._hover_signal.hover_leave.emit()
        super().hoverLeaveEvent(event)

    def set_highlighted(self, highlighted: bool):
        if highlighted:
            self.setDefaultTextColor(QColor("#FF4444"))
        else:
            self.setDefaultTextColor(self._original_color)


class CenterCircleItem(QGraphicsEllipseItem):
    """
    Center circle of the wheel with dark gradient.
    """

    def __init__(self, center_x: float, center_y: float, radius: float, parent=None):
        """
        Create the center circle.

        Args:
            center_x, center_y: Center position
            radius: Circle radius
        """
        super().__init__(center_x - radius, center_y - radius,
                        radius * 2, radius * 2, parent)

        # Dark gradient for depth (neutral dark gray)
        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, QColor("#2a2a2e"))
        gradient.setColorAt(0.7, QColor("#1a1a1e"))
        gradient.setColorAt(1.0, QColor("#151518"))

        self.setBrush(QBrush(gradient))
        # Pen width scaled for 2048px coordinate system
        self.setPen(QPen(QColor("#4a4a4e"), 4))  # was 2

        self.setZValue(2)
        self.setData(Qt.ItemDataRole.UserRole, "center_circle")


class BackgroundCircleItem(QGraphicsEllipseItem):
    """
    Outer background circle of the wheel.
    """

    def __init__(self, center_x: float, center_y: float, radius: float, parent=None):
        """
        Create the background circle.

        Args:
            center_x, center_y: Center position
            radius: Circle radius (slightly larger than outer ring)
        """
        super().__init__(center_x - radius, center_y - radius,
                        radius * 2, radius * 2, parent)

        # Dark background with subtle gradient (neutral dark gray, no purple)
        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, QColor("#3a3a3e"))
        gradient.setColorAt(0.5, QColor("#2a2a2e"))
        gradient.setColorAt(1.0, QColor("#1a1a1e"))

        self.setBrush(QBrush(gradient))
        # Pen width scaled for 2048px coordinate system
        self.setPen(QPen(QColor("#4a4a4e"), 4))  # was 2

        # Behind everything
        self.setZValue(-10)
        self.setData(Qt.ItemDataRole.UserRole, "background")


class SectorDividerLine(QGraphicsLineItem):
    """
    Radial line separating zodiac sectors.
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 angle: float, parent=None):
        """
        Create a sector divider line.

        Args:
            center_x, center_y: Center of wheel
            inner_radius: Start radius (center circle edge)
            outer_radius: End radius (outer ring edge)
            angle: Angle of the line in degrees
        """
        angle_rad = math.radians(angle)

        x1 = center_x + inner_radius * math.cos(angle_rad)
        y1 = center_y - inner_radius * math.sin(angle_rad)
        x2 = center_x + outer_radius * math.cos(angle_rad)
        y2 = center_y - outer_radius * math.sin(angle_rad)

        super().__init__(x1, y1, x2, y2, parent)

        # Pen width scaled for 2048px coordinate system
        self.setPen(QPen(QColor("#555555"), 2))  # was 1
        self.setZValue(1)
        self.setData(Qt.ItemDataRole.UserRole, "sector_line")


class AscendantGlowItem(QGraphicsEllipseItem):
    """
    Glow effect at the Ascendant position (9 o'clock).
    """

    def __init__(self, center_x: float, center_y: float, radius: float,
                 glow_radius: float = 30, parent=None):
        """
        Create an Ascendant glow.

        Args:
            center_x, center_y: Center of wheel
            radius: Radius of the Ascendant position
            glow_radius: Size of the glow effect
        """
        # Position at 180° (9 o'clock = LEFT)
        angle_rad = math.radians(180)
        glow_x = center_x + radius * math.cos(angle_rad)
        glow_y = center_y - radius * math.sin(angle_rad)

        super().__init__(glow_x - glow_radius, glow_y - glow_radius,
                        glow_radius * 2, glow_radius * 2, parent)

        # Golden gradient glow
        gradient = QRadialGradient(glow_x, glow_y, glow_radius)
        gradient.setColorAt(0, QColor(255, 215, 0, 180))   # Gold center
        gradient.setColorAt(0.5, QColor(255, 165, 0, 100)) # Orange mid
        gradient.setColorAt(1.0, QColor(255, 69, 0, 0))    # Transparent edge

        self.setBrush(QBrush(gradient))
        self.setPen(Qt.PenStyle.NoPen)

        self.setZValue(-5)  # Behind sectors but above background
        self.setData(Qt.ItemDataRole.UserRole, "ascendant_glow")


class TropicalOuterRimBackground(QGraphicsPathItem):
    """
    Dark background ring for the outer Tropical rim.
    Draws an annulus (ring) with dark gradient background.
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float, parent=None):
        """
        Create the outer rim background ring.

        Args:
            center_x, center_y: Center of the wheel
            inner_radius: Inner edge of the ring
            outer_radius: Outer edge of the ring
        """
        super().__init__(parent)

        # Create annulus path (ring shape)
        path = QPainterPath()

        # Outer circle (clockwise)
        path.addEllipse(
            center_x - outer_radius, center_y - outer_radius,
            outer_radius * 2, outer_radius * 2
        )

        # Inner circle (counter-clockwise to create hole)
        inner_path = QPainterPath()
        inner_path.addEllipse(
            center_x - inner_radius, center_y - inner_radius,
            inner_radius * 2, inner_radius * 2
        )

        # Subtract inner from outer
        path = path.subtracted(inner_path)
        self.setPath(path)

        # Dark gradient fill
        gradient = QRadialGradient(center_x, center_y, outer_radius)
        gradient.setColorAt(0.7, QColor("#1a1a1e"))
        gradient.setColorAt(0.85, QColor("#252528"))
        gradient.setColorAt(1.0, QColor("#1a1a1e"))

        self.setBrush(QBrush(gradient))
        self.setPen(QPen(QColor("#3a3a3e"), 3))

        # Z-value: above current outer ring but below zodiac icons
        self.setZValue(12)
        self.setData(Qt.ItemDataRole.UserRole, "tropical_rim_bg")


class TropicalSectorDivider(QGraphicsLineItem):
    """
    Radial divider line for Tropical rim sectors.
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 angle: float, parent=None):
        """
        Create a Tropical sector divider line.

        Args:
            center_x, center_y: Center of wheel
            inner_radius: Start radius
            outer_radius: End radius
            angle: Angle of the line in degrees
        """
        angle_rad = math.radians(angle)

        x1 = center_x + inner_radius * math.cos(angle_rad)
        y1 = center_y - inner_radius * math.sin(angle_rad)
        x2 = center_x + outer_radius * math.cos(angle_rad)
        y2 = center_y - outer_radius * math.sin(angle_rad)

        super().__init__(x1, y1, x2, y2, parent)

        self.setPen(QPen(QColor("#4a4a4e"), 2))
        self.setZValue(13)
        self.setData(Qt.ItemDataRole.UserRole, "tropical_divider")


class TropicalZodiacSymbolItem(QGraphicsPixmapItem):
    """
    Tropical zodiac sign icon on the outer Tropical rim.
    Positioned at TROPICAL positions (no Aditya shift).
    """

    def __init__(self, pixmap, x: float, y: float, sign_index: int, parent=None):
        """
        Create a Tropical zodiac icon from a pre-loaded pixmap.

        Args:
            pixmap: Pre-loaded QPixmap
            x, y: Center position for the icon
            sign_index: 0-11 (Tropical: 0=Aries, 1=Taurus, etc.)
        """
        super().__init__(pixmap, parent)

        # Center on position using pixmap dimensions
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        self.setPos(x, y)

        # Z-value: on top of the tropical rim background
        self.setZValue(14)

        self.setData(Qt.ItemDataRole.UserRole, f"tropical_symbol_{sign_index}")


class OuterRimAscendantGlow(QGraphicsEllipseItem):
    """
    Glow effect at the outer rim Ascendant position.
    Similar to AscendantGlowItem but positioned on the outer rim.
    """

    def __init__(self, center_x: float, center_y: float, radius: float,
                 ascendant_degrees: float, rotation_offset: float,
                 color: str = "#FF8C00", glow_radius: float = 60, parent=None):
        """
        Create an outer rim Ascendant glow.

        Args:
            center_x, center_y: Center of wheel
            radius: Radius of outer rim
            ascendant_degrees: Ascendant position in degrees
            rotation_offset: Current wheel rotation offset
            color: Glow color
            glow_radius: Size of glow effect
        """
        # Calculate position
        marker_angle = 180 + (ascendant_degrees - rotation_offset)
        angle_rad = math.radians(marker_angle)

        glow_x = center_x + radius * math.cos(angle_rad)
        glow_y = center_y - radius * math.sin(angle_rad)

        super().__init__(glow_x - glow_radius, glow_y - glow_radius,
                        glow_radius * 2, glow_radius * 2, parent)

        # Create gradient with the specified color
        base_color = QColor(color)
        gradient = QRadialGradient(glow_x, glow_y, glow_radius)
        gradient.setColorAt(0, QColor(base_color.red(), base_color.green(), base_color.blue(), 200))
        gradient.setColorAt(0.5, QColor(base_color.red(), base_color.green(), base_color.blue(), 100))
        gradient.setColorAt(1.0, QColor(base_color.red(), base_color.green(), base_color.blue(), 0))

        self.setBrush(QBrush(gradient))
        self.setPen(Qt.PenStyle.NoPen)

        self.setZValue(16)  # Behind outer rim planets but visible
        self.setData(Qt.ItemDataRole.UserRole, "outer_rim_asc_glow")


class OuterRimAscendantLabel(QGraphicsTextItem):
    """
    Text label showing the outer rim Ascendant sign name.
    """

    def __init__(self, center_x: float, center_y: float, radius: float,
                 ascendant_degrees: float, rotation_offset: float,
                 color: str = "#FF8C00", parent=None):
        """
        Create an outer rim Ascendant label.

        Args:
            center_x, center_y: Center of wheel
            radius: Radius for label placement (slightly outside outer rim)
            ascendant_degrees: Ascendant position in degrees
            rotation_offset: Current wheel rotation offset
            color: Text color
        """
        super().__init__(parent)

        # Get sign info
        sign_index = int(ascendant_degrees / 30) % 12
        ADITYA_SIGNS = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                        'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']
        sign_name = ADITYA_SIGNS[sign_index]
        deg_in_sign = ascendant_degrees % 30

        # Set text
        self.setPlainText(f"ASC {deg_in_sign:.0f}° {sign_name}")

        # Style
        font = QFont("Arial", 11, QFont.Weight.Bold)
        self.setFont(font)
        self.setDefaultTextColor(QColor(color))

        # Calculate position (outside the outer rim)
        marker_angle = 180 + (ascendant_degrees - rotation_offset)
        angle_rad = math.radians(marker_angle)

        label_x = center_x + radius * math.cos(angle_rad)
        label_y = center_y - radius * math.sin(angle_rad)

        # Offset to center the text
        self.setPos(label_x - 50, label_y - 10)

        self.setZValue(19)  # On top of everything
        self.setData(Qt.ItemDataRole.UserRole, "outer_rim_asc_label")


class OuterRimAscendantMarker(QGraphicsPathItem):
    """
    Triangle marker for outer rim Ascendant position.
    Points inward to indicate the Ascendant location.
    """

    def __init__(self, center_x: float, center_y: float, radius: float,
                 ascendant_degrees: float, rotation_offset: float,
                 color: str = "#FF8C00", size: float = 20, parent=None):
        """
        Create an outer rim Ascendant marker.

        Args:
            center_x, center_y: Center of wheel
            radius: Radius where marker should be placed (outer rim)
            ascendant_degrees: Ascendant position in degrees (0-360)
            rotation_offset: Current wheel rotation offset
            color: Marker color (default orange for eclipse/transit)
            size: Size of the triangle marker
        """
        super().__init__(parent)

        # Calculate position: Ascendant angle + wheel rotation
        marker_angle = 180 + (ascendant_degrees - rotation_offset)
        angle_rad = math.radians(marker_angle)

        # Position at outer radius
        marker_x = center_x + radius * math.cos(angle_rad)
        marker_y = center_y - radius * math.sin(angle_rad)

        # Create triangle pointing inward
        path = QPainterPath()
        inward_angle = angle_rad + math.pi  # Point toward center

        # Tip of triangle (pointing inward)
        tip_x = marker_x + (size * 0.8) * math.cos(inward_angle)
        tip_y = marker_y - (size * 0.8) * math.sin(inward_angle)

        # Base vertices (perpendicular to inward direction)
        perp_angle = inward_angle + math.pi / 2
        half_base = size * 0.5

        base1_x = marker_x + half_base * math.cos(perp_angle)
        base1_y = marker_y - half_base * math.sin(perp_angle)
        base2_x = marker_x - half_base * math.cos(perp_angle)
        base2_y = marker_y + half_base * math.sin(perp_angle)

        path.moveTo(tip_x, tip_y)
        path.lineTo(base1_x, base1_y)
        path.lineTo(base2_x, base2_y)
        path.closeSubpath()

        self.setPath(path)

        # Style
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor("#FFFFFF"), 2))

        self.setZValue(18)  # On top of outer rim planets
        self.setData(Qt.ItemDataRole.UserRole, "outer_rim_ascendant")

        # Tooltip
        sign_index = int(ascendant_degrees / 30) % 12
        ADITYA_SIGNS = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                        'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']
        sign_name = ADITYA_SIGNS[sign_index]
        deg_in_sign = ascendant_degrees % 30
        self.setToolTip(f"Outer Ascendant: {deg_in_sign:.1f}° {sign_name}")


class RetinueRingSector(QGraphicsPathItem):
    """
    Colored arc wedge for Hora or Trimsamsa ring sectors.

    Creates an annular wedge (donut slice) with variable span angle.
    Same arc-path pattern as ZodiacSectorItem but with configurable span
    and flat color fill (no gradient).
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 start_angle: float, span_angle: float,
                 bg_color: str, border_color: str = "#3a3a3e",
                 hover_signal=None, sector_key=None,
                 parent=None):
        """
        Create a retinue ring sector.

        Args:
            center_x, center_y: Center of the wheel
            inner_radius: Inner edge of the ring
            outer_radius: Outer edge of the ring
            start_angle: Starting angle in degrees (0° = 3 o'clock, CCW)
            span_angle: Angular width in degrees (e.g. 15 for Hora, 5-8 for Trimsamsa)
            bg_color: Fill color hex string
            border_color: Border color hex string
        """
        super().__init__(parent)

        # Build annular wedge path
        path = QPainterPath()

        # Calculate start points
        start_rad = math.radians(start_angle)
        outer_start_x = center_x + outer_radius * math.cos(start_rad)
        outer_start_y = center_y - outer_radius * math.sin(start_rad)

        end_rad = math.radians(start_angle + span_angle)
        inner_end_x = center_x + inner_radius * math.cos(end_rad)
        inner_end_y = center_y - inner_radius * math.sin(end_rad)

        # Start at outer arc
        path.moveTo(outer_start_x, outer_start_y)

        # Outer arc (counter-clockwise, positive span)
        path.arcTo(
            center_x - outer_radius, center_y - outer_radius,
            outer_radius * 2, outer_radius * 2,
            start_angle, span_angle
        )

        # Line to inner arc end
        path.lineTo(inner_end_x, inner_end_y)

        # Inner arc (clockwise, negative span)
        path.arcTo(
            center_x - inner_radius, center_y - inner_radius,
            inner_radius * 2, inner_radius * 2,
            start_angle + span_angle, -span_angle
        )

        path.closeSubpath()
        self.setPath(path)

        # Flat color fill
        self.setBrush(QBrush(QColor(bg_color)))
        self.setPen(QPen(QColor(border_color), 1))
        self._original_pen = self.pen()
        self._original_brush = self.brush()

        # Z=3.5: below zodiac icons (Z=4) so sign PNGs show on top
        self.setZValue(3.5)
        self.setData(Qt.ItemDataRole.UserRole, "retinue_sector")

        self._hover_signal = hover_signal
        self._sector_key = sector_key
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        if hover_signal is not None:
            self.setAcceptHoverEvents(True)

    def set_highlighted(self, highlighted: bool):
        if highlighted:
            self.setPen(QPen(QColor("#FFFFFF"), 3))
            self.setZValue(3.9)
        else:
            self.setPen(self._original_pen)
            self.setBrush(self._original_brush)
            self.setZValue(3.5)

    def hoverEnterEvent(self, event):
        if self._hover_signal and self._sector_key:
            self._hover_signal.hover_enter.emit(self._sector_key)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self._hover_signal:
            self._hover_signal.hover_leave.emit()
        super().hoverLeaveEvent(event)


class RetinueRingLabel(QGraphicsTextItem):
    """
    Rotated text label for Hora or Trimsamsa ring sectors.

    Positioned at the center of a sector arc and rotated radially
    so text reads outward from the wheel center.
    """

    def __init__(self, text: str, x: float, y: float,
                 rotation: float, font_size: int = 14,
                 color: str = "#FFFFFF", parent=None):
        """
        Create a retinue ring label.

        Args:
            text: Label text (being name or abbreviation)
            x, y: Center position for the label
            rotation: Rotation angle in degrees (pre-computed for radial alignment)
            font_size: Font size in points
            color: Text color hex string
        """
        super().__init__(parent)

        self.setPlainText(text)

        font = QFont("Inter", font_size, QFont.Weight.Bold)
        self.setFont(font)
        self.setDefaultTextColor(QColor(color))

        # Center the text on the position
        br = self.boundingRect()
        self.setPos(x - br.width() / 2, y - br.height() / 2)

        # Apply rotation around the item center
        self.setTransformOriginPoint(br.width() / 2, br.height() / 2)
        self.setRotation(rotation)

        # Z=3.9: above sectors (3.5) and glow lines (3.8), below zodiac icons (4)
        self.setZValue(3.9)
        self.setData(Qt.ItemDataRole.UserRole, "retinue_label")

        # Transparent to hover — let sector below receive hover events
        self.setAcceptHoverEvents(False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
