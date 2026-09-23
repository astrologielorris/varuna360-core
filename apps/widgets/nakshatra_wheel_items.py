"""
Nakshatra Wheel Graphics Items
Custom QGraphicsItem subclasses for the 27-sector nakshatra wheel.

Contains:
- NakshatraSectorItem - Annular wedge with alternating dark shades
- NakshatraNameItem - 3-letter abbreviation label, rotated radially
- LordIconItem - Planet PNG icon for Vimshottari lord
- DashaNumberItem - Bold number 1-9 in dasha ring
- PadaDividerLine - Thin line subdividing pada within outermost ring
- HouseCuspLine - Dotted radial line for house cusps (planet ring only)
- CenterBlankCircle - Dark center disc (reserved for future zodiac embed)
- RingBackground - Annular ring background with flat dark fill
- OppositeNakDiameterLine - Colored diameter line connecting opposite nakshatras
- NakEndpointLabel - 3-letter abbreviation at diameter line endpoints
"""
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsSimpleTextItem
)
from PySide6.QtCore import Qt, QPointF, Signal, QObject
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QRadialGradient
)

# SPEC-FONT-001 B5: painted wheel labels carry intrinsic size TIERS (name 13,
# dasha number 14, cusp 10, endpoint 7). scaled_tier_size scales each tier
# literal by the chart_labels factor — ratios preserved, responds to the
# per-area font setting + global scale, factor 1.0 at defaults (zero-change
# parity). Painted graphics items honor QFont, so these keep QFont (not QSS).
from ui.qt_theme import scaled_tier_size as _tier_pt, get_theme_colors


def canvas_color(dark, light):
    """Keep the established dark palette and provide an opaque light canvas."""
    return light if QColor(get_theme_colors()["secondary"]).lightness() > 128 else dark


# ── Click Signal Emitter ─────────────────────────────────────────

class NakshatraClickSignal(QObject):
    """Signal emitter for nakshatra sector click events."""
    clicked = Signal(int)  # Emits nak_index (0-26)


# ── Sector Wedge ─────────────────────────────────────────────────

class NakshatraSectorItem(QGraphicsPathItem):
    """
    Annular wedge for one nakshatra sector (13°20' arc).
    Alternates between two dark shades for visual distinction.
    """

    SHADE_A = "#2A2A2E"
    SHADE_B = "#323238"

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 start_angle: float, span_angle: float,
                 nak_index: int, parent=None):
        super().__init__(parent)

        self.nak_index = nak_index

        color = canvas_color(self.SHADE_A, "#f5f5f6") if (nak_index % 2 == 0) else canvas_color(self.SHADE_B, "#e8eaed")

        # Build annular wedge path
        path = QPainterPath()
        start_rad = math.radians(start_angle)
        end_rad = math.radians(start_angle + span_angle)

        # Outer arc start
        ox = center_x + outer_radius * math.cos(start_rad)
        oy = center_y - outer_radius * math.sin(start_rad)
        path.moveTo(ox, oy)

        # Outer arc (CCW)
        path.arcTo(
            center_x - outer_radius, center_y - outer_radius,
            outer_radius * 2, outer_radius * 2,
            start_angle, span_angle
        )

        # Line to inner arc end
        ix_end = center_x + inner_radius * math.cos(end_rad)
        iy_end = center_y - inner_radius * math.sin(end_rad)
        path.lineTo(ix_end, iy_end)

        # Inner arc (CW = negative span)
        path.arcTo(
            center_x - inner_radius, center_y - inner_radius,
            inner_radius * 2, inner_radius * 2,
            start_angle + span_angle, -span_angle
        )

        path.closeSubpath()
        self.setPath(path)

        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor(canvas_color("#555555", "#a4a8ae")), 1))
        self.setZValue(0)
        self.setData(Qt.ItemDataRole.UserRole, f"nak_sector_{nak_index}")



# ── Ring Background ──────────────────────────────────────────────

