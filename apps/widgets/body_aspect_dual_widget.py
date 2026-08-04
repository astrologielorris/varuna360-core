"""SPEC-BODY-002: Body Graph Rashi Aspect Dual View.

Wraps the SPEC-BODY-001 BodyGraphView (chart_stack index 3) in a splitter next
to a second SouthIndianView that carries rashi-aspect arrows. Hovering a sign on
the aspect side highlights its incoming+outgoing arrows AND the corresponding
body zones on the left (cross-view sync).

This widget is a DROP-IN proxy for BodyGraphView: it exposes exactly the surface
core_gui_qt.py touches and NOTHING more. It deliberately does NOT provide a catch-all
__getattr__ — that would forward wheel-only methods (set_show_retinue_rings,
draw_wheel, cusp_glow_mode, ...) to the embedded SouthIndianView and make the
hasattr-guarded F5/F6/Shift+F5 handlers fire on the body graph (grounding B3).

Aspect correctness (grounding B1/B7, codex+opencode reviewed):
  * Arrows are computed from the settings-selected table
    libaditya.constants.rashi_aspects[system] (1-based) + a per-sign grahas()
    check, over UNORDERED pairs so mutual aspects coalesce into ONE double-headed
    arrow. rashi_aspect_between / given_to / given_by / chart.context.rashi_aspects
    are NOT used (cached/asymmetric/mutable — would draw wrong arrows).
  * varga source is guarded exactly like the other views:
    chart.varga(vc) if vc and vc != 1 else chart.rashi().

Scene lifecycle (grounding B5): the SouthIndianView clears its whole scene on
every draw_full_chart(). Arrows + hover zones are therefore recreated AFTER each
render and NO Python reference to a scene item is held across a redraw. Stale
arrow items are removed by their "rashi_aspect_arrow" tag off the live scene
(ref-free), guarded against the wrapped-C++-deleted race.
"""
from contextlib import contextmanager
from math import hypot

from PySide6.QtCore import Qt, QEvent, QTimer, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QPolygonF
from PySide6.QtWidgets import QWidget, QSplitter, QHBoxLayout

from apps.widgets.body_graph_view import BodyGraphView
from apps.widgets.chart_view import (
    SouthIndianView, HoverSignal, HoverZoneItem, PlanetClickSignal,
)
from libaditya.constants import rashi_aspects as RASHI_ASPECT_TABLES
from managers.settings_manager import get_settings

_ARROW_TAG = "rashi_aspect_arrow"
_CRIMSON = "#DC143C"
_BRIGHT = "#FF2020"
_GREY = "#888888"

# state -> (color, alpha, pen width, z).
# z=78 sits above planet icons (z=75) so arrowheads are always visible;
# planet text (z=80) stays on top. Hovered arrows lift to z=82.
# "hidden" is the idle state: arrows exist but are invisible until hover.
_ARROW_STYLES = {
    "one_way": (_CRIMSON, 102, 2.5, 78),
    "mutual":  (_CRIMSON, 217, 3.5, 78),
    "hovered": (_BRIGHT, 255, 4.0, 82),
    "dimmed":  (_GREY, 38, 1.5, 78),
    "hidden":  (None, 0, 0.0, -1),
}


def compute_aspect_pairs(has_grahas, table):
    """Pure rashi-aspect computation (grounding B1/B7 — codex-corrected).

    Args:
        has_grahas: {1-based sign -> bool} — does the sign contain a graha (only
                    grahas cast rashi aspects; empty / outer-only signs do not).
        table:      libaditya.constants.rashi_aspects[system], 1-based, where
                    table[i] is the tuple of signs that sign i aspects.

    Returns {(i, j): direction} for i < j, direction in {"i2j","j2i","mutual"}.
    Iterating UNORDERED pairs coalesces reciprocal aspects into a single
    "mutual" (grounding B1); testing both table[i] and table[j] independently
    captures incoming aspects even when the table is asymmetric — which
    rashi_aspects_given_to/given_by cannot do (grounding B7).
    """
    pairs = {}
    for i in range(1, 13):
        for j in range(i + 1, 13):
            ltr = bool(has_grahas.get(i)) and (j in table[i])   # i casts onto j
            rtl = bool(has_grahas.get(j)) and (i in table[j])   # j casts onto i
            if ltr and rtl:
                pairs[(i, j)] = "mutual"
            elif ltr:
                pairs[(i, j)] = "i2j"
            elif rtl:
                pairs[(i, j)] = "j2i"
    return pairs


