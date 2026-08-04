# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Universal fullscreen for any chart-displaying surface — SPEC-FSV-001.

Rule 4: the fullscreen mechanism lives here, not in ``core_gui_qt``.

What this does — and, as importantly, does not
----------------------------------------------
``enter_fullscreen()`` resolves the CURRENT tab's fullscreen surface (a
duck-typed *descriptor*, below), lifts that surface's widget out of its owning
layout slot into a frameless top-level window shown full-screen, and
``exit_fullscreen()`` puts it back in the exact slot with the exact zoom, pan
and scroll every live view had. It is SESSION-ONLY: nothing is persisted (the
two-instance ``profiles/`` trap, SPEC-SES-001). Pop-out windows,
picture-in-picture and zoom animation are explicitly PLAN-2 — not here.

Originally (SAFE PLAN-1) this fullscreened ONLY the main ``chart_stack``. The
generalization (universal-fullscreen) keeps that single reparent/fit/restore
engine and drives it from a host-supplied descriptor so F fullscreens the
CORRECT surface on every tab: Chart (incl. the page-3 dual body/aspect view),
Eclipse Reading, Compatibility, Transit, Solar Return, Nakshatra, Antikythera.

The descriptor (host-owned, plain dict — no shared class, so the manager keeps
NO import of any host and stays in the Lite/Core allowlist)
--------------------------------------------------------------------------
Resolved fresh on every F via ``_resolve_target()``:

    {
      "widget":  QWidget,           # what reparents into the fullscreen window
      "layout":  QLayout,           # the OWNING layout, captured by the host at
                                    #   CONSTRUCTION time. A widget added to a
                                    #   nested sub-layout via addLayout() has
                                    #   indexOf() == -1 on the panel's top-level
                                    #   layout, so we can NEVER infer the layout
                                    #   from parentWidget().layout() — the host
                                    #   hands us the real one (Transit/SR blocker).
      "views":   callable -> list,  # live QGraphicsViews to save/refit NOW.
                                    #   Re-evaluated on every (re)fit, so it must
                                    #   reflect whatever is visible at call time
                                    #   (overlay engaged -> [left] only, etc.).
      "refit":   bool,              # True  -> reset_zoom() each view to fill.
                                    #   False -> free-pan surface (Antikythera):
                                    #   its showEvent recenters unconditionally,
                                    #   so on ENTER we replay the saved transform
                                    #   + scrollbars instead of refitting.
      "cycle":   bool,              # True only for chart_stack -> F2 cycles the
                                    #   chart page (a GLOBAL style broadcast; must
                                    #   NOT fire under a dual widget).
      "refit_signals": [Signal],    # optional. Connected on enter, each fires
                                    #   -> refit current views(); disconnected on
                                    #   exit. Used for internal mode/overlay flips
                                    #   the outer currentChanged never sees
                                    #   (overlay_toggled / overlay_state_changed /
                                    #   chart_stack.currentChanged for F2).
      "on_enter": callable | None,  # optional host hook: aux-pane policy
                                    #   (disable tajika button, snapshot splitter).
      "on_exit":  callable | None,  # optional host hook: restore splitter,
                                    #   re-enable controls.
      "floating_controls": [dict],  # optional. Each spec builds a checkable
                                    #   toggle in the floating capsule so a
                                    #   control that lived in a now-hidden top
                                    #   band stays reachable in fullscreen:
                                    #     {"text", "read"->bool, "write"(bool),
                                    #      "visible"->bool?, "enabled"->bool?}
                                    #   Put the SAME changed-Signal in
                                    #   refit_signals so the flip both refits and
                                    #   re-syncs the capsule (single source of
                                    #   truth; QSignalBlocker breaks the loop).
      "alternate": dict | None,     # optional (Compatibility). A SECOND surface
                                    #   the Chart<->x slider flips to:
                                    #     {"widget", "owner"(QSplitter),
                                    #      "label", "prepare"->bool}
                                    #   prepare() lazily builds/populates it and
                                    #   returns False to veto the flip (e.g. kuta
                                    #   needs both charts). The manager snapshots
                                    #   the owner slot/sizes/collapsible/hidden
                                    #   and restores them EXACTLY on exit — the
                                    #   slider is presentation-only, never state.
    }