class RingBackground(QGraphicsPathItem):
    """
    Full annular ring background (no sector divisions).
    Used for rings 2-5 behind labels/icons.
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 color: str, parent=None):
        super().__init__(parent)

        # Outer circle
        path = QPainterPath()
        path.addEllipse(
            center_x - outer_radius, center_y - outer_radius,
            outer_radius * 2, outer_radius * 2
        )
        # Subtract inner circle
        inner_path = QPainterPath()
        inner_path.addEllipse(
            center_x - inner_radius, center_y - inner_radius,
            inner_radius * 2, inner_radius * 2
        )
        path = path.subtracted(inner_path)
        self.setPath(path)

        self.setBrush(QBrush(QColor(color)))
        self.setPen(Qt.PenStyle.NoPen)
        self.setZValue(0.5)
        self.setData(Qt.ItemDataRole.UserRole, "ring_bg")


# ── Nakshatra Name Label ─────────────────────────────────────────

class NakshatraNameItem(QGraphicsTextItem):
    """
    Three-letter nakshatra abbreviation, placed horizontally in ring 2.
    Always horizontal (no rotation) — matches Kala's layout.
    Tooltip shows full nakshatra name on hover.
    Click opens nakshatra info dialog.
    """

    def __init__(self, text: str, x: float, y: float,
                 font_size: int = 14, full_name: str = "",
                 nak_index: int = 0, signal_emitter=None, parent=None):
        super().__init__(parent)

        self.nak_index = nak_index
        self.signal_emitter = signal_emitter

        self.setPlainText(text)
        font = QFont("Inter", _tier_pt(font_size), QFont.Weight.Bold)
        self.setFont(font)
        self.setDefaultTextColor(QColor(canvas_color("#FFFFFF", "#30343a")))

        # Center on position (always horizontal, no rotation)
        br = self.boundingRect()
        self.setPos(x - br.width() / 2, y - br.height() / 2)

        # Tooltip with full nakshatra name + click interaction
        if full_name:
            self.setToolTip(full_name)
        self.setAcceptHoverEvents(True)
        if signal_emitter is not None:
            # Don't accept mouse buttons - view handles clicks via mouseDoubleClickEvent
            self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setZValue(4)
        self.setData(Qt.ItemDataRole.UserRole, "nak_name")


# ── Lord Icon ────────────────────────────────────────────────────

class LordIconItem(QGraphicsPixmapItem):
    """
    Small planet PNG icon representing the Vimshottari lord of a nakshatra.
    Placed in ring 3.
    """

    def __init__(self, pixmap, x: float, y: float, nak_index: int, parent=None):
        super().__init__(pixmap, parent)

        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        self.setPos(x, y)
        self.setZValue(5)
        self.setData(Qt.ItemDataRole.UserRole, f"nak_lord_{nak_index}")


# ── Dasha Number ─────────────────────────────────────────────────

class DashaNumberItem(QGraphicsTextItem):
    """
    Bold white number (1-9) showing the dasha sequence position.
    Placed in ring 4.
    """

    def __init__(self, number: int, x: float, y: float,
                 font_size: int = 16, parent=None):
        super().__init__(parent)

        self.setPlainText(str(number))
        font = QFont("Inter", _tier_pt(font_size), QFont.Weight.Bold)
        self.setFont(font)
        self.setDefaultTextColor(QColor(canvas_color("#FFFFFF", "#30343a")))

        # Center on position
        br = self.boundingRect()
        self.setPos(x - br.width() / 2, y - br.height() / 2)

        self.setZValue(6)
        self.setData(Qt.ItemDataRole.UserRole, "dasha_number")


# ── Pada Divider Line ────────────────────────────────────────────

class PadaDividerLine(QGraphicsLineItem):
    """
    Thin radial line subdividing a nakshatra into 4 pada in ring 5.
    """

    def __init__(self, x1: float, y1: float, x2: float, y2: float, parent=None):
        super().__init__(x1, y1, x2, y2, parent)
        self.setPen(QPen(QColor(canvas_color("#444444", "#b5b9bf")), 1))
        self.setZValue(1.5)
        self.setData(Qt.ItemDataRole.UserRole, "pada_line")


# ── House Cusp Line ──────────────────────────────────────────────

class HouseCuspLine(QGraphicsLineItem):
    """
    Dotted radial line for a house cusp within the planet ring (ring 1).
    Angular houses (1,4,7,10) use brighter gray.
    """

    def __init__(self, x1: float, y1: float, x2: float, y2: float,
                 house_number: int, parent=None):
        super().__init__(x1, y1, x2, y2, parent)

        is_angular = house_number in [1, 4, 7, 10]
        color = canvas_color("#999999", "#62676f") if is_angular else canvas_color("#666666", "#838890")
        width = 2 if is_angular else 1

        pen = QPen(QColor(color), width)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(7)
        self.setData(Qt.ItemDataRole.UserRole, f"house_cusp_{house_number}")


# ── House Cusp Label ─────────────────────────────────────────────

class HouseCuspLabel(QGraphicsTextItem):
    """Small label for house cusp (e.g. 'Asc', 'H2'...'H12')."""

    def __init__(self, text: str, x: float, y: float,
                 house_number: int, font_size: int = 11, parent=None):
        super().__init__(parent)

        self.setPlainText(text)
        font = QFont("Inter", _tier_pt(font_size))
        self.setFont(font)

        is_angular = house_number in [1, 4, 7, 10]
        self.setDefaultTextColor(QColor(canvas_color("#CCCCCC", "#42474e") if is_angular else canvas_color("#999999", "#62676f")))

        br = self.boundingRect()
        self.setPos(x - br.width() / 2, y - br.height() / 2)
        self.setZValue(7.5)
        self.setData(Qt.ItemDataRole.UserRole, f"house_label_{house_number}")


# ── Center Blank Circle ──────────────────────────────────────────

class CenterBlankCircle(QGraphicsEllipseItem):
    """
    Dark center disc. Reserved for future zodiac wheel toggle.
    """

    def __init__(self, center_x: float, center_y: float, radius: float, parent=None):
        super().__init__(
            center_x - radius, center_y - radius,
            radius * 2, radius * 2, parent
        )

        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, QColor(canvas_color("#1E1E22", "#fafafa")))
        gradient.setColorAt(0.8, QColor(canvas_color("#1A1A1E", "#f5f5f5")))
        gradient.setColorAt(1.0, QColor(canvas_color("#161619", "#eeeeef")))

        self.setBrush(QBrush(gradient))
        self.setPen(QPen(QColor(canvas_color("#333336", "#b7bbc1")), 2))
        self.setZValue(2)
        self.setData(Qt.ItemDataRole.UserRole, "center_blank")


# ── Sector Divider Line (full radial) ────────────────────────────

class NakSectorDividerLine(QGraphicsLineItem):
    """
    Thin radial line separating nakshatra sectors across all rings.
    """

    def __init__(self, center_x: float, center_y: float,
                 inner_radius: float, outer_radius: float,
                 angle: float, parent=None):
        angle_rad = math.radians(angle)
        x1 = center_x + inner_radius * math.cos(angle_rad)
        y1 = center_y - inner_radius * math.sin(angle_rad)
        x2 = center_x + outer_radius * math.cos(angle_rad)
        y2 = center_y - outer_radius * math.sin(angle_rad)

        super().__init__(x1, y1, x2, y2, parent)
        self.setPen(QPen(QColor(canvas_color("#555555", "#a4a8ae")), 1))
        self.setZValue(1)
        self.setData(Qt.ItemDataRole.UserRole, "nak_divider")


# ── Ring Boundary Circle ─────────────────────────────────────────

class RingBoundaryCircle(QGraphicsEllipseItem):
    """Thin dark circle separating two rings."""

    def __init__(self, center_x: float, center_y: float, radius: float, parent=None):
        super().__init__(
            center_x - radius, center_y - radius,
            radius * 2, radius * 2, parent
        )
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setPen(QPen(QColor(canvas_color("#3A3A3E", "#b4b8bf")), 2))
        self.setZValue(3)
        self.setData(Qt.ItemDataRole.UserRole, "ring_boundary")


# ── Background Circle ────────────────────────────────────────────

class NakBackgroundCircle(QGraphicsEllipseItem):
    """Full dark background behind all rings."""

    def __init__(self, center_x: float, center_y: float, radius: float, parent=None):
        super().__init__(
            center_x - radius, center_y - radius,
            radius * 2, radius * 2, parent
        )

        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, QColor(canvas_color("#222226", "#ffffff")))
        gradient.setColorAt(0.5, QColor(canvas_color("#1C1C20", "#f6f6f7")))
        gradient.setColorAt(1.0, QColor(canvas_color("#161619", "#eeeeef")))

        self.setBrush(QBrush(gradient))
        self.setPen(Qt.PenStyle.NoPen)
        self.setZValue(-10)
        self.setData(Qt.ItemDataRole.UserRole, "nak_background")


# ── Opposite-Nakshatra Diameter Line ────────────────────────────

class OppositeNakDiameterLine(QGraphicsLineItem):
    """Diameter line connecting opposite nakshatra boundaries through center.

    Each of the 27 lines has a unique color so adjacent lines are visually
    distinct and you can trace one line from endpoint to endpoint.
    """

    def __init__(self, x1, y1, x2, y2, color, parent=None):
        super().__init__(x1, y1, x2, y2, parent)
        pen = QPen(QColor(color) if isinstance(color, str) else color, 1)
        pen.setCosmetic(True)  # Constant pixel width regardless of zoom
        self.setPen(pen)
        self.setData(Qt.ItemDataRole.UserRole, "opposite_nak_line")


# ── Nakshatra Endpoint Label ────────────────────────────────────

class NakEndpointLabel(QGraphicsSimpleTextItem):
    """3-letter nakshatra abbreviation at a diameter line endpoint.

    Positioned near the R_CENTER boundary inside the center circle.
    Same color as its diameter line for visual traceability.
    """

    def __init__(self, x, y, text, color, parent=None):
        super().__init__(text, parent)
        # Fixed 7pt tier (endpoint marker) — scaled by the same chart_labels factor.
        font = QFont("Segoe UI", _tier_pt(7), QFont.Weight.Bold)
        self.setFont(font)
        self.setBrush(QBrush(QColor(color) if isinstance(color, str) else color))
        br = self.boundingRect()
        self.setPos(x - br.width() / 2, y - br.height() / 2)
        self.setData(Qt.ItemDataRole.UserRole, "nak_endpoint_label")
