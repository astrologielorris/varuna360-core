"""Passive graphics items and click signals; no chart or view ownership."""
from PySide6.QtCore import QObject, Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem, QGraphicsPixmapItem
from ui.qt_theme import GOLD, desat_hex
from visualizations.wheel_constants import ELEMENT_COLORS, get_element_for_sign
from apps.widgets.south_indian_geometry import CARD_RADIUS, TAG_CARD, TAG_HOVER, TAG_PLANET

class SignCardItem(QGraphicsPathItem):
    """Rounded-rect element card for one sign (spec §4.3).

    Fill: QRadialGradient per the NI DiamondCellItem recipe — lighter(120)
    at 0.0, base element color at 0.5, darker(115) at 1.0, centered slightly
    above the card center. Border: 1.5px gold at 60% alpha. One item does
    fill + border (z=1); the z-table's separate border row (z=2) is only
    needed when fills and borders are distinct items — nothing at z<2
    overlaps a card.
    """

    def __init__(self, sign_index: int, rect: QRectF, parent=None):
        super().__init__(parent)
        self.sign_index = sign_index

        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        self.setPath(path)

        base = QColor(desat_hex(ELEMENT_COLORS[get_element_for_sign(sign_index)]))  # SPEC-SAT-001
        center = rect.center()
        gradient = QRadialGradient(
            center.x(), center.y() - rect.height() * 0.15,
            rect.width() * 0.75,
        )
        gradient.setColorAt(0.0, base.lighter(120))
        gradient.setColorAt(0.5, base)
        gradient.setColorAt(1.0, base.darker(115))
        self.setBrush(QBrush(gradient))

        border = QColor(GOLD)
        border.setAlphaF(0.6)
        self.setPen(QPen(border, 1.5))

        self.setZValue(1)
        self.setData(Qt.ItemDataRole.UserRole, TAG_CARD)

class HoverZoneItem(QGraphicsRectItem):
    """Invisible hover rect over a card (classic HoverZoneItem pattern,
    chart_view.py:86-162). Accepts NO mouse buttons so it never blocks
    clicks. Phase 1: the zones only exist and are tagged; the center-preview
    behavior they will drive is Phase 2 (spec §4.5)."""

    def __init__(self, rect: QRectF, zodiac_index: int, parent=None):
        super().__init__(rect, parent)
        self.zodiac_index = zodiac_index
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.GlobalColor.transparent))
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(50)
        self.setData(Qt.ItemDataRole.UserRole, TAG_HOVER)

class PlanetClickSignal(QObject):
    """Emitter for planet double-click events (classic chart_view.py:119-121)."""
    clicked = Signal(str, dict)

class SignClickSignal(QObject):
    """Emitter for sign double-click events (classic chart_view.py:142-144)."""
    clicked = Signal(int, int)

class ClickablePlanetItem(QGraphicsPixmapItem):
    """Planet icon carrying the payload the double-click signal emits.

    Passive (accepts NO mouse buttons): the view detects double-clicks via
    items(event.pos()) — the classic stuck-pan fix (chart_view.py:695-716).
    """

    def __init__(self, pixmap, planet_name, planet_info, signal_emitter,
                 parent=None):
        super().__init__(pixmap, parent)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.planet_name = planet_name
        self.planet_info = planet_info
        self.signal_emitter = signal_emitter
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setZValue(75)
        self.setData(Qt.ItemDataRole.UserRole, TAG_PLANET)

class SignIconItem(QGraphicsPixmapItem):
    """Sign icon carrying (zodiac_index, current_variation) for the variation
    dialog (classic ClickableZodiacItem, chart_view.py:146-162). Passive like
    ClickablePlanetItem."""

    def __init__(self, pixmap, zodiac_index, current_variation,
                 signal_emitter, parent=None):
        super().__init__(pixmap, parent)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.zodiac_index = zodiac_index
        self.current_variation = current_variation
        self.signal_emitter = signal_emitter
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