The fit trap (PM-1 / PM-g)
--------------------------
The chart QGraphicsViews auto-fit exactly once (guarded by
``_fit_zoom_applied``) and never refit on resize. A naive reparent therefore
re-applies the OLD windowed zoom, marooning a small chart in a huge black
rectangle. So on ENTER we force each current view to refit to the fullscreen
viewport via its OWN ``reset_zoom()`` — never duplicated fit math — and on EXIT
we restore each saved transform + scrollbars AFTER the re-show settles, because
each view's ``showEvent`` re-applies ``zoom_factor`` on becoming visible and
would otherwise clobber a synchronous restore (PM-3). Save/restore loops the
view list with per-view RuntimeError isolation so one dead C++ view cannot abort
the others' restore.

Key handling (probe-driven, 2026-07-30)
---------------------------------------
* Enter (windowed): the QAction("F") on ChartGUI (WindowShortcut). Text inputs
  keep typing "f" via ShortcutOverride.
* Exit (fullscreen): a ``QShortcut(QKeySequence("F"), container)`` — a focused
  non-editable QComboBox eats plain-letter keyPressEvents for type-ahead, but a
  WindowShortcut fires BEFORE the combo sees the key, so F always exits even
  with a combo focused. The container ``keyPressEvent`` keeps F as a fallback.
* Esc stays keyPressEvent-propagated — deliberately NOT a shortcut: the Cards of
  Truth ladder unwind depends on the view seeing Esc FIRST and accepting it only
  when there is something to unwind. A WindowShortcut Esc would steal that.
  Combos do not consume Esc, so the propagated path suffices.
