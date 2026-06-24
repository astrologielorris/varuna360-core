#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
North Indian Diamond Chart View Widget
Diamond-style zodiac chart using PySide6 QGraphicsView.

Features:
- 12 diamond/triangular cells arranged in North Indian pattern
- House 1 (Ascendant) at TOP CENTER (defining feature)
- Fixed houses, movable signs (opposite of South Indian)
- Zodiac icons rotate based on Ascendant sign
- Planet icons with stacking for multiple planets in same house
- Zoom and pan support
- Click on planets for info dialog

Layout Pattern:
    ┌────────┬────────┬────────┬────────┐
    │   12   │    1   │    2   │    3   │
    │        │  (ASC) │        │        │
    ├────────┼────────┴────────┼────────┤
    │   11   │                 │    4   │
    │        │     CENTER      │        │
    ├────────┤     DIAMOND     ├────────┤
    │   10   │                 │    5   │
    │        │                 │        │
    ├────────┼────────┬────────┼────────┤
    │    9   │    8   │    7   │    6   │
    │        │        │        │        │
    └────────┴────────┴────────┴────────┘

North Indian: Houses are FIXED, Signs ROTATE with Ascendant.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QGraphicsLineItem, QGraphicsRectItem, QGraphicsPolygonItem,
    QGraphicsPixmapItem
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainter, QFont, QImage, QPixmap, QPolygonF
)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Import North Indian items
from .north_indian_items import (
    NorthIndianPlanetClickSignal, NorthIndianSignClickSignal,
    DiamondCellItem, NorthIndianZodiacItem,
    NorthIndianPlanetItem, PlanetDegreeLabel
)

# Import theme
from ui.qt_theme import BG, SURFACE, TEXT_PRIMARY, GOLD, get_theme_colors
from core.aditya_mode import displayed_sign_name, get_planet_display_name


