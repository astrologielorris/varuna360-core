# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""SPEC-SIC-002: experimental VECTOR South Indian chart theme.

This module hosts ``SouthIndianVectorView`` — a ground-up vector South
Indian chart adopting the North Indian design language (element-colored
gradient cards, gold linework) while keeping the South Indian layout,
geometry, and public API. The classic image-backed view
(``apps/widgets/chart_view.py``, frozen per INV-10) remains available as the
"classic" theme; ``display.south_indian_style`` selects which renders.

Wave 1 (bead td-lizg.1) shipped the geometry foundation: the module
constants and the pure, headless-testable functions below (the T-1/T-2 test
seam, spec §4.2).

Wave 2a (bead td-lizg.2) adds the view CHROME: scene/zoom boilerplate
(re-derived from the NI donor per D-8), the gold outer frame, the center
medallion (bare — the center block is reserved content space, spec v0.6),
the 12 element gradient cards, variation-aware sign badges with pill
backdrops, Whole Sign house numbers, Campanus cusp labels, and inert hover
zones.

Wave 2b (bead td-lizg.4) adds the rest of the Phase-1 view: the
degree-ordered planet row (INV-6) with crowded shrink and per-icon shadows,
the lagna stripe + ASC label, click signals with view-level double-click
detection (§4.5), ``render_to_image()`` and the full INV-5 protocol
(§3/§4.6 stubs included). Call-site wiring (host widget) is Wave 3.

