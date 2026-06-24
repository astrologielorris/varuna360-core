#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Wheel Chart View Widget
Circular zodiac wheel using PySide6 QGraphicsView.

Features:
- 12 colored zodiac sectors with element colors
- Ascendant rotation (ASC at 9 o'clock / LEFT)
- Planet icons with collision avoidance
- Degree ruler with tick marks
- Zoom and pan support
- Click on planets for info dialog

Ported from visualizations/wheel_chart.py (Tkinter) to Qt.
"""
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPathItem
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QPainter, QFont, QPainterPath

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Import wheel items
from .wheel_items import (
    WheelPlanetClickSignal, ZodiacSectorItem, ZodiacSymbolItem,
    SignNameItem, DegreeTickItem, PlanetItem, PlanetIndicatorLine,
    HouseCuspMarker, HouseNumberItem, CenterCircleItem,
    BackgroundCircleItem, SectorDividerLine, AscendantGlowItem,
    TropicalOuterRimBackground, TropicalSectorDivider, TropicalZodiacSymbolItem,
    OuterRimAscendantMarker, OuterRimAscendantGlow, OuterRimAscendantLabel,
    RetinueRingSector, RetinueRingLabel, HouseHoverSignal, RetinueHoverSignal,
    RetinueClickSignal, WheelSignClickSignal,
    TrimsamshaDegreeTick
)

# Import shared zodiac renderer (pure functions used by both main wheel and mini wheel)
from .zodiac_renderer import (
    draw_ascendant_glow, draw_zodiac_sectors, draw_sector_dividers,
    draw_zodiac_icons, draw_sign_names, draw_center_circle,
    draw_house_numbers, draw_whole_sign_dividers,
    load_zodiac_icon as _load_zodiac_icon
)

# Import theme
from ui.qt_theme import BG, SURFACE, TEXT_PRIMARY, get_theme_colors

# Import geometry helpers (reuse from existing wheel)
from visualizations.wheel_geometry import (
    calculate_rotation_offset, polar_to_cartesian,
    get_sector_center_angle, get_sector_start_angle,
    get_planet_angle, degrees_to_sign_position
)

# Import constants (reuse from existing wheel)
from visualizations.wheel_constants import (
    WHEEL_RADII, ADITYA_NAMES, ZODIAC_SYMBOLS, ZODIAC_NAMES,
    DISPLAY_PLANETS, get_element_color, get_aditya_name, get_zodiac_symbol
)
from core.aditya_mode import get_planet_display_name

# Retinue data loaded lazily (defers AI_tools + libaditya.constants at startup, RPI-PERF-B)
_retinue_module = None

def _get_retinue():
    global _retinue_module
    if _retinue_module is None:
        from AI_tools.AI_main_function import retinue as _r
        _retinue_module = _r
    return _retinue_module


class WheelScene(QGraphicsScene):
    """
    Graphics scene for the wheel chart.

    Uses NoIndex item indexing to prevent Qt BSP tree corruption.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Disable BSP tree indexing to prevent segfaults (Qt Forum #71316)
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)


class WheelView(QGraphicsView):
    """
    Circular zodiac wheel view.

    Main features:
    - Rotates so Ascendant is always at LEFT (9 o'clock)
    - Element-colored sectors (Fire/Earth/Air/Water)
    - Planet icons with global collision avoidance
    - Zoom with mouse wheel, pan with drag
    - Click planets to show info dialog
    """

    # Aditya names (for house calculation)
    ADITYA_NAMES = [
        "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
        "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
    ]

    # Western names for icon filenames (same as SouthIndianView)
    WESTERN_NAMES = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    _TRANSIT_PLANET_NAMES = frozenset({
        "Sun", "Moon", "Mars", "Mercury", "Jupiter",
        "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto",
    })
    _OUTER_RIM_PLANET_NAMES = frozenset({
        "Sun", "Moon", "Mars", "Mercury", "Jupiter",
        "Venus", "Saturn", "Rahu", "Ketu",
    })

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create scene
        self.scene = WheelScene(self)
        self.setScene(self.scene)

        # Wheel dimensions - USE 2048px like SouthIndianView for high quality icons
        # Original wheel_constants are for 800px, scale factor = 2048/800 = 2.56
        self.wheel_size = 2048
        self.cx = self.wheel_size / 2  # 1024
        self.cy = self.wheel_size / 2  # 1024

        # Scale factor from original 800px constants to 2048px
        scale = self.wheel_size / 800.0  # 2.56

        # Ring radii - scaled up from wheel_constants (originally for 800px)
        self.r_outer = int(WHEEL_RADII["outer"] * scale)     # 360 * 2.56 = 922
        self.r_middle = int(WHEEL_RADII["middle"] * scale)   # 300 * 2.56 = 768
        self.r_inner = int(WHEEL_RADII["inner"] * scale)     # 220 * 2.56 = 563
        self.r_planets = int(WHEEL_RADII["planets"] * scale) # 190 * 2.56 = 486
        self.r_center = int(WHEEL_RADII["center"] * scale)   # 80 * 2.56 = 205

        # Zoom settings - start more zoomed out since wheel is now larger
        self.zoom_factor = 0.45  # Initial value; overwritten by _compute_fit_zoom on first show
        self._fit_zoom_applied = False  # Guard: auto-fit only fires once (first show)
        self.min_zoom = 0.2
        self.max_zoom = 3.0
        self.zoom_step = 1.15

        # Chart-first data (Issue 20)
        self._chart = None
        self._varga_code = None
        self._planets = None
        self._cusps = None
        self._aditya_mode = "aditya"
        self._house_system_code = "C"  # SPEC-HSY-001: SE code for cusp labels/transit
        self._wheel_house_display = "sign_based"  # SPEC-WHD-001

        self._has_chart = False
        # Deprecated — kept for set_planets_data() compat until Issue 11
        self.planets_data = None
        self.aditya_mode = "aditya"
        self.ayanamsa_offset = 0.0
        self.use_western_names = False
        self.sign_language = "en"
        self.show_planet_names = False
        self.rotation_offset = 0.0

        # Show outer planets toggle
        self.show_outer_planets = True  # Default ON

        # Show Tropical outer rim (dual rim mode)
        self.show_tropical_rim = False

        # Show Transit outer rim (current planetary positions)
        self.show_transit_rim = False
        self._transit_planets = None
        self._transit_cusps = None
        self._outer_rim_chart = None
        self._outer_rim_planets = None
        self._outer_rim_cusps = None

        # Custom outer rim data (e.g., eclipse chart overlay)
        self.custom_outer_rim_data = None
        self.show_custom_outer_rim = False

        # Show Retinue outer rings (Hora + Trimsamsa)
        self.show_retinue_rings = False
        self.show_trimsamsha_degrees = False
        self._retinue_dirty = False
        self._retinue_sectors = {}
        self._house_number_items = {}
        self._zodiac_sector_items = {}
        self._highlighted_house = None
        self._highlighted_sector = None
        self._original_shadows = {}

        # Hover signals for retinue rings (created once, reused across draw_wheel calls)
        self._house_hover_signal = HouseHoverSignal()
        self._house_hover_signal.hover_enter.connect(self._on_house_hover_enter)
        self._house_hover_signal.hover_leave.connect(self._on_house_hover_leave)
        self._retinue_hover_signal = RetinueHoverSignal()
        self._retinue_hover_signal.hover_enter.connect(self._on_sector_hover_enter)
        self._retinue_hover_signal.hover_leave.connect(self._on_sector_hover_leave)
        self._retinue_click_signal = RetinueClickSignal()

        # Cusp glow lines mode: 0=OFF, 1=Angles only, 2=All cusps (F9)
        self.cusp_glow_mode = 0

        # Show element pie charts (toggle via Shift+F5)
        self.show_element_pies = True

        # Ascendant override for "Sign as Ascendant" feature (F4)
        # None = use actual birth Ascendant, 0-11 = use that sign index as Ascendant
        self.ascendant_override = None

        # Planet click signal
        self.planet_click_signal = WheelPlanetClickSignal()
        self.sign_click_signal = WheelSignClickSignal()

        # Load variation settings from settings.json (same source as SouthIndianView)
        self.variation_settings = self._load_variation_settings()
        self.planet_variation_settings = self._load_planet_variation_settings()

        # Load display settings (font size, color, offsets)
        self.display_settings = self._load_display_settings()

        # Setup view
        self._setup_view()

        # Set scene rect - must accommodate outer rims (retinue+transit extends to r_outer+500)
        # Max extent from center: 1024 + 1272 = 2296, need padding beyond wheel_size/2
        padding = 400  # Larger padding for retinue + outer rim features
        self.setSceneRect(-padding, -padding,
                         self.wheel_size + padding * 2,
                         self.wheel_size + padding * 2)

    def _load_variation_settings(self):
        """Load zodiac icon variation settings from SettingsManager."""
        from managers.settings_manager import get_settings
        try:
            return get_settings().get("display.zodiac_variations", {})
        except Exception as e:
            print(f"[WHEEL] Warning: Could not load zodiac variation settings: {e}")
        return {}

    def _load_planet_variation_settings(self):
        """Load planet icon variation settings from SettingsManager."""
        from managers.settings_manager import get_settings
        try:
            return get_settings().get("display.planet_variations", {})
        except Exception as e:
            print(f"[WHEEL] Warning: Could not load planet variation settings: {e}")
        return {}

    def _load_display_settings(self) -> dict:
        """Load wheel display settings (font size, color, offsets, planet sizes)."""
        from managers.settings_manager import get_settings
        settings = get_settings()
        return settings.get_wheel_display()

    def reload_display_settings(self):
        """Reload display settings and redraw chart."""
        self.display_settings = self._load_display_settings()
        # Clear icon caches since planet sizes may have changed
        self.planet_icons = {}
        if self._chart:
            self.draw_wheel()

    def get_zodiac_variation(self, zodiac_index: int) -> int:
        """Get the selected variation number for a zodiac sign."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        return self.variation_settings.get(western_name, 1)

    def get_planet_variation(self, planet_name: str) -> int:
        """Get the selected variation number for a planet."""
        return self.planet_variation_settings.get(planet_name, 1)

    def reload_settings(self):
        """Reload variation settings and redraw (call after settings change)."""
        self.variation_settings = self._load_variation_settings()
        self.planet_variation_settings = self._load_planet_variation_settings()
        self.display_settings = self._load_display_settings()
        # Clear icon caches
        self.zodiac_icons = {}
        self.planet_icons = {}
        if self._chart:
            self.draw_wheel()

    def load_zodiac_icon(self, zodiac_index: int, size: int = 64):
        """Load zodiac icon — delegates to shared zodiac_renderer function."""
        if not hasattr(self, 'zodiac_icons'):
            self.zodiac_icons = {}
        return _load_zodiac_icon(zodiac_index, size,
                                 self.variation_settings, self.zodiac_icons)

    def load_planet_image(self, planet_name: str, size: int = 48):
        """
        Load planet image using Qt best practices for quality.

        COPIED FROM SouthIndianView - exact same pattern for consistency.
        Uses variation from settings.json.
        """
        from PySide6.QtGui import QImage, QPixmap

        # Planet icon filename mapping (same as SouthIndianView)
        PLANET_ICON_NAMES = {
            "Sun": "sun", "Moon": "moon", "Mars": "Mars",
            "Mercury": "Mercury", "Jupiter": "Jupiter", "Venus": "Venus",
            "Saturn": "Saturn", "Rahu": "rahu", "Ketu": "ketu",
            "Uranus": "uranus", "Neptune": "neptune", "Pluto": "pluto",
        }

        # Get selected variation for this planet
        variation = self.get_planet_variation(planet_name)

        # Cache key includes variation
        cache_key = f"{planet_name}_v{variation}_{size}"

        if not hasattr(self, 'planet_icons'):
            self.planet_icons = {}

        if cache_key in self.planet_icons:
            return self.planet_icons[cache_key]

        icon_filename = PLANET_ICON_NAMES.get(planet_name, planet_name.lower())

        # Try variation-specific file first (e.g., sun2.png for variation 2)
        if variation > 1:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}{variation}.webp"
        else:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        # Fallback to default if variation doesn't exist
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            print(f"[WHEEL] Warning: Planet icon not found: {icon_path}")
            self.planet_icons[cache_key] = None
            return None

        try:
            # Step 1: Load with QImage (best for I/O)
            qimage = QImage(str(icon_path))
            if qimage.isNull():
                print(f"[WHEEL] Warning: Failed to load image: {icon_path}")
                self.planet_icons[cache_key] = None
                return None

            # Step 2: Scale to LOGICAL size with smooth transformation
            qimage = qimage.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # Step 3: Convert to QPixmap
            pixmap = QPixmap.fromImage(qimage)

            self.planet_icons[cache_key] = pixmap
            return pixmap
        except Exception as e:
            print(f"[WHEEL] Error loading planet image {planet_name}: {e}")
            self.planet_icons[cache_key] = None
            return None

    def _setup_view(self):
        """Configure view settings."""
        # Enable anti-aliasing
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Enable scroll/pan
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Drag to pan
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        # Track drag state for cursor changes
        self._is_dragging = False

        # Arrow cursor by default (planets override with pointer)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        # Enable mouse tracking for hover
        self.setMouseTracking(True)
        # StrongFocus required so keyPressEvent receives +/- zoom shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Background color — live theme (SPEC-THM-001 G03)
        self.setBackgroundBrush(QBrush(QColor(get_theme_colors()["secondary_dark"])))

    def _compute_fit_zoom(self):
        """Return zoom factor that fits the full wheel in the current viewport."""
        vp = self.viewport().size()
        side = min(vp.width(), vp.height())
        if side < 100:
            return 0.45  # viewport not laid out yet — safe fallback
        return max(self.min_zoom, min(self.max_zoom, side / self.wheel_size * 0.92))

    def _apply_fit_zoom(self):
        """Deferred auto-fit — runs after Qt event loop processes layout (viewport size valid)."""
        if self._fit_zoom_applied:
            return
        self._fit_zoom_applied = True
        self.zoom_factor = self._compute_fit_zoom()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.cx, self.cy)

    def showEvent(self, event):
        """On first show: defer auto-fit via timer. On tab switch: re-apply current zoom."""
        super().showEvent(event)
        if not self._fit_zoom_applied:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._apply_fit_zoom)
        else:
            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)
            self.centerOn(self.cx, self.cy)

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
        """Reset zoom to fit the full wheel in the current viewport."""
        self.zoom_factor = self._compute_fit_zoom()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.cx, self.cy)

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

    def mousePressEvent(self, event):
        """Handle mouse press - always start panning (single click never opens dialogs)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def _get_sign_at_position(self, pos):
        """Determine which zodiac sign (0-11) is at the given viewport position."""
        scene_pos = self.mapToScene(pos)
        dx = scene_pos.x() - self.cx
        dy = -(scene_pos.y() - self.cy)
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < self.r_center or dist > self.r_outer + 40:
            return None
        angle_deg = math.degrees(math.atan2(dy, dx)) % 360
        asc_deg = self._get_effective_ascendant_degrees()
        zodiac_long = (asc_deg + (angle_deg - 180)) % 360
        return int(zodiac_long / 30) % 12

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open planet info or sector info dialog."""
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.items(event.pos()):
                if isinstance(item, PlanetItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.planet_name, item.planet_info)
                    event.accept()
                    return
                if isinstance(item, RetinueRingSector):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    key = getattr(item, '_sector_key', None)
                    click_sig = getattr(self, '_retinue_click_signal', None)
                    if key and click_sig:
                        sign, ring, btype = key
                        click_sig.clicked.emit(sign, ring, btype)
                    event.accept()
                    return
            sign_idx = self._get_sign_at_position(event.pos())
            if sign_idx is not None:
                self._is_dragging = False
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                var = self.variation_settings.get(sign_idx, 1)
                self.sign_click_signal.clicked.emit(sign_idx, var)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to restore cursor."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def set_planets_data(self, planets_data: dict):
        """Deprecated — use update_from_chart(). Kept until Issue 11."""
        self.planets_data = planets_data
        self._has_chart = bool(planets_data)

    def update_from_chart(self, chart, varga_code=None, use_western_names=False, aditya_mode=None,
                          house_system_code=None, **_kw):
        """Render wheel from a libaditya Chart (primary entry point)."""
        from libaditya.objects.context import Circle
        self._chart = chart
        self._varga_code = varga_code
        self._has_chart = True
        self.planets_data = True
        if aditya_mode is not None:
            self._aditya_mode = aditya_mode
        else:
            self._aditya_mode = "aditya" if chart.context.circle == Circle.ADITYA else "tropical_classic"
        # SPEC-HSY-001: the Chart carries its own house system code; prefer an
        # explicit override but fall back to the chart so labels match the cusps.
        self._house_system_code = house_system_code if house_system_code is not None \
            else (getattr(chart.context, 'hsys', 'C') or 'C')
        source = chart.varga(varga_code) if varga_code and varga_code != 1 else chart.rashi()
        self._planets = source.planets()
        self._cusps = source.cusps()
        self.use_western_names = use_western_names
        self._calculate_rotation()
        self.draw_wheel()

    def set_outer_rim_chart(self, chart, varga_code=None):
        """Set outer rim from a Chart, storing Planet objects for mode-aware drawing."""
        source = chart.varga(varga_code) if varga_code and varga_code != 1 else chart.rashi()
        self._outer_rim_chart = chart
        self._outer_rim_planets = source.planets()
        self._outer_rim_cusps = source.cusps()
        self.custom_outer_rim_data = None
        self.show_custom_outer_rim = True
        self.show_transit_rim = False
        self._transit_planets = None

    def update_outer_rim_from_chart(self, chart, varga_code=None):
        """Legacy wrapper — delegates to set_outer_rim_chart."""
        self.set_outer_rim_chart(chart, varga_code=varga_code)

    def connect_gui(self, gui):
        """Wire up GUI signals for live transit refresh and mode changes."""
        self._gui = gui
        if hasattr(gui, 'aditya_mode_changed'):
            gui.aditya_mode_changed.connect(self._on_aditya_mode_changed)

    def _on_aditya_mode_changed(self, new_mode):
        """Rebuild wheel when zodiac mode changes (pies, transit rim, labels)."""
        self._aditya_mode = new_mode
        if self._chart:
            self.draw_wheel()

    def update_transit_from_manager(self, manager):
        """Consume shared transit state from TransitOverlayManager."""
        if manager.transit_enabled:
            self._transit_planets = manager.transit_planets
            self._transit_cusps = manager.transit_cusps
            self.show_transit_rim = True
        else:
            self._transit_planets = None
            self._transit_cusps = None
            self.show_transit_rim = False
        if self._chart:
            self.draw_wheel()
            self.ensure_visible()

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
        self.centerOn(self.cx, self.cy)

    def refresh_theme(self):
        """Re-apply theme colors (SPEC-THM-001 W1 G03).

        Updates the scene background brush and re-draws the wheel so existing
        items pick up the new theme. Pre-mortem P-002/P-003 mitigation.
        """
        theme = get_theme_colors()
        self.setBackgroundBrush(QBrush(QColor(theme["secondary_dark"])))
        if self._chart is not None:
            try:
                self.draw_wheel()
            except Exception:
                pass
        self.scene.update()
        self.viewport().update()

    def set_aditya_mode(self, mode: str, ayanamsa_offset: float = 0.0):
        """Deprecated — mode is baked into Chart at construction. Kept until Issue 11."""
        self.aditya_mode = mode
        self.ayanamsa_offset = ayanamsa_offset
        if self._chart:
            self._calculate_rotation()
            self.draw_wheel()

    def set_use_western_names(self, use_western: bool):
        """
        Set sign name display preference.

        Args:
            use_western: True for Western names (Aries, Taurus...),
                        False for Aditya names (Dhata, Aryama...)
        """
        self.use_western_names = use_western
        # Note: Redraw will happen in set_planets_data() call

    def set_show_tropical_rim(self, show: bool):
        """
        Set whether to show the outer Tropical rim (dual rim mode).

        Args:
            show: True to show outer Tropical rim on top of Aditya wheel
        """
        self.show_tropical_rim = show
        # Note: Caller should call draw_wheel() to redraw

    def set_show_retinue_rings(self, show: bool):
        """
        Toggle Hora + Trimsamsa outer rings visibility.
        Mutually exclusive with tropical/custom rims (but NOT transit).

        Args:
            show: True to show retinue rings on wheel
        """
        self.show_retinue_rings = show
        if show:
            self.show_tropical_rim = False
            self.show_custom_outer_rim = False
        # Note: Caller should call draw_wheel() to redraw

    def set_cusp_glow_mode(self, mode: int):
        """Cycle cusp glow lines: 0=OFF, 1=Angles only, 2=All 12 cusps."""
        self.cusp_glow_mode = mode % 3
        self.draw_wheel()

    def set_house_display_mode(self, mode):
        if mode not in ("sign_based", "standard_western"):
            mode = "sign_based"
        self._wheel_house_display = mode
        if self._chart:
            self.draw_wheel()

    @property
    def _effective_house_display(self):
        if self.ascendant_override is not None:
            return "sign_based"
        return self._wheel_house_display

    def set_show_transit_rim(self, show: bool):
        """Set whether to show the outer Transit rim.

        Passive setter for rendering toggle. Timer and calculation are
        owned by TransitOverlayManager; use update_transit_from_manager()
        for full state updates.
        """
        self.show_transit_rim = show
        if not show:
            self._transit_planets = None
            self._transit_cusps = None

    def set_outer_rim_data(self, planets_data: dict = None):
        """
        Set custom planetary data to display on the outer rim.

        This allows overlaying any chart (e.g., eclipse chart) on the wheel,
        similar to transit display but with arbitrary data instead of "now".

        Args:
            planets_data: Planet position dictionary (same format as update_from_chart),
                         or None to disable custom outer rim
        """
        self.custom_outer_rim_data = planets_data
        self.show_custom_outer_rim = planets_data is not None
        self._outer_rim_planets = None
        self._outer_rim_cusps = None

        # Disable transit rim when custom rim is active (they share the same visual space)
        if self.show_custom_outer_rim:
            self.show_transit_rim = False
            self._transit_planets = None

        # Note: Caller should call draw_wheel() to redraw

    def set_ascendant_override(self, sign_index: int = None):
        """
        Set Ascendant override for chart display.

        Used by F3 "Cycle Sign as Ascendant" feature to visualize
        the chart as if any sign were the Ascendant.

        Args:
            sign_index: 0-11 for sign override (0=Dhata/Aries, 11=Parjanya/Pisces),
                       None for actual birth Ascendant
        """
        self.ascendant_override = sign_index
        if self._chart:
            self._calculate_rotation()
            self.draw_wheel()

    def _get_effective_ascendant_sign_index(self) -> int:
        """Get Ascendant sign index (0-11). Supports F4 override."""
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

    def _get_effective_ascendant_degrees(self) -> float:
        """Get Ascendant degrees for wheel rotation. Supports F4 override."""
        if self.ascendant_override is not None:
            return (self.ascendant_override % 12) * 30 + 15
        if not self._cusps:
            return 0.0
        asc = self._cusps[1]
        return (asc.sign() - 1) * 30 + asc.real_in_sign_longitude()

    def _calculate_rotation(self):
        """Calculate rotation offset to place Ascendant at LEFT (9 o'clock).

        Uses _get_effective_ascendant_degrees() to support ascendant override
        for the "Sign as Ascendant" feature (F4).
        """
        asc_deg = self._get_effective_ascendant_degrees()
        self.rotation_offset = calculate_rotation_offset(asc_deg)

    def draw_wheel(self):
        """Main drawing method - draws all wheel components."""
        self._retinue_sectors = {}
        self._house_number_items = {}
        self._zodiac_sector_items = {}
        self._highlighted_house = None
        self._highlighted_sector = None
        self._original_shadows = {}
        self.scene.clear()

        # Layer 1: Background circle
        self._draw_background()

        # Layer 2: Ascendant glow (before sectors)
        self._draw_ascendant_glow()

        # Layer 3: Colored zodiac sectors
        self._draw_zodiac_sectors()

        # Layer 4: Sector divider lines
        self._draw_sector_lines()

        # Layer 5: Zodiac symbols (outer ring)
        self._draw_zodiac_symbols()

        # Layer 6: Degree ruler (hidden when retinue rings active)
        if not self.show_retinue_rings:
            self._draw_degree_ruler()

        # Layer 7: Sign names (middle ring)
        self._draw_sign_names()

        # Layer 8: Center circle with house divisions (mode-dependent)
        self._draw_center()
        if self._effective_house_display == "sign_based":
            self._draw_whole_sign_sectors()
        else:
            self._draw_cusp_divider_lines()

        # Layer 9: House numbers in center (hover signal created once in __init__)
        if self.show_retinue_rings:
            self._draw_house_numbers(hover_signal=self._house_hover_signal)
        else:
            self._draw_house_numbers()

        # Layer 9a: Cusp glow lines (behind planets, behind sign icons)
        self._draw_cusp_glow_lines()

        # Layer 10: Planets
        if self._chart:
            self._draw_planets()

        # Layer 11: House cusps (hidden when retinue rings or cusp glow lines active)
        if not self.show_retinue_rings and self.cusp_glow_mode == 0:
            self._draw_house_cusps()

        # Layer 12: Retinue rings — Hora + Trimsamsa (F5)
        if self.show_retinue_rings:
            self._draw_hora_ring()
            self._draw_trimsamsa_ring()
            transit_active = self.show_transit_rim and self._transit_planets
            if not transit_active:
                self._draw_trimsamsha_degree_ruler()

        # Layer 13: Tropical outer rim (dual rim mode, mutually exclusive with retinue)
        if self.show_tropical_rim:
            self._draw_tropical_outer_rim()

        # Layer 14: Transit outer rim (current planetary positions)
        if self.show_transit_rim and self._transit_planets:
            self._draw_transit_outer_rim()

        # Layer 15: Custom outer rim (e.g., eclipse chart overlay)
        if self.show_custom_outer_rim and (self._outer_rim_planets or self.custom_outer_rim_data):
            self._draw_custom_outer_rim()

        # Layer 16: Element distribution pie chart (bottom-right of wheel)
        if self._chart and self.show_element_pies:
            self._draw_element_pie()

        # Expand scene rect to fit all drawn items (pie legends may extend beyond initial padding)
        items_rect = self.scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        current_rect = self.sceneRect()
        self.setSceneRect(current_rect.united(items_rect))

        # Force viewport refresh to ensure chart displays immediately
        self.scene.update()
        self.viewport().update()

    def _draw_background(self):
        """Draw the outer background circle."""
        # +26 scaled from original +10 (factor 2.56)
        item = BackgroundCircleItem(self.cx, self.cy, self.r_outer + 26)
        self.scene.addItem(item)

    def _draw_ascendant_glow(self):
        """Draw glow effect at Ascendant position."""
        draw_ascendant_glow(self.scene, self.cx, self.cy, self.r_middle,
                            glow_radius=102)

    def _draw_zodiac_sectors(self):
        """Draw the 12 colored zodiac sectors."""
        items = draw_zodiac_sectors(self.scene, self.cx, self.cy,
                            self.r_center, self.r_middle,
                            self.rotation_offset)
        if items:
            self._zodiac_sector_items = items

    def _draw_sector_lines(self):
        """Draw radial lines separating sectors."""
        draw_sector_dividers(self.scene, self.cx, self.cy,
                             self.r_center, self.r_outer,
                             self.rotation_offset)

    def _draw_zodiac_symbols(self):
        """Draw zodiac icons on the outer ring (same pattern as SouthIndianView)."""
        symbol_radius = (self.r_outer + self.r_middle) / 2 + 20
        draw_zodiac_icons(self.scene, self.cx, self.cy,
                          symbol_radius, icon_size=192,
                          rotation_offset=self.rotation_offset,
                          icon_loader=self.load_zodiac_icon)

    def _draw_degree_ruler(self):
        """Draw degree tick marks around the outer edge."""
        # All values scaled by 2.56 from original 800px constants
        ruler_outer = self.r_outer + 20       # was +8
        ruler_inner_major = self.r_outer - 31  # was -12 (10° ticks)
        ruler_inner_minor = self.r_outer - 15  # was -6 (5° ticks)
        ruler_inner_micro = self.r_outer - 8   # was -3 (1° ticks when zoomed)

        for deg in range(360):
            visual_angle = (deg + self.rotation_offset) % 360
            deg_in_sign = deg % 30

            if deg_in_sign % 10 == 0:
                # Major tick every 10°
                inner_r = ruler_inner_major
                tick_type = "major"

                # Draw label for 10° and 20°
                if deg_in_sign in [10, 20]:
                    label_r = ruler_outer + 31  # was +12
                    lx, ly = polar_to_cartesian(self.cx, self.cy, label_r, visual_angle)
                    label = QGraphicsTextItem(str(deg_in_sign))
                    label.setFont(QFont("Inter", 18))  # was 7, scaled
                    label.setDefaultTextColor(QColor("#888888"))
                    label.setPos(lx - label.boundingRect().width() / 2,
                                ly - label.boundingRect().height() / 2)
                    label.setZValue(3)
                    self.scene.addItem(label)

            elif deg_in_sign % 5 == 0:
                inner_r = ruler_inner_minor
                tick_type = "minor"
            elif self.zoom_factor >= 1.5:
                inner_r = ruler_inner_micro
                tick_type = "micro"
            else:
                continue

            x1, y1 = polar_to_cartesian(self.cx, self.cy, inner_r, visual_angle)
            x2, y2 = polar_to_cartesian(self.cx, self.cy, ruler_outer, visual_angle)

            item = DegreeTickItem(x1, y1, x2, y2, tick_type)
            self.scene.addItem(item)

    def _draw_sign_names(self):
        """Draw Aditya or Western sign names in the middle ring."""
        name_radius = (self.r_middle + self.r_inner) / 2 + 26
        _mode = self._aditya_mode
        draw_sign_names(self.scene, self.cx, self.cy, name_radius,
                        self.rotation_offset, _mode,
                        self.use_western_names, self.sign_language,
                        self.display_settings)

    def _draw_center(self):
        """Draw the center circle."""
        draw_center_circle(self.scene, self.cx, self.cy, self.r_center)

    def _draw_house_numbers(self, hover_signal=None):
        """Draw house numbers (1-12) in the center circle."""
        if not self._chart:
            return
        asc_deg = self._get_effective_ascendant_degrees()

        cusp_angles = None
        if self._effective_house_display == "standard_western" and self._cusps:
            cusp_angles = []
            for h in range(1, 13):
                cusp = self._cusps[h]
                risl = cusp.amsha_raw_in_sign_longitude() if self._varga_code \
                       else cusp.real_in_sign_longitude()
                cusp_angles.append((cusp.sign() - 1) * 30 + risl)

        items = draw_house_numbers(self.scene, self.cx, self.cy,
                           self.r_center * 0.65, font_size=23,
                           rotation_offset=self.rotation_offset,
                           asc_degrees=asc_deg,
                           hover_signal=hover_signal,
                           cusp_angles=cusp_angles)
        if items:
            self._house_number_items = items

    def _get_house_number_for_sign(self, sign_index: int) -> int:
        """
        Get house number (1-12) for a sign based on Ascendant.

        Uses Whole Sign house system and supports ascendant override.
        """
        asc_sign = self._get_effective_ascendant_sign_index()
        return ((sign_index - asc_sign) % 12) + 1

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

    def _planet_deg_min(self, planet):
        """Extract (degrees, minutes) within sign from a Planet object."""
        risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
        return int(risl), int((risl % 1) * 60)

    def _planet_effective_degrees(self, planet):
        """Get effective wheel degrees for a planet (sign-aware)."""
        return (planet.sign() - 1) * 30 + planet.real_in_sign_longitude()

    def _draw_planets(self):
        """Draw all planets with collision avoidance."""
        if not self._planets:
            return
        planets_to_draw = list(DISPLAY_PLANETS)
        if self.show_outer_planets:
            planets_to_draw.extend(["Uranus", "Neptune", "Pluto"])

        all_planets = []
        for planet_name in planets_to_draw:
            if planet_name == "Ascendant":
                continue
            try:
                planet = self._planets[planet_name]
            except KeyError:
                continue
            deg = self._planet_effective_degrees(planet)
            sign_index = planet.sign() - 1
            risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
            all_planets.append({
                "name": planet_name,
                "degrees": deg,
                "deg_in_sign": risl,
                "sign_index": sign_index,
                "planet_obj": planet,
            })

        # Calculate positions with collision avoidance
        planet_positions = self._calculate_planet_positions(all_planets)

        # Get indicator line settings
        line_settings = self.display_settings.get("indicator_line", {})
        glow_radius = line_settings.get("glow_radius", 40)
        line_width = line_settings.get("line_width", 3)

        # Draw planets
        for planet, (x, y, radius, label_offset) in planet_positions:
            visual_angle = get_planet_angle(planet["degrees"], self.rotation_offset)

            if self.show_retinue_rings:
                # Multi-segment glow: each ring section gets its own element color
                hora_inner = self.r_outer
                hora_outer = self.r_outer + 130
                trim_outer = self.r_outer + 300

                # Segment 1: Planet → zodiac ring edge (D1 sign color)
                d1_ex, d1_ey = polar_to_cartesian(self.cx, self.cy, hora_inner, visual_angle)
                line_d1 = PlanetIndicatorLine(
                    x, y, d1_ex, d1_ey,
                    sign_index=planet["sign_index"],
                    glow_intensity=glow_radius, line_width=line_width
                )
                line_d1.setZValue(3.8)
                self.scene.addItem(line_d1)

                # Segment 2: Hora ring (D2 color — Sun=Fire or Moon=Water)
                hora_ex, hora_ey = polar_to_cartesian(self.cx, self.cy, hora_outer, visual_angle)
                hora_color = self._get_hora_element_color(planet["sign_index"], planet["deg_in_sign"])
                line_hora = PlanetIndicatorLine(
                    d1_ex, d1_ey, hora_ex, hora_ey,
                    color=hora_color,
                    glow_intensity=glow_radius, line_width=line_width
                )
                line_hora.setZValue(3.8)
                self.scene.addItem(line_hora)

                # Segment 3: Trimsamsa ring (D30 element color)
                trim_ex, trim_ey = polar_to_cartesian(self.cx, self.cy, trim_outer, visual_angle)
                trim_color = self._get_trimsamsa_element_color(planet["sign_index"], planet["deg_in_sign"])
                line_trim = PlanetIndicatorLine(
                    hora_ex, hora_ey, trim_ex, trim_ey,
                    color=trim_color,
                    glow_intensity=glow_radius, line_width=line_width
                )
                line_trim.setZValue(3.8)
                self.scene.addItem(line_trim)
            else:
                # Single line to ruler edge (D1 color only)
                rim_radius = self.r_outer + 20
                ruler_x, ruler_y = polar_to_cartesian(self.cx, self.cy, rim_radius, visual_angle)
                line = PlanetIndicatorLine(
                    x, y, ruler_x, ruler_y,
                    sign_index=planet["sign_index"],
                    glow_intensity=glow_radius,
                    line_width=line_width
                )
                self.scene.addItem(line)

            # Load pixmap with size from display settings
            planet_sizes = self.display_settings.get("planet_sizes", {})
            planet_size = planet_sizes.get(planet["name"], 120)  # Default 120px
            pixmap = self.load_planet_image(planet["name"], size=planet_size)
            if pixmap:
                p_obj = planet.get("planet_obj")
                click_dict = self._planet_to_click_dict(planet["name"], p_obj) if p_obj else dict(planet)
                click_dict["sign_index"] = planet["sign_index"]
                click_dict["deg_in_sign"] = planet["deg_in_sign"]
                icon = PlanetItem(pixmap, x, y, planet["name"], click_dict,
                                 self.planet_click_signal)
                self.scene.addItem(icon)

            # Draw degree label below planet (y offset scaled: 20→51)
            self._draw_planet_label(x, y + 51, planet, label_offset)

    def _calculate_planet_positions(self, planets: list) -> list:
        """
        Calculate planet positions with collision avoidance.

        Uses a two-phase approach:
        1. Cluster planets that are within threshold degrees of each other
        2. Spread clustered planets angularly + use radius stacking

        Returns list of (planet_dict, (x, y, radius, label_offset)) tuples.
        """
        if not planets:
            return []

        # Sort by degree for clustering
        planets_sorted = sorted(planets, key=lambda p: p["degrees"])

        # Phase 1: Identify clusters (planets within CLUSTER_THRESHOLD degrees)
        CLUSTER_THRESHOLD = 12  # degrees - planets closer than this form a cluster
        MIN_VISUAL_SEP = 10     # minimum visual separation in degrees after spreading

        clusters = []
        current_cluster = [planets_sorted[0]]

        for i in range(1, len(planets_sorted)):
            prev_deg = planets_sorted[i - 1]["degrees"]
            curr_deg = planets_sorted[i]["degrees"]

            # Handle wrap-around (e.g., 358° and 2°)
            diff = curr_deg - prev_deg
            if diff < 0:
                diff += 360

            if diff <= CLUSTER_THRESHOLD:
                current_cluster.append(planets_sorted[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [planets_sorted[i]]

        clusters.append(current_cluster)

        # Also check wrap-around between last and first cluster
        if len(clusters) > 1:
            first_deg = clusters[0][0]["degrees"]
            last_deg = clusters[-1][-1]["degrees"]
            wrap_diff = (360 - last_deg) + first_deg
            if wrap_diff <= CLUSTER_THRESHOLD:
                # Merge first and last clusters
                clusters[-1].extend(clusters[0])
                clusters = clusters[1:]

        # Phase 2: Calculate spread positions for each cluster
        # Define the FULL available zone for planets - USE MAXIMUM SPACE
        min_r = self.r_center + 90   # Keep clear of house numbers in center
        max_r = self.r_inner - 10    # Very close to sign ring (use that outer space!)

        # Calculate base as CENTER of available zone
        zone_center = (min_r + max_r) / 2
        zone_range = (max_r - min_r) / 2  # Half the zone for +/- offsets

        # Zig-zag order: alternate far-outer, far-inner, mid-outer, mid-inner, center
        # Use 0.95 multiplier to really push to edges
        radii = [
            zone_center + zone_range * 0.95,   # Far outer (very close to sign ring)
            zone_center - zone_range * 0.95,   # Far inner (very close to center)
            zone_center + zone_range * 0.55,   # Mid outer
            zone_center - zone_range * 0.55,   # Mid inner
            zone_center,                        # Center of zone
            zone_center + zone_range * 0.75,   # Upper-mid outer
            zone_center - zone_range * 0.75,   # Lower-mid inner
        ]
        # Clamp to valid range (safety)
        radii = [max(min_r, min(r, max_r)) for r in radii]
        # Remove duplicates while preserving order
        seen = set()
        radii = [r for r in radii if not (r in seen or seen.add(r))]

        planet_positions = []

        for cluster in clusters:
            if len(cluster) == 1:
                # Single planet - place at natural position (center of zone)
                planet = cluster[0]
                visual_angle = get_planet_angle(planet["degrees"], self.rotation_offset)
                x, y = polar_to_cartesian(self.cx, self.cy, zone_center, visual_angle)
                planet_positions.append((planet, (x, y, zone_center, 0)))

            else:
                # Multiple planets - spread them out
                # Sort cluster by original degree for consistent ordering
                cluster_sorted = sorted(cluster, key=lambda p: p["degrees"])

                # Check if cluster spans multiple signs
                signs_in_cluster = set(p["sign_index"] for p in cluster)
                spans_multiple_signs = len(signs_in_cluster) > 1

                if spans_multiple_signs:
                    # SIGN-AWARE MODE: Spread within each sign, don't cross boundaries
                    # Group by sign and place each group within its sign
                    sign_groups = {}
                    for p in cluster_sorted:
                        sign_idx = p["sign_index"]
                        if sign_idx not in sign_groups:
                            sign_groups[sign_idx] = []
                        sign_groups[sign_idx].append(p)

                    # Process each sign group separately
                    radius_counter = 0
                    for sign_idx in sorted(sign_groups.keys()):
                        sign_planets = sign_groups[sign_idx]
                        n_in_sign = len(sign_planets)

                        if n_in_sign == 1:
                            # Single planet in this sign - place at natural position
                            planet = sign_planets[0]
                            visual_angle = get_planet_angle(planet["degrees"], self.rotation_offset)
                            radius = radii[radius_counter % len(radii)]
                            radius_counter += 1
                            x, y = polar_to_cartesian(self.cx, self.cy, radius, visual_angle)
                            planet_positions.append((planet, (x, y, radius, 0)))
                        else:
                            # Multiple planets in this sign - spread within sign bounds
                            # Calculate average position within this sign group
                            group_degs = [p["degrees"] for p in sign_planets]
                            avg_deg = sum(group_degs) / len(group_degs)

                            # Calculate spread needed
                            total_spread = (n_in_sign - 1) * MIN_VISUAL_SEP
                            start_offset = -total_spread / 2

                            # Sign boundaries (keep 2° margin from edges)
                            sign_start = sign_idx * 30 + 2
                            sign_end = (sign_idx + 1) * 30 - 2

                            # Sort by degree within sign group
                            sign_planets_sorted = sorted(sign_planets, key=lambda p: p["degrees"])

                            for i, planet in enumerate(sign_planets_sorted):
                                # Calculate spread angle centered on group average
                                spread_angle = avg_deg + start_offset + (i * MIN_VISUAL_SEP)

                                # Clamp to sign boundaries
                                spread_angle = max(sign_start, min(sign_end, spread_angle))

                                visual_angle = get_planet_angle(spread_angle, self.rotation_offset)

                                # Alternate radii for additional separation
                                radius = radii[radius_counter % len(radii)]
                                radius_counter += 1

                                x, y = polar_to_cartesian(self.cx, self.cy, radius, visual_angle)
                                planet_positions.append((planet, (x, y, radius, 0)))
                else:
                    # SINGLE-SIGN MODE: Safe to spread angularly within the sign
                    # Calculate cluster center (average degree)
                    cluster_degs = [p["degrees"] for p in cluster]

                    # Handle wrap-around for average calculation
                    sin_sum = sum(math.sin(math.radians(d)) for d in cluster_degs)
                    cos_sum = sum(math.cos(math.radians(d)) for d in cluster_degs)
                    avg_deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

                    # Calculate spread: total arc needed = (n-1) * MIN_VISUAL_SEP
                    n = len(cluster)
                    total_spread = (n - 1) * MIN_VISUAL_SEP
                    start_offset = -total_spread / 2

                    # Ensure spread stays within the sign (0-30° within sign)
                    sign_idx = cluster[0]["sign_index"]
                    sign_start = sign_idx * 30
                    sign_end = sign_start + 30

                    for i, planet in enumerate(cluster_sorted):
                        # Calculate spread angle
                        spread_angle = avg_deg + start_offset + (i * MIN_VISUAL_SEP)

                        # Clamp to sign boundaries to prevent crossing
                        spread_angle = max(sign_start + 1, min(sign_end - 1, spread_angle))

                        visual_angle = get_planet_angle(spread_angle, self.rotation_offset)

                        # Alternate radii for additional separation
                        radius_idx = i % len(radii)
                        radius = radii[radius_idx]

                        x, y = polar_to_cartesian(self.cx, self.cy, radius, visual_angle)
                        planet_positions.append((planet, (x, y, radius, 0)))

        return planet_positions

    def _draw_planet_label(self, x: float, y: float, planet: dict, label_offset: float):
        """Draw degree label below a planet using display settings."""
        if self.show_planet_names:
            label_text = get_planet_display_name(
                self.sign_language, planet["name"])
        else:
            deg_in_sign = planet["deg_in_sign"]
            degrees = int(deg_in_sign)
            minutes = int((deg_in_sign - degrees) * 60)
            label_text = f"{degrees}°{minutes:02d}'"

        # Get display settings for planet degrees
        deg_settings = self.display_settings.get("planet_degrees", {})
        font_size = deg_settings.get("font_size", 20)
        font_color = deg_settings.get("font_color", "#CCCCCC")
        font_weight = deg_settings.get("font_weight", "normal")
        offset_x = deg_settings.get("offset_x", 0)
        offset_y = deg_settings.get("offset_y", 0)

        label = QGraphicsTextItem(label_text)
        font = QFont("Inter", font_size)
        if font_weight == "bold":
            font.setBold(True)
        label.setFont(font)
        label.setDefaultTextColor(QColor(font_color))

        # Apply position with offsets
        label.setPos(x - label.boundingRect().width() / 2 + offset_x,
                    y - label.boundingRect().height() / 2 + offset_y)
        label.setZValue(9)
        self.scene.addItem(label)

    def _draw_cusp_glow_lines(self):
        """Draw glowing radial lines for house cusps on the outer rings only.

        Lines start at r_outer (zodiac ring edge) and extend outward — they
        never cross the planet area. In F5 mode, lines continue through
        Hora and Trimsamsa rings with color-coded segments.

        Modes: 0=OFF, 1=Angles only (ASC/IC/DESC/MC), 2=All 12 cusps.
        """
        if self.cusp_glow_mode == 0 or not self._cusps:
            return

        ANGLE_HOUSES = {1, 4, 7, 10}
        ANGLE_LABELS = {1: "ASC", 4: "IC", 7: "DESC", 10: "MC"}
        houses_to_draw = ANGLE_HOUSES if self.cusp_glow_mode == 1 else set(range(1, 13))

        line_settings = self.display_settings.get("indicator_line", {})
        glow = max(3, line_settings.get("glow_radius", 40) // 5)
        width = 1

        for house_num in range(1, 13):
            if house_num not in houses_to_draw:
                continue

            cusp = self._cusps[house_num]
            cusp_deg = (cusp.sign() - 1) * 30 + cusp.real_in_sign_longitude()
            visual_angle = (cusp_deg + self.rotation_offset) % 360
            risl = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
            deg_in_sign = int(risl)
            sign_index = cusp.sign() - 1

            is_angle = house_num in ANGLE_HOUSES
            color = "#FFD700" if is_angle else "#888888"

            # Start from the sign area (r_middle), above the planet ring
            start_r = self.r_middle

            if self.show_retinue_rings:
                hora_inner = self.r_outer
                hora_outer = self.r_outer + 130
                trim_outer = self.r_outer + 300

                # Segment 1: sign area → zodiac ring edge (gold/silver)
                sx, sy = polar_to_cartesian(self.cx, self.cy, start_r, visual_angle)
                d1_ex, d1_ey = polar_to_cartesian(self.cx, self.cy, hora_inner, visual_angle)
                line_d1 = PlanetIndicatorLine(
                    sx, sy, d1_ex, d1_ey,
                    color=color, glow_intensity=glow, line_width=width
                )
                line_d1.setZValue(3.7)
                self.scene.addItem(line_d1)

                # Segment 2: Hora ring (D2 color)
                hora_ex, hora_ey = polar_to_cartesian(self.cx, self.cy, hora_outer, visual_angle)
                hora_color = self._get_hora_element_color(sign_index, deg_in_sign)
                line_hora = PlanetIndicatorLine(
                    d1_ex, d1_ey, hora_ex, hora_ey,
                    color=hora_color, glow_intensity=glow, line_width=width
                )
                line_hora.setZValue(3.7)
                self.scene.addItem(line_hora)

                # Segment 3: Trimsamsa ring (D30 color)
                trim_ex, trim_ey = polar_to_cartesian(self.cx, self.cy, trim_outer, visual_angle)
                trim_color = self._get_trimsamsa_element_color(sign_index, deg_in_sign)
                line_trim = PlanetIndicatorLine(
                    hora_ex, hora_ey, trim_ex, trim_ey,
                    color=trim_color, glow_intensity=glow, line_width=width
                )
                line_trim.setZValue(3.7)
                self.scene.addItem(line_trim)

                label_radius = trim_outer + 40
            else:
                # Line from sign area to beyond zodiac ring
                sx, sy = polar_to_cartesian(self.cx, self.cy, start_r, visual_angle)
                ex, ey = polar_to_cartesian(self.cx, self.cy, self.r_outer + 40, visual_angle)
                line = PlanetIndicatorLine(
                    sx, sy, ex, ey,
                    color=color, glow_intensity=glow, line_width=width
                )
                line.setZValue(3.7)
                self.scene.addItem(line)

                label_radius = self.r_outer + 60

            # Label at the end of the glow line
            if is_angle:
                label_text = f"{ANGLE_LABELS[house_num]} {deg_in_sign}°"
            else:
                label_text = f"C{house_num} {deg_in_sign}°"

            lx, ly = polar_to_cartesian(self.cx, self.cy, label_radius, visual_angle)
            label = QGraphicsTextItem(label_text)
            label.setFont(QFont("Inter", 16))
            label.setDefaultTextColor(QColor("#FFD700" if is_angle else "#AAAAAA"))
            label.setPos(lx - label.boundingRect().width() / 2,
                        ly - label.boundingRect().height() / 2)
            label.setZValue(11)
            self.scene.addItem(label)

    def _draw_cusp_divider_lines(self):
        """Draw cusp-based divider lines from center ring through sign ring.

        SPEC-WHD-001: structural house boundary lines in Western cusp mode.
        Also draws cusp-based dividers inside the center ring (replacing
        the whole-sign dividers from _draw_whole_sign_sectors).
        """
        if not self._cusps:
            return

        for house_num in range(1, 13):
            cusp = self._cusps[house_num]
            risl = cusp.amsha_raw_in_sign_longitude() if self._varga_code \
                   else cusp.real_in_sign_longitude()
            cusp_deg = (cusp.sign() - 1) * 30 + risl
            visual_angle = (cusp_deg + self.rotation_offset) % 360

            color = "#2a2a2e"

            # Line through sign ring: r_center to r_outer. Solid wall (like the
            # sign sector dividers), NOT a glow — a dark color through the
            # PlanetIndicatorLine glow primitive renders invisible. SPEC-WHD-001.
            sx, sy = polar_to_cartesian(self.cx, self.cy, self.r_center, visual_angle)
            ex, ey = polar_to_cartesian(self.cx, self.cy, self.r_outer, visual_angle)
            line = QGraphicsLineItem(sx, sy, ex, ey)
            line.setPen(QPen(QColor(color), 2))
            line.setZValue(1.5)
            self.scene.addItem(line)

            # Divider inside center ring (replaces whole-sign dividers)
            inner_r = self.r_center * 0.3
            outer_r = self.r_center * 0.95
            div = SectorDividerLine(self.cx, self.cy, inner_r, outer_r, visual_angle)
            div.setZValue(6.5)
            self.scene.addItem(div)

    def _draw_house_cusps(self):
        """Draw house cusps on the outer edge (below degree numbers).

        SPEC-HSY-001: cusps come from the active Chart (chart.rashi().cusps()),
        which already reflects the user's house system. Labels are prefixed with
        the system's SE code letter (C/P/K/E/W/O/R).
        """
        if not self._cusps:
            return

        cusp_label_radius = self.r_outer + 130

        for house_num in range(1, 13):
            cusp = self._cusps[house_num]
            cusp_deg = (cusp.sign() - 1) * 30 + cusp.real_in_sign_longitude()
            visual_angle = (cusp_deg + self.rotation_offset) % 360

            x, y = polar_to_cartesian(self.cx, self.cy, cusp_label_radius, visual_angle)

            marker = HouseCuspMarker(
                self.cx, self.cy, self.r_outer + 80,
                visual_angle, house_num, marker_size=20
            )
            self.scene.addItem(marker)

            risl = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
            deg_in_sign = int(risl)
            label_text = f"C{house_num} {deg_in_sign}°"

            label = QGraphicsTextItem(label_text)
            label.setFont(QFont("Inter", 16))

            # Angular houses (1,4,7,10) in gold, others in silver
            if house_num in [1, 4, 7, 10]:
                label.setDefaultTextColor(QColor("#FFD700"))
            else:
                label.setDefaultTextColor(QColor("#AAAAAA"))

            label.setPos(x - label.boundingRect().width() / 2,
                        y - label.boundingRect().height() / 2)
            label.setZValue(11)
            self.scene.addItem(label)

    def _draw_whole_sign_sectors(self):
        """Draw Whole Sign house divisions in the center circle."""
        if not self._chart:
            return
        asc_deg = self._get_effective_ascendant_degrees()
        draw_whole_sign_dividers(self.scene, self.cx, self.cy,
                                 self.r_center * 0.3, self.r_center * 0.95,
                                 self.rotation_offset, asc_deg)

    # ── Retinue Rings (Hora + Trimsamsa) ─────────────────────────

    def _get_aditya_for_sector(self, sector_index: int) -> str:
        """Get the Aditya name for a wheel sector.

        Per SPEC-ZOD-001 §4.2: Division #1 = Dhata in ALL zodiac systems.
        Sector index 0 always maps to Dhata regardless of active zodiac mode.
        The zodiac mode determines WHERE sectors are positioned in the sky,
        not which Aditya they represent.
        """
        return self.ADITYA_NAMES[sector_index % 12]

    def _get_hora_element_color(self, sign_index: int, deg_in_sign: float) -> str:
        """Get the Hora (D2) element color for a planet at a given degree within its sign.

        Odd signs: 0-15° = Sun (Fire), 15-30° = Moon (Water)
        Even signs: 0-15° = Moon (Water), 15-30° = Sun (Fire)
        """
        SUN_COLOR = "#E57373"   # Fire red
        MOON_COLOR = "#1E4D8C"  # Water blue
        _r = _get_retinue()
        aditya_name = self._get_aditya_for_sector(sign_index)
        sign_data = _r.ADITYA_RETINUE.get(aditya_name)
        if not sign_data:
            return SUN_COLOR
        is_odd = sign_data["type"] == "odd"
        in_first_half = deg_in_sign < 15.0
        if is_odd:
            return SUN_COLOR if in_first_half else MOON_COLOR
        else:
            return MOON_COLOR if in_first_half else SUN_COLOR

    def _get_trimsamsa_element_color(self, sign_index: int, deg_in_sign: float) -> str:
        """Get the Trimsamsa (D30) element color for a planet at a given degree within its sign."""
        _r = _get_retinue()
        ELEMENT_BG = {
            "Fire": "#E57373", "Earth": "#8B6340", "Air": "#F0C75E",
            "Water": "#1E4D8C", "Ether": "#3D1A5C",
        }
        aditya_name = self._get_aditya_for_sector(sign_index)
        sign_data = _r.ADITYA_RETINUE.get(aditya_name)
        if not sign_data:
            return "#666666"
        boundaries = _r.TRIMSAMSA_ODD if sign_data["type"] == "odd" else _r.TRIMSAMSA_EVEN
        for start_deg, end_deg, _lord, _type, element in boundaries:
            if start_deg <= deg_in_sign < end_deg:
                return ELEMENT_BG.get(element, "#666666")
        # Fallback: last division (handles deg_in_sign == 30.0 edge case)
        return ELEMENT_BG.get(boundaries[-1][4], "#666666")

    @staticmethod
    def _radial_rotation(mid_angle: float) -> float:
        """Compute rotation for radial text at a given angle.

        Text reads outward from center. In the bottom half (90°-270°),
        text is flipped 180° to avoid being upside-down.
        """
        rotation = -mid_angle
        normalized = mid_angle % 360
        if 90 < normalized < 270:
            rotation += 180
        return rotation

    @staticmethod
    def _abbreviate_being(name: str, max_len: int = 6) -> str:
        """Truncate long being names for narrow ring sectors."""
        if len(name) <= max_len:
            return name
        return name[:max_len - 1] + "."

    def _draw_hora_ring(self):
        """
        Draw the Hora outer ring — 24 sectors (12 signs × 2 halves).

        Each sign is split at 15°:
        - Odd signs: 0-15° = Sun (Aditya), 15-30° = Moon (Naga)
        - Even signs: 0-15° = Moon (Naga), 15-30° = Sun (Aditya)

        Colors: Fire red for Sun side, Water blue for Moon side
        (matching the rasi zodiac sector element colors).
        """
        hora_inner = self.r_outer          # Flush with zodiac ring (no gap)
        hora_outer = self.r_outer + 130     # 130px wide

        # Hora colors — reuse rasi element colors: Fire = Sun, Water = Moon
        SUN_BG, SUN_TEXT = "#E57373", "#1a1a1a"   # Fire red, dark text
        MOON_BG, MOON_TEXT = "#1E4D8C", "#FFFFFF"  # Water blue, white text

        # Load Sun/Moon planet icons for sector labels
        sun_icon = self.load_planet_image("Sun", size=60)
        moon_icon = self.load_planet_image("Moon", size=60)

        # Background annulus
        bg = TropicalOuterRimBackground(self.cx, self.cy, hora_inner, hora_outer)
        bg.setZValue(3)
        self.scene.addItem(bg)

        _r = _get_retinue()
        for sign_idx in range(12):
            aditya_name = self._get_aditya_for_sector(sign_idx)
            sign_data = _r.ADITYA_RETINUE.get(aditya_name)
            if not sign_data:
                continue
            is_odd = sign_data["type"] == "odd"

            for half in range(2):  # 0 = first 15°, 1 = second 15°
                start_angle = sign_idx * 30 + half * 15 + self.rotation_offset

                # Odd: first=Sun, second=Moon. Even: first=Moon, second=Sun.
                if is_odd:
                    is_sun = (half == 0)
                else:
                    is_sun = (half == 1)

                bg_color = SUN_BG if is_sun else MOON_BG
                text_color = SUN_TEXT if is_sun else MOON_TEXT

                if is_sun:
                    label = aditya_name
                    tip = f"Sun Hora — {aditya_name} (Aditya side)"
                else:
                    naga = sign_data["naga"]
                    label = naga
                    tip = f"Moon Hora — {naga} (Naga side)"

                # Sector
                key = (aditya_name, "hora", "aditya" if is_sun else "naga")
                hover_sig = getattr(self, '_retinue_hover_signal', None)
                sector = RetinueRingSector(
                    self.cx, self.cy, hora_inner, hora_outer,
                    start_angle, 15, bg_color,
                    hover_signal=hover_sig, sector_key=key
                )
                sector.setToolTip(tip)
                self.scene.addItem(sector)
                self._retinue_sectors[key] = sector

                # Icon and name SIDE BY SIDE along the arc (same radius, different angles)
                mid_r = (hora_inner + hora_outer) / 2  # Both at ring midpoint

                # Icon at one end of the 15° sector (~3° angular footprint)
                icon_angle = start_angle + 3.0
                ix, iy = polar_to_cartesian(self.cx, self.cy, mid_r, icon_angle)
                icon_pixmap = sun_icon if is_sun else moon_icon
                if icon_pixmap:
                    from PySide6.QtWidgets import QGraphicsPixmapItem
                    icon_item = QGraphicsPixmapItem(icon_pixmap)
                    icon_item.setOffset(-icon_pixmap.width() / 2,
                                        -icon_pixmap.height() / 2)
                    icon_item.setPos(ix, iy)
                    icon_item.setZValue(3.9)  # Below zodiac icons (Z=4)
                    icon_item.setAcceptHoverEvents(False)
                    icon_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    self.scene.addItem(icon_item)

                # Text label close to icon (~4° gap center-to-center)
                text_angle = start_angle + 7.0  # Snug next to icon
                lx, ly = polar_to_cartesian(self.cx, self.cy, mid_r, text_angle)
                rotation = self._radial_rotation(text_angle)
                lbl = RetinueRingLabel(label, lx, ly, rotation,
                                       font_size=15, color=text_color)
                self.scene.addItem(lbl)

        # Divider lines at every 15° (Hora boundaries)
        for i in range(24):
            angle = i * 15 + self.rotation_offset
            divider = TropicalSectorDivider(self.cx, self.cy,
                                            hora_inner, hora_outer, angle)
            divider.setZValue(3.8)
            self.scene.addItem(divider)

    def _draw_trimsamsa_ring(self):
        """
        Draw the Trimsamsa outer ring — 60 sectors (12 signs × 5 divisions).

        Each sign has 5 unequal parts (5-5-8-7-5 for odd, 5-7-8-5-5 for even).
        Colors match the rasi zodiac element colors; Ether uses panel violet.
        """
        trim_inner = self.r_outer + 130     # Flush with hora_outer (no gap)
        trim_outer = self.r_outer + 300     # 170px wide

        # Element colors — matching rasi sectors; Earth darkened for flat fill; Ether = panel violet
        ELEMENT_BG = {
            "Fire": "#E57373", "Earth": "#8B6340", "Air": "#F0C75E",
            "Water": "#1E4D8C", "Ether": "#3D1A5C",
        }
        ELEMENT_TEXT = {
            "Fire": "#1a1a1a", "Earth": "#FFFFFF", "Air": "#1a1a1a",
            "Water": "#FFFFFF", "Ether": "#CE93D8",
        }

        # Background annulus
        bg = TropicalOuterRimBackground(self.cx, self.cy, trim_inner, trim_outer)
        bg.setZValue(3)
        self.scene.addItem(bg)

        _r = _get_retinue()
        for sign_idx in range(12):
            aditya_name = self._get_aditya_for_sector(sign_idx)
            sign_data = _r.ADITYA_RETINUE.get(aditya_name)
            if not sign_data:
                continue

            boundaries = _r.TRIMSAMSA_ODD if sign_data["type"] == "odd" else _r.TRIMSAMSA_EVEN
            sign_base = sign_idx * 30 + self.rotation_offset

            for start_deg, end_deg, planet_lord, being_type_key, element in boundaries:
                span = end_deg - start_deg
                start_angle = sign_base + start_deg

                being_name = sign_data[being_type_key]
                label = self._abbreviate_being(being_name, max_len=8)

                bg_color = ELEMENT_BG.get(element, "#333333")
                text_color = ELEMENT_TEXT.get(element, "#FFFFFF")
                font_size = 15 if span >= 7 else 13

                # Sector
                key = (aditya_name, "trimsamsa", being_type_key)
                hover_sig = getattr(self, '_retinue_hover_signal', None)
                sector = RetinueRingSector(
                    self.cx, self.cy, trim_inner, trim_outer,
                    start_angle, span, bg_color,
                    hover_signal=hover_sig, sector_key=key
                )
                being_label = _r.BEING_TYPE_LABELS.get(being_type_key, being_type_key)
                sector.setToolTip(f"{being_name} ({being_label}) — {element}")
                self.scene.addItem(sector)
                self._retinue_sectors[key] = sector

                # Label (radial text at sector center)
                mid_angle = start_angle + span / 2
                mid_r = (trim_inner + trim_outer) / 2
                lx, ly = polar_to_cartesian(self.cx, self.cy, mid_r, mid_angle)
                rotation = self._radial_rotation(mid_angle)
                lbl = RetinueRingLabel(
                    label, lx, ly, rotation, font_size=font_size, color=text_color
                )
                self.scene.addItem(lbl)

        # Divider lines at each trimsamsa boundary
        for sign_idx in range(12):
            aditya_name = self._get_aditya_for_sector(sign_idx)
            sign_data = _r.ADITYA_RETINUE.get(aditya_name)
            if not sign_data:
                continue
            boundaries = _r.TRIMSAMSA_ODD if sign_data["type"] == "odd" else _r.TRIMSAMSA_EVEN
            sign_base = sign_idx * 30 + self.rotation_offset

            for start_deg, end_deg, _lord, _type, _elem in boundaries:
                # Divider at start of each division
                angle = sign_base + start_deg
                divider = TropicalSectorDivider(
                    self.cx, self.cy, trim_inner, trim_outer, angle
                )
                divider.setZValue(3.8)
                self.scene.addItem(divider)

            # Final divider at end of last division (= sign boundary)
            angle = sign_base + 30
            divider = TropicalSectorDivider(
                self.cx, self.cy, trim_inner, trim_outer, angle
            )
            divider.setZValue(3.8)
            self.scene.addItem(divider)

    def _draw_trimsamsha_degree_ruler(self):
        """Draw degree tick marks at Trimsamsha sector boundaries (F6 toggle)."""
        if not self.show_trimsamsha_degrees:
            return

        trim_outer = self.r_outer + 300
        tick_inner = trim_outer
        tick_outer = trim_outer + 15
        label_r = trim_outer + 25

        _r = _get_retinue()
        for sign_idx in range(12):
            aditya_name = self._get_aditya_for_sector(sign_idx)
            sign_data = _r.ADITYA_RETINUE.get(aditya_name)
            if not sign_data:
                continue
            boundaries = _r.TRIMSAMSA_ODD if sign_data["type"] == "odd" else _r.TRIMSAMSA_EVEN
            sign_base = sign_idx * 30 + self.rotation_offset

            for start_deg, _end_deg, _lord, _being, _element in boundaries:
                if start_deg == 0:
                    continue
                visual_angle = (sign_base + start_deg) % 360
                x1, y1 = polar_to_cartesian(
                    self.cx, self.cy, tick_inner, visual_angle)
                x2, y2 = polar_to_cartesian(
                    self.cx, self.cy, tick_outer, visual_angle)
                lx, ly = polar_to_cartesian(
                    self.cx, self.cy, label_r, visual_angle)
                rotation = self._radial_rotation(visual_angle)
                tick = TrimsamshaDegreeTick(
                    x1, y1, x2, y2,
                    degree_text=str(start_deg),
                    label_x=lx, label_y=ly, rotation=rotation,
                )
                self.scene.addItem(tick)

    # ── Element Distribution Pie Charts ─────────────────────────

    # D1 / Hora pie colors (4 elements)
    _PIE_COLORS = {
        "Fire":  "#CC0000",   # Red
        "Earth": "#8B4513",   # Saddle brown
        "Air":   "#F0C75E",   # Golden yellow (same as wheel Air sectors)
        "Water": "#1E90FF",   # Dodger blue
    }

    # Trimsamsa pie colors (5 elements including Ether)
    _TRIMSAMSA_PIE_COLORS = {
        "Fire":  "#CC0000",   # Same red
        "Earth": "#8B4513",   # Same brown
        "Air":   "#F0C75E",   # Same golden yellow
        "Water": "#1E90FF",   # Same blue
        "Ether": "#7E57C2",   # Violet (matches trimsamsa ring)
    }

    def _pie_position_right(self, rings_active=False):
        """Bottom-right diagonal position for pie chart."""
        offset = (self.r_outer + 350) if rings_active else (self.r_outer + 80)
        pie_r = 140
        diag = offset + pie_r + 30
        diag_xy = diag * 0.707
        return self.cx + diag_xy, self.cy + diag_xy

    def _pie_position_top_right(self, rings_active=False):
        """Top-right diagonal position for pie chart."""
        offset = (self.r_outer + 350) if rings_active else (self.r_outer + 80)
        pie_r = 140
        diag = offset + pie_r + 30
        diag_xy = diag * 0.707
        return self.cx + diag_xy, self.cy - diag_xy  # Negative Y = top

    def _pie_position_left(self, rings_active=False):
        """Bottom-left diagonal position for pie chart (mirrored)."""
        offset = (self.r_outer + 350) if rings_active else (self.r_outer + 80)
        pie_r = 140
        diag = offset + pie_r + 30
        diag_xy = diag * 0.707
        return self.cx - diag_xy, self.cy + diag_xy

    def _draw_pie_chart(self, data, pie_cx, pie_cy, pie_r, title_text, colors,
                        legend_side="right"):
        """
        Generic pie chart renderer used by D1, Hora, and Trimsamsa pies.

        Args:
            data: dict from get_dominant_elements / get_hora_elements / get_trimsamsa_elements
            pie_cx, pie_cy: center position of the pie
            pie_r: radius (typically 140)
            title_text: legend title ("Elements", "Hora", "Trimsamsa")
            colors: dict mapping element name → hex color
            legend_side: "right" or "left" — always place away from wheel center
        """
        from PySide6.QtWidgets import QGraphicsRectItem

        total = data.get("total_weight", 0)
        if total == 0:
            return

        dominant = data.get("dominant_elements", [])
        current_angle = 90.0  # Start at 12 o'clock

        for element, raw_count, weighted, percent, planets_list in dominant:
            if percent == 0:
                continue

            span = (percent / 100.0) * 360.0

            path = QPainterPath()
            path.moveTo(pie_cx, pie_cy)
            path.arcTo(pie_cx - pie_r, pie_cy - pie_r,
                       pie_r * 2, pie_r * 2, current_angle, span)
            path.closeSubpath()

            slice_item = QGraphicsPathItem(path)
            slice_item.setBrush(QBrush(QColor(colors.get(element, "#555"))))
            slice_item.setPen(QPen(QColor("#1a1a1e"), 2))
            slice_item.setZValue(20)
            self.scene.addItem(slice_item)

            if percent >= 10:
                mid_angle = current_angle + span / 2
                label_r = pie_r * 0.6
                angle_rad = math.radians(mid_angle)
                lx = pie_cx + label_r * math.cos(angle_rad)
                ly = pie_cy - label_r * math.sin(angle_rad)

                label = QGraphicsTextItem(f"{percent:.0f}%")
                label.setFont(QFont("Inter", 16, QFont.Weight.Bold))
                label.setDefaultTextColor(QColor("#FFFFFF"))
                br = label.boundingRect()
                label.setPos(lx - br.width() / 2, ly - br.height() / 2)
                label.setZValue(21)
                self.scene.addItem(label)

            current_angle += span

        # Build legend items first to measure widths (needed for left alignment)
        legend_font_title = QFont("Inter", 14, QFont.Weight.Bold)
        legend_font = QFont("Inter", 13)
        line_h = 28
        gap = 20  # gap between pie edge and legend

        legend_entries = []
        for element, raw_count, weighted, percent, planets_list in dominant:
            if percent == 0:
                continue
            planet_abbrevs = [p[:2] if len(p) > 3 else p for p in planets_list]
            planets_str = ", ".join(planet_abbrevs)
            legend_entries.append((element, percent, planets_str))

        # For left-side legend, measure the widest text to right-align against the pie
        if legend_side == "left":
            from PySide6.QtGui import QFontMetricsF
            fm = QFontMetricsF(legend_font)
            max_text_w = max(
                (fm.horizontalAdvance(f"{el} {pct:.0f}%  {ps}") + 24
                 for el, pct, ps in legend_entries),
                default=200
            )
            fm_title = QFontMetricsF(legend_font_title)
            title_w = fm_title.horizontalAdvance(title_text)
            legend_width = max(max_text_w, title_w)
            legend_x = pie_cx - pie_r - gap - legend_width
        else:
            legend_x = pie_cx + pie_r + gap

        legend_y = pie_cy - pie_r

        from ui.qt_theme import is_light_theme
        light = is_light_theme()
        legend_text_color = QColor("#333333") if light else QColor("#DDDDDD")
        legend_title_color = QColor("#555555") if light else QColor("#AAAAAA")
        swatch_border_color = QColor("#AAAAAA") if light else QColor("#333333")

        title = QGraphicsTextItem(title_text)
        title.setFont(legend_font_title)
        title.setDefaultTextColor(legend_title_color)
        title.setPos(legend_x, legend_y)
        title.setZValue(20)
        self.scene.addItem(title)
        legend_y += line_h + 4

        for element, percent, planets_str in legend_entries:
            swatch = QGraphicsRectItem(legend_x, legend_y + 4, 18, 18)
            swatch.setBrush(QBrush(QColor(colors.get(element, "#555"))))
            swatch.setPen(QPen(swatch_border_color, 1))
            swatch.setZValue(20)
            self.scene.addItem(swatch)

            text = QGraphicsTextItem(f"{element} {percent:.0f}%  {planets_str}")
            text.setFont(legend_font)
            text.setDefaultTextColor(legend_text_color)
            text.setPos(legend_x + 24, legend_y)
            text.setZValue(20)
            self.scene.addItem(text)

            legend_y += line_h

    def _has_outer_ring(self):
        """Check if any outer ring is active (retinue, tropical, transit, custom)."""
        if self.show_retinue_rings:
            return True
        if self.show_tropical_rim:
            return True
        if self.show_transit_rim and self._transit_planets:
            return True
        if getattr(self, 'show_custom_outer_rim', False) and (getattr(self, '_outer_rim_planets', None) or getattr(self, 'custom_outer_rim_data', None)):
            return True
        return False

    def _get_pie_params(self):
        """Resolve mode params for pie chart functions, matching panel controllers."""
        mode = self._aditya_mode
        tropical_mode = (mode == "tropical_classic")
        aya = self.ayanamsa_offset
        if mode == "sidereal" and aya == 0.0 and hasattr(self, '_gui'):
            aya = getattr(self._gui, "chart_ayanamsa_offset", 0.0)
        return mode, tropical_mode, aya

    def _draw_element_pie(self):
        """Dispatch pie chart drawing based on F5 (retinue rings) state."""
        if not self._chart:
            return

        if self.show_retinue_rings:
            if not (self.show_transit_rim and self._transit_planets):
                self._draw_d1_element_pie(position="top_right", rings_active=True)
                self._draw_hora_pie()
                self._draw_trimsamsa_pie()
        else:
            has_ring = self._has_outer_ring()
            self._draw_d1_element_pie(rings_active=has_ring)

    def _draw_d1_element_pie(self, position="bottom_right", rings_active=False):
        """D1 sign element pie chart — position adapts based on F5 state."""
        from AI_tools.AI_main_function.dominant import get_dominant_elements
        mode, _, aya = self._get_pie_params()
        data = get_dominant_elements(
            self._chart, luminary_weight=1.5,
            mode=mode, ayanamsa_offset=aya)
        if position == "top_right":
            pie_cx, pie_cy = self._pie_position_top_right(rings_active=rings_active)
        else:
            pie_cx, pie_cy = self._pie_position_right(rings_active=rings_active)
        self._draw_pie_chart(data, pie_cx, pie_cy, 140, "D1 Elements", self._PIE_COLORS)

    def _draw_hora_pie(self):
        """Hora element pie chart — bottom-right (when F5 ON)."""
        from AI_tools.AI_main_function.dominant import get_hora_elements
        _, tropical_mode, aya = self._get_pie_params()
        data = get_hora_elements(
            self._chart, luminary_weight=1.5,
            tropical_mode=tropical_mode, ayanamsa_offset=aya)
        pie_cx, pie_cy = self._pie_position_right(rings_active=True)
        self._draw_pie_chart(data, pie_cx, pie_cy, 140, "Hora", self._PIE_COLORS)

    def _draw_trimsamsa_pie(self):
        """Trimsamsa element pie chart — bottom-LEFT (when F5 ON)."""
        from AI_tools.AI_main_function.dominant import get_trimsamsa_elements
        _, tropical_mode, aya = self._get_pie_params()
        data = get_trimsamsa_elements(
            self._chart, luminary_weight=1.5,
            tropical_mode=tropical_mode, ayanamsa_offset=aya)
        pie_cx, pie_cy = self._pie_position_left(rings_active=True)
        self._draw_pie_chart(
            data, pie_cx, pie_cy, 140, "Trimsamsa", self._TRIMSAMSA_PIE_COLORS,
            legend_side="left")

    def _on_house_hover_enter(self, house_num: int):
        self._clear_retinue_hover(clear_house_numbers=False)
        highlighted_keys = set()
        _r = _get_retinue()
        for sign_idx in range(12):
            sign_name = self._get_aditya_for_sector(sign_idx)
            beings = _r.get_beings_for_house(sign_name, house_num)
            for being in beings:
                key = (sign_name, being["ring"], being["being_key"])
                sector = self._retinue_sectors.get(key)
                if sector:
                    sector.set_highlighted(True)
                highlighted_keys.add(key)
        self._amplify_planet_shadows(highlighted_keys)
        self._highlighted_house = house_num

    def _on_house_hover_leave(self):
        self._clear_retinue_hover()
        self._highlighted_house = None

    def _on_sector_hover_enter(self, sector_key):
        self._clear_retinue_hover()
        sign_name, ring, being_key = sector_key
        sector = self._retinue_sectors.get(sector_key)
        if sector:
            sector.set_highlighted(True)
        _r = _get_retinue()
        connected_houses = []
        for h in range(1, 13):
            beings = _r.get_beings_for_house(sign_name, h)
            if beings and beings[0]["being_key"] == being_key and beings[0]["ring"] == ring:
                connected_houses.append(h)
        for h in connected_houses:
            item = self._house_number_items.get(h)
            if item:
                item.set_highlighted(True)
        sign_data = _r.ADITYA_RETINUE.get(sign_name)
        if sign_data and connected_houses:
            sign_number = sign_data["number"]
            for h in connected_houses:
                target_idx = (sign_number - 1 + h - 1) % 12
                zodiac_item = self._zodiac_sector_items.get(target_idx)
                if zodiac_item:
                    zodiac_item.set_highlighted(True)
        if ring == "trimsamsa" and sign_data:
            is_odd = sign_data["type"] == "odd"
            boundaries = _r.TRIMSAMSA_ODD if is_odd else _r.TRIMSAMSA_EVEN
            for start_deg, end_deg, _, bkey, _ in boundaries:
                if bkey == being_key:
                    if start_deg < 15:
                        side = "aditya" if is_odd else "naga"
                        h_sector = self._retinue_sectors.get((sign_name, "hora", side))
                        if h_sector:
                            h_sector.set_highlighted(True)
                    if end_deg > 15:
                        side = "naga" if is_odd else "aditya"
                        h_sector = self._retinue_sectors.get((sign_name, "hora", side))
                        if h_sector:
                            h_sector.set_highlighted(True)
                    break
        self._amplify_planet_shadows({sector_key})
        self._highlighted_sector = sector_key

    def _on_sector_hover_leave(self):
        self._clear_retinue_hover()
        self._highlighted_sector = None

    def _clear_retinue_hover(self, clear_house_numbers=True):
        for sector in self._retinue_sectors.values():
            sector.set_highlighted(False)
        if clear_house_numbers:
            for item in self._house_number_items.values():
                item.set_highlighted(False)
        for item in self._zodiac_sector_items.values():
            item.set_highlighted(False)
        self._restore_planet_shadows()

    def _retinue_keys_for_planet(self, planet_info: dict):
        sign_idx = planet_info.get("sign_index")
        if sign_idx is None:
            return None, None
        _r = _get_retinue()
        aditya_name = self._get_aditya_for_sector(sign_idx)
        sign_data = _r.ADITYA_RETINUE.get(aditya_name)
        if not sign_data:
            return None, None
        deg_in_sign = planet_info.get("deg_in_sign", 0)
        is_odd = sign_data["type"] == "odd"
        in_first_half = deg_in_sign < 15
        is_sun = in_first_half if is_odd else not in_first_half
        hora_key = (aditya_name, "hora", "aditya" if is_sun else "naga")
        boundaries = _r.TRIMSAMSA_ODD if is_odd else _r.TRIMSAMSA_EVEN
        trimsamsa_key = None
        for start_deg, end_deg, _, being_type_key, _ in boundaries:
            if start_deg <= deg_in_sign < end_deg:
                trimsamsa_key = (aditya_name, "trimsamsa", being_type_key)
                break
        return hora_key, trimsamsa_key

    def _amplify_planet_shadows(self, highlighted_keys: set):
        self._original_shadows = {}
        for item in self.scene.items():
            if not isinstance(item, PlanetItem):
                continue
            hora_key, trim_key = self._retinue_keys_for_planet(item.planet_info)
            if not ((hora_key and hora_key in highlighted_keys) or
                    (trim_key and trim_key in highlighted_keys)):
                continue
            effect = item.graphicsEffect()
            if effect:
                orig_blur = effect.blurRadius()
                orig_color = QColor(effect.color())
                orig_offset = (effect.xOffset(), effect.yOffset())
                self._original_shadows[item] = (orig_blur, orig_color, orig_offset, False)
                effect.setBlurRadius(orig_blur * 3)
                boosted = QColor(orig_color)
                boosted.setAlpha(255)
                effect.setColor(boosted)
                effect.setOffset(0, 0)
            else:
                from PySide6.QtWidgets import QGraphicsDropShadowEffect
                from apps.widgets.planet_shadow import create_planet_shadow
                ref = create_planet_shadow(planet_name=item.planet_name)
                if ref:
                    ref_color = QColor(ref.color())
                    del ref
                else:
                    ref_color = QColor(200, 200, 200)
                new_effect = QGraphicsDropShadowEffect()
                new_effect.setBlurRadius(36)
                new_effect.setOffset(0, 0)
                ref_color.setAlpha(255)
                new_effect.setColor(ref_color)
                item.setGraphicsEffect(new_effect)
                del new_effect
                self._original_shadows[item] = (0, None, None, True)

    def _restore_planet_shadows(self):
        for item, (blur, color, offset, was_created) in self._original_shadows.items():
            if was_created:
                item.setGraphicsEffect(None)
            else:
                effect = item.graphicsEffect()
                if effect:
                    effect.setBlurRadius(blur)
                    effect.setColor(color)
                    effect.setOffset(offset[0], offset[1])
        self._original_shadows = {}

    def _draw_tropical_outer_rim(self):
        """
        Draw the outer comparison rim on top of the main wheel.

        Behavior depends on current aditya_mode:
        - Aditya Circle mode: Shows Tropical signs on outer rim
        - Tropical Classic mode: Shows Aditya signs on outer rim

        This allows visual comparison of both zodiac systems simultaneously.

        The rim includes:
        - Dark background ring
        - 12 zodiac icons at their true ecliptic positions
        - Sector divider lines
        """
        # Outer rim dimensions
        # Start just outside current degree ruler and campanus cusps
        outer_inner_r = self.r_outer + 150  # Start past campanus markers
        outer_outer_r = self.r_outer + 300  # Thick enough for icons

        # Layer 12.1: Dark background ring
        bg_item = TropicalOuterRimBackground(
            self.cx, self.cy,
            outer_inner_r, outer_outer_r
        )
        self.scene.addItem(bg_item)

        if self._aditya_mode == "aditya":
            rim_rotation = self.rotation_offset + 30
            icon_offset = 0
        else:
            rim_rotation = self.rotation_offset
            icon_offset = 1

        # Layer 12.2: Sector divider lines
        for i in range(12):
            # Sign boundaries at 0°, 30°, 60°, etc.
            angle = (i * 30 + rim_rotation) % 360
            item = TropicalSectorDivider(
                self.cx, self.cy,
                outer_inner_r, outer_outer_r,
                angle
            )
            self.scene.addItem(item)

        # Layer 12.3: Zodiac icons
        # Position each icon at center of its sector
        icon_radius = (outer_inner_r + outer_outer_r) / 2
        icon_size = 140  # Slightly smaller than main zodiac icons

        for i in range(12):
            # Center of sector (15° into the 30° sector)
            center_angle = (i * 30 + 15 + rim_rotation) % 360

            # Convert to cartesian
            angle_rad = math.radians(center_angle)
            x = self.cx + icon_radius * math.cos(angle_rad)
            y = self.cy - icon_radius * math.sin(angle_rad)

            # Load zodiac icon with appropriate offset
            # In Aditya mode: icon_offset=0, show Tropical (i)
            # In Classic mode: icon_offset=1, show Aditya (i+1)%12
            icon_index = (i + icon_offset) % 12
            pixmap = self.load_zodiac_icon(icon_index, size=icon_size)
            if pixmap:
                item = TropicalZodiacSymbolItem(pixmap, x, y, icon_index)
                self.scene.addItem(item)

    def _draw_transit_outer_rim(self):
        """Draw the outer Transit rim showing current planetary positions."""
        if not self._transit_planets:
            return

        positions = {}
        for pn, p in self._transit_planets.items():
            if pn in self._TRANSIT_PLANET_NAMES:
                positions[pn] = {"decimal_degrees": float(self._planet_effective_degrees(p))}
        if self._transit_cusps:
            try:
                asc = self._transit_cusps[1]
                positions["Ascendant"] = {
                    "decimal_degrees": float((asc.sign() - 1) * 30 + asc.real_in_sign_longitude())
                }
            except (IndexError, AttributeError):
                pass

        self._draw_outer_rim_planets(
            planets_data=positions,
            base_z=15,
            line_color=None,
            label_color="#AAAAAA",
            tooltip_prefix="Transit"
        )

        self._draw_outer_rim_ascendant(
            planets_data=positions,
            color="#4A90D9"
        )

    def _draw_custom_outer_rim(self):
        """Draw custom outer rim (e.g., eclipse/transit chart overlay)."""
        if self._outer_rim_planets:
            positions = {}
            for pn, p in self._outer_rim_planets.items():
                if pn in self._OUTER_RIM_PLANET_NAMES:
                    positions[pn] = {"decimal_degrees": float(self._planet_effective_degrees(p))}
            if self._outer_rim_cusps:
                try:
                    asc = self._outer_rim_cusps[1]
                    positions["Ascendant"] = {
                        "decimal_degrees": float((asc.sign() - 1) * 30 + asc.real_in_sign_longitude())
                    }
                except (IndexError, AttributeError):
                    pass
        elif self.custom_outer_rim_data:
            positions = self.custom_outer_rim_data
        else:
            return

        self._draw_outer_rim_planets(
            planets_data=positions,
            base_z=17,
            line_color="#FF8C00",
            label_color="#FF8C00",
            tooltip_prefix="Overlay"
        )

        self._draw_outer_rim_ascendant(
            planets_data=positions,
            color="#FF8C00",
            cusp_source=self._outer_rim_cusps
        )

    def _draw_outer_rim_ascendant(self, planets_data: dict, color: str = "#FF8C00",
                                    cusp_source=None):
        """
        Draw Ascendant indicator for an outer rim chart.

        Draws three elements:
        1. Glow effect at Ascendant position (like main chart)
        2. Triangle marker pointing inward
        3. Text label showing "ASC X° SignName"

        Args:
            planets_data: Planet data dict containing Ascendant
            color: Color for all elements
        """
        cusps = cusp_source if cusp_source is not None else self._transit_cusps
        if cusps is not None:
            asc = cusps[1]
            asc_degrees = (asc.sign() - 1) * 30 + asc.real_in_sign_longitude()
        elif "Ascendant" in planets_data:
            asc_degrees = planets_data["Ascendant"].get("decimal_degrees", 0)
        elif self._cusps:
            asc = self._cusps[1]
            asc_degrees = (asc.sign() - 1) * 30 + asc.real_in_sign_longitude()
        else:
            return

        # Outer rim radii — shift when retinue rings are underneath
        if self.show_retinue_rings:
            outer_rim_middle = self.r_outer + 405
            outer_rim_edge = self.r_outer + 520
        else:
            outer_rim_middle = self.r_outer + 225
            outer_rim_edge = self.r_outer + 320

        # 1. Glow effect (behind everything)
        glow = OuterRimAscendantGlow(
            center_x=self.cx,
            center_y=self.cy,
            radius=outer_rim_middle,
            ascendant_degrees=asc_degrees,
            rotation_offset=self.rotation_offset,
            color=color,
            glow_radius=70
        )
        self.scene.addItem(glow)

        # 2. Triangle marker pointing inward
        marker = OuterRimAscendantMarker(
            center_x=self.cx,
            center_y=self.cy,
            radius=outer_rim_middle,
            ascendant_degrees=asc_degrees,
            rotation_offset=self.rotation_offset,
            color=color,
            size=28
        )
        self.scene.addItem(marker)

        # 3. Text label with sign name
        label = OuterRimAscendantLabel(
            center_x=self.cx,
            center_y=self.cy,
            radius=outer_rim_edge,
            ascendant_degrees=asc_degrees,
            rotation_offset=self.rotation_offset,
            color=color
        )
        self.scene.addItem(label)

    def _draw_outer_rim_planets(
        self,
        planets_data: dict,
        base_z: float,
        line_color: str = None,
        label_color: str = "#AAAAAA",
        tooltip_prefix: str = "Outer"
    ):
        """
        Draw planets on an outer rim with collision avoidance.

        This is the shared implementation for both Transit and Custom outer rims.
        Any improvements to planet ordering will automatically apply to both.

        Args:
            planets_data: Dictionary of planet positions (same format as main chart)
            base_z: Base Z-value for layering (background=base, dividers=base+0.5, etc.)
            line_color: Fixed color for indicator lines, or None to use element colors
            label_color: Color for degree labels
            tooltip_prefix: Prefix for tooltip text (e.g., "Transit", "Eclipse")
        """
        from PySide6.QtWidgets import QGraphicsPixmapItem

        # Outer rim dimensions — shift outward when retinue rings occupy the first band
        if self.show_retinue_rings:
            outer_inner_r = self.r_outer + 310
            outer_outer_r = self.r_outer + 500
        else:
            outer_inner_r = self.r_outer + 150
            outer_outer_r = self.r_outer + 300

        # Layer 1: Dark background ring
        bg_item = TropicalOuterRimBackground(
            self.cx, self.cy,
            outer_inner_r, outer_outer_r
        )
        bg_item.setZValue(base_z)
        self.scene.addItem(bg_item)

        # Layer 2: Sector divider lines (sign boundaries)
        for i in range(12):
            angle = (i * 30 + self.rotation_offset) % 360
            item = TropicalSectorDivider(
                self.cx, self.cy,
                outer_inner_r, outer_outer_r,
                angle
            )
            item.setZValue(base_z + 0.5)
            self.scene.addItem(item)

        # Layer 3: Draw planets with collision avoidance
        # Use ~40% of inner wheel planet size for outer ring readability
        planet_sizes = self.display_settings.get("planet_sizes", {})
        avg_inner_size = sum(planet_sizes.values()) / len(planet_sizes) if planet_sizes else 120
        planet_size = max(36, int(avg_inner_size * 0.4))

        # Get indicator line settings
        line_settings = self.display_settings.get("indicator_line", {})
        glow_radius = line_settings.get("glow_radius", 40)
        line_width = line_settings.get("line_width", 3)

        # Planets to show (exclude Ascendant - it's location-dependent)
        planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                        "Venus", "Saturn", "Rahu", "Ketu"]
        if self.show_outer_planets:
            planet_names.extend(["Uranus", "Neptune", "Pluto"])

        planets_list = []
        for planet_name in planet_names:
            if planet_name not in planets_data:
                continue

            planet_data = planets_data[planet_name]
            planet_deg = planet_data.get("decimal_degrees", 0)
            if self._transit_planets and planet_name in self._transit_planets:
                sign_idx = (self._transit_planets[planet_name].sign() - 1) % 12
            else:
                sign_idx = int(planet_deg / 30) % 12
            planets_list.append({
                "name": planet_name,
                "degrees": planet_deg,
                "sign_index": sign_idx,
                "data": planet_data
            })

        # Calculate positions with collision avoidance
        planet_positions = self._calculate_transit_positions_with_avoidance(
            planets_list, outer_inner_r, outer_outer_r
        )

        # Draw planets and indicator lines
        for planet, (planet_x, planet_y, radius) in planet_positions:
            # Calculate original angle for indicator line (points to true position)
            original_angle = (planet["degrees"] + self.rotation_offset) % 360
            original_angle_rad = math.radians(original_angle)

            # Indicator line end point - pointing INWARD past the outermost ring
            inner_target_r = (self.r_outer + 295) if self.show_retinue_rings else (self.r_outer + 20)
            inner_x = self.cx + inner_target_r * math.cos(original_angle_rad)
            inner_y = self.cy - inner_target_r * math.sin(original_angle_rad)

            # Draw glowing indicator line
            if line_color:
                # Use fixed color (e.g., eclipse orange)
                indicator = PlanetIndicatorLine(
                    planet_x, planet_y,
                    inner_x, inner_y,
                    color=line_color,
                    glow_intensity=glow_radius,
                    line_width=line_width
                )
            else:
                # Use element color based on sign
                indicator = PlanetIndicatorLine(
                    planet_x, planet_y,
                    inner_x, inner_y,
                    sign_index=planet["sign_index"],
                    glow_intensity=glow_radius,
                    line_width=line_width
                )
            indicator.setZValue(base_z + 0.3)
            self.scene.addItem(indicator)

            # Load planet icon (half size)
            pixmap = self.load_planet_image(planet["name"], size=planet_size)
            if pixmap:
                item = QGraphicsPixmapItem(pixmap)
                item.setPos(planet_x - planet_size / 2, planet_y - planet_size / 2)
                item.setZValue(base_z + 1)
                item.setToolTip(f"{tooltip_prefix} {planet['name']}: {planet['degrees']:.1f}°")
                self.scene.addItem(item)

            # Draw degree label on outer edge
            dx = planet_x - self.cx
            dy = planet_y - self.cy
            angle_to_planet = math.atan2(-dy, dx)

            label_radius = outer_outer_r - 25
            label_x = self.cx + label_radius * math.cos(angle_to_planet)
            label_y = self.cy - label_radius * math.sin(angle_to_planet)

            # Format degree label or planet name
            if self.show_planet_names:
                label_text = get_planet_display_name(
                    self.sign_language, planet["name"])
            else:
                deg_in_sign = planet["degrees"] % 30
                degrees = int(deg_in_sign)
                minutes = int((deg_in_sign - degrees) * 60)
                label_text = f"{degrees}°{minutes:02d}'"

            label = QGraphicsTextItem(label_text)
            label.setFont(QFont("Inter", 14))
            label.setDefaultTextColor(QColor(label_color))
            label.setPos(label_x - label.boundingRect().width() / 2,
                        label_y - label.boundingRect().height() / 2)
            label.setZValue(base_z + 1.5)
            self.scene.addItem(label)

    def _calculate_transit_positions_with_avoidance(
        self, planets: list, inner_r: float, outer_r: float
    ) -> list:
        """
        Calculate transit planet positions with collision avoidance.

        Similar to _calculate_planet_positions() but adapted for the narrower
        outer rim. Uses angular spreading and limited radius variation.

        Args:
            planets: List of planet dicts with 'name', 'degrees', 'sign_index'
            inner_r: Inner radius of the transit rim
            outer_r: Outer radius of the transit rim

        Returns:
            List of (planet_dict, (x, y, radius)) tuples
        """
        if not planets:
            return []

        # Sort by degree for clustering
        planets_sorted = sorted(planets, key=lambda p: p["degrees"])

        # Clustering parameters (tighter for smaller icons)
        CLUSTER_THRESHOLD = 8   # degrees - planets closer than this form a cluster
        MIN_VISUAL_SEP = 6      # minimum visual separation in degrees

        # Build clusters
        clusters = []
        current_cluster = [planets_sorted[0]]

        for i in range(1, len(planets_sorted)):
            prev_deg = planets_sorted[i - 1]["degrees"]
            curr_deg = planets_sorted[i]["degrees"]

            diff = curr_deg - prev_deg
            if diff < 0:
                diff += 360

            if diff <= CLUSTER_THRESHOLD:
                current_cluster.append(planets_sorted[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [planets_sorted[i]]

        clusters.append(current_cluster)

        # Check wrap-around between last and first cluster
        if len(clusters) > 1:
            first_deg = clusters[0][0]["degrees"]
            last_deg = clusters[-1][-1]["degrees"]
            wrap_diff = (360 - last_deg) + first_deg
            if wrap_diff <= CLUSTER_THRESHOLD:
                clusters[-1].extend(clusters[0])
                clusters = clusters[1:]

        # Available radii within the transit rim (limited range)
        base_radius = (inner_r + outer_r) / 2
        radius_step = 35  # Smaller step for narrow rim
        radii = [
            base_radius,
            base_radius - radius_step,
            base_radius + radius_step,
        ]
        # Clamp to rim boundaries with padding
        min_r = inner_r + 25
        max_r = outer_r - 25
        radii = [max(min_r, min(r, max_r)) for r in radii]

        # Calculate positions
        positions = []

        for cluster in clusters:
            if len(cluster) == 1:
                # Single planet - place at natural position
                planet = cluster[0]
                angle = (planet["degrees"] + self.rotation_offset) % 360
                angle_rad = math.radians(angle)
                x = self.cx + base_radius * math.cos(angle_rad)
                y = self.cy - base_radius * math.sin(angle_rad)
                positions.append((planet, (x, y, base_radius)))

            else:
                # Multiple planets - spread them angularly and by radius
                cluster_degs = [p["degrees"] for p in cluster]

                # Calculate cluster center using circular mean
                sin_sum = sum(math.sin(math.radians(d)) for d in cluster_degs)
                cos_sum = sum(math.cos(math.radians(d)) for d in cluster_degs)
                avg_deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

                # Calculate spread
                n = len(cluster)
                total_spread = (n - 1) * MIN_VISUAL_SEP
                start_offset = -total_spread / 2

                # Sort by degree for consistent ordering
                cluster_sorted = sorted(cluster, key=lambda p: p["degrees"])

                for i, planet in enumerate(cluster_sorted):
                    # Spread angle around cluster center
                    spread_angle = avg_deg + start_offset + (i * MIN_VISUAL_SEP)
                    visual_angle = (spread_angle + self.rotation_offset) % 360
                    angle_rad = math.radians(visual_angle)

                    # Alternate radii for additional separation
                    radius = radii[i % len(radii)]

                    x = self.cx + radius * math.cos(angle_rad)
                    y = self.cy - radius * math.sin(angle_rad)
                    positions.append((planet, (x, y, radius)))

        return positions

    def clear_chart(self):
        """Clear the wheel display."""
        self._has_chart = False
        self.planets_data = None
        self._chart = None
        self._planets = None
        self._cusps = None
        self._varga_code = None
        self._transit_planets = None
        self._transit_cusps = None
        self.show_transit_rim = False
        self._outer_rim_planets = None
        self._outer_rim_cusps = None
        self._outer_rim_chart = None
        self.custom_outer_rim_data = None
        self.show_custom_outer_rim = False
        self.rotation_offset = 0.0
        self._retinue_sectors = {}
        self._house_number_items = {}
        self._zodiac_sector_items = {}
        self._highlighted_house = None
        self._highlighted_sector = None
        self._original_shadows = {}
        self.scene.clear()
        # Draw empty wheel
        self._draw_background()
        self._draw_zodiac_sectors()
        self._draw_sector_lines()
        self._draw_zodiac_symbols()
        self._draw_sign_names()
        self._draw_center()
