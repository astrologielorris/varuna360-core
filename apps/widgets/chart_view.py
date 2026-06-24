#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
South Indian View Widget
Extracted from core_gui_qt.py for modularity

Contains:
- HoverSignal, PlanetClickSignal, SignClickSignal - Signal emitters
- HoverZoneItem, ClickablePlanetItem, ClickableZodiacItem - Interactive graphics items
- SouthIndianView - Main chart rendering widget (renamed for future view types)
"""
import sys
import json
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPixmap, QFont, QImage,
    QPainterPath, QFontMetrics, QLinearGradient
)

# Project root for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import centralized theme
from ui.qt_theme import (
    BG, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    GOLD, ACCENTS, FONT_CHART, get_theme_colors,
)

# Import settings manager for chart display customization
from managers.settings_manager import get_settings
from core.aditya_mode import displayed_sign_name, get_planet_display_name
from state.user_data import get_settings_path as _get_settings_path

# Background images folder - NEW location (no fallback)
BACKGROUNDS_PATH = PROJECT_ROOT / "img" / "background"

# Per-background display presets (house number offsets, sign label offsets, etc.)
BACKGROUND_PRESETS_PATH = PROJECT_ROOT / "data" / "background_presets.json"

def _load_background_presets():
    """Load per-background display presets from JSON file.

    Keys must be short background identifiers like 'stone_01', not
    full filename stems like 'stone_01_white_carrara_marble'.
    """
    if BACKGROUND_PRESETS_PATH.exists():
        try:
            with open(BACKGROUND_PRESETS_PATH, 'r') as f:
                data = json.load(f)
            # Convert list values to tuples for offset dicts
            presets = {}
            for bg_id, settings in data.items():
                if bg_id.startswith('_comment'):
                    continue  # Skip JSON comment keys
                # Warn if key looks like a full filename stem
                parts = bg_id.split('_')
                if len(parts) > 2:
                    print(f"[CHART] Warning: preset key '{bg_id}' looks like a full "
                          f"filename — use short prefix like '{parts[0]}_{parts[1]}'")
                presets[bg_id] = {}
                for key, value in settings.items():
                    if key.endswith('_offset') and isinstance(value, dict):
                        presets[bg_id][key] = {
                            name: tuple(coords) for name, coords in value.items()
                        }
                    else:
                        presets[bg_id][key] = value
            return presets
        except Exception as e:
            print(f"[CHART] Warning: Could not load background presets: {e}")
    return {}

BACKGROUND_PRESETS = _load_background_presets()

class HoverSignal(QObject):
    """Signal emitter for hover zone events (QGraphicsItem can't emit signals directly)"""
    hover_enter = Signal(int)  # Emits zodiac_index
    hover_leave = Signal()

class HoverZoneItem(QGraphicsRectItem):
    """Invisible rectangle that detects hover events for a zodiac cell"""

    def __init__(self, x, y, width, height, zodiac_index, signal_emitter, parent=None):
        super().__init__(x, y, width, height, parent)
        self.zodiac_index = zodiac_index
        self.signal_emitter = signal_emitter

        # Make invisible but still detect hover
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.GlobalColor.transparent))

        # Enable hover events
        self.setAcceptHoverEvents(True)

        # Don't accept mouse buttons: hover zones must not block planet clicks
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def hoverEnterEvent(self, event):
        """Emit signal when mouse enters this zone"""
        self.signal_emitter.hover_enter.emit(self.zodiac_index)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Don't hide preview on leave - only change when entering another cell"""
        # Preview stays until user hovers over a different cell
        super().hoverLeaveEvent(event)

class PlanetClickSignal(QObject):
    """Signal emitter for planet click events"""
    clicked = Signal(str, dict)  # Emits (planet_name, planet_info)

class ClickablePlanetItem(QGraphicsPixmapItem):
    """Planet icon that can be clicked to show detailed info"""

    def __init__(self, pixmap, planet_name, planet_info, signal_emitter, parent=None):
        super().__init__(pixmap, parent)
        self.planet_name = planet_name
        self.planet_info = planet_info
        self.signal_emitter = signal_emitter

        # Don't accept mouse buttons - view handles clicks via mouseDoubleClickEvent
        # This prevents items from consuming events before the view can detect double-clicks
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        # Hover cursor still works (uses hover events, independent of mouse button acceptance)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # BoundingRectShape needed for itemAt() detection at view level
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)

class SignClickSignal(QObject):
    """Signal emitter for zodiac sign click events"""
    clicked = Signal(int, int)  # Emits (zodiac_index, current_variation)

class ClickableZodiacItem(QGraphicsPixmapItem):
    """Zodiac icon that can be double-clicked to open variation dialog"""

    def __init__(self, pixmap, zodiac_index, current_variation, signal_emitter, parent=None):
        super().__init__(pixmap, parent)
        self.zodiac_index = zodiac_index
        self.current_variation = current_variation
        self.signal_emitter = signal_emitter

        # Don't accept mouse buttons - view handles clicks via mouseDoubleClickEvent
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        # Hover cursor still works (uses hover events, independent of mouse button acceptance)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # BoundingRectShape needed for itemAt() detection at view level
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)