* F2 is gated on ``cycle`` — chart_stack only.
"""

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QGraphicsView, QHBoxLayout, QLabel,
                               QSlider, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)


class _FullscreenContainer(QWidget):
    """The frameless top-level that holds the fullscreened surface.

    Owns F/Esc/F2 keys itself: while fullscreen the surface widget is reparented
    into this window, so key events land here, not on ChartGUI. The QAction("F")
    on ChartGUI is out of the widget tree while this window is active, so the two
    never fight over the key.

    Two optional overlays sit ON TOP of the reparented surface (SPEC-FSV-001
    §3.7, the chart-area-only rework):

    * a ``QStackedWidget`` content area used ONLY when the descriptor carries an
      ``alternate`` (Compatibility: chart page 0, kuta-table page 1). Without an
      alternate the primary widget mounts directly, preserving the original
      single-widget path byte-for-byte.
    * a floating control ``_capsule`` (a shrink-wrapped child QFrame pinned
      top-right in ``resizeEvent``) that carries the Overlay toggle(s) and, when
      an alternate exists, the Chart<->Kuta slider. It reserves NO layout height
      and only its own small rect intercepts input, so pan/zoom everywhere else
      still reaches the chart — the whole point of the rework (the top band that
      "killed" the fullscreen view is gone; the useful buttons float instead).
    """

    def __init__(self, on_exit, on_cycle_view, background, can_cycle):
        super().__init__(
            None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._on_exit = on_exit
        self._on_cycle_view = on_cycle_view
        self._can_cycle = can_cycle
        self.setStyleSheet(f"background-color: {background};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.body_layout = lay
        self._content_stack = None      # QStackedWidget iff an alternate exists
        self._capsule = None            # floating controls QFrame, or None
        self._capsule_buttons = []      # [(QToolButton, spec_dict), ...]
        self._slider = None             # Chart<->alternate QSlider, or None
        # True while the alternate (kuta) page is shown: the Overlay toggle(s)
        # do not apply there and MUST stay hidden even when a later refit signal
        # calls sync_capsule() (gpt-5.6-sol probe: sync re-showed them).
        self._toggles_suppressed = False

    # -- content mounting -------------------------------------------------

    def mount(self, primary, alternate=None):
        """Mount the primary chart surface (and optional alternate).

        With an alternate the two share a ``QStackedWidget`` so the slider flips
        between them with no second reparent; without one the primary mounts
        directly (original path). QStackedWidget force-shows its current page, so
        an alternate that was hidden in its windowed dock renders when selected —
        its windowed hidden-state is restored on exit by the manager."""
        if alternate is not None:
            stack = QStackedWidget(self)
            stack.addWidget(primary)        # index 0 = chart
            stack.addWidget(alternate)      # index 1 = alternate (kuta table)
            self.body_layout.addWidget(stack)
            self._content_stack = stack
        else:
            self.body_layout.addWidget(primary)

    def take_content(self, primary, alternate=None):
        """Detach primary/alternate from the container BEFORE teardown, so
        deleting the container cannot delete a live reparented child (Rule 18)."""
        for w in (primary, alternate):
            if w is None:
                continue
            try:
                if self._content_stack is not None:
                    self._content_stack.removeWidget(w)
                else:
                    self.body_layout.removeWidget(w)
            except RuntimeError:
                pass

    def set_content_index(self, i):
        if self._content_stack is not None:
            try:
                self._content_stack.setCurrentIndex(i)
            except RuntimeError:
                pass

    # -- floating control capsule -----------------------------------------

    def build_capsule(self, control_specs, slider_spec):
        """Build the floating top-right capsule (Overlay toggles + optional
        Chart<->alternate slider). Positioned in ``resizeEvent``; never in the
        layout, so it steals no chart space."""
        cap = QFrame(self)
        cap.setObjectName("fsv_capsule")
        cap.setStyleSheet(
            "#fsv_capsule { background-color: rgba(24, 24, 24, 200);"
            " border: 1px solid rgba(255, 255, 255, 70); border-radius: 9px; }"
            " QToolButton { color: #eee; background: rgba(70,70,70,180);"
            " border: 1px solid rgba(255,255,255,50); border-radius: 5px;"
            " padding: 3px 10px; }"
            " QToolButton:checked { background: rgba(230,180,60,220);"
            " color: #111; }"
            " QLabel { color: #ddd; }")
        row = QHBoxLayout(cap)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(9)

        self._capsule_buttons = []
        for spec in control_specs or []:
            btn = QToolButton(cap)
            btn.setText(spec.get("text", ""))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # NoFocus: clicking the toggle must not pull keyboard focus off the
            # chart view (F stays a WindowShortcut, but arrow-pan should keep
            # working right after a click).
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            on_click = spec.get("_on_click")
            if callable(on_click):
                btn.toggled.connect(on_click)
            row.addWidget(btn)
            self._capsule_buttons.append((btn, spec))

        self._slider = None
        if slider_spec is not None:
            row.addWidget(QLabel(slider_spec.get("left_label", "Chart"), cap))
            sld = QSlider(Qt.Orientation.Horizontal, cap)
            sld.setRange(0, 1)
            sld.setPageStep(1)
            sld.setFixedWidth(64)
            sld.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            on_change = slider_spec.get("_on_change")
            if callable(on_change):
                sld.valueChanged.connect(on_change)
            row.addWidget(sld)
            row.addWidget(QLabel(slider_spec.get("right_label", "Table"), cap))
            self._slider = sld

        self._capsule = cap
        cap.show()
        self._position_capsule()

    def set_slider_value(self, value):
        """Set the slider without re-firing valueChanged (revert-on-failure)."""
        if self._slider is not None:
            with QSignalBlocker(self._slider):
                self._slider.setValue(value)

    def set_toggles_visible(self, visible):
        """Show/hide the Overlay toggle(s) — hidden on the alternate page where
        overlay does not apply. Sets ``_toggles_suppressed`` so a later
        sync_capsule() honours the page state. When re-showing, each toggle
        re-consults its own ``visible`` predicate."""
        self._toggles_suppressed = not visible
        for btn, spec in self._capsule_buttons:
            try:
                if visible:
                    vis = spec.get("visible")
                    btn.setVisible(bool(vis()) if callable(vis) else True)
                else:
                    btn.setVisible(False)
            except Exception:                            # noqa: BLE001
                pass
        self._position_capsule()

    def sync_capsule(self):
        """Re-affirm each toggle's checked/visible/enabled from its predicates
        (called after any refit signal), under a signal block so mirroring the
        real button's state never re-fires the write() path (no toggle loop).
        While the alternate page is shown (``_toggles_suppressed``) the toggles
        stay hidden regardless of their own ``visible`` predicate."""
        for btn, spec in self._capsule_buttons:
            try:
                read = spec.get("read")
                if callable(read):
                    with QSignalBlocker(btn):
                        btn.setChecked(bool(read()))
                if self._toggles_suppressed:
                    btn.setVisible(False)
                else:
                    vis = spec.get("visible")
                    if callable(vis):
                        btn.setVisible(bool(vis()))
                en = spec.get("enabled")
                if callable(en):
                    btn.setEnabled(bool(en()))
            except Exception:                            # noqa: BLE001
                pass

    def _position_capsule(self):
        cap = self._capsule
        if cap is None:
            return
        try:
            cap.adjustSize()
            margin = 12
            x = max(margin, self.width() - cap.width() - margin)
            cap.move(x, margin)
            cap.raise_()
        except RuntimeError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_capsule()

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_F, Qt.Key.Key_Escape):
            # F here is a fallback: the container QShortcut normally handles F
            # first (and beats a focused combo's type-ahead). Esc is ONLY here —
            # never a shortcut — so a view's own Escape ladder sees it first.
            self._on_exit()
            event.accept()
            return
        # F2 cycles the chart page WITHOUT leaving fullscreen — but ONLY for the
        # chart_stack (cycle=True). _cycle_chart_view is a GLOBAL style broadcast;
        # firing it under a dual widget would restyle every hidden panel.
        if key == Qt.Key.Key_F2 and self._can_cycle:
            self._on_cycle_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        # A window-manager close (Alt+F4, wmctrl) on this frameless top-level
        # would otherwise just HIDE it, stranding the reparented surface inside a
        # hidden window while the main window shows an empty slot and the manager
        # still thinks it is fullscreen. Route it through the normal exit so the
        # widget goes home first (Codex review).
        self._on_exit()
        event.accept()


class ViewFloatManager:
    """Enter/exit fullscreen for the active tab's chart surface. Idempotent."""

    def __init__(self, gui):
        self._gui = gui
        self._container = None
        self._saved = None       # restore state while fullscreen, else None
        self._shortcut = None    # QShortcut("F") on the container while fullscreen
        self._signal_conns = []  # refit_signals connected this session

    @property
    def is_fullscreen(self):
        return self._container is not None

    # -- target resolution ------------------------------------------------

    def _resolve_target(self):
        """Walk the active-tab chain to a fullscreen descriptor, or None.

        ``gui.tab_widget.currentWidget()`` is the active host. Every host that
        owns a chart surface exposes ``fullscreen_target()`` (duck-typed, like
        the existing ``on_page_shown`` protocol); EclipsePanel implements it by
        FORWARDING to ``content_stack.currentWidget().fullscreen_target()``.
        Tabs without the method (Edit Chart, Find Chart, Birth Finder, AI Tools,
        Settings) return None here -> no-op with a status message. That is the
        whole point of the generalization: F no longer lifts the Chart tab's
        stack from a tab where it is not even visible.
        """
        gui = self._gui
        tabs = getattr(gui, "tab_widget", None)
        if tabs is None:
            return None
        host = tabs.currentWidget()
        target_fn = getattr(host, "fullscreen_target", None)
        if callable(target_fn):
            try:
                return target_fn()
            except Exception as exc:                     # noqa: BLE001
                print(f"[FSV] fullscreen_target() raised on "
                      f"{type(host).__name__}: {exc}")
                return None
        return None

    def _current_tab_name(self):
        tabs = getattr(self._gui, "tab_widget", None)
        if tabs is None:
            return "this tab"
        return tabs.tabText(tabs.currentIndex()) or "this tab"

    def _status_message(self, text):
        try:
            self._gui.statusBar().showMessage(text, 4000)
        except Exception:                                # noqa: BLE001
            pass

    # -- view-state helpers -----------------------------------------------

    @staticmethod
    def _is_graphics_view(view):
        return isinstance(view, QGraphicsView)

    def _save_view_state(self, view):
        """Snapshot one live QGraphicsView's zoom + pan, or None if unusable.

        ``scene_center`` (the scene point under the viewport centre) is captured
        alongside the raw scrollbar values because scrollbar values are
        viewport-SIZE relative: replaying them into the much larger fullscreen
        viewport clamps to a smaller range and shifts the pan. For free-pan
        surfaces (refit=False) we restore via ``centerOn(scene_center)`` instead,
        which is viewport-size independent (PM-d). refit=True surfaces keep the
        battle-tested scrollbar restore (same viewport size on exit)."""
        if not self._is_graphics_view(view):
            return None
        try:
            scene_center = None
            vp = view.viewport()
            if vp is not None and vp.width() > 0 and vp.height() > 0:
                scene_center = view.mapToScene(vp.rect().center())
            return {
                "view": view,
                "transform": view.transform(),
                "zoom_factor": getattr(view, "zoom_factor", None),
                # Some views (wheel_view) carry a manual-zoom lock; reset_zoom on
                # enter clears it, so capture and restore it or a later
                # _refit_if_auto discards the user's restored zoom (codex M-4).
                "user_zoomed": getattr(view, "user_zoomed", None),
                "h": view.horizontalScrollBar().value(),
                "v": view.verticalScrollBar().value(),
                "scene_center": scene_center,
                "pan_via_center": False,   # set per-descriptor in enter_fullscreen
            }
        except RuntimeError:
            return None

    def _current_views(self):
        """The descriptor's live views() right now (empty on any failure)."""
        saved = self._saved or {}
        desc = saved.get("descriptor") or {}
        views_fn = desc.get("views")
        if not callable(views_fn):
            return []
        try:
            return [v for v in (views_fn() or []) if self._is_graphics_view(v)]
        except Exception:                                # noqa: BLE001
            return []

    @staticmethod
    def _safe_reset_zoom(view):
        """Call view.reset_zoom(), tolerant of a view whose C++ object died
        between scheduling and firing (codex M-3: a bare singleShot on a dead
        view would raise inside the timer callback)."""
        try:
            reset = getattr(view, "reset_zoom", None)
            if callable(reset):
                reset()
        except RuntimeError:
            pass

    @staticmethod
    def _safe_set_sizes(splitter, sizes):
        """Re-apply saved QSplitter sizes, tolerant of a dead C++ splitter."""
        try:
            splitter.setSizes(sizes)
        except RuntimeError:
            pass

    def _refit(self, view):
        """Refit ``view`` via its own fit logic, queued so it runs after the
        geometry change (reparent / fullscreen / mode switch) has settled —
        ``reset_zoom`` reads the live viewport size. Guarded against a view that
        dies before the queued call fires."""
        if getattr(view, "reset_zoom", None) is not None:
            QTimer.singleShot(0, lambda v=view: self._safe_reset_zoom(v))

    def _refit_current(self):
        # Views that first become visible DURING fullscreen (an overlay/mode
        # flip, an F2 page cycle) get refit to the fullscreen viewport here but
        # were never in the enter snapshot; record them so exit can refit them
        # back to the windowed viewport instead of leaving fullscreen zoom
        # stranded in the smaller window (codex H-1).
        saved = self._saved or {}
        enter_ids = saved.get("enter_view_ids") or set()
        extra = saved.get("extra_views")
        seen = saved.get("extra_view_ids")
        for view in self._current_views():
            if extra is not None and seen is not None:
                vid = id(view)
                if vid not in enter_ids and vid not in seen:
                    seen.add(vid)
                    extra.append(view)
            self._refit(view)

    def _restore_view_state(self, vs):
        """Re-affirm one saved view's transform + pan. Tolerant of dead C++."""
        view = vs["view"]
        try:
            if vs["zoom_factor"] is not None:
                view.zoom_factor = vs["zoom_factor"]
            # Restore the manual-zoom lock so a later _refit_if_auto keeps the
            # user's zoom (codex M-4).
            if vs.get("user_zoomed") is not None:
                view.user_zoomed = vs["user_zoomed"]
            view.setTransform(vs["transform"])
            if vs.get("pan_via_center") and vs.get("scene_center") is not None:
                # Free-pan surface across a viewport-size change: centre on the
                # saved scene point (scrollbar values would clamp/shift, PM-d).
                view.centerOn(vs["scene_center"])
            else:
                view.horizontalScrollBar().setValue(vs["h"])
                view.verticalScrollBar().setValue(vs["v"])
        except RuntimeError:
            # The C++ view is gone (tab torn down mid-exit) — nothing to restore.
            pass

    # -- refit_signals ----------------------------------------------------

    def _on_refit_signal(self, *_args):
        """A descriptor refit_signal fired (overlay/mode/page flip): refit the
        NEWLY-shown views AND re-sync the floating capsule so its toggle mirrors
        the panel's real (hidden) button. Accepts any signal signature."""
        if self.is_fullscreen:
            self._refit_current()
            if self._container is not None:
                self._container.sync_capsule()

    def _connect_refit_signals(self, signals):
        for sig in signals or []:
            try:
                sig.connect(self._on_refit_signal)
                self._signal_conns.append(sig)
            except Exception:                            # noqa: BLE001
                pass

    def _disconnect_refit_signals(self):
        for sig in self._signal_conns:
            try:
                sig.disconnect(self._on_refit_signal)
            except Exception:                            # noqa: BLE001
                pass
        self._signal_conns = []

    # -- enter ------------------------------------------------------------

    def enter_fullscreen(self):
        if self.is_fullscreen:
            return
        gui = self._gui
        desc = self._resolve_target()
        if not desc:
            self._status_message(
                f"No fullscreen chart surface on the {self._current_tab_name()} tab")
            return

        widget = desc.get("widget")
        layout = desc.get("layout")
        if widget is None or layout is None:
            self._status_message(
                f"Fullscreen unavailable on the {self._current_tab_name()} tab")
            return
        index = layout.indexOf(widget)
        if index < 0:
            # The widget is not in the layout the host handed us — refuse rather
            # than crash. (A -1 here means the host captured the wrong layout;
            # for nested body_layouts the host MUST hand the sub-layout.)
            print("[FSV] target widget not found in its owning layout; "
                  "fullscreen aborted")
            self._status_message(
                f"Fullscreen unavailable on the {self._current_tab_name()} tab")
            return

        refit = bool(desc.get("refit", True))

        # Validate the alternate (Compatibility kuta page) BEFORE moving
        # anything — a half-move that stranded a widget is pre-mortem #6. We only
        # commit to the alternate if its owner slot resolves; otherwise fall back
        # to a plain single-surface fullscreen (chart still fills the screen).
        alternate = desc.get("alternate") or None
        alt_state = None
        if alternate:
            alt_widget = alternate.get("widget")
            owner = alternate.get("owner")
            alt_index = owner.indexOf(alt_widget) if (
                alt_widget is not None and owner is not None
                and hasattr(owner, "indexOf")) else -1
            if alt_index < 0:
                print("[FSV] alternate widget not in its owner splitter; "
                      "fullscreen proceeds without the alternate page")
                alternate = None
            else:
                alt_state = {
                    "widget": alt_widget,
                    "owner": owner,
                    "index": alt_index,
                    # isHidden(), NOT isVisible(): the kuta dock is explicitly
                    # hidden when windowed, and only the explicit-hidden intent
                    # must be restored (pre-mortem #3).
                    "hidden": alt_widget.isHidden(),
                    "sizes": (owner.sizes() if hasattr(owner, "sizes")
                              else None),
                    "collapsible": (owner.isCollapsible(alt_index)
                                    if hasattr(owner, "isCollapsible")
                                    else None),
                }

        # Save the layout slot and EVERY current view's zoom state BEFORE
        # anything moves. views() is re-evaluated here so overlay/mode state at
        # enter is captured correctly.
        view_states = []
        try:
            live_views = [v for v in (desc.get("views", lambda: [])() or [])
                          if self._is_graphics_view(v)]
        except Exception:                                # noqa: BLE001
            live_views = []
        for view in live_views:
            vs = self._save_view_state(view)
            if vs is not None:
                # Free-pan surfaces (refit=False) restore pan via centerOn, which
                # survives the fullscreen viewport-size change; refit=True keeps
                # the scrollbar path (charts refit-to-fill anyway).
                vs["pan_via_center"] = not refit
                view_states.append(vs)

        self._saved = {
            "descriptor": desc,
            "index": index,
            "stretch": layout.stretch(index),
            "view_states": view_states,
            # Views visible at enter — restored to their EXACT windowed state on
            # exit. Views that appear later (overlay/mode/F2) accumulate in
            # extra_views and are refit to the windowed viewport on exit instead
            # (codex H-1).
            "enter_view_ids": {id(v) for v in live_views},
            "extra_views": [],
            "extra_view_ids": set(),
            "alt_state": alt_state,
            # QStackedWidget.removeWidget() (the alternate path) HIDES the removed
            # page and reinsertion into a layout does not clear that; snapshot the
            # primary's own hidden intent so exit restores it (gpt-5.6-sol F1: the
            # Compatibility chart area went blank after the first cycle).
            "prim_hidden": bool(widget.isHidden()) if widget is not None else False,
        }

        # Host hook (aux-pane policy: disable tajika button, snapshot splitter)
        # BEFORE the reparent, so the snapshot reflects the windowed geometry.
        self._call_hook(desc.get("on_enter"))

        from ui.qt_theme import get_theme_colors
        background = get_theme_colors().get("secondary_dark", "#000000")
        self._container = _FullscreenContainer(
            self.exit_fullscreen, self._cycle_view, background,
            can_cycle=bool(desc.get("cycle", False)))

        # Move the widget: remove from the old layout FIRST (reparenting alone
        # leaves a dangling layout item behind), then mount into the container.
        # With an alternate, detach it from its owner splitter and hand both to
        # the container's content stack (chart page + alternate page).
        layout.removeWidget(widget)
        alt_widget = alt_state["widget"] if alt_state else None
        if alt_widget is not None:
            try:
                alt_widget.setParent(None)   # detach from the owner QSplitter
            except RuntimeError:
                alt_widget = None
        self._container.mount(widget, alt_widget)

        # Fullscreen on the SAME monitor as the main window. setScreen() alone
        # does not reliably move a not-yet-shown frameless window on a
        # multi-monitor desktop; seating the geometry to the target screen first
        # does.
        screen = gui.screen()
        if screen is not None:
            self._container.setScreen(screen)
            self._container.setGeometry(screen.geometry())
        self._container.showFullScreen()
        self._container.raise_()
        self._container.activateWindow()

        # A container QShortcut for F beats a focused combo's type-ahead (probe).
        # setAutoRepeat(False): otherwise HOLDING F autorepeats enter->exit->enter
        # (codex M-5); the shortcut fires before the container keyPressEvent's
        # isAutoRepeat guard can help.
        self._shortcut = QShortcut(QKeySequence("F"), self._container)
        self._shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._shortcut.setAutoRepeat(False)
        self._shortcut.activated.connect(self.exit_fullscreen)

        # Focus the first live view, never the widget: a dual widget's combo
        # would otherwise own focus and eat keys.
        focus_target = live_views[0] if live_views else widget
        try:
            focus_target.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            widget.setFocus(Qt.FocusReason.OtherFocusReason)

        if refit:
            # Force each current view to fit the fullscreen viewport (PM-1).
            for view in live_views:
                self._refit(view)
        else:
            # Free-pan surface (Antikythera): its showEvent recenters
            # unconditionally, so replay the saved transform + scrollbars on the
            # ENTER side too, or the pan is lost the moment the container shows.
            for vs in view_states:
                QTimer.singleShot(0, lambda vs=vs: self._restore_view_state(vs))

        # Internal mode/overlay/page flips refit the newly-shown views.
        self._connect_refit_signals(desc.get("refit_signals"))

        # Floating capsule (Overlay toggle[s] + optional Chart<->alternate
        # slider). Built AFTER the surface is shown so it raises above it.
        self._build_floating_capsule(desc.get("floating_controls"), alternate)

    # -- floating capsule wiring ------------------------------------------

    def _build_floating_capsule(self, floating_controls, alternate):
        container = self._container
        if container is None:
            return
        specs = []
        for spec in (floating_controls or []):
            s = dict(spec)                   # copy: never mutate the descriptor

            def _click(checked, write=s.get("write")):
                # The floating toggle writes through the panel's PUBLIC setter,
                # which flips the mode and emits the panel's own changed signal;
                # that signal (also in refit_signals) refits + re-syncs the
                # capsule. The button is never the source of truth.
                if callable(write):
                    try:
                        write(bool(checked))
                    except Exception as exc:             # noqa: BLE001
                        print(f"[FSV] floating control write raised: {exc}")

            s["_on_click"] = _click
            specs.append(s)

        slider_spec = None
        if alternate:
            def _on_slide(value):
                self._on_alternate_slide(int(value), alternate)
            slider_spec = {
                "left_label": "Chart",
                "right_label": alternate.get("label", "Table"),
                "_on_change": _on_slide,
            }

        if specs or slider_spec is not None:
            container.build_capsule(specs, slider_spec)
            container.sync_capsule()

    def _on_alternate_slide(self, value, alternate):
        """Chart<->alternate slider moved. value 1 = alternate page."""
        if not self.is_fullscreen or self._container is None:
            return
        if value == 1:
            prepare = alternate.get("prepare")
            ok = True
            if callable(prepare):
                try:
                    ok = bool(prepare())
                except Exception as exc:                 # noqa: BLE001
                    print(f"[FSV] alternate prepare() raised: {exc}")
                    ok = False
            if not ok:
                # Veto: leave the chart visible, snap the slider back.
                self._container.set_slider_value(0)
                self._status_message(
                    f"{alternate.get('label', 'Alternate')} unavailable")
                return
            self._container.set_content_index(1)
            self._container.set_toggles_visible(False)   # overlay N/A on table
        else:
            self._container.set_content_index(0)
            self._container.set_toggles_visible(True)
            self._refit_current()                        # chart back — refit it

    # -- exit -------------------------------------------------------------

    def exit_fullscreen(self):
        if not self.is_fullscreen:
            return
        # Clear the fullscreen state FIRST so is_fullscreen is False for the rest
        # of teardown: any re-entrant exit (a queued signal, a WM close racing the
        # F key) short-circuits at the guard above.
        saved = self._saved or {}
        self._saved = None
        container = self._container
        self._container = None

        desc = saved.get("descriptor") or {}
        widget = desc.get("widget")
        layout = desc.get("layout")
        refit = bool(desc.get("refit", True))
        view_states = saved.get("view_states", [])
        enter_ids = saved.get("enter_view_ids") or set()
        extra_views = saved.get("extra_views") or []
        alt_state = saved.get("alt_state")
        alt_widget = alt_state["widget"] if alt_state else None

        self._disconnect_refit_signals()

        if self._shortcut is not None:
            try:
                self._shortcut.setParent(None)
                self._shortcut.deleteLater()
            except RuntimeError:
                pass
            self._shortcut = None

        # The reparent/reinsert can raise if the target widget or its owning
        # layout's C++ object died while fullscreen (a tab torn down under us).
        # Do it in try/finally so the frameless container is ALWAYS torn down —
        # otherwise it is stranded on screen over an empty main window (codex H-2).
        try:
            # Detach BOTH primary and alternate from the container first (Rule
            # 18: deleting the container must not take a live child down).
            container.take_content(widget, alt_widget)

            # Restore the alternate (kuta) to its owner splitter EXACTLY: same
            # index, collapsibility, explicit-hidden intent, and sizes. The
            # slider is presentation-only, so the windowed dock must look
            # untouched (pre-mortem #3/#4).
            if alt_state is not None and alt_widget is not None:
                owner = alt_state["owner"]
                a_index = alt_state["index"]
                try:
                    owner.insertWidget(a_index, alt_widget)
                    if alt_state.get("collapsible") is not None:
                        owner.setCollapsible(a_index, alt_state["collapsible"])
                    alt_widget.setVisible(not alt_state.get("hidden", True))
                    sizes = alt_state.get("sizes")
                    if sizes is not None:
                        QTimer.singleShot(
                            0, lambda o=owner, s=sizes: self._safe_set_sizes(o, s))
                except RuntimeError:
                    pass

            # Pre-seat each saved zoom_factor BEFORE the reinsert triggers the
            # view's showEvent (already-fitted showEvent does resetTransform() +
            # scale(zoom_factor)); the queued restore then only re-affirms
            # transform + pan. Robust to the zero-timer vs showEvent order (PM-3).
            for vs in view_states:
                if vs.get("zoom_factor") is not None:
                    try:
                        vs["view"].zoom_factor = vs["zoom_factor"]
                    except RuntimeError:
                        pass

            # Put the widget back in its exact slot AND its original stretch.
            if widget is not None and layout is not None:
                try:
                    layout.insertWidget(saved.get("index", 0), widget,
                                        stretch=saved.get("stretch", 1))
                    # Restore the primary's visibility: the QStackedWidget path
                    # hid it on removeWidget and the reinsert does not undo that
                    # (gpt-5.6-sol F1). isHidden() at enter was False for a shown
                    # chart, so this un-hides it.
                    widget.setVisible(not saved.get("prim_hidden", False))
                except RuntimeError:
                    pass
        finally:
            # Rule 18: the widget is reparented out, so deleting the container
            # cannot take a live child down with it. hide() before deleteLater()
            # so the now-empty window does not flash a black frame.
            try:
                container.setParent(None)
                container.hide()
                container.deleteLater()
            except RuntimeError:
                pass

        # Host hook (restore splitter, re-enable controls) AFTER reinsert.
        self._call_hook(desc.get("on_exit"))

        # Re-affirm each ENTER view's transform + pan AFTER the re-show settles
        # (the showEvent above may have recentred), and refit BACK to the
        # windowed viewport any view that first appeared DURING fullscreen and
        # is still visible — it was refit to the fullscreen viewport but has no
        # saved windowed state, so leaving it would strand fullscreen zoom in the
        # smaller window (codex H-1). Queued to run after the re-show.
        if view_states or extra_views:
            def _restore(states=view_states, extra=extra_views,
                         do_refit=refit, eids=enter_ids):
                for vs in states:
                    self._restore_view_state(vs)
                if do_refit:
                    for v in extra:
                        try:
                            if id(v) not in eids and v.isVisible():
                                self._safe_reset_zoom(v)
                        except RuntimeError:
                            pass
            QTimer.singleShot(0, _restore)

    # -- cycle view (F2 while fullscreen) ---------------------------------

    def _cycle_view(self):
        """Cycle the chart page while staying fullscreen (F2 passthrough).

        Only reachable when the active descriptor has cycle=True (chart_stack).
        Delegates to the GUI's own F2 handler so fullscreen and windowed cycle
        share one code path; the stack's currentChanged (a refit_signal) then
        refits the newly shown page to the fullscreen viewport.
        """
        if not self.is_fullscreen:
            return
        cycle = getattr(self._gui, "_cycle_chart_view", None)
        if callable(cycle):
            cycle()

    # -- hooks ------------------------------------------------------------

    @staticmethod
    def _call_hook(hook):
        if callable(hook):
            try:
                hook()
            except Exception as exc:                     # noqa: BLE001
                print(f"[FSV] descriptor hook raised: {exc}")

    # -- toggle -----------------------------------------------------------

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()
