"""Center source precedence and one explicitly owned offscreen miniature."""
from apps.widgets.additional_bodies import enabled_names
from apps.widgets.planet_icon_style import appearance_signature
from dataclasses import dataclass
from shiboken6 import isValid
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush,QColor,QPainterPath,QPen
from PySide6.QtWidgets import QGraphicsPathItem
from apps.widgets.center_mini import CenterMiniCache,CenterMiniItem,record_center_picture
from apps.widgets.south_indian_material import WoodMiniBackground
from apps.widgets.south_indian_cells import wood_face
from apps.widgets.south_indian_geometry import (center_rect,CARD_RADIUS,TAG_MEDALLION,TAG_MEDALLION_RING,
    TRANSIT_MEDALLION_INSET,TRANSIT_MINI_TREATMENT,TAG_TRANSIT,varga_label)
from ui.qt_theme import GOLD,get_theme_colors,get_ui_saturation
@dataclass(frozen=True)
class CenterRequest:
    chart: object
    aditya_mode: str
    western_names: bool
    language: str
    show_outer: bool
    show_names: bool
    finish: str
    sign_display: str
    sign_variations: dict
    planet_variations: dict

class CenterContentController:
    def __init__(self, mini_factory):
        self.mini_factory = mini_factory
        self._mini_transit_view = None
        self._center_cache = CenterMiniCache()
        self._transit_manager = None
        self._transit_overlay_active = False
        self._center_varga_code = None
        self.time_adjust_mode = False
        self._z6b_selection = None

    def dispose(self):
        self._release_transit_mini()
        self._transit_manager = None
        self.mini_factory = None


    def _draw_medallion(self, scene, style, request):
        """Center medallion: theme secondary fill, 2px gold border, thin gold
                inner ring inset 18px. T-8 revision (spec v0.6, D-12 reversed): no
                chart title — the center block is reserved for other content
                (transit placeholder stub, Phase-2 center modes)."""
        rect = center_rect()
        colors = get_theme_colors()
        path = QPainterPath()
        path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        base = QGraphicsPathItem(path)
        base.setBrush(Qt.BrushStyle.NoBrush if style.wood else QBrush(QColor(colors['secondary'])))
        base.setPen(QPen(Qt.PenStyle.NoPen) if style.wood else QPen(QColor(GOLD), 2))
        base.setZValue(0)
        base.setData(Qt.ItemDataRole.UserRole, TAG_MEDALLION)
        scene.addItem(base)
        ring_path = QPainterPath()
        ring_path.addRoundedRect(rect.adjusted(18, 18, -18, -18), CARD_RADIUS, CARD_RADIUS)
        ring = QGraphicsPathItem(ring_path)
        ring.setBrush(Qt.BrushStyle.NoBrush)
        ring.setPen(QPen(Qt.PenStyle.NoPen) if style.wood else QPen(QColor(GOLD), 1))
        ring.setZValue(2)
        ring.setData(Qt.ItemDataRole.UserRole, TAG_MEDALLION_RING)
        scene.addItem(ring)
        if style.wood:
            wood_face(scene, style, rect, 'si.vector.wood.center')
        if self.time_adjust_mode or request.chart is None:
            return
        if self._transit_overlay_active:
            transit = getattr(self._transit_manager, 'transit_chart', None)
            self._draw_center_mini(rect, transit, None, scene, style, request)
        elif self._center_varga_code is not None:
            self._draw_center_mini(rect, request.chart, self._center_varga_code, scene, style, request)

    def _transit_source_renderable(self):
        """INV-4: active only when the source says enabled AND carries a
            chart. `manager is not None` is NOT the test — the comparison panel
            passes a deliberately DISABLED source to clear the overlay
            (pro/panels/dual_chart_comparison.py), and the manager can sit
            enabled with no usable chart after a calculation failure."""
        source = self._transit_manager
        return bool(source is not None and getattr(source, 'transit_enabled', False) and (getattr(source, 'transit_chart', None) is not None))

    def _center_render_signature(self, chart, varga_code, request):
        """What the cached recording depends on that has NO event to hook.

            F8 (outer planets), F11 (planet names) and the sign language reach
            this view as PLAIN ATTRIBUTE WRITES from the host, so nothing fires
            when they change and the center box would keep showing the old
            planet set or language. The chart identity and varga code are in
            here too (a dasha-locked switch keeps the jd; D-9 -> D-10 changes
            neither jd, mode nor labels, SPEC-VGC-001 INV-8), as is the icon family."""
        return (enabled_names(), appearance_signature(), id(chart), varga_code, request.language, request.show_outer, request.show_names, request.finish, request.sign_display, get_ui_saturation(), request.aditya_mode, request.western_names)

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
        if mini is not None and isValid(mini):
            mini.deleteLater()

    def _draw_center_mini(self, medallion_rect, chart, varga_code, scene, style, request):
        """Render (or reuse) a mini chart and place it in the medallion.

            Source-agnostic by design (SPEC-VGC-001 INV-1): the transit overlay
            passes the transit chart with `varga_code=None` because transit is
            always D-1 rashi (SPEC-TRN-001 §4.2); the varga mode passes the
            natal chart with the selected code. Precedence between them is the
            caller's, in `_draw_medallion`."""
        inset = TRANSIT_MEDALLION_INSET
        target = medallion_rect.adjusted(inset, inset, -inset, -inset)
        size = int(min(target.width(), target.height()))
        if size <= 0 or chart is None:
            return
        signature = self._center_render_signature(chart, varga_code, request)
        picture = self._center_cache.get(signature)
        if picture is None:
            picture = self._center_cache.put(self._record_center_mini(size, chart, varga_code, style, request), signature)
        if picture is None:
            return
        item = CenterMiniItem(picture, size, veil=TRANSIT_MINI_TREATMENT == 'veil', label=varga_label(varga_code), label_color=style.ink('main', GOLD), background=WoodMiniBackground(request.finish) if style.wood else None)
        item.setPos(target.center().x() - size / 2, target.center().y() - size / 2)
        item.setZValue(52)
        item.setData(Qt.ItemDataRole.UserRole, TAG_TRANSIT)
        scene.addItem(item)
        del item

    def _record_center_mini(self, size, chart, varga_code, style, request):
        """Feed the shared off-screen mini and record it at `size`.

            ONE mini per chart type per view (SPEC-VGC-001 INV-7): transit and
            varga are both South Indian charts, so they reuse this instance
            rather than allocating a second one per source."""
        if self._mini_transit_view is None:
            self._mini_transit_view = self.mini_factory()
            self._mini_transit_view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        mini = self._mini_transit_view
        mini.appearance.vector_finish = request.finish
        mini.appearance.wood_sign_display = request.sign_display
        mini.appearance.foreground_only = bool(style.wood)
        mini.sign_language = request.language
        mini.show_outer_planets = request.show_outer
        mini.show_planet_names = request.show_names
        mini.appearance._variation_settings = dict(request.sign_variations)
        mini.appearance._planet_variation_settings = dict(request.planet_variations)
        try:
            mini.update_from_chart(chart, varga_code=varga_code, use_western_names=request.western_names, aditya_mode=request.aditya_mode)
        except Exception as e:
            print(f'[SI VECTOR] Center mini render skipped: {e}')
            return None
        return record_center_picture(mini, size)

    def update_transit_overlay(self, manager, redraw):
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
        redraw()

    def set_center_varga(self, varga_code, redraw):
        """Draw `varga_code` in the medallion while the outer grid stays D-1.

            SPEC-VGC-001. `None` clears it. Validated rather than coerced: the
            Z6b setter shipped with a `% 12` that silently mapped 0 to Parjanya
            and 13 to Dhata, and a bad varga code here would silently draw the
            WRONG divisional chart — which reads as a real reading.
            """
        valid = varga_code is None or (isinstance(varga_code, int) and (not isinstance(varga_code, bool)) and (varga_code != 0))
        if not valid:
            print(f'[SI VECTOR] Ignoring invalid center varga: {varga_code!r} (expected a libaditya varga code or None)')
            return
        if varga_code == self._center_varga_code:
            return
        self._center_varga_code = varga_code
        self._center_cache.invalidate()
        if varga_code is None and (not self._transit_overlay_active):
            self._release_transit_mini()
        redraw()

    def set_z6b_selection(self, sign_index_1based, set_ascendant):
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
            set_ascendant(None)
            return
        valid = isinstance(sign_index_1based, int) and (not isinstance(sign_index_1based, bool)) and (1 <= sign_index_1based <= 12)
        if not valid:
            print(f'[SI VECTOR] Ignoring invalid Z6b selection: {sign_index_1based!r} (expected 1-12 or None)')
            return
        self._z6b_selection = sign_index_1based
        set_ascendant(sign_index_1based - 1)

    def set_time_adjust_mode(self, enabled, redraw):
        """Time adjust owns the center area (precedence 1, §3.2): the
            overlay leaves the SCENE, not just the screen, so nothing shows
            around the time-adjust widget and nothing is redrawn underneath it.

            The redraw is mandatory, not cosmetic: under INV-5 the scene is the
            only path to the screen, so a setter that changes center state and
            does not redraw changes nothing at all."""
        self.time_adjust_mode = bool(enabled)
        redraw()
