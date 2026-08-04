#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Body Graph View Widget (SPEC-BODY-001)
======================================
The 4th chart view (chart_stack index 3). Maps each planet to a body region
based on its Aditya (sign) placement, drawn over an AI-generated luminous
silhouette (arms extended horizontally, Vitruvian / T-pose).

Rendering stack (bottom to top):
  1. Background pixmap (dark or light theme variant), z = -10
  2. 12 element-colored zone overlays over the body anatomy, z = 0..1
  3. Element-colored planet label bars in two columns beside the body, z = 10..12
  4. Leader lines connecting each bar to the centre of its body zone, z = 5

Planet-to-zone mapping uses the chart's native sign index
(get_planet_sign_index), which is automatically correct for the active zodiac
mode because the Chart object is rebuilt when the mode changes
(_set_aditya_mode -> _recalculate_chart). No manual ayanamsa math.

Reuses ClickablePlanetItem from chart_view so double-click opens the same
planet dialog as the other three views. The whole label bar is clickable via
a transparent ClickablePlanetItem overlay (BoundingRectShape hit area).
"""
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPixmap, QImage, QFont, QPainterPath,
)

from core.aditya_data import (
    BODY_ZONE_COORDS, BODY_LABEL_SIDES, ELEMENT_COLORS,
)
from core.aditya_mode import displayed_sign_name
# ClickablePlanetItem + PlanetClickSignal give the same click contract as the
# other views; BACKGROUNDS_PATH / PROJECT_ROOT resolve bundled image assets;
# SouthIndianView carries the canonical PLANET_NAMES / PLANET_ICON_NAMES lists.
from apps.widgets.chart_view import (
    ClickablePlanetItem, PlanetClickSignal, SouthIndianView,
    BACKGROUNDS_PATH, PROJECT_ROOT,
)
from ui.qt_theme import (
    is_light_theme, scaled_area_size, desat_image, get_ui_saturation, desat_hex,
)

# Scene matches the 1920x1920 background silhouette images exactly.
SCENE_SIZE = 1920
# The body silhouette is horizontally centred in the scene.
BODY_CENTER_X = 958

# Label-bar geometry (scene coordinates). Tuned smaller than the first pass so
# the planet text reads cleanly at the default fit-zoom (Phase 5 feedback).
_BAR_W = 300
_BAR_H = 56
_BAR_GAP = 10
_ICON_SIZE = 40
_SIDE_MARGIN = 24
# Font point sizes now come from scaled_area_size() (SPEC-FONT-001) so they
# follow the user's Settings > Font Sizes preference. Former constants:
# _NAME_PT=18 -> 'chart_labels', _ZONE_PT=15 -> 'panel_titles', _SUB_PT=13 -> 'info_text'.

# Outer planets hidden by the F8 toggle.
_OUTER_PLANETS = frozenset({"Uranus", "Neptune", "Pluto"})


class BodyGraphView(QGraphicsView):
    """Planets mapped to body zones by Aditya placement (SPEC-BODY-001)."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Scene — NoIndex BSP avoids the known Qt segfault on frequent
        # add/remove of items (QTBUG-18021), same as SouthIndianView.
        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(self.scene)
        self.setSceneRect(0, 0, SCENE_SIZE, SCENE_SIZE)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Click signal — wired to _show_planet_dialog by core_gui_qt, exactly
        # like chart_view / wheel_view / north_indian_view.
        self.planet_click_signal = PlanetClickSignal()

        # Zoom — relative to the fitInView base set in ensure_visible().
        self.zoom_factor = 1.0
        self.min_zoom = 0.4
        self.max_zoom = 8.0
        self.zoom_step = 1.15
        # Set when ensure_visible() is asked to fit while HIDDEN; the fit is
        # deferred to the next showEvent (see ensure_visible docstring).
        self._needs_fit = False

        # Chart + display flags, stored so refresh_theme() can re-render with
        # the new background variant (M5/M7: refresh_theme is a no-op otherwise).
        self._current_chart = None
        self._use_western = False
        self._aditya_mode = "aditya"
        self._varga_code = None
        # Outer-planet visibility (Uranus/Neptune/Pluto), toggled by F8 — kept
        # in sync with the other views by _toggle_outer_planets.
        self.show_outer_planets = True
        # Birth gender ("Male"/"Female"/"Unknown") chooses the silhouette image.
        # Unknown defaults to the male body.
        self._gender = "Unknown"

        # Planet-icon pixmap cache: (name, size) -> QPixmap | None.
        self._icon_cache = {}

        # SPEC-BODY-002: live references to the zone-overlay QGraphicsItems so
        # highlight_zones()/clear_highlights() can redraw ONLY the zones (not the
        # whole chart) on cross-view hover. Rebuilt every _draw_zone_overlays().
        # Never accessed across a scene.clear() — the update path resets the list
        # instead of removing (items are already destroyed); only the highlight
        # path calls removeItem on known-live items (segfault rule #18).
        self._zone_items = []

    # ------------------------------------------------------------------ #
    # Public contract (matches the other three views)
    # ------------------------------------------------------------------ #
    def update_from_chart(self, chart, use_western_names=False,
                          aditya_mode="aditya", gender=None,
                          varga_code=None, **_kw):
        """Render the body graph from a libaditya Chart object.

        **_kw absorbs extra kwargs that the shared refresh path passes to all
        views (e.g. ayanamsa_offset) — without it the lazy push from
        _toggle_wheel_view would raise TypeError (six-eyes M1).

        `gender` selects the silhouette (Female -> female body, else male). It
        is only updated when provided, so refresh_theme()/F8 re-renders (which
        don't pass it) keep the stored value.
        """
        # Store for refresh_theme() (six-eyes M5/M7).
        self._current_chart = chart
        self._use_western = use_western_names
        self._aditya_mode = aditya_mode
        self._varga_code = varga_code
        if gender is not None:
            self._gender = gender

        self.scene.clear()
        if chart is None:
            return

        self._draw_background()
        self._draw_zone_overlays()
        self._draw_planet_labels(chart)

    def ensure_visible(self):
        """Fit the whole 1920x1920 body into the viewport (six-eyes M2).

        Called by _update_all_chart_views after every update. fitInView sets
        the base transform; wheel zoom scales relative to it.

        HIDDEN-WIDGET GUARD (bug 2026-07-09): fitInView on a hidden view
        computes the transform from stale/collapsed viewport geometry, leaving
        the graph permanently "zoomed-down" when the tab is shown again (e.g. a
        zodiac-mode change made from the Compatibility page re-fits the hidden
        main-tab body graph). When hidden, defer the fit to the next showEvent.
        """
        if not self.isVisible():
            self._needs_fit = True
            return
        self._do_fit()

    def _do_fit(self):
        self._needs_fit = False
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_factor = 1.0
        self.scene.update()
        self.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_fit:
            # Defer one event-loop turn so the viewport geometry is settled.
            QTimer.singleShot(0, self._deferred_fit)

    def _deferred_fit(self):
        try:
            self._do_fit()
        except RuntimeError:
            pass   # view torn down before the queued fit fired (codex review)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the base fit on live resizes, but never clobber a manual wheel
        # zoom (zoom_factor != 1.0 means the user zoomed on purpose).
        if (self.isVisible() and self.zoom_factor == 1.0
                and self._current_chart is not None):
            self._do_fit()

    def clear_icon_cache(self):
        """Drop cached planet pixmaps so they re-render at the current UI
        saturation (SPEC-SAT-001 WI-4). Hasattr-guarded for safety."""
        if hasattr(self, "_icon_cache"):
            self._icon_cache.clear()

    def refresh_theme(self):
        """Swap the dark/light background by re-rendering (novel pattern).

        Other views only repaint colours; the body graph must reload a
        different pixmap, so it re-runs the full render with the stored chart
        and flags.
        """
        if self._current_chart is not None:
            self.update_from_chart(
                self._current_chart,
                use_western_names=self._use_western,
                aditya_mode=self._aditya_mode,
                varga_code=self._varga_code,
            )

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def _draw_background(self):
        """Load the gender-/theme-appropriate silhouette behind everything.

        Female charts use the female body image; everything else (including
        Unknown) uses the male body. Falls back to the male image if a female
        variant is missing.
        """
        theme = "light" if is_light_theme() else "dark"
        # Exact-token match (not startswith) so free-form gender strings from
        # TOML imports (e.g. "fluid") don't wrongly pick the female silhouette.
        # CHTK/chart_factory normalize to Male/Female/Unknown; "f" covers a
        # bare single-letter value.
        is_female = str(self._gender).strip().lower() in ("female", "f")
        candidates = []
        if is_female:
            candidates.append(f"body_graph_female_{theme}.webp")
        candidates.append(f"body_graph_{theme}.webp")  # male / fallback

        for name in candidates:
            path = BACKGROUNDS_PATH / name
            if not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            item = self.scene.addPixmap(pixmap)
            item.setZValue(-10)
            item.setOffset(0, 0)
            return

    def _draw_zone_overlays(self, alpha_overrides=None):
        """Draw the body-zone markers.

        Most zones are simple element-bordered rectangles. The pelvic trio
        uses bespoke shapes (Phase 5 feedback) because rectangles read poorly
        there and they map to distinct anatomical ideas:
          - Tvasta (6, Libra): a thick central balance/symmetry beam.
          - Vishnu (7): a small focal circle between the legs (intimate area).
          - Amzu  (8): the buttocks, a faint dashed ellipse drawn to read as
            sitting BEHIND the body.

        SPEC-BODY-002: `alpha_overrides` is an optional {zodiac_idx: alpha}
        mapping used by highlight_zones() for cross-view hover sync. When None
        (the default), every zone uses its own hardcoded alpha and the render is
        byte-identical to SPEC-BODY-001. A per-zone alpha of None inside the map
        also falls back to that zone's default.
        """
        # Reset the tracking list. On the update path scene.clear() has already
        # destroyed the prior items (do NOT removeItem them); on the highlight
        # path _redraw_zones() already removed them. Either way, start empty.
        self._zone_items = []
        for idx in range(12):
            color = QColor(desat_hex(ELEMENT_COLORS[idx]))  # SPEC-SAT-001
            a = None if alpha_overrides is None else alpha_overrides.get(idx)
            if idx == 6:
                self._draw_tvasta_axis(idx, color, alpha=a)
            elif idx == 7:
                self._draw_vishnu_circle(idx, color, alpha=a)
            elif idx == 8:
                self._draw_amzu_behind(idx, color, alpha=a)
            elif idx == 9:
                # Bhaga starts up at Tvasta and overlaps the pelvic markers, so
                # its label drops below the Vishnu circle into the clear thigh.
                self._draw_zone_rect(idx, color, label_y=BODY_ZONE_COORDS[9][1] + 160, alpha=a)
            else:
                self._draw_zone_rect(idx, color, alpha=a)

    def _draw_zone_rect(self, idx, color, label_y=None, alpha=None):
        """Standard element-bordered rectangle zone with a centred label.

        `label_y` overrides the default label position (top of the rect) for
        zones whose top overlaps other markers (e.g. Bhaga over the pelvis).
        `alpha` (SPEC-BODY-002) overrides the fill alpha; None keeps 38.
        """
        x, y, w, h = BODY_ZONE_COORDS[idx]
        fill = QColor(color)
        fill.setAlpha(38 if alpha is None else alpha)  # subtle — silhouette shows through
        rect = self.scene.addRect(x, y, w, h, QPen(color, 2), QBrush(fill))
        rect.setZValue(0)
        self._zone_items.append(rect)
        self._zone_label(idx, color, label_y if label_y is not None else y + 2)

    def _zone_label(self, idx, color, y, cx=None, text=None):
        """Draw a zone name centred (default on the body axis) with a dark
        rounded backing so the element colour reads on the bright silhouette.

        `text` overrides the default Aditya name (e.g. to append "(behind)").
        """
        if cx is None:
            cx = BODY_CENTER_X
        default_name = displayed_sign_name(
            idx, self._aditya_mode, self._use_western)
        label = self.scene.addText(text if text is not None else default_name)
        label.setDefaultTextColor(color)
        f = QFont()
        f.setPointSize(scaled_area_size('panel_titles'))
        f.setBold(True)
        label.setFont(f)
        lw = label.boundingRect().width()
        lh = label.boundingRect().height()
        lx = cx - lw / 2.0
        back_path = QPainterPath()
        back_path.addRoundedRect(QRectF(lx - 8, y, lw + 16, lh), 8, 8)
        backing = self.scene.addPath(
            back_path, QPen(Qt.PenStyle.NoPen), QBrush(QColor(0, 0, 0, 120)))
        backing.setZValue(0.9)
        label.setPos(lx, y)
        label.setZValue(1)
        self._zone_items.append(backing)
        self._zone_items.append(label)

    def _draw_tvasta_axis(self, idx, color, alpha=None):
        """Tvasta (Libra): a thick horizontal balance beam through the body's
        centre, with a symmetry dot — the equilibrium/middle point.

        This zone is normally OPAQUE (no fill alpha). SPEC-BODY-002: when
        `alpha` is given (highlight sync), it is applied to both the beam pen and
        the dot pen+brush so the zone can dim/brighten like the others. None =
        fully opaque, identical to SPEC-BODY-001.
        """
        x, y, w, h = BODY_ZONE_COORDS[idx]
        cy = y + h / 2.0
        stroke = QColor(color)
        if alpha is not None:
            stroke.setAlpha(alpha)
        beam = self.scene.addLine(x, cy, x + w, cy, QPen(stroke, 7))
        beam.setZValue(0.5)
        r = 11  # central symmetry marker
        dot = self.scene.addEllipse(BODY_CENTER_X - r, cy - r, 2 * r, 2 * r,
                                    QPen(stroke, 2), QBrush(stroke))
        dot.setZValue(0.6)
        self._zone_items.append(beam)
        self._zone_items.append(dot)
        self._zone_label(idx, color, y - 26)  # label sits just above the beam

    def _draw_vishnu_circle(self, idx, color, alpha=None):
        """Vishnu: a small solid focal circle between the legs (intimate area).

        SPEC-BODY-002: `alpha` overrides the fill alpha for highlight sync;
        None keeps the default 85. The 2.5px border stays opaque (unchanged).
        """
        x, y, w, h = BODY_ZONE_COORDS[idx]
        fill = QColor(color)
        fill.setAlpha(85 if alpha is None else alpha)
        circ = self.scene.addEllipse(x, y, w, h, QPen(color, 2.5), QBrush(fill))
        circ.setZValue(0.7)
        self._zone_items.append(circ)
        # Label to the RIGHT of the circle so the central axis just below it
        # stays clear for the Bhaga (thighs) zone label.
        self._zone_label(idx, color, y + h / 2.0 - 11, cx=x + w + 58)

    def _draw_amzu_behind(self, idx, color, alpha=None):
        """Amzu (buttocks): optical illusion of depth — the zone appears to sit
        BEHIND the body using two layers:

        1. A wide dashed ellipse at z=-1 (behind other zone markers).
        2. Left and right "peek" crescents that are slightly brighter, giving
           the illusion that only the buttock edges are visible from the sides
           while the centre is hidden behind the torso.

        SPEC-BODY-002: `alpha` (highlight sync) scales all three layer alphas
        proportionally; None keeps the 55/45/70 defaults.
        """
        x, y, w, h = BODY_ZONE_COORDS[idx]
        cy = y + h / 2.0

        # SPEC-BODY-002: this zone has THREE alphas (outline 55 / peek-fill 45 /
        # peek-pen 70). For highlight sync, scale all three proportionally to the
        # target `alpha` (anchored on the dominant outline=55) so the layered
        # look is preserved. alpha=None keeps the exact 55/45/70 defaults.
        if alpha is None:
            outline_a, peekfill_a, peekpen_a = 55, 45, 70
        else:
            scale = alpha / 55.0
            outline_a = max(0, min(255, alpha))
            peekfill_a = max(0, min(255, int(round(45 * scale))))
            peekpen_a = max(0, min(255, int(round(70 * scale))))

        # Layer 1: full dashed ellipse outline (faint, behind everything).
        outline_color = QColor(color)
        outline_color.setAlpha(outline_a)
        pen = QPen(outline_color, 2.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        ell_outline = self.scene.addEllipse(x, y, w, h, pen, QBrush(Qt.BrushStyle.NoBrush))
        ell_outline.setZValue(-1)

        # Layer 2: left and right "peek" crescents — the visible buttock edges.
        peek_w = w * 0.22
        peek_h = h * 0.85
        peek_y = cy - peek_h / 2.0

        peek_fill = QColor(color)
        peek_fill.setAlpha(peekfill_a)
        peek_pen = QPen(QColor(color.red(), color.green(), color.blue(), peekpen_a), 1.5)
        peek_pen.setStyle(Qt.PenStyle.DashDotLine)

        left_peek = self.scene.addEllipse(
            x - peek_w * 0.15, peek_y, peek_w, peek_h,
            peek_pen, QBrush(peek_fill))
        left_peek.setZValue(-0.8)

        right_peek = self.scene.addEllipse(
            x + w - peek_w * 0.85, peek_y, peek_w, peek_h,
            peek_pen, QBrush(peek_fill))
        right_peek.setZValue(-0.8)

        self._zone_items.append(ell_outline)
        self._zone_items.append(left_peek)
        self._zone_items.append(right_peek)

        # Label offset left to avoid collision with Tvasta/Vishnu labels.
        # Mode-aware name (FIX 1): in Tropical/Sidereal/Western-names modes this
        # zone shows its displayed sign name, not the hardcoded Aditya name.
        amzu_name = displayed_sign_name(idx, self._aditya_mode, self._use_western)
        self._zone_label(idx, color, y + h / 2.0 - 11, cx=x + 78,
                         text=f"{amzu_name} (behind)")

    def _draw_planet_labels(self, chart):
        """Place element-coloured label bars beside the body with leader lines.

        Bars are laid out per side (left/right column) with collision
        resolution: each bar prefers to sit at its zone centre, but bars are
        pushed apart so no two overlap. This handles both many planets in one
        zone AND several planets across the clustered pelvic zones
        (Tvasta/Vishnu/Amzu), which previously stacked on top of each other.
        """
        # Group present planets by their (mode-correct) sign/zone index.
        zones = {}  # zone_idx -> [(name, planet_obj), ...]
        for name, obj, sign_idx in self._iter_chart_planets(chart):
            zones.setdefault(sign_idx, []).append((name, obj))

        left, right = [], []
        for zone_idx, planets in zones.items():
            zx, zy, zw, zh = BODY_ZONE_COORDS[zone_idx]
            zone_cy = zy + zh / 2.0
            side = BODY_LABEL_SIDES[zone_idx]
            if side == "left":
                bar_x = _SIDE_MARGIN
                line_start_x = bar_x + _BAR_W      # bar's inner (right) edge
                zone_anchor_x = zx                 # connect to body's left edge
                bucket = left
            else:
                bar_x = SCENE_SIZE - _BAR_W - _SIDE_MARGIN
                line_start_x = bar_x               # bar's inner (left) edge
                zone_anchor_x = zx + zw            # connect to body's right edge
                bucket = right

            n = len(planets)
            block = n * _BAR_H + (n - 1) * _BAR_GAP
            for i, (name, obj) in enumerate(planets):
                bucket.append({
                    "name": name, "obj": obj, "zone": zone_idx,
                    "pref_y": zone_cy - block / 2.0 + i * (_BAR_H + _BAR_GAP),
                    "zone_cy": zone_cy, "bar_x": bar_x,
                    "line_start_x": line_start_x, "zone_anchor_x": zone_anchor_x,
                })

        self._place_column(left)
        self._place_column(right)

    def _place_column(self, specs):
        """Resolve vertical overlaps within one side column, then draw.

        Bars are sorted by preferred y and pushed down so consecutive bars
        never overlap, then the whole column is clamped to the scene: shifted
        DOWN if it underflows the top margin (a tall stack in a high zone like
        Dhata) and UP if it overflows the bottom. Both ends are bounded so a
        bar can never render off-scene.
        """
        if not specs:
            return
        specs.sort(key=lambda s: s["pref_y"])
        prev_bottom = None
        for s in specs:
            y = s["pref_y"]
            if prev_bottom is not None and y < prev_bottom + _BAR_GAP:
                y = prev_bottom + _BAR_GAP
            s["y"] = y
            prev_bottom = y + _BAR_H
        # Clamp the top first so specs[0]['y'] >= _BAR_GAP.
        top_under = _BAR_GAP - specs[0]["y"]
        if top_under > 0:
            for s in specs:
                s["y"] += top_under
        # Then shift up if the column overflows the bottom, but never so far
        # that the top crosses the margin (shift is guaranteed >= 0 now).
        overflow = (specs[-1]["y"] + _BAR_H + _BAR_GAP) - SCENE_SIZE
        if overflow > 0:
            shift = min(overflow, specs[0]["y"] - _BAR_GAP)
            if shift > 0:
                for s in specs:
                    s["y"] -= shift

        for s in specs:
            color = QColor(desat_hex(ELEMENT_COLORS[s["zone"]]))  # SPEC-SAT-001
            self._draw_one_bar(s["name"], s["obj"], s["zone"], color,
                               s["bar_x"], s["y"], s["line_start_x"],
                               s["zone_anchor_x"], s["zone_cy"])

    def _draw_one_bar(self, name, obj, zone_idx, color,
                      bar_x, bar_y, line_start_x, zone_anchor_x, zone_cy):
        """Draw a single planet label bar + icon + text + leader line."""
        cy = bar_y + _BAR_H / 2.0

        # Leader line first so it sits under the bar (z = 5).
        line_color = QColor(color)
        line_color.setAlpha(140)
        line = self.scene.addLine(line_start_x, cy, zone_anchor_x, zone_cy,
                                   QPen(line_color, 2.0))
        line.setZValue(5)

        # Bar background — element colour, rounded "pill". Slightly translucent
        # so it reads as a tint rather than a hard block (Phase 5 feedback).
        bar_fill = QColor(color)
        bar_fill.setAlpha(205)
        bar_path = QPainterPath()
        bar_path.addRoundedRect(QRectF(bar_x, bar_y, _BAR_W, _BAR_H), 14, 14)
        bar = self.scene.addPath(bar_path, QPen(QColor(color), 1.5), QBrush(bar_fill))
        bar.setZValue(10)

        # Planet icon (visible, non-interactive — the overlay handles clicks).
        pixmap = self._planet_pixmap(name, _ICON_SIZE)
        if pixmap is not None and not pixmap.isNull():
            icon = self.scene.addPixmap(pixmap)
            icon.setPos(bar_x + 8, cy - pixmap.height() / 2.0)
            icon.setZValue(11)

        text_x = bar_x + 8 + _ICON_SIZE + 8

        # Line 1: planet name (bold).
        name_item = self.scene.addText(name)
        name_item.setDefaultTextColor(QColor(Qt.GlobalColor.white))
        nf = QFont()
        nf.setPointSize(scaled_area_size('chart_labels'))
        nf.setBold(True)
        name_item.setFont(nf)
        name_item.setPos(text_x, bar_y + 3)
        name_item.setZValue(11)

        # Line 2: "Aditya-N  DD°MM'".
        deg, mins, retro = self._planet_pos(obj)
        sign_label = displayed_sign_name(
            zone_idx, self._aditya_mode, self._use_western)
        sub = f"{sign_label}-{zone_idx + 1}  {deg}°{mins:02d}'"
        if retro:
            sub += "  ℞"  # retrograde mark
        sub_item = self.scene.addText(sub)
        sub_item.setDefaultTextColor(QColor(Qt.GlobalColor.white))
        sf = QFont()
        sf.setPointSize(scaled_area_size('info_text'))
        sub_item.setFont(sf)
        sub_item.setPos(text_x, bar_y + _BAR_H - 24)
        sub_item.setZValue(11)

        # Transparent full-bar hit target (six-eyes #16): the whole bar opens
        # the planet dialog, not just the icon. BoundingRectShape lets the
        # view's mouseDoubleClickEvent detect it via items(pos).
        hit = QPixmap(int(_BAR_W), int(_BAR_H))
        hit.fill(QColor(0, 0, 0, 0))
        click_item = ClickablePlanetItem(
            hit, name, self._planet_click_dict(obj, zone_idx),
            self.planet_click_signal,
        )
        click_item.setPos(bar_x, bar_y)
        click_item.setZValue(12)
        self.scene.addItem(click_item)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _iter_chart_planets(self, chart):
        """Yield (name, planet_obj, sign_index) for planets present in chart.

        Iterates the canonical PLANET_NAMES and skips any planet the chart
        lacks (e.g. outer planets in older data). sign() - 1 is the native,
        mode-correct zone index.
        """
        try:
            vc = self._varga_code
            source = chart.varga(vc) if vc and vc != 1 else chart.rashi()
            planets = source.planets()
        except Exception:
            return
        for name in SouthIndianView.PLANET_NAMES:
            # Respect the F8 outer-planet toggle, like the other views.
            if not self.show_outer_planets and name in _OUTER_PLANETS:
                continue
            try:
                obj = planets[name]
            except (KeyError, IndexError, TypeError, AttributeError):
                obj = None
            if obj is None:
                continue
            try:
                sign_raw = obj.sign()
            except Exception:
                continue
            # Explicit bounds check (not `% 12`): a bad-but-non-raising value
            # like 0 or 13 would otherwise be masked into a plausible zone.
            if not isinstance(sign_raw, int) or not (1 <= sign_raw <= 12):
                continue
            yield name, obj, sign_raw - 1

    def _planet_pos(self, obj):
        """Return (deg, minutes, is_retrograde) within the sign."""
        try:
            if self._varga_code and self._varga_code != 1:
                risl = obj.amsha_raw_in_sign_longitude()
            else:
                risl = obj.real_in_sign_longitude()
            deg = int(risl)
            mins = int((risl % 1) * 60)
        except Exception:
            deg, mins = 0, 0
        try:
            retro = bool(obj.retrograde())
        except Exception:
            retro = False
        return deg, mins, retro

    def _planet_click_dict(self, obj, zone_idx):
        """Build the planet_info dict consumed by _show_planet_dialog.

        Mirrors SouthIndianView._planet_to_click_dict so the planet dialog
        receives the same shape from every view.
        """
        deg, mins, retro = self._planet_pos(obj)
        try:
            sign_name = obj.sign_name()
        except Exception:
            sign_name = displayed_sign_name(
                zone_idx, self._aditya_mode, self._use_western)
        try:
            dec = obj.ecliptic_longitude()
        except Exception:
            dec = 0.0
        return {
            "sign": sign_name,
            "aditya_zodiac": sign_name,
            "sign_index": zone_idx,
            "degrees": deg,
            "minutes": mins,
            "decimal_degrees": dec,
            "is_retrograde": retro,
        }

    def _planet_pixmap(self, planet_name, size):
        """Load (and cache) a planet icon at the given size (default variation)."""
        key = (planet_name, size, get_ui_saturation())
        if key in self._icon_cache:
            return self._icon_cache[key]
        filename = SouthIndianView.PLANET_ICON_NAMES.get(
            planet_name, planet_name.lower())
        path = PROJECT_ROOT / "img" / "planets" / f"{filename}.webp"
        pixmap = None
        if path.exists():
            img = QImage(str(path))
            if not img.isNull():
                img = img.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                img = desat_image(img)
                pixmap = QPixmap.fromImage(img)
        self._icon_cache[key] = pixmap
        return pixmap

    # ------------------------------------------------------------------ #
    # Interaction (same patterns as SouthIndianView)
    # ------------------------------------------------------------------ #
    def mouseDoubleClickEvent(self, event):
        """Open the planet dialog when a label bar is double-clicked."""
        if event.button() == Qt.MouseButton.LeftButton:
            for item in self.items(event.pos()):
                if isinstance(item, ClickablePlanetItem):
                    self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    item.signal_emitter.clicked.emit(
                        item.planet_name, item.planet_info)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        """Pointer cursor when hovering a clickable bar."""
        super().mouseMoveEvent(event)
        found = any(isinstance(it, ClickablePlanetItem)
                    for it in self.items(event.pos()))
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if found
            else Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        """Cursor-anchored exponential zoom (mirror of SouthIndianView)."""
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
        new_zoom = self.zoom_factor * step if steps > 0 else self.zoom_factor / step
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

    def _zoom_by(self, step):
        """Scale by `step` relative to the current zoom, within bounds.

        This view cannot use the resetTransform()/scale(zoom_factor) idiom the
        other three share. There, zoom_factor is the absolute scene scale. Here
        fitInView owns the base transform (see ensure_visible) and zoom_factor
        is a multiplier ON TOP of it, so 1.0 means "fitted", not "1:1".
        resetTransform() would discard the fit and snap the body to raw scene
        scale. Apply the delta instead, exactly as wheelEvent does.
        """
        new_zoom = max(self.min_zoom,
                       min(self.max_zoom, self.zoom_factor * step))
        if new_zoom == self.zoom_factor:
            return
        factor = new_zoom / self.zoom_factor
        self.zoom_factor = new_zoom
        self.scale(factor, factor)

    def zoom_in(self):
        """Zoom in by one step."""
        self._zoom_by(self.zoom_step)

    def zoom_out(self):
        """Zoom out by one step."""
        self._zoom_by(1.0 / self.zoom_step)

    def reset_zoom(self):
        """Back to the fitted view, the state ensure_visible() produces."""
        self._do_fit()

    def keyPressEvent(self, event):
        """Keyboard zoom shortcuts: +/= zoom in, - zoom out, 0 reset.

        Parity with chart_view, wheel_view, north_indian_view and
        south_indian_vector_view, which have carried these since they were
        written. This view had the focus policy and the wheel zoom but never
        the keys, so the keyboard silently did nothing on one view out of four.
        """
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

    # ------------------------------------------------------------------ #
    # SPEC-BODY-002: cross-view hover highlighting                        #
    # ------------------------------------------------------------------ #
    def _remove_zone_items(self):
        """Remove the currently-drawn zone overlay items from the scene.

        Only called on the highlight path, where the items were created in the
        most recent _draw_zone_overlays() and are known-live. Guarded against the
        'wrapped C/C++ object deleted' race (segfault rule #18) just in case a
        scene.clear() slipped in between.
        """
        for it in getattr(self, "_zone_items", []):
            try:
                self.scene.removeItem(it)
            except (RuntimeError, ValueError):
                pass  # already destroyed — nothing to remove
        self._zone_items = []

    def _redraw_zones(self, alpha_overrides=None):
        """Redraw ONLY the zone overlays (not background/planets) with the given
        per-zone alpha map. No-op when no chart is loaded."""
        if self._current_chart is None:
            return
        self._remove_zone_items()
        self._draw_zone_overlays(alpha_overrides=alpha_overrides)
        self.scene.update()
        self.viewport().update()

    def highlight_zones(self, primary_index, related_indices):
        """Highlight body zones for cross-view hover sync (SPEC-BODY-002).

        primary_index: 0-based zodiac index of the hovered sign (brightest).
        related_indices: iterable of 0-based indices that aspect / are aspected
                         by the hovered sign (medium highlight).
        Uninvolved zones dim. Alphas: primary=120, related=80, uninvolved=15.
        Redraws zones via _draw_zone_overlays with per-zone alpha overrides.
        """
        if type(primary_index) is not int or not (0 <= primary_index < 12):
            return  # defensive: caller passes a valid 0-based int zodiac index
        related = {i for i in (related_indices or []) if i != primary_index}
        overrides = {}
        for idx in range(12):
            if idx == primary_index:
                overrides[idx] = 120
            elif idx in related:
                overrides[idx] = 80
            else:
                overrides[idx] = 15
        self._redraw_zones(alpha_overrides=overrides)

    def clear_highlights(self):
        """Restore all zones to their default alpha (redraw with no overrides)."""
        self._redraw_zones(alpha_overrides=None)
