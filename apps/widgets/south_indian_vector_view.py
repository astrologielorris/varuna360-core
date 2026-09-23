# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""South Indian chart composition and the stable classic/vector host API.

The vector facade owns its Qt scene, signals, source inputs and COT subscription.
Appearance, camera policy, retinue graphics and center lifetime have explicit
owners; projection and stateless painters preserve the existing chart geometry.
Geometry/item names remain re-exported for the established consumer contract.
"""
from apps.widgets.additional_bodies import display_names, add_unavailable_notice, refresh_host, refresh_vector

import weakref

from PySide6.QtCore import QPointF, Qt, QRectF, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QStackedLayout, QWidget

from managers.settings_manager import DEFAULT_SOUTH_INDIAN_STYLE, SOUTH_INDIAN_STYLES

# INV-1: the sign→cell mapping is the classic view's class constant, imported
# (never copied) so the two themes can never drift apart. chart_view pulls in
# Qt, which is fine — this module is Qt-based too.
from apps.widgets.chart_view import SouthIndianView
from apps.widgets.wheel_items import RetinueClickSignal

# The ONE center-mini renderer (SPEC-VGC-001 INV-1). It imports neither view,
# so this arrow stays one-way. Imported for USE, not re-export: anything that
# wants these names takes them from center_mini, or INV-1 is cosmetic.

# INV-7/INV-8: colors come ONLY from the theme module and the shared element
# table — no raw hex literals in this file.
from ui.qt_theme import get_theme_colors
from core.aditya_mode import displayed_sign_name

# SPEC-COT-001 §4.10 — the in-sign card index. The setting, the memoised
# spread and the plaque art are shared with the wheel and North Indian views;
# only WHERE the plaque goes is this view's business.
from apps.widgets.cot_index_item import CotIndexMixin

from apps.widgets.south_indian_material import JoshGlyphItem

from apps.widgets.south_indian_geometry import (
    ZODIAC_POSITIONS as ZODIAC_POSITIONS,
    SCENE_SIZE as SCENE_SIZE,
    CELL_SIZE as CELL_SIZE,
    GUTTER as GUTTER,
    CARD_SIZE as CARD_SIZE,
    CARD_RADIUS as CARD_RADIUS,
    CONTENT_PADDING as CONTENT_PADDING,
    _SIGN_CELLS as _SIGN_CELLS,
    cell_rect as cell_rect,
    center_rect as center_rect,
    house_number_for_sign as house_number_for_sign,
    PROJECT_ROOT as PROJECT_ROOT,
    TAG_FRAME as TAG_FRAME,
    TAG_MEDALLION as TAG_MEDALLION,
    TAG_MEDALLION_RING as TAG_MEDALLION_RING,
    TAG_CARD as TAG_CARD,
    TAG_SIGN_ICON as TAG_SIGN_ICON,
    TAG_SIGN_NAME as TAG_SIGN_NAME,
    TAG_BADGE_PILL as TAG_BADGE_PILL,
    TAG_COT_CARD as TAG_COT_CARD,
    TAG_HOUSE_NUMBER as TAG_HOUSE_NUMBER,
    TAG_CUSP as TAG_CUSP,
    TAG_HOVER as TAG_HOVER,
    SIGN_ICON_SIZE as SIGN_ICON_SIZE,
    MIN_BADGE_FONT_SIZE as MIN_BADGE_FONT_SIZE,
    HOUSE_NUMBER_FONT_SIZE as HOUSE_NUMBER_FONT_SIZE,
    BADGE_PILL_PAD_X as BADGE_PILL_PAD_X,
    BADGE_PILL_PAD_Y as BADGE_PILL_PAD_Y,
    COT_INDEX_MIN_GAP as COT_INDEX_MIN_GAP,
    TAG_PLANET as TAG_PLANET,
    TAG_PLANET_TEXT as TAG_PLANET_TEXT,
    TAG_COMPASS_HOUSE as TAG_COMPASS_HOUSE,
    TAG_LAGNA as TAG_LAGNA,
    TAG_LAGNA_LABEL as TAG_LAGNA_LABEL,
    TAG_TRANSIT as TAG_TRANSIT,
    OUTER_PLANETS as OUTER_PLANETS,
    PLANET_ROW_HEIGHT_FRACTION as PLANET_ROW_HEIGHT_FRACTION,
    TRANSIT_MEDALLION_INSET as TRANSIT_MEDALLION_INSET,
    TRANSIT_MINI_TREATMENT as TRANSIT_MINI_TREATMENT,
    varga_label as varga_label,
    crowded_planet_size as crowded_planet_size,
    lone_planet_zone as lone_planet_zone,
)
from apps.widgets.south_indian_items import (
    SignCardItem as SignCardItem,
    HoverZoneItem as HoverZoneItem,
    PlanetClickSignal as PlanetClickSignal,
    SignClickSignal as SignClickSignal,
    ClickablePlanetItem as ClickablePlanetItem,
    SignIconItem as SignIconItem,
)

from core.south_indian_render_data import RenderProjection
from apps.widgets.south_indian_appearance import AppearanceAssets
from apps.widgets.south_indian_paint_style import LayoutMetrics, ClickSignals
from apps.widgets.south_indian_cells import draw_chrome, draw_house_numbers, draw_cusps
from apps.widgets.south_indian_planets import draw_planets, draw_lagna_stripe

def _compass_frame_provider():
    compass_frame = None
    pass  # Pro import stripped for Lite distribution
    if compass_frame is None:  # The Core source builder strips the import above.
        raise ImportError('Compass frame is not available in this edition.')
    return compass_frame

def _require_compass_frame():
    frame = _compass_frame_provider()
    for name in ('compass_house', 'compass_position', 'location_cell',
                 'planet_right_ascension', 'planet_tropical_longitude',
                 'true_obliquity', 'yamakoti_armc'):
        if not callable(getattr(frame, name, None)):
            raise ImportError('South Indian Compass frame is incomplete: '+name)

from apps.widgets.south_indian_interaction import InteractionController, CameraOps, PointerIntent

def _camera_ops(view):
    # A synchronous, typed capability set; no controller retains these callbacks.
    return CameraOps(view.viewport().size, view.scene.sceneRect, view.resetTransform,
                     view.scale, view.centerOn, view.setTransformationAnchor)

def _pointer_hits(view, event):
    # Normalize transient Qt hits; policy receives values, never retained items.
    for item in view.items(event.position().toPoint()):
        if isinstance(item, ClickablePlanetItem):
            yield PointerIntent('planet', (item.planet_name, item.planet_info))
        elif isinstance(item, (SignIconItem, JoshGlyphItem)):
            yield PointerIntent('sign', (item.zodiac_index, item.current_variation))
        elif view.wood and item.data(Qt.ItemDataRole.UserRole) == TAG_SIGN_NAME:
            index = item.data(Qt.ItemDataRole.UserRole+1)
            yield PointerIntent('sign', (index, view.get_selected_variation(index)))

from core.south_indian_retinue_data import retinue_records
from apps.widgets.south_indian_retinue_controller import RetinueController, RetinueEligibility, RetinueInput
from apps.widgets.south_indian_retinue_layer import SouthIndianRetinueLayer, LayerServices
from PySide6.QtWidgets import QLabel, QMenu
from PySide6.QtCore import QCoreApplication

def _layer_services(view):
    ref = weakref.ref(view)
    def menu_factory():
        return QMenu(ref())
    def global_position(point):
        target = ref()
        return target.viewport().mapToGlobal(target.mapFromScene(point))
    return LayerServices(view.scene, view.appearance.style(), False, QLabel(view),
        lambda text: QCoreApplication.translate('SouthIndianVectorView', text), menu_factory, global_position)

def _retinue_eligibility(view):
    return RetinueEligibility(view.center_box_enabled, view.retinue.drawable,
                             bool(view.compass_mode and view.projection._chart_jd() is not None))

def _retinue_input(view):
    eligibility = _retinue_eligibility(view)
    records, omissions = (), ()
    if view.retinue.effective(eligibility):
        anchors = {i.planet_name:(i.pos().x(),i.pos().y()) for i in view.scene.items() if isinstance(i, ClickablePlanetItem)}
        if view._cusps:
            try:
                point = cell_rect(view._cusps[1].sign()-1).center()
                anchors['Ascendant'] = (point.x(),point.y())
            except (KeyError, TypeError, ValueError, AttributeError):
                pass  # The Qt-free adapter records the malformed cusp omission below.
        records, omissions = retinue_records(view._planets, view._cusps, view._varga_code, anchors, display_names(view.PLANET_NAMES), view.show_outer_planets)
    labels = tuple(displayed_sign_name(i,view._aditya_mode,view._use_western_names,view.sign_language) for i in range(12))
    return RetinueInput(eligibility, records, omissions, labels,
        view.projection._effective_ascendant_sign_index(), view.appearance.style())

from functools import partial
from apps.widgets.south_indian_center import CenterContentController, CenterRequest

def _new_center_mini():
    return SouthIndianVectorView(center_box_enabled=False)

from apps.widgets.ascendant_guide import AscendantGuide

def _center_request(view):
    return CenterRequest(view.guide.center_chart(view._chart), view._aditya_mode, view._use_western_names,
        view.sign_language, view.show_outer_planets, view.show_planet_names,
        view.vector_finish, view.wood_sign_display,
        dict(view.appearance._variation_settings), dict(view.appearance._planet_variation_settings))


def _draw_vector_chart(view):
    view.projection.configure(view._chart, view._cusps, view._planets, view._varga_code, view._aditya_mode, view._use_western_names, view.sign_language, view.ascendant_override, view.compass_mode)
    snapshot = view.projection.snapshot(display_names(view.PLANET_NAMES), view.show_outer_planets, view.show_planet_names)
    style = view.appearance.style()
    layout = LayoutMetrics({}, {})
    signals = ClickSignals(view.planet_click_signal, view.sign_click_signal)
    faces = view._cot_faces() if view._cot_enabled() else {}
    view.retinue.begin_rebuild()
    view.scene.clear()
    draw_chrome(view.scene, snapshot, style, layout, signals, view.center_box_enabled, partial(view.center._draw_medallion, view.scene, style, _center_request(view)), faces, view.devicePixelRatioF())
    if snapshot.has_chart:
        if not snapshot.compass_mode:
            draw_house_numbers(view.scene, snapshot, style)
            draw_cusps(view.scene, snapshot, style)
        draw_planets(view.scene, snapshot, style, layout, signals)
        add_unavailable_notice(view.scene, view._planets)
        if not snapshot.compass_mode:
            draw_lagna_stripe(view.scene, snapshot, style)
    view.retinue.drawable = bool(view._chart)
    view._refresh_retinue()
    birth_sign = view._cusps[1].sign() - 1 if view._cusps else None
    view.guide.update(snapshot, style, birth_sign)


def _draw_vector_empty(view):
    view.projection.configure(view._chart, view._cusps, view._planets, view._varga_code, view._aditya_mode, view._use_western_names, view.sign_language, view.ascendant_override, view.compass_mode)
    snapshot = view.projection.snapshot(display_names(view.PLANET_NAMES), view.show_outer_planets, view.show_planet_names)
    style = view.appearance.style()
    layout = LayoutMetrics({}, {})
    signals = ClickSignals(view.planet_click_signal, view.sign_click_signal)
    faces = view._cot_faces() if view._cot_enabled() else {}
    view.retinue.drawable = False
    view.setViewportMargins(0,0,0,0)
    view.retinue.begin_rebuild()
    view.scene.setSceneRect(view.natal_bounds)
    view.scene.clear()
    draw_chrome(view.scene, snapshot, style, layout, signals, view.center_box_enabled, partial(view.center._draw_medallion, view.scene, style, _center_request(view)), faces, view.devicePixelRatioF())
    birth_sign = view._cusps[1].sign() - 1 if view._cusps else None
    view.guide.update(snapshot, style, birth_sign)

class SouthIndianVectorView(CotIndexMixin, QGraphicsView):
    """Vector South Indian chart view (SPEC-SIC-002).

    Standard chrome remains flat under INV-3/D-11. The opt-in wood finishes
    use only their dedicated material textures; ``set_background`` stores an
    unrelated legacy background id without changing this renderer.
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
        self.projection = RenderProjection(_compass_frame_provider)
        self.appearance = AppearanceAssets(live=center_box_enabled)
        self.interaction = InteractionController()
        self.center = CenterContentController(_new_center_mini)
        self.destroyed.connect(self.center.dispose)
        self.destroyed.connect(self.interaction.dispose)
        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.scene.setSceneRect(0, 0, SCENE_SIZE, SCENE_SIZE)
        self.setScene(self.scene)
        self._chart = None
        self.projection._chart = None
        self._varga_code = None
        self._use_western_names = False
        self._aditya_mode = 'aditya'
        self._cusps = None
        self.guide = AscendantGuide(self.viewport(), self.mapFromScene, self.center, self.draw_full_chart)
        self._has_chart = False
        self.ascendant_override = None
        self.compass_mode = False
        self.projection._compass_armc = None
        self.projection._compass_jd = None
        self.projection._compass_eps = None
        self.compass_notice = None
        self.projection._location_cell = None
        self.show_outer_planets = True
        self.show_planet_names = False
        self._planets = None
        self.planet_click_signal = PlanetClickSignal()
        self.sign_click_signal = SignClickSignal()
        self.retinue_click_signal = RetinueClickSignal()
        self._cot_init()
        self._setup_view()
        self.retinue = RetinueController(SouthIndianRetinueLayer(_layer_services(self)))
        self.destroyed.connect(self.retinue.dispose)
        _LIVE_VECTOR_VIEWS.add(self)

    # ------------------------------------------------------------------
    # View boilerplate (re-derived from the NI donor, D-8)
    # ------------------------------------------------------------------

    @property
    def vector_finish(self):
        return self.appearance.vector_finish

    @property
    def wood_sign_display(self):
        return self.appearance.wood_sign_display

    @property
    def sign_language(self):
        return self.appearance.sign_language

    @sign_language.setter
    def sign_language(self, value):
        self.appearance.sign_language = value

    @property
    def zoom_factor(self):
        return self.interaction.zoom_factor

    @zoom_factor.setter
    def zoom_factor(self, value):
        self.interaction.zoom_factor = value

    @property
    def min_zoom(self):
        return self.interaction.min_zoom

    @property
    def max_zoom(self):
        return self.interaction.max_zoom

    @property
    def zoom_step(self):
        return self.interaction.zoom_step

    @property
    def _is_dragging(self):
        return self.interaction._is_dragging

    @_is_dragging.setter
    def _is_dragging(self, value):
        self.interaction._is_dragging = value

    @property
    def show_retinue_rings(self):
        return self.retinue.rings

    @property
    def show_trimsamsha_degrees(self):
        return self.retinue.ruler

    @property
    def retinue_layer(self):
        return self.retinue.layer

    @property
    def time_adjust_mode(self):
        return self.center.time_adjust_mode

    def _setup_view(self):
        """Configure render hints, drag, focus, and background (NI :252-277)."""
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.interaction._is_dragging = False
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        # StrongFocus so keyPressEvent receives the +/- /0 zoom shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setBackgroundBrush(
            QBrush(QColor(get_theme_colors()["secondary_dark"])))

    def _apply_fit_zoom(self):
        return self.interaction._apply_fit_zoom(_camera_ops(self))

    def showEvent(self, event):
        """On first show: defer auto-fit via timer. Later: re-apply zoom."""
        super().showEvent(event)
        if self.retinue_layer.dirty:
            self._refresh_retinue()
        if not self.interaction._fit_zoom_applied:
            QTimer.singleShot(0, self, self._apply_fit_zoom)
        else:
            self.interaction.reapply(_camera_ops(self))

    def wheelEvent(self, event):
        return self.interaction.wheelEvent(_camera_ops(self), event)

    def zoom_in(self):
        return self.interaction.zoom_in(_camera_ops(self))

    def zoom_out(self):
        return self.interaction.zoom_out(_camera_ops(self))

    def fit_width(self):
        return self.interaction.fit_width(_camera_ops(self))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.interaction.resize(_camera_ops(self), getattr(self, 'retinue', None) is not None and self.retinue.updating)

    def reset_zoom(self):
        return self.interaction.reset_zoom(_camera_ops(self))

    def focusNextPrevChild(self, next):
        layer = getattr(self, 'retinue_layer', None)
        if layer is not None and self.retinue_effective:
            focused = self.scene.focusItem()
            current = layer.chips.index(focused) if focused in layer.chips else None
            target = self.interaction.focus_index(len(layer.chips), current, next, self.hasFocus())
            if target is not None:
                layer.chips[target].setFocus()
                return True
        return super().focusNextPrevChild(next)

    def keyPressEvent(self, event):
        intent = self.interaction.key_intent(event.key())
        actions = {'clear': self.retinue_layer.clear_trace, 'in': self.zoom_in, 'out': self.zoom_out, 'reset': self.reset_zoom}
        if intent in actions:
            actions[intent]()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Start panning on left press (single click never opens dialogs)."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        for item in self.items(event.position().toPoint()):
            chip = self.retinue_layer.chip_for_item(item)
            if chip is not None:
                chip.setFocus()
                chip.choose()
                event.accept()
                return
        # Sectors retain the chart's double-click-to-open / drag-to-pan contract.
        # A press on one is not an empty-space dismissal of a pinned planet.
        if self.retinue_layer.sector_at(self.mapToScene(event.position().toPoint())) is None:
            self.retinue_layer.clear_trace()
        if event.button() == Qt.MouseButton.LeftButton:
            self.interaction._is_dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.retinue_effective:
            for item in self.items(event.position().toPoint()):
                if isinstance(item, ClickablePlanetItem):
                    self.retinue_layer.hover(item.planet_name)
                    return
            # Chip hover is dispatched by QGraphicsScene.
            if not any(self.retinue_layer.chip_for_item(i) is not None
                       for i in self.items(event.position().toPoint())):
                self.retinue_layer.hover_sector(self.mapToScene(event.position().toPoint()))

    def leaveEvent(self, event):
        self.retinue_layer.hover(None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        """Restore the arrow cursor after panning."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.interaction._is_dragging = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        sector = self.retinue_layer.sector_at(self.mapToScene(event.position().toPoint())) if self.retinue_effective else None
        intent = self.interaction.double_click_intent(event.button() == Qt.MouseButton.LeftButton, sector, _pointer_hits(self, event))
        if intent is None:
            super().mouseDoubleClickEvent(event)
            return
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        signals = {'retinue': self.retinue_click_signal, 'planet': self.planet_click_signal, 'sign': self.sign_click_signal}
        signals[intent.kind].clicked.emit(*intent.payload)
        event.accept()

    @property
    def display_settings(self):
        return self.appearance._si_display_settings

    @display_settings.setter
    def display_settings(self, value):
        self.appearance.reload_display()

    def load_sign_icon(self, sign_index: int, size: int=SIGN_ICON_SIZE):
        return self.appearance.load_sign_icon(sign_index, size)

    # ------------------------------------------------------------------
    # Public protocol (Wave 2a subset — full INV-5 surface is Wave 2b)
    # ------------------------------------------------------------------

    @property
    def natal_bounds(self):
        return QRectF(0, 0, SCENE_SIZE, SCENE_SIZE)

    @property
    def content_bounds(self):
        return self.scene.sceneRect()

    @property
    def retinue_effective(self):
        return self.retinue.effective(_retinue_eligibility(self))

    def retinue_state(self):
        return self.retinue.state(_retinue_eligibility(self))

    def set_show_retinue_rings(self, on, *, defer_hidden=False):
        if self.retinue.set_rings(on):
            self._refresh_retinue(defer_hidden=defer_hidden)

    def set_show_trimsamsha_degrees(self, on):
        return self.retinue.set_ruler(on)

    def set_retinue_style_active(self, active):
        if self.retinue.set_style_active(active):
            self._refresh_retinue()

    def _refresh_retinue(self, *, defer_hidden=False):
        if defer_hidden and (not self.isVisible()):
            self.retinue.defer()
            return
        center = self.viewportTransform().inverted()[0].map(QPointF(self.viewport().width() / 2, self.viewport().height() / 2))
        self.retinue.updating = True
        try:
            self.retinue.materialize(_retinue_input(self))
            self.setViewportMargins(0, self.retinue.notice_margin(_retinue_eligibility(self)), 0, 0)
            self.centerOn(center)
        finally:
            self.retinue.updating = False

    def set_background(self, bg_id):
        self.appearance.background_id = bg_id

    @property
    def wood(self):
        return self.appearance.wood

    def set_vector_appearance(self, finish, sign_display):
        """Apply local rendering preferences without writing global settings."""
        if not self.appearance.apply(finish, sign_display):
            return
        pin = self.retinue_layer.pin
        self.center._invalidate_transit_cache()
        self.draw_full_chart()
        if pin is not None and pin in self.retinue_layer.placements:
            self.retinue_layer.select(pin)

    def get_background(self):
        return self.appearance.background_id

    def update_from_chart(self, chart, varga_code=None, use_western_names=False,
                          aditya_mode=None, **_kw):
        """Render from a libaditya Chart object (primary entry point)."""
        previous_chart = self._chart
        self._chart = chart
        self.projection._chart = chart
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
        # SPEC-SIC-004: invalidate the Yamakoti MC on every chart update (a new
        # jd needs a new Midheaven, PM-4) — recomputed lazily by _placement only
        # while on. NEVER reset compass_mode here (PM-3): update_from_chart is
        # also the varga-switch / view-sync / ascendant-broadcast redraw path,
        # and the flag has the same lifetime as ascendant_override. Recompute
        # the notice each time so it is set AND cleared (PM-12).
        self.projection._compass_armc = self.projection._compass_eps = None
        self.projection._location_cell = None      # SPEC-SIC-005: recomputed lazily (INV-H7)
        self.compass_notice = None
        if self.compass_mode:
            if self.projection._chart_jd() is None:
                self.compass_notice = "chart has no time, sign frame shown"
            elif varga_code not in (None, 1):
                self.compass_notice = (
                    "Compass shows the D1 frame; varga ignored while on")

        # INV-11: a new natal chart can change the mini's zodiac mode and
        # labels, and (dasha-locked) the transit chart itself at the same jd.
        # Only when the chart OBJECT actually changed, though: this method
        # is also how the outer grid is re-rendered for a varga switch, a
        # view sync or an ascendant change, and invalidating there re-records
        # the mini on every one of them — the multiplier that turned a
        # per-click cost into an everywhere cost.
        if chart is not previous_chart:
            self.center._invalidate_transit_cache()

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

    def set_compass_mode(self, on):
        """Toggle the SPEC-SIC-004 South Indian Compass (Earth-fixed dial).

        No-op when unchanged. Turning ON refuses (returns False, flag unchanged)
        when the chart has no jd (T-13) — the caller surfaces "chart has no
        time". INV-9: the Pro compass-frame import is reached ONLY here (a
        compass-on path) and in _compass_position; on the Core build (Pro
        modules absent) this raises a clear message rather than a bare failure
        (T-12). Returns
        the resulting compass_mode (bool)."""
        on = bool(on)
        if on == self.compass_mode:
            return self.compass_mode
        if on:
            if self.projection._chart_jd() is None:
                # Refused: flag stays off. The caller (Pro handler / remote)
                # surfaces the "chart has no time" reason from the False return;
                # the view does not set compass_notice while off (W1 review N1).
                return False
            # INV-9 / T-12: fail fast and clearly if the Pro frame is absent,
            # BEFORE mutating any state or half-drawing the scene. Probe BOTH
            # names the compass path needs, so a partial module cannot pass the
            # guard and then raise mid-draw where it would be swallowed (CW#3).
            try:
                _require_compass_frame()
            except ImportError as exc:
                raise ImportError(
                    "Compass frame is not available in this edition.") from exc
        self.compass_notice = None
        self.compass_mode = on
        self.projection._compass_armc = self.projection._compass_eps = None  # recompute lazily
        self.draw_full_chart()
        return self.compass_mode

    def clear_icon_cache(self):
        return self.appearance.clear_icon_cache()

    def refresh_theme(self):
        """Re-read theme colors and redraw (SPEC-THM-001 live switch)."""
        self.setBackgroundBrush(
            QBrush(QColor(get_theme_colors()["secondary_dark"])))
        # INV-11: the mini chart is painted with the old palette.
        self.center._invalidate_transit_cache()
        self.draw_full_chart()

    def items_by_tag(self, tag: str):
        """Scene items carrying a si.vector.* UserRole tag (INV-9 tracking)."""
        return [item for item in self.scene.items()
                if item.data(Qt.ItemDataRole.UserRole) == tag]

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw_full_chart(self):
        return _draw_vector_chart(self)

    def draw_empty_grid(self):
        return _draw_vector_empty(self)

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

    def load_planet_image(self, planet_name, size=48):
        return self.appearance.load_planet_image(planet_name, size)

    @property
    def location_cell(self):
        return self.projection.location_cell

    @property
    def location_house(self):
        return self.projection.location_house

    # ------------------------------------------------------------------
    # Transit placeholder + export + remaining INV-5 protocol (Wave 2b)
    # ------------------------------------------------------------------

    def clear_chart(self):
        """Clear the chart display to the empty grid (classic :1490-1502)."""
        self._chart = None
        self.projection._chart = None
        self._varga_code = None
        self._planets = None
        self._cusps = None
        self._has_chart = False
        # SPEC-SIC-004: a stale compass notice/MC must not outlive the chart it
        # described (W1 review CW#1/#2) — invalidate both. compass_mode itself
        # is kept (same lifetime as the F4 override): the next chart re-enters
        # the frame the user last chose.
        self.compass_notice = None
        self.projection._compass_armc = self.projection._compass_eps = None
        self.projection._location_cell = None      # SPEC-SIC-005: same lifetime (INV-H7)
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
        self.scale(self.interaction.zoom_factor, self.interaction.zoom_factor)
        self.centerOn(SCENE_SIZE / 2, SCENE_SIZE / 2)

    def render_to_image(self, source_rect=None) -> QImage:
        """Detached scene snapshot (§4.6 / T-6): a fresh ARGB32 QImage at
        sceneRect size, pre-filled with the theme background. Adds nothing
        to the scene and is independent of the view transform — safe to
        call any time."""
        if self.retinue_layer.dirty:
            self._refresh_retinue()
        source = (source_rect if source_rect is not None
                  else self.scene.sceneRect())
        image = QImage(round(source.width()), round(source.height()), QImage.Format.Format_ARGB32)
        image.fill(QColor(get_theme_colors()["secondary_dark"]))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.scene.render(painter, QRectF(0, 0, image.width(), image.height()),
                          source)
        painter.end()
        return image

    def update_transit_overlay(self, manager):
        return self.center.update_transit_overlay(manager, self.draw_full_chart)

    def set_center_varga(self, varga_code):
        return self.center.set_center_varga(varga_code, self.draw_full_chart)

    def set_z6b_selection(self, sign_index_1based):
        return self.center.set_z6b_selection(sign_index_1based, self.set_ascendant_override)

    def set_time_adjust_mode(self, enabled):
        return self.center.set_time_adjust_mode(enabled, self.draw_full_chart)

    # ------------------------------------------------------------------
    # Variation API (INV-5; classic semantics, settings-manager backing
    # store per spec §4.7: display.zodiac_variations /
    # display.planet_variations — NOT the classic settings.json files)
    # ------------------------------------------------------------------

    def get_selected_variation(self, zodiac_index):
        return self.appearance.get_selected_variation(zodiac_index)

    def set_selected_variation(self, zodiac_index, variation_num):
        return self.appearance.set_selected_variation(zodiac_index, variation_num, self.center._invalidate_transit_cache, self.draw_full_chart)

    def get_planet_variation(self, planet_name):
        return self.appearance.get_planet_variation(planet_name)

    def set_planet_variation(self, planet_name, variation_num):
        return self.appearance.set_planet_variation(planet_name, variation_num, self.center._invalidate_transit_cache, self.draw_full_chart)

# ---------------------------------------------------------------------------
# Wave 3a (bead td-lizg.5): SouthIndianHostWidget + create_south_indian_view
# ---------------------------------------------------------------------------

# Live-host registry (Phase-3 review finding 1): a style-only settings change
# must reach EVERY live host, including hosts owned by Pro panels the main
# window has no references to. WeakSet so closed panels drop out naturally;
# RuntimeError guards catch wrappers whose C++ object is already gone.
_LIVE_HOSTS = weakref.WeakSet()
_LIVE_VECTOR_VIEWS = weakref.WeakSet()

def _accepts_appearance_refresh(view):
    """Disposed graphics owners must not interrupt live settings broadcasts."""
    return view.appearance.live and view.retinue.layer.services is not None

def sync_all_south_indian_hosts():
    """Call sync_style() on every live SouthIndianHostWidget (D-13).

    The single activation entry point: the settings-apply handler calls
    this instead of syncing one host it happens to know about."""
    from managers.settings_manager import get_settings
    settings = get_settings()
    for view in list(_LIVE_VECTOR_VIEWS):
        try:
            if _accepts_appearance_refresh(view):
                refresh_vector(view, settings.get('display.south_indian_vector_finish', 'standard'),
                                           settings.get('display.sign_display', 'zodiac'))  # td-iaqm.5: unified sign-display
        except RuntimeError:
            _LIVE_VECTOR_VIEWS.discard(view)
    for host in list(_LIVE_HOSTS):
        try:
            refresh_host(host)
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
        self.retinue_click_signal = RetinueClickSignal()
        self.vector_view.retinue_click_signal.clicked.connect(
            self.retinue_click_signal.clicked.emit)
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

        self.vector_view.set_retinue_style_active(self.active_view is self.vector_view)
        self._retinue_live = center_box_enabled
        self.hydrate_retinue_settings()
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
        self.vector_view.set_retinue_style_active(self.active_view is self.vector_view)

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
        self.vector_view.set_retinue_style_active(self.active_view is self.vector_view)

    # ------------------------------------------------------------------
    # Fan-out method calls — BOTH children (INV-12)
    # ------------------------------------------------------------------

    def set_vector_appearance(self, finish, sign_display):
        self.vector_view.set_vector_appearance(finish, sign_display)

    @property
    def vector_finish(self):
        return self.vector_view.vector_finish

    @property
    def wood_sign_display(self):
        return self.vector_view.wood_sign_display

    def hydrate_retinue_settings(self):
        if not getattr(self, '_retinue_live', False):
            return
        from managers.settings_manager import get_settings
        settings = get_settings()
        self.set_show_trimsamsha_degrees(settings.get('chart.show_trimsamsha_degrees', False))
        self.set_show_retinue_rings(settings.get('chart.show_retinue_rings', False))

    def set_retinue_live(self, enabled):
        """Exclude standalone CLI renderers from live GUI preference broadcasts."""
        self._retinue_live = self.vector_view.appearance.live = bool(enabled)

    def set_show_retinue_rings(self, on, *, defer_hidden=False):
        self.vector_view.set_show_retinue_rings(on, defer_hidden=defer_hidden)

    def set_show_trimsamsha_degrees(self, on):
        self.vector_view.set_show_trimsamsha_degrees(on)

    @property
    def show_retinue_rings(self):
        return self.vector_view.show_retinue_rings

    @property
    def show_trimsamsha_degrees(self):
        return self.vector_view.show_trimsamsha_degrees

    @property
    def retinue_effective(self):
        return self.active_view is self.vector_view and self.vector_view.retinue_effective

    def retinue_state(self):
        return self.vector_view.retinue_state()

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

    def set_compass_mode(self, on):
        """SPEC-SIC-004: fan the compass flag to BOTH children (INV-12) so it
        survives a style switch — the classic child accepts and ignores it, the
        vector child does the real work. Returns the VECTOR child's resulting
        state (bool; False if it refused for a jd-less chart)."""
        self.classic_view.set_compass_mode(on)
        return self.vector_view.set_compass_mode(on)

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
        if self.active_view is self.vector_view and self.vector_view.retinue_layer.dirty:
            self.vector_view._refresh_retinue()
        return self.active_view.scene

    @property
    def _chart(self):
        return self.active_view._chart

    @property
    def _has_chart(self):
        return getattr(self.active_view, "_has_chart", False)

    @property
    def compass_mode(self):
        """The compass flag — read from the VECTOR child specifically (spec
        §3.3), NOT the active child: the classic child's accept-and-ignore flag
        stays False, so reading via active_view would report OFF while the
        vector child holds the mode across a style switch (PM-8)."""
        return self.vector_view.compass_mode

    @property
    def compass_shown(self):
        """The host's half of 'shown' (spec §3.3): the flag AND the vector child
        is the active style. The Pro window ANDs its chart_stack visibility and
        the current page onto this."""
        return (self.vector_view.compass_mode
                and self.active_view is self.vector_view)

    @property
    def compass_notice(self):
        """The vector child's varga / no-jd status text, or None."""
        return self.vector_view.compass_notice

    @property
    def location_cell(self):
        """SPEC-SIC-005: the chart location's compass cell — read from the
        VECTOR child specifically (like compass_mode), None while off."""
        return self.vector_view.location_cell

    @property
    def location_house(self):
        """SPEC-SIC-005: 'the house we are in' (the location cell's house),
        from the vector child; None while off."""
        return self.vector_view.location_house

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
        if self.active_view is self.vector_view:
            return self.vector_view.render_to_image(source_rect)
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

def create_south_indian_view(parent=None, center_box_enabled=True, style=None,
                             *, sector_dialog_handler=None):
    """Factory (§4.1, D-9): the host widget, or the classic view DIRECTLY
    when center_box_enabled=False (body-aspect + recursive self-render stay
    classic-only).

    style: optional construction-time theme override ("classic"/"vector",
    validated against SOUTH_INDIAN_STYLES, fallback classic). Activates the
    theme WITHOUT persisting it (Phase-3 review finding 3) — the CLI uses
    this so a render never writes the user's settings file."""
    if not center_box_enabled:
        return SouthIndianView(parent=parent, center_box_enabled=False)
    host = SouthIndianHostWidget(parent=parent,
                                 center_box_enabled=center_box_enabled,
                                 style=style)
    if sector_dialog_handler is None:
        from functools import partial
        from apps.widgets.sector_dialog_presenter import show_chart_sector
        sector_dialog_handler = partial(show_chart_sector, host.vector_view)
    host.retinue_click_signal.clicked.connect(sector_dialog_handler)
    return host