class SouthIndianView(QGraphicsView):
    """Custom QGraphicsView for South Indian chart (renamed for future view types)"""

    # Zodiac position mapping - (row, col) -> zodiac_index
    # South Indian chart layout (FIXED signs, counter-clockwise from top-left)
    ZODIAC_POSITIONS = {
        # Top row (left to right): Parjanya, Dhata, Aryama, Mitra
        (0, 0): 11,  # Parjanya (top-left) - Pisces
        (0, 1): 0,   # Dhata - Aries
        (0, 2): 1,   # Aryama - Taurus
        (0, 3): 2,   # Mitra (top-right) - Gemini
        # Left column (top to bottom): Pusha, Bhaga
        (1, 0): 10,  # Pusha - Aquarius
        (2, 0): 9,   # Bhaga - Capricorn
        # Right column (top to bottom): Varuna, Indra
        (1, 3): 3,   # Varuna - Cancer
        (2, 3): 4,   # Indra - Leo
        # Bottom row (left to right): Amzu, Vishnu, Tvasta, Vivasvan
        (3, 0): 8,   # Amzu (bottom-left) - Sagittarius
        (3, 1): 7,   # Vishnu - Scorpio
        (3, 2): 6,   # Tvasta - Libra
        (3, 3): 5,   # Vivasvan (bottom-right) - Virgo
    }

    # Aditya names for display labels
    ADITYA_NAMES = [
        "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
        "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
    ]

    # Western names for icon filenames (img/sign/icons_128/*.png)
    WESTERN_NAMES = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    # Planet names for calculation (includes outer planets)
    PLANET_NAMES = [
        "Sun", "Moon", "Mars", "Mercury", "Jupiter",
        "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto"
    ]

    # Planet icon filename mapping (handles inconsistent casing in img/planets/)
    PLANET_ICON_NAMES = {
        "Sun": "sun",
        "Moon": "moon",
        "Mars": "Mars",
        "Mercury": "Mercury",
        "Jupiter": "Jupiter",
        "Venus": "Venus",
        "Saturn": "Saturn",
        "Rahu": "rahu",
        "Ketu": "ketu",
        "Uranus": "uranus",
        "Neptune": "neptune",
        "Pluto": "pluto",
    }

    # Individual planet sizes for 2048px scene (512px cells)
    # Moon is larger (reflection of Atma), Venus/Rahu/Ketu/outer planets are smaller
    PLANET_SIZES = {
        "Sun": 160,      # Standard
        "Moon": 200,     # 25% larger - Atma reflection
        "Mars": 160,     # Standard
        "Mercury": 160,  # Standard
        "Jupiter": 160,  # Standard
        "Venus": 128,    # 25% smaller
        "Saturn": 160,   # Standard
        "Rahu": 128,     # 25% smaller
        "Ketu": 128,     # 25% smaller
        "Uranus": 100,   # Smaller - outer planet
        "Neptune": 100,  # Smaller - outer planet
        "Pluto": 100,    # Smaller - outer planet
    }

    # Element colors for ascendant stripe (by zodiac index)
    # Fire=Red, Earth=Brown, Air=Green, Water=Blue
    ELEMENT_COLORS = {
        0: "#E57373",   # Dhata (Aries) - Fire - Coral red
        1: "#A67C52",   # Aryama (Taurus) - Earth - Brown/tan
        2: "#F0C75E",   # Mitra (Gemini) - Air - Golden yellow
        3: "#1E4D8C",   # Varuna (Cancer) - Water - Deep blue
        4: "#E57373",   # Indra (Leo) - Fire - Coral red
        5: "#A67C52",   # Vivasvan (Virgo) - Earth - Brown/tan
        6: "#F0C75E",   # Tvasta (Libra) - Air - Golden yellow
        7: "#1E4D8C",   # Vishnu (Scorpio) - Water - Deep blue
        8: "#E57373",   # Amzu (Sagittarius) - Fire - Coral red
        9: "#A67C52",   # Bhaga (Capricorn) - Earth - Brown/tan
        10: "#F0C75E",  # Pusha (Aquarius) - Air - Golden yellow
        11: "#1E4D8C",  # Parjanya (Pisces) - Water - Deep blue
    }

    # Enhanced element glow colors for Ascendant effect
    ELEMENT_GLOW_COLORS = {
        "fire": {"primary": "#FF6B00", "glow": "#FF4500", "outer": "#FFD700"},
        "earth": {"primary": "#CD853F", "glow": "#DAA520", "outer": "#F4A460"},
        "air": {"primary": "#87CEEB", "glow": "#B0E0E6", "outer": "#E0FFFF"},
        "water": {"primary": "#4169E1", "glow": "#1E90FF", "outer": "#00CED1"},
    }

    # Map zodiac index to element name
    ZODIAC_ELEMENT = {
        0: "fire", 1: "earth", 2: "air", 3: "water",
        4: "fire", 5: "earth", 6: "air", 7: "water",
        8: "fire", 9: "earth", 10: "air", 11: "water",
    }

    # Inner box positioning offsets - distance from cell edge to inner content area
    # Background images have decorative frames that vary by position:
    # - Row 0 (top): Thinner top frame (outer edge of image)
    # - Row 3 (bottom): Thicker top frame (borders center area + gap)
    # - Edge columns (0, 3): Thicker side frames
    # These offsets ensure sign labels appear inside the inner content boxes
    # consistently across all background designs (measured from smallest grid: ~383px inner)
    INNER_BOX_Y_OFFSET = {
        0: 55,   # Row 0: Top row - moderate frame, label needs to clear top edge
        1: 65,   # Row 1: Left edge cells (adjacent to center)
        2: 65,   # Row 2: Left edge cells (adjacent to center)
        3: 35,   # Row 3: Bottom row - less offset needed (visual balance)
    }

    INNER_BOX_X_OFFSET = {
        0: 60,   # Col 0: Left edge - thicker frame
        1: 55,   # Col 1: Top/bottom row cells
        2: 55,   # Col 2: Top/bottom row cells
        3: 60,   # Col 3: Right edge - thicker frame
    }

    # Per-sign base offsets (calibrated for background inner boxes)
    # These are the BASE positions - settings offsets are applied on top
    SIGN_LABEL_BASE_OFFSET = {
        "Dhata": (-29, -13),
        "Aryama": (-37, -12),
        "Mitra": (-50, -12),
        "Varuna": (-50, -40),
        "Indra": (-52, -46),
        "Vivasvan": (-52, -24),
        "Tvasta": (-37, -27),
        "Vishnu": (-31, -29),
        "Amzu": (-21, -25),
        "Bhaga": (-23, -49),
        "Pusha": (-20, -42),
        "Parjanya": (-21, -13),
    }

    # Per-sign house number base offsets (calibrated for background inner boxes)
    # These are the BASE positions - settings offsets are applied on top
    HOUSE_NUMBER_BASE_OFFSET = {
        "Dhata": (47, -14),
        "Aryama": (32, -16),
        "Mitra": (23, -13),
        "Varuna": (20, -25),
        "Indra": (16, -39),
        "Vivasvan": (18, -55),
        "Tvasta": (27, -56),
        "Vishnu": (39, -56),
        "Amzu": (61, -54),
        "Bhaga": (61, -40),
        "Pusha": (63, -24),
        "Parjanya": (64, -9),
    }

    def __init__(self, parent=None, center_box_enabled=True):
        super().__init__(parent)
        self.center_box_enabled = center_box_enabled

        # Setup scene
        self.scene = QGraphicsScene(self)
        # Disable BSP tree indexing to prevent segfaults (Qt Forum #71316)
        # BSP tree corruption is a known Qt bug (QTBUG-18021) that causes crashes
        # when items are frequently added/removed. NoIndex uses linear search but
        # eliminates crashes. Performance impact negligible for ~24 items.
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(self.scene)

        # Track drag state for cursor changes
        self._is_dragging = False

        # Chart parameters (base size, will scale)
        self.chart_size = 2048  # Match source image resolution (2048x2048)
        self.cell_size = self.chart_size / 4  # 512x512 per cell

        # Enable anti-aliasing
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Set scene rect
        self.setSceneRect(0, 0, self.chart_size, self.chart_size)

        # Enable scrollbars for panning
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Enable drag to pan with left mouse button
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        # Set viewport cursor to arrow (not hand) - planets/signs override with their own cursor
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        # Enable mouse tracking for hover events
        self.setMouseTracking(True)
        # StrongFocus required so keyPressEvent receives +/- zoom shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Zoom settings
        self.zoom_factor = 0.45  # Initial value; overwritten by _compute_fit_zoom on first show
        self._fit_zoom_applied = False  # Guard: auto-fit only fires once (first show)
        self.min_zoom = 0.2
        self.max_zoom = 3.0
        self.zoom_step = 1.15  # 15% per scroll step

        # Colors - from centralized theme (live, theme-aware)
        # SPEC-THM-001 G02: read from get_theme_colors() so light theme works.
        _theme = get_theme_colors()
        self.bg_color = QColor(_theme["secondary_dark"])
        self.grid_color = QColor(GOLD)
        self.text_color = QColor(_theme["secondary_text"])
        self.preview_bg_color = QColor(_theme["secondary"])

        # Background image system. `stone_01` is the light-theme lock in Core
        # and is guaranteed present in both Core and Pro asset sets. The old
        # default `stone_05` was removed from Core's assets during the
        # 2026-04-08 public-release cleanup, leaving this initializer pointing
        # at a missing file. Pro users hitting this path without a
        # `display.background` in settings would have had their identifier
        # silently stuck at "stone_05" while the pixmap fell back to stone_01.
        self.background_identifier = "stone_01"  # Default background identifier
        self.background_pixmap = None  # Cached scaled background
        self.background_cache = {}  # Cache for all loaded backgrounds

        # Grid visibility (OFF by default - backgrounds have grid lines)
        self.show_grid = False

        # Ascendant effect settings (element-themed glow)
        # Disabled by default - only enabled explicitly in Testing tab
        self.ascendant_effect_settings = {
            "enabled": False,
            "effect_type": "Element Glow",
            "opacity": 0.7,      # Alpha transparency (0.0 to 1.0)
            "spread": 30,        # How far glow extends beyond shape (px)
            "size": 1.0          # Size ratio (0.3 to 1.5, 1.0 = cell size)
        }

        # House effect settings (5th and 9th house glows)
        self.house_effect_settings = {
            5: {"enabled": False, "effect_type": "Element Glow", "opacity": 0.5, "spread": 20, "size": 0.8, "offset_x": 0, "offset_y": 0},
            9: {"enabled": False, "effect_type": "Element Glow", "opacity": 0.5, "spread": 20, "size": 0.8, "offset_x": 0, "offset_y": 0}
        }

        # Icon caches
        self.zodiac_icons = {}
        self.planet_icons = {}

        # Planet data — Chart-first (Issue 20)
        self._chart = None
        self._varga_code = None
        self._planets = None  # dict of planet objects from rashi/varga
        self._cusps = None    # cusps from rashi/varga
        self._has_chart = False
        # Deprecated — kept for set_planets_data() compat until Issue 11
        self.planets_data = None
        self.aditya_mode = "aditya"
        self.ayanamsa_offset = 0.0

        # Sign name display: False = Aditya names (Dhata...), True = Western names (Aries...)
        # Only affects label display, not calculations
        self.use_western_names = False
        self.sign_language = "en"
        self.show_planet_names = False

        # Outer planets toggle (Uranus, Neptune, Pluto)
        self.show_outer_planets = True  # Default ON - matches previous behavior

        # Ascendant override for "Sign as Ascendant" feature (F4)
        # None = use actual birth Ascendant, 0-11 = use that sign index as Ascendant
        self.ascendant_override = None

        # Transit overlay state (set by mediator via update_transit_overlay)
        self._transit_overlay_active = False
        self._transit_manager = None
        self._mini_transit_si_view = None

        # Hover system - preview stays until user hovers different cell
        self.hover_signal = HoverSignal()
        if self.center_box_enabled:
            self.hover_signal.hover_enter.connect(self._show_center_preview)
        # Note: hover_leave not connected - preview persists until next cell hover

        # Planet click system
        self.planet_click_signal = PlanetClickSignal()
        # Dialog connection will be set by parent

        # Sign click system (for variation selection)
        self.sign_click_signal = SignClickSignal()
        # Dialog connection will be set by parent

        # Zodiac icon variation settings (per sign)
        self.variation_settings = self._load_variation_settings()

        # Planet icon variation settings (per planet)
        self.planet_variation_settings = self._load_planet_variation_settings()

        # Center preview tracking (no Python list - use Qt's item tagging)
        self.current_hover_sign = None

        # Time adjust mode - when True, disable center preview (time adjustment overlay uses center)
        self.time_adjust_mode = False

        # Z6b sign-selector state — drives center-box mode.
        # None = Mode 1 (hover preview). 1..12 = Mode 2 (mini North Indian).
        self.selected_z6b_sign = None

        # Lazy off-screen NorthIndianView used as the rendering source for
        # Mode 2 (the mini chart in the 2x2 center). Created on first use,
        # reused thereafter. We render its scene to a pixmap rather than
        # embedding the QGraphicsView itself — embedding via
        # QGraphicsProxyWidget gives flaky sizing inside another QGraphicsView.
        self._mini_north_indian_view = None

        # REMOVED: All reference lists caused dual ownership with Qt scene
        # Qt's scene owns items via parent-child hierarchy - no Python lists needed
        # Keeping Python references causes double-deletion during cleanup

        # Load initial background
        self._load_background(self.background_identifier)

        # Load chart display settings from app_settings.json
        self.display_settings = self._load_display_settings()

    def resizeEvent(self, event):
        """Handle resize event."""
        super().resizeEvent(event)

    def set_time_adjust_mode(self, enabled):
        """
        Set time adjust mode - when enabled, both center modes are disabled.

        Args:
            enabled: True to suppress Mode 1 (hover preview) and Mode 2
                     (mini North Indian) for the time-adjustment overlay.
        """
        self.time_adjust_mode = enabled
        if enabled:
            self._hide_center_preview()
            self._hide_mini_north_indian()
            self._hide_transit_overlay()
            self.current_hover_sign = None
        else:
            if self._transit_overlay_active and self._transit_manager:
                self._show_transit_overlay(self._transit_manager)
            elif self.selected_z6b_sign is not None:
                self._show_mini_north_indian(self.selected_z6b_sign - 1)

    def _compute_fit_zoom(self):
        """Return zoom factor that fits the full chart in the current viewport."""
        vp = self.viewport().size()
        side = min(vp.width(), vp.height())
        if side < 100:
            return 0.45  # viewport not laid out yet — safe fallback
        return max(self.min_zoom, min(self.max_zoom, side / self.chart_size * 0.92))

    def _apply_fit_zoom(self):
        """Deferred auto-fit — runs after Qt event loop processes layout (viewport size valid)."""
        if self._fit_zoom_applied:
            return
        self._fit_zoom_applied = True
        self.zoom_factor = self._compute_fit_zoom()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.chart_size / 2, self.chart_size / 2)

    def showEvent(self, event):
        """On first show: defer auto-fit via timer (layout not done yet at showEvent time).
        On subsequent shows (tab switch): re-apply current user zoom."""
        super().showEvent(event)
        if not self._fit_zoom_applied:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._apply_fit_zoom)
        else:
            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)
            self.centerOn(self.chart_size / 2, self.chart_size / 2)

    def wheelEvent(self, event):
        """Handle scroll wheel / touchpad scroll for zooming.

        Works correctly on X11, Wayland, Windows, and macOS:
        - Uses pixelDelta() on macOS (angleDelta is synthetic/large there)
        - Filters kinetic momentum events on Wayland so zoom stops with the gesture
        - Exponential formula: two half-clicks == one full click (commutative)
        - Mouse wheel (delta=120): identical zoom step as before
        Use +/- keyboard shortcuts as an additional touchpad zoom alternative.
        """
        # Ignore kinetic deceleration after finger lift (Wayland/libinput)
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            event.accept()
            return

        # Prefer pixelDelta on macOS — angleDelta is large and synthetic there
        if event.hasPixelDelta():
            raw = event.pixelDelta().y()
            if raw == 0:
                event.accept()
                return
            # pixelDelta is in screen pixels — use sensitivity factor, not /120
            # tune PIXEL_SENSITIVITY to taste; 0.02 ≈ smooth trackpad feel
            steps = raw * 0.02
        else:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            steps = delta / 120.0

        # Respect OS-level scroll direction inversion (macOS natural scrolling off)
        if event.isInverted():
            steps = -steps

        # Exponential formula: zoom_step ** steps
        # Ensures two delta=60 events == one delta=120 event (commutative)
        step = self.zoom_step ** abs(steps)

        if steps > 0:
            new_zoom = self.zoom_factor * step
        else:
            new_zoom = self.zoom_factor / step

        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if new_zoom != self.zoom_factor:
            # Cursor-anchored zoom: scale by delta factor with AnchorUnderMouse
            # so Qt keeps the scene point under the cursor stationary.
            factor = new_zoom / self.zoom_factor
            self.zoom_factor = new_zoom
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        event.accept()

    def zoom_in(self):
        """Zoom in by one step."""
        new_zoom = min(self.zoom_factor * self.zoom_step, self.max_zoom)
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)

    def zoom_out(self):
        """Zoom out by one step."""
        new_zoom = max(self.zoom_factor / self.zoom_step, self.min_zoom)
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)

    def reset_zoom(self):
        """Reset zoom to fit the full chart in the current viewport."""
        self.zoom_factor = self._compute_fit_zoom()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.chart_size / 2, self.chart_size / 2)

    def keyPressEvent(self, event):
        """Keyboard zoom shortcuts: +/= zoom in, - zoom out, 0 reset."""
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
            event.accept()
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_out()
            event.accept()
        elif event.key() == Qt.Key.Key_0:
            self.reset_zoom()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _load_display_settings(self) -> dict:
        """Load chart display settings from app_settings.json

        Returns settings dict with defaults for any missing values.
        Settings control positions of all chart elements.
        """
        try:
            settings = get_settings()
            return settings.get_chart_display()
        except Exception as e:
            print(f"[CHART] Warning: Could not load display settings: {e}")
            # Return sensible defaults matching original hardcoded values
            return {
                "shadow": {
                    "enabled": True, "blur_radius": 12, "offset_x": 4, "offset_y": 4,
                    "color": "#000000", "opacity": 120
                },
                "sign_label": {"offset_x": 20, "offset_y": 12},
                "sign_icon": {"offset_x": 20, "offset_y": 20},
                "planets": {"vertical_position": 58, "horizontal_padding": 40},
                "planet_text": {"abbrev_offset_y": 4, "degrees_offset_y": 28},
                "lagna_strip": {"offset_x": 5, "offset_y": 5},
                "planet_sizes": {
                    "Sun": 160, "Moon": 200, "Mars": 160, "Mercury": 160,
                    "Jupiter": 160, "Venus": 128, "Saturn": 160,
                    "Rahu": 128, "Ketu": 128, "Uranus": 100, "Neptune": 100, "Pluto": 100
                }
            }

    def reload_display_settings(self):
        """Reload display settings and redraw chart

        Call this when settings are changed in the Chart Display settings tab.
        Also reloads icon variation settings (zodiac_icons, planet_icons).
        """
        self.display_settings = self._load_display_settings()

        # Also reload variation settings (for icon model changes)
        self.variation_settings = self._load_variation_settings()
        self.planet_variation_settings = self._load_planet_variation_settings()

        # Clear caches to force reload with new settings
        self.zodiac_icons.clear()
        self.planet_icons.clear()

        if self._chart:
            self.draw_full_chart()

    def mousePressEvent(self, event):
        """Handle mouse press - always start panning (single click never opens dialogs)"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open planet/sign info dialogs.

        Single click is always pan. Double click on a planet or zodiac sign
        opens the info dialog. This prevents the 'stuck pan mode' bug that
        occurred when modal dialogs blocked mouseReleaseEvent.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.items(event.pos()):
                if isinstance(item, ClickablePlanetItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.planet_name, item.planet_info)
                    event.accept()
                    return
                elif isinstance(item, ClickableZodiacItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.zodiac_index, item.current_variation)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for cursor updates"""
        super().mouseMoveEvent(event)

        if not self._is_dragging:
            found_clickable = any(
                isinstance(item, (ClickablePlanetItem, ClickableZodiacItem))
                for item in self.items(event.pos())
            )
            if found_clickable:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to restore cursor"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            found_clickable = any(
                isinstance(item, (ClickablePlanetItem, ClickableZodiacItem))
                for item in self.items(event.pos())
            )
            if not found_clickable:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    # =========================================================================
    # HIGH-DPI SUPPORT
    # =========================================================================

    def _get_dpr(self):
        """Get device pixel ratio for high-DPI display support.

        Returns devicePixelRatio (e.g., 2.0 for Retina displays, 1.0 for standard).
        This ensures images render at physical resolution, not logical resolution.
        """
        # Try widget's devicePixelRatio first (most accurate)
        if hasattr(self, 'devicePixelRatio'):
            return self.devicePixelRatio()

        # Fallback to screen's devicePixelRatio
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            return screen.devicePixelRatio()

        return 1.0  # Standard DPI fallback

    def _scale_image_hidpi(self, qimage, target_width, target_height):
        """Scale QImage for high-DPI displays and return QPixmap.

        This is the key method for crisp images on Retina/4K displays.

        Args:
            qimage: Source QImage to scale
            target_width: Logical width in device-independent pixels
            target_height: Logical height in device-independent pixels

        Returns:
            QPixmap scaled to physical pixels with devicePixelRatio set
        """
        dpr = self._get_dpr()

        # Scale to physical pixels (e.g., 64x64 logical → 128x128 physical on Retina)
        physical_width = int(target_width * dpr)
        physical_height = int(target_height * dpr)

        # Scale QImage to physical resolution
        scaled_image = qimage.scaled(
            physical_width, physical_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Convert to QPixmap and set devicePixelRatio
        pixmap = QPixmap.fromImage(scaled_image)
        pixmap.setDevicePixelRatio(dpr)

        return pixmap

    def _load_background(self, bg_identifier):
        """
        Load background image using Qt best practices for quality.

        IMPORTANT: Do NOT use HiDPI scaling here because fitInView() is used.
        fitInView() applies a view transform that re-scales everything.
        If we also use setDevicePixelRatio(), the image gets scaled TWICE
        which causes pixelation (double interpolation).

        Instead: Load at LOGICAL scene size and let fitInView() +
        SmoothPixmapTransform handle the final scaling smoothly.

        Args:
            bg_identifier: Background identifier (e.g., "celestial_01") or legacy int (1-10)
        """
        # Handle legacy int format for backwards compatibility
        if isinstance(bg_identifier, int):
            bg_identifier = f"celestial_{bg_identifier:02d}"

        # Cache key
        cache_key = bg_identifier

        if cache_key in self.background_cache:
            self.background_pixmap = self.background_cache[cache_key]
            return

        # Use glob pattern to find matching file: {category}_{number}_*.webp
        # Example: celestial_01_moon_surface.webp matches pattern "celestial_01_*.webp"
        pattern = f"{bg_identifier}_*.webp"
        matching_files = list(BACKGROUNDS_PATH.glob(pattern))

        qimage = None
        if matching_files:
            # Use first matching file
            path = matching_files[0]
            # Step 1: Load with QImage (best for I/O)
            qimage = QImage(str(path))

        if qimage and not qimage.isNull():
            # Step 2: Scale to LOGICAL scene size (no HiDPI - fitInView handles scaling)
            logical_size = self.chart_size

            scaled_image = qimage.scaled(
                logical_size, logical_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # Crop to exact logical size if needed
            if scaled_image.width() > logical_size or scaled_image.height() > logical_size:
                x_offset = (scaled_image.width() - logical_size) // 2
                y_offset = (scaled_image.height() - logical_size) // 2
                scaled_image = scaled_image.copy(
                    x_offset, y_offset,
                    logical_size, logical_size
                )

            # Step 3: Convert to QPixmap - NO setDevicePixelRatio!
            # fitInView + SmoothPixmapTransform will handle display scaling
            pixmap = QPixmap.fromImage(scaled_image)

            self.background_cache[cache_key] = pixmap
            self.background_pixmap = pixmap
        else:
            print(f"Warning: Could not load background '{bg_identifier}' from {BACKGROUNDS_PATH}")
            # Fall back to a background that is guaranteed to exist in Core.
            # Historical note: this used to fall back to `stone_05`, but that
            # file was removed from the Core asset set during the public
            # release cleanup (2026-04-08). `stone_01` is the light-theme
            # lock and is guaranteed present in both Core and Pro.
            if bg_identifier != "stone_01":
                print(f"Falling back to default background 'stone_01'")
                self._load_background("stone_01")
            else:
                self.background_pixmap = None

    def set_background(self, bg_identifier):
        """
        Change background image and redraw chart.

        Args:
            bg_identifier: Background identifier (e.g., "celestial_01") or legacy int (1-10)
        """
        # Handle legacy int format
        if isinstance(bg_identifier, int):
            bg_identifier = f"celestial_{bg_identifier:02d}"

        self.background_identifier = bg_identifier
        self._load_background(bg_identifier)
        # Note: callers must call draw_full_chart() explicitly if needed.
        # Background is stored in self.background_pixmap for next draw.

    def get_background(self):
        """Get current background identifier."""
        return self.background_identifier

    # =========================================================================
    # VARIATION SETTINGS (load/save to settings.json)
    # =========================================================================

    def _load_variation_settings(self):
        """Load zodiac icon variation settings from settings.json

        Format in settings.json:
        {
            "zodiac_icons": {
                "Aries": 1,
                "Taurus": 2,
                ...
            }
        }
        """
        settings_path = _get_settings_path()
        try:
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    return settings.get('zodiac_icons', {})
        except Exception as e:
            print(f"Warning: Could not load variation settings: {e}")
        return {}

    def _save_variation_settings(self):
        """Save zodiac icon variation settings to settings.json"""
        settings_path = _get_settings_path()
        try:
            # Load existing settings
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)

            # Update zodiac_icons section
            settings['zodiac_icons'] = self.variation_settings

            # Save back
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=4)

        except Exception as e:
            print(f"Error saving variation settings: {e}")

    def get_selected_variation(self, zodiac_index):
        """Get the selected variation number for a zodiac sign

        Args:
            zodiac_index: 0-11 (Dhata to Parjanya)

        Returns:
            int: Variation number (1 if not set)
        """
        western_name = self.WESTERN_NAMES[zodiac_index]
        return self.variation_settings.get(western_name, 1)

    def set_selected_variation(self, zodiac_index, variation_num):
        """Set the selected variation for a zodiac sign and refresh

        Args:
            zodiac_index: 0-11 (Dhata to Parjanya)
            variation_num: Variation number to use
        """
        western_name = self.WESTERN_NAMES[zodiac_index]
        self.variation_settings[western_name] = variation_num

        # Save to file
        self._save_variation_settings()

        # DON'T clear caches - let draw_full_chart() handle it naturally
        # Cache keys include variation number, so old variations won't be reused

        # Redraw chart (will load new variation from disk, cache it)
        self.draw_full_chart()

        # Force Qt to process all pending deletions before returning
        # This ensures any deleteLater() calls from scene.clear() are fully processed
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    # =========================================================================
    # PLANET VARIATION SETTINGS
    # =========================================================================

    def _load_planet_variation_settings(self):
        """Load planet icon variation settings from settings.json

        Format in settings.json:
        {
            "planet_icons": {
                "Sun": 1,
                "Moon": 2,
                ...
            }
        }
        """
        settings_path = _get_settings_path()
        try:
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    return settings.get('planet_icons', {})
        except Exception as e:
            print(f"Warning: Could not load planet variation settings: {e}")
        return {}

    def _save_planet_variation_settings(self):
        """Save planet icon variation settings to settings.json"""
        settings_path = _get_settings_path()
        try:
            # Load existing settings
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)

            # Update planet_icons section
            settings['planet_icons'] = self.planet_variation_settings

            # Save back
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=4)

        except Exception as e:
            print(f"Error saving planet variation settings: {e}")

    def get_planet_variation(self, planet_name):
        """Get the selected variation number for a planet

        Args:
            planet_name: "Sun", "Moon", "Mars", etc.

        Returns:
            int: Variation number (1 if not set)
        """
        return self.planet_variation_settings.get(planet_name, 1)

    def set_planet_variation(self, planet_name, variation_num):
        """Set the selected variation for a planet and refresh

        Args:
            planet_name: "Sun", "Moon", "Mars", etc.
            variation_num: Variation number to use
        """
        self.planet_variation_settings[planet_name] = variation_num

        # Save to file
        self._save_planet_variation_settings()

        # Redraw chart (cache keys include variation, old won't be reused)
        self.draw_full_chart()

        # Force Qt to process all pending deletions
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def draw_empty_grid(self):
        """Draw 4x4 grid with diagonal in center"""
        # Trust Qt's scene.clear() to handle all cleanup automatically
        # Manual cleanup of parent-child relationships interferes with Qt's internal state
        self.scene.clear()

        # Background - use image if available, fallback to solid color
        if self.background_pixmap:
            bg_item = QGraphicsPixmapItem(self.background_pixmap)
            bg_item.setZValue(-10)  # Behind everything
            self.scene.addItem(bg_item)
        else:
            self.scene.setBackgroundBrush(QBrush(self.bg_color))

        # Grid lines (optional - backgrounds usually have them)
        if self.show_grid:
            pen = QPen(self.grid_color)
            pen.setWidth(2)

            # Draw vertical lines
            for i in range(5):
                x = i * self.cell_size
                self.scene.addLine(x, 0, x, self.chart_size, pen)

            # Draw horizontal lines
            for i in range(5):
                y = i * self.cell_size
                self.scene.addLine(0, y, self.chart_size, y, pen)

            # Draw center diagonals (2x2 center area)
            center_start = self.cell_size
            center_end = self.cell_size * 3

            # Top-left to bottom-right diagonal
            self.scene.addLine(center_start, center_start, center_end, center_end, pen)

            # Top-right to bottom-left diagonal
            self.scene.addLine(center_end, center_start, center_start, center_end, pen)

    def set_show_grid(self, show):
        """Toggle grid line visibility and redraw"""
        self.show_grid = show
        self.draw_full_chart()

    def load_zodiac_icon(self, zodiac_index, size=64):
        """Load zodiac icon using Qt best practices for quality

        IMPORTANT: Do NOT use HiDPI scaling here because fitInView() is used.
        fitInView() applies a view transform that re-scales everything.
        If we also use setDevicePixelRatio(), the image gets scaled TWICE
        which causes pixelation (double interpolation).

        Instead: Load at a larger LOGICAL size and let fitInView() +
        SmoothPixmapTransform handle the final scaling smoothly.

        Source: 2048×2048 originals for maximum quality when scaling down
        Uses selected variation from settings (e.g., Leo1.png, Leo2.png, Leo3.png)
        """
        # Get selected variation for this sign
        variation = self.get_selected_variation(zodiac_index)

        # Cache key - NO DPR since we're not using HiDPI here
        cache_key = f"zodiac_{zodiac_index}_v{variation}_{size}"

        if cache_key in self.zodiac_icons:
            return self.zodiac_icons[cache_key]

        western_name = self.WESTERN_NAMES[zodiac_index]

        # Try the selected variation (e.g. Leo3.webp for variation 3).
        icon_path = PROJECT_ROOT / f"img/sign/{western_name}{variation}.webp"
        if not icon_path.exists():
            # Fallback to variation 1 if the selected variation doesn't exist.
            # Core always ships {Sign}1.webp for every sign (the single default
            # the 2026-04-08 cleanup kept), so this fallback is guaranteed to
            # succeed in a healthy Core build. The proprietary edition may
            # add more variants via an overlay path; see the variation system
            # rebuild TODO in the proprietary tree.
            icon_path = PROJECT_ROOT / f"img/sign/{western_name}1.webp"

        if not icon_path.exists():
            print(f"Warning: Icon not found for {western_name}")
            return None

        # Step 1: Load with QImage (best for I/O)
        qimage = QImage(str(icon_path))
        if qimage.isNull():
            print(f"Warning: Failed to load image: {icon_path}")
            return None

        # Step 2: Scale to LOGICAL size (no HiDPI - fitInView handles scaling)
        # Use larger size for quality - fitInView will scale down smoothly
        qimage = qimage.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Step 3: Convert to QPixmap - NO setDevicePixelRatio!
        # fitInView + SmoothPixmapTransform will handle display scaling
        pixmap = QPixmap.fromImage(qimage)

        self.zodiac_icons[cache_key] = pixmap
        return pixmap

    def add_zodiac_label(self, row, col, zodiac_idx):
        """Add sign name label at top-left corner of inner content box

        Labels are positioned inside the inner content area of each cell,
        accounting for decorative frames that vary by row/column position.
        User offsets provide fine-tuning relative to the inner box edge.

        Position structure:
            label_pos = cell_start + inner_box_offset + user_offset

        Where inner_box_offset varies by row/col to handle frame asymmetry:
            - Row 0 (top): moderate offset (outer image edge)
            - Row 3 (bottom): smaller offset (visual balance)
            - Edge columns: slightly larger X offset

        Sign names switch between Aditya (Dhata, Aryama...) and Western (Aries, Taurus...)
        based on self.use_western_names flag. Western names localized via displayed_sign_name() based on sign_language setting.
        """
        # Choose name list based on mode + toggle state
        sign_name = displayed_sign_name(zodiac_idx, self.aditya_mode,
                                        self.use_western_names,
                                        self.sign_language)

        # Keep aditya_name for offset lookups (offsets are calibrated for Aditya names)
        aditya_name = self.ADITYA_NAMES[zodiac_idx]

        # Cell boundaries (512px grid)
        cell_x = col * self.cell_size
        cell_y = row * self.cell_size

        # Inner box position (accounts for decorative frame variations)
        # Row 0 has thinner top frame, Row 3 needs less offset for visual balance
        inner_box_x = cell_x + self.INNER_BOX_X_OFFSET.get(col, 55)
        inner_box_y = cell_y + self.INNER_BOX_Y_OFFSET.get(row, 55)

        # Get sign_label style settings (includes user offsets, font, outline, background)
        sign_label_settings = self.display_settings.get("sign_label", {})

        # Global user offsets (relative to inner box edge)
        global_offset_x = sign_label_settings.get("offset_x", 8)
        global_offset_y = sign_label_settings.get("offset_y", 5)

        # Per-sign BASE offset — use per-background preset if available,
        # otherwise fall back to hardcoded class constant
        bg_preset = BACKGROUND_PRESETS.get(self.background_identifier, {})
        preset_offsets = bg_preset.get('sign_label_base_offset', None)
        if preset_offsets and aditya_name in preset_offsets:
            base_offset = preset_offsets[aditya_name]
        else:
            base_offset = self.SIGN_LABEL_BASE_OFFSET.get(aditya_name, (0, 0))
        base_offset_x, base_offset_y = base_offset

        # Per-sign SETTINGS offset (for further fine-tuning, defaults to 0)
        sign_label_offsets = self.display_settings.get("sign_label_offsets", {})
        per_sign_enabled = sign_label_offsets.get("enabled", False)

        per_sign_offset_x = 0
        per_sign_offset_y = 0
        if per_sign_enabled and aditya_name in sign_label_offsets:
            sign_offset = sign_label_offsets[aditya_name]
            per_sign_offset_x = sign_offset.get("offset_x", 0)
            per_sign_offset_y = sign_offset.get("offset_y", 0)

        # Get text color from settings (for backwards compatibility)
        text_colors = self.display_settings.get("text_colors", {})
        sign_label_color = text_colors.get("sign_label", "#DAA520")  # Default gold

        # Final position = inner box + global offset + base offset + settings adjustment
        x = inner_box_x + global_offset_x + base_offset_x + per_sign_offset_x
        y = inner_box_y + global_offset_y + base_offset_y + per_sign_offset_y

        # Draw with styled text (font, outline, background all customizable)
        self._draw_styled_text(sign_name, x, y, sign_label_settings,
                               QColor(sign_label_color), z_value=10)

    def _create_shadow_effect(self, blur_radius=None, offset_x=None, offset_y=None,
                               color=None, opacity=None, planet_name=None):
        """Create a drop shadow effect for icons using Chart Display settings.

        Delegates to the shared planet_shadow factory which reads from
        app_settings.json -> chart_display -> shadow (with per-planet overrides).

        Signature kept for backwards compatibility — callers pass various kwargs.

        IMPORTANT: After calling setGraphicsEffect(), delete the Python reference
        to avoid a Qt/Python dual-ownership crash. Qt takes ownership of the
        effect and will free it; if Python also holds a reference, the
        eventual Python deletion triggers a double-free at the C++ layer.
        """
        from apps.widgets.planet_shadow import create_planet_shadow
        return create_planet_shadow(planet_name=planet_name)

    def _create_text_shadow_effect(self):
        """Create a drop shadow effect for text elements using Chart Display settings.

        Separate from icon shadows to allow independent control of text readability.
        """
        text_shadow_settings = self.display_settings.get("text_shadow", {})

        # Check if text shadows are enabled
        if not text_shadow_settings.get("enabled", False):
            return None

        blur = text_shadow_settings.get("blur_radius", 4)
        off_x = text_shadow_settings.get("offset_x", 2)
        off_y = text_shadow_settings.get("offset_y", 2)
        color_hex = text_shadow_settings.get("color", "#000000")
        alpha = text_shadow_settings.get("opacity", 150)

        shadow_color = QColor(color_hex)
        shadow_color.setAlpha(alpha)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(blur)
        shadow.setOffset(off_x, off_y)
        shadow.setColor(shadow_color)
        return shadow

    def _create_element_shadow_effect(self, zodiac_idx):
        """Create element-colored shadow for a sign icon based on zodiac index.

        Fire signs (Dhata=0, Indra=4, Amzu=8) get red shadow
        Earth signs (Aryama=1, Vivasvan=5, Bhaga=9) get brown shadow
        Air signs (Mitra=2, Tvasta=6, Pusha=10) get green shadow
        Water signs (Varuna=3, Vishnu=7, Parjanya=11) get blue shadow

        Element shadows have their own blur/offset/opacity settings.
        """
        element_settings = self.display_settings.get("element_shadows", {})

        # If element shadows not enabled, return regular shadow
        if not element_settings.get("enabled", False):
            return self._create_shadow_effect()

        # Determine element from zodiac index
        element_map = {
            0: "fire", 1: "earth", 2: "air", 3: "water",
            4: "fire", 5: "earth", 6: "air", 7: "water",
            8: "fire", 9: "earth", 10: "air", 11: "water"
        }
        element = element_map.get(zodiac_idx, "fire")

        # Get element color
        default_colors = {
            'fire': '#FF4444', 'earth': '#8B4513',
            'air': '#44FF44', 'water': '#4444FF'
        }
        color_hex = element_settings.get(element, default_colors[element])

        # Use element shadow's own settings for blur/offset/opacity
        blur = element_settings.get("blur_radius", 12)
        off_x = element_settings.get("offset_x", 4)
        off_y = element_settings.get("offset_y", 4)
        alpha = element_settings.get("opacity", 120)

        shadow_color = QColor(color_hex)
        shadow_color.setAlpha(alpha)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(blur)
        shadow.setOffset(off_x, off_y)
        shadow.setColor(shadow_color)
        return shadow

    def draw_chart_with_icons(self):
        """Draw grid with zodiac icons

        Matches original CustomTkinter layout:
        - Aditya name: top-LEFT corner of each cell
        - Zodiac icon: top-RIGHT corner of each cell (CLICKABLE for variation dialog)
        - House number: bottom-LEFT corner (Whole Sign Houses)
        Same simple pattern for ALL 12 cells.
        Positions are customizable via Chart Display settings.
        """
        self.draw_empty_grid()

        # Reset hover state (no list to clear - items managed by scene)
        self.current_hover_sign = None

        # Get sign icon position offsets from settings (defaults: 20, 20)
        sign_icon_settings = self.display_settings.get("sign_icon", {})
        icon_offset_x = sign_icon_settings.get("offset_x", 20)
        icon_offset_y = sign_icon_settings.get("offset_y", 20)

        for (row, col), zodiac_idx in self.ZODIAC_POSITIONS.items():
            # Cell boundaries
            x1 = col * self.cell_size
            y1 = row * self.cell_size
            x2 = x1 + self.cell_size
            y2 = y1 + self.cell_size

            # Get current variation for this sign
            current_variation = self.get_selected_variation(zodiac_idx)

            # Load zodiac icon (192px for 512px cells)
            pixmap = self.load_zodiac_icon(zodiac_idx, size=192)
            if pixmap:
                # Use ClickableZodiacItem for variation selection
                icon_item = ClickableZodiacItem(
                    pixmap, zodiac_idx, current_variation, self.sign_click_signal
                )
                # Position at top-right corner (customizable via settings)
                icon_x = x2 - icon_offset_x - pixmap.width()
                icon_y = y1 + icon_offset_y
                icon_item.setPos(icon_x, icon_y)

                # Apply shadow effect (element-colored if enabled, else regular shadow)
                # Rule #18: del after setGraphicsEffect to avoid Qt/Python ownership crash
                shadow_effect = self._create_element_shadow_effect(zodiac_idx)
                if shadow_effect:
                    icon_item.setGraphicsEffect(shadow_effect)
                    del shadow_effect  # Release Python reference - Qt owns it now

                self.scene.addItem(icon_item)
                # Qt scene owns this item - no Python reference needed

            # Add Aditya name at top-left
            self.add_zodiac_label(row, col, zodiac_idx)

            # === Draw house number in bottom-left corner (if enabled) ===
            house_settings = self.display_settings.get('house_number', {})
            if house_settings.get('enabled', True):
                try:
                    house_number = self.get_house_number_for_sign(zodiac_idx)
                    if house_number:
                        aditya_name = self.ADITYA_NAMES[zodiac_idx]
                        self._draw_house_number(x1, y1, x2, y2, house_number, aditya_name)
                except Exception as e:
                    print(f"[CHART] Warning: Could not draw house number for cell ({row},{col}): {e}")

            # === Draw Campanus house cusps in bottom-right corner ===
            try:
                self._draw_house_cusps(x1, y1, x2, y2, zodiac_idx)
            except Exception as e:
                print(f"[CHART] Warning: Could not draw house cusps for cell ({row},{col}): {e}")

        if self.center_box_enabled:
            self._create_hover_zones()

    def load_planet_image(self, planet_name, size=48):
        """Load planet image using Qt best practices for quality

        IMPORTANT: Do NOT use HiDPI scaling here because fitInView() is used.
        fitInView() applies a view transform that re-scales everything.
        If we also use setDevicePixelRatio(), the image gets scaled TWICE
        which causes pixelation (double interpolation).

        Instead: Load at LOGICAL size and let fitInView() +
        SmoothPixmapTransform handle the final scaling smoothly.

        Supports variations: sun.png, sun2.png, sun3.png, etc.
        """
        # Get selected variation for this planet
        variation = self.get_planet_variation(planet_name)

        # Cache key includes variation
        cache_key = f"{planet_name}_v{variation}_{size}"

        if cache_key in self.planet_icons:
            return self.planet_icons[cache_key]

        icon_filename = self.PLANET_ICON_NAMES.get(planet_name, planet_name.lower())

        # Try variation-specific file first (e.g., sun2.png for variation 2)
        if variation > 1:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}{variation}.webp"
        else:
            # Variation 1 = default (no suffix)
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        # Fallback to default if variation doesn't exist
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            print(f"Warning: Planet icon not found: {icon_path}")
            self.planet_icons[cache_key] = None
            return None

        try:
            # Step 1: Load with QImage (best for I/O operations)
            qimage = QImage(str(icon_path))
            if qimage.isNull():
                print(f"Warning: Failed to load image: {icon_path}")
                self.planet_icons[cache_key] = None
                return None

            # Step 2: Scale to LOGICAL size (no HiDPI - fitInView handles scaling)
            qimage = qimage.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # Step 3: Convert to QPixmap - NO setDevicePixelRatio!
            # fitInView + SmoothPixmapTransform will handle display scaling
            pixmap = QPixmap.fromImage(qimage)

            self.planet_icons[cache_key] = pixmap
            return pixmap
        except Exception as e:
            print(f"Error loading planet image {planet_name}: {e}")
            self.planet_icons[cache_key] = None
            return None

    def set_planets_data(self, planets_data, aditya_mode="aditya", use_western_names=False, ayanamsa_offset=0.0):
        """Deprecated — use update_from_chart(). Kept until Issue 11."""
        self.planets_data = planets_data
        self.aditya_mode = aditya_mode
        self.use_western_names = use_western_names
        self.ayanamsa_offset = ayanamsa_offset

    def update_from_chart(self, chart, varga_code=None, use_western_names=False,
                          aditya_mode=None, **_kw):
        """Render from a libaditya Chart object (primary entry point)."""
        from libaditya.objects.context import Circle
        self._chart = chart
        self._varga_code = varga_code
        self._has_chart = True
        self.planets_data = True
        self.aditya_mode = aditya_mode or (
            "aditya" if chart.context.circle == Circle.ADITYA else "tropical_classic"
        )
        source = chart.varga(varga_code) if varga_code and varga_code != 1 else chart.rashi()
        self._planets = source.planets()
        self._cusps = source.cusps()
        self.use_western_names = use_western_names
        self.draw_full_chart()

    def ensure_visible(self):
        """Force viewport refresh to ensure chart is visible.

        Call this after loading a chart if it doesn't display correctly.
        Useful when the view might not have been fully initialized or visible.
        """
        self.scene.update()
        self.viewport().update()
        # Ensure proper zoom and centering
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.chart_size / 2, self.chart_size / 2)

    def refresh_theme(self):
        """Re-apply theme colors to the chart view (SPEC-THM-001 W1).

        Re-assigns the cached QColor objects (which were frozen at __init__)
        and triggers a full chart redraw so existing scene items pick up the
        new text/background colors. Pre-mortem P-002 + P-003 mitigation:
        QColor instances are cached and existing scene items do not respond
        to color changes unless redrawn.
        """
        theme = get_theme_colors()
        self.bg_color = QColor(theme["secondary_dark"])
        self.text_color = QColor(theme["secondary_text"])
        self.preview_bg_color = QColor(theme["secondary"])
        self.scene.setBackgroundBrush(QBrush(self.bg_color))
        # Redraw chart so existing planet/text items get new colors.
        if self._chart is not None:
            try:
                self.draw_full_chart()
            except Exception:
                # Best-effort: don't let a redraw failure crash theme switch.
                pass
        self.scene.update()
        self.viewport().update()

    def draw_full_chart(self):
        """Draw complete chart with icons and planets"""
        self.draw_chart_with_icons()

        if not self._chart:
            return

        # Draw ascendant element glow effect (if enabled)
        # Check both explicit settings (Testing tab) and display_settings (saved settings)
        asc_effect = self.ascendant_effect_settings.copy()
        if not asc_effect.get("enabled", False):
            # Fall back to display_settings if explicit settings not enabled
            # ALWAYS read fresh from display_settings (don't cache - allows slider updates)
            saved_effect = self.display_settings.get("ascendant_effect", {})
            if saved_effect.get("enabled", False):
                # Convert from saved format (percentage integers) to internal format (floats)
                asc_effect = {
                    "enabled": True,
                    "effect_type": saved_effect.get("effect_type", "Element Glow"),
                    "opacity": saved_effect.get("opacity", 70) / 100.0,
                    "spread": saved_effect.get("spread", 30),
                    "size": saved_effect.get("size", 100) / 100.0,
                    "offset_x": saved_effect.get("offset_x", 0),
                    "offset_y": saved_effect.get("offset_y", 0)
                }
                # Note: Don't cache to self.ascendant_effect_settings - must read fresh each time

        if asc_effect.get("enabled", False):
            self._draw_ascendant_element_glow(asc_effect)

        # Draw 5th and 9th house effects (if enabled)
        for house_num in [5, 9]:
            house_effect = self.house_effect_settings.get(house_num, {}).copy()
            if not house_effect.get("enabled", False):
                # Fall back to display_settings if explicit settings not enabled
                saved_key = f"house_{house_num}_effect"
                saved_effect = self.display_settings.get(saved_key, {})
                if saved_effect.get("enabled", False):
                    house_effect = {
                        "enabled": True,
                        "effect_type": saved_effect.get("effect_type", "Element Glow"),
                        "opacity": saved_effect.get("opacity", 50) / 100.0,
                        "spread": saved_effect.get("spread", 20),
                        "size": saved_effect.get("size", 80) / 100.0,
                        "offset_x": saved_effect.get("offset_x", 0),
                        "offset_y": saved_effect.get("offset_y", 0)
                    }
            if house_effect.get("enabled", False):
                self._draw_house_element_glow(house_num, house_effect)

        # Draw ascendant stripe indicator
        self._draw_ascendant_stripe()

        planets_by_sign = self._group_planets_by_sign()

        for zodiac_idx, planets_in_sign in planets_by_sign.items():
            self._draw_planets_in_sign(zodiac_idx, planets_in_sign)

        # Force viewport refresh to ensure chart displays immediately
        self.scene.update()
        self.viewport().update()

        if not self.center_box_enabled:
            pass
        elif self._transit_overlay_active and not self.time_adjust_mode \
                and self._transit_manager:
            self._show_transit_overlay(self._transit_manager)
        elif self.selected_z6b_sign is not None and not self.time_adjust_mode:
            self._show_mini_north_indian(self.selected_z6b_sign - 1)

    def set_ascendant_effect_settings(self, settings: dict):
        """Set ascendant effect settings for element-themed glow.

        Args:
            settings: Dict with keys:
                - enabled: bool
                - effect_type: str ("Element Glow", "Golden Aura", etc.)
                - opacity: float (0.0 to 1.0) - transparency/alpha
                - spread: int (pixels) - how far glow extends beyond shape
                - size: float (0.3 to 1.5) - size ratio (1.0 = cell size)
        """
        self.ascendant_effect_settings = settings

    def set_house_effect_settings(self, house_num: int, settings: dict):
        """Set effect settings for a specific house (5th or 9th).

        Args:
            house_num: House number (5 or 9)
            settings: Dict with keys:
                - enabled: bool
                - effect_type: str ("Element Glow", "Golden Aura", etc.)
                - opacity: float (0.0 to 1.0)
                - spread: int (pixels)
                - size: float (0.3 to 1.5)
                - offset_x: int (pixels)
                - offset_y: int (pixels)
        """
        if house_num in self.house_effect_settings:
            self.house_effect_settings[house_num] = settings

    def _draw_ascendant_element_glow(self, effect_settings: dict = None):
        """Draw element-themed glow effect around the Ascendant cell.

        Creates a visually striking glow that indicates both the Ascendant
        position and its elemental nature (Fire, Earth, Air, Water).

        Args:
            effect_settings: Dict with keys: enabled, effect_type, opacity, spread, size.
                             If None, falls back to self.ascendant_effect_settings.

        Note: Uses _get_effective_ascendant_sign_index() to support
        the F4 "Sign as Ascendant" override feature.
        """
        from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsEllipseItem
        from PySide6.QtGui import QRadialGradient

        if not self._chart:
            return

        sign_index = self._get_effective_ascendant_sign_index()

        cell_pos = None
        for (row, col), zidx in self.ZODIAC_POSITIONS.items():
            if zidx == sign_index:
                cell_pos = (row, col)
                break

        if not cell_pos:
            return

        row, col = cell_pos
        x1 = col * self.cell_size
        y1 = row * self.cell_size
        cell_center_x = x1 + self.cell_size / 2
        cell_center_y = y1 + self.cell_size / 2

        # Get element and colors
        element = self.ZODIAC_ELEMENT.get(sign_index, "fire")
        colors = self.ELEMENT_GLOW_COLORS.get(element, self.ELEMENT_GLOW_COLORS["fire"])

        # Get effect settings (prefer passed parameter, fall back to instance attribute)
        settings = effect_settings if effect_settings else self.ascendant_effect_settings
        opacity = settings.get("opacity", 0.7)
        spread = settings.get("spread", 30)
        size_ratio = settings.get("size", 1.0)
        effect_type = settings.get("effect_type", "Element Glow")
        offset_x = settings.get("offset_x", 0)
        offset_y = settings.get("offset_y", 0)

        # Apply offsets to center position
        cell_center_x += offset_x
        cell_center_y += offset_y

        # Calculate base size (can be smaller or larger than cell)
        base_radius = (self.cell_size / 2) * size_ratio
        # Calculate glow dimensions (spread adds to the base size)
        glow_radius = base_radius + spread
        inner_radius = base_radius - 20

        if effect_type == "Element Glow":
            # Create radial gradient glow
            gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius)

            # Inner color (element primary)
            inner_color = QColor(colors["primary"])
            inner_color.setAlphaF(opacity * 0.6)

            # Middle color (element glow)
            mid_color = QColor(colors["glow"])
            mid_color.setAlphaF(opacity * 0.4)

            # Outer color (fade to transparent)
            outer_color = QColor(colors["outer"])
            outer_color.setAlphaF(opacity * 0.15)

            transparent = QColor(0, 0, 0, 0)

            gradient.setColorAt(0.0, transparent)  # Center transparent
            gradient.setColorAt(0.5, inner_color)  # Inner glow
            gradient.setColorAt(0.7, mid_color)    # Mid glow
            gradient.setColorAt(0.85, outer_color) # Outer glow
            gradient.setColorAt(1.0, transparent)  # Edge fade

            # Draw glow ellipse
            glow_rect = QGraphicsEllipseItem(
                cell_center_x - glow_radius,
                cell_center_y - glow_radius,
                glow_radius * 2,
                glow_radius * 2
            )
            glow_rect.setBrush(QBrush(gradient))
            glow_rect.setPen(QPen(Qt.PenStyle.NoPen))
            glow_rect.setZValue(1)  # Behind everything else
            self.scene.addItem(glow_rect)

            # Add inner bright ring for emphasis (scales with size)
            ring_size = base_radius + 15
            ring_gradient = QRadialGradient(cell_center_x, cell_center_y, ring_size)
            ring_inner = QColor(colors["glow"])
            ring_inner.setAlphaF(opacity * 0.8)
            ring_outer = QColor(colors["primary"])
            ring_outer.setAlphaF(0)

            ring_gradient.setColorAt(0.85, ring_outer)
            ring_gradient.setColorAt(0.92, ring_inner)
            ring_gradient.setColorAt(1.0, ring_outer)

            ring_offset = ring_size - self.cell_size / 2
            inner_ring = QGraphicsEllipseItem(
                x1 - ring_offset, y1 - ring_offset,
                self.cell_size + ring_offset * 2, self.cell_size + ring_offset * 2
            )
            inner_ring.setBrush(QBrush(ring_gradient))
            inner_ring.setPen(QPen(Qt.PenStyle.NoPen))
            inner_ring.setZValue(2)
            self.scene.addItem(inner_ring)

        elif effect_type == "Golden Aura":
            # Golden glow regardless of element
            gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius)

            gold_inner = QColor("#FFD700")
            gold_inner.setAlphaF(opacity * 0.5)
            gold_mid = QColor("#FFA500")
            gold_mid.setAlphaF(opacity * 0.3)
            transparent = QColor(0, 0, 0, 0)

            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(0.6, gold_inner)
            gradient.setColorAt(0.85, gold_mid)
            gradient.setColorAt(1.0, transparent)

            glow_rect = QGraphicsEllipseItem(
                cell_center_x - glow_radius,
                cell_center_y - glow_radius,
                glow_radius * 2,
                glow_radius * 2
            )
            glow_rect.setBrush(QBrush(gradient))
            glow_rect.setPen(QPen(Qt.PenStyle.NoPen))
            glow_rect.setZValue(1)
            self.scene.addItem(glow_rect)

        elif effect_type == "Double Border":
            # Draw double border around cell (scales with size)
            border_color = QColor(colors["glow"])
            border_color.setAlphaF(opacity)

            # Calculate border offsets based on size ratio
            size_offset = (self.cell_size / 2) * (1 - size_ratio)
            outer_offset = 12 * size_ratio
            inner_offset = 4 * size_ratio

            pen = QPen(border_color)
            pen.setWidth(int(8 * size_ratio))

            # Outer border
            outer_rect = QGraphicsRectItem(
                x1 + size_offset - outer_offset,
                y1 + size_offset - outer_offset,
                self.cell_size * size_ratio + outer_offset * 2,
                self.cell_size * size_ratio + outer_offset * 2
            )
            outer_rect.setPen(pen)
            outer_rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            outer_rect.setZValue(2)
            self.scene.addItem(outer_rect)

            # Inner border
            pen.setWidth(int(4 * size_ratio))
            inner_rect = QGraphicsRectItem(
                x1 + size_offset - inner_offset,
                y1 + size_offset - inner_offset,
                self.cell_size * size_ratio + inner_offset * 2,
                self.cell_size * size_ratio + inner_offset * 2
            )
            inner_rect.setPen(pen)
            inner_rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            inner_rect.setZValue(2)
            self.scene.addItem(inner_rect)

        elif effect_type == "Radiant Burst":
            # Sunburst rays radiating from the cell center
            import math
            ray_color = QColor(colors["glow"])
            ray_color.setAlphaF(opacity * 0.7)

            # Outer glow first (soft background)
            outer_gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius * 1.2)
            outer_glow = QColor(colors["primary"])
            outer_glow.setAlphaF(opacity * 0.25)
            transparent = QColor(0, 0, 0, 0)
            outer_gradient.setColorAt(0.4, transparent)
            outer_gradient.setColorAt(0.7, outer_glow)
            outer_gradient.setColorAt(1.0, transparent)

            glow_ellipse = QGraphicsEllipseItem(
                cell_center_x - glow_radius * 1.2,
                cell_center_y - glow_radius * 1.2,
                glow_radius * 2.4,
                glow_radius * 2.4
            )
            glow_ellipse.setBrush(QBrush(outer_gradient))
            glow_ellipse.setPen(QPen(Qt.PenStyle.NoPen))
            glow_ellipse.setZValue(1)
            self.scene.addItem(glow_ellipse)

            # Draw radiant rays (scale with size)
            num_rays = 12
            inner_ray_start = base_radius - 10
            outer_ray_end = base_radius + spread

            for i in range(num_rays):
                angle = (2 * math.pi * i / num_rays) - math.pi / 2  # Start from top
                # Alternating ray lengths for visual interest
                ray_length = outer_ray_end if i % 2 == 0 else outer_ray_end * 0.7

                start_x = cell_center_x + inner_ray_start * math.cos(angle)
                start_y = cell_center_y + inner_ray_start * math.sin(angle)
                end_x = cell_center_x + ray_length * math.cos(angle)
                end_y = cell_center_y + ray_length * math.sin(angle)

                # Thicker rays for primary directions
                ray_width = 4 if i % 3 == 0 else 2
                ray_pen = QPen(ray_color)
                ray_pen.setWidth(ray_width)
                ray_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

                ray_line = self.scene.addLine(start_x, start_y, end_x, end_y, ray_pen)
                ray_line.setZValue(2)

            # Center bright spot (scales with size)
            center_size = 20 * size_ratio
            center_gradient = QRadialGradient(cell_center_x, cell_center_y, center_size)
            center_bright = QColor(colors["outer"])
            center_bright.setAlphaF(opacity * 0.6)
            center_gradient.setColorAt(0.0, center_bright)
            center_gradient.setColorAt(1.0, transparent)

            center_spot = QGraphicsEllipseItem(
                cell_center_x - center_size, cell_center_y - center_size,
                center_size * 2, center_size * 2
            )
            center_spot.setBrush(QBrush(center_gradient))
            center_spot.setPen(QPen(Qt.PenStyle.NoPen))
            center_spot.setZValue(3)
            self.scene.addItem(center_spot)

        elif effect_type == "Corner Sparkles":
            # Diamond sparkles at each corner of the cell
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            from PySide6.QtWidgets import QGraphicsPolygonItem

            sparkle_color = QColor(colors["glow"])
            sparkle_color.setAlphaF(opacity * 0.9)

            sparkle_size = (8 + (spread / 10)) * size_ratio  # Scale with spread and size

            # Calculate scaled cell bounds
            size_offset = (self.cell_size / 2) * (1 - size_ratio)
            scaled_x1 = x1 + size_offset
            scaled_y1 = y1 + size_offset
            scaled_size = self.cell_size * size_ratio

            # Corner positions (outside the scaled cell slightly)
            corners = [
                (scaled_x1 - 5, scaled_y1 - 5),                              # Top-left
                (scaled_x1 + scaled_size + 5, scaled_y1 - 5),                # Top-right
                (scaled_x1 - 5, scaled_y1 + scaled_size + 5),                # Bottom-left
                (scaled_x1 + scaled_size + 5, scaled_y1 + scaled_size + 5)   # Bottom-right
            ]

            for cx, cy in corners:
                # Create diamond shape
                diamond = QPolygonF([
                    QPointF(cx, cy - sparkle_size),      # Top
                    QPointF(cx + sparkle_size, cy),      # Right
                    QPointF(cx, cy + sparkle_size),      # Bottom
                    QPointF(cx - sparkle_size, cy)       # Left
                ])

                sparkle_item = QGraphicsPolygonItem(diamond)
                sparkle_item.setBrush(QBrush(sparkle_color))
                sparkle_item.setPen(QPen(Qt.PenStyle.NoPen))
                sparkle_item.setZValue(3)
                self.scene.addItem(sparkle_item)

                # Inner bright center for each sparkle
                inner_sparkle_size = sparkle_size * 0.5
                inner_diamond = QPolygonF([
                    QPointF(cx, cy - inner_sparkle_size),
                    QPointF(cx + inner_sparkle_size, cy),
                    QPointF(cx, cy + inner_sparkle_size),
                    QPointF(cx - inner_sparkle_size, cy)
                ])

                inner_color = QColor(colors["outer"])
                inner_color.setAlphaF(opacity)

                inner_sparkle = QGraphicsPolygonItem(inner_diamond)
                inner_sparkle.setBrush(QBrush(inner_color))
                inner_sparkle.setPen(QPen(Qt.PenStyle.NoPen))
                inner_sparkle.setZValue(4)
                self.scene.addItem(inner_sparkle)

            # Add subtle glow behind the whole cell
            glow_size_scaled = base_radius * 1.6
            cell_glow = QRadialGradient(cell_center_x, cell_center_y, glow_size_scaled)
            glow_color = QColor(colors["primary"])
            glow_color.setAlphaF(opacity * 0.2)
            transparent = QColor(0, 0, 0, 0)
            cell_glow.setColorAt(0.0, transparent)
            cell_glow.setColorAt(0.6, glow_color)
            cell_glow.setColorAt(1.0, transparent)

            glow_bg = QGraphicsEllipseItem(
                cell_center_x - glow_size_scaled,
                cell_center_y - glow_size_scaled,
                glow_size_scaled * 2,
                glow_size_scaled * 2
            )
            glow_bg.setBrush(QBrush(cell_glow))
            glow_bg.setPen(QPen(Qt.PenStyle.NoPen))
            glow_bg.setZValue(1)
            self.scene.addItem(glow_bg)

    def _draw_house_element_glow(self, house_num: int, effect_settings: dict):
        """Draw element-themed glow effect around a specific house cell.

        The house position is calculated as (Ascendant sign + house_num - 1) % 12
        using Whole Sign house system.

        Args:
            house_num: House number (1-12, typically 5 or 9)
            effect_settings: Dict with effect parameters

        Note: Uses _get_effective_ascendant_sign_index() to support
        the F4 "Sign as Ascendant" override feature.
        """
        from PySide6.QtWidgets import QGraphicsEllipseItem
        from PySide6.QtGui import QRadialGradient

        if not self._chart:
            return

        asc_sign_index = self._get_effective_ascendant_sign_index()

        # Calculate house sign index (Whole Sign: house N is N-1 signs from Ascendant)
        house_sign_index = (asc_sign_index + house_num - 1) % 12

        # Find cell position for this sign
        cell_pos = None
        for (row, col), zidx in self.ZODIAC_POSITIONS.items():
            if zidx == house_sign_index:
                cell_pos = (row, col)
                break

        if not cell_pos:
            return

        row, col = cell_pos
        x1 = col * self.cell_size
        y1 = row * self.cell_size
        cell_center_x = x1 + self.cell_size / 2
        cell_center_y = y1 + self.cell_size / 2

        # Get element and colors for this house's sign
        element = self.ZODIAC_ELEMENT.get(house_sign_index, "fire")
        colors = self.ELEMENT_GLOW_COLORS.get(element, self.ELEMENT_GLOW_COLORS["fire"])

        # Get effect settings
        opacity = effect_settings.get("opacity", 0.5)
        spread = effect_settings.get("spread", 20)
        size_ratio = effect_settings.get("size", 0.8)
        effect_type = effect_settings.get("effect_type", "Element Glow")
        offset_x = effect_settings.get("offset_x", 0)
        offset_y = effect_settings.get("offset_y", 0)

        # Apply offsets to center position
        cell_center_x += offset_x
        cell_center_y += offset_y

        # Calculate base size
        base_radius = (self.cell_size / 2) * size_ratio
        glow_radius = base_radius + spread

        # Reuse the same rendering logic as ascendant glow
        # (Element Glow is most common, implement all 5 effect types)
        if effect_type == "Element Glow":
            gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius)
            inner_color = QColor(colors["primary"])
            inner_color.setAlphaF(opacity * 0.6)
            mid_color = QColor(colors["glow"])
            mid_color.setAlphaF(opacity * 0.4)
            outer_color = QColor(colors["outer"])
            outer_color.setAlphaF(opacity * 0.15)
            transparent = QColor(0, 0, 0, 0)

            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(0.5, inner_color)
            gradient.setColorAt(0.7, mid_color)
            gradient.setColorAt(0.85, outer_color)
            gradient.setColorAt(1.0, transparent)

            glow_rect = QGraphicsEllipseItem(
                cell_center_x - glow_radius, cell_center_y - glow_radius,
                glow_radius * 2, glow_radius * 2
            )
            glow_rect.setBrush(QBrush(gradient))
            glow_rect.setPen(QPen(Qt.PenStyle.NoPen))
            glow_rect.setZValue(1)
            self.scene.addItem(glow_rect)

            # Inner ring
            ring_size = base_radius + 15
            ring_gradient = QRadialGradient(cell_center_x, cell_center_y, ring_size)
            ring_inner = QColor(colors["glow"])
            ring_inner.setAlphaF(opacity * 0.8)
            ring_outer = QColor(colors["primary"])
            ring_outer.setAlphaF(0)
            ring_gradient.setColorAt(0.85, ring_outer)
            ring_gradient.setColorAt(0.92, ring_inner)
            ring_gradient.setColorAt(1.0, ring_outer)

            ring = QGraphicsEllipseItem(
                cell_center_x - ring_size, cell_center_y - ring_size,
                ring_size * 2, ring_size * 2
            )
            ring.setBrush(QBrush(ring_gradient))
            ring.setPen(QPen(Qt.PenStyle.NoPen))
            ring.setZValue(2)
            self.scene.addItem(ring)

        elif effect_type == "Golden Aura":
            # Golden gradient regardless of element
            gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius)
            gold_inner = QColor("#FFD700")
            gold_inner.setAlphaF(opacity * 0.7)
            gold_mid = QColor("#FFA500")
            gold_mid.setAlphaF(opacity * 0.4)
            gold_outer = QColor("#FF8C00")
            gold_outer.setAlphaF(opacity * 0.1)
            transparent = QColor(0, 0, 0, 0)

            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(0.4, gold_inner)
            gradient.setColorAt(0.7, gold_mid)
            gradient.setColorAt(0.9, gold_outer)
            gradient.setColorAt(1.0, transparent)

            glow = QGraphicsEllipseItem(
                cell_center_x - glow_radius, cell_center_y - glow_radius,
                glow_radius * 2, glow_radius * 2
            )
            glow.setBrush(QBrush(gradient))
            glow.setPen(QPen(Qt.PenStyle.NoPen))
            glow.setZValue(1)
            self.scene.addItem(glow)

        elif effect_type == "Radiant Burst":
            # Sunburst rays radiating from the cell center
            import math
            ray_color = QColor(colors["glow"])
            ray_color.setAlphaF(opacity * 0.7)

            # Outer glow first (soft background)
            outer_gradient = QRadialGradient(cell_center_x, cell_center_y, glow_radius * 1.2)
            outer_glow = QColor(colors["primary"])
            outer_glow.setAlphaF(opacity * 0.25)
            transparent = QColor(0, 0, 0, 0)
            outer_gradient.setColorAt(0.4, transparent)
            outer_gradient.setColorAt(0.7, outer_glow)
            outer_gradient.setColorAt(1.0, transparent)

            glow_ellipse = QGraphicsEllipseItem(
                cell_center_x - glow_radius * 1.2,
                cell_center_y - glow_radius * 1.2,
                glow_radius * 2.4,
                glow_radius * 2.4
            )
            glow_ellipse.setBrush(QBrush(outer_gradient))
            glow_ellipse.setPen(QPen(Qt.PenStyle.NoPen))
            glow_ellipse.setZValue(1)
            self.scene.addItem(glow_ellipse)

            # Draw radiant rays (scale with size)
            num_rays = 12
            inner_ray_start = base_radius - 10
            outer_ray_end = base_radius + spread

            for i in range(num_rays):
                angle = (2 * math.pi * i / num_rays) - math.pi / 2  # Start from top
                # Alternating ray lengths for visual interest
                ray_length = outer_ray_end if i % 2 == 0 else outer_ray_end * 0.7

                start_x = cell_center_x + inner_ray_start * math.cos(angle)
                start_y = cell_center_y + inner_ray_start * math.sin(angle)
                end_x = cell_center_x + ray_length * math.cos(angle)
                end_y = cell_center_y + ray_length * math.sin(angle)

                # Thicker rays for primary directions
                ray_width = 4 if i % 3 == 0 else 2
                ray_pen = QPen(ray_color)
                ray_pen.setWidth(ray_width)
                ray_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

                ray_line = self.scene.addLine(start_x, start_y, end_x, end_y, ray_pen)
                ray_line.setZValue(2)

            # Center bright spot (scales with size)
            center_size = 20 * size_ratio
            center_gradient = QRadialGradient(cell_center_x, cell_center_y, center_size)
            center_bright = QColor(colors["outer"])
            center_bright.setAlphaF(opacity * 0.6)
            center_gradient.setColorAt(0.0, center_bright)
            center_gradient.setColorAt(1.0, transparent)

            center_spot = QGraphicsEllipseItem(
                cell_center_x - center_size, cell_center_y - center_size,
                center_size * 2, center_size * 2
            )
            center_spot.setBrush(QBrush(center_gradient))
            center_spot.setPen(QPen(Qt.PenStyle.NoPen))
            center_spot.setZValue(3)
            self.scene.addItem(center_spot)

        elif effect_type == "Double Border":
            # Draw double border around cell (scales with size)
            from PySide6.QtWidgets import QGraphicsRectItem

            border_color = QColor(colors["glow"])
            border_color.setAlphaF(opacity)

            # Calculate border offsets based on size ratio
            size_offset = (self.cell_size / 2) * (1 - size_ratio)
            outer_offset = 12 * size_ratio
            inner_offset = 4 * size_ratio

            pen = QPen(border_color)
            pen.setWidth(int(8 * size_ratio))

            # Outer border
            outer_rect = QGraphicsRectItem(
                x1 + size_offset - outer_offset,
                y1 + size_offset - outer_offset,
                self.cell_size * size_ratio + outer_offset * 2,
                self.cell_size * size_ratio + outer_offset * 2
            )
            outer_rect.setPen(pen)
            outer_rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            outer_rect.setZValue(2)
            self.scene.addItem(outer_rect)

            # Inner border
            pen.setWidth(int(4 * size_ratio))
            inner_rect = QGraphicsRectItem(
                x1 + size_offset - inner_offset,
                y1 + size_offset - inner_offset,
                self.cell_size * size_ratio + inner_offset * 2,
                self.cell_size * size_ratio + inner_offset * 2
            )
            inner_rect.setPen(pen)
            inner_rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            inner_rect.setZValue(2)
            self.scene.addItem(inner_rect)

        elif effect_type == "Corner Sparkles":
            # Diamond sparkles at each corner of the cell
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            from PySide6.QtWidgets import QGraphicsPolygonItem

            sparkle_color = QColor(colors["glow"])
            sparkle_color.setAlphaF(opacity * 0.9)

            sparkle_size = (8 + (spread / 10)) * size_ratio  # Scale with spread and size

            # Calculate scaled cell bounds
            size_offset = (self.cell_size / 2) * (1 - size_ratio)
            scaled_x1 = x1 + size_offset
            scaled_y1 = y1 + size_offset
            scaled_size = self.cell_size * size_ratio

            # Corner positions (outside the scaled cell slightly)
            corners = [
                (scaled_x1 - 5, scaled_y1 - 5),                              # Top-left
                (scaled_x1 + scaled_size + 5, scaled_y1 - 5),                # Top-right
                (scaled_x1 - 5, scaled_y1 + scaled_size + 5),                # Bottom-left
                (scaled_x1 + scaled_size + 5, scaled_y1 + scaled_size + 5)   # Bottom-right
            ]

            for cx, cy in corners:
                # Create diamond shape
                diamond = QPolygonF([
                    QPointF(cx, cy - sparkle_size),      # Top
                    QPointF(cx + sparkle_size, cy),      # Right
                    QPointF(cx, cy + sparkle_size),      # Bottom
                    QPointF(cx - sparkle_size, cy)       # Left
                ])

                sparkle_item = QGraphicsPolygonItem(diamond)
                sparkle_item.setBrush(QBrush(sparkle_color))
                sparkle_item.setPen(QPen(Qt.PenStyle.NoPen))
                sparkle_item.setZValue(3)
                self.scene.addItem(sparkle_item)

                # Inner bright center for each sparkle
                inner_sparkle_size = sparkle_size * 0.5
                inner_diamond = QPolygonF([
                    QPointF(cx, cy - inner_sparkle_size),
                    QPointF(cx + inner_sparkle_size, cy),
                    QPointF(cx, cy + inner_sparkle_size),
                    QPointF(cx - inner_sparkle_size, cy)
                ])

                inner_color = QColor(colors["outer"])
                inner_color.setAlphaF(opacity)

                inner_sparkle = QGraphicsPolygonItem(inner_diamond)
                inner_sparkle.setBrush(QBrush(inner_color))
                inner_sparkle.setPen(QPen(Qt.PenStyle.NoPen))
                inner_sparkle.setZValue(4)
                self.scene.addItem(inner_sparkle)

            # Add subtle glow behind the whole cell
            glow_size_scaled = base_radius * 1.6
            cell_glow = QRadialGradient(cell_center_x, cell_center_y, glow_size_scaled)
            glow_color = QColor(colors["primary"])
            glow_color.setAlphaF(opacity * 0.2)
            transparent = QColor(0, 0, 0, 0)
            cell_glow.setColorAt(0.0, transparent)
            cell_glow.setColorAt(0.6, glow_color)
            cell_glow.setColorAt(1.0, transparent)

            glow_bg = QGraphicsEllipseItem(
                cell_center_x - glow_size_scaled,
                cell_center_y - glow_size_scaled,
                glow_size_scaled * 2,
                glow_size_scaled * 2
            )
            glow_bg.setBrush(QBrush(cell_glow))
            glow_bg.setPen(QPen(Qt.PenStyle.NoPen))
            glow_bg.setZValue(1)
            self.scene.addItem(glow_bg)

            # Subtle background glow
            glow_size_scaled = base_radius * 0.9
            cell_glow = QRadialGradient(cell_center_x, cell_center_y, glow_size_scaled)
            glow_center = QColor(colors["outer"])
            glow_center.setAlphaF(opacity * 0.3)
            glow_edge = QColor(colors["primary"])
            glow_edge.setAlphaF(0)
            cell_glow.setColorAt(0.0, glow_center)
            cell_glow.setColorAt(1.0, glow_edge)

            glow_bg = QGraphicsEllipseItem(
                cell_center_x - glow_size_scaled, cell_center_y - glow_size_scaled,
                glow_size_scaled * 2, glow_size_scaled * 2
            )
            glow_bg.setBrush(QBrush(cell_glow))
            glow_bg.setPen(QPen(Qt.PenStyle.NoPen))
            glow_bg.setZValue(1)
            self.scene.addItem(glow_bg)

    def _draw_ascendant_stripe(self):
        """Draw diagonal stripe in the ascendant sign cell corner (traditional South Indian chart style)

        The stripe consists of two parallel diagonal lines at the top-right
        corner of the ascendant cell, with the degree shown nearby.

        Note: Uses _get_effective_ascendant_sign_index() to support
        the F4 "Sign as Ascendant" override feature.
        """
        if not self._chart:
            return

        # Get effective Ascendant sign (may be overridden by F4 Sign as Ascendant)
        sign_index = self._get_effective_ascendant_sign_index()

        # Find cell position for this sign
        cell_pos = None
        for (row, col), zidx in self.ZODIAC_POSITIONS.items():
            if zidx == sign_index:
                cell_pos = (row, col)
                break

        if not cell_pos:
            return

        row, col = cell_pos
        x1 = col * self.cell_size
        y1 = row * self.cell_size
        x2 = x1 + self.cell_size

        # Get element color for this sign
        color_hex = self.ELEMENT_COLORS.get(sign_index, "#CC0000")
        stripe_color = QColor(color_hex)
        stripe_color.setAlpha(80)  # 31% opacity (80/255 ≈ 0.31)

        # Pen settings matching original: max(6, int(width * 0.035))
        stroke_width = max(6, int(self.cell_size * 0.035))
        pen = QPen(stripe_color)
        pen.setWidth(stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # Stripe parameters (original CustomTkinter values)
        stripe_length = int(self.cell_size * 0.40)
        gap = max(16, int(self.cell_size * 0.08))

        # Get lagna strip position offsets from settings (defaults: 5, 5)
        lagna_settings = self.display_settings.get("lagna_strip", {})
        lagna_offset_x = lagna_settings.get("offset_x", 5)
        lagna_offset_y = lagna_settings.get("offset_y", 5)

        # Start position in top-right corner (customizable via settings)
        start_x = x2 - stripe_length - gap - lagna_offset_x
        start_y = y1 + lagna_offset_y

        # Second stripe is shorter so it doesn't overflow the cell edge
        # Account for pen width so the painted stroke stays inside
        margin = stroke_width + 4  # full pen width + buffer
        max_end_x = x2 - lagna_offset_x - margin
        stripe2_length = min(stripe_length, max_end_x - (start_x + gap))

        # First stripe is longer by the same margin so it reaches the cell edge
        stripe1_length = stripe_length + margin

        # Multiple overlapping strokes for soft effect
        # Qt takes ownership of QGraphicsLineItem when returned by addLine()
        for offset in range(-1, 2):
            # First stripe (extended at bottom-right end to reach cell edge)
            line_item = self.scene.addLine(
                start_x + offset, start_y,
                start_x + stripe1_length + offset, start_y + stripe1_length,
                pen
            )
            line_item.setZValue(-1)  # Behind sign icons (z=0) and labels (z=10)

            # Second parallel stripe (shorter to stay within cell)
            line_item = self.scene.addLine(
                start_x + gap + offset, start_y,
                start_x + gap + stripe2_length + offset, start_y + stripe2_length,
                pen
            )
            line_item.setZValue(-1)  # Behind sign icons (z=0) and labels (z=10)

        # Add ascendant degree text - positioned below the sign name area
        # Only show actual birth degree when not in override mode
        asc_deg_settings = self.display_settings.get('ascendant_degree', {})
        if asc_deg_settings.get('enabled', True) and self.ascendant_override is None:
            asc_cusp = self._cusps[1] if self._cusps else None
            if asc_cusp:
                risl = asc_cusp.amsha_raw_in_sign_longitude() if self._varga_code else asc_cusp.real_in_sign_longitude()
                deg = int(risl)
                mins = int((risl % 1) * 60)
            else:
                deg, mins = 0, 0
            text_item = QGraphicsTextItem(f"{deg}:{mins:02d}")

            # Determine color: "element" uses sign element color, "custom" uses user color
            color_mode = asc_deg_settings.get('color_mode', 'element')
            if color_mode == 'custom':
                text_color = QColor(asc_deg_settings.get('custom_color', '#FFFFFF'))
            else:
                text_color = QColor(color_hex)
            text_item.setDefaultTextColor(text_color)

            # Font settings
            font_size = asc_deg_settings.get('font_size', 20)
            font_weight = asc_deg_settings.get('font_weight', 'normal')
            font = QFont(FONT_CHART, font_size)
            if font_weight == 'bold':
                font.setWeight(QFont.Weight.Bold)
            text_item.setFont(font)

            # Position with user-configurable offsets
            offset_x = asc_deg_settings.get('offset_x', 10)
            offset_y = asc_deg_settings.get('offset_y', 45)
            text_width = text_item.boundingRect().width()
            text_item.setPos(x2 - text_width - offset_x, y1 + offset_y)
            text_item.setZValue(10)
            self.scene.addItem(text_item)

    def set_ascendant_override(self, sign_index: int = None):
        """
        Set Ascendant override for chart display.

        Used by F4 "Cycle Sign as Ascendant" feature to visualize
        the chart as if any sign were the Ascendant.

        Args:
            sign_index: 0-11 for sign override (0=Dhata, 11=Parjanya),
                       None for actual birth Ascendant
        """
        self.ascendant_override = sign_index
        if self._chart:
            self.draw_full_chart()

    def _get_effective_ascendant_sign_index(self) -> int:
        """Get the Ascendant sign index (0-11). Supports F4 override."""
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

    def get_house_number_for_sign(self, zodiac_index):
        """Get the whole sign house number for a zodiac sign based on ascendant

        Args:
            zodiac_index: Index from ZODIAC_POSITIONS (0-11)

        Returns:
            House number (1-12) or None if ascendant not available

        Note: Uses _get_effective_ascendant_sign_index() to support
        the F4 "Sign as Ascendant" override feature.
        """
        if not self._chart:
            return None

        # Get effective Ascendant (may be overridden by F4 Sign as Ascendant)
        asc_sign_index = self._get_effective_ascendant_sign_index()

        # House number = (zodiac_index - ascendant_sign_index) % 12 + 1
        house_num = (zodiac_index - asc_sign_index) % 12 + 1
        return house_num

    def get_cusps_for_sign(self, zodiac_index):
        """Get list of Campanus house cusps that fall in this zodiac sign.

        Campanus house system divides the prime vertical into 12 equal parts,
        which means house cusps can fall at any degree. This method finds which
        house cusps (if any) fall within the given zodiac sign.

        Args:
            zodiac_index: Index from ZODIAC_POSITIONS (0-11)

        Returns:
            List of formatted strings like ["C1 15°", "C2 28°"] or empty list
        """
        if not self._cusps:
            return []

        cusps = []
        for i in range(1, 13):
            cusp = self._cusps[i]
            if (cusp.sign() - 1) == zodiac_index:
                risl = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
                deg = int(risl)
                cusps.append((i, f"C{i} {deg}°"))

        cusps.sort(key=lambda x: x[0])
        return [c[1] for c in cusps]

    def _draw_house_number(self, x1, y1, x2, y2, house_number, aditya_name):
        """Draw house number in bottom-left corner of cell

        Args:
            x1, y1, x2, y2: Cell boundaries
            house_number: House number to display (1-12)
            aditya_name: Sign name for per-sign offset lookup
        """
        # Get settings
        house_settings = self.display_settings.get('house_number', {})
        global_offset_x = house_settings.get('offset_x', 8)
        global_offset_y = house_settings.get('offset_y', 38)

        # Per-sign BASE offset — use per-background preset if available,
        # otherwise fall back to hardcoded class constant
        bg_preset = BACKGROUND_PRESETS.get(self.background_identifier, {})
        preset_offsets = bg_preset.get('house_number_base_offset', None)
        if preset_offsets and aditya_name in preset_offsets:
            base_offset = preset_offsets[aditya_name]
        else:
            base_offset = self.HOUSE_NUMBER_BASE_OFFSET.get(aditya_name, (0, 0))
        base_offset_x, base_offset_y = base_offset

        # Per-sign SETTINGS offset (for fine-tuning, defaults to 0)
        house_number_offsets = self.display_settings.get("house_number_offsets", {})
        per_sign_enabled = house_number_offsets.get("enabled", False)

        per_sign_offset_x = 0
        per_sign_offset_y = 0
        if per_sign_enabled and aditya_name in house_number_offsets:
            sign_offset = house_number_offsets[aditya_name]
            per_sign_offset_x = sign_offset.get("offset_x", 0)
            per_sign_offset_y = sign_offset.get("offset_y", 0)

        # House number text (e.g., "H1", "H2")
        text = f"H{house_number}"

        # Position in bottom-left corner = global + base + per-sign adjustment
        x = x1 + global_offset_x + base_offset_x + per_sign_offset_x  # from left edge
        y = y2 - global_offset_y + base_offset_y + per_sign_offset_y  # from bottom edge (negative base_y = higher)

        # Draw with styling
        self._draw_styled_text(text, x, y, house_settings, self.text_color, z_value=5)

    def _draw_house_cusps(self, x1, y1, x2, y2, zodiac_index):
        """Draw Campanus house cusps in bottom-right corner of cell.

        Campanus cusps show where each house actually begins in the zodiac,
        which can differ significantly from Whole Sign Houses. This is useful
        for practitioners who use both systems.

        Args:
            x1, y1, x2, y2: Cell boundaries
            zodiac_index: Zodiac sign index (0-11)
        """
        # Get cusps for this sign
        cusps_in_sign = self.get_cusps_for_sign(zodiac_index)
        if not cusps_in_sign:
            return

        # Combine cusps into comma-separated text
        cusp_text = ", ".join(cusps_in_sign)

        # Get cusp settings from display_settings (with defaults)
        cusp_settings = self.display_settings.get('house_cusps', {})
        if not cusp_settings.get('enabled', True):
            return

        # Adaptive font size: smaller when many cusps (e.g., polar latitudes)
        # Base font size from settings, with reductions for multiple cusps
        base_font_size = cusp_settings.get('font_size', 24)
        if len(cusps_in_sign) >= 4:
            font_size = max(16, base_font_size - 10)
        elif len(cusps_in_sign) >= 3:
            font_size = max(18, base_font_size - 6)
        else:
            font_size = base_font_size

        # Create temporary settings dict for _draw_styled_text
        style_settings = {
            'font_family': cusp_settings.get('font_family', 'default'),
            'font_size': font_size,
            'font_weight': cusp_settings.get('font_weight', 'normal'),
            'outline_enabled': cusp_settings.get('outline_enabled', False),
            'outline_color': cusp_settings.get('outline_color', '#000000'),
            'outline_width': cusp_settings.get('outline_width', 2),
            'background_enabled': cusp_settings.get('background_enabled', False),
            'background_color': cusp_settings.get('background_color', '#000000'),
            'background_opacity': cusp_settings.get('background_opacity', 180),
            'background_padding': cusp_settings.get('background_padding', 4),
            'background_radius': cusp_settings.get('background_radius', 0),
        }

        # Position in bottom-right corner (offset from edge)
        offset_x = cusp_settings.get('offset_x', 16)
        offset_y = cusp_settings.get('offset_y', 32)
        x = x2 - offset_x
        y = y2 - offset_y

        # Draw using simple text item (positioned from right edge)
        # Use QGraphicsSimpleTextItem for right-aligned text
        from PySide6.QtWidgets import QGraphicsSimpleTextItem
        from PySide6.QtGui import QFont

        # Get font
        font_family = style_settings.get('font_family', 'default')
        if font_family == 'default' or font_family == FONT_CHART:
            font = QFont(FONT_CHART)
        else:
            font = QFont(font_family)
        font.setPixelSize(font_size)

        font_weight_str = style_settings.get('font_weight', 'normal')
        if font_weight_str == 'bold':
            font.setWeight(QFont.Weight.Bold)

        text_item = QGraphicsSimpleTextItem(cusp_text)
        text_item.setFont(font)
        text_item.setBrush(QBrush(self.text_color))

        # Calculate position - anchor at bottom-right
        text_width = text_item.boundingRect().width()
        text_height = text_item.boundingRect().height()
        text_item.setPos(x - text_width, y - text_height)
        text_item.setZValue(5)
        self.scene.addItem(text_item)

    def _draw_styled_text(self, text: str, x: float, y: float, style_settings: dict,
                          default_color: QColor = None, z_value: int = 5, center_x: bool = False):
        """
        Draw text with optional styling (font, outline, background).

        Args:
            text: The text to draw
            x, y: Position coordinates (x is center if center_x=True)
            style_settings: Dict with font_family, font_size, font_weight,
                           outline_enabled, outline_color, outline_width,
                           background_enabled, background_color, background_opacity,
                           background_padding, background_radius
            default_color: Default text color if not styled
            z_value: Z-order for layering
            center_x: If True, x is treated as center point, text is centered horizontally
        """
        from PySide6.QtWidgets import QGraphicsSimpleTextItem, QGraphicsPathItem

        # Get style settings with defaults
        font_family = style_settings.get('font_family', 'default')
        font_size = style_settings.get('font_size', 16)
        font_weight = style_settings.get('font_weight', 'normal')
        outline_enabled = style_settings.get('outline_enabled', False)
        outline_color = style_settings.get('outline_color', '#000000')
        outline_width = style_settings.get('outline_width', 2)
        bg_enabled = style_settings.get('background_enabled', False)
        bg_color = style_settings.get('background_color', '#000000')
        bg_opacity = style_settings.get('background_opacity', 180)
        bg_padding = style_settings.get('background_padding', 4)
        bg_radius = style_settings.get('background_radius', 0)

        # Create font
        if font_family == 'default':
            font = QFont(FONT_CHART, font_size)
        else:
            font = QFont(font_family, font_size)

        if font_weight == 'bold':
            font.setWeight(QFont.Weight.Bold)

        has_cjk = any('一' <= ch <= '鿿' for ch in text)
        if has_cjk and font_weight != 'bold':
            font.setWeight(QFont.Weight.Light)

        # Calculate text metrics for background/outline
        metrics = QFontMetrics(font)
        text_rect = metrics.boundingRect(text)
        text_width = text_rect.width()
        text_height = metrics.height()

        # Adjust x position if centering is requested
        if center_x:
            x = x - text_width / 2

        # Get frame settings (rectangular border around text - like a picture frame)
        frame_enabled = style_settings.get('frame_enabled', False)
        frame_color = style_settings.get('frame_color', '#DAA520')
        frame_gradient = style_settings.get('frame_gradient', None)  # Gradient dict or None
        frame_width = style_settings.get('frame_width', 2)
        frame_padding = style_settings.get('frame_padding', 4)
        frame_radius = style_settings.get('frame_radius', 0)

        # Draw frame if enabled (border stroke only, no fill - like a picture frame)
        if frame_enabled:
            frame_x = x - frame_padding
            frame_y = y - frame_padding
            frame_w = text_width + 2 * frame_padding
            frame_h = text_height + 2 * frame_padding

            # Create pen - either solid color or gradient
            if frame_gradient and isinstance(frame_gradient, dict):
                # Use gradient for 3D metallic effect
                colors = frame_gradient.get('colors', ['#FFFFFF', '#808080'])
                gradient = QLinearGradient(frame_x, frame_y, frame_x, frame_y + frame_h)
                for i, color in enumerate(colors):
                    pos = i / (len(colors) - 1) if len(colors) > 1 else 0
                    gradient.setColorAt(pos, QColor(color))
                frame_pen = QPen(QBrush(gradient), frame_width)
            else:
                # Solid color
                frame_pen = QPen(QColor(frame_color), frame_width)

            if frame_radius > 0:
                # Rounded rectangle frame using QPainterPath
                path = QPainterPath()
                path.addRoundedRect(frame_x, frame_y, frame_w, frame_h, frame_radius, frame_radius)
                frame_item = QGraphicsPathItem(path)
                frame_item.setPen(frame_pen)
                frame_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))  # No fill - just border
            else:
                # Regular rectangle frame
                frame_item = QGraphicsRectItem(frame_x, frame_y, frame_w, frame_h)
                frame_item.setPen(frame_pen)
                frame_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))  # No fill - just border

            frame_item.setZValue(z_value - 1)  # Behind text
            frame_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            frame_item.setAcceptHoverEvents(False)
            self.scene.addItem(frame_item)

        # Draw background fill if enabled (separate from frame)
        if bg_enabled:
            bg_qcolor = QColor(bg_color)
            bg_qcolor.setAlpha(bg_opacity)

            bg_x = x - bg_padding
            bg_y = y - bg_padding
            bg_w = text_width + 2 * bg_padding
            bg_h = text_height + 2 * bg_padding

            if bg_radius > 0:
                # Rounded rectangle using QPainterPath
                path = QPainterPath()
                path.addRoundedRect(bg_x, bg_y, bg_w, bg_h, bg_radius, bg_radius)
                bg_item = QGraphicsPathItem(path)
            else:
                # Regular rectangle
                bg_item = QGraphicsRectItem(bg_x, bg_y, bg_w, bg_h)

            bg_item.setBrush(QBrush(bg_qcolor))
            bg_item.setPen(QPen(Qt.PenStyle.NoPen))
            bg_item.setZValue(z_value - 2)  # Behind frame and text
            bg_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            bg_item.setAcceptHoverEvents(False)
            self.scene.addItem(bg_item)

        # Draw outline if enabled (using QPainterPath for stroke effect)
        if outline_enabled:
            path = QPainterPath()
            path.addText(x, y + metrics.ascent(), font, text)

            outline_item = QGraphicsPathItem(path)
            outline_pen = QPen(QColor(outline_color))
            outline_pen.setWidth(outline_width)
            outline_item.setPen(outline_pen)
            outline_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            outline_item.setZValue(z_value)
            outline_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            outline_item.setAcceptHoverEvents(False)
            self.scene.addItem(outline_item)

        # Draw main text
        text_item = QGraphicsSimpleTextItem(text)
        text_item.setFont(font)

        # Use default color or theme color
        if default_color:
            text_item.setBrush(default_color)
        else:
            text_item.setBrush(self.text_color)

        text_item.setPos(x, y)
        text_item.setZValue(z_value + 1)  # Above outline/background
        text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        text_item.setAcceptHoverEvents(False)
        self.scene.addItem(text_item)

    # === DRAWING HELPERS ===

    def _group_planets_by_sign(self):
        """Group planets by zodiac sign using planet.sign() from Chart."""
        if not self._planets:
            return {}
        planets_by_sign = {}
        outer_planets = {"Uranus", "Neptune", "Pluto"}
        for planet_name in self.PLANET_NAMES:
            if not self.show_outer_planets and planet_name in outer_planets:
                continue
            try:
                planet = self._planets[planet_name]
            except KeyError:
                continue
            sign_idx = planet.sign() - 1
            if sign_idx not in planets_by_sign:
                planets_by_sign[sign_idx] = []
            planets_by_sign[sign_idx].append((planet_name, planet))
        return planets_by_sign

    def _planet_deg_min(self, planet):
        """Extract (degrees, minutes) within sign from a Planet object."""
        risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
        return int(risl), int((risl % 1) * 60)

    def _planet_to_click_dict(self, planet_name, planet):
        """Project Planet object to mini-dict for click signal consumers."""
        deg, mins = self._planet_deg_min(planet)
        return {
            "sign": planet.sign_name(),
            "aditya_zodiac": planet.sign_name(),
            "sign_index": planet.sign() - 1,
            "degrees": deg,
            "minutes": mins,
            "decimal_degrees": planet.ecliptic_longitude(),
            "is_retrograde": planet.retrograde(),
        }

    def _get_crowded_size(self, base_size, num_planets):
        """Apply crowding reduction to planet size

        Original CustomTkinter logic:
        - 1-3 planets: full size
        - 4-5 planets: reduce 1 tier
        - 6+ planets: force minimum 24px
        """
        if num_planets <= 3:
            return base_size
        elif num_planets <= 5:
            # Reduce by ~25% (one tier down)
            return int(base_size * 0.75)
        else:
            # Force minimum for very crowded signs (scaled for 2048 scene)
            return 64

    def _draw_planets_in_sign(self, zodiac_idx, planets_in_sign):
        """Draw planets in a specific sign cell with individual sizes and crowding

        All positions, sizes, colors, and shadows are customizable via Chart Display settings.
        Per-planet text offsets allow fine-tuning of label positions.
        """
        cell_pos = None
        for (row, col), zidx in self.ZODIAC_POSITIONS.items():
            if zidx == zodiac_idx:
                cell_pos = (row, col)
                break

        if not cell_pos:
            return

        row, col = cell_pos
        x1 = col * self.cell_size
        y1 = row * self.cell_size

        # Get planet position settings
        planet_settings = self.display_settings.get("planets", {})
        vertical_pct = planet_settings.get("vertical_position", 58) / 100.0
        padding = planet_settings.get("horizontal_padding", 40)

        # Get planet text offset settings (base offsets)
        text_settings = self.display_settings.get("planet_text", {})
        base_abbrev_offset_y = text_settings.get("abbrev_offset_y", 4)
        base_degrees_offset_y = text_settings.get("degrees_offset_y", 28)

        # Get per-planet text offsets (added to base offset)
        planet_text_offsets = self.display_settings.get("planet_text_offsets", {})

        # Get text colors from settings
        text_colors = self.display_settings.get("text_colors", {})
        abbrev_color = text_colors.get("planet_abbrev", "#EEEEEE")
        degrees_color = text_colors.get("planet_degrees", "#AAAAAA")

        # Get planet sizes from settings (fallback to class defaults)
        planet_sizes = self.display_settings.get("planet_sizes", self.PLANET_SIZES)

        # Sort planets by in-sign longitude so left=0deg, right=30deg (SPEC-SIC-001)
        varga = self._varga_code
        planets_in_sign = sorted(
            planets_in_sign,
            key=lambda item: item[1].amsha_raw_in_sign_longitude() if varga else item[1].real_in_sign_longitude()
        )

        num_planets = len(planets_in_sign)
        y_pos = y1 + self.cell_size * vertical_pct  # Customizable vertical position

        available_width = self.cell_size - (2 * padding)
        spacing = available_width / max(num_planets, 1)

        for i, (planet_name, planet) in enumerate(planets_in_sign):
            if num_planets == 1:
                risl = planet.amsha_raw_in_sign_longitude() if varga else planet.real_in_sign_longitude()
                zone = 0 if risl < 10 else (1 if risl < 20 else 2)
                third_width = available_width / 3
                x_pos = x1 + padding + (zone * third_width) + (third_width / 2)
            else:
                x_pos = x1 + padding + (i * spacing) + (spacing / 2)

            # Get individual planet size from settings with crowding adjustment
            base_size = planet_sizes.get(planet_name, self.PLANET_SIZES.get(planet_name, 128))
            planet_size = self._get_crowded_size(base_size, num_planets)

            # Get per-planet text offset adjustment
            planet_offset = planet_text_offsets.get(planet_name, 0)
            abbrev_offset_y = base_abbrev_offset_y + planet_offset
            degrees_offset_y = base_degrees_offset_y + planet_offset

            pixmap = self.load_planet_image(planet_name, size=planet_size)
            if pixmap:
                click_dict = self._planet_to_click_dict(planet_name, planet)
                planet_item = ClickablePlanetItem(
                    pixmap, planet_name, click_dict, self.planet_click_signal
                )
                planet_item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
                planet_item.setPos(x_pos, y_pos)
                planet_item.setZValue(75)

                shadow_effect = self._create_shadow_effect(planet_name=planet_name)
                if shadow_effect:
                    planet_item.setGraphicsEffect(shadow_effect)
                    del shadow_effect

                self.scene.addItem(planet_item)

            # Planet abbreviation text (e.g., "Su", "Mo")
            abbrev = planet_name[:2]
            abbrev_style = self.display_settings.get("planet_abbrev_style", {})
            abbrev_y = y_pos + planet_size / 2 + abbrev_offset_y
            self._draw_styled_text(abbrev, x_pos, abbrev_y, abbrev_style,
                                   QColor(abbrev_color), z_value=80, center_x=True)

            # Planet degrees text (e.g., "15°30'") or planet name
            if self.show_planet_names:
                degrees_text = get_planet_display_name(
                    self.sign_language, planet_name)
            else:
                deg, mins = self._planet_deg_min(planet)
                degrees_text = f"{deg}°{mins:02d}'"
            degrees_style = self.display_settings.get("planet_degrees_style", {})
            degrees_y = y_pos + planet_size / 2 + degrees_offset_y
            self._draw_styled_text(degrees_text, x_pos, degrees_y, degrees_style,
                                   QColor(degrees_color), z_value=80, center_x=True)

        # Clear local variables to prevent lingering Qt object references
        planet_item = None
        pixmap = None

    def _create_hover_zones(self):
        """Create invisible hover detection zones for all 12 outer cells"""
        for (row, col), zodiac_idx in self.ZODIAC_POSITIONS.items():
            x = col * self.cell_size
            y = row * self.cell_size

            hover_zone = HoverZoneItem(
                x, y, self.cell_size, self.cell_size,
                zodiac_idx, self.hover_signal
            )
            hover_zone.setZValue(50)
            self.scene.addItem(hover_zone)

    def _show_center_preview(self, zodiac_idx):
        """Show preview of zodiac sign in center 2x2 area

        Uses Qt's item tagging (setData) instead of Python lists to avoid dual ownership.

        Matches original CustomTkinter layout (scaled up):
        - Aditya name: top-left corner
        - Zodiac icon: top-right corner (large)
        - Sign number: top center
        - Western name: below sign number
        - Planets: middle/lower area
        """
        if self.time_adjust_mode:
            return
        if self._transit_overlay_active:
            return
        if self.selected_z6b_sign is not None:
            return

        # Only redraw if different sign (prevents flicker)
        if self.current_hover_sign == zodiac_idx:
            return

        self._hide_center_preview()

        self.current_hover_sign = zodiac_idx

        # Center 2x2 area boundaries
        center_x1 = self.cell_size
        center_y1 = self.cell_size
        center_x2 = self.cell_size * 3
        center_y2 = self.cell_size * 3
        center_mid_x = (center_x1 + center_x2) / 2

        # Scale factor for larger preview
        scale = 1.5

        # Sign name at top-left (matching original: x1+8, y1+12)
        sign_name = displayed_sign_name(zodiac_idx, self.aditya_mode,
                                        self.use_western_names,
                                        self.sign_language)
        name_text = QGraphicsTextItem(sign_name)
        name_text.setDefaultTextColor(self.grid_color)
        name_text.setFont(QFont(FONT_CHART, int(14 * scale), QFont.Weight.Bold))
        name_text.setPos(center_x1 + 10, center_y1 + 10)
        name_text.setZValue(51)
        name_text.setData(Qt.ItemDataRole.UserRole, "center_preview")  # Tag for removal
        self.scene.addItem(name_text)

        # Zodiac icon at top-right (matching original: 256px for 2K resolution)
        icon_size = 512  # Full size for 2048 scene (center preview)
        zodiac_pixmap = self.load_zodiac_icon(zodiac_idx, size=icon_size)
        if zodiac_pixmap:
            icon_item = QGraphicsPixmapItem(zodiac_pixmap)
            icon_x = center_x2 - 10 - zodiac_pixmap.width()
            icon_y = center_y1 + 10
            icon_item.setPos(icon_x, icon_y)
            icon_item.setZValue(51)
            icon_item.setData(Qt.ItemDataRole.UserRole, "center_preview")  # Tag for removal

            # Element-colored shadow (same as regular cells)
            shadow_effect = self._create_element_shadow_effect(zodiac_idx)
            if shadow_effect:
                icon_item.setGraphicsEffect(shadow_effect)
                del shadow_effect  # Rule #18: Qt owns it now

            self.scene.addItem(icon_item)

        # Sign number at top center
        sign_number = zodiac_idx + 1
        num_text = QGraphicsTextItem(str(sign_number))
        num_text.setDefaultTextColor(self.text_color)
        num_text.setFont(QFont(FONT_CHART, int(16 * scale), QFont.Weight.Bold))
        num_width = num_text.boundingRect().width()
        num_text.setPos(center_mid_x - num_width / 2, center_y1 + 10)
        num_text.setZValue(51)
        num_text.setData(Qt.ItemDataRole.UserRole, "center_preview")  # Tag for removal
        self.scene.addItem(num_text)

        # Planets in this sign - ICONS with shadows (matching original CustomTkinter)
        if self._chart:
            planets_by_sign = self._group_planets_by_sign()
            planets_in_sign = planets_by_sign.get(zodiac_idx, [])

            if planets_in_sign:
                varga = self._varga_code
                planets_in_sign = sorted(
                    planets_in_sign,
                    key=lambda item: item[1].amsha_raw_in_sign_longitude() if varga else item[1].real_in_sign_longitude()
                )
                num_planets = len(planets_in_sign)

                # Calculate horizontal positions (evenly distributed)
                padding = 40 * scale
                available_width = (center_x2 - center_x1) - (2 * padding)
                step = available_width / max(num_planets, 1)

                # Vertical position - below the zodiac icon (scaled for 2048 scene)
                y_pos = center_y1 + 720  # Below the 512px icon area

                # Planet icon size for center preview (scaled for 2048 scene)
                planet_size = 360

                # Auto-reduce if many planets
                if num_planets > 3:
                    if num_planets >= 6:
                        planet_size = 128
                    elif num_planets >= 4:
                        planet_size = 256

                for i, (planet_name, planet) in enumerate(planets_in_sign):
                    if num_planets == 1:
                        risl = planet.amsha_raw_in_sign_longitude() if varga else planet.real_in_sign_longitude()
                        zone = 0 if risl < 10 else (1 if risl < 20 else 2)
                        third_width = available_width / 3
                        x_pos = center_x1 + padding + (zone * third_width) + (third_width / 2)
                    else:
                        x_pos = center_x1 + padding + (i * step) + (step / 2)

                    planet_pixmap = self.load_planet_image(planet_name, size=planet_size)
                    if planet_pixmap:
                        planet_item = QGraphicsPixmapItem(planet_pixmap)
                        planet_item.setPos(x_pos - planet_pixmap.width() / 2,
                                           y_pos - planet_pixmap.height() / 2)
                        planet_item.setZValue(51)
                        planet_item.setData(Qt.ItemDataRole.UserRole, "center_preview")

                        shadow_effect = self._create_shadow_effect(planet_name=planet_name)
                        if shadow_effect:
                            planet_item.setGraphicsEffect(shadow_effect)
                            del shadow_effect

                        self.scene.addItem(planet_item)

                    name_text = QGraphicsTextItem(planet_name[:3])
                    # SPEC-THM-001 G01: live theme color (was QColor(TEXT_PRIMARY))
                    name_text.setDefaultTextColor(QColor(get_theme_colors()["secondary_text"]))
                    name_text.setFont(QFont(FONT_CHART, int(11 * scale), QFont.Weight.Bold))
                    name_width = name_text.boundingRect().width()
                    name_text.setPos(x_pos - name_width / 2, y_pos + planet_size / 2 + 5)
                    name_text.setZValue(51)
                    name_text.setData(Qt.ItemDataRole.UserRole, "center_preview")
                    self.scene.addItem(name_text)

                    deg, mins = self._planet_deg_min(planet)
                    degree_text = QGraphicsTextItem(f"{deg}° {mins}'")
                    # SPEC-THM-001 G01b: live theme color (was QColor(TEXT_SECONDARY))
                    degree_text.setDefaultTextColor(QColor(get_theme_colors()["secondary_text"]))
                    degree_text.setFont(QFont(FONT_CHART, int(10 * scale)))
                    deg_width = degree_text.boundingRect().width()
                    degree_text.setPos(x_pos - deg_width / 2, y_pos + planet_size / 2 + 28)
                    degree_text.setZValue(51)
                    degree_text.setData(Qt.ItemDataRole.UserRole, "center_preview")  # Tag for removal
                    self.scene.addItem(degree_text)
            # Empty signs show nothing (cleaner look)

    def _hide_center_preview(self):
        """Remove all center preview items using Qt's item tagging"""
        # Find all items tagged as "center_preview" and remove them
        items_to_remove = [
            item for item in self.scene.items()
            if item.data(Qt.ItemDataRole.UserRole) == "center_preview"
        ]
        for item in items_to_remove:
            self.scene.removeItem(item)

        self.current_hover_sign = None

    # ------------------------------------------------------------------
    # Z6b sign-selector dispatcher and Mode 2 (mini North Indian)
    # ------------------------------------------------------------------

    def set_z6b_selection(self, sign_index_1based):
        """Receive the Z6b column's selection state and switch center modes.

        Args:
            sign_index_1based: 1..12 to render Mode 2 with that sign as the
                forced Lagna; None to clear and resume Mode 1 hover preview.
        """
        self.selected_z6b_sign = sign_index_1based

        # Always clear BOTH modes' items before re-rendering. This handles
        # all three transitions cleanly:
        #   Mode 1 -> Mode 2  : clears the hover preview underneath
        #   Mode 2 -> Mode 2  : clears the previous mini-chart pixmap, fixing
        #                       the "planet placements stack on each click" bug
        #   Mode 2 -> Mode 1  : clears the mini chart so hover can re-arm
        self._hide_center_preview()
        self._hide_mini_north_indian()

        if sign_index_1based is None:
            return
        if self.time_adjust_mode:
            return
        if self._transit_overlay_active:
            return

        self._show_mini_north_indian(sign_index_1based - 1)

    def notify_zodiac_changed(self):
        """Re-render Mode 2 when the Z4 zodiac radio (aditya_mode) changes.

        Called by the parent GUI after switching aditya_mode between
        'zodiac' / 'classic' / 'sidereal'. Idempotent and a no-op when
        Mode 2 is not active.
        """
        if self.selected_z6b_sign is None or self.time_adjust_mode:
            return
        self._hide_mini_north_indian()
        self._show_mini_north_indian(self.selected_z6b_sign - 1)

    def _show_mini_north_indian(self, lagna_zodiac_idx):
        """Render Mode 2: a mini North Indian chart in the 2x2 center.

        Args:
            lagna_zodiac_idx: 0-based Aditya sign index to force as H1.
        """
        if not self._chart:
            return

        if self._mini_north_indian_view is None:
            from apps.widgets.north_indian_view import NorthIndianView
            self._mini_north_indian_view = NorthIndianView()

        miniview = self._mini_north_indian_view
        miniview.use_western_names = self.use_western_names
        miniview.ascendant_override = lagna_zodiac_idx
        miniview.update_from_chart(self._chart, varga_code=self._varga_code,
                                   use_western_names=self.use_western_names)

        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPixmap, QPainter
        render_size = miniview.chart_size
        pixmap = QPixmap(int(render_size), int(render_size))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        source_rect = QRectF(0.0, 0.0, float(render_size), float(render_size))
        target_rect = QRectF(0.0, 0.0, float(render_size), float(render_size))
        miniview.scene.render(painter, target_rect, source_rect)
        painter.end()

        from PySide6.QtWidgets import QGraphicsPixmapItem
        x1 = self.cell_size
        y1 = self.cell_size
        target_size = self.cell_size * 2
        scale_factor = target_size / render_size

        pixmap_item = QGraphicsPixmapItem(pixmap)
        pixmap_item.setPos(x1, y1)
        pixmap_item.setScale(scale_factor)
        pixmap_item.setZValue(50)
        pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        pixmap_item.setData(Qt.ItemDataRole.UserRole, "center_mode2")
        self.scene.addItem(pixmap_item)
        del pixmap_item  # Rule #18: Qt now owns it; drop the Python ref.

    def _hide_mini_north_indian(self):
        """Remove all Mode 2 items using Qt's item tagging."""
        items_to_remove = [
            item for item in self.scene.items()
            if item.data(Qt.ItemDataRole.UserRole) == "center_mode2"
        ]
        for item in items_to_remove:
            self.scene.removeItem(item)

    # ------------------------------------------------------------------
    #  Transit overlay (center box Mode 3)
    # ------------------------------------------------------------------

    def update_transit_overlay(self, manager):
        """Receive transit state from TransitOverlayManager via mediator."""
        self._transit_manager = manager
        if manager.transit_enabled:
            self._transit_overlay_active = True
            self._hide_center_preview()
            self._hide_mini_north_indian()
            self._show_transit_overlay(manager)
        else:
            self._transit_overlay_active = False
            self._hide_transit_overlay()
            if self.selected_z6b_sign is not None:
                self._show_mini_north_indian(self.selected_z6b_sign - 1)

    def _show_transit_overlay(self, manager):
        """Render a mini transit SI chart in the 2x2 center box."""
        if manager.transit_chart is None:
            return

        self._hide_transit_overlay()

        if self._mini_transit_si_view is None:
            self._mini_transit_si_view = SouthIndianView(
                center_box_enabled=False
            )
            self._mini_transit_si_view.setAttribute(
                Qt.WidgetAttribute.WA_DontShowOnScreen
            )

        miniview = self._mini_transit_si_view

        is_dark = self.bg_color.lightnessF() < 0.5
        if is_dark:
            miniview._load_background("stone_01")
            miniview.bg_color = QColor("#F5F5F5")
            miniview.text_color = QColor("#1A1A2E")
        else:
            miniview._load_background("stone_06")
            miniview.bg_color = QColor("#1A1A2E")
            miniview.text_color = QColor("#E0E0E0")

        miniview.update_from_chart(
            manager.transit_chart,
            aditya_mode=self.aditya_mode,
            use_western_names=self.use_western_names,
        )

        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPixmap, QPainter
        render_size = miniview.chart_size
        pixmap = QPixmap(int(render_size), int(render_size))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        source_rect = QRectF(0.0, 0.0, float(render_size), float(render_size))
        target_rect = QRectF(0.0, 0.0, float(render_size), float(render_size))
        miniview.scene.render(painter, target_rect, source_rect)
        painter.end()

        from PySide6.QtWidgets import QGraphicsPixmapItem
        x1 = self.cell_size
        y1 = self.cell_size
        target_size = self.cell_size * 2
        scale_factor = target_size / render_size

        pixmap_item = QGraphicsPixmapItem(pixmap)
        pixmap_item.setPos(x1, y1)
        pixmap_item.setScale(scale_factor)
        pixmap_item.setZValue(52)
        pixmap_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation
        )
        pixmap_item.setData(Qt.ItemDataRole.UserRole, "center_transit")
        self.scene.addItem(pixmap_item)
        del pixmap_item
        self.scene.update()
        self.viewport().update()

    def _hide_transit_overlay(self):
        """Remove all transit overlay items using Qt's item tagging."""
        items_to_remove = [
            item for item in self.scene.items()
            if item.data(Qt.ItemDataRole.UserRole) == "center_transit"
        ]
        for item in items_to_remove:
            self.scene.removeItem(item)