class BodyAspectDualWidget(QWidget):
    """Splitter shell: BodyGraphView (left) + aspect SouthIndianView (right)."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- child views ---
        self.body_graph_view = BodyGraphView(self)
        # center_box_enabled=False: no built-in hover zones / center preview, so
        # arrows at z=40 are never covered and we own the hover wiring.
        self.aspect_si_view = SouthIndianView(self, center_box_enabled=False)

        # --- splitter layout (equal halves by default) ---
        # Was 70/30. The aspect side is a full South Indian chart, four columns
        # wide: at 30% it rendered clipped, which is what the reader sees first
        # after Shift+F2. Both sides carry a whole chart, so both get half.
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.body_graph_view)
        self.splitter.addWidget(self.aspect_si_view)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        # --- aggregated planet-click signal (wired once at construction) ---
        self.planet_click_signal = PlanetClickSignal()
        self.body_graph_view.planet_click_signal.clicked.connect(
            self.planet_click_signal.clicked.emit)
        self.aspect_si_view.planet_click_signal.clicked.connect(
            self.planet_click_signal.clicked.emit)

        # --- arrow bookkeeping (rebuilt every render; no refs across scene.clear) ---
        # Initialised BEFORE any signal / event-filter wiring so a handler can
        # never fire against a half-constructed widget (codex W2 finding 6).
        self._arrows = {}          # (i, j) 1-based i<j -> {dir, base, curve, heads, items}
        self._hovered_sign = None  # 0-based currently hovered zodiac index, or None
        self._rendering = False    # reentrancy guard for all scene-rebuild paths
        self._si_dirty = False     # aspect side needs a refresh when next shown

        # --- our own hover signal for the aspect SI (its own is unconnected) ---
        self._aspect_hover_signal = HoverSignal(self)
        self._aspect_hover_signal.hover_enter.connect(self._on_aspect_hover)
        self.aspect_si_view.viewport().installEventFilter(self)
        self.aspect_si_view.viewport().setMouseTracking(True)

        # --- panel visibility (persisted) ---
        self._panel_visible = bool(get_settings().get("chart.show_aspect_panel", False))
        self.aspect_si_view.setVisible(self._panel_visible)

        # --- splitter-size persistence (debounced so a drag isn't 100 disk writes) ---
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(300)
        self._splitter_save_timer.timeout.connect(self._save_splitter_sizes)
        self.splitter.splitterMoved.connect(lambda *_: self._splitter_save_timer.start())

        # --- redraw arrows when the aspect system setting changes (W3c) ---
        # Register for the broad "chart" prefix so we catch both direct
        # set("chart.rashi_aspect_system", ...) AND reset_to_defaults("chart").
        # The callback filters out unrelated chart.* changes (view_type, etc.).
        get_settings().on_changed("chart", self._on_aspect_system_changed)

    # ================================================================== #
    # Proxy surface (EXPLICIT — do not add a catch-all __getattr__)       #
    # ================================================================== #
    @contextmanager
    def _render_guard(self):
        """Mark a scene-rebuild in progress so a queued hover/leave never touches
        arrow items mid-teardown (segfault rule #18). Save/restore (not plain
        True/False) so nested rebuilds — e.g. update_from_chart -> _refresh_aspect
        _side -> _compute_and_draw_aspects — don't clear the outer guard early.
        """
        prev = self._rendering
        self._rendering = True
        try:
            yield
        finally:
            self._rendering = prev

    def update_from_chart(self, chart, use_western_names=False,
                          aditya_mode="aditya", gender=None,
                          varga_code=None, **_kw):
        """Delegate to the body graph, then (if visible) refresh the aspect side."""
        with self._render_guard():
            self.body_graph_view.update_from_chart(
                chart, use_western_names=use_western_names,
                aditya_mode=aditya_mode, gender=gender,
                varga_code=varga_code, **_kw)
            self._hovered_sign = None
            if chart is None:
                # Clear the aspect side too, else it keeps a stale chart + arrows.
                # (SouthIndianView.update_from_chart is NOT None-safe, so clear the
                # scene directly.) No refs are held across this clear.
                self.aspect_si_view.scene.clear()
                self._arrows = {}
                self._si_dirty = False
            elif self._panel_visible:
                self._refresh_aspect_side()
                self._si_dirty = False
            else:
                self._si_dirty = True

    def ensure_visible(self):
        self.body_graph_view.ensure_visible()
        if self._panel_visible:
            self.aspect_si_view.ensure_visible()

    def refresh_theme(self):
        self.body_graph_view.refresh_theme()
        if self._panel_visible and self._current_chart is not None:
            # SI.refresh_theme() re-reads theme colours and redraws (clearing our
            # arrows/hover zones), so rebuild the aspect side afterwards.
            with self._render_guard():
                self.aspect_si_view.refresh_theme()
                self._compute_and_draw_aspects()
                self._create_aspect_hover_zones()
            if self._hovered_sign is not None:
                self._on_aspect_hover(self._hovered_sign)
        elif self._current_chart is not None:
            self._si_dirty = True

    # --- proxied attributes -------------------------------------------------
    @property
    def show_outer_planets(self):
        return self.body_graph_view.show_outer_planets

    @show_outer_planets.setter
    def show_outer_planets(self, value):
        # write-through to BOTH child views (F8 handler sets this then re-renders)
        self.body_graph_view.show_outer_planets = value
        self.aspect_si_view.show_outer_planets = value

    @property
    def _current_chart(self):
        return self.body_graph_view._current_chart

    @property
    def _use_western(self):
        return self.body_graph_view._use_western

    @property
    def _aditya_mode(self):
        return self.body_graph_view._aditya_mode

    @property
    def _varga_code(self):
        return self.body_graph_view._varga_code

    @property
    def _gender(self):
        return self.body_graph_view._gender

    @property
    def scene(self):
        # PNG export target: the body graph is the primary export subject.
        return self.body_graph_view.scene

    @property
    def zoom_factor(self):
        return self.body_graph_view.zoom_factor

    @property
    def min_zoom(self):
        return self.body_graph_view.min_zoom

    @property
    def max_zoom(self):
        return self.body_graph_view.max_zoom

    # ================================================================== #
    # Shift+F2 panel toggle                                               #
    # ================================================================== #
    def toggle_aspect_panel(self):
        self.set_aspect_panel_visible(not self._panel_visible)

    def set_aspect_panel_visible(self, visible):
        visible = bool(visible)
        self._panel_visible = visible
        get_settings().set("chart.show_aspect_panel", visible)
        self.aspect_si_view.setVisible(visible)
        if visible:
            w = self.width() or 1200
            frac = self._aspect_split_fraction()
            self.splitter.setSizes([int(w * frac), int(w * (1.0 - frac))])
            if self._si_dirty and self._current_chart is not None:
                with self._render_guard():
                    self._refresh_aspect_side()
                self._si_dirty = False
            # defer fit until the splitter has laid the children out (context-object
            # overload auto-cancels if the widget is destroyed first)
            QTimer.singleShot(0, self, self._fit_both)
        else:
            self._on_aspect_hover_leave()   # clear any active highlight
            QTimer.singleShot(0, self, self.body_graph_view.ensure_visible)

    def _fit_both(self):
        self.body_graph_view.ensure_visible()
        self.aspect_si_view.ensure_visible()

    #: Left-pane share used when nothing usable has been saved.
    DEFAULT_ASPECT_SPLIT = 0.5

    def _aspect_split_fraction(self):
        """Left pane's share of the width, from the saved split or the default.

        The old chart.aspect_splitter_sizes was written on every drag and read
        nowhere, so each Shift+F2 threw the reader's chosen split away. This is
        the missing half, against the replacement key.

        A fraction rather than the pixel pair QSplitter.sizes() returns: the
        panel is shown at whatever width the window happens to have now, so
        replaying old pixels would reproduce the split at the wrong proportion.
        """
        frac = get_settings().get("chart.aspect_split_fraction")
        try:
            frac = float(frac)
        except (TypeError, ValueError):
            return self.DEFAULT_ASPECT_SPLIT
        # A pane dragged (or left) almost shut is nearly always an accident, and
        # restoring it would hide one of the two charts on open. Fall back.
        if not 0.15 <= frac <= 0.85:
            return self.DEFAULT_ASPECT_SPLIT
        return frac

    def _save_splitter_sizes(self):
        """Store the proportion, not the pixels, so it survives a resize."""
        sizes = self.splitter.sizes()
        total = sum(sizes[:2])
        if total <= 0:
            return
        get_settings().set("chart.aspect_split_fraction", sizes[0] / total)

    # ================================================================== #
    # Aspect side: render + arrows + hover zones                         #
    # ================================================================== #
    def _refresh_aspect_side(self):
        """Push the current chart to the aspect SI, then (re)draw arrows + zones.

        Reads chart state back from the body view (single source of truth), so
        the varga/mode/western flags always match the left side.
        """
        chart = self._current_chart
        if chart is None:
            return
        # SI.update_from_chart -> draw_full_chart -> scene.clear() destroys any
        # prior arrows AND hover zones. Recreate them AFTER, holding no old refs.
        self.aspect_si_view.update_from_chart(
            chart, varga_code=self._varga_code,
            use_western_names=self._use_western, aditya_mode=self._aditya_mode)
        self._compute_and_draw_aspects()
        self._create_aspect_hover_zones()

    def _signs_for_current(self):
        """Return the 1-based Signs object for the active chart, varga-guarded."""
        chart = self._current_chart
        if chart is None:
            return None
        vc = self._varga_code
        source = chart.varga(vc) if vc and vc != 1 else chart.rashi()
        return source.signs()

    def _compute_and_draw_aspects(self):
        """Draw rashi-aspect arrows for the current chart + settings system."""
        self._clear_arrow_items()
        signs_obj = self._signs_for_current()
        if signs_obj is None:
            return
        system = get_settings().get("chart.rashi_aspect_system") or "quadrant"
        table = RASHI_ASPECT_TABLES.get(system) or RASHI_ASPECT_TABLES["quadrant"]

        has_grahas = {}
        for s in range(1, 13):
            try:
                g = signs_obj[s].grahas()
                has_grahas[s] = bool(g)
            except (KeyError, IndexError, AttributeError) as e:
                from utils.debug import debug_print
                debug_print(f"[BodyAspect] grahas() failed for sign {s}: {e}")
                has_grahas[s] = False

        pairs = compute_aspect_pairs(has_grahas, table)
        for (i, j), direction in pairs.items():
            base = "mutual" if direction == "mutual" else "one_way"
            arr = self._draw_arrow(i, j, direction, base)
            self._style_arrow(arr, "hidden")
            self._arrows[(i, j)] = arr

    def _clear_arrow_items(self):
        """Remove prior arrow items by tag off the LIVE scene (ref-free).

        After a draw_full_chart the scene was already cleared, so this is a no-op
        then; on a settings-driven redraw it removes the still-live tagged items.
        """
        scene = self.aspect_si_view.scene
        for it in list(scene.items()):
            try:
                if it.data(Qt.ItemDataRole.UserRole) == _ARROW_TAG:
                    scene.removeItem(it)
            except (RuntimeError, ValueError):
                pass
        self._arrows = {}

    # ---- geometry ----------------------------------------------------------
    def _cell_center(self, gui_idx):
        """Scene-coordinate centre of the cell for a 0-based zodiac index."""
        cs = self.aspect_si_view.cell_size
        for (row, col), z in SouthIndianView.ZODIAC_POSITIONS.items():
            if z == gui_idx:
                return QPointF(col * cs + cs / 2.0, row * cs + cs / 2.0)
        return None

    def _draw_arrow(self, i, j, direction, base):
        """Draw a quadratic-Bezier arrow between signs i and j (1-based).

        The control point is offset perpendicular to the chord, toward the scene
        centre, so arrows bow through the central void (magnitude scales with
        chord length). Arrowheads sit at the target end(s).
        """
        scene = self.aspect_si_view.scene
        ci = self._cell_center(i - 1)
        cj = self._cell_center(j - 1)
        center = QPointF(self.aspect_si_view.chart_size / 2.0,
                         self.aspect_si_view.chart_size / 2.0)

        mid = QPointF((ci.x() + cj.x()) / 2.0, (ci.y() + cj.y()) / 2.0)
        chord = QPointF(cj.x() - ci.x(), cj.y() - ci.y())
        clen = hypot(chord.x(), chord.y()) or 1.0
        # perpendicular unit vector, oriented toward the scene centre
        px, py = -chord.y() / clen, chord.x() / clen
        to_c = QPointF(center.x() - mid.x(), center.y() - mid.y())
        if (px * to_c.x() + py * to_c.y()) < 0:
            px, py = -px, -py
        offset = min(clen * 0.28, 320.0)
        ctrl = QPointF(mid.x() + px * offset, mid.y() + py * offset)

        path = QPainterPath(ci)
        path.quadTo(ctrl, cj)
        curve = scene.addPath(path, QPen(QColor(_CRIMSON), 2.5))
        self._tag(curve)

        heads = []
        if direction in ("i2j", "mutual"):
            heads.append(self._add_head(scene, cj, ctrl))
        if direction in ("j2i", "mutual"):
            heads.append(self._add_head(scene, ci, ctrl))

        arr = {"dir": direction, "base": base, "curve": curve,
               "heads": heads, "items": [curve, *heads]}
        self._style_arrow(arr, base)
        return arr

    def _add_head(self, scene, tip, from_pt):
        """Filled triangular arrowhead at `tip`, pointing away from `from_pt`."""
        dx, dy = tip.x() - from_pt.x(), tip.y() - from_pt.y()
        L = hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L                 # unit travel direction into tip
        hl, hw = 52.0, 28.0                     # ~13px at typical fit scale
        bx, by = tip.x() - ux * hl, tip.y() - uy * hl
        p1 = QPointF(bx - uy * hw, by + ux * hw)
        p2 = QPointF(bx + uy * hw, by - ux * hw)
        head = scene.addPolygon(QPolygonF([tip, p1, p2]),
                                QPen(QColor(_CRIMSON), 1), QBrush(QColor(_CRIMSON)))
        self._tag(head)
        return head

    def _tag(self, item):
        item.setData(Qt.ItemDataRole.UserRole, _ARROW_TAG)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setZValue(78)

    def _style_arrow(self, arr, state):
        color, alpha, width, z = _ARROW_STYLES[state]
        hidden = (state == "hidden")
        for item in arr["items"]:
            item.setVisible(not hidden)
        if hidden:
            return
        col = QColor(color)
        col.setAlpha(alpha)
        pen = QPen(col, width)
        pen.setCosmetic(True)
        arr["curve"].setPen(pen)
        arr["curve"].setZValue(z)
        head_pen = QPen(col, 1)
        head_pen.setCosmetic(True)
        for h in arr["heads"]:
            h.setPen(head_pen)
            h.setBrush(QBrush(col))
            h.setZValue(z)

    # ================================================================== #
    # Hover                                                              #
    # ================================================================== #
    def _create_aspect_hover_zones(self):
        """Create hover zones on the aspect SI: 12 sign cells + 4 center-void cells.

        The center 2×2 void (rows 1-2, cols 1-2) has no sign cells. Without
        hover zones there, moving the pointer from a sign cell into the void
        never fires hover-leave, leaving the last sign's arrows stuck in the
        highlighted state (all others dimmed). The void zones use index -1 so
        _on_aspect_hover clears the highlight instead of selecting a sign.
        """
        cs = self.aspect_si_view.cell_size
        scene = self.aspect_si_view.scene
        for (row, col), zodiac_idx in SouthIndianView.ZODIAC_POSITIONS.items():
            hz = HoverZoneItem(col * cs, row * cs, cs, cs,
                               zodiac_idx, self._aspect_hover_signal)
            hz.setZValue(50)
            scene.addItem(hz)
        for r in range(1, 3):
            for c in range(1, 3):
                hz = HoverZoneItem(c * cs, r * cs, cs, cs,
                                   -1, self._aspect_hover_signal)
                hz.setZValue(50)
                scene.addItem(hz)

    def _on_aspect_hover(self, zodiac_idx):
        """A sign cell was hovered: highlight its arrows + related body zones."""
        if self._rendering:
            return
        if zodiac_idx < 0:
            self._on_aspect_hover_leave()
            return
        self._hovered_sign = zodiac_idx
        s = zodiac_idx + 1  # 1-based
        related = set()
        for key, arr in self._arrows.items():
            if s in key:
                self._style_arrow(arr, "hovered")
                other = key[1] if key[0] == s else key[0]
                related.add(other - 1)   # back to 0-based for the body view
            else:
                self._style_arrow(arr, "dimmed")
        self.body_graph_view.highlight_zones(zodiac_idx, list(related))

    def _on_aspect_hover_leave(self):
        """Pointer left the aspect viewport: hide all arrows + clear body zones."""
        if self._rendering:
            return  # never touch arrow items mid-render (may be being rebuilt)
        self._hovered_sign = None
        for arr in self._arrows.values():
            self._style_arrow(arr, "hidden")
        self.body_graph_view.clear_highlights()

    def eventFilter(self, obj, event):
        # HoverSignal.hover_leave is never emitted by the item; detect the
        # pointer leaving the viewport instead (grounding: no existing leaveEvent).
        if obj is self.aspect_si_view.viewport() and event.type() == QEvent.Type.Leave:
            self._on_aspect_hover_leave()
        return super().eventFilter(obj, event)

    # ================================================================== #
    # Settings reaction (W3c): redraw arrows on aspect-system change      #
    # ================================================================== #
    def _on_aspect_system_changed(self, key, value):
        """on_changed callback for chart.rashi_aspect_system.

        Fires on three paths: (a) direct set("chart.rashi_aspect_system", val),
        (b) reset_to_defaults(None) → ("*", None), (c) reset_to_defaults("chart")
        → ("chart", {...}).  For (b)/(c) the value is None or the entire section
        dict — resolve to the actual current setting value so the arrows update.
        The broad "chart" prefix registration also fires on unrelated chart.*
        changes (view_type, outer_planets, etc.) — skip those.
        When the panel is HIDDEN, mark _si_dirty so the new system is drawn on the
        next show (codex W2 finding 7).
        """
        if key.startswith("chart.") and key != "chart.rashi_aspect_system":
            return
        if value is None or key in ("*", "chart"):
            value = get_settings().get("chart.rashi_aspect_system") or "quadrant"
        if self._current_chart is None:
            return
        if not self._panel_visible:
            self._si_dirty = True
            return
        with self._render_guard():
            self._compute_and_draw_aspects()
        if self._hovered_sign is not None:
            self._on_aspect_hover(self._hovered_sign)
