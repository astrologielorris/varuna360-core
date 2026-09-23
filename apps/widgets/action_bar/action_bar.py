"""SPEC-BAR-001 — ChartActionBar assembly + the flag-gated construction path.

`create_action_bar(gui)` is the v2 counterpart of
`chart_title_widget.create_chart_title_widget` behind `ui.action_bar_v2`:
it builds the whole bar and assigns EVERY legacy attribute name
(INV-5 census: transit_btn, wheel_btn, cards_btn, open_in_kala_btn,
chart_info_btn, chart_title_label, chart_close_button, overlay_chip,
overlay_chip_view, overlay_chip_clear, now_btn,
add_chart_btn, search_btn, time_adjust_btn, human_design_btn, aditya_btn,
dual_rim_btn, tropical_btn, chart_title_widget) plus the new sidereal_btn,
connecting the same gui handlers (and context menus, drop targets) the old
construction connects. cards_btn (D-23(d)) is the TINT_GOLD Cards toggle.

Layout (mockup #track, logical px at fs 1.0): side pad 9; track gap 8; group
margins 2; group gap 6; D-1 rev2: the title well is uncapped and absorbs ALL
surplus width (mockup .title flex:1 with the 560*fs max-width lifted), so the
clusters always hug the bar ends — no slack ever reaches the edges.

Handlers connect through `_maybe_connect` so the capture harness can build
the bar against a stub gui; on the real gui every handler exists.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui.qt_theme import bar_tokens

from . import paint_controls, paint_surfaces
from .bar_types import BarMetrics, Role, SegSpec, effective_bar_fs
from .clusters import HairlineSep, SegmentCluster, ZodiacTray
from .segment_button import SegmentButton
from .overlay_chip import OverlayChip
from .title_well import (BarTextLabel, CloseGlyphButton, ElidedPillButton,
                         TitleWell)

# D-23(d): the F2 view cycle is now the FOUR-view ring 0 South -> 1 Wheel ->
# 2 North -> 3 Body -> 0. CARDS (index 4) LEFT the cycle and became its own
# TINT_GOLD button (Alt+K); index 4 is reachable only by that button/shortcut.
# _NEXT_VIEW_LABEL names the view the cycler shows NEXT from a non-Cards view.
# Keys/values track the F2 ring (state.chart_state.F2_RING_INDICES), currently
# [0,1,2,3,6]: South→Wheel→North→Body→Nakshatra→South. When the ring changes,
# update these two maps (td-bu8s BUG1: index 6 was missing → Nakshatra fell
# through to the "WHEEL" default, and Body wrongly said "SOUTH").
_NEXT_VIEW_LABEL = {0: "WHEEL", 1: "NORTH", 2: "BODY", 3: "NAKSHATRA", 6: "SOUTH"}
# When Cards (index 4) is active, F2 returns to the REMEMBERED non-Cards view,
# so the cycler label names that view's OWN name, not its successor (Sol r3
# BLOCKER: running the remembered index through _NEXT_VIEW_LABEL mislabels it).
_OWN_VIEW_LABEL = {0: "SOUTH", 1: "WHEEL", 2: "NORTH", 3: "BODY", 6: "NAKSHATRA"}
_NO_CHART_REASON = "No chart loaded"             # Dm3-39 (D-12)


class ChartActionBar(QWidget):
    """The 40x fs bar body; paints the vibrancy gradient chrome.

    ``cluster_widgets`` (set by create_action_bar) are the four .seg clusters
    whose CSS ``var(--drop)`` outer shadow falls on BAR rows above/below their
    boxes — a child cannot paint outside its rect (INV-2), so the bar lays
    those bands down in its own paint pass.
    """

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.cluster_widgets: list = []
        self.layout_controller = None            # set by create_action_bar
        self._min_hint_w = 1
        self._gui = None                         # set by bind_state (M3)
        self._bound = False
        self._pill = None                        # set by create_action_bar
        self._meta_label = None
        self.setFixedHeight(metrics.bar_h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def refresh_scale(self, factor: float):
        """Rebox the existing controls, preserving their connections and state.

        ``factor`` is the Display Scale; the action_buttons font-area ratio is
        folded in here (td-l0jfa), so a Font Sizes change that leaves the scale
        untouched still yields new metrics and reboxes the bar."""
        metrics = BarMetrics(fs=effective_bar_fs(factor))
        if metrics == self._m:
            return
        self.snap_motion()
        self._m = metrics
        # Update all measured surfaces before the controller chooses a tier.
        for widget in self.findChildren(QWidget):
            setter = getattr(widget, "set_metrics", None)
            if callable(setter):
                setter(metrics)
        for group in self._scale_groups:
            group.layout().setSpacing(metrics.grp_gap)
        self.layout().setContentsMargins(metrics.side_pad, 0, metrics.side_pad, 0)
        self.layout().setSpacing(metrics.track_gap)
        self.setFixedHeight(metrics.bar_h)
        self.layout_controller.set_metrics(metrics)
        self.updateGeometry()
        self.update()

    # D-22a: the d0 fixed-width children would otherwise pin the WINDOW
    # minimum (measured: resize(400) leaves it at 1483px) and no denser tier
    # is ever reachable. The bar declares the d5 floor instead; overflow past
    # d5 clips, like the mockup's #track{overflow:hidden}.
    def set_min_hint_width(self, w: int):
        if w != self._min_hint_w:
            self._min_hint_w = max(1, int(w))
            self.updateGeometry()

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._min_hint_w, self._m.bar_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ov = getattr(self, "focus_overlay", None)
        if ov is not None:
            ov.setGeometry(self.rect())        # Dm4-34: bar-wide overlay
        if self.layout_controller is not None:
            self.layout_controller.on_bar_resized(event.size().width())

    def _cluster_rects(self):
        out = []
        for w in self.cluster_widgets:
            if w is not None and not w.isHidden():
                g = w.geometry()
                top_left = w.parentWidget().mapTo(self, g.topLeft())
                out.append(QRectF(top_left.x(), top_left.y(),
                                  g.width(), g.height()))
        return out

    @property
    def metrics(self) -> BarMetrics:
        return self._m

    # ----------------------------------------------------- M4 motion hooks
    def snap_motion(self) -> None:
        """Dm4-8/9: cancel every in-flight bar animation and land on the end
        state. Called on theme refresh (a control fade left running across a
        theme flip is exactly the boot-vs-live drift D-6 cut the whole-bar
        crossfade to avoid) and, via each widget's own set_metrics, on any
        metrics change (old-box snapshots must never survive a rebox)."""
        for w in self.findChildren(QWidget):
            fn = getattr(w, "snap_motion", None)
            if callable(fn):
                fn()

    def clear_icon_cache(self) -> None:
        """Theme/saturation fan-out hook (core_gui sweeps findChildren for
        this name): stale glyph pixmaps AND stale mid-fade snapshots both
        carry old-theme RGBA, so they drop together."""
        paint_controls.clear_icon_cache()
        self.snap_motion()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Type.WindowStateChange:
            # Dm4-30 P2 kept as wiring: the NOW dot is static, so sync() is a
            # no-op and there is no loop left to reconcile on minimisation.
            # The call site stays so the dot keeps ONE reconcile entry point
            # if it ever regains state.
            for w in self.findChildren(SegmentButton):
                dot = getattr(w, "_dot", None)
                if dot is not None:
                    dot.sync()

    # ------------------------------------------------- M3 observer contract
    # INV-7: clicks emit intents, observers render. bind_state subscribes;
    # render_state is the ONE render entry — a pure read of live app state
    # into set_lit / set_base_label / setEnabled, idempotent, and it never
    # mutates app state (Dm3-7/9: no dispatch, no settings.set, no
    # recalculation — the D-5 class of bug).

    def bind_state(self, gui) -> None:
        """Subscribe to every state source (design doc §3.6). Idempotent."""
        self._gui = gui
        if self._bound:
            return
        self._bound = True
        state = getattr(gui, "state", None)
        if state is not None and hasattr(state, "connect"):
            state.connect(self._on_chart_state)
        # Dm3-5: the naming-only routes N1/N2 never dispatch — only these
        # two Qt signals see them; without them the `*` accent goes stale.
        for sig_name in ("aditya_mode_changed", "sign_names_changed"):
            sig = getattr(gui, sig_name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(self._on_naming_signal)
        try:
            from managers.settings_manager import get_settings
            get_settings().on_changed("ui.hide_human_design",
                                      self._on_hide_hd_changed)
            # Sol M3 major 1 (second half): the meta's Nakshatra-frame
            # segment reads gui.nakshatra_coords, which a settings change
            # rewrites without any ChartState dispatch.
            get_settings().on_changed("zodiac.nakshatra_coords",
                                      self._on_nakshatra_frame_changed)
            # td-1bpk w1-2: the old dasha.left.ayanamsa_id subscriber here
            # (_on_nakshatra_ayanamsa_changed) is DELETED. Syncing the runtime
            # left ayanamsa on a programmatic settings write now belongs to
            # DashaManager's reconciliation subscriber (SPEC-DSH-002); the action
            # bar no longer writes dasha state.
        except Exception:
            pass                                  # stub gui / harness process
        self.render_state("bind")

    def _on_naming_signal(self, *_):
        self.render_state("naming")

    def _on_nakshatra_frame_changed(self, *_):
        try:
            gui = self._gui
            if gui is not None and hasattr(gui, "_update_title"):
                # gui.nakshatra_coords may lag the settings write until the
                # app's own settings reload — sync it from the source first
                # (the meta must never show a frame the file no longer has).
                try:
                    from managers.settings_manager import get_settings
                    gui.nakshatra_coords = get_settings().get(
                        "zodiac.nakshatra_coords", "neither")
                except Exception:
                    pass
                gui._update_title()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "action bar meta refresh failed", exc_info=True)

    def _on_chart_state(self, reason: str):
        # Dm3-8: ChartState._emit iterates listeners bare — an exception
        # here would break the Beginner clamp and every later subscriber.
        try:
            if reason in ("aditya_mode", "active_chart",
                          "time_adjust_mode", "chart_view_style"):
                self.render_state(reason)
            if reason == "aditya_mode":
                # Sol M3 major 1: the meta line carries the mode label
                # (Dm3-14), so a BARE dispatch (Alt+S, session/memory/CHTK
                # dispatches) must also refresh the title well — the recalc
                # path calls _update_title anyway, but a dispatch with no
                # recalculation would leave the old mode on the meta.
                # _update_title is render-only (pill + window title).
                gui = self._gui
                if gui is not None and hasattr(gui, "_update_title"):
                    gui._update_title()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "action bar render failed for reason %r", reason,
                exc_info=True)

    def _on_hide_hd_changed(self, *_):
        """Dm3-28: prefix-matched notify — always RE-READ the value. The
        callback renders only (Dm3-30: no dispatch, no mode mutation)."""
        try:
            from managers.settings_manager import get_settings
            hidden = get_settings().get_hide_human_design()
        except Exception:
            hidden = False
        if self.layout_controller is not None:
            self.layout_controller.set_hd_visible(not hidden)
        self.render_state("hd_swap")              # dual-role label may flip

    def render_state(self, reason: str = "") -> None:
        gui, ctl = self._gui, self.layout_controller
        if gui is None or ctl is None:
            return
        try:
            self._render_state(gui, ctl)
        except Exception:                         # Dm3-8, same contract
            import logging
            logging.getLogger(__name__).warning(
                "action bar render_state failed (reason %r)", reason,
                exc_info=True)

    def _render_state(self, gui, ctl) -> None:
        state = getattr(gui, "state", None)

        # view-cycler segment (Dm3-10): label names the NEXT view; lit
        # everywhere but South Indian (the old bar's one inactive_style).
        stack = getattr(gui, "chart_stack", None)
        wheel = getattr(gui, "wheel_btn", None)
        if stack is not None and wheel is not None:
            idx = stack.currentIndex()
            if idx == 4:                              # D-23(d): Cards active
                last = getattr(gui, "_last_chart_view_index", 0)
                wheel.set_base_label(_OWN_VIEW_LABEL.get(last, "WHEEL"))
                wheel.set_lit(last != 0)
            else:
                wheel.set_base_label(_NEXT_VIEW_LABEL.get(idx, "WHEEL"))
                wheel.set_lit(idx != 0)

        # D-23(d) / D-c: CARDS is NON-checkable; its lit state is observer-
        # driven ONLY (a checkable button paints `lit OR checked` and could
        # latch visually on).
        cards = getattr(gui, "cards_btn", None)
        if cards is not None and stack is not None:
            cards.set_lit(stack.currentIndex() == 4)

        # D-12 no-chart disabled set (Dm3-16): info, kala, birth, close.
        has_chart = (state is not None
                     and getattr(state, "active_chart", None) is not None)
        for attr in ("chart_info_btn", "open_in_kala_btn", "time_adjust_btn"):
            btn = getattr(gui, attr, None)
            if btn is not None and hasattr(btn, "set_disabled_reason"):
                btn.set_disabled_reason(_NO_CHART_REASON)
                btn.setEnabled(has_chart)
        close = getattr(gui, "chart_close_button", None)
        if close is not None:
            close.setEnabled(has_chart)
            close.setToolTip("Close chart" if has_chart
                             else f"Close chart — {_NO_CHART_REASON}")

        # folded-toggle lit (Dm3-38: without these the overflow menu lies
        # at every tier >= d3 — its rows read btn.lit).
        birth = getattr(gui, "time_adjust_btn", None)
        if birth is not None and state is not None:
            birth.set_lit(bool(getattr(state, "time_adjust_mode", False)))
        hd = getattr(gui, "human_design_btn", None)
        if hd is not None:
            # C7: the HD button is lit in BOTH cycle-active states — on the
            # bodygraph page (chart-stack index 5) and in the -88 Design chart.
            _on_bodygraph = False
            _stack = getattr(gui, "chart_stack", None)
            if _stack is not None:
                try:
                    from state.chart_state import VIEW_STACK_INDEX
                    _on_bodygraph = (_stack.currentIndex()
                                     == VIEW_STACK_INDEX["human_design"])
                except Exception:
                    _on_bodygraph = False
            hd.set_lit(bool(getattr(gui, "is_human_design", False)) or _on_bodygraph)

        # zodiac tray (Dm3-21, the four-branch dual-role rule).
        mode = "aditya"
        if state is not None:
            mode = getattr(state, "aditya_mode", "aditya") or "aditya"
        aditya = getattr(gui, "aditya_btn", None)
        classic = getattr(gui, "tropical_btn", None)
        sidereal = getattr(gui, "sidereal_btn", None)
        if aditya is not None and classic is not None and sidereal is not None:
            # C8: all three pills are always present — no dual-role morph.
            aditya.set_lit(mode == "aditya")
            classic.set_lit(mode == "tropical_classic")
            classic.set_base_label("TROPICAL CLASSIC")
            sidereal.set_lit(mode == "sidereal")
            # D-24 alternate naming (glyph swap + tooltip token): derived
            # AFTER the Beginner clamp (its observer registered before this
            # bar existed), on the lit segment only. alt == "naming differs
            # from native".
            use_w = bool(getattr(gui, "use_western_names", False))
            alt = (use_w == (mode == "aditya"))
            for btn in (aditya, classic, sidereal):
                btn.set_alt_names(alt and btn.lit)

        # modifier capsule label follows the mode (Dm3-23); checked stays a
        # direct write (Dm3-4, INV-5).
        dual = getattr(gui, "dual_rim_btn", None)
        if dual is not None:
            dual.set_base_label("+ TROPICAL" if mode == "aditya"
                                else "+ ADITYA")

    def set_title(self, name, meta: str = "") -> None:
        """Dm3-13: the ONE title entry (writers W2/W9). None -> the no-chart
        pill and an empty meta. A CONTENT change, not a state change
        (Dm3-15): the pill's own updateGeometry and the D-22f meta band
        re-evaluation are its legitimate layout effects."""
        pill, meta_lbl = self._pill, self._meta_label
        if pill is None:
            return
        if name is None or not str(name).strip():
            pill.setText("No Chart Loaded")
            if meta_lbl is not None:
                meta_lbl.setText("")
        else:
            pill.setText(str(name))
            if meta_lbl is not None:
                meta_lbl.setText(meta or "")

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            paint_surfaces.paint_bar(p, QRectF(self.rect()),
                                     self._tokens_fn(), self._m,
                                     self.devicePixelRatioF(),
                                     cluster_rects=self._cluster_rects())
        finally:
            p.end()


def _maybe_connect(signal, gui, attr, *, lam=None):
    """Connect signal -> gui.<attr> (or a lambda) when the gui provides it."""
    if lam is not None:
        signal.connect(lam)
        return
    fn = getattr(gui, attr, None)
    if callable(fn):
        signal.connect(fn)


def _legacy(gui, name, *args):
    """Call a chart_title_widget module-level handler (kept there — the v2 bar
    reuses the behavior verbatim; INV-5). No-op on a stub gui."""
    try:
        from apps.widgets import chart_title_widget as legacy
    except Exception:
        return
    fn = getattr(legacy, name, None)
    if callable(fn):
        fn(gui, *args)


def _group(children, metrics: BarMetrics, right_margin=0, left_margin=0):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(left_margin, 0, right_margin, 0)
    lay.setSpacing(metrics.grp_gap)
    for c in children:
        lay.addWidget(c)
    return w


def create_action_bar(gui, fs: float | None = None,
                      hide_human_design: bool | None = None) -> ChartActionBar:
    # The bar's fixed widths come from measuring its labels in the bundled
    # Inter family. Only the __main__ boot registered it (core_gui_qt
    # :6983), so every PROGRAMMATIC boot (harness drivers, tests embedding
    # the real app) measured in "Sans Serif": clusters came out ~24 px
    # narrower and the edge stretches ballooned into bare dead zones at
    # both ends of the bar (Lorris's live screenshots, 2026-08-24). The
    # bar now guarantees its own measuring font — idempotent and never
    # raises, so double registration from the normal boot is harmless.
    try:
        from pathlib import Path as _Path

        from ui.font_bootstrap import register_bundled_fonts
        register_bundled_fonts(_Path(__file__).resolve().parents[3])
    except Exception:
        pass
    if fs is None:
        from ui.qt_theme import get_scale_factor
        fs = get_scale_factor()
    m = BarMetrics(fs=effective_bar_fs(fs))
    tokens_fn = bar_tokens

    # Dm4-49: ui.reduce_motion drives REDUCED mode. The env var wins
    # (Dm4-44, capture subprocesses), and an un-set preference never writes
    # the mode — a test's set_mode(POSE) must not be clobbered here.
    import os as _os
    if "V360_BAR_MOTION" not in _os.environ:
        try:
            from managers.settings_manager import get_settings
            if get_settings().get_reduce_motion():
                from . import motion as _motion
                _motion.set_mode(_motion.Mode.REDUCED)
        except Exception:
            pass

    def seg(key, labels, icon, role=Role.PLAIN, tip="", checkable=False,
            live=False, plus=False, alt_icon="", name_sets=(),
            dual_tooltip="") -> SegmentButton:
        return SegmentButton(
            SegSpec(key=key, labels=labels, icon=icon, role=role, tooltip=tip,
                    checkable=checkable, live_dot=live, gold_plus=plus,
                    alt_icon=alt_icon, name_sets=name_sets,
                    dual_tooltip=dual_tooltip),
            m, tokens_fn)

    # ---- LEFT --------------------------------------------------------------
    # Transit is the drop target for chart overlays (SPEC-TRN-006) — the
    # TransitDropButton contract rebased onto a segment (Sol M1 major 1).
    from .transit_segment import TransitSegmentButton
    # D-23(e): tooltips name their accelerator; controls with no binding stay
    # plain (no empty parens). Never painted — zero golden impact.
    gui.transit_btn = TransitSegmentButton(
        SegSpec(key="transit", labels=["TRANSIT", "OVERLAY"], icon="transit",
                role=Role.TINT_BLUE, tooltip="Transit / Overlay (F3)",
                checkable=True),
        m, tokens_fn, gui)
    gui.wheel_btn = seg("north", ["NORTH", "SOUTH", "EAST"], "north",
                        Role.TINT_GREEN,
                        "Chart style — North / South / East (F2)")
    # D-23(d): CARDS is the THIRD cell of the view segment — its own
    # NON-checkable TINT_GOLD button, OUT of the F2 cycle (reached only by the
    # button + Alt+K). restripe() makes it the new seg-last. Keeps its FULL
    # label through d1, icon-only at d2 (its lb-full and lb-min are both CARDS).
    gui.cards_btn = seg("cards", ["CARDS"], "cards", Role.TINT_GOLD,
                        "Cards of Truth (Alt+K)", checkable=False)
    # C7: HUMAN DESIGN sits next to CARDS in the LEFT group (was a right-cluster
    # toggle next to BIRTH TIME). It is a 3-state cycle — bodygraph page ->
    # -88 Design chart -> wheel — so it carries two captions; the "hd" ladder row
    # holds both. Handler _cycle_human_design; the -88 lit state still tracks
    # is_human_design (rendered in bind_state).
    gui.human_design_btn = seg("hd", ["HUMAN DESIGN", "DESIGN CHART"], "hd",
                               Role.TINT_BLUE, "Human Design (Ctrl+Shift+H)")
    gui.open_in_kala_btn = seg("kala", ["OPEN IN KALA"], "kala",
                               tip="Open in Kala (Alt+O)")
    gui.chart_info_btn = seg("info", ["CHART INFO"], "info",
                             tip="Chart info")
    left_seg1 = SegmentCluster(
        [gui.transit_btn, gui.wheel_btn, gui.cards_btn, gui.human_design_btn],
        m, tokens_fn)
    left_seg2 = SegmentCluster([gui.open_in_kala_btn, gui.chart_info_btn],
                               m, tokens_fn)
    left_grp = _group([left_seg1, left_seg2], m, right_margin=m.grp_margin)

    _maybe_connect(gui.transit_btn.clicked, gui, "_toggle_transit_rim")
    _maybe_connect(gui.wheel_btn.clicked, gui, "_toggle_wheel_view")
    _maybe_connect(gui.cards_btn.clicked, gui, "_toggle_cards_view")
    _maybe_connect(gui.human_design_btn.clicked, gui, "_cycle_human_design")
    _maybe_connect(gui.open_in_kala_btn.clicked, gui, "_open_in_kala")
    # chart info is a chart_title_widget MODULE function, not a gui method
    gui.chart_info_btn.clicked.connect(lambda: _legacy(gui, "_fetch_chart_info"))
    # transit right-click menu — same module handler as legacy (Sol M1 major 3)
    gui.transit_btn.setContextMenuPolicy(Qt.CustomContextMenu)
    gui.transit_btn.customContextMenuRequested.connect(
        lambda pos: _legacy(gui, "_show_transit_context_menu",
                            gui.transit_btn, pos))

    # ---- CENTER ------------------------------------------------------------
    gui.chart_title_label = ElidedPillButton(m, tokens_fn)
    meta = BarTextLabel(m, tokens_fn, token_key="muted")
    meta.setObjectName("bar_meta")
    gui.chart_title_meta = meta
    gui.chart_close_button = CloseGlyphButton(m, tokens_fn)
    title_well = TitleWell(gui.chart_title_label, meta,
                           gui.chart_close_button, m, tokens_fn)
    gui.chart_title_well = title_well
    _maybe_connect(gui.chart_close_button.clicked, gui, "_close_current_chart")
    gui.chart_title_label.clicked.connect(
        lambda: _legacy(gui, "_search_chart_name_google_images"))
    # pill right-click menu (Sol M1 major 3)
    gui.chart_title_label.setContextMenuPolicy(Qt.CustomContextMenu)
    gui.chart_title_label.customContextMenuRequested.connect(
        lambda pos: _legacy(gui, "_show_pill_context_menu",
                            gui.chart_title_label, pos))

    # ---- RIGHT -------------------------------------------------------------
    gui.now_btn = seg("now", ["NOW"], "now", tip="Jump to now (Alt+N)",
                      live=True)
    gui.add_chart_btn = seg("add", ["ADD CHART"], "add", Role.PRIMARY,
                            "Add chart (Alt+A)")
    gui.time_adjust_btn = seg("birth", ["BIRTH TIME ±"], "time",
                              Role.TINT_BLUE, "Birth time ± (Alt+T)")
    right_seg1 = SegmentCluster([gui.now_btn, gui.add_chart_btn], m, tokens_fn)
    # C7: HUMAN DESIGN moved to the left group (next to CARDS); BIRTH TIME is now
    # the sole member of the fold-at-d3 toggles cluster.
    right_seg2 = SegmentCluster([gui.time_adjust_btn], m, tokens_fn)
    _maybe_connect(gui.now_btn.clicked, gui, "_load_now_chart")
    _maybe_connect(gui.add_chart_btn.clicked, gui, "show_add_chart_dialog")
    _maybe_connect(gui.time_adjust_btn.clicked, gui, "_toggle_time_adjust")

    # ---- ZODIAC TRAY -------------------------------------------------------
    # D-24: the glyph names the NAME SET, the label names the system. Sun
    # (dhata) = Aditya names on, ram = Western names on; Sidereal keeps its
    # star natively (the only frame emblem in the tray) and shows the sun
    # under Aditya names. The globe is retired.
    _ADI, _WES = "Aditya names", "Western names"
    gui.aditya_btn = seg("aditya", ["ADITYA CIRCLE"], "dhata", Role.ZOD,
                         "Aditya Circle (Alt+Z)",
                         alt_icon="ram", name_sets=(_ADI, _WES))
    gui.tropical_btn = seg("classic", ["TROPICAL CLASSIC"], "ram", Role.ZOD,
                           "Tropical Classic (Alt+C)",
                           alt_icon="dhata", name_sets=(_WES, _ADI),
                           dual_tooltip="Sidereal (Alt+S)")
    gui.sidereal_btn = seg("sidereal", ["SIDEREAL"], "sid", Role.ZOD,
                           "Sidereal (Alt+S)",
                           alt_icon="dhata", name_sets=(_WES, _ADI))
    zod_cluster = SegmentCluster(
        [gui.aditya_btn, gui.tropical_btn, gui.sidereal_btn], m, tokens_fn,
        transparent_bg=True)
    gui.dual_rim_btn = seg("dual", ["+ TROPICAL"], "rim", Role.MOD,
                           "Modifier — add a second, tropical rim",
                           checkable=True, plus=True)
    tray = ZodiacTray(zod_cluster, HairlineSep(m, tokens_fn, gradient=True),
                      gui.dual_rim_btn, m, tokens_fn)
    gui.zodiac_tray = tray

    _maybe_connect(gui.aditya_btn.clicked, gui, "",
                   lam=lambda: getattr(gui, "_set_aditya_mode",
                                       lambda *_: None)("aditya"))
    _maybe_connect(gui.tropical_btn.clicked, gui, "",
                   lam=lambda: getattr(gui, "_set_aditya_mode",
                                       lambda *_: None)("tropical_classic"))
    _maybe_connect(gui.sidereal_btn.clicked, gui, "",
                   lam=lambda: getattr(gui, "_set_aditya_mode",
                                       lambda *_: None)("sidereal"))
    _maybe_connect(gui.dual_rim_btn.clicked, gui, "_toggle_dual_rim")

    # Hide-HD swap (D-5 dual-role wiring lands in M3; construction shows the
    # correct static config): HD visible -> sidereal segment absent.
    if hide_human_design is None:
        try:
            from managers.settings_manager import get_settings
            hide_human_design = bool(
                get_settings().get("ui.hide_human_design", False))
        except Exception:
            hide_human_design = False
    # The HD<->sidereal swap is now OWNED by the layout controller's
    # app_visible flags (D-22h) — its first apply hides the right one through
    # set_button_visible, restriped. (M1's direct calls moved there.)

    # INV-7: tray state is rendered by bind_state's construction-time pull
    # below (boot's R4 sets the mode with no signal — design doc §2.4).

    # overflow capsule (.ovf :640-643): icon-only SOLO, literal 8px pad
    # (D-22d), hidden until d3 — the controller owns its visibility.
    gui.bar_overflow_btn = seg("overflow", [], "more", Role.SOLO,
                               "More controls")
    gui.bar_overflow_btn.hide()

    sep_s3 = HairlineSep(m, tokens_fn)      # the ONLY separator that hides
    right_grp = _group(
        [right_seg1, sep_s3, right_seg2,
         HairlineSep(m, tokens_fn), tray, gui.bar_overflow_btn],
        m, left_margin=m.grp_margin)
    gui.bar_toggles_cluster = right_seg2    # .lvl3 (folds whole at d3+)

    # ---- legacy compatibility attrs ---------------------------------------
    # search_btn stays layout-orphaned (chart_memory_panel delegation); a
    # hidden parented button so it can never appear as a stray window. It must
    # still WORK when clicked programmatically (Sol M1 major 2).
    from PySide6.QtWidgets import QHBoxLayout as _HB
    from PySide6.QtWidgets import QPushButton
    gui.search_btn = QPushButton("Search")
    gui.search_btn.hide()
    gui.search_btn.clicked.connect(lambda: _legacy(gui, "_open_chart_search"))

    # Overlay chip (Sol M1 major 4 + M3 repaint): ChartOverlayManager shows/
    # hides gui.overlay_chip and update_overlay_chip writes gui.overlay_chip_view
    # (the painted OverlayChip); the × clear button returns to the live sky.
    chip = QWidget()
    chip_lay = _HB(chip)
    chip_lay.setContentsMargins(0, 0, 0, 0)
    chip_lay.setSpacing(round(4 * fs))
    # D-23(b) / F2: the painted ◇·name·info chip (mockup .ovl — --ctl fill,
    # 0.5px --hair-soft inset hairline, real flex elision: info gives ground
    # first, name last), then the × as a separate round control (the mockup's
    # .xbtn is a SIBLING of .ovl, not inside it). Replaces the three plain,
    # non-eliding, blue-bordered QLabels (Sol M1 BLOCKER 1).
    gui.overlay_chip_view = OverlayChip(fs=fs)
    chip_lay.addWidget(gui.overlay_chip_view)
    # F2 / MAJOR 2: the mockup's chip is `◇ Name · info` and the slot before the
    # base-chart close renders the well's painted downward CHEVRON (.chev, :617),
    # NOT a second ×. The old code seated a muted `×` QPushButton in exactly that
    # slot, painting a × OVER the chevron (CP-4 is glyph-blind, so it never
    # caught the doubled mark). Keep an 18px control in the slot so the chip
    # geometry stays byte-stable (the golden ◇ x is measured with the slot
    # filled), but render NO glyph: the flat, empty, translucent button lets the
    # well's chevron show through, and clicking it is the "back to live sky"
    # affordance. `overlay_chip_clear` stays the clickable attribute it always
    # was (remote / tests / back-compat).
    gui.overlay_chip_clear = QPushButton("")
    gui.overlay_chip_clear.setFixedSize(18, 18)
    gui.overlay_chip_clear.setFlat(True)
    gui.overlay_chip_clear.setCursor(Qt.PointingHandCursor)
    gui.overlay_chip_clear.setAttribute(Qt.WA_TranslucentBackground, True)
    gui.overlay_chip_clear.setToolTip(
        "Remove overlay chart (back to live sky)")
    gui.overlay_chip_clear.clicked.connect(
        lambda: getattr(gui, "chart_overlay_manager", None) is not None
        and gui.chart_overlay_manager.back_to_live_sky())
    chip_lay.addWidget(gui.overlay_chip_clear)
    gui.overlay_chip = chip
    chip.hide()
    # MINOR 6 / INV-4: the v2 chip is fully painted (OverlayChip self-themes via
    # bar_tokens; container transparent by default; the clear control paints no
    # glyph). It needs NO QSS, so mark it and let _style_overlay_chip skip the
    # QSS path it keeps for the legacy bar's visible × (QSS = overflow menu only).
    gui._overlay_chip_painted = True

    # ---- assemble ----------------------------------------------------------
    bar = ChartActionBar(m, tokens_fn)
    gui.search_btn.setParent(bar)  # parented + hidden (spec: no stray window)
    # chip lives in the well right-aligned BEFORE the close glyph, matching the
    # mockup order `.names(flex) → .ovl chip → .chev → .xbtn(close)` (:607-618):
    # the name's leftover-space stretch pushes the chip to the right, the close
    # glyph (with its painted chevron slot) stays the far-right control. Hidden
    # children take no layout space, so goldens are untouched until an overlay
    # shows it. (Was appended AFTER close — that put the ◇ 20px right of golden
    # and left the close glyph mid-well; Sol M1 BLOCKER 1.)
    _well_lay = title_well.layout()
    _well_lay.insertWidget(_well_lay.indexOf(gui.chart_close_button), chip)
    lay = QHBoxLayout(bar)
    # D-22a second half: without SetNoConstraint the layout enforces its own
    # minimumSize on the widget (a top-level bar could never shrink below
    # d0's content and the window case pins too); the bar's honest floor is
    # declared via minimumSizeHint instead.
    from PySide6.QtWidgets import QLayout
    lay.setSizeConstraint(QLayout.SetNoConstraint)
    lay.setContentsMargins(m.side_pad, 0, m.side_pad, 0)
    lay.setSpacing(m.track_gap)
    # C8 (2026-08-29, Lorris): the well hugs its content (Maximum policy) and a
    # single spacer to its RIGHT absorbs the surplus. left_grp still hugs the
    # left end and right_grp the right end (only ONE mid stretch, not the rev1
    # centre-slack pair), so there are no dead backdrop caps at the bar edges.
    # QBoxLayout adds no spacing next to a spacer item, so inserting it drops
    # the well<->sep gap: required() now counts 3 track gaps, not 4.
    lay.addWidget(left_grp)
    lay.addWidget(HairlineSep(m, tokens_fn))
    lay.addStretch(1)                          # C8: even slack, LEFT of the well
    lay.addWidget(title_well, 0)
    lay.addStretch(1)                          # C8: even slack, RIGHT of the well
    lay.addWidget(HairlineSep(m, tokens_fn))
    lay.addWidget(right_grp)

    bar.cluster_widgets = [left_seg1, left_seg2, right_seg1, right_seg2]

    # ---- M2: the layout controller (d0-d5 ladder) -------------------------
    from .layout_controller import ActionBarLayoutController
    controller = ActionBarLayoutController(
        bar, gui, m, tokens_fn,
        buttons={"transit": gui.transit_btn, "north": gui.wheel_btn,
                 "cards": gui.cards_btn,
                 "kala": gui.open_in_kala_btn, "info": gui.chart_info_btn,
                 "now": gui.now_btn, "add": gui.add_chart_btn,
                 "birth": gui.time_adjust_btn, "hd": gui.human_design_btn,
                 "aditya": gui.aditya_btn, "classic": gui.tropical_btn,
                 "sidereal": gui.sidereal_btn, "dual": gui.dual_rim_btn},
        toggles_cluster=right_seg2, zod_cluster=zod_cluster, sep_s3=sep_s3,
        tray=tray, title_well=title_well, meta=meta,
        overflow_btn=gui.bar_overflow_btn,
        hd_visible=not hide_human_design)
    gui.bar_overflow_btn.clicked.connect(controller.show_overflow_menu)
    bar._scale_groups = (left_grp, right_grp)
    bar.layout_controller = controller
    gui.bar_layout_controller = controller
    controller.apply_initial()                  # boot at d0, like the mockup

    # ---- M3: observer wiring (INV-7) --------------------------------------
    bar._pill = gui.chart_title_label
    bar._meta_label = meta
    bar.bind_state(gui)          # subscribes + one initial render; the boot
    #                              R4 direct-field write is covered by this
    #                              construction-time pull (design doc §2.4)

    # ---- M4: the keyboard focus ring (Dm4-33..37) -------------------------
    from .focus_overlay import FocusOverlay
    bar.focus_overlay = FocusOverlay(bar, tokens_fn)

    gui.chart_title_widget = bar
    return bar