Geometry: a fixed 2048×2048 scene, a 4×4 grid of 512px cells. The 12 sign
cells sit on the perimeter (sign→cell mapping is EXACTLY
``SouthIndianView.ZODIAC_POSITIONS``, imported read-only per INV-1), inset
by a 12px gutter into 488×488 rounded cards; the central 2×2 block is the
medallion area. Houses are Whole Sign (INV-2): they rotate against the
fixed signs as ``house = (sign - asc_sign) % 12 + 1``.
"""

from pathlib import Path
import math
import weakref

from PySide6.QtCore import QObject, Qt, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QStackedLayout,
    QWidget,
)

from managers.settings_manager import (
    DEFAULT_SOUTH_INDIAN_STYLE,
    SOUTH_INDIAN_STYLES,
)

# INV-1: the sign→cell mapping is the classic view's class constant, imported
# (never copied) so the two themes can never drift apart. chart_view pulls in
# Qt, which is fine — this module is Qt-based too.
from apps.widgets.chart_view import SouthIndianView

# The ONE center-mini renderer (SPEC-VGC-001 INV-1). It imports neither view,
# so this arrow stays one-way. Imported for USE, not re-export: anything that
# wants these names takes them from center_mini, or INV-1 is cosmetic.
from apps.widgets.center_mini import (
    CenterMiniCache,
    CenterMiniItem,
    record_center_picture,
)

# INV-7/INV-8: colors come ONLY from the theme module and the shared element
# table — no raw hex literals in this file.
from ui.qt_theme import (
    GOLD,
    get_theme_colors,
    desat_image,
    get_ui_saturation,
    desat_hex,
)
from visualizations.wheel_constants import (
    ELEMENT_COLORS,
    element_text_color,
    get_element_for_sign,
)
from core.aditya_mode import displayed_sign_name, get_planet_display_name

# SPEC-COT-001 §4.10 — the in-sign card index. The setting, the memoised
# spread and the plaque art are shared with the wheel and North Indian views;
# only WHERE the plaque goes is this view's business.
from apps.widgets.cot_index_item import COT_SETTING_KEY, CotIndexMixin, CotPlaque

ZODIAC_POSITIONS = SouthIndianView.ZODIAC_POSITIONS

# Scene/cell geometry (spec §4.2; radius/gutter are OD-1, confirmed at T-8).
SCENE_SIZE = 2048
CELL_SIZE = 512
GUTTER = 12
CARD_SIZE = CELL_SIZE - 2 * GUTTER      # 488
CARD_RADIUS = 28
CONTENT_PADDING = 24

# sign_index -> (row, col), the inverse of ZODIAC_POSITIONS.
_SIGN_CELLS = {sign: cell for cell, sign in ZODIAC_POSITIONS.items()}


def cell_rect(sign_index: int) -> QRectF:
    """Return the card rect for a sign (0-11) in scene coordinates.

    The sign's 512px grid cell inset by GUTTER on every side, yielding a
    CARD_SIZE×CARD_SIZE card.

    Raises:
        ValueError: if sign_index is not one of the 12 zodiac indices.
    """
    if sign_index not in _SIGN_CELLS:
        raise ValueError(f"unknown sign_index: {sign_index!r}")
    row, col = _SIGN_CELLS[sign_index]
    return QRectF(
        col * CELL_SIZE + GUTTER,
        row * CELL_SIZE + GUTTER,
        CARD_SIZE,
        CARD_SIZE,
    )


def center_rect() -> QRectF:
    """Return the central 2×2 medallion block, inset by GUTTER like the cards."""
    origin = CELL_SIZE + GUTTER                      # 524
    size = 2 * CELL_SIZE - 2 * GUTTER                # 1000
    return QRectF(origin, origin, size, size)


def house_number_for_sign(sign_index: int, asc_sign_index: int) -> int:
    """Return the Whole Sign house number (1-12) of a sign for an ascendant.

    INV-2: houses rotate against the fixed signs;
    ``house = (sign_index - asc_sign_index) % 12 + 1``.

    Raises:
        ValueError: if either index is not one of the 12 zodiac indices.
    """
    if sign_index not in _SIGN_CELLS:
        raise ValueError(f"unknown sign_index: {sign_index!r}")
    if not 0 <= asc_sign_index <= 11:
        raise ValueError(f"unknown asc_sign_index: {asc_sign_index!r}")
    return (sign_index - asc_sign_index) % 12 + 1


# ---------------------------------------------------------------------------
# Wave 2a (bead td-lizg.2): view chrome
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Namespaced UserRole tags (INV-9). Items are tracked by these tags, never by
# Python lists retained across scene.clear().
TAG_FRAME = "si.vector.frame"
TAG_MEDALLION = "si.vector.medallion"
TAG_MEDALLION_RING = "si.vector.medallion.ring"
TAG_CARD = "si.vector.card"
TAG_SIGN_ICON = "si.vector.sign_icon"
TAG_SIGN_NAME = "si.vector.sign_name"
TAG_BADGE_PILL = "si.vector.badge_pill"
TAG_COT_CARD = "si.vector.cot_card"
TAG_HOUSE_NUMBER = "si.vector.house_number"
TAG_CUSP = "si.vector.cusp"
TAG_HOVER = "si.vector.hover"

SIGN_ICON_SIZE = 96          # spec §4.3 — NI badge language, 96px icons
MIN_BADGE_FONT_SIZE = 10     # NI shrink-floor convention (spec §4.3)
HOUSE_NUMBER_FONT_SIZE = 20  # "modest" quiet label (spec §4.3)
BADGE_PILL_PAD_X = 18        # sign-name pill horizontal padding (T-8 rev.)
BADGE_PILL_PAD_Y = 10        # sign-name pill vertical padding (T-8 rev.)

# ---- Cards of Truth in-sign index (SPEC-COT-001 §4.10) --------------------
# The card each sign owns by LORDSHIP, drawn as a rank + suit plaque in the
# empty middle of the top band, between the sign-name pill and the sign glyph.
# The plaque metrics live in cot_index_item; this scene renders at the size
# they were tuned for, so it scales them by 1.
COT_INDEX_MIN_GAP = 46       # below this the band is too tight — draw nothing


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


# ---------------------------------------------------------------------------
# Wave 2b (bead td-lizg.4): planets, lagna stripe, signals, INV-5 protocol
# ---------------------------------------------------------------------------

TAG_PLANET = "si.vector.planet"
TAG_PLANET_TEXT = "si.vector.planet_text"
TAG_LAGNA = "si.vector.lagna"
TAG_LAGNA_LABEL = "si.vector.lagna_label"
TAG_TRANSIT = "si.vector.transit"

# F8 hides these when show_outer_planets is False (classic chart_view.py:2775)
OUTER_PLANETS = frozenset({"Uranus", "Neptune", "Pluto"})

# Planet row vertical position inside the card (spec §4.3)
PLANET_ROW_HEIGHT_FRACTION = 0.60

# Mini transit chart inset inside the medallion (SPEC-SIC-003 §4.1): clears
# the gold inner ring (18px) plus a margin, so the ring frames the mini.
TRANSIT_MEDALLION_INSET = 24

# D-4: how the mini transit chart is set apart from the natal cards around
# it. The classic theme flips the mini to a contrasting stone background so
# it cannot be misread as the natal chart; the vector theme needs its own
# answer. All four candidates share one rendering path — only this constant
# changes. Renders for the on-screen pick:
#   scripts/render_transit_mini_candidates.py
# Lorris picked "none" from the rendered candidates (D-4, 2026-07-26): the
# mini keeps the full element palette, undimmed. It already reads as a
# separate chart because it is inset inside the medallion's gold ring at a
# quarter of the scale, so dimming it only cost legibility.
#
# Only "veil" survives as an alternative. "gold" and "desaturate" were pixel
# operations on a baked image; the mini is now replayed as vector commands
# (CenterMiniItem) so it stays sharp at any zoom, and per-pixel recolouring
# has no place in that path. Veil is a paint-time overlay, so it still works.
TRANSIT_MINI_TREATMENT = "none"   # "veil" | "none"


def varga_label(varga_code):
    """The name to write in the middle of a center mini, or None.

    Only a divisional chart gets one: transit is always D-1 rashi, so a
    label there would say nothing. With the main chart on D-1 and a second
    chart drawn inside it, this answers the question the feature creates —
    WHICH divisional chart is that?
    """
    if varga_code is None:
        return None
    from core.varga_codes import (
        from_libaditya_varga_code,
        varga_display_label,
    )
    return f"D-{varga_display_label(from_libaditya_varga_code(varga_code))}"


def crowded_planet_size(base_size: int, num_planets: int) -> int:
    """Crowded-sign shrink (INV-6) — behavior matches the frozen classic
    (chart_view.py:2807-2822), 64px floor included: 1-3 planets full size,
    4-5 one tier down (~75%), 6+ forced to 64px."""
    if num_planets <= 3:
        return base_size
    if num_planets <= 5:
        return int(base_size * 0.75)
    return 64


def lone_planet_zone(risl: float) -> int:
    """Degree-zone third (0/1/2) for a lone planet's in-sign longitude
    (SPEC-SIC-001, classic chart_view.py:2880): 0-10° left, 10-20° middle,
    20-30° right."""
    if risl < 10:
        return 0
    if risl < 20:
        return 1
    return 2


class PlanetClickSignal(QObject):
    """Emitter for planet double-click events (classic chart_view.py:119-121)."""
    clicked = Signal(str, dict)  # (planet_name, planet_info)


class SignClickSignal(QObject):
    """Emitter for sign double-click events (classic chart_view.py:142-144)."""
    clicked = Signal(int, int)  # (zodiac_index, current_variation)


class ClickablePlanetItem(QGraphicsPixmapItem):
    """Planet icon carrying the payload the double-click signal emits.

    Passive (accepts NO mouse buttons): the view detects double-clicks via
    items(event.pos()) — the classic stuck-pan fix (chart_view.py:695-716).
    """

    def __init__(self, pixmap, planet_name, planet_info, signal_emitter,
                 parent=None):
        super().__init__(pixmap, parent)
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
        self.zodiac_index = zodiac_index
        self.current_variation = current_variation
        self.signal_emitter = signal_emitter
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)


class SouthIndianVectorView(CotIndexMixin, QGraphicsView):
    """Vector South Indian chart view (SPEC-SIC-002).

    Wave 2a scope: chrome only — frame, medallion, cards, badges, house
    numbers, cusps, hover zones, zoom/pan. No planets, no lagna stripe, no
    signals (Wave 2b). Never renders a raster background: INV-3/D-11 make
    the decorative allowlist empty in Phase 1, so ``set_background`` only
    stores the id.
    """

    # INV-5 class constants, re-exported read-only from the frozen classic
    # view (body_graph_view and the sign selector read them off the class).
    WESTERN_NAMES = SouthIndianView.WESTERN_NAMES
    ADITYA_NAMES = SouthIndianView.ADITYA_NAMES
    PLANET_NAMES = SouthIndianView.PLANET_NAMES
    PLANET_ICON_NAMES = SouthIndianView.PLANET_ICON_NAMES
    # Fallback planet sizes when the settings block lacks a planet.
    PLANET_SIZES = SouthIndianView.PLANET_SIZES

    def __init__(self, parent=None, center_box_enabled=True):
        super().__init__(parent)
        self.center_box_enabled = center_box_enabled

        # INV-5: scene as an ATTRIBUTE (shadows QGraphicsView.scene()) —
        # export and dual-chart hosts access ``.scene`` directly. NoIndex
        # prevents Qt BSP tree corruption (NI donor :72, Qt Forum #71316).
        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.scene.setSceneRect(0, 0, SCENE_SIZE, SCENE_SIZE)
        self.setScene(self.scene)

        # Zoom settings (NI donor :143-145)
        self.zoom_factor = 0.45  # overwritten by _apply_fit_zoom on first show
        self._fit_zoom_applied = False
        self.min_zoom = 0.2
        self.max_zoom = 3.0
        self.zoom_step = 1.15

        # Chart state
        self._chart = None
        self._varga_code = None
        self._use_western_names = False
        self._aditya_mode = "aditya"
        self._cusps = None
        self._chart_name = ""
        self._has_chart = False
        self.sign_language = "en"

        # F4 "Sign as Ascendant" override: None = real Ascendant from cusps
        self.ascendant_override = None

        # F8/F11 toggles — plain attributes the host writes directly
        # (classic defaults: chart_view.py:434, core_gui_qt.py:3700-3724)
        self.show_outer_planets = True
        self.show_planet_names = False

        self._planets = None

        self.time_adjust_mode = False
        self._z6b_selection = None

        # Transit overlay (SPEC-SIC-003 §4.1). `_transit_manager` is any
        # source satisfying INV-4 — the real TransitOverlayManager, or the
        # comparison panel's adapter, which has NO transit_jd and no state
        # machine. The mini is cached as PAINT COMMANDS, never pixels, and
        # invalidated by event rather than by a value key (SPEC-SIC-003
        # INV-9/INV-11).
        self._transit_manager = None
        self._transit_overlay_active = False
        self._mini_transit_view = None
        self._center_cache = CenterMiniCache()

        # SPEC-VGC-001: the divisional chart drawn INSIDE the center box
        # while the outer grid stays on D-1. None = no center varga. Set by
        # set_center_varga(); outranked by transit and time adjust (§3.2).
        self._center_varga_code = None

        # Click signal emitters (classic pattern chart_view.py:121/142-144)
        self.planet_click_signal = PlanetClickSignal()
        self.sign_click_signal = SignClickSignal()

        # Phase 1 decorative background: stored, never rendered (D-11/INV-3)
        self._background_id = None

        # SPEC-COT-001 §4.10: caches + the live-update subscription for both
        # keys that change what the in-sign index shows. Without the
        # subscription the Settings checkbox writes a value no open chart picks
        # up until the next chart load, which reads as "the setting does
        # nothing" — the exact bug D-7 was.
        self._cot_init()

        # Display settings (south_indian_display block) — read-only here;
        # never mutate the returned dict in place (shallow-copy gotcha).
        # Stored under a private name: the public display_settings property
        # below is a STORING NO-OP (Phase-3 review finding 2).
        self._si_display_settings = self._load_display_settings()
        self._variation_settings = self._load_variation_settings()
        self._planet_variation_settings = self._load_planet_variation_settings()

        # `_badge_band` is filled by _draw_sign_badge with the leftover top-band
        # space per sign, so the index positions itself against the font the
        # badge actually solved for rather than re-deriving it.
        self._badge_band = {}

        # Sign icon cache keyed (sign, variation, size)
        self._icon_cache = {}
        # Planet icon cache keyed (planet, variation, size)
        self._planet_icon_cache = {}

        self._setup_view()

    # ------------------------------------------------------------------
    # View boilerplate (re-derived from the NI donor, D-8)
    # ------------------------------------------------------------------

    def _setup_view(self):
        """Configure render hints, drag, focus, and background (NI :252-277)."""
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._is_dragging = False
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        # StrongFocus so keyPressEvent receives the +/- /0 zoom shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setBackgroundBrush(
            QBrush(QColor(get_theme_colors()["secondary_dark"])))

    def _compute_fit_zoom(self):
        """Return zoom factor that fits the full chart in the current viewport."""
        vp = self.viewport().size()
        side = min(vp.width(), vp.height())
        if side < 100:
            return 0.45  # viewport not laid out yet — safe fallback
        return max(self.min_zoom,
                   min(self.max_zoom, side / SCENE_SIZE * 0.92))

    def _apply_fit_zoom(self):
        """Deferred auto-fit — runs after layout (viewport size valid)."""
        if self._fit_zoom_applied:
            return
        self._fit_zoom_applied = True
        self.zoom_factor = self._compute_fit_zoom()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(SCENE_SIZE / 2, SCENE_SIZE / 2)

    def showEvent(self, event):
        """On first show: defer auto-fit via timer. Later: re-apply zoom."""
        super().showEvent(event)
        if not self._fit_zoom_applied:
            QTimer.singleShot(0, self._apply_fit_zoom)
        else:
            self.resetTransform()
            self.scale(self.zoom_factor, self.zoom_factor)
            self.centerOn(SCENE_SIZE / 2, SCENE_SIZE / 2)

    def wheelEvent(self, event):
        """Cursor-anchored zoom (NI donor :809-862).

        Cross-platform: pixelDelta on macOS, kinetic-momentum filtering on
        Wayland, exponential steps so two half-clicks == one full click.
        """
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            event.accept()
            return

        if event.hasPixelDelta():
            raw = event.pixelDelta().y()
            if raw == 0:
                event.accept()
                return
            steps = raw * 0.02
        else:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            steps = delta / 120.0

        if event.isInverted():
            steps = -steps

        step = self.zoom_step ** abs(steps)
        if steps > 0:
            new_zoom = self.zoom_factor * step
        else:
            new_zoom = self.zoom_factor / step
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if new_zoom != self.zoom_factor:
            factor = new_zoom / self.zoom_factor
            self.zoom_factor = new_zoom
            self.setTransformationAnchor(
                QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
            self.setTransformationAnchor(
                QGraphicsView.ViewportAnchor.AnchorViewCenter)

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
        self.centerOn(SCENE_SIZE / 2, SCENE_SIZE / 2)

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
        """Start panning on left press (single click never opens dialogs)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Restore the arrow cursor after panning."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-click a planet/sign icon to emit the click signals
        (classic chart_view.py:695-716). Single click stays pan; items are
        passive so detection happens here via items(event.pos())."""
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.items(event.position().toPoint()):
                if isinstance(item, ClickablePlanetItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.planet_name,
                                                     item.planet_info)
                    event.accept()
                    return
                elif isinstance(item, SignIconItem):
                    self._is_dragging = False
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(item.zodiac_index,
                                                     item.current_variation)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Settings / assets
    # ------------------------------------------------------------------

    def _load_display_settings(self) -> dict:
        """Load the south_indian_display block (font size/weight)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get_south_indian_display()
        except Exception as e:
            print(f"[SI VECTOR] Warning: could not load display settings: {e}")
            return {}

    @property
    def display_settings(self):
        """The vector view's configuration — ALWAYS the south_indian_display
        block loaded from the settings accessors, never an assigned dict."""
        return self._si_display_settings

    @display_settings.setter
    def display_settings(self, value):
        # STORING NO-OP (Phase-3 review finding 2): the host's conformant
        # display_settings property fans the CLASSIC chart_display dict to
        # both children (pro/ui/chart_display_tab.py assigns its edited
        # classic block to the preview host). The classic child consumes it
        # (its own config path — unchanged); the vector child must NOT be
        # configured by classic-only keys, so the assignment is ignored.
        # Vector config is re-read from get_south_indian_display() here.
        self._si_display_settings = self._load_display_settings()

    def _load_variation_settings(self) -> dict:
        """Load display.zodiac_variations (sign icon variation per sign)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get("display.zodiac_variations", {})
        except Exception as e:
            print(f"[SI VECTOR] Warning: could not load variations: {e}")
            return {}

    def load_sign_icon(self, sign_index: int, size: int = SIGN_ICON_SIZE):
        """Load the variation-aware sign icon (canonical classic loader,
        chart_view.py:1095-1154, mirrored). No HiDPI scaling — the view
        transform handles it (INV-4). Cached by (sign, variation, size).

        Tries img/sign/{WesternName}{variation}.webp, falls back to
        {WesternName}1.webp (always shipped). Returns None if unreadable.
        """
        western_name = self.WESTERN_NAMES[sign_index]
        variation = self.get_selected_variation(sign_index)
        cache_key = (sign_index, variation, size, get_ui_saturation())
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon_path = PROJECT_ROOT / f"img/sign/{western_name}{variation}.webp"
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/sign/{western_name}1.webp"
        if not icon_path.exists():
            print(f"[SI VECTOR] Warning: icon not found for {western_name}")
            self._icon_cache[cache_key] = None
            return None

        qimage = QImage(str(icon_path))
        if qimage.isNull():
            print(f"[SI VECTOR] Warning: failed to load image: {icon_path}")
            self._icon_cache[cache_key] = None
            return None

        qimage = qimage.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        qimage = desat_image(qimage)
        pixmap = QPixmap.fromImage(qimage)
        self._icon_cache[cache_key] = pixmap
        return pixmap

    # ------------------------------------------------------------------
    # Public protocol (Wave 2a subset — full INV-5 surface is Wave 2b)
    # ------------------------------------------------------------------

    def set_background(self, bg_id):
        """Store the background id; Phase 1 always renders flat (D-11)."""
        self._background_id = bg_id

    def get_background(self):
        return self._background_id

    def update_from_chart(self, chart, varga_code=None, use_western_names=False,
                          aditya_mode=None, **_kw):
        """Render from a libaditya Chart object (primary entry point)."""
        previous_chart = self._chart
        self._chart = chart
        self._varga_code = varga_code
        self._use_western_names = use_western_names
        self._has_chart = True

        if aditya_mode is not None:
            self._aditya_mode = aditya_mode
        else:
            # Classic behavior (chart_view.py:1468-1470): derive from context
            try:
                from libaditya.objects.context import Circle
                circle = getattr(getattr(chart, "context", None), "circle", None)
                self._aditya_mode = (
                    "aditya" if circle == Circle.ADITYA else "tropical_classic")
            except Exception:
                self._aditya_mode = "tropical_classic"

        # Campanus cusps + planets + native name, all defensive (the chart
        # shape may vary)
        self._cusps = None
        self._planets = None
        try:
            source = (chart.varga(varga_code)
                      if varga_code and varga_code != 1 else chart.rashi())
            self._cusps = source.cusps()
            self._planets = source.planets()
        except Exception:
            pass
        ctx = getattr(chart, "context", None)
        self._chart_name = (
            getattr(ctx, "name", None) or getattr(chart, "name", None) or "")

        # INV-11: a new natal chart can change the mini's zodiac mode and
        # labels, and (dasha-locked) the transit chart itself at the same jd.
        # Only when the chart OBJECT actually changed, though: this method
        # is also how the outer grid is re-rendered for a varga switch, a
        # view sync or an ascendant change, and invalidating there re-records
        # the mini on every one of them — the multiplier that turned a
        # per-click cost into an everywhere cost.
        if chart is not previous_chart:
            self._invalidate_transit_cache()

        # SPEC-COT-001 §4.10: drop the memoised faces on EVERY update, not only
        # when the object changed. The cache exists for the redraws that do NOT
        # come through here — theme switch, ascendant override, setting change —
        # and object identity alone would keep serving old faces if a caller
        # ever mutated a Chart in place instead of rebuilding it. Recomputing
        # costs ~0.3 ms; being unable to rule that out costs an argument every
        # time someone reads this method.
        self._cot_forget_faces()

        self.draw_full_chart()

    def set_ascendant_override(self, sign_index):
        """F4 Sign-as-Ascendant override: 0-11, or None for the real Asc."""
        self.ascendant_override = sign_index
        self.draw_full_chart()

    def clear_icon_cache(self):
        """Drop cached sign + planet pixmaps (e.g. on UI saturation change)."""
        if hasattr(self, "_icon_cache"):
            self._icon_cache.clear()
        if hasattr(self, "_planet_icon_cache"):
            self._planet_icon_cache.clear()

    def refresh_theme(self):
        """Re-read theme colors and redraw (SPEC-THM-001 live switch)."""
        self.setBackgroundBrush(
            QBrush(QColor(get_theme_colors()["secondary_dark"])))
        # INV-11: the mini chart is painted with the old palette.
        self._invalidate_transit_cache()
        self.draw_full_chart()

    def items_by_tag(self, tag: str):
        """Scene items carrying a si.vector.* UserRole tag (INV-9 tracking)."""
        return [item for item in self.scene.items()
                if item.data(Qt.ItemDataRole.UserRole) == tag]

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw_full_chart(self):
        """Rebuild the whole scene: frame → medallion → cards → badges →
        house numbers → cusps → planets → lagna stripe → hover zones.
        With no chart, draws the empty grid (no title, no house numbers,
        no cusps, no planets, no stripe)."""
        self.scene.clear()
        self._draw_chrome()
        if self._chart:
            self._draw_house_numbers()
            self._draw_cusps()
            self._draw_planets()
            self._draw_lagna_stripe()

    def _draw_chrome(self):
        """Chart-independent layers: frame → medallion → cards → badges →
        hover zones.

        With ``center_box_enabled=False`` this is the INERT mini view
        (SPEC-SIC-003 INV-6): no medallion (which is what would recurse into
        another transit render), no outer gold frame (it would sit inside
        the host medallion's gold ring as a double frame), and no hover
        zones (nothing to hover in an off-screen render)."""
        if self.center_box_enabled:
            self._draw_frame()
            self._draw_medallion()
        for sign in range(12):
            card = SignCardItem(sign, cell_rect(sign))
            self.scene.addItem(card)
        self._badge_band.clear()
        for sign in range(12):
            self._draw_sign_badge(sign)
        # After the badges: the index positions itself in the space they left,
        # and it needs a chart, so with none it draws nothing (draw_empty_grid
        # reaches this method too).
        if self._cot_enabled():
            self._draw_cot_indices()
        if self.center_box_enabled:
            for sign in range(12):
                self.scene.addItem(HoverZoneItem(cell_rect(sign), sign))

    def draw_empty_grid(self):
        """Draw the empty-state grid (classic chart_view.py:1051 semantics):
        chrome only — no house numbers, cusps, planets, or lagna
        stripe. Chart state (_chart) is NOT cleared, mirroring the classic
        method hosts call (e.g. managers/chart_manager.py:399 when the
        last chart is removed)."""
        self.scene.clear()
        self._draw_chrome()

    def _draw_frame(self):
        """4px gold rounded frame at sceneRect inset 2px (pen half-clip trap,
        spec §4.2)."""
        rect = self.scene.sceneRect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        item = QGraphicsPathItem(path)
        item.setBrush(Qt.BrushStyle.NoBrush)
        item.setPen(QPen(QColor(GOLD), 4))
        item.setZValue(0)
        item.setData(Qt.ItemDataRole.UserRole, TAG_FRAME)
        self.scene.addItem(item)

    def _draw_medallion(self):
        """Center medallion: theme secondary fill, 2px gold border, thin gold
        inner ring inset 18px. T-8 revision (spec v0.6, D-12 reversed): no
        chart title — the center block is reserved for other content
        (transit placeholder stub, Phase-2 center modes)."""
        rect = center_rect()
        colors = get_theme_colors()

        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        base = QGraphicsPathItem(path)
        base.setBrush(QBrush(QColor(colors["secondary"])))
        base.setPen(QPen(QColor(GOLD), 2))
        base.setZValue(0)
        base.setData(Qt.ItemDataRole.UserRole, TAG_MEDALLION)
        self.scene.addItem(base)

        ring_path = QPainterPath()
        ring_path.addRoundedRect(rect.adjusted(18, 18, -18, -18),
                                 CARD_RADIUS, CARD_RADIUS)
        ring = QGraphicsPathItem(ring_path)
        ring.setBrush(Qt.BrushStyle.NoBrush)
        ring.setPen(QPen(QColor(GOLD), 1))
        ring.setZValue(2)
        ring.setData(Qt.ItemDataRole.UserRole, TAG_MEDALLION_RING)
        self.scene.addItem(ring)

        # Center-box precedence (SPEC-VGC-001 §3.2), highest first:
        #   1 time adjust   -> empty medallion (its widget owns the area)
        #   2 transit       -> mini transit chart (always D-1 rashi)
        #   3 center varga  -> mini varga chart (SPEC-VGC-001)
        #   4 no chart      -> empty medallion, even with a mode enabled
        #   5 default       -> empty medallion
        # Drawn HERE, inside the rebuild, because draw_full_chart() clears
        # the scene on every call — a patched-in item would be lost on the
        # next varga switch, override change or theme refresh (INV-6).
        if self.time_adjust_mode or self._chart is None:
            return
        if self._transit_overlay_active:
            transit = getattr(self._transit_manager, "transit_chart", None)
            self._draw_center_mini(rect, transit, None)
        elif self._center_varga_code is not None:
            self._draw_center_mini(rect, self._chart, self._center_varga_code)

    @staticmethod
    def _fit_font(text: str, base_size, weight, max_width: float) -> QFont:
        """Shrink Inter from base_size toward the 10pt floor until the text
        fits max_width. Built with the same pipeline as the medallion
        headline (QFont + setPointSizeF + setWeight) so badge and center
        typography render identically (T-8 revision, spec v0.6)."""
        size = max(float(MIN_BADGE_FONT_SIZE), float(base_size))
        font = QFont("Inter")
        font.setPointSizeF(size)
        font.setWeight(weight)
        while size > MIN_BADGE_FONT_SIZE and \
                QFontMetricsF(font).horizontalAdvance(text) > max_width:
            size -= 1
            font.setPointSizeF(size)
        return font

    def _draw_sign_badge(self, sign_index: int):
        """Sign icon (96px, variation-aware) top-right + sign name in a pill
        anchored to the card's top-left corner (NI badge language,
        rect-adapted; same corner the classic image-backed view uses).

        T-8 revision (spec v0.6): the name sits on a rounded pill in the
        medallion's design language — theme secondary fill, 1px gold
        hairline, secondary_text color, medallion-pipeline Inter — instead
        of bare element-colored text on the card."""
        rect = cell_rect(sign_index)
        pad = CONTENT_PADDING
        colors = get_theme_colors()

        pixmap = self.load_sign_icon(sign_index, SIGN_ICON_SIZE)
        icon_w = pixmap.width() if pixmap else 0
        icon_h = pixmap.height() if pixmap else 0
        icon_x = rect.right() - pad - icon_w
        icon_y = rect.top() + pad

        if pixmap:
            icon_item = SignIconItem(
                pixmap, sign_index, self.get_selected_variation(sign_index),
                self.sign_click_signal)
            icon_item.setPos(icon_x, icon_y)
            icon_item.setZValue(4.5)
            icon_item.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_ICON)
            self.scene.addItem(icon_item)

        name = displayed_sign_name(sign_index, self._aditya_mode,
                                   self._use_western_names,
                                   self.sign_language)
        sign_settings = self.display_settings.get("sign_name", {})
        base_size = sign_settings.get("font_size", 24)
        weight = (QFont.Weight.Bold
                  if sign_settings.get("font_weight", "bold") == "bold"
                  else QFont.Weight.Normal)

        # Top band beside the icon — the pill anchors to the card's TOP-LEFT
        # corner and the icon keeps the top-right, matching the classic
        # image-backed view (chart_view.py:1224 anchors the sign label to the
        # inner box's top-left). The pill padding comes out of the text budget
        # so the pill never crowds the icon or the card edge.
        pill_left = rect.left() + pad
        band_right = (icon_x - 8) if pixmap else (rect.right() - pad)
        text_budget = (band_right - pill_left) - 2 * BADGE_PILL_PAD_X
        font = self._fit_font(name, base_size, weight, text_budget)
        fits_beside = \
            QFontMetricsF(font).horizontalAdvance(name) <= text_budget
        if not fits_beside:
            # Shrink floor reached: move the name below the icon, full width.
            text_budget = rect.width() - 2 * pad - 2 * BADGE_PILL_PAD_X
            font = self._fit_font(name, base_size, weight, text_budget)

        label = QGraphicsTextItem(name)
        label.setFont(font)
        label.setDefaultTextColor(QColor(colors["secondary_text"]))
        bounds = label.boundingRect()
        lx = pill_left + BADGE_PILL_PAD_X
        if fits_beside:
            # Vertically centred on the icon row so badge + icon read as one
            # band across the top of the card.
            ly = (icon_y + (icon_h - bounds.height()) / 2) if pixmap \
                else rect.top() + pad + BADGE_PILL_PAD_Y
        else:
            # Name too long to sit beside the icon: drop below it, still
            # left-anchored (never centred — the corner is the anchor).
            ly = icon_y + icon_h + 4 + BADGE_PILL_PAD_Y

        # Pill backdrop behind the text (below the icon row, above cards).
        pill_rect = QRectF(lx - BADGE_PILL_PAD_X, ly - BADGE_PILL_PAD_Y,
                           bounds.width() + 2 * BADGE_PILL_PAD_X,
                           bounds.height() + 2 * BADGE_PILL_PAD_Y)
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill_rect, pill_rect.height() / 2,
                                 pill_rect.height() / 2)
        pill = QGraphicsPathItem(pill_path)
        fill = QColor(colors["secondary"])
        fill.setAlphaF(0.88)
        pill.setBrush(QBrush(fill))
        border = QColor(GOLD)
        border.setAlphaF(0.55)
        pill.setPen(QPen(border, 1.5))
        pill.setZValue(4.4)
        pill.setData(Qt.ItemDataRole.UserRole, TAG_BADGE_PILL)
        self.scene.addItem(pill)

        label.setPos(lx, ly)
        label.setZValue(5)
        label.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_NAME)
        self.scene.addItem(label)

        # Hand the leftover top-band space to the Cards of Truth index
        # (§4.10). Recorded here rather than recomputed there because the gap
        # depends on the SHRUNK font this method solved for, and re-deriving it
        # would mean re-running _fit_font and quietly disagreeing whenever the
        # two solvers drift. When the name did not fit beside the icon it has
        # dropped below, so the whole band from the card edge is free.
        gap_left = (pill_rect.right() + 8) if fits_beside else (rect.left() + pad)
        gap_right = icon_x - 8 if pixmap else rect.right() - pad
        band_top = icon_y if pixmap else rect.top() + pad
        band_h = icon_h if pixmap else SIGN_ICON_SIZE
        self._badge_band[sign_index] = (gap_left, gap_right, band_top, band_h)

    # ------------------------------------------------------------------
    # Cards of Truth in-sign index (SPEC-COT-001 §4.10)
    # ------------------------------------------------------------------

    _cot_log_prefix = "[SI VECTOR]"

    def _cot_supported(self):
        """Never in the inert mini view.

        At the size the center box renders, the rank glyph would be about two
        screen pixels tall — present in the scene, unreadable on screen, and
        competing with the mini's own labels for the same band.
        """
        return bool(self.center_box_enabled)

    def _cot_repaint(self):
        self.draw_full_chart()

    def _draw_cot_indices(self):
        """One rank+suit plaque per sign, in the gap the sign badge left free.

        Lordship, not occupancy: Aries shows Mars's card, Leo the Sun's, and
        Capricorn and Aquarius both show Saturn's — twelve signs onto seven
        planetary positions, so five cards legitimately appear twice.

        The plaque exists because the element cards are strongly coloured in
        both themes: a bare red pip on the red Dhata card would vanish. It uses
        the sign-name pill's recipe (theme secondary fill, gold hairline) so it
        reads as a peer of the name, and the suit ink is then contrasted against
        the pill rather than against whichever element the sign happens to be.
        """
        faces = self._cot_faces()
        if not faces:
            return

        dpr = self.devicePixelRatioF() or 1.0
        for sign_index, card in faces.items():
            band = self._badge_band.get(sign_index)
            if band is None:
                continue
            gap_left, gap_right, band_top, band_h = band
            if gap_right - gap_left < COT_INDEX_MIN_GAP:
                # Not a silent skip in spirit: a name long enough to eat this
                # band has already been dropped below the icon by the badge,
                # which frees the whole width. Reaching here means the card is
                # genuinely too narrow to hold both, and half a plaque overlapping
                # the glyph would be worse than none.
                continue

            # scale=1: this scene renders at exactly the size the plaque
            # metrics were tuned for (SPEC-COT-001 §4.10).
            plaque = CotPlaque(card, dpr=dpr)
            if plaque.width > (gap_right - gap_left):
                continue
            plaque.add_to(self.scene,
                          (gap_left + gap_right) / 2.0,
                          band_top + band_h / 2.0,
                          tag=TAG_COT_CARD)

    def _effective_ascendant_sign_index(self):
        """Effective Ascendant sign index: F4 override, else cusp 1
        (classic chart_view.py:2427-2433)."""
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

    def _draw_house_numbers(self):
        """'H {n}' bottom-left of each card. T-8 revision (spec v0.6, D-6
        superseded): element text color (INV-7) instead of gold — readable
        on all four element gradients, including Air."""
        asc = self._effective_ascendant_sign_index()
        font = QFont("Inter", HOUSE_NUMBER_FONT_SIZE)
        fm = QFontMetricsF(font)
        pad = CONTENT_PADDING
        for sign in range(12):
            house = house_number_for_sign(sign, asc)
            color = QColor(element_text_color(get_element_for_sign(sign)))
            color.setAlphaF(0.85)
            item = QGraphicsTextItem(f"H {house}")
            item.setFont(font)
            item.setDefaultTextColor(color)
            rect = cell_rect(sign)
            item.setPos(rect.left() + pad,
                        rect.bottom() - pad - fm.height())
            item.setZValue(5)
            item.setData(Qt.ItemDataRole.UserRole, TAG_HOUSE_NUMBER)
            self.scene.addItem(item)

    def _draw_cusps(self):
        """'C{n} {deg}°' bottom-right, same quiet element-colored style as
        the house numbers (T-8 revision, spec v0.6) — only for Campanus
        cusps the chart provides; skipped silently when unavailable."""
        if not self._cusps:
            return
        try:
            per_sign = {}
            for i in range(1, 13):
                cusp = self._cusps[i]
                sign = cusp.sign() - 1
                risl = (cusp.amsha_raw_in_sign_longitude()
                        if self._varga_code
                        else cusp.real_in_sign_longitude())
                per_sign.setdefault(sign, []).append(f"C{i} {int(risl)}°")
        except Exception:
            return

        font = QFont("Inter", HOUSE_NUMBER_FONT_SIZE)
        fm = QFontMetricsF(font)
        pad = CONTENT_PADDING
        for sign, labels in per_sign.items():
            color = QColor(element_text_color(get_element_for_sign(sign)))
            color.setAlphaF(0.7)
            text = " ".join(labels)
            item = QGraphicsTextItem(text)
            item.setFont(font)
            item.setDefaultTextColor(color)
            rect = cell_rect(sign)
            item.setPos(rect.right() - pad - fm.horizontalAdvance(text),
                        rect.bottom() - pad - fm.height())
            item.setZValue(5)
            item.setData(Qt.ItemDataRole.UserRole, TAG_CUSP)
            self.scene.addItem(item)


    # ------------------------------------------------------------------
    # Planets (Wave 2b, spec §4.3 + INV-6)
    # ------------------------------------------------------------------

    def _load_planet_variation_settings(self) -> dict:
        """Load display.planet_variations (planet icon variation per planet)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get("display.planet_variations", {})
        except Exception as e:
            print(f"[SI VECTOR] Warning: could not load planet variations: {e}")
            return {}

    def load_planet_image(self, planet_name, size=48):
        """Load the variation-aware planet icon (canonical classic loader,
        chart_view.py:1395-1459, mirrored; case-fix via PLANET_ICON_NAMES).
        No HiDPI scaling — the view transform handles it (INV-4). Cached by
        (planet, variation, size). Returns None if unreadable.
        """
        variation = self.get_planet_variation(planet_name)
        cache_key = (planet_name, variation, size, get_ui_saturation())
        if cache_key in self._planet_icon_cache:
            return self._planet_icon_cache[cache_key]

        icon_filename = self.PLANET_ICON_NAMES.get(planet_name,
                                                   planet_name.lower())
        if variation > 1:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}{variation}.webp"
        else:
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f"img/planets/{icon_filename}.webp"
        if not icon_path.exists():
            print(f"[SI VECTOR] Warning: planet icon not found: {icon_path}")
            self._planet_icon_cache[cache_key] = None
            return None

        try:
            qimage = QImage(str(icon_path))
            if qimage.isNull():
                print(f"[SI VECTOR] Warning: failed to load image: {icon_path}")
                self._planet_icon_cache[cache_key] = None
                return None
            qimage = qimage.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            qimage = desat_image(qimage)
            pixmap = QPixmap.fromImage(qimage)
            self._planet_icon_cache[cache_key] = pixmap
            return pixmap
        except Exception as e:
            print(f"[SI VECTOR] Error loading planet image {planet_name}: {e}")
            self._planet_icon_cache[cache_key] = None
            return None

    def _planet_deg_min(self, planet):
        """(degrees, minutes) within sign, varga-aware (classic :2790-2792)."""
        risl = (planet.amsha_raw_in_sign_longitude() if self._varga_code
                else planet.real_in_sign_longitude())
        return int(risl), int((risl % 1) * 60)

    def _planet_to_click_dict(self, planet_name, planet):
        """Classic click payload shape (chart_view.py:2794-2805)."""
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
        """Group planets by sign and draw each card's row."""
        if not self._planets:
            return

        planets_by_sign = {}
        for planet_name in self.PLANET_NAMES:
            if not self.show_outer_planets and planet_name in OUTER_PLANETS:
                continue
            try:
                planet = self._planets[planet_name]
            except (KeyError, TypeError):
                continue
            try:
                sign_idx = planet.sign() - 1
            except Exception:
                continue
            planets_by_sign.setdefault(sign_idx, []).append(
                (planet_name, planet))

        planet_sizes = self.display_settings.get("planet_sizes", {})
        for sign_idx, planets_in_sign in planets_by_sign.items():
            self._draw_planets_in_sign(sign_idx, planets_in_sign, planet_sizes)

    def _draw_planets_in_sign(self, sign_idx, planets_in_sign, planet_sizes):
        """Degree-ordered, evenly spaced planet row at 60% card height
        (SPEC-SIC-001 / INV-6; classic :2864-2884 geometry adapted to the
        488px card with uniform CONTENT_PADDING)."""
        rect = cell_rect(sign_idx)
        pad = CONTENT_PADDING
        varga = self._varga_code

        # SPEC-SIC-001: left = 0°, right = 30°
        planets_in_sign = sorted(
            planets_in_sign,
            key=lambda item: (item[1].amsha_raw_in_sign_longitude() if varga
                              else item[1].real_in_sign_longitude()))

        num_planets = len(planets_in_sign)
        y_pos = rect.top() + CARD_SIZE * PLANET_ROW_HEIGHT_FRACTION
        available_width = CARD_SIZE - 2 * pad
        spacing = available_width / num_planets

        text_color = QColor(element_text_color(get_element_for_sign(sign_idx)))
        text_color.setAlphaF(0.85)
        deg_settings = self.display_settings.get("planet_degrees", {})
        deg_weight = (QFont.Weight.Bold
                      if deg_settings.get("font_weight", "normal") == "bold"
                      else QFont.Weight.Normal)
        text_font = QFont("Inter", deg_settings.get("font_size", 14),
                          deg_weight)
        fm = QFontMetricsF(text_font)

        # Rule #18 / INV-9: create_planet_shadow() is a FACTORY — one effect
        # instance per icon, and del the Python reference after install.
        from apps.widgets.planet_shadow import create_planet_shadow

        for i, (planet_name, planet) in enumerate(planets_in_sign):
            if num_planets == 1:
                risl = (planet.amsha_raw_in_sign_longitude() if varga
                        else planet.real_in_sign_longitude())
                third = available_width / 3
                x_pos = (rect.left() + pad
                         + lone_planet_zone(risl) * third + third / 2)
            else:
                x_pos = rect.left() + pad + i * spacing + spacing / 2

            base_size = planet_sizes.get(
                planet_name, self.PLANET_SIZES.get(planet_name, 128))
            planet_size = crowded_planet_size(base_size, num_planets)

            icon_bottom = y_pos
            pixmap = self.load_planet_image(planet_name, size=planet_size)
            if pixmap:
                planet_item = ClickablePlanetItem(
                    pixmap, planet_name,
                    self._planet_to_click_dict(planet_name, planet),
                    self.planet_click_signal)
                planet_item.setOffset(-pixmap.width() / 2,
                                      -pixmap.height() / 2)
                planet_item.setPos(x_pos, y_pos)
                shadow = create_planet_shadow(planet_name=planet_name)
                if shadow:
                    planet_item.setGraphicsEffect(shadow)
                    del shadow  # Rule #18 — Qt owns the effect now
                self.scene.addItem(planet_item)
                icon_bottom = y_pos + pixmap.height() / 2

            # 2-letter abbreviation + degrees (F11 swaps the degrees line to
            # the localized planet name — classic :2912-2929)
            abbrev = planet_name[:2]
            if self.show_planet_names:
                degrees_text = get_planet_display_name(self.sign_language,
                                                       planet_name)
            else:
                deg, mins = self._planet_deg_min(planet)
                degrees_text = f"{deg}°{mins:02d}'"
            abbrev_y = icon_bottom + 4
            degrees_y = abbrev_y + fm.height() + 2
            for text, ty in ((abbrev, abbrev_y), (degrees_text, degrees_y)):
                label = QGraphicsTextItem(text)
                label.setFont(text_font)
                label.setDefaultTextColor(text_color)
                label.setPos(x_pos - label.boundingRect().width() / 2, ty)
                label.setZValue(80)
                label.setData(Qt.ItemDataRole.UserRole, TAG_PLANET_TEXT)
                self.scene.addItem(label)

    # ------------------------------------------------------------------
    # Lagna stripe (Wave 2b, spec §4.3)
    # ------------------------------------------------------------------

    def _draw_lagna_stripe(self):
        """Two parallel diagonal strikes calibrated to the ascendant card's
        top-right corner, BEHIND the badge icon, + a quiet 'ASC d°mm'' label
        (SPEC-NIC-001 §3.2 format, §3.3 varga-aware degree). Hidden under
        the F4 override.

        Calibration (T-8 rev 2, spec v0.7) — perfect square math, no fudge
        offsets: each strike is a 45° line whose ROUND CAPS kiss the top and
        right card edges exactly (endpoints inset by precisely pen.width()/2
        perpendicular to the edge they touch, so nothing spills into the
        gutter). Inner strike reach = CARD_SIZE/3 — an exact fraction of the
        card, like tick marks on a well-made dial. The air between the two
        strikes is exactly one stroke width (perpendicular), so the outer
        strike's reach shrinks by 2*w*sqrt(2) along the edges.

        Overlap choice (documented): the strikes sit BEHIND the badge icon
        (z=2 < pills 4.4 < icons 4.5 < labels 5), element-colored
        lighter(150) at 45% so they read on their own card — glyph corners
        are transparent enough for the marks to show around the icon, and
        the inner strike's reach (CARD_SIZE/3 ≈ 163px) extends ~40px past
        the icon column so the mark is always visible. The ASC label sits
        directly below the badge icon, right-aligned with it, in the same
        quiet style as the house numbers (Lorris, T-8 rev 2: the strikes
        alone advertise the ascendant).

        Under an F4 / sign-column override the strikes MOVE to the overridden
        card — they are the only on-chart signal that an override is active
        (SPEC-SIC-003 INV-2, classic parity at chart_view.py:2306). Only the
        degree label is suppressed, because an invented Ascendant has no real
        degree (classic parity at chart_view.py:2378)."""
        if not self._chart:
            return

        sign_index = self._effective_ascendant_sign_index()
        rect = cell_rect(sign_index)

        # Element-colored over the element card: the raw base color would be
        # invisible on its own fill, lighter(150) keeps the strike
        # element-hued but readable (documented deviation from classic,
        # which paints over a NEUTRAL marble cell).
        stripe_color = QColor(
            desat_hex(ELEMENT_COLORS[get_element_for_sign(sign_index)])).lighter(150)  # SPEC-SAT-001
        stripe_color.setAlphaF(0.45)
        pen = QPen(stripe_color)
        pen.setWidth(max(6, int(CARD_SIZE * 0.035)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        w = pen.width()
        half = w / 2
        top = rect.top()
        right = rect.right()
        reach = CARD_SIZE / 3                 # exact card fraction
        gap = 2 * w * math.sqrt(2)            # one stroke width of air

        for r in (reach, reach - gap):
            line = QGraphicsLineItem(
                right - r, top + half,        # cap kisses the top edge
                right - half, top + r)        # cap kisses the right edge
            line.setPen(pen)
            line.setZValue(2)
            line.setData(Qt.ItemDataRole.UserRole, TAG_LAGNA)
            self.scene.addItem(line)

        # ASC label: quiet house-number style (element text color, regular
        # Inter) — deliberately less apparent; the strikes carry the mark.
        # Suppressed under an override (INV-2): there is no real Ascendant
        # degree for a sign the user nominated.
        if self.ascendant_override is not None:
            return

        deg, mins = 0, 0
        try:
            asc_cusp = self._cusps[1] if self._cusps else None
            if asc_cusp:
                risl = (asc_cusp.amsha_raw_in_sign_longitude()
                        if self._varga_code
                        else asc_cusp.real_in_sign_longitude())
                deg, mins = int(risl), int((risl % 1) * 60)
        except Exception:
            pass
        label = QGraphicsTextItem(f"ASC {deg}°{mins:02d}'")
        label.setFont(QFont("Inter", HOUSE_NUMBER_FONT_SIZE))
        color = QColor(element_text_color(get_element_for_sign(sign_index)))
        color.setAlphaF(0.9)
        label.setDefaultTextColor(color)
        label.setPos(rect.right() - CONTENT_PADDING
                     - label.boundingRect().width(),
                     rect.top() + CONTENT_PADDING + SIGN_ICON_SIZE + 6)
        label.setZValue(5)
        label.setData(Qt.ItemDataRole.UserRole, TAG_LAGNA_LABEL)
        self.scene.addItem(label)

    # ------------------------------------------------------------------
    # Transit placeholder + export + remaining INV-5 protocol (Wave 2b)
    # ------------------------------------------------------------------

    def _transit_target_rect(self, medallion_rect):
        """Where the mini transit chart sits: inside the medallion's gold
        inner ring (inset 18px) plus a small margin, so the ring frames it."""
        inset = TRANSIT_MEDALLION_INSET
        return medallion_rect.adjusted(inset, inset, -inset, -inset)

    def _transit_source_renderable(self):
        """INV-4: active only when the source says enabled AND carries a
        chart. `manager is not None` is NOT the test — the comparison panel
        passes a deliberately DISABLED source to clear the overlay
        (pro/panels/dual_chart_comparison.py), and the manager can sit
        enabled with no usable chart after a calculation failure."""
        source = self._transit_manager
        return bool(source is not None
                    and getattr(source, "transit_enabled", False)
                    and getattr(source, "transit_chart", None) is not None)

    def _center_render_signature(self, chart, varga_code):
        """What the cached recording depends on that has NO event to hook.

        F8 (outer planets), F11 (planet names) and the sign language reach
        this view as PLAIN ATTRIBUTE WRITES from the host, so nothing fires
        when they change and the center box would keep showing the old
        planet set or language. The chart identity and varga code are in
        here too: a dasha-locked chart switch rebuilds at the SAME jd with a
        different ayanamsa, and D-9 -> D-10 changes neither jd nor mode nor
        labels (SPEC-VGC-001 INV-8)."""
        return (id(chart), varga_code, self.sign_language,
                bool(self.show_outer_planets), bool(self.show_planet_names))

    def _invalidate_transit_cache(self):
        """Event-based invalidation for everything that CAN change invisibly.

        Kept as an explicit event rather than trusting the signature alone:
        the signature uses `id(chart)`, and CPython reuses ids of collected
        objects, so a rebuilt chart could land on the same id."""
        self._center_cache.invalidate()

    def _release_transit_mini(self):
        """Drop the off-screen mini view and its recording. Called when the
        overlay is torn down, so the mini exists only while center content is
        actually being displayed rather than for the lifetime of the host."""
        self._center_cache.invalidate()
        mini = self._mini_transit_view
        self._mini_transit_view = None
        if mini is not None:
            mini.deleteLater()

    def _draw_center_mini(self, medallion_rect, chart, varga_code):
        """Render (or reuse) a mini chart and place it in the medallion.

        Source-agnostic by design (SPEC-VGC-001 INV-1): the transit overlay
        passes the transit chart with `varga_code=None` because transit is
        always D-1 rashi (SPEC-TRN-001 §4.2); the varga mode passes the
        natal chart with the selected code. Precedence between them is the
        caller's, in `_draw_medallion`."""
        target = self._transit_target_rect(medallion_rect)
        size = int(min(target.width(), target.height()))
        if size <= 0 or chart is None:
            return

        signature = self._center_render_signature(chart, varga_code)
        picture = self._center_cache.get(signature)
        if picture is None:
            picture = self._center_cache.put(
                self._record_center_mini(size, chart, varga_code), signature)
        if picture is None:
            return

        item = CenterMiniItem(picture, size,
                              veil=(TRANSIT_MINI_TREATMENT == "veil"),
                              label=varga_label(varga_code),
                              label_color=QColor(GOLD))
        # setPos ONLY — the picture is recorded at the target size, so a
        # setScale on top of it is a silent 2x geometry bug (pre-mortem F-2).
        item.setPos(target.center().x() - size / 2,
                    target.center().y() - size / 2)
        item.setZValue(52)
        item.setData(Qt.ItemDataRole.UserRole, TAG_TRANSIT)
        self.scene.addItem(item)
        del item  # Rule 18: Qt owns it now.

    def _record_center_mini(self, size, chart, varga_code):
        """Feed the shared off-screen mini and record it at `size`.

        ONE mini per chart type per view (SPEC-VGC-001 INV-7): transit and
        varga are both South Indian charts, so they reuse this instance
        rather than allocating a second one per source."""
        if self._mini_transit_view is None:
            # Constructed DIRECTLY: create_south_indian_view() returns the
            # CLASSIC view for center_box_enabled=False. Held as a plain
            # attribute rather than a Qt child so it is never laid out or
            # shown; it is released with this view.
            self._mini_transit_view = SouthIndianVectorView(
                center_box_enabled=False)
            self._mini_transit_view.setAttribute(
                Qt.WidgetAttribute.WA_DontShowOnScreen)

        mini = self._mini_transit_view
        mini.sign_language = self.sign_language
        mini.show_outer_planets = self.show_outer_planets
        mini.show_planet_names = self.show_planet_names
        # §4.4: the inner chart must never contradict the outer one, icons
        # included — the mini loads its own settings at construction and
        # would otherwise keep them for its whole life.
        mini._variation_settings = dict(self._variation_settings)
        mini._planet_variation_settings = dict(self._planet_variation_settings)
        # Do NOT clear the mini's icon caches here. They key on
        # (sign, variation, size) and (planet, variation, size), so a
        # variation change misses naturally; clearing forced 12 webp decodes
        # and smooth rescales on EVERY recording — measured 1760 ms per varga
        # change against 76 ms without it.
        try:
            mini.update_from_chart(
                chart, varga_code=varga_code,
                use_western_names=self._use_western_names,
                aditya_mode=self._aditya_mode)
        except Exception as e:  # a chart can be half-built
            print(f"[SI VECTOR] Center mini render skipped: {e}")
            return None

        return record_center_picture(mini, size)

    def clear_chart(self):
        """Clear the chart display to the empty grid (classic :1490-1502)."""
        self._chart = None
        self._varga_code = None
        self._planets = None
        self._cusps = None
        self._chart_name = ""
        self._has_chart = False
        # The memoised spread holds the Chart strongly. Dropping `_chart` alone
        # would leave the whole object graph alive until the NEXT chart loads —
        # which, for a view kept around between charts, is exactly the window a
        # "clear" is supposed to close. Predates the wheel/NI extension; fixed
        # here at the same time so all three behave alike.
        self._cot_forget_faces()
        self.draw_full_chart()

    def ensure_visible(self):
        """Force viewport refresh and re-apply zoom (classic :1477-1488)."""
        self.scene.update()
        self.viewport().update()
        self.resetTransform()
        self.scale(self.zoom_factor, self.zoom_factor)
        self.centerOn(SCENE_SIZE / 2, SCENE_SIZE / 2)

    def render_to_image(self, source_rect=None) -> QImage:
        """Detached scene snapshot (§4.6 / T-6): a fresh ARGB32 QImage at
        sceneRect size, pre-filled with the theme background. Adds nothing
        to the scene and is independent of the view transform — safe to
        call any time."""
        source = (source_rect if source_rect is not None
                  else self.scene.sceneRect())
        image = QImage(SCENE_SIZE, SCENE_SIZE, QImage.Format.Format_ARGB32)
        image.fill(QColor(get_theme_colors()["secondary_dark"]))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.scene.render(painter, QRectF(0, 0, SCENE_SIZE, SCENE_SIZE),
                          source)
        painter.end()
        return image

    def update_transit_overlay(self, manager):
        """Receive transit state from any source satisfying INV-4 and redraw.

        Accepts the real TransitOverlayManager and the comparison panel's
        adapter alike: only `transit_enabled` and `transit_chart` are read,
        never `transit_jd` (the adapter has none)."""
        self._transit_manager = manager
        self._transit_overlay_active = self._transit_source_renderable()
        if self._transit_overlay_active:
            self._invalidate_transit_cache()
        else:
            self._release_transit_mini()
        self.draw_full_chart()

    def set_center_varga(self, varga_code):
        """Draw `varga_code` in the medallion while the outer grid stays D-1.

        SPEC-VGC-001. `None` clears it. Validated rather than coerced: the
        Z6b setter shipped with a `% 12` that silently mapped 0 to Parjanya
        and 13 to Dhata, and a bad varga code here would silently draw the
        WRONG divisional chart — which reads as a real reading.
        """
        valid = (varga_code is None
                 or (isinstance(varga_code, int)
                     and not isinstance(varga_code, bool)
                     and varga_code != 0))
        if not valid:
            print("[SI VECTOR] Ignoring invalid center varga: "
                  f"{varga_code!r} (expected a libaditya varga code or None)")
            return
        if varga_code == self._center_varga_code:
            return
        self._center_varga_code = varga_code
        self._center_cache.invalidate()
        # The off-screen mini is an unparented QGraphicsView holding a full
        # scene and its icon caches, per host across nine host sites. Keep
        # it only while the center box is actually showing something.
        if varga_code is None and not self._transit_overlay_active:
            self._release_transit_mini()
        # INV-6: the scene is cleared on every draw, so a setter that changes
        # center content must redraw — there is no other path to the screen.
        self.draw_full_chart()

    def set_z6b_selection(self, sign_index_1based):
        """Sign-column selection = an Ascendant override (SPEC-SIC-003 D-1).

        The vector theme does NOT draw a mini North Indian chart: selecting
        sign n re-anchors the whole chart to that sign, so the strikes move
        and the Whole Sign house numbers follow. The classic theme keeps its
        mini chart and receives this call too (host fans to both children).

        Args:
            sign_index_1based: 1..12, or None to clear.

        The domain is checked rather than wrapped: `(n - 1) % 12` would map
        0 to Parjanya, 13 to Dhata and -1 to Pusha, turning an invalid
        selection into a plausible-looking chart. Out-of-domain input warns
        and changes nothing. `bool` is rejected explicitly (it is an `int`
        subclass, so True would silently mean sign 1), and floats/strings
        are rejected rather than truncated. State is written only after the
        input is known good, so a rejected call cannot leave
        `_z6b_selection` disagreeing with `ascendant_override` (INV-1)."""
        if sign_index_1based is None:
            self._z6b_selection = None
            self.set_ascendant_override(None)
            return

        valid = (isinstance(sign_index_1based, int)
                 and not isinstance(sign_index_1based, bool)
                 and 1 <= sign_index_1based <= 12)
        if not valid:
            print("[SI VECTOR] Ignoring invalid Z6b selection: "
                  f"{sign_index_1based!r} (expected 1-12 or None)")
            return

        self._z6b_selection = sign_index_1based
        self.set_ascendant_override(sign_index_1based - 1)

    def set_time_adjust_mode(self, enabled):
        """Time adjust owns the center area (precedence 1, §3.2): the
        overlay leaves the SCENE, not just the screen, so nothing shows
        around the time-adjust widget and nothing is redrawn underneath it.

        The redraw is mandatory, not cosmetic: under INV-5 the scene is the
        only path to the screen, so a setter that changes center state and
        does not redraw changes nothing at all."""
        self.time_adjust_mode = bool(enabled)
        self.draw_full_chart()

    # ------------------------------------------------------------------
    # Variation API (INV-5; classic semantics, settings-manager backing
    # store per spec §4.7: display.zodiac_variations /
    # display.planet_variations — NOT the classic settings.json files)
    # ------------------------------------------------------------------

    def get_selected_variation(self, zodiac_index):
        """Selected sign icon variation number (1 if unset)."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        return self._variation_settings.get(western_name, 1)

    def set_selected_variation(self, zodiac_index, variation_num):
        """Persist + apply a sign icon variation, then redraw (classic
        chart_view.py:951-973 semantics)."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        self._variation_settings[western_name] = variation_num
        # The center mini draws the same icons; a dict is not hashable, so
        # the event is the invalidation rather than the signature.
        self._center_cache.invalidate()
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            stored = dict(settings.get("display.zodiac_variations", {}))
            stored[western_name] = variation_num
            settings.set("display.zodiac_variations", stored)
        except Exception as e:
            print(f"[SI VECTOR] Error saving variation settings: {e}")
        # Cache keys include the variation, so stale entries are never
        # reused; redraw picks the new icon up from disk.
        self.draw_full_chart()
        # Flush pending deleteLater()s from scene.clear() (classic :970-973)
        QApplication.processEvents()

    def get_planet_variation(self, planet_name):
        """Selected planet icon variation number (1 if unset)."""
        return self._planet_variation_settings.get(planet_name, 1)

    def set_planet_variation(self, planet_name, variation_num):
        """Persist + apply a planet icon variation, then redraw (classic
        chart_view.py:1032-1049 semantics)."""
        self._planet_variation_settings[planet_name] = variation_num
        self._center_cache.invalidate()
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            stored = dict(settings.get("display.planet_variations", {}))
            stored[planet_name] = variation_num
            settings.set("display.planet_variations", stored)
        except Exception as e:
            print(f"[SI VECTOR] Error saving planet variation settings: {e}")
        self.draw_full_chart()
        QApplication.processEvents()


# ---------------------------------------------------------------------------
# Wave 3a (bead td-lizg.5): SouthIndianHostWidget + create_south_indian_view
# ---------------------------------------------------------------------------

# Live-host registry (Phase-3 review finding 1): a style-only settings change
# must reach EVERY live host, including hosts owned by Pro panels the main
# window has no references to. WeakSet so closed panels drop out naturally;
# RuntimeError guards catch wrappers whose C++ object is already gone.
_LIVE_HOSTS = weakref.WeakSet()


def sync_all_south_indian_hosts():
    """Call sync_style() on every live SouthIndianHostWidget (D-13).

    The single activation entry point: the settings-apply handler calls
    this instead of syncing one host it happens to know about."""
    for host in list(_LIVE_HOSTS):
        try:
            host.sync_style()
        except RuntimeError:
            # C++ object deleted while the Python wrapper lingered.
            _LIVE_HOSTS.discard(host)


class SouthIndianHostWidget(QWidget):
    """One host widget owning BOTH South Indian themes (spec §4.1, D-7).

    A QStackedLayout holds one classic image-backed ``SouthIndianView`` and
    one ``SouthIndianVectorView``, both built at construction; the current
    index follows ``display.south_indian_style`` (INV-11 — the proven F2
    stack mechanism; never teardown-and-reinstantiate).

    Forwarding contract (INV-12):
    - Method calls fan to BOTH children (explicit defs, NO catch-all
      ``__getattr__``/``__setattr__``).
    - Writable attributes are explicit properties writing BOTH children.
    - Read-throughs resolve to the ACTIVE child.
    - Inherited-Qt surface: setDragMode fans to both (per-view state),
      viewport()/setFocus() go to the active child.
    - The host owns the click signal emitters and re-emits both children.

    Style activation (D-13): construction reads the setting once; runtime
    changes are applied by the settings-apply handler calling sync_style()
    on every live host — no subscription machinery.
    """

    # Class constants re-exported (core_gui_qt.py:2703 reads them off the
    # instance; body_graph_view reads them off the class).
    WESTERN_NAMES = SouthIndianView.WESTERN_NAMES
    ADITYA_NAMES = SouthIndianView.ADITYA_NAMES
    PLANET_NAMES = SouthIndianView.PLANET_NAMES
    PLANET_ICON_NAMES = SouthIndianView.PLANET_ICON_NAMES
    PLANET_SIZES = SouthIndianView.PLANET_SIZES

    _STYLE_INDEX = {"classic": 0, "vector": 1}

    def __init__(self, parent=None, center_box_enabled=True, style=None):
        super().__init__(parent)
        self.center_box_enabled = center_box_enabled

        self._stack = QStackedLayout(self)
        self.classic_view = SouthIndianView(
            center_box_enabled=center_box_enabled)
        self.vector_view = SouthIndianVectorView(
            center_box_enabled=center_box_enabled)
        self._stack.addWidget(self.classic_view)   # index 0
        self._stack.addWidget(self.vector_view)    # index 1

        # Host-owned signal emitters (same QObject-holder pattern as the
        # views); hosts connect ONLY to these (core_gui_qt.py:493/495).
        self.planet_click_signal = PlanetClickSignal()
        self.sign_click_signal = SignClickSignal()
        for child in (self.classic_view, self.vector_view):
            child.planet_click_signal.clicked.connect(
                self.planet_click_signal.clicked.emit)
            child.sign_click_signal.clicked.connect(
                self.sign_click_signal.clicked.emit)

        # Construction reads the style setting once (D-13) — unless an
        # explicit construction-time override was passed (factory style=
        # param, e.g. the CLI renderer): activate it WITHOUT persisting
        # (Phase-3 review finding 3); a later sync_style() re-reads the
        # setting as usual. Unknown styles fall back to classic.
        if style is not None:
            if style not in SOUTH_INDIAN_STYLES:
                style = DEFAULT_SOUTH_INDIAN_STYLE
            self._stack.setCurrentIndex(self._STYLE_INDEX[style])
        else:
            self.sync_style()

        _LIVE_HOSTS.add(self)

    # ------------------------------------------------------------------
    # Style activation (D-13)
    # ------------------------------------------------------------------

    @property
    def active_view(self):
        """The currently visible child (classic or vector)."""
        return self._stack.currentWidget()

    def set_style(self, style):
        """Set the SI theme, persist it, and move the stack index.
        Unknown styles fall back to "classic" (codex review finding #5)."""
        if style not in SOUTH_INDIAN_STYLES:
            style = DEFAULT_SOUTH_INDIAN_STYLE
        try:
            from managers.settings_manager import get_settings
            get_settings().set("display.south_indian_style", style)
        except Exception as e:
            print(f"[SI HOST] Warning: could not persist style: {e}")
        self._stack.setCurrentIndex(self._STYLE_INDEX[style])

    def sync_style(self):
        """Read display.south_indian_style and move the stack index.
        Called by the settings-apply handler on every live host (D-13)."""
        try:
            from managers.settings_manager import get_settings
            style = get_settings().get("display.south_indian_style",
                                       DEFAULT_SOUTH_INDIAN_STYLE)
        except Exception:
            style = DEFAULT_SOUTH_INDIAN_STYLE
        if style not in SOUTH_INDIAN_STYLES:
            style = DEFAULT_SOUTH_INDIAN_STYLE
        self._stack.setCurrentIndex(self._STYLE_INDEX[style])

    # ------------------------------------------------------------------
    # Fan-out method calls — BOTH children (INV-12)
    # ------------------------------------------------------------------

    def _fan(self, name, *args, **kwargs):
        for child in (self.classic_view, self.vector_view):
            getattr(child, name)(*args, **kwargs)

    def update_from_chart(self, chart, varga_code=None, use_western_names=False,
                          aditya_mode=None, **kw):
        for child in (self.classic_view, self.vector_view):
            child.update_from_chart(
                chart, varga_code=varga_code,
                use_western_names=use_western_names,
                aditya_mode=aditya_mode, **kw)

    def draw_full_chart(self):
        self._fan("draw_full_chart")

    def draw_empty_grid(self):
        """Classic-only grid draw on classic; chrome-only redraw on vector
        (chart_manager.py:399 calls this when the last chart is removed)."""
        self._fan("draw_empty_grid")

    def clear_chart(self):
        self._fan("clear_chart")

    def ensure_visible(self):
        self._fan("ensure_visible")

    def refresh_theme(self):
        self._fan("refresh_theme")

    def set_background(self, bg_id):
        self._fan("set_background", bg_id)

    def set_ascendant_override(self, sign_index):
        self._fan("set_ascendant_override", sign_index)

    def set_time_adjust_mode(self, enabled):
        self._fan("set_time_adjust_mode", enabled)

    def set_z6b_selection(self, sign_index_1based):
        """Narrowed alongside the child API (SPEC-SIC-003 §4.2): the old
        variadic passthrough let a malformed call reach both children and
        fail differently in each."""
        self._fan("set_z6b_selection", sign_index_1based)

    def update_transit_overlay(self, manager):
        self._fan("update_transit_overlay", manager)

    def set_center_varga(self, varga_code):
        """SPEC-VGC-001. Fanned to BOTH children (SPEC-SIC-002 INV-12) so
        flipping the South Indian theme cannot change what the center box
        shows."""
        self._fan("set_center_varga", varga_code)

    def set_selected_variation(self, zodiac_index, variation_num):
        self._fan("set_selected_variation", zodiac_index, variation_num)

    def set_planet_variation(self, planet_name, variation_num):
        self._fan("set_planet_variation", planet_name, variation_num)

    def zoom_in(self):
        self._fan("zoom_in")

    def zoom_out(self):
        self._fan("zoom_out")

    def reset_zoom(self):
        self._fan("reset_zoom")

    # ------------------------------------------------------------------
    # Writable attributes — explicit properties writing BOTH children
    # ------------------------------------------------------------------

    @staticmethod
    def _write_both(attr):
        def getter(self):
            return getattr(self.active_view, attr)

        def setter(self, value):
            for child in (self.classic_view, self.vector_view):
                setattr(child, attr, value)
        return property(getter, setter)

    show_outer_planets = _write_both("show_outer_planets")
    show_planet_names = _write_both("show_planet_names")
    sign_language = _write_both("sign_language")
    zoom_factor = _write_both("zoom_factor")
    display_settings = _write_both("display_settings")
    _is_dragging = _write_both("_is_dragging")

    # ------------------------------------------------------------------
    # Read-throughs — resolve to the ACTIVE child
    # ------------------------------------------------------------------

    @property
    def scene(self):
        """The ACTIVE child's scene OBJECT (export at core_gui_qt.py:4512
        depends on this being the scene, not a bound method)."""
        return self.active_view.scene

    @property
    def _chart(self):
        return self.active_view._chart

    @property
    def _has_chart(self):
        return getattr(self.active_view, "_has_chart", False)

    def get_background(self):
        return self.active_view.get_background()

    def get_selected_variation(self, zodiac_index):
        return self.active_view.get_selected_variation(zodiac_index)

    def get_planet_variation(self, planet_name):
        return self.active_view.get_planet_variation(planet_name)

    def load_planet_image(self, planet_name, size=48):
        return self.active_view.load_planet_image(planet_name, size=size)

    def render_to_image(self, source_rect=None) -> QImage:
        """Detached snapshot of the ACTIVE child's scene (uniform for both
        themes — renders the scene, never the view's live transform)."""
        scene = self.scene
        source = source_rect if source_rect is not None else scene.sceneRect()
        image = QImage(SCENE_SIZE, SCENE_SIZE, QImage.Format.Format_ARGB32)
        image.fill(QColor(get_theme_colors()["secondary_dark"]))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scene.render(painter, QRectF(0, 0, SCENE_SIZE, SCENE_SIZE), source)
        painter.end()
        return image

    # ------------------------------------------------------------------
    # Inherited-Qt surface (§4.1: the manifest entries hosts actually call)
    # ------------------------------------------------------------------

    def setDragMode(self, mode):
        """Drag mode is per-view state: fan to BOTH children."""
        for child in (self.classic_view, self.vector_view):
            child.setDragMode(mode)

    def viewport(self):
        """The ACTIVE child's viewport (cursor/focus mutations land there)."""
        return self.active_view.viewport()

    def setFocus(self, *args):
        """Forward to the ACTIVE child (keyboard handlers live there)."""
        self.active_view.setFocus(*args)


def create_south_indian_view(parent=None, center_box_enabled=True, style=None):
    """Factory (§4.1, D-9): the host widget, or the classic view DIRECTLY
    when center_box_enabled=False (body-aspect + recursive self-render stay
    classic-only).

    style: optional construction-time theme override ("classic"/"vector",
    validated against SOUTH_INDIAN_STYLES, fallback classic). Activates the
    theme WITHOUT persisting it (Phase-3 review finding 3) — the CLI uses
    this so a render never writes the user's settings file."""
    if not center_box_enabled:
        return SouthIndianView(parent=parent, center_box_enabled=False)
    return SouthIndianHostWidget(parent=parent,
                                 center_box_enabled=center_box_enabled,
                                 style=style)
