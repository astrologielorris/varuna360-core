"""
Nakshatra Wheel View Widget
Circular 27-sector nakshatra wheel using PySide6 QGraphicsView.

Features:
- 27 alternating-shade nakshatra sectors
- 5 concentric rings: Planets, Names, Lords, Dasha Numbers, Pada
- Ascendant at LEFT (9 o'clock) using sidereal longitude
- Planet icons with collision avoidance
- House cusp dotted lines in planet ring
- Zoom and pan support

Scene: 2048x2048, center at (1024, 1024).
"""
import math
from pathlib import Path
from datetime import timedelta

from apps.widgets.additional_body_glyphs import make_planet_item
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsEllipseItem, QGraphicsLineItem, QToolTip
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QPainter, QFont, QImage, QPixmap

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Import graphics items
from apps.widgets.nakshatra_wheel_items import (
    NakshatraSectorItem, NakshatraClickSignal, RingBackground,
    NakshatraNameItem, LordIconItem, DashaNumberItem, PadaDividerLine,
    HouseCuspLine, HouseCuspLabel,
    CenterBlankCircle, NakSectorDividerLine, RingBoundaryCircle,
    NakBackgroundCircle, OppositeNakDiameterLine, NakEndpointLabel, canvas_color
)

# Import wheel items for planet rendering + glowing indicator lines (Core widget)
from apps.widgets.wheel_items import PlanetItem, WheelPlanetClickSignal, PlanetIndicatorLineGroup

# Import shared zodiac renderer for inner zodiac wheel (Core widget)
from apps.widgets.zodiac_renderer import (
    draw_ascendant_glow, draw_zodiac_sectors, draw_sector_dividers,
    draw_zodiac_icons, draw_sign_names, draw_house_numbers,
    draw_whole_sign_dividers, load_zodiac_icon
)

# Import geometry helpers
from visualizations.wheel_geometry import polar_to_cartesian

# Import constants
from visualizations.wheel_constants import (
    NAKSHATRA_ABBREV, NAKSHATRA_LORDS, DISPLAY_PLANETS
)

# Import theme
from ui.qt_theme import get_theme_colors, desat_image, sat_key

# Nakshatra angular size (360 / 27 = 13.3333...)
NAK_SIZE_DEG = 360.0 / 27.0