class NorthIndianScene(QGraphicsScene):
    """
    Graphics scene for the North Indian chart.

    Uses NoIndex item indexing to prevent Qt BSP tree corruption.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Disable BSP tree indexing to prevent segfaults (Qt Forum #71316)
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)


class NorthIndianView(QGraphicsView):
    """
    North Indian diamond-style chart view.

    Main features:
    - Fixed house positions, rotating zodiac signs
    - House 1 (Ascendant) at TOP CENTER
    - Element-colored diamond cells
    - Planet icons with stacking
    - Zoom with mouse wheel, pan with drag
    - Click planets to show info dialog
    """

    # Aditya names (12 solar deities)
    ADITYA_NAMES = [
        "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
        "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
    ]

    # Western names for icon filenames
    WESTERN_NAMES = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    # Planets to display (main 9 + outer planets optional)
    DISPLAY_PLANETS = [
        "Sun", "Moon", "Mars", "Mercury", "Jupiter",
        "Venus", "Saturn", "Rahu", "Ketu"
    ]

    # Planet icon filename mapping
    PLANET_ICON_NAMES = {
        "Sun": "sun", "Moon": "moon", "Mars": "Mars",
        "Mercury": "Mercury", "Jupiter": "Jupiter", "Venus": "Venus",
        "Saturn": "Saturn", "Rahu": "rahu", "Ketu": "ketu",
        "Uranus": "uranus", "Neptune": "neptune", "Pluto": "pluto",
    }

    # Planet sizes for 2048px scene
    PLANET_SIZES = {
        "Sun": 100, "Moon": 120, "Mars": 100, "Mercury": 100,
        "Jupiter": 100, "Venus": 80, "Saturn": 100,
        "Rahu": 80, "Ketu": 80,
        "Uranus": 70, "Neptune": 70, "Pluto": 70,
    }

    _TRANSIT_PLANET_NAMES = frozenset({
        "Sun", "Moon", "Mars", "Mercury", "Jupiter",
        "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto",
    })

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create scene
        self.scene = NorthIndianScene(self)
        self.setScene(self.scene)

        # Chart dimensions (2048x2048 for high quality icons)
        self.chart_size = 2048
        self.cx = self.chart_size / 2  # 1024
        self.cy = self.chart_size / 2  # 1024

        # Zoom settings (same as other views)
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
        self._is_aditya = False

        self._has_chart = False
        # Deprecated — kept for set_planets_data() compat until Issue 11
        self.planets_data = None
        self.aditya_mode = "aditya"
        self.ayanamsa_offset = 0.0
        self.use_western_names = False
        self.sign_language = "en"
        self.show_planet_names = False

        # Show outer planets toggle
        self.show_outer_planets = True  # Default ON

        # Transit overlay state (SPEC-TRN-003)
        self._transit_overlay_active = False
        self._transit_manager = None
        self._transit_geometry = None
        self._original_scene_rect = None

        # Ascendant override for "Sign as Ascendant" feature (F4)
        # None = use actual birth Ascendant, 0-11 = use that sign index as Ascendant
        self.ascendant_override = None

        # Planet click signal
        self.planet_click_signal = NorthIndianPlanetClickSignal()
        self.sign_click_signal = NorthIndianSignClickSignal()

        # Icon caches
        self.zodiac_icons = {}
        self.planet_icons = {}

        # Load variation settings
        self.variation_settings = self._load_variation_settings()
        self.planet_variation_settings = self._load_planet_variation_settings()

        # Load display settings (font sizes, colors, offsets)
        self.display_settings = self._load_display_settings()

        # House cell references (for updating)
        self.house_cells = {}

        # Setup view
        self._setup_view()

        # Set scene rect
        padding = 50
        self.setSceneRect(-padding, -padding,
                         self.chart_size + padding * 2,
                         self.chart_size + padding * 2)

        # Define house geometry (calculated once)
        self._calculate_house_geometry()

    def _load_variation_settings(self):
        """Load zodiac icon variation settings from SettingsManager."""
        from managers.settings_manager import get_settings
        try:
            return get_settings().get("display.zodiac_variations", {})
        except Exception as e:
            print(f"[NORTH INDIAN] Warning: Could not load zodiac variation settings: {e}")
        return {}

    def _load_planet_variation_settings(self):
        """Load planet icon variation settings from SettingsManager."""
        from managers.settings_manager import get_settings
        try:
            return get_settings().get("display.planet_variations", {})
        except Exception as e:
            print(f"[NORTH INDIAN] Warning: Could not load planet variation settings: {e}")
        return {}

    def _load_display_settings(self) -> dict:
        """Load North Indian display settings (fonts, colors, sizes)."""
        from managers.settings_manager import get_settings
        settings = get_settings()
        return settings.get_north_indian_display()

    def reload_display_settings(self):
        """Reload display settings and redraw chart."""
        self.display_settings = self._load_display_settings()
        if self._chart:
            self.draw_chart()

    def get_zodiac_variation(self, zodiac_index: int) -> int:
        """Get the selected variation number for a zodiac sign."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        return self.variation_settings.get(western_name, 1)

    def get_planet_variation(self, planet_name: str) -> int:
        """Get the selected variation number for a planet."""
        return self.planet_variation_settings.get(planet_name, 1)

    def reload_settings(self):
        """Reload variation settings and redraw."""
        self.variation_settings = self._load_variation_settings()
        self.planet_variation_settings = self._load_planet_variation_settings()
        self.zodiac_icons = {}
        self.planet_icons = {}
        if self._chart:
            self.draw_chart()

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

        # Arrow cursor by default
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        # Enable mouse tracking for hover
        self.setMouseTracking(True)
        # StrongFocus required so keyPressEvent receives +/- zoom shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Background color — live theme (SPEC-THM-001 G04)
        self.setBackgroundBrush(QBrush(QColor(get_theme_colors()["secondary_dark"])))

    # ===================================================================
    # POLYGON GEOMETRY HELPERS
    # Used by label and planet placement to keep content inside cells.
    # ===================================================================

    @staticmethod
    def _point_in_polygon_with_margin(point: QPointF, polygon: QPolygonF,
                                       margin: float = 0.0) -> bool:
        """
        True if ``point`` is strictly inside ``polygon`` with at least
        ``margin`` scene-units of clearance from every edge.

        Uses Qt's OddEvenFill containment (valid for simple convex polygons
        — all North Indian cells are diamonds or triangles, both convex).
        """
        if not polygon.containsPoint(point, Qt.FillRule.OddEvenFill):
            return False
        if margin <= 0:
            return True
        # Perpendicular distance from point to each polygon edge.
        n = polygon.size()
        px, py = point.x(), point.y()
        for i in range(n):
            a = polygon.at(i)
            b = polygon.at((i + 1) % n)
            ax, ay = a.x(), a.y()
            bx, by = b.x(), b.y()
            dx, dy = bx - ax, by - ay
            edge_len_sq = dx * dx + dy * dy
            if edge_len_sq < 1e-6:
                continue
            # Distance from point to infinite line through (a, b)
            # |cross| / |edge|
            cross = abs((px - ax) * dy - (py - ay) * dx)
            dist = cross / (edge_len_sq ** 0.5)
            if dist < margin:
                return False
        return True

    @staticmethod
    def _rect_inside_polygon(cx: float, cy: float, half_w: float,
                              half_h: float, polygon: QPolygonF,
                              margin: float = 0.0) -> bool:
        """
        True if the axis-aligned rectangle centered at (cx, cy) with the
        given half-extents fits inside ``polygon`` with ``margin`` clearance
        on every side (checked at corners).
        """
        corners = [
            QPointF(cx - half_w, cy - half_h),
            QPointF(cx + half_w, cy - half_h),
            QPointF(cx - half_w, cy + half_h),
            QPointF(cx + half_w, cy + half_h),
        ]
        return all(
            NorthIndianView._point_in_polygon_with_margin(c, polygon, margin)
            for c in corners
        )

    @staticmethod
    def _inscribed_rect(polygon: QPolygonF, centroid: tuple,
                         aspect: float = 1.0, margin: float = 6.0) -> tuple:
        """
        Find the largest axis-aligned rectangle centered at ``centroid``
        that fits inside ``polygon`` with ``margin`` clearance.

        ``aspect`` = width / height for the inscribed rectangle. 1.0 = square.

        Returns (left, top, width, height) in scene units. Falls back to a
        minimal rectangle centered on centroid if polygon is degenerate.
        """
        cx, cy = centroid

        # Binary search on the half-diagonal scale
        # max scale based on polygon bounding rect
        bbox = polygon.boundingRect()
        max_half_h = min(bbox.height() / 2, bbox.width() / (2 * aspect))
        if max_half_h <= margin:
            # Degenerate — return a tiny centered rect as safe fallback
            fallback = max(4.0, bbox.width() * 0.1)
            return (cx - fallback, cy - fallback, 2 * fallback, 2 * fallback)

        lo, hi = 0.0, max_half_h
        best_half_h = 0.0
        # 20 iterations → sub-pixel precision
        for _ in range(20):
            mid = (lo + hi) / 2
            half_w = mid * aspect
            if NorthIndianView._rect_inside_polygon(cx, cy, half_w, mid, polygon, margin):
                best_half_h = mid
                lo = mid
            else:
                hi = mid

        if best_half_h <= 0:
            # Nothing fits — degenerate fallback
            fallback = max(4.0, bbox.width() * 0.1)
            return (cx - fallback, cy - fallback, 2 * fallback, 2 * fallback)

        half_w = best_half_h * aspect
        return (cx - half_w, cy - best_half_h, 2 * half_w, 2 * best_half_h)

    @staticmethod
    def _inscribed_rect_avoiding(polygon: QPolygonF, center: tuple,
                                  avoid_rect: tuple,
                                  aspect: float = 1.0,
                                  margin: float = 6.0) -> tuple:
        """
        Variant of ``_inscribed_rect`` that also rejects rectangles which
        intersect ``avoid_rect`` (typically the sign badge bbox).

        This implements Codex's recommended fix for the "rect minus rect
        is not a rect" problem: instead of trying to subtract the badge
        from the inscribed rectangle (which produces an L-shape), we
        binary-search for the largest inscribed rect at ``center`` whose
        4 corners both (a) stay inside the polygon with margin AND (b)
        do not intersect the badge rectangle.

        ``avoid_rect`` = (left, top, width, height). Pass ``None`` to
        behave like plain ``_inscribed_rect``.

        Returns (left, top, width, height). Returns a tiny fallback rect
        when nothing fits.
        """
        cx, cy = center
        bbox = polygon.boundingRect()
        max_half_h = min(bbox.height() / 2, bbox.width() / (2 * aspect))
        if max_half_h <= margin:
            fallback = max(4.0, bbox.width() * 0.1)
            return (cx - fallback, cy - fallback, 2 * fallback, 2 * fallback)

        # AABB intersection test against the avoid rectangle.
        def intersects_avoid(half_w, half_h):
            if avoid_rect is None:
                return False
            ar_l, ar_t, ar_w, ar_h = avoid_rect
            ar_r = ar_l + ar_w
            ar_b = ar_t + ar_h
            rl = cx - half_w
            rr = cx + half_w
            rt = cy - half_h
            rb = cy + half_h
            # Not-intersect condition: one rect is fully on one side.
            return not (rr < ar_l or rl > ar_r or rb < ar_t or rt > ar_b)

        lo, hi = 0.0, max_half_h
        best_half_h = 0.0
        for _ in range(20):
            mid = (lo + hi) / 2
            half_w = mid * aspect
            inside = NorthIndianView._rect_inside_polygon(
                cx, cy, half_w, mid, polygon, margin
            )
            if inside and not intersects_avoid(half_w, mid):
                best_half_h = mid
                lo = mid
            else:
                hi = mid

        if best_half_h <= 0:
            fallback = max(4.0, bbox.width() * 0.05)
            return (cx - fallback, cy - fallback, 2 * fallback, 2 * fallback)

        half_w = best_half_h * aspect
        return (cx - half_w, cy - best_half_h,
                2 * half_w, 2 * best_half_h)

    @staticmethod
    def _clamp_text_inside(text_width: float, text_height: float,
                            naive_x: float, naive_y: float,
                            polygon: QPolygonF, centroid: tuple,
                            margin: float = 8.0, max_steps: int = 20) -> tuple:
        """
        Nudge a text bounding box so it fits inside ``polygon`` with
        ``margin`` clearance.

        Input (naive_x, naive_y) is the text's top-left position. Moves the
        rectangle along the vector from its center toward ``centroid`` in
        discrete steps until all 4 corners clear the polygon edges.

        Returns (clamped_x, clamped_y) — the new top-left.
        If no valid position found, returns the closest attempted position.
        """
        cx, cy = centroid
        x, y = naive_x, naive_y
        hw, hh = text_width / 2, text_height / 2

        def corners(tl_x, tl_y):
            return [
                QPointF(tl_x, tl_y),
                QPointF(tl_x + text_width, tl_y),
                QPointF(tl_x, tl_y + text_height),
                QPointF(tl_x + text_width, tl_y + text_height),
            ]

        def all_inside(tl_x, tl_y):
            return all(
                NorthIndianView._point_in_polygon_with_margin(c, polygon, margin)
                for c in corners(tl_x, tl_y)
            )

        if all_inside(x, y):
            return (x, y)

        # Direction from text center to polygon centroid
        center_x = x + hw
        center_y = y + hh
        dx = cx - center_x
        dy = cy - center_y
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return (x, y)
        ux, uy = dx / length, dy / length

        step_size = max(2.0, length / max_steps)
        for i in range(1, max_steps + 1):
            new_x = x + ux * step_size * i
            new_y = y + uy * step_size * i
            if all_inside(new_x, new_y):
                return (new_x, new_y)

        # Last resort: center text on the polygon centroid
        return (cx - hw, cy - hh)

    def _calculate_house_geometry(self):
        """
        Calculate the geometry for all 12 house cells.

        North Indian layout (from Gemini's specification):
        - Outer square with LARGE inner diamond at S/4 positions
        - Angular houses (1, 4, 7, 10) are DIAMOND shapes touching center
        - Triangular houses (2, 3, 5, 6, 8, 9, 11, 12) are in corners

        14 Key Points:
        - 4 outer corners: TL, TR, BR, BL
        - 4 midpoints: T, R, B, L
        - 1 center: C
        - 4 inner intersections at S/4: I1, I2, I3, I4

        Layout:
                TL────────T────────TR
                │ \\  12 / \\  2  // │
                │   \\  /   \\  //   │
                │ 11 I1──────I2  3   │
                │    │\\  1  //│     │
                L────│  \\  //  │────R
                │    │  //  \\  │     │
                │ 10 │//  7  \\│  4   │
                │   I4──────I3       │
                │ 9  /\\      //\\  5 │
                │  //  \\  //    \\  │
                BL────────B────────BR
                       8       6
        """
        # Chart dimensions
        margin = 100
        S = self.chart_size - 2 * margin  # Size of square

        # ===== A. OUTER BOX (4 corners) =====
        TL = (margin, margin)                      # Top-left
        TR = (margin + S, margin)                  # Top-right
        BR = (margin + S, margin + S)              # Bottom-right
        BL = (margin, margin + S)                  # Bottom-left

        # ===== B. MIDPOINTS (4 points) =====
        T = (margin + S / 2, margin)               # Top midpoint
        R = (margin + S, margin + S / 2)           # Right midpoint
        B = (margin + S / 2, margin + S)           # Bottom midpoint
        L = (margin, margin + S / 2)               # Left midpoint

        # ===== C. CENTER (1 point) =====
        C = (self.cx, self.cy)

        # ===== D. INNER INTERSECTIONS at S/4 marks (4 points) =====
        I1 = (margin + S / 4, margin + S / 4)         # Top-left inner
        I2 = (margin + 3 * S / 4, margin + S / 4)     # Top-right inner
        I3 = (margin + 3 * S / 4, margin + 3 * S / 4) # Bottom-right inner
        I4 = (margin + S / 4, margin + 3 * S / 4)     # Bottom-left inner

        # Helper to create polygon from points
        def make_poly(*points):
            return QPolygonF([QPointF(p[0], p[1]) for p in points])

        # Helper to calculate centroid
        def centroid(*points):
            x = sum(p[0] for p in points) / len(points)
            y = sum(p[1] for p in points) / len(points)
            return (x, y)

        # Helper to calculate a point biased toward the inner vertex
        # blend: 0.0 = at inner point, 1.0 = at centroid
        def inner_biased(inner_point, cent, blend=0.3):
            x = inner_point[0] + blend * (cent[0] - inner_point[0])
            y = inner_point[1] + blend * (cent[1] - inner_point[1])
            return (x, y)

        # Helper: midpoint of two points
        def midpoint(a, b):
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

        # Helper: point biased from an OUTER anchor toward the centroid.
        # Used for triangle sign-badge anchors where we want the badge near
        # the WIDE outer edge of the triangle, not the narrow inner tip.
        # blend=0.0 at outer anchor, 1.0 at centroid.
        def outer_biased(outer_point, cent, blend=0.25):
            x = outer_point[0] + blend * (cent[0] - outer_point[0])
            y = outer_point[1] + blend * (cent[1] - outer_point[1])
            return (x, y)

        # Store cell geometry
        self.house_geometry = {}

        # ===== ANGULAR HOUSES (DIAMONDS - 4 vertices) =====
        # These touch the center of the chart
        # Houses go COUNTER-CLOCKWISE from House 1 at top
        # Icon position: near center C, biased slightly outward

        # House 1 (Top Center): Diamond from T → I1 → C → I2
        # Icon at BOTTOM of diamond (near C)
        h1_cent = centroid(T, I1, C, I2)
        self.house_geometry[1] = {
            'polygon': make_poly(T, I1, C, I2),
            'center': h1_cent,
            'inner_vertex': C,
            'icon_position': inner_biased(C, h1_cent, 0.35),
            'planet_area': (h1_cent[0], h1_cent[1], S * 0.2),
            'shape': 'diamond',
            'badge_rect': None,
        }

        # House 4 (Left Center): Diamond from L → I4 → C → I1
        # Icon at RIGHT of diamond (near C)
        h4_cent = centroid(L, I4, C, I1)
        self.house_geometry[4] = {
            'polygon': make_poly(L, I4, C, I1),
            'center': h4_cent,
            'inner_vertex': C,
            'icon_position': inner_biased(C, h4_cent, 0.35),
            'planet_area': (h4_cent[0], h4_cent[1], S * 0.2),
            'shape': 'diamond',
            'badge_rect': None,
        }

        # House 7 (Bottom Center): Diamond from B → I3 → C → I4
        # Icon at TOP of diamond (near C)
        h7_cent = centroid(B, I3, C, I4)
        self.house_geometry[7] = {
            'polygon': make_poly(B, I3, C, I4),
            'center': h7_cent,
            'inner_vertex': C,
            'icon_position': inner_biased(C, h7_cent, 0.35),
            'planet_area': (h7_cent[0], h7_cent[1], S * 0.2),
            'shape': 'diamond',
            'badge_rect': None,
        }

        # House 10 (Right Center): Diamond from R → I2 → C → I3
        # Icon at LEFT of diamond (near C)
        h10_cent = centroid(R, I2, C, I3)
        self.house_geometry[10] = {
            'polygon': make_poly(R, I2, C, I3),
            'center': h10_cent,
            'inner_vertex': C,
            'icon_position': inner_biased(C, h10_cent, 0.35),
            'planet_area': (h10_cent[0], h10_cent[1], S * 0.2),
            'shape': 'diamond',
            'badge_rect': None,
        }

        # ===== TRIANGULAR HOUSES (CORNERS - 2 per corner) =====
        # Houses go COUNTER-CLOCKWISE: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12
        # Icon position: near the inner vertex (I1, I2, I3, I4)

        # Triangle cells: badge anchor uses the OUTER-EDGE midpoint biased
        # toward the centroid (NOT the inner vertex). This places the sign
        # badge at the WIDE side of each triangle where there is room for
        # both icon and label, instead of cramming it into the narrow tip
        # near the chart center. The geometry was derived by hand by
        # walking the polygon vertices and picking the widest sub-region.

        # Top-left corner (Houses 2, 3) - counter-clockwise from House 1
        # House 2: Triangle I1 → T → TL (inner vertex is I1, outer edge T-TL)
        h2_cent = centroid(I1, T, TL)
        self.house_geometry[2] = {
            'polygon': make_poly(I1, T, TL),
            'center': h2_cent,
            'inner_vertex': I1,
            'icon_position': outer_biased(midpoint(T, TL), h2_cent, 0.25),
            'planet_area': (h2_cent[0], h2_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,  # populated by _draw_sign_badge
        }

        # House 3: Triangle I1 → TL → L (inner vertex I1, outer edge TL-L)
        h3_cent = centroid(I1, TL, L)
        self.house_geometry[3] = {
            'polygon': make_poly(I1, TL, L),
            'center': h3_cent,
            'inner_vertex': I1,
            'icon_position': outer_biased(midpoint(TL, L), h3_cent, 0.25),
            'planet_area': (h3_cent[0], h3_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # Bottom-left corner (Houses 5, 6)
        # House 5: Triangle I4 → L → BL (inner I4, outer edge L-BL)
        h5_cent = centroid(I4, L, BL)
        self.house_geometry[5] = {
            'polygon': make_poly(I4, L, BL),
            'center': h5_cent,
            'inner_vertex': I4,
            'icon_position': outer_biased(midpoint(L, BL), h5_cent, 0.25),
            'planet_area': (h5_cent[0], h5_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # House 6: Triangle I4 → BL → B (inner I4, outer edge BL-B)
        h6_cent = centroid(I4, BL, B)
        self.house_geometry[6] = {
            'polygon': make_poly(I4, BL, B),
            'center': h6_cent,
            'inner_vertex': I4,
            'icon_position': outer_biased(midpoint(BL, B), h6_cent, 0.25),
            'planet_area': (h6_cent[0], h6_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # Bottom-right corner (Houses 8, 9)
        # House 8: Triangle I3 → B → BR (inner I3, outer edge B-BR)
        h8_cent = centroid(I3, B, BR)
        self.house_geometry[8] = {
            'polygon': make_poly(I3, B, BR),
            'center': h8_cent,
            'inner_vertex': I3,
            'icon_position': outer_biased(midpoint(B, BR), h8_cent, 0.25),
            'planet_area': (h8_cent[0], h8_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # House 9: Triangle I3 → BR → R (inner I3, outer edge BR-R)
        h9_cent = centroid(I3, BR, R)
        self.house_geometry[9] = {
            'polygon': make_poly(I3, BR, R),
            'center': h9_cent,
            'inner_vertex': I3,
            'icon_position': outer_biased(midpoint(BR, R), h9_cent, 0.25),
            'planet_area': (h9_cent[0], h9_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # Top-right corner (Houses 11, 12)
        # House 11: Triangle I2 → R → TR (inner I2, outer edge R-TR)
        h11_cent = centroid(I2, R, TR)
        self.house_geometry[11] = {
            'polygon': make_poly(I2, R, TR),
            'center': h11_cent,
            'inner_vertex': I2,
            'icon_position': outer_biased(midpoint(R, TR), h11_cent, 0.25),
            'planet_area': (h11_cent[0], h11_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # House 12: Triangle I2 → TR → T (inner I2, outer edge TR-T)
        h12_cent = centroid(I2, TR, T)
        self.house_geometry[12] = {
            'polygon': make_poly(I2, TR, T),
            'center': h12_cent,
            'inner_vertex': I2,
            'icon_position': outer_biased(midpoint(TR, T), h12_cent, 0.25),
            'planet_area': (h12_cent[0], h12_cent[1], S * 0.15),
            'shape': 'triangle',
            'badge_rect': None,
        }

        # Store inner diamond coordinates for drawing
        self.inner_diamond = {
            'I1': I1,
            'I2': I2,
            'I3': I3,
            'I4': I4,
        }

        # Store outer points for reference
        self.outer_square = {
            'TL': TL, 'T': T, 'TR': TR,
            'R': R, 'BR': BR, 'B': B,
            'BL': BL, 'L': L
        }

        # Store center
        self.center = C

    def _compute_fit_zoom(self):
        """Return zoom factor that fits the full chart in the current viewport."""
        vp = self.viewport().size()
        side = min(vp.width(), vp.height())
        if side < 100:
            return 0.45  # viewport not laid out yet — safe fallback
        effective_size = self.chart_size
        if self._transit_overlay_active:
            effective_size += 2 * self._get_transit_depth()
        return max(self.min_zoom, min(self.max_zoom, side / effective_size * 0.92))

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
        """Reset zoom to fit the full chart in the current viewport."""
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

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open planet info or sign variation dialog."""
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.items(event.pos()):
                if isinstance(item, NorthIndianPlanetItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.planet_name, item.planet_info)
                    event.accept()
                    return
                if isinstance(item, DiamondCellItem):
                    if item.data(Qt.ItemDataRole.UserRole) == self._TAG:
                        continue
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    self.sign_click_signal.clicked.emit(item.sign_index, 1)
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

    def update_from_chart(self, chart, varga_code=None, use_western_names=False, **_kw):
        """Render diamond from a libaditya Chart (primary entry point)."""
        from libaditya.objects.context import Circle
        self._chart = chart
        self._varga_code = varga_code
        self._has_chart = True
        self.planets_data = True
        self._is_aditya = (chart.context.circle == Circle.ADITYA)
        source = chart.varga(varga_code) if varga_code and varga_code != 1 else chart.rashi()
        self._planets = source.planets()
        self._cusps = source.cusps()
        self.use_western_names = use_western_names
        self.draw_chart()

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
        """Re-apply theme colors (SPEC-THM-001 W1 G04).

        Updates scene background brush and redraws the chart so the inner
        background rectangle (drawn via _draw_background) picks up the new
        theme color. Pre-mortem P-002/P-003 mitigation.
        """
        theme = get_theme_colors()
        self.setBackgroundBrush(QBrush(QColor(theme["secondary_dark"])))
        if self._chart is not None:
            try:
                self.draw_chart()
            except Exception:
                pass
        self.scene.update()
        self.viewport().update()

    def set_aditya_mode(self, mode: str, ayanamsa_offset: float = 0.0):
        """Deprecated — mode is baked into Chart at construction. Kept until Issue 11."""
        self.aditya_mode = mode
        self.ayanamsa_offset = ayanamsa_offset
        if self._chart:
            self.draw_chart()

    def set_use_western_names(self, use_western: bool):
        """
        Set sign name display preference.

        Args:
            use_western: True for Western names (Aries, Taurus...),
                        False for Aditya names (Dhata, Aryama...)
        """
        self.use_western_names = use_western
        # Note: Redraw will happen in set_planets_data() call

    def load_zodiac_icon(self, zodiac_index: int, size: int = 140):
        """Load zodiac icon using Qt best practices."""
        variation = self.get_zodiac_variation(zodiac_index)
        cache_key = f"zodiac_{zodiac_index}_v{variation}_{size}"

        if cache_key in self.zodiac_icons:
            return self.zodiac_icons[cache_key]

        western_name = self.WESTERN_NAMES[zodiac_index]

        # Try with selected variation
        icon_path = PROJECT_ROOT / f"img/sign/{western_name}{variation}.webp"
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/sign/{western_name}1.webp"
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/sign/icons_256/{western_name}.webp"

        if not icon_path.exists():
            print(f"[NORTH INDIAN] Warning: Icon not found for {western_name}")
            return None

        qimage = QImage(str(icon_path))
        if qimage.isNull():
            return None

        qimage = qimage.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        pixmap = QPixmap.fromImage(qimage)
        self.zodiac_icons[cache_key] = pixmap
        return pixmap

    def load_planet_image(self, planet_name: str, size: int = 100):
        """Load planet image using Qt best practices."""
        variation = self.get_planet_variation(planet_name)
        cache_key = f"{planet_name}_v{variation}_{size}"

        if cache_key in self.planet_icons:
            return self.planet_icons[cache_key]

        icon_filename = self.PLANET_ICON_NAMES.get(planet_name, planet_name.lower())

        if variation > 1:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}{variation}.webp"
        else:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"

        if not icon_path.exists():
            print(f"[NORTH INDIAN] Warning: Planet icon not found: {icon_path}")
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

            pixmap = QPixmap.fromImage(qimage)
            self.planet_icons[cache_key] = pixmap
            return pixmap
        except Exception as e:
            print(f"[NORTH INDIAN] Error loading planet image {planet_name}: {e}")
            self.planet_icons[cache_key] = None
            return None

    def _get_ascendant_sign_index(self) -> int:
        """
        Get the zodiac sign index of the Ascendant.

        Supports F4 "Sign as Ascendant" override feature.
        When ascendant_override is set, returns that sign index directly.
        Otherwise, calculates from actual birth Ascendant.

        Returns:
            Sign index 0-11 (0=Dhata/Aries)
        """
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

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
            self.draw_chart()

    def _get_sign_for_house(self, house_num: int) -> int:
        """
        Calculate which sign is in a given house.

        In North Indian charts:
        - House 1 = Ascendant sign
        - House 2 = next sign, etc.

        Args:
            house_num: 1-12

        Returns:
            Sign index 0-11
        """
        asc_sign = self._get_ascendant_sign_index()
        return (asc_sign + house_num - 1) % 12

    def _get_house_for_planet_sign(self, planet_sign_idx: int) -> int:
        """Get house number (1-12) for a planet given its sign index (0-11)."""
        asc_sign = self._get_ascendant_sign_index()
        return ((planet_sign_idx - asc_sign) % 12) + 1

    def draw_chart(self):
        """Main drawing method - draws all chart components."""
        self.scene.clear()
        self.house_cells = {}

        # Layer 1: Background
        self._draw_background()

        # Layer 2: House cells with element colors
        self._draw_house_cells()

        # Layer 3: Inner diamond outline
        self._draw_inner_diamond()

        # Layer 4+5: Sign badges (icon + label as single indivisible unit)
        # Replaces the old separate _draw_zodiac_icons + _draw_sign_names
        # passes. The badge drawer also writes geom['badge_rect'] which
        # _draw_planets_in_house reads to compute the non-overlapping
        # planet zone.
        self._draw_sign_badge()

        # Layer 5.5: Ascendant degree marker (SPEC-NIC-001)
        if self._cusps and self.ascendant_override is None:
            self._draw_ascendant_degree()

        # Layer 6: Planets
        if self._chart:
            self._draw_planets()

        # Force viewport refresh to ensure chart displays immediately
        self.scene.update()
        self.viewport().update()

        # Post-redraw restore: transit overlay survives scene.clear() (SPEC-TRN-003 S5.7)
        if self._transit_overlay_active and self._transit_manager:
            self._expand_scene_for_transit()
            self._calculate_transit_geometry()
            self._draw_transit_overlay()

    def _draw_background(self):
        """Draw the background rectangle."""
        margin = 100
        rect = QGraphicsRectItem(margin, margin,
                                  self.chart_size - 2 * margin,
                                  self.chart_size - 2 * margin)
        # SPEC-THM-001 G04: live theme color (was QColor(SURFACE))
        rect.setBrush(QBrush(QColor(get_theme_colors()["secondary"])))
        rect.setPen(QPen(QColor(GOLD), 4))
        rect.setZValue(0)
        self.scene.addItem(rect)

    def _draw_house_cells(self, geometry=None, tag=None):
        """Draw the 12 house cells with element-based colors."""
        geo = geometry if geometry is not None else self.house_geometry
        for house_num in range(1, 13):
            geom = geo[house_num]
            sign_index = self._get_sign_for_house(house_num)

            cell = DiamondCellItem(
                house_number=house_num,
                polygon=geom['polygon'],
                sign_index=sign_index
            )
            if tag:
                cell.setData(Qt.ItemDataRole.UserRole, tag)
            self.scene.addItem(cell)
            if not tag:
                self.house_cells[house_num] = cell

    def _draw_inner_diamond(self):
        """
        Draw the chart skeleton lines:
        - Diagonals from TL to BR and TR to BL (the cross)

        Note: The inner diamond (I1→I2→I3→I4) is NOT drawn separately
        because it's already defined by the house cell boundaries.
        Drawing it would cut through the angular houses.
        """
        outer = self.outer_square
        pen = QPen(QColor(GOLD), 3)

        # Draw the DIAGONALS only (The Cross)
        diagonal_lines = [
            (outer['TL'], outer['BR']),  # TL to BR
            (outer['TR'], outer['BL']),  # TR to BL
        ]

        for (x1, y1), (x2, y2) in diagonal_lines:
            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(pen)
            line.setZValue(2)
            self.scene.addItem(line)

    def _draw_sign_badge(self, geometry=None, tag=None):
        """Draw the sign BADGE (zodiac icon + name label as one unit) per house.

        Strategy — "indivisible badge" design:
        The sign icon and its text label are treated as a single bounding
        rectangle (the "badge"). The badge is placed at the cell's anchor
        (`geom['icon_position']`, which is already outer-edge-biased for
        triangles and inner-vertex-biased for diamonds). If the badge does
        not fit at the anchor with safety margin, it is shifted along the
        anchor→centroid vector in discrete steps until it fits. If no
        position along that line fits at the current font size, the font
        shrinks and the search repeats. If even MIN_FONT_SIZE does not
        fit, the label is dropped and an icon-only badge is placed at
        whichever position accommodates it.

        The resulting badge rectangle is stored on `geom['badge_rect']`
        so `_draw_planets_in_house` can compute a planet zone that does
        not intersect the badge.

        Z-order (per council review):
            zodiac icon: z = 4.5
            label text:  z = 5
            planets:     z = 6 (unchanged)
            degree lbls: z = 7 (bumped in planet drawer)
        """
        sign_settings = self.display_settings.get("sign_name", {})
        font_size_diamond = sign_settings.get("font_size_diamond", 24)
        font_size_triangle = sign_settings.get("font_size_triangle", 18)
        font_color = sign_settings.get("font_color", GOLD)
        font_weight = sign_settings.get("font_weight", "bold")
        offset_x_user = sign_settings.get("offset_x", 0)
        offset_y_user = sign_settings.get("offset_y", 0)

        qt_weight = QFont.Weight.Bold if font_weight == "bold" else QFont.Weight.Normal
        cjk_lang = self.sign_language in ("zh",)

        # Badge layout constants (scene units — scene is 2048px)
        ICON_LABEL_GAP = 4
        BADGE_MARGIN = 18
        SHIFT_STEP_PX = 10
        MAX_SHIFT_STEPS = 20
        MIN_FONT_SIZE = 10

        def _badge_corners_in(bleft, btop, bw, bh, poly):
            """True if all 4 corners of (bleft, btop, bw, bh) are inside
            poly with BADGE_MARGIN clearance."""
            corners = [
                QPointF(bleft, btop),
                QPointF(bleft + bw, btop),
                QPointF(bleft, btop + bh),
                QPointF(bleft + bw, btop + bh),
            ]
            for c in corners:
                if not self._point_in_polygon_with_margin(c, poly, BADGE_MARGIN):
                    return False
            return True

        geo = geometry if geometry is not None else self.house_geometry
        for house_num in range(1, 13):
            geom = geo[house_num]
            sign_index = self._get_sign_for_house(house_num)
            polygon = geom['polygon']
            centroid = geom['center']
            is_diamond = geom.get('shape') == 'diamond'

            icon_size = 140 if is_diamond else 90

            # Pick the sign name for this display mode
            sign_name = displayed_sign_name(sign_index, self.aditya_mode,
                                            self.use_western_names,
                                            self.sign_language)

            base_font_size = font_size_diamond if is_diamond else font_size_triangle

            # Anchor: outer-edge-biased for triangles, inner-biased for diamonds
            anchor_x, anchor_y = geom['icon_position']
            # Optional user offsets
            anchor_x += offset_x_user
            anchor_y += offset_y_user

            # Shift direction: from anchor toward centroid. If the anchor
            # is already at the centroid (unlikely), we can't shift.
            shift_dx = centroid[0] - anchor_x
            shift_dy = centroid[1] - anchor_y
            shift_len = (shift_dx * shift_dx + shift_dy * shift_dy) ** 0.5
            if shift_len > 1e-6:
                shift_ux = shift_dx / shift_len
                shift_uy = shift_dy / shift_len
            else:
                shift_ux, shift_uy = 0.0, 0.0

            # Try badge (icon + label) at decreasing font sizes. For each
            # font size, march along anchor→centroid looking for a
            # position where all 4 corners clear the polygon by
            # BADGE_MARGIN.
            fitted = False
            badge_left = badge_top = 0.0
            badge_w = badge_h = 0.0
            text_w = text_h = 0.0

            measure_item = QGraphicsTextItem(sign_name)
            measure_item.setDefaultTextColor(QColor(font_color))

            current_size = base_font_size
            while current_size >= MIN_FONT_SIZE:
                w = QFont.Weight.Light if cjk_lang else qt_weight
                measure_item.setFont(QFont("Inter", current_size, w))
                mrect = measure_item.boundingRect()
                text_w = mrect.width()
                text_h = mrect.height()

                bw = max(icon_size, text_w)
                bh = icon_size + ICON_LABEL_GAP + text_h

                # March from anchor toward centroid
                for step in range(MAX_SHIFT_STEPS + 1):
                    cx = anchor_x + shift_ux * step * SHIFT_STEP_PX
                    cy = anchor_y + shift_uy * step * SHIFT_STEP_PX
                    bl = cx - bw / 2
                    bt = cy - bh / 2
                    if _badge_corners_in(bl, bt, bw, bh, polygon):
                        badge_left = bl
                        badge_top = bt
                        badge_w = bw
                        badge_h = bh
                        fitted = True
                        break

                if fitted:
                    break
                current_size -= 2

            # Label drawable only if the full badge fit at some font size
            draw_label = fitted

            if not fitted:
                # Fall back to icon-only badge. Try to place it along the
                # anchor→centroid line.
                badge_w = icon_size
                badge_h = icon_size
                for step in range(MAX_SHIFT_STEPS + 1):
                    cx = anchor_x + shift_ux * step * SHIFT_STEP_PX
                    cy = anchor_y + shift_uy * step * SHIFT_STEP_PX
                    bl = cx - badge_w / 2
                    bt = cy - badge_h / 2
                    if _badge_corners_in(bl, bt, badge_w, badge_h, polygon):
                        badge_left = bl
                        badge_top = bt
                        fitted = True
                        break
                if not fitted:
                    # Last resort: centroid-centered icon, no margin guarantee
                    badge_left = centroid[0] - badge_w / 2
                    badge_top = centroid[1] - badge_h / 2

            # Persist the badge rect on the geom so _draw_planets_in_house
            # can avoid it when computing the planet zone.
            geom['badge_rect'] = (badge_left, badge_top, badge_w, badge_h)

            # ---- Draw the icon at badge top-center ----
            icon_cx = badge_left + badge_w / 2
            icon_cy = badge_top + icon_size / 2
            pixmap = self.load_zodiac_icon(sign_index, size=icon_size)
            if pixmap:
                icon_item = NorthIndianZodiacItem(
                    pixmap, icon_cx, icon_cy, sign_index
                )
                icon_item.setZValue(4.5)  # above cell fill, below label
                if tag:
                    icon_item.setData(Qt.ItemDataRole.UserRole, tag)
                self.scene.addItem(icon_item)

            # ---- Draw the label at badge bottom-center ----
            if draw_label:
                label_item = QGraphicsTextItem(sign_name)
                label_item.setDefaultTextColor(QColor(font_color))
                w = QFont.Weight.Light if cjk_lang else qt_weight
                label_item.setFont(QFont("Inter", current_size, w))
                # Re-measure after font set (redundant but safe)
                lbl_rect = label_item.boundingRect()
                lbl_w = lbl_rect.width()
                label_x = badge_left + (badge_w - lbl_w) / 2
                label_y = badge_top + icon_size + ICON_LABEL_GAP
                label_item.setPos(label_x, label_y)
                label_item.setZValue(5)  # below planets (z=6)
                if tag:
                    label_item.setData(Qt.ItemDataRole.UserRole, tag)
                self.scene.addItem(label_item)

    def _draw_ascendant_degree(self, geometry=None, tag=None,
                               house_num=1, cusps_source=None):
        """Draw ASC degree label next to the sign name (SPEC-NIC-001 S3)."""
        geo = geometry if geometry is not None else self.house_geometry
        cusps = cusps_source if cusps_source is not None else self._cusps
        if not cusps:
            return
        asc_cusp = cusps[1]
        if self._varga_code and cusps_source is None:
            asc_risl = asc_cusp.amsha_raw_in_sign_longitude()
        else:
            asc_risl = asc_cusp.real_in_sign_longitude()
        degrees = int(asc_risl)
        minutes = int((asc_risl % 1) * 60)
        label_text = f"ASC {degrees}°{minutes:02d}'"

        label = QGraphicsTextItem(label_text)
        label.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        label.setDefaultTextColor(QColor("#FFFFFF"))
        label.setZValue(5.5)

        lw = label.boundingRect().width()
        lh = label.boundingRect().height()
        cell = geo[house_num]
        cx, cy = cell['center']
        poly = cell['polygon']
        badge_rect = cell.get('badge_rect')

        side_placement = house_num in (2, 6, 8, 12)

        if badge_rect is not None:
            bl, bt, bw, bh = badge_rect
            badge_cx = bl + bw / 2

            if side_placement:
                icon_sz = 90
                sign_y = bt + icon_sz + 4
                lx = bl + bw + 8
                ly = sign_y
                pt = QPointF(lx + lw / 2, ly + lh / 2)
                if not poly.containsPoint(pt, Qt.FillRule.OddEvenFill):
                    lx = bl - lw - 8
                    ly = sign_y
                    pt = QPointF(lx + lw / 2, ly + lh / 2)
                if not poly.containsPoint(pt, Qt.FillRule.OddEvenFill):
                    lx = cx - lw / 2
                    ly = cy - lh / 2
            else:
                lx = badge_cx - lw / 2
                ly = bt + bh + 4
                pt = QPointF(lx + lw / 2, ly + lh / 2)
                if not poly.containsPoint(pt, Qt.FillRule.OddEvenFill):
                    lx = cx - lw / 2
                    ly = cy - lh / 2 - 20
        else:
            lx = cx - lw / 2
            ly = cy - lh / 2

        label.setPos(lx, ly)
        if tag:
            label.setData(Qt.ItemDataRole.UserRole, tag)
        self.scene.addItem(label)

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

    def _draw_planets(self):
        """Draw all planets in their respective houses with stacking."""
        if not self._planets:
            return
        planets_to_draw = list(self.DISPLAY_PLANETS)
        if self.show_outer_planets:
            planets_to_draw.extend(["Uranus", "Neptune", "Pluto"])

        planets_by_house = {i: [] for i in range(1, 13)}

        for planet_name in planets_to_draw:
            if planet_name == "Ascendant":
                continue
            try:
                planet = self._planets[planet_name]
            except KeyError:
                continue
            sign_idx = planet.sign() - 1
            house = self._get_house_for_planet_sign(sign_idx)
            risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
            planets_by_house[house].append({
                "name": planet_name,
                "deg_in_sign": risl,
                "planet_obj": planet,
            })

        # Draw planets in each house with stacking
        for house_num, planets in planets_by_house.items():
            if not planets:
                continue

            self._draw_planets_in_house(house_num, planets)

    def _draw_planets_in_house(self, house_num: int, planets: list,
                              geometry=None, tag=None):
        """
        Draw planets in a specific house using the 4-candidate planet zone
        search recommended by the Codex council judge.

        Args:
            house_num: 1-12
            planets: List of planet dicts with 'name', 'deg_in_sign', 'planet_obj'
            geometry: Optional geometry dict (defaults to self.house_geometry)
            tag: Optional item tag for transit cleanup
        """
        geo = geometry if geometry is not None else self.house_geometry
        geom = geo[house_num]
        polygon = geom['polygon']
        centroid = geom['center']
        is_diamond = geom.get('shape') == 'diamond'
        badge_rect = geom.get('badge_rect')  # may be None if badge failed

        inner_vertex = geom.get('inner_vertex', centroid)

        # Get display settings for planet sizes and degrees
        planet_sizes = self.display_settings.get("planet_sizes", {})
        deg_settings = self.display_settings.get("planet_degrees", {})
        deg_font_size = deg_settings.get("font_size", 14)
        deg_font_color = deg_settings.get("font_color", "#FFFFFF")
        deg_font_weight = deg_settings.get("font_weight", "normal")
        deg_offset_x = deg_settings.get("offset_x", 0)
        deg_offset_y = deg_settings.get("offset_y", 0)

        count = len(planets)
        if count == 0:
            return

        # ---- Step 1: Four candidate planet-zone centers ----
        aspect = 1.0 if is_diamond else 1.3
        rect_margin = 20.0 if is_diamond else 28.0

        if badge_rect is not None:
            badge_cx = badge_rect[0] + badge_rect[2] / 2
            badge_cy = badge_rect[1] + badge_rect[3] / 2
            # OPPOSITE: mirror badge across centroid
            opp_x = 2 * centroid[0] - badge_cx
            opp_y = 2 * centroid[1] - badge_cy
        else:
            opp_x, opp_y = centroid

        ix, iy = inner_vertex

        candidates = [
            ("opposite", (opp_x, opp_y)),
            ("centroid", (centroid[0], centroid[1])),
            ("inner-mid", (centroid[0] + 0.5 * (ix - centroid[0]),
                            centroid[1] + 0.5 * (iy - centroid[1]))),
            ("inner-deep", (centroid[0] + 0.75 * (ix - centroid[0]),
                             centroid[1] + 0.75 * (iy - centroid[1]))),
        ]

        best_rect = None
        best_area = -1.0
        for _name, cand_center in candidates:
            cand_rect = self._inscribed_rect_avoiding(
                polygon, cand_center, badge_rect,
                aspect=aspect, margin=rect_margin
            )
            _, _, cw, ch = cand_rect
            area = cw * ch
            if area > best_area:
                best_area = area
                best_rect = cand_rect

        rect_left, rect_top, rect_w, rect_h = best_rect
        # Fallback if the 4-candidate search found nothing usable
        if rect_w < 20 or rect_h < 20:
            rect_left, rect_top, rect_w, rect_h = self._inscribed_rect(
                polygon, centroid, aspect=aspect, margin=rect_margin
            )

        # Center used by the pull-toward-centroid safety fallback later
        cx = rect_left + rect_w / 2
        cy = rect_top + rect_h / 2

        # ---- Step 2: Choose grid dimensions ----
        # Favor wider grids for low counts, square-ish grids for high counts.
        if count == 1:
            cols, rows = 1, 1
        elif count == 2:
            cols, rows = 2, 1
        elif count == 3:
            cols, rows = 3, 1
        elif count == 4:
            cols, rows = 2, 2
        elif count <= 6:
            cols, rows = 3, 2
        elif count <= 9:
            cols, rows = 3, 3
        else:
            cols = 4
            rows = (count + cols - 1) // cols

        # ---- Step 3: Size each planet ----
        cell_w = rect_w / cols
        cell_h = rect_h / rows
        # Leave 10% of slot as internal padding; reserve ~22px at slot bottom
        # for the degree label so planet + label both fit.
        label_reserve = 22
        slot_w = cell_w * 0.90
        slot_h = max(cell_h * 0.90 - label_reserve, cell_h * 0.55)

        # Planet icon side length — square, fits in the smaller slot dimension.
        max_fit = min(slot_w, slot_h)
        base_ref_size = 100  # "nominal" size to scale toward
        # Start from the user's configured size, cap to max_fit, clamp min.
        MIN_PLANET_SIZE = 48
        MAX_PLANET_SIZE = 110

        # ---- Step 4: Row-major placement inside the inscribed rect ----
        planet_items = []  # (x, y, size, planet) for post-placement label draw

        for i, planet in enumerate(planets):
            row = i // cols
            col = i % cols

            # Grid slot center (inside the inscribed rectangle).
            # Vertical slot center is shifted up to leave room for label below.
            px_slot = rect_left + (col + 0.5) * cell_w
            py_slot = rect_top + (row + 0.5) * cell_h - label_reserve / 2

            # Per-planet size = user setting clamped to slot fit
            user_size = planet_sizes.get(
                planet["name"], self.PLANET_SIZES.get(planet["name"], base_ref_size)
            )
            size = int(max(MIN_PLANET_SIZE, min(user_size, max_fit, MAX_PLANET_SIZE)))

            # ---- Step 5: Pull-toward-centroid safety check ----
            # If the slot center escaped the polygon (triangle tips), blend
            # with centroid until it's safely inside.
            pt = QPointF(px_slot, py_slot)
            if not self._point_in_polygon_with_margin(pt, polygon, margin=size * 0.45):
                for blend in (0.2, 0.4, 0.6, 0.8):
                    test_x = px_slot + (cx - px_slot) * blend
                    test_y = py_slot + (cy - py_slot) * blend
                    if self._point_in_polygon_with_margin(
                        QPointF(test_x, test_y), polygon, margin=size * 0.45
                    ):
                        px_slot, py_slot = test_x, test_y
                        break
                else:
                    # Last resort — place at centroid
                    px_slot, py_slot = cx, cy

            pixmap = self.load_planet_image(planet["name"], size=size)
            if pixmap:
                p_obj = planet.get("planet_obj")
                click_dict = self._planet_to_click_dict(planet["name"], p_obj) if p_obj else planet
                item = NorthIndianPlanetItem(
                    pixmap, px_slot, py_slot,
                    planet["name"], click_dict,
                    self.planet_click_signal
                )
                if tag:
                    item.setData(Qt.ItemDataRole.UserRole, tag)
                self.scene.addItem(item)
                planet_items.append((px_slot, py_slot, size, planet))

        # ---- Step 6: Draw degree labels, clamped to polygon ----
        for px, py, size, planet in planet_items:
            font_size = deg_font_size - 2 if count > 4 else deg_font_size

            # Create a dummy label to measure its bounding rect, then clamp.
            # We can't easily measure PlanetDegreeLabel before instantiation,
            # so we use a naive position then push toward centroid if needed.
            naive_y = py + size / 2 + 12 + deg_offset_y
            naive_x = px + deg_offset_x

            # Approximate label bounding box (3–5 chars × font_size × 0.6 width)
            approx_label_w = font_size * 3.5
            approx_label_h = font_size * 1.4
            label_tl_x = naive_x - approx_label_w / 2
            label_tl_y = naive_y

            clamped_x, clamped_y = self._clamp_text_inside(
                approx_label_w, approx_label_h, label_tl_x, label_tl_y,
                polygon, centroid, margin=8.0
            )
            # Convert back from top-left to center for PlanetDegreeLabel
            label_center_x = clamped_x + approx_label_w / 2
            label_center_y = clamped_y + approx_label_h / 2

            label_override = ""
            if self.show_planet_names:
                label_override = get_planet_display_name(
                    self.sign_language, planet["name"])
            label = PlanetDegreeLabel(
                label_center_x, label_center_y, planet["deg_in_sign"], font_size,
                font_color=deg_font_color, font_weight=deg_font_weight,
                label_override=label_override
            )
            if tag:
                label.setData(Qt.ItemDataRole.UserRole, tag)
            self.scene.addItem(label)

    def clear_chart(self):
        """Clear the chart display."""
        self._has_chart = False
        self._chart = None
        self._planets = None
        self._cusps = None
        self.planets_data = None
        self.scene.clear()
        self.house_cells = {}
        self._transit_overlay_active = False
        self._transit_manager = None
        self._restore_scene_rect()

        # Draw empty chart structure
        self._draw_background()
        self._draw_house_cells()
        self._draw_inner_diamond()

    # =================================================================
    # TRANSIT OVERLAY (SPEC-TRN-003 v2.0)
    # Reuses natal drawing code via parameterized geometry/tag.
    # =================================================================

    _TAG = "ni_transit"

    def _get_transit_depth(self):
        """S/2: exact mirror of natal cells."""
        margin = 100
        S = self.chart_size - 2 * margin
        return S / 2

    def update_transit_overlay(self, manager):
        """Public entry point called by core_gui_qt mediator."""
        self._transit_manager = manager
        if manager.transit_enabled and manager.transit_planets:
            self._transit_overlay_active = True
            self._hide_transit_overlay()
            self._expand_scene_for_transit()
            self._calculate_transit_geometry()
            self._draw_transit_overlay()
        else:
            self._transit_overlay_active = False
            self._hide_transit_overlay()
            self._restore_scene_rect()

    def _expand_scene_for_transit(self):
        """Expand scene rect to accommodate full-mirror outer ring."""
        padding = 50
        depth = self._get_transit_depth()
        if self._original_scene_rect is None:
            self._original_scene_rect = self.sceneRect()
        self.setSceneRect(
            -padding - depth, -padding - depth,
            self.chart_size + 2 * padding + 2 * depth,
            self.chart_size + 2 * padding + 2 * depth
        )

    def _restore_scene_rect(self):
        """Restore original scene rect when transit is disabled."""
        if self._original_scene_rect is not None:
            self.setSceneRect(self._original_scene_rect)
            self._original_scene_rect = None

    def _calculate_transit_geometry(self):
        """Compute transit geometry dict with the SAME shape as
        house_geometry so _draw_house_cells, _draw_sign_badge, and
        _draw_planets_in_house can consume it identically."""
        sq = self.outer_square
        margin = 100
        S = self.chart_size - 2 * margin
        depth = self._get_transit_depth()
        cx, cy = self.cx, self.cy

        TL = sq['TL']
        T = sq['T']
        TR = sq['TR']
        R = sq['R']
        BR = sq['BR']
        B = sq['B']
        BL = sq['BL']
        L = sq['L']

        OT = (cx, margin - depth)
        OL = (margin - depth, cy)
        OB = (cx, margin + S + depth)
        OR_pt = (margin + S + depth, cy)

        def mid(a, b):
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

        def make_poly(*points):
            return QPolygonF([QPointF(p[0], p[1]) for p in points])

        def centroid(*points):
            x = sum(p[0] for p in points) / len(points)
            y = sum(p[1] for p in points) / len(points)
            return (x, y)

        def outer_biased(outer_pt, cent, blend=0.25):
            return (outer_pt[0] + blend * (cent[0] - outer_pt[0]),
                    outer_pt[1] + blend * (cent[1] - outer_pt[1]))

        E1 = mid(TL, OT)
        E2 = mid(TR, OT)
        E3 = mid(TL, OL)
        E4 = mid(BL, OL)
        E5 = mid(BL, OB)
        E6 = mid(BR, OB)
        E7 = mid(TR, OR_pt)
        E8 = mid(BR, OR_pt)

        def _cell(pts, shape, inner_vtx, icon_anchor):
            poly = make_poly(*pts)
            cent = centroid(*pts)
            return {
                'polygon': poly,
                'center': cent,
                'inner_vertex': inner_vtx,
                'icon_position': outer_biased(icon_anchor, cent, 0.3),
                'planet_area': (cent[0], cent[1], S * 0.15),
                'shape': shape,
                'badge_rect': None,
            }

        self._transit_geometry = {
            1:  _cell((T, E1, OT, E2),    'diamond',  T,  OT),
            2:  _cell((TL, E1, T),         'triangle', E1, mid(TL, T)),
            12: _cell((T, E2, TR),         'triangle', E2, mid(T, TR)),
            4:  _cell((L, E3, OL, E4),     'diamond',  L,  OL),
            3:  _cell((TL, E3, L),         'triangle', E3, mid(TL, L)),
            5:  _cell((L, E4, BL),         'triangle', E4, mid(L, BL)),
            7:  _cell((B, E5, OB, E6),     'diamond',  B,  OB),
            6:  _cell((BL, E5, B),         'triangle', E5, mid(BL, B)),
            8:  _cell((B, E6, BR),         'triangle', E6, mid(B, BR)),
            10: _cell((R, E7, OR_pt, E8),  'diamond',  R,  OR_pt),
            11: _cell((TR, E7, R),         'triangle', E7, mid(TR, R)),
            9:  _cell((R, E8, BR),         'triangle', E8, mid(R, BR)),
        }

    def _draw_transit_overlay(self):
        """Render transit overlay by calling the same drawing functions
        as natal, parameterized with transit geometry and data."""
        if not self._transit_geometry or not self._transit_manager:
            return
        mgr = self._transit_manager
        if not mgr.transit_planets:
            return

        tag = self._TAG
        geo = self._transit_geometry

        self._draw_house_cells(geometry=geo, tag=tag)
        self._draw_sign_badge(geometry=geo, tag=tag)

        planets_to_draw = [
            n for n in self._TRANSIT_PLANET_NAMES
            if n not in ("Uranus", "Neptune", "Pluto")
            or self.show_outer_planets
        ]
        planets_by_house = {i: [] for i in range(1, 13)}
        for planet_name in planets_to_draw:
            try:
                planet = mgr.transit_planets[planet_name]
                sign_idx = planet.sign() - 1
                house_num = self._get_house_for_planet_sign(sign_idx)
                deg_in_sign = planet.real_in_sign_longitude()
                planets_by_house[house_num].append({
                    "name": planet_name,
                    "deg_in_sign": deg_in_sign,
                    "planet_obj": planet,
                })
            except (KeyError, AttributeError, TypeError):
                continue

        for house_num, planets in planets_by_house.items():
            if planets:
                self._draw_planets_in_house(
                    house_num, planets, geometry=geo, tag=tag)

        # Transit ascendant marker (SPEC-TRN-003 S5.4)
        if mgr.transit_cusps and self._cusps:
            try:
                natal_asc = self._cusps[1].sign() - 1
                transit_asc_sign = mgr.transit_cusps[1].sign() - 1
                transit_asc_house = ((transit_asc_sign - natal_asc) % 12) + 1
                self._draw_ascendant_degree(
                    geometry=geo, tag=tag,
                    house_num=transit_asc_house,
                    cusps_source=mgr.transit_cusps)
            except (IndexError, AttributeError, TypeError):
                pass

        self.scene.update()
        self.viewport().update()

    def _hide_transit_overlay(self):
        """Remove all items tagged 'ni_transit' from the scene."""
        tag = self._TAG
        to_remove = [
            item for item in self.scene.items()
            if item.data(Qt.ItemDataRole.UserRole) == tag
        ]
        for item in to_remove:
            self.scene.removeItem(item)
