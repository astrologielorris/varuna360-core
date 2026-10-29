# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""ChartLayoutManager: sole owner of the Chart tab's right side geometry.

SPEC-LAYOUT-001 (plan proprietary_docs/docs/plans/2026-10-15-responsive-dasha-
and-panels.md). It owns the info column (``right_scroll``), the right dasha
column (the canonical ``DashaPanelWidget``), the bottom shelf host and the
last-resort right drawer. ``ChartGUI`` keeps ONE attribute for it
(``chart_layout``); every other piece of layout state lives here (Rule 4b).

Width allocation (plan D2/D2a), from TARGET widths so no decision reads its own
effect. ``chart_t`` is what the chart gets with the dasha Full; the chart keeps it
whatever the dasha presentation, and the info column receives every released
pixel. Yield order when space runs out: (1) the left group to its drawer, (2) the
effective dasha presentation to Rail (the stored preference is untouched),
(3) info shrinks to INFO_MIN, (5) the whole right group to its drawer. Every
boundary has a 24 px hysteresis band.

Dasha position (plan A.3): stored ``position`` (side | bottom) and ``user_rail``;
runtime ``band`` (wide | narrow) and ``auto_folded``. Auto acts once per band
crossing and never selects or leaves Bottom.

Resize handling is coalesced: every geometry input restarts one single-shot
timer, so a live drag runs ``_apply`` once per event-loop turn, never per pixel,
and never calls engines, writes settings or builds widgets. A presentation change
animates the dasha width, the info width and the shelf height together from ONE
200 ms animation (0 ms with reduce motion), so the chart frame width never jumps.
"""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QEvent, QKeyCombination, QObject, QPropertyAnimation,
                            Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QHBoxLayout, QWidget

from ui.qt_theme import get_theme_colors, scaled_px

POSITIONS = ("full", "rail", "bottom")
CHART_MIN_BASE = 420          # px at scale 1 (plan D2)
INFO_MIN_BASE = 330           # px at scale 1 (plan D2)
RAIL_BASE = 64                # px at scale 1 (plan A.1)
SHELF_BASE = 188              # px at scale 1 (plan A.1, Landing shelf)
SHELF_MARGIN_BASE = 10
HYSTERESIS = 24               # px band around each fold point (plan A.3)
CHART_MIN_TWO_BASE = 520      # px at scale 1, per chart in two-chart mode (SPEC-DUAL-001 D-16)
ANIM_MS = 200
COALESCE_MS = 0               # one apply per event-loop turn
_M, _K = Qt.KeyboardModifier, Qt.Key
SHORTCUTS = {                 # free keys (plan D1, P0.10): Ctrl+], Ctrl+Shift+D, Alt+X, Alt+1
    "toggle_fold": (_M.ControlModifier, _K.Key_BracketRight),
    "toggle_dock": (_M.ControlModifier | _M.ShiftModifier, _K.Key_D),
    "exchange_panels": (_M.AltModifier, _K.Key_X),
    "fold_karakas": (_M.AltModifier, _K.Key_1),
}
_WMAX = 16777215


def _shelf_style():
    theme = get_theme_colors()
    return (f"QWidget#dashaShelfHost {{ background: {theme['secondary_dark']}; "
            f"border-top: 2px solid {theme['primary']}; border-radius: {scaled_px(7)}px; }}")


def _fix(w: QWidget, width: int) -> None:
    w.setMinimumWidth(width)
    w.setMaximumWidth(width)


class ChartLayoutManager(QObject):
    """Frozen API (plan D1). Created once by ChartGUI after the Chart tab exists."""

    def __init__(self, gui):
        super().__init__(gui)
        self._gui = gui
        self._installed = False
        self._drawer_mode = False       # right group folded into its drawer
        self._drawer_open = False       # drawer slid in while in drawer mode
        self._fullscreen = False
        self._pending_apply = False
        self._pending_position = None   # (pos, persist) asked during fullscreen
        self._position = "side"         # stored: side | bottom
        self._user_rail = False         # stored
        self._band = None               # runtime: wide | narrow
        self._auto_folded = False       # runtime
        self._effective = "full"        # shown: full | rail | bottom
        self._info_w = 0
        self._anim = None
        self._anim_target = None
        self._drawer_anims = []
        self._needs_refit = set()
        self._anim_refit = []           # views the running dasha move refits at its end
        self._refit_carry = []          # pre-change fit snapshot handed to the next move
        self._shortcuts = []
        # SPEC-DUAL-001 §4.3: two-chart geometry (session-only, never persisted).
        self._two = False
        self._two_intent = None         # (position, user_rail, auto_folded) at entry
        self._rail = None               # InfoRail (built at install)
        self._drawer_host = None        # InfoDrawerHost (built at install)
        self._placeholders = {}         # slot keepers for the reparented columns
        self._info_drawer_open = False
        self._esc = None
        self._press_filter = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COALESCE_MS)
        self._timer.timeout.connect(self._apply)

    # ------------------------------------------------------------------ setup
    def install(self, gui=None) -> None:
        """Wire geometry inputs, the shelf host and shortcuts. Idempotent."""
        if self._installed:
            return
        gui = gui or self._gui
        self._installed = True
        self._content = gui.chart_content
        self._row = self._content.layout()
        self._scroll = gui.right_scroll
        self._dasha = gui.vimshottari_panel
        self._toggle = gui._right_toggle
        self._sign = gui.sign_selector_column
        self._chart_stack = gui.chart_stack
        self._info_base = self._scroll.maximumWidth()
        self._dasha_full = self._dasha.maximumWidth()
        self._info_w = self._info_base

        # Placeholder keeping the dasha slot's width while the shelf animates.
        self._slot = QWidget(self._content)
        self._slot.setVisible(False)
        self._row.insertWidget(self._row.indexOf(self._dasha) + 1, self._slot)

        # Bottom shelf host: a sibling BELOW chart_content in the Chart tab's
        # QVBoxLayout (plan P0.5), so it spans the whole row.
        self._shelf = QWidget(gui.chart_tab)
        self._shelf.setObjectName("dashaShelfHost")
        self._shelf.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._shelf.setStyleSheet(_shelf_style())
        m = scaled_px(6)
        QHBoxLayout(self._shelf).setContentsMargins(m, m, m, m)
        self._shelf.setFixedHeight(0)
        self._shelf.setVisible(False)
        gui.chart_tab.layout().addWidget(self._shelf)

        # The left drawer's Show/Hide/width animation also changes the budget.
        for w in (self._content, self._scroll.viewport(), gui.vedanga_panel):
            w.installEventFilter(self)
        for name, (mods, key) in SHORTCUTS.items():
            sc = QShortcut(QKeySequence(QKeyCombination(mods, key)), gui.chart_tab)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(getattr(self, name))
            self._shortcuts.append(sc)
        self._dasha.fold_requested.connect(self.toggle_fold)
        self._dasha.dock_requested.connect(self._on_dock_requested)
        self._dasha.return_requested.connect(self._on_return_requested)
        self._chart_stack.currentChanged.connect(self._refit_shown_page)
        self._install_two_chart(gui)
        self._load_position()
        self.schedule()

    def _install_two_chart(self, gui) -> None:
        """SPEC-DUAL-001 §4.3: the rail (a row item right of the info slot,
        hidden in one-chart mode), the drawer host (a floating child of
        chart_content) and the drawer's Esc shortcut (enabled while open)."""
        from apps.widgets.info_rail import InfoDrawerHost, InfoRail
        self._rail = InfoRail(self._content)
        self._rail.setVisible(False)
        self._rail.clicked.connect(self.toggle_info_drawer)
        self._row.insertWidget(self._row.indexOf(self._scroll) + 1, self._rail)
        self._drawer_host = InfoDrawerHost(self._content)
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), gui.chart_tab)
        self._esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._esc.setEnabled(False)
        self._esc.activated.connect(self.close_info_drawer)
        gui.chart_tab.destroyed.connect(self.teardown)

    def _on_dock_requested(self) -> None:
        if self._two:                              # INV-13: inert while paired
            return
        self.set_dasha_position("bottom", persist=True)

    def _on_return_requested(self) -> None:
        if self._two:                              # INV-13: inert while paired
            return
        self.set_dasha_position("full", persist=True)

    def _load_position(self) -> None:
        from managers.settings_manager import get_settings
        s = get_settings()
        pos = s.get("ui.layout.dasha_right_position")
        pos = pos if pos in POSITIONS else "full"
        self._position = "bottom" if pos == "bottom" else "side"
        self._user_rail = pos == "rail" or bool(s.get("ui.layout.dasha_right_user_rail"))
        if self._position == "bottom":
            self._dock(animated=False)
        elif self._user_rail:
            self._effective = "rail"
            self._dasha.set_presentation("rail")
            _fix(self._dasha, self._dasha_w("rail"))

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            self.schedule()
        return False

    # ----------------------------------------------------------- frozen hooks
    def schedule(self) -> None:
        """Coalesce every geometry input into one ``_apply`` (plan A.3/D1)."""
        if self._installed:
            self._timer.start()

    def on_window_resized(self) -> None:
        self.schedule()

    def on_fullscreen(self, on: bool) -> None:
        """Called by the chart descriptor's on_enter BEFORE ViewFloatManager
        captures the view states (SPEC-DUAL-001 §4.7): running motion is settled
        first, so F during the dasha's exit slide is safe."""
        if on:
            self._settle_motion()
        self._fullscreen = bool(on)
        if not on:
            self._pending_apply = True

    def on_settled(self) -> None:
        """Fullscreen exit has restored every view; apply queued work (D1)."""
        pending, self._pending_position = self._pending_position, None
        if pending is not None:
            self.set_dasha_position(pending[0], persist=pending[1])
        if self._pending_apply:
            self._pending_apply = False
            self.schedule()

    def refresh_theme(self) -> None:
        if self._installed:
            self._shelf.setStyleSheet(_shelf_style())
            self._rail.refresh_theme()
            self._drawer_host.update()
        self.info_stack().refresh_theme()
        pair = getattr(self._gui, "chart_pair", None)     # SPEC-DUAL-001 §4.9
        if pair is not None:
            pair.refresh_theme()
        self.schedule()

    def refresh_fonts(self) -> None:
        if self._installed and self._effective == "bottom" and self._anim is None:
            self._shelf.setFixedHeight(self._shelf_h())
        if self._installed:
            self._rail.refresh_theme()
        self.info_stack().refresh_fonts()
        pair = getattr(self._gui, "chart_pair", None)     # SPEC-DUAL-001 §4.9
        if pair is not None:
            pair.refresh_fonts()
        self.schedule()

    def info_stack(self):
        return self._gui.right_panels

    def dasha_presentation(self, side: str = "right") -> str:
        return self._effective if side == "right" else "full"

    def set_dasha_position(self, pos: str, *, persist: bool) -> None:
        """Full / Rail / Bottom. ``persist=False`` for remote/AI (INV-17)."""
        if pos not in POSITIONS:
            raise ValueError(f"position must be one of {POSITIONS}, got {pos!r}")
        if self._two and pos != "bottom":          # SPEC-DUAL-001 INV-13
            raise ValueError("two-chart mode: the right dasha stays on the bottom shelf")
        if not self._installed:
            return
        if self._two:                              # already Bottom: a no-op; the entry
            return                                 # intent stays what leaving restores (INV-3)
        if self._fullscreen:                       # applied on exit (plan A.4)
            self._pending_position = (pos, persist)
            return
        self._position = "bottom" if pos == "bottom" else "side"
        self._user_rail = pos == "rail"
        self._auto_folded = False
        if persist:
            self._persist()
        self._show(self._wanted())

    def toggle_fold(self) -> None:
        """Ctrl+] / fold button: side Full <-> Rail; nothing at Bottom."""
        if self._position == "bottom" or self._two:
            return
        self.set_dasha_position("full" if self._effective == "rail" else "rail", persist=True)

    def toggle_dock(self) -> None:
        """Ctrl+Shift+D / Bottom button: side <-> bottom."""
        if self._two:                              # INV-13: inert while paired
            return
        self.set_dasha_position("full" if self._position == "bottom" else "bottom", persist=True)

    def exchange_panels(self) -> None:
        self.info_stack().exchange_active()

    def fold_karakas(self) -> None:
        self.info_stack().toggle_fold("karakas")

    def capture_widget_for(self, region_id: str):
        """Widget whose geometry a capture region uses (plan D7a)."""
        if region_id.startswith("dasha.right"):
            return self._dasha
        return None

    def layout_state(self) -> dict:
        return {"dasha_right": self.dasha_presentation("right"),
                "dasha_right_position": self._stored_position(),
                "band": self._band, "auto_folded": self._auto_folded,
                "right_drawer": {"mode": self._drawer_mode, "open": self._drawer_open},
                "two_chart": self._two, "info_drawer": self._info_drawer_open,
                "panels": self.info_stack().layout_state()}

    def _stored_position(self) -> str:
        if self._position == "bottom":
            return "bottom"
        return "rail" if self._user_rail else "full"

    def _persist(self) -> None:
        """Position and user_rail written together (plan D5)."""
        from managers.settings_manager import get_settings
        s = get_settings()
        s.persist_runtime_change("ui.layout.dasha_right_position", self._stored_position(), save=False)
        s.persist_runtime_change("ui.layout.dasha_right_user_rail", self._user_rail)

    # --------------------------------------------------------------- geometry
    def _chart_min(self) -> int:
        return max(scaled_px(CHART_MIN_BASE), self._chart_stack.minimumSizeHint().width())

    def _shelf_h(self) -> int:
        m = self._shelf.layout().contentsMargins()
        need = self._dasha.minimumSizeHint().height() + m.top() + m.bottom()
        return max(scaled_px(SHELF_BASE), need) + scaled_px(SHELF_MARGIN_BASE)

    def _dasha_w(self, presentation: str) -> int:
        return {"full": self._dasha_full, "rail": scaled_px(RAIL_BASE), "bottom": 0}[presentation]

    def _fixed(self, left: str, dasha_w: int) -> int:
        """Row width of everything except the chart and the info column.
        ``left``: "full" (whole left group), "compact" (its toggle only) or
        "drawer" (toggle + the open drawer's Vedanga and varga columns)."""
        m = self._row.contentsMargins()
        targets = self._gui._panel_target_widths
        gui = self._gui
        if left == "full":
            items = [targets[gui.vedanga_panel], targets[gui.varga_column], targets[self._sign]]
        else:
            items = [gui._left_toggle.width()]
            if left == "drawer":
                items += [targets[gui.vedanga_panel], targets[gui.varga_column]]
        if dasha_w:
            items.append(dasha_w)
        gaps = len(items) + 1                      # + chart + info
        return m.left() + m.right() + sum(items) + self._row.spacing() * gaps

    def _left_mode(self) -> str:
        gui = self._gui
        if not gui._left_toggle.isVisible():
            return "full"
        return "drawer" if gui._left_drawer_open else "compact"

    def _wanted(self) -> str:
        """Effective presentation. A narrow band clamps a preferred Full to Rail
        (plan D2: the stored preference stays Full and shows again as soon as
        it fits), so Return to side never pushes the chart below CHART_MIN."""
        if getattr(self, "_two", False) or self._position == "bottom":   # SPEC-DUAL-001
            return "bottom"
        narrow = self._band == "narrow"
        return "rail" if (self._user_rail or self._auto_folded or narrow) else "full"

    def _info_for(self, left: str, presentation: str, row: int) -> int:
        """The chart keeps chart_t (what it has with the dasha Full); the info
        column takes every released pixel, never below INFO_MIN (plan D2)."""
        chart_t = row - self._fixed(left, self._dasha_full) - self._info_base
        avail = row - self._fixed(left, self._dasha_w(presentation))
        return max(scaled_px(INFO_MIN_BASE), avail - max(chart_t, self._chart_min()))

    def _apply(self) -> None:
        if not self._installed or self._fullscreen:
            if self._fullscreen:
                self._pending_apply = True
            return
        if self._anim is not None:                 # the animation reschedules
            return
        if self._two:
            self._apply_two()
            return
        gui = self._gui
        row = self._content.width()
        chart_min, info_min = self._chart_min(), scaled_px(INFO_MIN_BASE)
        # (1) the left group, budgeted with the dasha Full whatever its
        # presentation: width a Rail/Bottom releases goes to the info panels
        # (Lorris's brief), never back to the left group.
        was_compact = gui._left_toggle.isVisible()
        restore_at = (self._fixed("full", self._dasha_full) + chart_min
                      + self._info_base + (HYSTERESIS if was_compact else 0))
        gui._set_left_compact(not gui._side_panels_visible or row < restore_at)
        left = self._left_mode()
        # (2) band: does the Full column fit next to the chart minimum?
        need_full = self._fixed(left, self._dasha_full) + chart_min + self._info_base
        self._on_band("narrow" if row < need_full + (HYSTERESIS if self._band == "narrow" else 0)
                      else "wide")
        eff = self._wanted()
        # (5) last resort: the whole right group to its drawer.
        smallest = "bottom" if eff == "bottom" else "rail"
        need_min = self._fixed(left, self._dasha_w(smallest)) + chart_min + info_min
        fits = row >= need_min + (HYSTERESIS if self._drawer_mode else 0)
        if fits == self._drawer_mode:
            self._set_drawer_mode(not fits)
        # (3) widths.
        self._info_w = self._info_for(left, eff, row)
        if eff != self._effective:
            self._show(eff)
        elif not self._drawer_mode:
            _fix(self._scroll, self._info_w)
            if eff != "bottom":
                _fix(self._dasha, self._dasha_w(eff))
        self.info_stack().set_available_size(self._scroll.viewport().size())
        gui._align_status_controls()

    def _on_band(self, band: str) -> None:
        """Plan A.3: auto acts once per crossing and never at Bottom."""
        prev, self._band = self._band, band
        if self._position == "bottom" or prev == band:
            return
        if band == "narrow" and not self._user_rail:
            self._auto_folded = True             # startup narrow, or wide -> narrow
        elif band == "wide" and prev == "narrow":
            self._auto_folded = False            # only undoes auto's own fold

    # ------------------------------------------------------- presentation move
    def _show(self, target: str) -> None:
        """Move the right dasha to ``target`` with one coordinated animation
        (plan A.4); retargeted, never stacked, on rapid requests."""
        if self._anim is not None and self._anim_target == target:
            return                                 # already on its way there
        self._stop_anim()
        if self._drawer_anims:                     # their callbacks must not touch a moved panel
            self._stop_drawer_anims()
            self._settle_drawer()
        source = self._effective
        if target == source and self._dasha_in_place(target):
            self.schedule()
            return
        if self._drawer_mode:                      # inside the drawer: instant
            self._set_presentation_now(target)
            self.schedule()
            return
        refit = self._fit_snapshot() if "bottom" in (source, target) else []
        carry, self._refit_carry = self._refit_carry, []
        refit = list(dict.fromkeys(list(refit) + list(carry)))
        self._effective = target
        row = self._content.width()
        info_to = self._info_for(self._left_mode(), target, row)
        if target == "bottom":
            self._dock(animated=True)
        elif self._dasha.parentWidget() is self._shelf:
            self._slot.setVisible(True)            # the side slot grows back
        else:
            self._dasha.set_presentation(target)
        # Fixed widths are min == max, so the minimums are the current values
        # even before the layout has run (retargeted mid-animation too).
        start = {"info": self._scroll.minimumWidth(),
                 "dasha": self._dasha.minimumWidth(),
                 "slot": self._slot.minimumWidth() if self._slot.isVisible() else 0,
                 "shelf": self._shelf.maximumHeight() if self._shelf.isVisible() else 0}
        end = {"info": info_to,
               "dasha": self._dasha_w(target),
               "slot": 0 if target == "bottom" else self._dasha_w(target),
               "shelf": self._shelf_h() if target == "bottom" else 0}
        if self._dasha.parentWidget() is not self._shelf:
            start["slot"] = end["slot"] = 0        # side <-> side: no slot
        self._anim_refit = refit
        self._run(start, end, lambda: self._finish(target, refit))

    def _dasha_in_place(self, target: str) -> bool:
        in_shelf = self._dasha.parentWidget() is self._shelf
        return in_shelf == (target == "bottom")

    def _dock(self, *, animated: bool) -> None:
        """Reparent the canonical panel into the shelf (plan D4: setParent +
        layout insert + show); the slot keeps the side width while animating."""
        if self._dasha.parentWidget() is self._shelf:
            return
        width = self._dasha.width() if animated else 0
        self._row.removeWidget(self._dasha)
        _fix(self._slot, width)
        self._slot.setVisible(animated)
        self._dasha.setParent(self._shelf)
        self._shelf.layout().addWidget(self._dasha)
        self._dasha.setMinimumWidth(0)
        self._dasha.setMaximumWidth(_WMAX)
        self._dasha.set_presentation("shelf")
        self._dasha.show()
        self._shelf.setVisible(True)
        if not animated:
            self._effective = "bottom"
            self._shelf.setFixedHeight(self._shelf_h())

    def _undock(self, target: str) -> None:
        """Return the panel to its stored side slot (plan D4)."""
        self._shelf.layout().removeWidget(self._dasha)
        self._dasha.setParent(self._content)
        self._row.insertWidget(self._row.indexOf(self._slot), self._dasha)
        self._dasha.set_presentation(target)
        _fix(self._dasha, self._dasha_w(target))
        self._dasha.setVisible(not self._drawer_mode or self._drawer_open)
        self._slot.setVisible(False)
        self._shelf.setFixedHeight(0)
        self._shelf.setVisible(False)

    def _set_presentation_now(self, target: str) -> None:
        """Instant variant used inside the right drawer."""
        self._effective = target
        if target == "bottom":
            self._dock(animated=False)
        elif self._dasha.parentWidget() is self._shelf:
            self._undock(target)
        else:
            self._dasha.set_presentation(target)
            _fix(self._dasha, self._dasha_w(target))

    def _run(self, start: dict, end: dict, done) -> None:
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(0 if self._reduce_motion() else ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade = start["shelf"] != end["shelf"] and anim.duration() > 0
        if fade:                                   # plan D8; Qt owns the effect (Rule 18)
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(1.0 if start["shelf"] else 0.0)
            self._shelf.setGraphicsEffect(effect)
            del effect
        opening = end["shelf"] > start["shelf"]

        def frame(u):
            u = float(u)
            v = {k: round(start[k] + (end[k] - start[k]) * u) for k in start}
            _fix(self._scroll, v["info"])
            if self._dasha.parentWidget() is not self._shelf:
                _fix(self._dasha, max(v["dasha"], 1))
            if self._slot.isVisible():
                _fix(self._slot, v["slot"])
            if start["shelf"] != end["shelf"]:
                self._shelf.setFixedHeight(v["shelf"])
                eff = self._shelf.graphicsEffect()
                if eff is not None:
                    eff.setOpacity(u if opening else 1.0 - u)

        anim.valueChanged.connect(frame)
        anim.finished.connect(done)
        self._anim = anim
        self._anim_target = self._effective
        if anim.duration() == 0:
            frame(1.0)
            done()
        else:
            anim.start()

    def _finish(self, target: str, refit) -> None:
        anim, self._anim = self._anim, None
        self._anim_target = None
        self._anim_refit = []
        if anim is None:
            return
        anim.deleteLater()
        if self._shelf.graphicsEffect() is not None:
            self._shelf.setGraphicsEffect(None)
        if target == "bottom":
            self._slot.setVisible(False)
            self._shelf.setFixedHeight(self._shelf_h())
        elif self._dasha.parentWidget() is self._shelf:
            self._undock(target)
        else:
            _fix(self._dasha, self._dasha_w(target))
        self._dasha.relayout_items()
        self._apply_refit(refit)
        self.schedule()

    def _stop_anim(self) -> None:
        """Retarget: stop the running move where it is; the next one starts
        from the current widths (its owed refit is carried to the next move)."""
        anim, self._anim = self._anim, None
        self._anim_target = None
        if anim is not None and self._anim_refit:
            self._refit_carry = list(dict.fromkeys(self._refit_carry + self._anim_refit))
        self._anim_refit = []
        if anim is not None:
            anim.stop()
            anim.deleteLater()
            if self._shelf.graphicsEffect() is not None:
                self._shelf.setGraphicsEffect(None)

    # ------------------------------------------------------------ chart refit
    def _views(self):
        from PySide6.QtWidgets import QGraphicsView
        out = []
        for i in range(self._chart_stack.count()):
            page = self._chart_stack.widget(i)
            for v in [page] + page.findChildren(QGraphicsView):
                if hasattr(v, "_compute_fit_zoom") and hasattr(v, "zoom_factor") and v not in out:
                    out.append(v)
        return out

    def _fit_snapshot(self):
        """Views at their fit zoom BEFORE a shelf change (plan A.4/D10); a view
        the user zoomed or panned keeps its zoom."""
        at_fit = []
        for v in self._views():
            try:
                fit = v._compute_fit_zoom()
                if abs(v.zoom_factor - fit) <= 1e-3 * max(fit, 1e-6):
                    at_fit.append(v)
            except RuntimeError:
                continue
        return at_fit

    def _apply_refit(self, views, now: bool = False) -> None:
        if not views:
            return
        self._gui.chart_tab.layout().activate()
        for v in views:
            try:
                if v.isVisible() and now:
                    v.reset_zoom()
                elif v.isVisible():
                    QTimer.singleShot(0, v, lambda v=v: v.reset_zoom())
                else:
                    self._needs_refit.add(v)       # hidden page: refit on show (D10)
            except RuntimeError:
                continue

    def _refit_shown_page(self, _index=None) -> None:
        for v in list(self._needs_refit):
            try:
                if v.isVisible():
                    self._needs_refit.discard(v)
                    QTimer.singleShot(0, v, lambda v=v: v.reset_zoom())
            except RuntimeError:
                self._needs_refit.discard(v)

    # ------------------------------------------------------- right drawer (D2a)
    def toggle_right_drawer(self) -> None:
        if not self._drawer_mode:
            return
        self._slide(open_=not self._drawer_open)

    def _drawer_widgets(self):
        out = [(self._scroll, scaled_px(INFO_MIN_BASE))]
        if self._effective != "bottom":
            out.append((self._dasha, self._dasha_w(self._effective)))
        return out

    def _set_drawer_mode(self, on: bool) -> None:
        self._stop_drawer_anims()
        self._drawer_mode = on
        self._drawer_open = False
        for w, width in self._drawer_widgets():
            _fix(w, width)
            w.setVisible(not on)
        self._toggle.setText("◀")
        self._toggle.setVisible(on)

    def _slide(self, *, open_: bool) -> None:
        self._stop_drawer_anims()
        ms = 0 if self._reduce_motion() else self._gui.DRAWER_ANIM_MS
        for w, width in self._drawer_widgets():
            w.setMinimumWidth(0)
            anim = QPropertyAnimation(w, b"maximumWidth", self)
            anim.setDuration(ms)
            if open_:
                w.setMaximumWidth(0)
                w.setVisible(True)
                anim.setStartValue(0)
                anim.setEndValue(width)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(lambda w=w, width=width: _fix(w, width))
            else:
                anim.setStartValue(width)
                anim.setEndValue(0)
                anim.setEasingCurve(QEasingCurve.Type.InCubic)
                anim.finished.connect(lambda w=w: w.setVisible(False))
            anim.finished.connect(anim.deleteLater)
            anim.start()
            self._drawer_anims.append(anim)
        self._drawer_open = open_
        self._toggle.setText("▶" if open_ else "◀")

    def _settle_drawer(self) -> None:
        """A stopped slide leaves partial widths: put the drawer at its end state."""
        for w, width in self._drawer_widgets():
            _fix(w, width)
            w.setVisible(self._drawer_open)

    def _stop_drawer_anims(self) -> None:
        for anim in self._drawer_anims:
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:                   # already deleted on finish
                pass
        self._drawer_anims.clear()

    # ------------------------------------------- two-chart mode (SPEC-DUAL-001)
    def two_chart(self) -> bool:
        return self._two

    def owns_widget(self, w) -> bool:
        """``_set_left_compact`` skips a widget the layout manager has taken
        (the sign column lives in the info drawer while paired, §4.3)."""
        return self._two and w is not None and w in (self._sign, self._scroll)

    def b_host_index(self) -> int:
        """Row index right after chart_stack (where chart B's frame lives)."""
        return self._row.indexOf(self._chart_stack) + 1

    def info_drawer_open(self) -> bool:
        return self._info_drawer_open

    def rail(self):
        return self._rail

    def drawer_host(self):
        return self._drawer_host

    def set_two_chart(self, on: bool, *, before=None) -> None:
        """The ONLY entry point of the two-chart geometry (§4.3). Settles any
        running motion first, then changes the geometry instantly; only the
        rail slides in, and on exit the dasha slides back with its own move.
        ``before`` runs after the fit snapshot and before any geometry change
        (the pair's frames and header band), so the snapshot sees the views as
        they were; on exit the snapshot also rides the dasha move, which
        refits at its end (or when fullscreen settles it)."""
        on = bool(on)
        if not self._installed or on == self._two or self._fullscreen:
            if before is not None:
                before()
            return
        self._settle_motion()
        refit = self._fit_snapshot()
        if before is not None:
            before()
        if on:
            self._enter_two()
        else:
            self._refit_carry = list(refit)
            self._exit_two()
            self._refit_carry = []
        self._apply_refit(refit)

    def _settle_anim(self) -> None:
        """Stop the dasha move and put it at the target of the stopped move."""
        if self._anim is None:
            return
        target = self._anim_target or self._effective
        refit, self._anim_refit = self._anim_refit, []   # the stopped move's refit is owed
        self._stop_anim()                          # its finished never fires now
        self._effective = target
        if target == "bottom":
            self._slot.setVisible(False)
            self._shelf.setFixedHeight(self._shelf_h())
        elif self._dasha.parentWidget() is self._shelf:
            self._undock(target)
        else:
            self._dasha.set_presentation(target)
            _fix(self._dasha, self._dasha_w(target))
        _fix(self._scroll, self._info_for(self._left_mode(), target, self._content.width()))
        self._apply_refit(refit, now=True)         # before a fullscreen capture reads zoom

    def _settle_motion(self) -> None:
        """Every running motion stopped and jumped to its end state; late
        callbacks are disarmed (animation identity / generation counters)."""
        self._settle_anim()
        if self._drawer_anims:
            self._stop_drawer_anims()
            self._settle_drawer()
        if self._rail is not None:
            self._rail.stop_slide()
        if self._drawer_host is not None:
            self._drawer_host.stop()
        self.close_info_drawer()

    def _chart_min_two(self) -> int:
        each = max(scaled_px(CHART_MIN_TWO_BASE), self._chart_stack.minimumSizeHint().width())
        return 2 * each + self._row.spacing()

    def _fixed_two(self, left: str) -> int:
        """Row width of everything except the two charts (§4.3): the left
        group (or its toggle / open drawer), the rail, margins and gaps."""
        m = self._row.contentsMargins()
        targets = self._gui._panel_target_widths
        gui = self._gui
        if left == "full":
            items = [targets[gui.vedanga_panel], targets[gui.varga_column]]
        else:
            items = [gui._left_toggle.width()]
            if left == "drawer":
                items += [targets[gui.vedanga_panel], targets[gui.varga_column]]
        items.append(self._rail.width())
        return m.left() + m.right() + sum(items) + self._row.spacing() * len(items)

    def _apply_two(self) -> None:
        gui = self._gui
        row = self._content.width()
        was_compact = gui._left_toggle.isVisible()
        restore_at = (self._fixed_two("full") + self._chart_min_two()
                      + (HYSTERESIS if was_compact else 0))
        gui._set_left_compact(not gui._side_panels_visible or row < restore_at)
        if was_compact != gui._left_toggle.isVisible():
            self.close_info_drawer()               # a resize across the fold point
        self._place_drawer()
        if self._info_drawer_open:
            self.info_stack().set_available_size(self._scroll.viewport().size())
        gui._align_status_controls()

    def _place_drawer(self) -> None:
        host = self._drawer_host
        rail = self._rail
        targets = self._gui._panel_target_widths
        m = self._row.contentsMargins()
        width = (host.shadow_width() + targets[self._sign] + host.layout().spacing()
                 + self._info_base)
        top = m.top()
        height = max(0, self._content.height() - m.top() - m.bottom())
        right = rail.geometry().left() if rail.isVisible() else self._content.width() - m.right()
        from PySide6.QtCore import QRect
        host.set_target_geometry(QRect(right - width, top, width, height))

    def _enter_two(self) -> None:
        self._two_intent = (self._position, self._user_rail, self._auto_folded)
        self._pending_position = None              # fullscreen-queued request dropped
        if self._drawer_mode:                      # the D2a drawer is not used in mode two
            self._set_drawer_mode(False)
        self._two = True
        self._set_presentation_now("bottom")       # transient, never persisted (INV-5)
        self._dasha.set_return_allowed(False)
        host_lay = self._drawer_host.content_layout()
        for key, w in (("sign", self._sign), ("info", self._scroll)):
            ph = QWidget(self._content)
            ph.setVisible(False)
            self._row.replaceWidget(w, ph)
            self._placeholders[key] = ph
            host_lay.addWidget(w)
        targets = self._gui._panel_target_widths
        _fix(self._sign, targets[self._sign])
        self._sign.setVisible(True)
        _fix(self._scroll, self._info_base)
        self._scroll.setVisible(True)
        self.info_stack().set_drawer_hold(True)
        self._rail.set_labels(self._rail_labels())
        self._rail.slide_in()
        self._apply()

    def _exit_two(self) -> None:
        self.close_info_drawer()
        self._rail.stop_slide()
        self._rail.setVisible(False)
        host_lay = self._drawer_host.content_layout()
        for key, w in (("sign", self._sign), ("info", self._scroll)):
            host_lay.removeWidget(w)
            ph = self._placeholders.pop(key, None)
            if ph is not None:
                self._row.replaceWidget(ph, w)
                ph.deleteLater()                   # after the child is back (Rule 18)
        gui = self._gui
        _fix(self._sign, gui._panel_target_widths[self._sign])
        self._sign.setVisible(not gui._left_toggle.isVisible())
        self._scroll.setVisible(True)
        self.info_stack().set_drawer_hold(False)
        self._two = False
        pos, user_rail, auto_folded = self._two_intent or ("side", False, False)
        self._two_intent = None
        self._position, self._user_rail, self._auto_folded = pos, user_rail, auto_folded
        self._dasha.set_return_allowed(True)
        _fix(self._scroll, self._info_for(self._left_mode(), self._wanted(),
                                          self._content.width()))
        self._show(self._wanted())                 # the dasha slides back (200 ms)
        self.schedule()

    @staticmethod
    def _rail_labels():
        from core.i18n import t
        return [t("panel.info.title.karakas", "Karakas"),
                t("panel.info.title.strength", "Strength"),
                t("panel.info.title.aspects", "Aspects")]

    def toggle_info_drawer(self) -> None:
        """Rail click (T19)."""
        if not self._two:
            return
        if self._info_drawer_open:
            self.close_info_drawer()
        else:
            self.open_info_drawer()

    def open_info_drawer(self, animated: bool = True) -> None:
        if not self._two or self._info_drawer_open or self._fullscreen:
            return
        self._place_drawer()
        self._info_drawer_open = True
        self._drawer_host.open(animated=animated)
        self._esc.setEnabled(True)
        if self._press_filter is None:
            from managers.context_menu_manager import install_app_filter
            self._press_filter = _OutsidePressFilter(self)
            install_app_filter(self._press_filter)   # off while a web view exists
        self.info_stack().set_drawer_hold(False)  # the held controllers drain once
        self._gui.chart_tab.layout().activate()
        self.info_stack().set_available_size(self._scroll.viewport().size())

    def close_info_drawer(self) -> None:
        """Esc, a press outside, the rail, a mode change, a fold-point resize
        or fullscreen entry (T19). Instant."""
        if self._press_filter is not None:
            from managers.context_menu_manager import remove_app_filter
            remove_app_filter(self._press_filter)
            self._press_filter.deleteLater()
            self._press_filter = None
        if self._esc is not None:
            self._esc.setEnabled(False)
        if not self._info_drawer_open:
            return
        self._info_drawer_open = False
        self._drawer_host.close()
        if self._two:
            self.info_stack().set_drawer_hold(True)

    def _on_outside_press(self, global_pos) -> None:
        for w in (self._drawer_host, self._rail):
            if w is not None and w.isVisible() and w.rect().contains(w.mapFromGlobal(global_pos)):
                return
        self.close_info_drawer()

    def teardown(self) -> None:
        """Stop the animations and remove the application event filter."""
        try:
            self._stop_anim()
            self._stop_drawer_anims()
            if self._rail is not None:
                self._rail.stop_slide()
            if self._drawer_host is not None:
                self._drawer_host.stop()
        except RuntimeError:
            pass
        self.close_info_drawer()

    @staticmethod
    def _reduce_motion() -> bool:
        from managers.settings_manager import get_settings
        return bool(get_settings().get("ui.reduce_motion"))


class _OutsidePressFilter(QObject):
    """Application event filter, installed only while the info drawer is open:
    a mouse press outside the drawer and the rail closes it (T19)."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                pos = event.globalPosition().toPoint()
            except AttributeError:
                return False
            QTimer.singleShot(0, lambda p=pos: self._owner._on_outside_press(p))
        return False