class NakshatraWheelScene(QGraphicsScene):
    """Graphics scene with NoIndex to prevent BSP tree issues."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)


class NakshatraWheelView(QGraphicsView):
    """
    Circular 27-sector nakshatra wheel.

    Ring layout (inside-out):
        Ring 0: Center blank   (r=0..300)     - reserved for future zodiac embed
        Ring 1: Planets/Houses (r=300..600)    - planet icons + house cusp lines
        Ring 2: Nakshatra Names(r=600..700)    - 3-letter abbreviations
        Ring 3: Lord Icons     (r=700..800)    - Vimshottari lord planet PNGs
        Ring 4: Dasha Numbers  (r=800..880)    - bold 1-9 cycling
        Ring 5: Pada           (r=880..940)    - 4 subdivisions per nakshatra
    """

    # Ring radii (planet ring reduced by ~1/3: 300→200 width)
    R_CENTER = 300
    # Inner zodiac wheel radii (fits inside R_CENTER=300)
    R_MINI_CENTER = 60       # Dark hub (house numbers go here)
    R_MINI_MIDDLE = 245      # Outer edge of colored sector area
    R_MINI_OUTER = 288       # Zodiac icons ring + divider line extent
    R_PLANET_INNER = 300
    R_PLANET_OUTER = 500
    R_NAME_INNER = 500
    R_NAME_OUTER = 600
    R_LORD_INNER = 600
    R_LORD_OUTER = 700
    R_DASHA_INNER = 700
    R_DASHA_OUTER = 780
    R_PADA_INNER = 780
    R_PADA_OUTER = 840
    TRANSIT_RING_WIDTH = 150  # Width of transit ring when active

    def __init__(self, gui=None, parent=None, ayanamsa_source=None, summary_provider=None):
        super().__init__(parent)

        self.gui = gui
        # Injected bindings (SPEC-NAK-LITE-001). Both editions supply these
        # explicitly so the two ayanamsa frames and the Pro-only teacher-content
        # outer ring are visible at the construction site, never a hidden flag:
        #   ayanamsa_source  – callable returning the sidereal ayanamsa id. Core
        #                      injects zodiac.ayanamsa_id; Pro injects dasha.left.
        #                      None → legacy default (dasha.left) for bare tests.
        #   summary_provider – Pro-only object exposing valid_modes + draw(...) for
        #                      the teacher-content property outer ring. None
        #                      (Core/Lite) → the ring is never drawn and no
        #                      teacher content is reachable; property_mode "none".
        self._ayanamsa_source = ayanamsa_source
        self._summary_provider = summary_provider
        self.scene = NakshatraWheelScene(self)
        self.setScene(self.scene)

        # Scene dimensions
        self.wheel_size = 2048
        self.cx = self.wheel_size / 2  # 1024
        self.cy = self.wheel_size / 2  # 1024

        # Zoom
        self.zoom_factor = 0.45
        self.min_zoom = 0.15
        self.max_zoom = 3.0
        self.zoom_step = 1.15

        # Chart-first data (Issue 20)
        # ``_chart`` holds the ORIGINAL frame chart (the frame the user selected
        # on the main tab) and is what the planet-click dialog reports; the
        # nakshatra engine + inner tropical ring read ``_engine_chart``, the
        # tropical rebuild. They are set and cleared together.
        self._chart = None
        self._engine_chart = None
        self._planets = None
        self._cusps = None

        self.rotation_offset = 0.0
        self.show_inner_zodiac = True
        self.show_nak_labels = True   # Endpoint labels on opposite-nak diameter lines
        self.planet_glow_mode = "normal"  # "normal" → "full" → "off" cycle
        from managers.settings_manager import get_settings
        # House-cusp lines, toggled by F9 like the main Wheel (td-bu8s BUG3):
        # 0 = OFF, 1 = Angles only (H1/4/7/10), 2 = All 12 cusps. Seeded from the
        # shared chart.cusp_glow_mode so the view opens in the current F9 state.
        self.cusp_glow_mode = get_settings().get("chart.cusp_glow_mode", 0)
        self._drawn_cusp_mode = None   # cusp mode the scene was last drawn with
        # The teacher-content outer ring exists only when a Pro summary provider
        # is injected. Core/Lite gets no provider, so property_mode stays "none"
        # and the paid-edition nakshatra properties module is never imported here.
        if self._summary_provider is not None:
            saved = get_settings().get("display.nakshatra.property_mode", "none")
            self.property_mode = saved if saved in self._summary_provider.valid_modes else "none"
        else:
            self.property_mode = "none"
        self.danishta_mode = False    # Danishta zodiac: tropical + 90° shift (F10)

        # Transit ring state
        self.show_transit_ring = False
        self._transit_chart = None
        self._transit_frame = None
        self.transit_planet_naks = None
        self.transit_time_offset = timedelta(0)  # Time offset for transit adjustment
        self.transit_display_time = None  # Stores the actual transit datetime for label display

        # Icon caches
        self.planet_icons = {}
        self.zodiac_icons = {}

        # Planet click signal
        self.planet_click_signal = WheelPlanetClickSignal()

        # Nakshatra sector click signal
        self.nakshatra_click_signal = NakshatraClickSignal()

        # Load planet variation settings
        self.planet_variation_settings = self._load_planet_variation_settings()

        # Track last tooltip item to avoid redundant updates
        self._last_tooltip_item = None

        # Setup view
        self._setup_view()
        self.refresh_theme()

        padding = 100
        self.setSceneRect(-padding, -padding,
                          self.wheel_size + padding * 2,
                          self.wheel_size + padding * 2)

    # ── Settings ─────────────────────────────────────────────────

    def _load_planet_variation_settings(self):
        from managers.settings_manager import get_settings
        try:
            return get_settings().get("display.planet_variations", {})
        except Exception:
            pass
        return {}

    def get_planet_variation(self, planet_name: str) -> int:
        return self.planet_variation_settings.get(planet_name, 1)

    # ── Image Loading (copied from wheel_view.py pattern) ────────

    def load_planet_image(self, planet_name: str, size: int = 48):
        """Load planet icon PNG with variation support and caching."""
        PLANET_ICON_NAMES = {
            "Sun": "sun", "Moon": "moon", "Mars": "Mars",
            "Mercury": "Mercury", "Jupiter": "Jupiter", "Venus": "Venus",
            "Saturn": "Saturn", "Rahu": "rahu", "Ketu": "ketu",
            "Uranus": "uranus", "Neptune": "neptune", "Pluto": "pluto",
        }

        variation = self.get_planet_variation(planet_name)
        cache_key = f"{planet_name}_v{variation}_{size}{sat_key()}"

        if cache_key in self.planet_icons:
            return self.planet_icons[cache_key]

        icon_filename = PLANET_ICON_NAMES.get(planet_name, planet_name.lower())

        if variation > 1:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}{variation}.webp"
        else:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            self.planet_icons[cache_key] = None
            return None

        try:
            qimage = QImage(str(icon_path))
            if qimage.isNull():
                self.planet_icons[cache_key] = None
                return None

            qimage = qimage.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            qimage = desat_image(qimage)
            pixmap = QPixmap.fromImage(qimage)
            self.planet_icons[cache_key] = pixmap
            return pixmap
        except Exception as e:
            print(f"[NAK_WHEEL] Error loading planet image {planet_name}: {e}")
            self.planet_icons[cache_key] = None
            return None

    # ── View Setup ───────────────────────────────────────────────

    def _setup_view(self):
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._is_dragging = False
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(QColor(get_theme_colors()["secondary_dark"])))

    def showEvent(self, event):
        """Apply zoom and center on wheel when view becomes visible.

        Also re-seed the F9 cusp mode from the shared setting so showing this
        view REFLECTS F9 presses made on other views. The seed lives on the
        SHARED view (not on one host), so both the Core F2 panel and the Pro
        Nakshatra tab pick up the current mode when shown (td-yi23 finding 2).
        (This is display-consistency only: F9 *input* while the Pro tab is
        current is a separate concern — that panel has no cusp forwarders and is
        not in the F9 propagation list.) ``set_cusp_glow_mode`` normalises the
        value and redraws if a chart is loaded."""
        super().showEvent(event)
        from managers.settings_manager import get_settings
        self.set_cusp_glow_mode(get_settings().get("chart.cusp_glow_mode", 0))
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.cx, self.cy)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            factor = self.zoom_step
        else:
            factor = 1.0 / self.zoom_step

        current = self.transform().m11()
        new_zoom = current * factor
        if self.min_zoom <= new_zoom <= self.max_zoom:
            self.scale(factor, factor)
            # Keep the LOGICAL zoom in sync with the transform. Without this the
            # next showEvent/ensure_visible resets to the stale zoom_factor and
            # snaps the manual wheel-zoom away (SPEC-FSV-001 WI-5).
            self.zoom_factor = new_zoom

    def mousePressEvent(self, event):
        """Handle mouse press - always start panning (single click never opens dialogs)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open planet/nakshatra info dialog."""
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and item.data(Qt.UserRole) == 'nak_summary':
                point = self.mapToScene(event.pos())
                angle = math.degrees(math.atan2(self.cy-point.y(),point.x()-self.cx))
                index = int(((angle-self.rotation_offset)%360)/NAK_SIZE_DEG)
                self._is_dragging = False
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                self.nakshatra_click_signal.clicked.emit(index)
                event.accept()
                return
            if isinstance(item, PlanetItem):
                self._is_dragging = False
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                item.signal_emitter.clicked.emit(item.planet_name, item.planet_info)
                event.accept()
                return
            elif isinstance(item, NakshatraNameItem) and item.signal_emitter is not None:
                self._is_dragging = False
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                item.signal_emitter.clicked.emit(item.nak_index)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release to restore cursor."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        """Show tooltips for items under cursor (bypasses ScrollHandDrag blocking)."""
        super().mouseMoveEvent(event)
        # Check scene items under cursor position
        vp_items = self.items(event.pos())
        for item in vp_items:
            tip = item.toolTip()
            if tip:
                if item is not self._last_tooltip_item:
                    self._last_tooltip_item = item
                    from PySide6.QtGui import QCursor
                    QToolTip.showText(QCursor.pos(), tip, self)
                return
        # No tooltip item under cursor — hide any existing tooltip
        if self._last_tooltip_item is not None:
            self._last_tooltip_item = None
            QToolTip.hideText()

    # ── Public API ───────────────────────────────────────────────

    @staticmethod
    def _as_tropical_chart(chart):
        """Return a chart whose longitudes are TROPICAL, rebuilding if needed.

        Thin delegate to the single engine frame guard
        ``AI_tools.AI_main_function.nakshatra.as_tropical_chart`` (td-lgiq): the
        rebuild logic lives in the engine module now, so the wheel, the engine
        batch calls and ``core/nakshatra_kuta`` all share one implementation and
        no caller can double-subtract the ayanamsa (td-bu8s BUG2). The wheel keeps
        this method because it also needs the tropical chart OBJECT for its
        ``_engine_chart`` (the outer nakshatra rings); the rebuild feeds the
        ENGINE ONLY — the inner zodiac ring, ascendant and cusps read the original
        frame chart."""
        from AI_tools.AI_main_function.nakshatra import as_tropical_chart
        return as_tropical_chart(chart)

    def update_from_chart(self, chart, **_kw):
        """Render the nakshatra wheel from a libaditya Chart (primary entry point)."""
        if chart is None:
            self.clear_chart()
            return
        # ``_chart`` is the ORIGINAL frame chart the user selected on the main tab
        # (Aditya Circle / Tropical Classic / Sidereal). It drives BOTH the
        # planet-click dialog payload AND the inner zodiac ring / ascendant /
        # house cusps, which must FOLLOW THAT FRAME exactly like the main Wheel
        # view (td-bu8s BUG2). Only the nakshatra ENGINE (the outer nakshatra /
        # name / lord / dasha / pada rings) needs tropical longitudes — the
        # engine applies the ayanamsa itself — so a Sidereal-frame chart is
        # rebuilt tropical for that feed alone (``_engine_chart``), and the
        # rebuild never leaks into the dialog OR the inner ring.
        # Build the tropical engine chart first, then assign both together, so a
        # rebuild failure cannot leave _chart and _engine_chart torn (out of sync).
        engine_chart = self._as_tropical_chart(chart)
        self._chart = chart
        self._engine_chart = engine_chart
        self.planet_variation_settings = self._load_planet_variation_settings()
        # BUG2 / td-yi23: the inner-ring ASCENDANT / cusps AND the planet radial
        # lines follow the selected frame, so both ``_cusps`` and ``_planets``
        # read the ORIGINAL frame chart. ``_planets`` feeds ONLY
        # ``_get_tropical_sign_index`` (the radial-line element colours), which
        # must match the frame inner zodiac wheel — its stated design intent —
        # so in Sidereal the line colour agrees with the sidereal sign shown
        # (DeepSeek finding 5). The Danishta exception (a fixed tropical+90 shift
        # regardless of frame) reads the tropical ENGINE chart directly inside
        # ``_get_tropical_sign_index``, so it is unaffected by this frame binding.
        self._cusps = chart.rashi().cusps()
        self._planets = chart.rashi().planets()
        if (self.show_transit_ring and self._transit_chart is not None
                and self._transit_frame != self._transit_frame_settings()):
            self._calculate_transit_positions()
        self._draw_wheel()

    def ensure_visible(self):
        """Force viewport refresh with proper zoom and centering."""
        self.scene.update()
        self.viewport().update()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(self.cx, self.cy)

    def reset_zoom(self):
        """Fit the wheel to the CURRENT viewport (SPEC-FSV-001 refit contract).

        Fits the WHEEL bounds, not the ±100-padded sceneRect: the scene is
        2048px square but the drawn wheel is only ~R_PADA_OUTER radius about the
        centre, so fitting the sceneRect would leave the wheel tiny. The transit
        ring pushes the outer pada ring out by TRANSIT_RING_WIDTH, so include it
        when that ring is shown or fullscreen would clip it. Sets self.zoom_factor
        so a subsequent showEvent/ensure_visible reproduces this fit rather than
        snapping back to the fixed 0.45."""
        vp = self.viewport().size()
        if vp.width() <= 0 or vp.height() <= 0:
            return
        r_outer = self.R_PADA_OUTER + (
            self.TRANSIT_RING_WIDTH if self.show_transit_ring else 0)
        margin = 40  # breathing room so the outer ring / labels are not clipped
        diameter = 2 * r_outer + 2 * margin
        scale = min(vp.width(), vp.height()) / diameter
        scale = max(self.min_zoom, min(self.max_zoom, scale))
        self.zoom_factor = scale
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(self.cx, self.cy)

    def refresh_theme(self):
        """Redraw canvas chrome and labels using the current light/dark palette."""
        theme = get_theme_colors()
        self.setBackgroundBrush(QBrush(QColor(theme["secondary_dark"])))
        self.setStyleSheet(f"QToolTip {{background-color:{theme['secondary']}; color:{theme['secondary_text']}; border:1px solid {theme['secondary_text']}; padding:6px;}}")
        if self._engine_chart is not None:
            self._draw_wheel()
        self.scene.update()
        self.viewport().update()

    def reload_display_settings(self):
        """Re-render from the stored frame chart so a live display.sign_display
        flip repaints the inner zodiac ring (td-iaqm.5 CP7d). update_from_chart
        reads display.sign_display at draw, so re-invoking it is the redraw; the
        chart-host registry (chart_host_registry.sync_all_chart_hosts) calls this
        on every Settings Apply so the Pro Nakshatra tab flips live like the
        other chart views (the Core F2 nakshatra already flips via
        _apply_current_varga)."""
        if self._chart is not None:
            self.update_from_chart(self._chart)

    def clear_chart(self):
        self.scene.clear()
        self._chart = None
        self._engine_chart = None
        self._planets = None
        self._cusps = None

    def clear_icon_cache(self):
        """Drop cached planet pixmaps so they re-desaturate on the next load
        after a global UI saturation change (SPEC-SAT-001 WI-4)."""
        if hasattr(self, "planet_icons"):
            self.planet_icons = {}
        self.zodiac_icons.clear()

    def set_cusp_glow_mode(self, mode):
        """Set the F9 house-cusp mode (0 OFF / 1 Angles / 2 All) and redraw.

        Mirrors the main Wheel's ``set_cusp_glow_mode`` so the shared F9 handler
        (``core_gui_qt._cycle_cusp_glow``) drives this view too (td-bu8s BUG3).
        The panel forwards to here."""
        if not isinstance(mode, bool) and isinstance(mode, int):
            mode %= 3
        else:
            mode = 0            # tolerate a None/str from a hand-edited settings file
        if mode == self.cusp_glow_mode and mode == self._drawn_cusp_mode:
            # No change AND the scene already reflects it -> no redraw. Comparing
            # against the DRAWN mode (not just the attribute) keeps the showEvent
            # re-seed from forcing a second rebuild on top of the host's
            # update_chart (GLM review) WHILE preserving the hidden-wheel F9
            # catch-up: a raw attribute write that happens to equal the seed
            # still redraws when the scene was drawn at a different mode (DeepSeek
            # review). A real F9 press always changes the mode and redraws.
            return
        self.cusp_glow_mode = mode
        if self._engine_chart is not None:
            self._draw_wheel()
            self.scene.update()
            self.viewport().update()

    def set_show_transit_ring(self, show):
        """Toggle transit planet ring visibility."""
        self.show_transit_ring = show
        if show:
            self._calculate_transit_positions()
        else:
            self._transit_chart = None
            self.transit_planet_naks = None

    def _calculate_transit_positions(self):
        """Calculate planetary positions for transit ring (sidereal), with time offset."""
        from datetime import datetime, timezone
        from libaditya import swe
        from core.chart_factory import build_chart_from_params
        from AI_tools.AI_main_function.nakshatra import get_all_nakshatras

        try:
            now = datetime.now(timezone.utc)
            target_time = now + self.transit_time_offset
            self.transit_display_time = target_time

            hour_dec = target_time.hour + target_time.minute / 60.0 + target_time.second / 3600.0
            jd = swe.julday(target_time.year, target_time.month, target_time.day, hour_dec)
            mode, ayanamsa_id = self._transit_frame_settings()
            from core.transit_utils import get_current_location
            t_lat, t_lon = get_current_location()
            _chart = build_chart_from_params(jd=jd, lat=t_lat, lon=t_lon, mode=mode, ayanamsa=ayanamsa_id)
            self._transit_chart = _chart
            self._transit_frame = (mode, ayanamsa_id)

            jd_ut = _chart.context.timeJD.jd if _chart else None
            if jd_ut:
                ayanamsa = self._get_ayanamsa_settings()
                # Sidereal transit frame carries FLG_SIDEREAL; feed tropical so
                # the engine does not double-subtract the ayanamsa (as natal does).
                self.transit_planet_naks = get_all_nakshatras(
                    self._as_tropical_chart(_chart), jd_ut,
                    ayanamsa=ayanamsa
                )
            print(f"[NAK_TRANSIT] Calculated transit for {target_time.strftime('%Y-%m-%d %H:%M UTC')}")
        except (ValueError, RuntimeError, OSError, swe.Error) as e:
            print(f"[NAK_TRANSIT] Error: {e}")
            import traceback
            traceback.print_exc()
            self._transit_chart = None
            self.transit_planet_naks = None
            self.transit_display_time = None

    def _transit_frame_settings(self):
        """Inputs used to build the transit chart, independent of natal settings."""
        mode = self.gui.state.aditya_mode if self.gui else 'aditya'
        ayanamsa = getattr(self.gui, 'chart_sidereal_ayanamsa_id', 100) if self.gui else 100
        return mode, ayanamsa

    # ── Ayanamsa Settings (from GUI) ─────────────────────────────

    def _get_ayanamsa_settings(self):
        """Sidereal ayanamsa id, from the injected source (SPEC-NAK-LITE-001).

        Core injects zodiac.ayanamsa_id; Pro injects dasha.left. With no source
        (bare construction in tests) the legacy dasha.left default applies."""
        if self._ayanamsa_source is not None:
            return self._ayanamsa_source()
        if self.gui:
            return self.gui.dasha_manager.ayanamsa("left") if getattr(self.gui, "dasha_manager", None) else 100
        return 100

    # ── Dynamic Radii ─────────────────────────────────────────────

    def _recalculate_radii(self):
        """Compute instance radii from class constants.

        When show_transit_ring is ON, outer rings (names, lords, dasha, pada)
        shift outward by TRANSIT_RING_WIDTH to make room for the transit ring
        between the planet ring and the names ring.
        """
        C = NakshatraWheelView  # Class ref for constants
        shift = C.TRANSIT_RING_WIDTH if self.show_transit_ring else 0

        # Center and mini radii (never shift)
        self.r_center = C.R_CENTER
        self.r_mini_center = C.R_MINI_CENTER
        self.r_mini_middle = C.R_MINI_MIDDLE
        self.r_mini_outer = C.R_MINI_OUTER

        # Planet ring (never shifts)
        self.r_planet_inner = C.R_PLANET_INNER
        self.r_planet_outer = C.R_PLANET_OUTER

        # Transit ring (only when ON)
        if self.show_transit_ring:
            self.r_transit_inner = C.R_PLANET_OUTER              # 500
            self.r_transit_outer = C.R_PLANET_OUTER + C.TRANSIT_RING_WIDTH  # 650
        else:
            self.r_transit_inner = None
            self.r_transit_outer = None

        # Outer rings (shift when transit is ON)
        self.r_name_inner = C.R_NAME_INNER + shift
        self.r_name_outer = C.R_NAME_OUTER + shift
        self.r_lord_inner = C.R_LORD_INNER + shift
        self.r_lord_outer = C.R_LORD_OUTER + shift
        self.r_dasha_inner = C.R_DASHA_INNER + shift
        self.r_dasha_outer = C.R_DASHA_OUTER + shift
        self.r_pada_inner = C.R_PADA_INNER + shift
        self.r_pada_outer = C.R_PADA_OUTER + shift

    # ── Main Drawing Pipeline ────────────────────────────────────

    def _draw_wheel(self):
        """Full redraw of the nakshatra wheel."""
        self._last_tooltip_item = None
        self.scene.clear()
        self._recalculate_radii()

        if self._engine_chart is None:
            return
        # Record the cusp mode the scene is actually drawn with, so
        # set_cusp_glow_mode's no-redraw fast path can tell a real no-op from a
        # stale scene whose attribute was written raw (td-yi23).
        self._drawn_cusp_mode = self.cusp_glow_mode

        # Get Julian Day (frame-independent; read from the engine chart)
        jd_ut = self._engine_chart.context.timeJD.jd
        if not jd_ut:
            print("[NAK_WHEEL] No julian day on chart")
            return

        ayanamsa = self._get_ayanamsa_settings()

        # Import nakshatra functions
        from AI_tools.AI_main_function.nakshatra import (
            get_all_nakshatras, get_house_cusp_nakshatras, compute_dasha_numbers
        )

        # Compute nakshatra data for all bodies from the TROPICAL engine chart
        # (the engine applies the ayanamsa itself; feeding a sidereal chart
        # would double-subtract).
        planet_naks = get_all_nakshatras(
            self._engine_chart, jd_ut, ayanamsa=ayanamsa
        )
        planet_naks = compute_dasha_numbers(planet_naks)

        house_naks = get_house_cusp_nakshatras(
            self._engine_chart, jd_ut, ayanamsa=ayanamsa
        )

        # Compute rotation: Ascendant sidereal at LEFT (180°)
        lagna_data = planet_naks.get("Lagna")
        if lagna_data:
            asc_sid = lagna_data["sidereal_long"]
            self.rotation_offset = 180.0 - asc_sid
        else:
            self.rotation_offset = 0.0

        cx, cy = self.cx, self.cy

        # ── Z-10: Background circle
        bg = NakBackgroundCircle(cx, cy, self.r_pada_outer + 20)
        self.scene.addItem(bg)

        # ── Z0: Nakshatra sectors (ring 1 area: planet ring)
        self._draw_sectors(cx, cy)

        # ── Z0.5: Ring backgrounds (rings 2-5)
        for inner, outer, color in [
            (self.r_name_inner, self.r_name_outer, canvas_color("#252529", "#fafafa")),
            (self.r_lord_inner, self.r_lord_outer, canvas_color("#202024", "#f0f1f3")),
            (self.r_dasha_inner, self.r_dasha_outer, canvas_color("#1C1C20", "#f7f7f8")),
            (self.r_pada_inner, self.r_pada_outer, canvas_color("#18181C", "#edeff1")),
        ]:
            ring_bg = RingBackground(cx, cy, inner, outer, color)
            self.scene.addItem(ring_bg)

        # ── Z0.6: Transit ring background (when ON)
        if self.show_transit_ring:
            transit_bg = RingBackground(cx, cy, self.r_transit_inner,
                                        self.r_transit_outer, canvas_color("#1E2028", "#edf2f8"))
            self.scene.addItem(transit_bg)

        # ── Z1: Sector divider lines (across all rings)
        self._draw_sector_dividers(cx, cy)

        # ── Z1.5: Pada subdivision lines (ring 5)
        self._draw_pada_lines(cx, cy)

        # ── Z2: Center blank circle
        center = CenterBlankCircle(cx, cy, self.r_center)
        self.scene.addItem(center)

        # ── Z2.x: Inner content (zodiac OR opposite-nak diameter lines)
        if self.show_inner_zodiac:
            self._draw_inner_zodiac(cx, cy)
        else:
            self._draw_opposite_nak_lines(cx, cy)

        # ── Z3: Ring boundary circles
        boundaries = [self.r_planet_outer, self.r_name_outer,
                      self.r_lord_outer, self.r_dasha_outer, self.r_pada_outer]
        if self.show_transit_ring:
            boundaries.append(self.r_transit_outer)
        for r in boundaries:
            boundary = RingBoundaryCircle(cx, cy, r)
            self.scene.addItem(boundary)
        # Also inner boundary of ring 1
        boundary_inner = RingBoundaryCircle(cx, cy, self.r_planet_inner)
        self.scene.addItem(boundary_inner)

        # ── Z4: Nakshatra name labels (ring 2)
        self._draw_nakshatra_names(cx, cy)

        # ── Z5: Lord icons (ring 3)
        self._draw_lord_icons(cx, cy)

        # ── Z6: Dasha numbers (ring 4), or the Pro teacher-content summary ring.
        # The summary ring is drawn ONLY through an injected Pro provider; with
        # no provider (Core/Lite) property_mode is pinned "none" and no Pro
        # module is imported here.
        moon_data = planet_naks.get("Moon")
        if self.property_mode == "none" or self._summary_provider is None:
            self._draw_dasha_numbers(cx, cy, moon_data)
        else:
            self._summary_provider.draw(self.scene, cx, self.r_dasha_inner,
                                        self.r_dasha_outer, self.rotation_offset,
                                        self.property_mode)

        # ── Z7: House cusp lines + labels (ring 1)
        self._draw_house_cusps(cx, cy, house_naks)

        # ── Z8: Transit planet ring (when ON)
        if self.show_transit_ring and self.transit_planet_naks:
            self._draw_transit_ring(cx, cy)

        # ── Z9: Planet icons (ring 1)
        self._draw_planets(cx, cy, planet_naks)

        # Force viewport refresh to ensure chart displays immediately
        self.scene.update()
        self.viewport().update()

    # ── Drawing Sub-Routines ─────────────────────────────────────

    def _draw_sectors(self, cx, cy):
        """Draw 27 alternating-shade sectors in the planet ring area."""
        for i in range(27):
            start_deg = (i * NAK_SIZE_DEG + self.rotation_offset) % 360
            sector = NakshatraSectorItem(
                cx, cy, self.r_planet_inner, self.r_planet_outer,
                start_deg, NAK_SIZE_DEG, i
            )
            self.scene.addItem(sector)

    def _draw_sector_dividers(self, cx, cy):
        """Draw 27 radial lines from center to outermost ring."""
        for i in range(27):
            angle = (i * NAK_SIZE_DEG + self.rotation_offset) % 360
            line = NakSectorDividerLine(
                cx, cy, self.r_planet_inner, self.r_pada_outer, angle
            )
            self.scene.addItem(line)

    def _draw_pada_lines(self, cx, cy):
        """Draw 3 inner pada division lines per nakshatra in ring 5 (81 total)."""
        pada_size = NAK_SIZE_DEG / 4.0
        for i in range(27):
            base_angle = i * NAK_SIZE_DEG + self.rotation_offset
            for p in range(1, 4):  # 3 inner dividers
                angle = (base_angle + p * pada_size) % 360
                angle_rad = math.radians(angle)
                x1 = cx + self.r_pada_inner * math.cos(angle_rad)
                y1 = cy - self.r_pada_inner * math.sin(angle_rad)
                x2 = cx + self.r_pada_outer * math.cos(angle_rad)
                y2 = cy - self.r_pada_outer * math.sin(angle_rad)
                line = PadaDividerLine(x1, y1, x2, y2)
                self.scene.addItem(line)

    def _draw_nakshatra_names(self, cx, cy):
        """Draw 27 three-letter abbreviations in ring 2.

        All names are horizontal (no rotation) — matching Kala's layout.
        This keeps every name readable regardless of wheel position.
        """
        from AI_tools.AI_main_function.dasha import NAKSHATRA_NAMES_27

        mid_r = (self.r_name_inner + self.r_name_outer) / 2
        for i in range(27):
            mid_angle = (i + 0.5) * NAK_SIZE_DEG + self.rotation_offset
            mid_angle_norm = mid_angle % 360

            x, y = polar_to_cartesian(cx, cy, mid_r, mid_angle_norm)

            abbrev = NAKSHATRA_ABBREV[i] if i < len(NAKSHATRA_ABBREV) else f"N{i}"
            full_name = NAKSHATRA_NAMES_27[i] if i < len(NAKSHATRA_NAMES_27) else ""
            label = NakshatraNameItem(
                abbrev, x, y, font_size=13, full_name=full_name,
                nak_index=i, signal_emitter=self.nakshatra_click_signal
            )
            self.scene.addItem(label)

    def _draw_lord_icons(self, cx, cy):
        """Draw 27 lord planet PNG icons in ring 3."""
        mid_r = (self.r_lord_inner + self.r_lord_outer) / 2
        for i in range(27):
            lord_name = NAKSHATRA_LORDS[i] if i < len(NAKSHATRA_LORDS) else "Ketu"
            pixmap = self.load_planet_image(lord_name, size=256)
            if not pixmap:
                continue

            mid_angle = (i + 0.5) * NAK_SIZE_DEG + self.rotation_offset
            mid_angle_norm = mid_angle % 360
            x, y = polar_to_cartesian(cx, cy, mid_r, mid_angle_norm)

            icon = make_planet_item(LordIconItem, lord_name, pixmap, x, y, i)
            icon.setScale(72 / 256)  # Display at 72 scene units, keep 256px detail for zoom
            self.scene.addItem(icon)

    def _draw_dasha_numbers(self, cx, cy, moon_data):
        """Draw 1-9 dasha cycle numbers in ring 4."""
        mid_r = (self.r_dasha_inner + self.r_dasha_outer) / 2

        if moon_data:
            moon_lord_idx = moon_data["lord_idx"]
        else:
            moon_lord_idx = 0  # Fallback

        for i in range(27):
            nak_lord_idx = i % 9
            dasha_num = ((nak_lord_idx - moon_lord_idx) % 9) + 1

            mid_angle = (i + 0.5) * NAK_SIZE_DEG + self.rotation_offset
            mid_angle_norm = mid_angle % 360
            x, y = polar_to_cartesian(cx, cy, mid_r, mid_angle_norm)

            item = DashaNumberItem(dasha_num, x, y, font_size=14)
            self.scene.addItem(item)

    def _draw_house_cusps(self, cx, cy, house_naks):
        """Draw the house-cusp LABELS (always) and the dotted cusp LINES (F9-gated).

        The Asc / H2..H12 labels are orientation aids shown on EVERY mode, like
        the main Wheel's house numbers — they are not part of the F9 toggle
        (td-yi23 finding 1). The F9 ``cusp_glow_mode`` governs only the dotted
        radial LINES: 0 = no lines, 1 = Angles only (H1/4/7/10), 2 = all 12
        (td-bu8s BUG3)."""
        for label, cusp_trop_deg, nak_info in house_naks:
            # Extract house number from label
            if label == "Lagna":
                h_num = 1
            else:
                try:
                    h_num = int(label.replace("H", ""))
                except ValueError:
                    h_num = 0

            sid_long = nak_info["sidereal_long"]
            visual_angle = (sid_long + self.rotation_offset) % 360

            # Label near inner edge of planet ring — ALWAYS drawn (all 12).
            label_r = self.r_planet_inner + 20
            lx, ly = polar_to_cartesian(cx, cy, label_r, visual_angle)
            display_label = "Asc" if h_num == 1 else label
            cusp_label = HouseCuspLabel(display_label, lx, ly, h_num, font_size=10)
            self.scene.addItem(cusp_label)

            # Dotted radial LINE — gated by the F9 cusp mode.
            if self.cusp_glow_mode == 0:
                continue
            # Angles-only mode draws the four cardinal cusps (ASC/IC/DESC/MC).
            if self.cusp_glow_mode == 1 and h_num not in (1, 4, 7, 10):
                continue

            angle_rad = math.radians(visual_angle)
            # Dotted line from planet inner to outermost pada ring
            x1 = cx + self.r_planet_inner * math.cos(angle_rad)
            y1 = cy - self.r_planet_inner * math.sin(angle_rad)
            x2 = cx + self.r_pada_outer * math.cos(angle_rad)
            y2 = cy - self.r_pada_outer * math.sin(angle_rad)

            line = HouseCuspLine(x1, y1, x2, y2, h_num)
            self.scene.addItem(line)

    def _draw_planets(self, cx, cy, planet_naks):
        """Draw planet icons in ring 1 with collision avoidance + radial lines."""
        # Build list of planets with their sidereal longitudes
        planet_list = []
        for planet_name in DISPLAY_PLANETS:
            if planet_name in planet_naks:
                nak_data = planet_naks[planet_name]
                planet_list.append({
                    "name": planet_name,
                    "sidereal_long": nak_data["sidereal_long"],
                    "nak_data": nak_data,
                })

        # Also include Lagna marker if present
        if "Lagna" in planet_naks:
            planet_list.append({
                "name": "Ascendant",
                "sidereal_long": planet_naks["Lagna"]["sidereal_long"],
                "nak_data": planet_naks["Lagna"],
            })

        if not planet_list:
            return

        # Draw radial position lines for each planet (exact pada position)
        if self.planet_glow_mode != "off":
            self._draw_planet_radial_lines(cx, cy, planet_list)

        # Calculate positions with collision avoidance
        positions = self._calculate_positions_with_avoidance([
            p for p in planet_list if self.load_planet_image(p['name'], size=256) is not None
        ])

        for planet_dict, (x, y, _radius) in positions:
            planet_name = planet_dict["name"]
            # Load at 256px for zoom quality, display at 48 scene units
            pixmap = self.load_planet_image(planet_name, size=256)
            if not pixmap:
                continue

            # Build planet_info dict for click signal
            nak_data = planet_dict["nak_data"]
            planet_info = {
                "name": planet_name,
                "nakshatra": nak_data.get("name", ""),
                "lord": nak_data.get("lord", ""),
                "pada": nak_data.get("pada", 0),
                "dasha_number": nak_data.get("dasha_number"),
                "sidereal_long": nak_data.get("sidereal_long", 0),
            }

            item = make_planet_item(PlanetItem, planet_name, pixmap, x, y, planet_name, planet_info,
                              self.planet_click_signal)
            # Scale down to 48 scene units but keep 256px detail for zoom
            item.setScale(48 / 256)
            self.scene.addItem(item)

    def _draw_inner_zodiac(self, cx, cy):
        """Draw the miniature zodiac wheel in the centre, in the CURRENT FRAME.

        The inner zodiac ring FOLLOWS the main-tab frame (Aditya Circle /
        Tropical Classic / Sidereal), exactly like the main Wheel view
        (td-bu8s BUG2): its sign sectors, ascendant and house numbers read the
        original frame chart (``self._cusps``), so ``asc.sign()`` and
        ``real_in_sign_longitude()`` are already frame-relative. The OUTER
        nakshatra rings stay on the sidereal engine rotation
        (``self.rotation_offset``); the two rings are independent.

        Danishta (Pro F10) is a deliberate exception: a fixed tropical + 90°
        shift regardless of frame, so it reads the tropical ENGINE cusp, not the
        frame cusp (which is sidereal in Sidereal mode).
        """
        if not self._cusps:
            return

        if self.danishta_mode:
            # Fixed tropical+90 regardless of frame -> tropical engine chart.
            eng_asc = self._engine_chart.rashi().cusps()[1]
            asc_frame = (eng_asc.ecliptic_longitude() + 90) % 360
        else:
            asc = self._cusps[1]
            asc_frame = (asc.sign() - 1) * 30 + asc.real_in_sign_longitude()

        # Rotate so the frame Ascendant sits at LEFT (180°).
        tropical_rotation = 180.0 - asc_frame

        # Icon loader using variation settings from gui's main wheel
        wheel_view = getattr(self.gui, 'wheel_view', None) if self.gui else None
        var_settings = wheel_view.variation_settings if wheel_view else {}
        icon_cache = self.zodiac_icons

        def mini_icon_loader(zodiac_index, size=48):
            return load_zodiac_icon(zodiac_index, size, var_settings, icon_cache)

        # Z-base 2.x: inside center blank circle layer (Z=2)
        draw_ascendant_glow(self.scene, cx, cy, self.r_mini_middle,
                            glow_radius=40, z_base=2.05)
        draw_zodiac_sectors(self.scene, cx, cy, self.r_mini_center,
                            self.r_mini_middle, tropical_rotation, z_base=2.1)
        draw_sector_dividers(self.scene, cx, cy, self.r_mini_center,
                             self.r_mini_outer, tropical_rotation, z_base=2.2)

        # Inner zodiac ring honours display.sign_display (td-iaqm.5): names ->
        # sign-name text, zodiac -> the symbol icons (default), josh -> the Aditya
        # glyphs. The frame-following name/glyph context is borrowed from the main
        # Wheel, exactly like the icon variation settings above.
        from managers.settings_manager import get_settings
        mode = get_settings().get('display.sign_display', 'zodiac')
        if mode == 'names':
            # The mini ring is ~1/4 the main Wheel's scale (icons 48 vs 192), so
            # the Wheel's sign-name font (26) and its offset_x/offset_y (both
            # Wheel-scaled) would overflow the 245..288 band: force font_size 11
            # and zero the offsets so a user's Wheel tweaks can't deform the ring.
            # font_color is primary_text — the theme's foreground, always the
            # polarity-opposite of the ring's themed canvas ground (canvas_color:
            # near-black on dark themes, near-white on light) — so the names read
            # on either polarity. The name/frame context (aditya_mode, western
            # names, language) is borrowed from the main Wheel, like the icon
            # variation settings above.
            ds = dict(wheel_view.display_settings) if wheel_view else {}
            ds['sign_name'] = dict(ds.get('sign_name', {}),
                                   font_size=11,
                                   font_color=get_theme_colors()['primary_text'],
                                   offset_x=0, offset_y=0)
            draw_sign_names(self.scene, cx, cy, 265, tropical_rotation,
                            wheel_view._aditya_mode if wheel_view else 'aditya',
                            wheel_view.use_western_names if wheel_view else False,
                            wheel_view.sign_language if wheel_view else 'en',
                            ds, z_base=2.5)
        elif mode in ('josh', 'josh_only'):
            # The glyph ring sits at r=265, outside the element sectors (r<=245),
            # on the wheel's themed canvas ground. Inked with primary_text (the
            # theme's polarity-opposite foreground, Rule 20) so the flat glyphs
            # read on either polarity, like the main Wheel's josh ring.
            from apps.widgets.aditya_glyph_render import draw_aditya_glyphs
            draw_aditya_glyphs(self.scene, cx, cy, 265, 48, tropical_rotation,
                               get_theme_colors()['primary_text'], z_base=2.5)
            if mode == 'josh':
                ds = dict(wheel_view.display_settings) if wheel_view else {}
                ds['sign_name'] = dict(ds.get('sign_name', {}), font_size=9,
                                       font_color=get_theme_colors()['primary_text'],
                                       offset_x=0, offset_y=0)
                draw_sign_names(self.scene, cx, cy, 218, tropical_rotation,
                                wheel_view._aditya_mode if wheel_view else 'aditya',
                                wheel_view.use_western_names if wheel_view else False,
                                wheel_view.sign_language if wheel_view else 'en', ds, z_base=2.5)
        else:
            # Zodiac sign icons: load at 128px for zoom quality, display at 48 scene units
            draw_zodiac_icons(self.scene, cx, cy, radius=265, icon_size=128,
                              rotation_offset=tropical_rotation,
                              icon_loader=mini_icon_loader, z_base=2.5,
                              display_size=48)

        hub = CenterBlankCircle(cx, cy, self.r_mini_center)
        hub.setZValue(2.6)
        self.scene.addItem(hub)

        # Whole sign dividers + house numbers inside tiny hub (R=60)
        draw_whole_sign_dividers(self.scene, cx, cy,
                                 self.r_mini_center * 0.3,
                                 self.r_mini_center * 0.95,
                                 tropical_rotation, asc_frame, z_base=2.7)
        numbers = draw_house_numbers(self.scene, cx, cy, self.r_mini_center * 0.65,
                           font_size=10, rotation_offset=tropical_rotation,
                           asc_degrees=asc_frame, z_base=2.8)
        for number in numbers.values():
            number.setDefaultTextColor(QColor(canvas_color("#FFFFFF", "#30343a")))

    def _draw_opposite_nak_lines(self, cx, cy):
        """Draw 27 diameter lines connecting opposite nak boundaries when zodiac is off.

        Each line connects: start of nak i ↔ 2nd pada of nak (i+13)%27.
        The 2nd pada boundary of nak (i+13) is at (i+13)*NAK_DEG + NAK_DEG/2,
        which is exactly 180° from nak i's start = i*NAK_DEG (since 13.5 * 13.333 = 180).

        Colors cycle with coprime stride=7 so adjacent lines are visually distinct.
        """
        def line_color(idx):
            """Generate a distinct hue for line idx, maximizing neighbor separation."""
            hue = (idx * 7 * (360.0 / 27)) % 360
            return QColor.fromHslF(hue / 360.0, 0.6, 0.55)

        for i in range(27):
            # Side A: start of nakshatra i
            angle_a_deg = (i * NAK_SIZE_DEG + self.rotation_offset) % 360
            angle_a_rad = math.radians(angle_a_deg)
            # Side B: exactly 180° opposite (= 2nd pada of nak (i+13)%27)
            angle_b_rad = angle_a_rad + math.pi

            x1 = cx + self.r_center * math.cos(angle_a_rad)
            y1 = cy - self.r_center * math.sin(angle_a_rad)
            x2 = cx + self.r_center * math.cos(angle_b_rad)
            y2 = cy - self.r_center * math.sin(angle_b_rad)

            color = line_color(i)
            line = OppositeNakDiameterLine(x1, y1, x2, y2, color)
            line.setZValue(2.1)
            self.scene.addItem(line)

            # Endpoint labels (3-letter nak abbreviations)
            if self.show_nak_labels:
                label_r = self.r_center - 15
                lx1 = cx + label_r * math.cos(angle_a_rad)
                ly1 = cy - label_r * math.sin(angle_a_rad)
                lx2 = cx + label_r * math.cos(angle_b_rad)
                ly2 = cy - label_r * math.sin(angle_b_rad)

                opp_idx = (i + 13) % 27  # Opposite nak whose 2nd pada aligns
                label_a = NakEndpointLabel(lx1, ly1, NAKSHATRA_ABBREV[i], color)
                label_a.setZValue(2.5)
                self.scene.addItem(label_a)
                label_b = NakEndpointLabel(lx2, ly2, NAKSHATRA_ABBREV[opp_idx], color)
                label_b.setZValue(2.5)
                self.scene.addItem(label_b)

    def _get_tropical_sign_index(self, planet_name):
        """Element-colour sign index (0-11) for a planet's radial line.

        Non-Danishta: the FRAME sign (``_planets`` is the frame chart), so the
        radial line's element colour matches the frame inner zodiac wheel — its
        stated design intent (td-yi23 finding 5). Danishta (Pro F10) reads the
        tropical ENGINE chart here so the NATAL lines are tropical + 90 in every
        frame. (The transit lines have their own path,
        ``_get_tropical_sign_index_from_transit``, which reads the transit chart
        in its own frame — a pre-existing behaviour left unchanged here.)"""
        if self.danishta_mode:
            planets = (self._engine_chart.rashi().planets()
                       if self._engine_chart is not None else None)
            if not planets:
                return None
            try:
                planet = planets[planet_name]
            except KeyError:
                return None
            return int(((planet.ecliptic_longitude() + 90) % 360) / 30)
        if self._planets:
            try:
                planet = self._planets[planet_name]
            except KeyError:
                return None
            return planet.sign() - 1
        return None

    def _draw_planet_radial_lines(self, cx, cy, planet_list):
        """Draw glowing indicator lines showing each planet's exact angular position.

        Uses the same PlanetIndicatorLineGroup as the main zodiac wheel
        for a consistent neon glow effect. Lines extend from planet ring
        through all outer rings (names, lords, dasha, pada).

        Glow settings are read from the user's wheel display settings
        so both wheels use the same visual intensity.
        """
        # Read user's glow settings (same as main wheel chart)
        from managers.settings_manager import get_settings
        settings = get_settings()
        wheel_display = settings.get_wheel_display()
        line_settings = wheel_display.get("indicator_line", {})
        glow_radius = line_settings.get("glow_radius", 40)
        line_width = line_settings.get("line_width", 3)

        for planet_dict in planet_list:
            # Ascendant is a cusp, not a planet — skip glow line
            if planet_dict["name"] == "Ascendant":
                continue
            sid_long = planet_dict["sidereal_long"]
            visual_angle = (sid_long + self.rotation_offset) % 360
            angle_rad = math.radians(visual_angle)

            # Line from inner planet ring to outermost pada ring
            x1 = cx + self.r_planet_inner * math.cos(angle_rad)
            y1 = cy - self.r_planet_inner * math.sin(angle_rad)
            x2 = cx + self.r_pada_outer * math.cos(angle_rad)
            y2 = cy - self.r_pada_outer * math.sin(angle_rad)

            # Colour by the FRAME sign so the line matches the frame inner zodiac
            # wheel (td-yi23 finding 5); Danishta stays tropical+90 internally.
            planet_name = planet_dict["name"]
            trop_sign_idx = self._get_tropical_sign_index(planet_name)
            sign_idx = trop_sign_idx if trop_sign_idx is not None else 0

            indicator = PlanetIndicatorLineGroup(
                x1, y1, x2, y2,
                sign_index=sign_idx,
                glow_intensity=glow_radius,
                line_width=line_width
            )
            # Z=3.5: above ring backgrounds (0.5) and boundaries (3),
            # but BEHIND names (4), lords (5), numbers (6), cusps (7), planets (9)
            indicator.setZValue(3.5)
            self.scene.addItem(indicator)

            # Inward glow line through center circle
            if self.planet_glow_mode == "full":
                # Full diameter: edge-to-edge through center (R_CENTER both sides)
                x3 = cx + self.r_center * math.cos(angle_rad)
                y3 = cy - self.r_center * math.sin(angle_rad)
                opp_rad = angle_rad + math.pi
                x4 = cx + self.r_center * math.cos(opp_rad)
                y4 = cy - self.r_center * math.sin(opp_rad)
            else:
                # Normal: from R_PLANET_INNER inward to R_MINI_CENTER (half-radius)
                x3 = cx + self.r_planet_inner * math.cos(angle_rad)
                y3 = cy - self.r_planet_inner * math.sin(angle_rad)
                x4 = cx + self.r_mini_center * math.cos(angle_rad)
                y4 = cy - self.r_mini_center * math.sin(angle_rad)

            inner_indicator = PlanetIndicatorLineGroup(
                x3, y3, x4, y4,
                sign_index=sign_idx,
                glow_intensity=glow_radius,
                line_width=line_width
            )
            inner_indicator.setZValue(2.3)  # Above sectors (2.1), below icons (2.5)
            self.scene.addItem(inner_indicator)

    # ── Collision Avoidance ──────────────────────────────────────

    def _calculate_positions_with_avoidance(self, planets):
        """
        Calculate planet positions with clustering and radial spread.
        Adapted from WheelView._calculate_transit_positions_with_avoidance().
        """
        if not planets:
            return []

        sorted_planets = sorted(planets, key=lambda p: p["sidereal_long"])

        CLUSTER_THRESHOLD = 8
        MIN_VISUAL_SEP = 6

        # Build clusters
        clusters = []
        current_cluster = [sorted_planets[0]]

        for i in range(1, len(sorted_planets)):
            prev_deg = sorted_planets[i - 1]["sidereal_long"]
            curr_deg = sorted_planets[i]["sidereal_long"]
            diff = curr_deg - prev_deg
            if diff < 0:
                diff += 360

            if diff <= CLUSTER_THRESHOLD:
                current_cluster.append(sorted_planets[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_planets[i]]

        clusters.append(current_cluster)

        # Wrap-around check
        if len(clusters) > 1:
            first_deg = clusters[0][0]["sidereal_long"]
            last_deg = clusters[-1][-1]["sidereal_long"]
            wrap_diff = (360 - last_deg) + first_deg
            if wrap_diff <= CLUSTER_THRESHOLD:
                clusters[-1].extend(clusters[0])
                clusters = clusters[1:]

        # Available radii (narrower ring: step reduced to fit)
        base_radius = (self.r_planet_inner + self.r_planet_outer) / 2  # 400
        radius_step = 40
        radii = [
            base_radius,
            base_radius - radius_step,
            base_radius + radius_step,
        ]
        min_r = self.r_planet_inner + 25
        max_r = self.r_planet_outer - 25
        radii = [max(min_r, min(r, max_r)) for r in radii]

        positions = []
        cx, cy = self.cx, self.cy

        for cluster in clusters:
            if len(cluster) == 1:
                p = cluster[0]
                angle = (p["sidereal_long"] + self.rotation_offset) % 360
                x, y = polar_to_cartesian(cx, cy, base_radius, angle)
                positions.append((p, (x, y, base_radius)))
            else:
                cluster_degs = [p["sidereal_long"] for p in cluster]
                sin_sum = sum(math.sin(math.radians(d)) for d in cluster_degs)
                cos_sum = sum(math.cos(math.radians(d)) for d in cluster_degs)
                avg_deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

                n = len(cluster)
                total_spread = (n - 1) * MIN_VISUAL_SEP
                start_offset = -total_spread / 2

                cluster_sorted = sorted(cluster, key=lambda p: p["sidereal_long"])

                for i, p in enumerate(cluster_sorted):
                    spread_angle = avg_deg + start_offset + (i * MIN_VISUAL_SEP)
                    visual_angle = (spread_angle + self.rotation_offset) % 360
                    radius = radii[i % len(radii)]
                    x, y = polar_to_cartesian(cx, cy, radius, visual_angle)
                    positions.append((p, (x, y, radius)))

        return positions

    # ── Transit Ring Drawing ─────────────────────────────────────

    def _get_tropical_sign_index_from_transit(self, planet_name):
        """Get tropical sign index (0-11) for a transit planet (element color helper).

        Same logic as _get_tropical_sign_index() but reads from the transit Chart.
        """
        from core.chart_helpers import (
            get_planet_aditya_degrees, get_planet_decimal_degrees, has_planet
        )
        chart = self._transit_chart
        if chart is None or not has_planet(chart, planet_name):
            return None
        if self.danishta_mode:
            deg = (get_planet_decimal_degrees(chart, planet_name) + 90) % 360
        else:
            deg = get_planet_aditya_degrees(chart, planet_name)
        return int(deg / 30) % 12

    def _draw_transit_ring(self, cx, cy):
        """Draw transit planet ring between birth planets and nakshatra names."""
        if not self.transit_planet_naks:
            return

        # Build planet list from transit nakshatras
        planet_list = []
        for planet_name in DISPLAY_PLANETS:
            if planet_name in self.transit_planet_naks:
                nak_data = self.transit_planet_naks[planet_name]
                planet_list.append({
                    "name": planet_name,
                    "sidereal_long": nak_data["sidereal_long"],
                    "nak_data": nak_data,
                })

        if not planet_list:
            return

        # Draw transit glow lines (within transit ring only, dimmer)
        if self.planet_glow_mode != "off":
            self._draw_transit_radial_lines(cx, cy, planet_list)

        # Calculate positions with collision avoidance
        positions = self._calculate_transit_ring_positions([
            p for p in planet_list if self.load_planet_image(p['name'], size=256) is not None
        ])

        # Draw planet icons (smaller, slightly transparent)
        for planet_dict, (x, y, _radius) in positions:
            planet_name = planet_dict["name"]
            pixmap = self.load_planet_image(planet_name, size=256)
            if not pixmap:
                continue

            nak_data = planet_dict["nak_data"]
            planet_info = {
                "name": f"T.{planet_name}",
                "nakshatra": nak_data.get("name", ""),
                "lord": nak_data.get("lord", ""),
                "pada": nak_data.get("pada", 0),
                "sidereal_long": nak_data.get("sidereal_long", 0),
            }

            item = make_planet_item(PlanetItem, planet_name, pixmap, x, y, planet_name, planet_info,
                              self.planet_click_signal)
            item.setScale(36 / 256)  # Display at 36 scene units, keep 256px detail
            item.setOpacity(0.85)
            item.setZValue(8.5)   # Below natal planets (Z9)
            self.scene.addItem(item)

    def _calculate_transit_ring_positions(self, planets):
        """Calculate transit planet positions with collision avoidance (narrower ring)."""
        if not planets:
            return []

        sorted_planets = sorted(planets, key=lambda p: p["sidereal_long"])

        CLUSTER_THRESHOLD = 8
        MIN_VISUAL_SEP = 6

        clusters = []
        current_cluster = [sorted_planets[0]]

        for i in range(1, len(sorted_planets)):
            prev_deg = sorted_planets[i - 1]["sidereal_long"]
            curr_deg = sorted_planets[i]["sidereal_long"]
            diff = curr_deg - prev_deg
            if diff < 0:
                diff += 360
            if diff <= CLUSTER_THRESHOLD:
                current_cluster.append(sorted_planets[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_planets[i]]

        clusters.append(current_cluster)

        # Wrap-around check
        if len(clusters) > 1:
            first_deg = clusters[0][0]["sidereal_long"]
            last_deg = clusters[-1][-1]["sidereal_long"]
            wrap_diff = (360 - last_deg) + first_deg
            if wrap_diff <= CLUSTER_THRESHOLD:
                clusters[-1].extend(clusters[0])
                clusters = clusters[1:]

        base_radius = (self.r_transit_inner + self.r_transit_outer) / 2
        radius_step = 30  # Narrower ring than birth planets
        radii = [base_radius, base_radius - radius_step, base_radius + radius_step]
        min_r = self.r_transit_inner + 20
        max_r = self.r_transit_outer - 20
        radii = [max(min_r, min(r, max_r)) for r in radii]

        positions = []
        cx, cy = self.cx, self.cy

        for cluster in clusters:
            if len(cluster) == 1:
                p = cluster[0]
                angle = (p["sidereal_long"] + self.rotation_offset) % 360
                x, y = polar_to_cartesian(cx, cy, base_radius, angle)
                positions.append((p, (x, y, base_radius)))
            else:
                cluster_degs = [p["sidereal_long"] for p in cluster]
                sin_sum = sum(math.sin(math.radians(d)) for d in cluster_degs)
                cos_sum = sum(math.cos(math.radians(d)) for d in cluster_degs)
                avg_deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

                n = len(cluster)
                total_spread = (n - 1) * MIN_VISUAL_SEP
                start_offset = -total_spread / 2

                cluster_sorted = sorted(cluster, key=lambda p: p["sidereal_long"])

                for i, p in enumerate(cluster_sorted):
                    spread_angle = avg_deg + start_offset + (i * MIN_VISUAL_SEP)
                    visual_angle = (spread_angle + self.rotation_offset) % 360
                    radius = radii[i % len(radii)]
                    x, y = polar_to_cartesian(cx, cy, radius, visual_angle)
                    positions.append((p, (x, y, radius)))

        return positions

    def _draw_transit_radial_lines(self, cx, cy, planet_list):
        """Draw glow lines for transit planets (within transit ring only, dimmer)."""
        from managers.settings_manager import get_settings
        settings = get_settings()
        wheel_display = settings.get_wheel_display()
        line_settings = wheel_display.get("indicator_line", {})
        glow_radius = int(line_settings.get("glow_radius", 40) * 0.7)
        line_width = max(1, line_settings.get("line_width", 3) - 1)

        for planet_dict in planet_list:
            sid_long = planet_dict["sidereal_long"]
            visual_angle = (sid_long + self.rotation_offset) % 360
            angle_rad = math.radians(visual_angle)

            x1 = cx + self.r_transit_inner * math.cos(angle_rad)
            y1 = cy - self.r_transit_inner * math.sin(angle_rad)
            x2 = cx + self.r_transit_outer * math.cos(angle_rad)
            y2 = cy - self.r_transit_outer * math.sin(angle_rad)

            planet_name = planet_dict["name"]
            trop_sign_idx = self._get_tropical_sign_index_from_transit(planet_name)
            sign_idx = trop_sign_idx if trop_sign_idx is not None else int(sid_long / 30) % 12

            indicator = PlanetIndicatorLineGroup(
                x1, y1, x2, y2,
                sign_index=sign_idx,
                glow_intensity=glow_radius,
                line_width=line_width
            )
            indicator.setZValue(3.3)  # Below natal glow (3.5)
            self.scene.addItem(indicator)
