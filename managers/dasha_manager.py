# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dasha Manager - the two dasha panels (SPEC-DSH-002, SPEC-DSH-004).

Both panels are the same panel (SPEC-DSH-004): two `DashaSide` instances, each
offering every mode of the registry (`managers/dasha/modes.py`: Vimshottari with
an ayanamsa, Planetary Ages, Zodiacal Releasing). The manager owns the
navigation state (`DashaState`), the two panels, the settings reconciliation, the
ayanamsa / year-length / cycle setters, the shared row helpers (context menu,
lord highlights, transit actions) and the read accessors. Every panel event is
`manager.<verb>(side, ...) -> sides[side] -> renderer of the side's mode`.
"""

import logging
import weakref

from PySide6.QtWidgets import QMenu, QApplication
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtCore import Qt, QTimer

from managers.dasha import engine
from managers.dasha.modes import (
    MODES, SIDES, VALID_MODES, mode_spec, mode_reads, next_mode, normalize_mode)
from managers.dasha_state import (
    LEFT_DEFAULT_AYANAMSA, RIGHT_DEFAULT_AYANAMSA, DEFAULT_YEAR_LENGTH)
from managers.dasha.modes import DEFAULT_MODE
from apps.panels.dasha_panel import DashaPanelWidget

logger = logging.getLogger(__name__)

# SPEC-DSH-004 §4.5: the settings leaves this manager OWNS (its deferred
# reconciliation and Settings Apply are the only routes that relist for them),
# with the default each one re-reads to. dasha.zr.* belongs to
# ZodiacSettingsManager.
OWNED_LEAF_DEFAULTS = {
    "dasha.left.ayanamsa_id": LEFT_DEFAULT_AYANAMSA,
    "dasha.right.ayanamsa_id": RIGHT_DEFAULT_AYANAMSA,
    "dasha.left.mode": DEFAULT_MODE["left"],
    "dasha.right.mode": DEFAULT_MODE["right"],
    "display.date_format": "MM/DD/YYYY",
    "display.calendar_convention": "astronomical",
    "dasha.year_length.nakshatra": DEFAULT_YEAR_LENGTH,      # SPEC-DSH-003
}


class DashaManager:
    """The two dasha panels: state, panels, settings, shared row helpers."""

    def __init__(self, gui):
        """
        Initialize the dasha manager.

        Args:
            gui: The main ChartGUI instance (QMainWindow)
        """
        self.gui = gui
        self.state = gui.state

        # td-1bpk w1-1 (SPEC-DSH-002): construct the unified dasha navigation
        # state. INERT at this commit — nothing reads self.dasha_state yet; the
        # manager wires its readers and writers in at w1-2 (the atomic cutover),
        # where the 12 ChartGUI attribute inits (core_gui_qt.py:317-338) are
        # deleted. Built via from_settings so a saved or locked ayanamsa/mode
        # config is honoured at boot, exactly as those inits do today.
        from managers.dasha_state import DashaState
        from managers.settings_manager import get_settings
        self.dasha_state = DashaState.from_settings(get_settings())

        # SPEC-DSH-004: ONE DashaSide per side, both identical. Each owns one
        # renderer per mode (registry managers/dasha/modes.py) and dispatches every
        # panel event to its current mode's renderer.
        from managers.dasha.side import DashaSide
        self.sides = {name: DashaSide(self, name) for name in SIDES}
        # The F7 / Shift+F7 menu actions, per side (built by the menu builder).
        self.cycle_actions = {}

        # The shown varga can be a view input of a mode: re-list the
        # sides reading it when it changes. Weakref closure: the state's
        # listener list must not pin the manager (as the reconciliation timer).
        import weakref
        _self_ref = weakref.ref(self)

        def _on_state_changed(reason, _ref=_self_ref):
            mgr = _ref()
            if mgr is not None and reason == "current_varga":
                mgr.on_view_input_changed("view.varga")
        if hasattr(self.state, "connect"):
            self.state.connect(_on_state_changed)

        # td-9xlc w3-2 (SPEC-DSH-002): the manager OWNS the two dasha panels. Both
        # are None until build_panel() runs (ChartGUI calls it at :690/:797). The
        # 27 sub-widgets that used to live on ChartGUI as gui.vedanga_*/vimshottari_*
        # are now attributes of these panel objects; gui.vedanga_panel /
        # gui.vimshottari_panel are construction-time ALIASES of the same objects.
        self.left_panel = None
        self.right_panel = None

        # =====================================================================
        # DEFERRED SETTINGS RECONCILIATION (td-1bpk w1-2, SPEC-DSH-002,
        # plan rev 3.3). Kept as ONE self-contained block so a late review
        # finding on the timer is a local change.
        #
        # Mechanism: the manager owns ONE single-shot QTimer (interval 0) plus a
        # weakref on_changed closure over four settings keys. A subscribed
        # setting write records _pending_settings[key] = value and (re)starts
        # the timer. When the timer fires it acts ONLY on the keys recorded
        # since the last stop, using the recorded values -- PENDING KEYS, never
        # a value diff. A stored-vs-runtime difference is NOT evidence of a
        # write: a locked key legitimately diverges (dialog under a locked left
        # key -> persist_runtime_change is a no-op; locked F7/remote mode;
        # session restore, which persists nothing), and a value-diff timer would
        # revert every one of those on the next unrelated subscribed write.
        #
        # This FOLDS IN the old display.date_format live-apply (td-okit c0-2):
        # date_format is one of the four subscribed keys and its fire relists
        # both sides through their current mode. _on_dasha_settings_changed
        # (Apply) stops the timer and clears _pending_settings FIRST, so Apply's
        # own set() writes never drive a second relist here.
        #
        # td-okit c0-5 / GLM r3-6: BOTH the subscriber and the timer.timeout are
        # connected to closures over a WEAK ref to self, never bound methods --
        # SettingsManager keeps callbacks for the process lifetime with no
        # unsubscribe API, so a bound method would pin the manager (and its GUI)
        # forever. The timer is parented to the GUI (QTimer(gui)) so it dies
        # with it; a fire on a GC'd manager or a destroyed GUI no-ops.
        # =====================================================================
        self._pending_settings = {}
        self._stored_seen = {}          # leaf -> last stored value seen by its subscriber
        self._settings_reconcile_timer = None
        try:
            from managers.settings_manager import get_settings
            self_ref = weakref.ref(self)

            timer = QTimer(gui)
            timer.setSingleShot(True)
            timer.setInterval(0)

            def _reconcile_fire(_ref=self_ref):
                mgr = _ref()
                if mgr is not None:
                    mgr._reconcile_pending_settings()

            timer.timeout.connect(_reconcile_fire)
            self._settings_reconcile_timer = timer

            # ONE closure PER subscribed leaf, binding that leaf (sol MAJOR fix).
            # SettingsManager._notify_change is SYMMETRIC (SPEC-SET Dm3-33): a
            # subscriber of a leaf ALSO fires on an ANCESTOR write ("dasha", a
            # section reset) and on the global "*" reset — and its contract
            # (Dm3-28) is that subscribers RE-READ the value, never trust the
            # notified _key or payload. The old single callback recorded the
            # NOTIFICATION path ("*"/"dasha") and its payload, so a reset queued
            # a key _reconcile_pending_settings ignores and never reconciled.
            # Each closure instead records ITS OWN leaf and re-reads the current
            # value, so a leaf write, an ancestor write and a full/section reset
            # all enqueue the right leaf with the right value.
            # Re-read with the SAME default `from_settings` uses, so a leaf that
            # is missing from the store (a section delete, a hand-edited
            # app_settings.json) reconciles to the DEFAULT rather than queuing
            # None — which would otherwise reach set_ayanamsa(None) /
            # configure_side(None) (orchestrator NIT).
            # SPEC-DSH-004 §4.5: this manager OWNS these leaves (the only
            # route that relists for them); dasha.zr.* belongs to
            # ZodiacSettingsManager.
            _leaf_defaults = dict(OWNED_LEAF_DEFAULTS)

            def _make_reconcile_cb(_leaf, _default):
                def _cb(_key=None, _value=None, _ref=self_ref,
                        _leaf=_leaf, _default=_default):
                    mgr = _ref()
                    if mgr is None:
                        return
                    from managers.settings_manager import get_settings as _gs
                    value = _gs().get(_leaf, _default)
                    # A real change of the STORED value (Settings Apply, a reset,
                    # a remote write) supersedes this session's pick of that
                    # locked key (td-fj70t.11.5 review). Every Apply rewrites
                    # every row, so an unchanged value keeps the pick.
                    seen = mgr._stored_seen
                    if _leaf in seen and seen[_leaf] != value:
                        mgr.dasha_state.session_options.pop(_leaf, None)
                    seen[_leaf] = value
                    mgr._pending_settings[_leaf] = value
                    t = mgr._settings_reconcile_timer
                    if t is not None:
                        t.start()
                return _cb

            settings = get_settings()
            for _k, _d in _leaf_defaults.items():
                self._stored_seen[_k] = settings.get(_k, _d)
                settings.on_changed(_k, _make_reconcile_cb(_k, _d))
        except Exception:
            pass

    def _reconcile_pending_settings(self):
        """Fire handler for the deferred settings-reconciliation timer. Acts ONLY
        on the keys recorded in _pending_settings since the last stop, with the
        recorded values (pending keys, never a value diff), through the one
        per-side transaction `apply_dasha_settings`.

        Guards: GUI C++ object gone (shiboken6.isValid false) -> return; no chart
        -> drop the pending set silently. Nothing here writes a setting, so a fire
        never re-arms the timer."""
        try:
            import shiboken6
            if not shiboken6.isValid(self.gui):
                return
        except Exception:
            pass
        timer = self._settings_reconcile_timer
        if timer is not None:
            timer.stop()
        pending = dict(self._pending_settings)
        self._pending_settings.clear()
        if not pending:
            return
        if not getattr(self.gui, "current_chart_data", None):
            return
        try:
            self.apply_dasha_settings(pending, apply_route=False)
        except Exception:
            logger.warning("settings reconciliation failed", exc_info=True)

    def apply_dasha_settings(self, values, *, apply_route):
        """The per-side pending-key transaction (SPEC-DSH-004 §4.5).

        1. ADOPT every value state-only (year length, each side's ayanamsa, mode
           options are read at render time) — so every re-list below already
           runs on the new values (the old sol BLOCKER rule, both sides).
        2. ACT once per side: its mode changed -> `configure_side` (one reshape +
           one render); else, Settings Apply (`apply_route=True`) -> reset that
           mode's navigation and re-list (Planetary Ages: nothing); else a pending
           leaf its current mode reads -> one re-list. At most one re-list per
           side. Returns {side: "configure" | "update" | None}."""
        if "dasha.year_length.nakshatra" in values:
            try:
                self.set_year_length(values["dasha.year_length.nakshatra"], relist=False)
            except ValueError as exc:      # corrupt stored key: warn, keep the year
                logger.warning("Ignoring dasha year length: %s", exc)
        actions = {}
        for name in SIDES:
            st = self.dasha_state.side(name)
            key = f"dasha.{name}.ayanamsa_id"
            if key in values:
                self.set_ayanamsa(name, values[key], persist=False, relist=False,
                                  reset="none" if apply_route else "navigation")
            new_mode = st.mode
            mkey = f"dasha.{name}.mode"
            if mkey in values:
                if values[mkey] in VALID_MODES:
                    new_mode = values[mkey]
                else:
                    logger.warning("Ignoring unknown dasha mode %r for %s",
                                   values[mkey], mkey)
            if new_mode != st.mode:
                actions[name] = ("configure", new_mode)
            elif apply_route:
                actions[name] = (("update", None) if mode_spec(st.mode).relist_on_apply
                                 else None)
            elif mode_reads(st.mode, name) & set(values):
                actions[name] = ("update", None)
            else:
                actions[name] = None
        for name in SIDES:
            act = actions[name]
            if act is None:
                continue
            if act[0] == "configure":
                self.configure_side(name, act[1])
            else:
                if apply_route:
                    self.dasha_state.side(name).reset_mode_entry(
                        self.dasha_state.side(name).mode)
                    self.sync_level_buttons(name)
                self.update_side(name)
                self.update_cycle_label(name)
        return {n: (a[0] if a else None) for n, a in actions.items()}

    def cancel_pending_reconciliation(self):
        """Stop the deferred settings-reconciliation timer (if any) and drop
        every recorded pending key (SPEC-DSH-002 §4.6, rev 3.3 fold 1). The Apply
        handler calls this BEFORE it applies those same keys itself, so a
        still-pending deferred pass can never fire a second re-list. Public
        because `_settings_reconcile_timer` / `_pending_settings` are
        DashaManager-owned state — collaborators mutate them through the manager
        API, never by reaching into the private fields (Rule 4b)."""
        timer = self._settings_reconcile_timer
        if timer is not None:
            timer.stop()
        self._pending_settings.clear()

    def _discard_self_pending(self, key, value):
        """Drop the pending entry this manager's own persist write just queued on
        the reconciliation subscriber (GLM MAJOR) — but VALUE-GUARDED (sol delta):
        pop only when the pending value still equals what we persisted (`value`).
        If a same-key write from another producer lands DURING the persist (after
        our synchronous notify, before this discard), it leaves a DIFFERENT pending
        value, so it is preserved and reconciled, not lost. A foreign write with
        the SAME value is indistinguishable and dropped, harmlessly. Stops the
        timer only if nothing remains pending. Guarded for managers built via
        __new__ in unit tests (no _pending_settings)."""
        pending = getattr(self, "_pending_settings", None)
        if not pending:
            return
        if pending.get(key) == value:
            pending.pop(key, None)
        if not pending and self._settings_reconcile_timer is not None:
            self._settings_reconcile_timer.stop()


    # =========================================================================
    # DASHA STATE API (SPEC-DSH-002, SPEC-DSH-004)
    # =========================================================================

    def mode(self, side):
        """The mode `side` shows (registry key)."""
        return self.dasha_state.side(side).mode

    def zr_state(self, side):
        """`side`'s Zodiacal Releasing state (SPEC-ZR-001)."""
        return self.dasha_state.side(side).zr

    def ayanamsa(self, side):
        """Ayanamsa id for a Vimshottari-family side ('left' | 'right')."""
        return self.dasha_state.side(side).ayanamsa

    @property
    def year_length(self):
        """Dasha year-length key shared by both Vimshottari sides (SPEC-DSH-003):
        'saura' (default) | 'savana' | 'nakshatra' | 'sidereal'."""
        return self.dasha_state.year_length

    def set_year_length(self, key, *, relist):
        """SOLE writer of DashaState.year_length. Unknown keys raise ValueError
        (a wrong year silently shifts every date by months). On a change both
        sides drop navigation to level 1 (`reset_navigation(offset=False)`: the
        120-year offset is kept, cached rows are dropped) so a drilled sub-period
        can never be re-subdivided from a stale parent span. `relist=True` then
        re-lists both Vimshottari-family sides. Returns True when the value
        changed."""
        from managers.dasha_state import VALID_YEAR_LENGTHS
        if key not in VALID_YEAR_LENGTHS:
            raise ValueError(
                f"unknown dasha year length {key!r}; expected one of {VALID_YEAR_LENGTHS}")
        changed = self.dasha_state.year_length != key
        self.dasha_state.year_length = key
        if changed:
            self.dasha_state.left.reset_navigation(offset=False)
            self.dasha_state.right.reset_navigation(offset=False)
        if relist and changed:
            for name in SIDES:
                self.update_side(name)
                self.update_cycle_label(name)
        if changed:
            self._publish_live()
        return changed

    def _publish_live(self):
        """The tools calculate in the dasha frame on screen (AIC plan 2):
        publish a change at once through the live frame manager."""
        zs = getattr(getattr(self, "gui", None), "zodiac_settings", None)
        if zs is not None and hasattr(zs, "publish_live"):
            zs.publish_live()

    def side_level(self, side):
        """STORED Vimshottari level for 'left' | 'right' (not mode-routed; the
        mode-routed level is get_current_level)."""
        return self.dasha_state.side(side).level

    def cycle_offset(self, side):
        """120-year cycle offset for 'left' | 'right'."""
        return self.dasha_state.side(side).cycle_offset

    def rows(self, side):
        """Cached dasha rows for 'left' | 'right' (or None)."""
        return self.dasha_state.side(side).rows


    # =========================================================================
    # PANEL OWNERSHIP (SPEC-DSH-002 §4.10, SPEC-DSH-004)
    # =========================================================================

    def panel(self, side):
        """The DashaPanelWidget for 'left' | 'right' (None until build_panel ran).

        Raises ValueError on any other side (mirrors dasha_state.side)."""
        if side == "left":
            return self.left_panel
        if side == "right":
            return self.right_panel
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")

    def build_panel(self, side, *, parent):
        """Construct the DashaPanelWidget for `side` (both sides alike, SPEC-DSH-004
        §3.3: only the accent and the shortcut label differ), store it, wire its
        signals to the side-parameterised verbs, and return it. ChartGUI assigns
        the return value to gui.vedanga_panel / gui.vimshottari_panel."""
        from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
        s = self.sides[side]
        title_text = f"{get_ayanamsa_name(self.ayanamsa(side))}  ▾"
        panel = DashaPanelWidget(
            side, accent=s.traits["accent"], title_text=title_text,
            swap_tooltip=(f"Next dasha ({s.traits['shortcut']}). "
                          "Right-click to choose."),
            parent=parent)
        if side == "left":
            self.left_panel = panel
        else:
            self.right_panel = panel
        panel.level_requested.connect(lambda lvl, n=side: self.set_level(n, lvl))
        panel.drill_requested.connect(lambda item, n=side: self.on_drill(n, item))
        panel.select_requested.connect(lambda item, n=side: self.on_select(n, item))
        panel.prev_requested.connect(lambda n=side: self.nav_prev(n))
        panel.next_requested.connect(lambda n=side: self.nav_next(n))
        panel.title_clicked.connect(lambda n=side: self.on_title_clicked(n))
        panel.swap_requested.connect(lambda n=side: self.cycle_mode(n))
        panel.swap_menu_requested.connect(lambda n=side: self.show_mode_menu(n))
        panel.context_menu_requested.connect(
            lambda pos, n=side: self.show_dasha_context_menu(n, pos))
        panel.lord_filter_changed.connect(
            lambda n=side: self.refresh_dasha_lord_highlights(n))
        # Initialise the checked level button from the current side state.
        self.sync_level_buttons(side)
        return panel

    def sync_level_buttons(self, side=None):
        """Reflect the STORED level of each side's current mode on its level
        buttons. `side` in {None, 'left', 'right'} (None = both). Skips a panel
        that is not built. The single external level-button writer."""
        if side not in (None, "left", "right"):
            raise ValueError(f"side must be None, 'left' or 'right', got {side!r}")
        for name in (SIDES if side is None else (side,)):
            p = self.panel(name)
            if p is not None:
                p.set_level_checked(self.sides[name].checked_level())

    def refresh_panel_styles(self):
        """Re-apply theme + fonts to both dasha panels (the mixin replay). The
        ONLY caller of the panels' replay: core_gui._refresh_panel_styles routes
        its former dasha block here. Skips a panel that is not built."""
        for p in (self.left_panel, self.right_panel):
            if p is not None:
                p.refresh_fonts()


    def reset_for_chart(self):
        """Chart-context reset (decision 2): clear ALL navigation of every mode on
        both sides. Aborts in-flight renders and pending delayed callbacks of both
        sides, clears the selection highlight, refreshes the cycle labels and the
        level buttons. Does NOT relist — the caller relists."""
        for name in SIDES:
            self.sides[name].invalidate()
        self.dasha_state.reset_for_chart()
        for name in SIDES:
            p = self.panel(name)
            if p is not None and p.delegate is not None:
                p.delegate.update_selected_row(None)
            self.update_cycle_label(name)
        self.sync_level_buttons()

    def invalidate_renders(self):
        """Abort every in-flight render and pending delayed callback on BOTH sides.
        For chart-close / teardown paths that clear the dasha lists directly:
        callers invoke this immediately BEFORE such a direct clear."""
        for name in SIDES:
            self.sides[name].invalidate()

    def reset_mode_entry(self, side, mode):
        """Targeted reset when `side` (re)enters `mode`."""
        self.dasha_state.reset_mode_entry(side, mode)

    def set_ayanamsa(self, side, ayanamsa_id, *, persist, relist, reset):
        """Set a Vimshottari-family side's ayanamsa (SPEC-DSH-002).

        `reset`: 'full' zeroes the 120-year offset too (dialog routes),
        'navigation' keeps it (Settings Apply), 'none' resets no navigation
        (session restore). `persist=True` writes the setting via
        persist_runtime_change (lock-respecting: unlocked stores, locked keeps the
        stored value but runtime still adopts the id). `relist=True` re-lists that
        side through its CURRENT mode and refreshes title + cycle label; `relist=
        False` is STATE-ONLY. Exactly one persist write and at most one relist.

        A `persist=True` write goes to the settings store, whose notification is
        SYNCHRONOUS and arms this manager's reconciliation subscriber for the
        SAME key. Since this call applies the change itself, that self-triggered
        pending entry is discarded so the deferred pass does not re-list the side
        a SECOND time (GLM MAJOR; one-relist contract §4.4)."""
        st = self.dasha_state.side(side)            # ValueError on bad side
        if reset == "full":
            st.reset_navigation(offset=True)
        elif reset == "navigation":
            st.reset_navigation(offset=False)
        elif reset == "none":
            pass
        else:
            raise ValueError(
                f"unknown reset {reset!r}; expected 'full', 'navigation' or 'none'")
        changed = st.ayanamsa != ayanamsa_id
        st.ayanamsa = ayanamsa_id
        if persist:
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change(
                f"dasha.{side}.ayanamsa_id", ayanamsa_id)
            self._discard_self_pending(f"dasha.{side}.ayanamsa_id", ayanamsa_id)
        if relist:
            self.update_side(side)
            self.update_cycle_label(side)
        if changed and hasattr(self.gui, "zodiac_settings"):
            self.gui.zodiac_settings.notify_dasha(f"dasha.{side}.ayanamsa_id")


    def set_cycle_offset(self, side, offset):
        """SOLE cycle-offset writer outside DashaState (GLM r3-7). Validates
        `side` (ValueError) and coerces `offset` to int, writes the DashaState
        field, and refreshes that side's cycle label. Relists nothing itself."""
        st = self.dasha_state.side(side)            # ValueError on bad side
        st.cycle_offset = int(offset)
        self.update_cycle_label(side)

    def _display_date_at_offset(self, entry_jd, years_offset):
        """Display-only: the row's date with its YEAR shifted by `years_offset`
        (cycle_offset * 120); month/day untouched, no normalisation (carry-over 1).

        w2-2: delegates to the pure engine, resolving the two display settings per
        invocation through the PUBLIC readers (byte-identical to what display_revjul
        / format_display_ymd do given None) and passing them EXPLICITLY, so the
        engine never reads settings. Kept as a retained manager method (seam) — the
        renderer calls it per row, and its spies keep firing."""
        from core.time_utils import (
            read_display_date_format, read_calendar_convention)
        from managers.dasha import engine
        return engine.display_date_at_offset(
            entry_jd, years_offset,
            date_format=read_display_date_format(),
            convention=read_calendar_convention())


    # =========================================================================
    # SIDE VERBS (SPEC-DSH-004 §3.5): every panel event, mode-routed per side
    # =========================================================================

    def _auto_build_parent_chain(self, dasha_data, target_level, side="right"):
        """Build a Vimshottari parent chain from the current (is_current) entries
        of `side` (seam: the body lives in VimshottariSideController)."""
        return self.sides[side].renderer("vimshottari").auto_build_chain(
            dasha_data, target_level)

    def configure_side(self, side, mode, announce=True):
        """Reshape `side` for `mode` (title, nav, level buttons, mode-entry reset)
        and re-list. The ONLY reshaper. An unknown mode falls back to that side's
        default with one warning. Boot and session restore pass announce=False."""
        mode = normalize_mode(side, mode, logger)
        built = self.sides[side].configure(mode)
        self._publish_live()
        if built and announce:
            s = self.sides[side]
            self.gui.statusBar().showMessage(
                f"{s.traits['label']} panel: {mode_spec(mode).status_label} "
                f"({s.traits['shortcut']} to switch)", 3000)

    def select_mode(self, side, mode):
        """User/remote choice of a mode: reshape, then persist
        `dasha.<side>.mode` (lock-respecting)."""
        from managers.settings_manager import get_settings
        self.configure_side(side, mode)
        get_settings().persist_runtime_change(f"dasha.{side}.mode", self.mode(side))

    def cycle_mode(self, side):
        """Next mode in registry order (swap click, F7 right, Shift+F7 left)."""
        self.select_mode(side, next_mode(self.mode(side)))

    def show_mode_menu(self, side):
        """Mode menu on the swap button (right-click): every registry mode,
        the current one checked."""
        from ui.qt_theme import get_theme_colors
        p = self.panel(side)
        if p is None or p.swap_btn is None:
            return
        theme = get_theme_colors()
        menu = QMenu(p.swap_btn)
        from managers.dasha.common import menu_style
        menu.setStyleSheet(menu_style(theme))
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = self.mode(side)
        for spec in MODES:
            act = QAction(spec.label, menu)
            act.setCheckable(True)
            act.setChecked(spec.key == current)
            group.addAction(act)
            act.triggered.connect(
                lambda _=False, k=spec.key, n=side: self.select_mode(n, k))
            menu.addAction(act)
        btn = p.swap_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def update_side(self, side):
        """Re-list `side` for its CURRENT mode (no reshape)."""
        self.sides[side].update()

    def update_all_sides(self):
        """Re-list both sides (chart load, frame or names change)."""
        for name in SIDES:
            self.update_side(name)

    def set_level(self, side, level):
        """Route a level-button press to `side`'s current mode."""
        self.sides[side].set_level(level)

    def on_drill(self, side, item):
        """Double-click: drill (Nisarga: no-op)."""
        self.sides[side].on_drill(item)

    def on_select(self, side, item):
        """Single click: move the ▶ marker (Nisarga: no-op)."""
        self.sides[side].on_select(item)

    def nav_prev(self, side):
        """Prev arrow: previous 120-year cycle (Vimshottari), back one level
        (ZR)."""
        self.sides[side].nav_prev()

    def nav_next(self, side):
        self.sides[side].nav_next()

    def on_title_clicked(self, side):
        """Title click: ayanamsa dialog (Vimshottari), releaser menu (ZR),
        nothing (Planetary Ages)."""
        self.sides[side].on_title_clicked()

    def write_shared_option(self, key, value):
        value = _offered_or_factory(key, value)
        """A title-menu pick of a shared option (dasha.zr.*).
        Unlocked: persist only; the leaf's owner re-lists every side in that
        mode once (SPEC-DSH-004 §4.5). Locked: the stored value stays (the
        lock), the pick is adopted for this session, the sides reading it
        re-list now and the live frame publishes it at once (SPEC-SET-003
        INV-16: no settings write, so no watched-key change point fires)."""
        from managers.settings_manager import get_settings
        s = get_settings()
        if s.is_locked(key):
            self.dasha_state.session_options[key] = value
            self.relist_sides_reading(key, reset=True)   # as the owner's relist
            self._publish_live()
            return
        self.dasha_state.session_options.pop(key, None)
        s.persist_runtime_change(key, value)

    def write_shared_options(self, changes):
        """Several picks in one transaction (the dasa chooser's Apply,
        td-fj70t.11.5): a locked key is adopted for this session, an unlocked
        one persisted (its deferred reconciliation entry dropped, as
        set_ayanamsa does); then each side reading any of them re-lists ONCE
        and the live frame publishes once."""
        if not changes:
            return
        from managers.settings_manager import get_settings
        s = get_settings()
        for key, value in changes.items():
            value = _offered_or_factory(key, value)
            if s.is_locked(key):
                self.dasha_state.session_options[key] = value
            else:
                self.dasha_state.session_options.pop(key, None)
                s.persist_runtime_change(key, value)
                self._discard_self_pending(key, value)
        self.relist_sides_reading(set(changes), reset=True)
        self._publish_live()

    def shared_option(self, key, default=None):
        """A shared option as the panels use it: this session's pick of a
        locked option, else the stored setting. A saved choice the registry no
        longer offers (a renamed or removed method or dasa) reads as the
        factory value, as the capability resolves it."""
        if key in self.dasha_state.session_options:
            value = self.dasha_state.session_options[key]
        else:
            from managers.settings_manager import get_settings
            value = get_settings().get(key, default)
        return _offered_or_factory(key, value)

    def on_view_input_changed(self, leaf):
        """A view input changed (the shown varga, the ascendant override):
        re-list the sides whose mode reads it (ModeSpec.reads "view.*")."""
        self.relist_sides_reading(leaf)

    def relist_sides_reading(self, leaves, reset=False):
        """Re-list, once each, the sides whose mode reads any of `leaves`
        (a leaf or a set); `reset` first applies that mode's entry reset."""
        leaves = {leaves} if isinstance(leaves, str) else set(leaves)
        for name in SIDES:
            mode = self.mode(name)
            if leaves & mode_reads(mode, name):
                if reset:
                    self.reset_mode_entry(name, mode)
                self.update_side(name)

    # =========================================================================
    # SINGLE-CLICK SELECT (move ▶ marker without expanding)
    # =========================================================================

    # Aliases of the engine constants (w2-2). Kept because _select_dasha_entry
    # (and any remote reader) still reference them by these names.
    _PREFIX_CURRENT = engine.PREFIX_CURRENT
    _PREFIX_NORMAL = engine.PREFIX_NORMAL

    def _select_dasha_entry(self, side, list_widget, item, delegate):
        """Move ▶ highlight to the clicked entry (single-click selection).

        `side` is the SideState (left / right-in-vimshottari); `delegate` is the
        list's highlight delegate. Updates is_current in the list-widget entries
        AND the cached rows (side.rows), so the pill context menu picks up the new
        selection. G7 fix (rev 3 §DashaManager API): each affected row_entry gets
        is_current THEN a setData(UserRole, row_entry) write-back (UserRole stores
        a copy), and the cache is flipped via side.mark_current, so widget, cache
        and the remote periods[] all agree.
        """
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or not entry.get('jd'):
            return

        if side.cycle_offset != 0:
            return

        clicked_level = entry.get('level', 0)
        clicked_jd = entry.get('jd')
        clicked_lord = entry.get('lord')
        highlight_rows = set()

        for row_idx in range(list_widget.count()):
            row_item = list_widget.item(row_idx)
            row_entry = row_item.data(Qt.ItemDataRole.UserRole)
            if not row_entry:
                continue

            row_level = row_entry.get('level', 0)
            text = row_item.text()

            if row_level == clicked_level:
                is_this = (row_item is item)
                row_entry['is_current'] = is_this
                row_item.setData(Qt.ItemDataRole.UserRole, row_entry)

                if text.startswith(self._PREFIX_CURRENT) or text.startswith(self._PREFIX_NORMAL):
                    body = text[2:]
                    row_item.setText(
                        (self._PREFIX_CURRENT if is_this else self._PREFIX_NORMAL) + body)
                if is_this:
                    highlight_rows.add(row_idx)
            else:
                if row_entry.get('is_current', False):
                    highlight_rows.add(row_idx)

        if delegate:
            delegate.update_highlights(highlight_rows)
            list_widget.viewport().update()

        # Cache: flip is_current in the cached rows for this level (G7).
        side.mark_current(clicked_jd, clicked_lord, clicked_level)


    # =========================================================================
    # CONTEXT MENU HANDLERS
    # =========================================================================

    def show_dasha_context_menu(self, side, pos):
        """Right-click context menu for a row of `side`'s list (SPEC-DSH-004:
        side-neutral; the side's current mode renderer gives the cycle offset to
        apply to the row's jd: the 120-year offset in Vimshottari, 0 elsewhere)."""
        list_widget = self._list_widget_for(side)
        if list_widget is None:
            return
        item = list_widget.itemAt(pos)
        if not item:
            return

        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        from ui.qt_theme import get_theme_colors

        theme = get_theme_colors()
        menu = QMenu(list_widget)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
            }}
            QMenu::item:selected {{
                background-color: {theme["secondary_light"]};
            }}
            QMenu::item:disabled {{
                color: {theme["secondary_dark"]};
            }}
        """)

        jd = entry.get('jd')
        if jd is not None:
            cycle_offset = self.sides[side].context_cycle_offset()
            if cycle_offset != 0:
                jd = jd + (cycle_offset * 120 * 365.25)

        if not self.gui.has_transit_tab():
            action = menu.addAction("\U0001f512 Open in Transit")
            action.setEnabled(False)
            action.setToolTip("Available in full version")
        else:
            action = menu.addAction("Open in Transit")
            if jd is not None:
                action.triggered.connect(
                    lambda checked, j=jd: self._open_in_transit(j)
                )
            else:
                action.setEnabled(False)

        menu.addSeparator()

        act_chart = menu.addAction("Create chart")
        if jd is not None:
            lord = entry.get('lord', 'Dasha')
            act_chart.triggered.connect(
                lambda checked, j=jd, l=lord: self._create_chart_for_dasha(j, l)
            )
        else:
            act_chart.setEnabled(False)

        act_overlay = menu.addAction("Show as transit overlay")
        if jd is not None and hasattr(self.gui, 'transit_overlay_manager'):
            act_overlay.triggered.connect(
                lambda checked, j=jd: self._show_dasha_as_transit_overlay(j)
            )
        else:
            act_overlay.setEnabled(False)

        menu.exec(list_widget.mapToGlobal(pos))

    def _open_in_transit(self, jd):
        """Open the Transit tab with the chart for a specific Julian Day.

        Args:
            jd: Julian Day number (UTC) for the transit date
        """
        gui = self.gui
        gui.loading_manager.start("Opening in Transit...")

        # Switch to Transit tab
        if hasattr(gui, 'tab_widget'):
            from ui.tab_ids import tab_index
            # By widget, never by title (SPEC-LOC-002 INV-3).
            transit_index = tab_index(gui, "transit")
            if transit_index >= 0:
                gui.tab_widget.setCurrentIndex(transit_index)
        QApplication.processEvents()

        # Ensure natal chart is loaded and set the transit date
        if hasattr(gui, 'transit_panel') and gui.transit_panel:
            tp = gui.transit_panel

            # Populate dropdown and select the current memory chart
            tp._populate_natal_dropdown()
            if hasattr(gui, 'memory_panel') and gui.memory_panel:
                active_idx = gui.memory_panel.current_index
                for i in range(tp.natal_combo.count()):
                    if tp.natal_combo.itemData(i) == active_idx:
                        tp.natal_combo.setCurrentIndex(i)
                        break

            # Set the transit date (this triggers get_all_planets_data inside transit_panel)
            tp.set_transit_for_date(jd)

        gui.loading_manager.finish()

    def _create_chart_for_dasha(self, jd, lord_name):
        """Create a standalone chart for a dasha period's start date.

        Uses the natal chart's birth location (not current geolocation)
        because the dasha is tied to the natal chart's context.
        """
        gui = self.gui
        natal = gui.state.active_chart
        if not natal:
            return

        from libaditya import swe
        from core.chart_factory import build_chart_from_params, make_recipe, make_source_params
        from state.events import SetActiveChart

        ctx = natal.context
        lat = ctx.location.lat
        lon = ctx.location.long
        natal_bd = getattr(gui, 'current_birth_data', {}) or {}
        city = natal_bd.get('city', '') or ''
        country = natal_bd.get('country', '') or ''
        iana_tz = natal_bd.get('iana_timezone', natal_bd.get('timezone', 'UTC')) or 'UTC'

        local_off = ctx.timeJD.utcoffset if ctx.timeJD else 0.0

        local_jd = jd + local_off / 24.0
        ut_tuple = swe.revjul(local_jd)
        year, month, day = int(ut_tuple[0]), int(ut_tuple[1]), int(ut_tuple[2])
        hour_dec = ut_tuple[3]
        hour = int(hour_dec)
        minute = int((hour_dec - hour) * 60)
        second = int(((hour_dec - hour) * 60 - minute) * 60)

        mode = gui.state.aditya_mode
        ayanamsa = getattr(gui, 'chart_sidereal_ayanamsa_id', 100)
        hsys = getattr(gui, '_house_system_code', 'C')

        chart = build_chart_from_params(
            jd=jd, lat=lat, lon=lon,
            mode=mode, ayanamsa=ayanamsa,
            hsys=hsys, utcoffset=local_off,
        )

        name = f"Dasha {lord_name} {year}-{month:02d}-{day:02d}"
        chart.context.name = name

        recipe = make_recipe(
            name=name,
            year=year, month=month, day=day,
            timedec=hour_dec,
            utcoffset=local_off,
            timezone=iana_tz,
            lat=lat, lon=lon,
            city=city, country=country,
        )

        birth_data = {
            'name': name,
            'year': year, 'month': month, 'day': day,
            'timedec': hour_dec,
            'hour': hour, 'minute': minute, 'second': second,
            'lat': lat, 'lon': lon,
            'utcoffset': local_off,
            'iana_timezone': iana_tz, 'timezone': iana_tz,
            'city': city, 'country': country,
        }

        gui.state.dispatch(SetActiveChart(
            chart=chart,
            source_params=make_source_params(
                chtk_path=None,
                birth_data=birth_data,
                mode=mode,
                ayanamsa=ayanamsa,
                house_system=gui.state.house_system,
                is_human_design=False,
            ),
        ))

        from state.events import SetHumanDesignMode
        gui.state.dispatch(SetHumanDesignMode(enabled=False))  # Stage 2 td-ltha
        gui.current_chart_path = None
        gui.current_birth_data = birth_data
        gui._current_chart_data = None

        if hasattr(gui, 'chart_memory_panel') and gui.chart_memory_panel:
            gui.chart_memory_panel.add_chart(
                recipe,
                kind="dasha_moment",
                chart_obj=gui.state.active_chart,
            )

        chart_entry = {
            'recipe': recipe,
            'birth_metadata': {},
            'birth_data': birth_data,
            'person_name': name,
            'city': city,
            'country': country,
            'chtk_path': None,
        }
        if hasattr(gui, 'edit_chart_panel') and gui.edit_chart_panel:
            gui.edit_chart_panel.load_chart_from_memory(chart_entry)

        gui._finalize_chart_load()

    def _show_dasha_as_transit_overlay(self, jd):
        """Load a dasha period's start date into the transit overlay."""
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        if not mgr:
            return
        if not mgr.transit_enabled:
            mgr.enable_transit()
        if not mgr.transit_enabled:
            return
        mgr.lock_to_jd(jd)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    # =========================================================================
    # KARAKA / LORD HIGHLIGHT HELPERS
    # =========================================================================

    # Map full planet names to dasha abbreviations
    # Also build reverse map for Nisarga entries which store full names
    PLANET_TO_ABBREV = {
        "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
        "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa",
        "Rahu": "Ra", "Ketu": "Ke",
    }

    def get_karaka_planet_abbrev(self, karaka_code):
        """Return the 2-letter dasha abbreviation for the planet holding a karaka role.

        Args:
            karaka_code: 'AK', 'AmK', 'BK', 'MK', 'PiK', 'GK', 'DK'
        Returns:
            Abbreviation like 'Ma' or None if unavailable.
        """
        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
        planet_degrees = []
        planets = chart.rashi().planets()
        for name in planet_names:
            try:
                p = planets[name]
                planet_degrees.append({"name": name, "degree": p.real_in_sign_longitude()})
            except (KeyError, AttributeError):
                continue

        planet_degrees.sort(key=lambda x: x["degree"], reverse=True)
        karaka_order = ["AK", "AmK", "BK", "MK", "PiK", "GK", "DK"]
        try:
            idx = karaka_order.index(karaka_code)
        except ValueError:
            return None
        if idx >= len(planet_degrees):
            return None
        return self.PLANET_TO_ABBREV.get(planet_degrees[idx]["name"])

    def get_house_lord_abbrev(self, house_num, whole_sign=True):
        """Return the 2-letter dasha abbreviation for the lord of a house.

        Args:
            house_num: 1-12
            whole_sign: if True use whole-sign houses, else cusp-based (both use same calc for now)
        Returns:
            Abbreviation like 'Ve' or None.
        """
        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        asc = chart.rashi().cusps()[1]
        asc_sign_idx = asc.sign() - 1

        if self.gui.state.aditya_mode == "aditya":
            asc_sign = asc_sign_idx
            names = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                     'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']
        else:
            asc_sign = asc_sign_idx
            names = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                     'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']

        sign_index = (asc_sign + house_num - 1) % 12
        sign_name = names[sign_index]

        rulers = {
            "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury",
            "Varuna": "Moon", "Indra": "Sun", "Vivasvan": "Mercury",
            "Tvasta": "Venus", "Vishnu": "Mars", "Amzu": "Jupiter",
            "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter",
            "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
            "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
            "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
            "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
        }
        planet_full = rulers.get(sign_name)
        if not planet_full:
            return None
        return self.PLANET_TO_ABBREV.get(planet_full)

    def compute_lord_highlight_rows(self, list_widget, target_abbrev):
        """Scan displayed list items, return set of row indices whose lord chain
        contains the target planet abbreviation at ANY level.

        Handles both Vimshottari entries (lord='Ma/Ve') and Nisarga entries
        (lord='Mars' full name or None for separators).

        Args:
            list_widget: QListWidget (left/right panel's list_widget)
            target_abbrev: 2-letter abbreviation like 'Ma'
        Returns:
            set of row indices
        """
        if not target_abbrev:
            return set()
        # Build reverse lookup: full name → abbreviation for Nisarga entries
        full_name_for_abbrev = {v: k for k, v in self.PLANET_TO_ABBREV.items()}
        target_full = full_name_for_abbrev.get(target_abbrev, '')
        rows = set()
        for row_idx in range(list_widget.count()):
            item = list_widget.item(row_idx)
            entry = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not entry:
                continue
            lord = entry.get('lord')
            if not lord:
                continue
            # Check abbreviated form (Vimshottari: 'Ma/Ve/Su')
            parts = lord.split('/')
            if target_abbrev in parts:
                rows.add(row_idx)
            # Check full name form (Nisarga: 'Mars', 'Venus')
            elif target_full and lord == target_full:
                rows.add(row_idx)
        return rows


    def refresh_dasha_lord_highlights(self, side):
        """Recompute karaka/cusp/WS lord highlights of `side` from its combo
        selections and push updated row sets to the delegate. Works in every mode:
        rows carry their lord (Vimshottari 'Ma/Ve', Nisarga 'Mars', ZR the sign's
        ruler)."""
        p = self.panel(side)
        if p is None:
            return
        list_widget = p.list_widget
        delegate = p.delegate
        karaka_combo = p.karaka_combo
        cusp_combo = p.cusp_combo
        ws_combo = p.ws_combo

        if not delegate:
            return

        # Karaka highlight
        if karaka_combo and karaka_combo.currentIndex() > 0:
            karaka_code = karaka_combo.currentData()
            abbrev = self.get_karaka_planet_abbrev(karaka_code)
            delegate.update_karaka_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_karaka_highlights(set())

        # Cusp lord highlight
        if cusp_combo and cusp_combo.currentIndex() > 0:
            house_num = cusp_combo.currentData()
            abbrev = self.get_house_lord_abbrev(house_num, whole_sign=False)
            delegate.update_cusp_lord_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_cusp_lord_highlights(set())

        # Whole-sign lord highlight
        if ws_combo and ws_combo.currentIndex() > 0:
            house_num = ws_combo.currentData()
            abbrev = self.get_house_lord_abbrev(house_num, whole_sign=True)
            delegate.update_whole_sign_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_whole_sign_highlights(set())

        list_widget.viewport().update()

    def scroll_to_row(self, side, row):
        """Scroll `side`'s list to `row`, centered."""
        self.sides[side].renderer("vimshottari").scroll_to_row(row)

    def _age_str(self, entry_jd, years_offset=0):
        """Compute 'Xy Zm' age string from birth date to a dasha period start.

        w2-2: delegates to the pure engine (engine.age_text via one
        side's controller — both sides compute identically, so ONE delegation). Kept as a
        retained manager method (seam) so the renderer calls it per row and its
        spies keep firing. The engine computes both endpoints in the fixed
        astronomical calendar (an age is a DURATION, invariant to the display
        calendar toggle, byte-equivalent to core/zodiacal_releasing._age_ym); the
        120-year cycle offset is applied ONCE as `years_offset`."""
        return self.sides["left"].renderer("vimshottari").age_str(entry_jd, years_offset)


    def update_cycle_label(self, side):
        """The 120-year caption of `side`, only while it shows Vimshottari (ZR
        uses the same label for its own strip)."""
        if self.mode(side) == "vimshottari":
            self.sides[side].renderer("vimshottari").update_cycle_label()

    # =========================================================================
    # TITLE UPDATE
    # =========================================================================

    def _update_dasha_title(self, side):
        """Vimshottari title of `side`: its ayanamsa name."""
        from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
        name = get_ayanamsa_name(self.dasha_state.side(side).ayanamsa)
        p = self.panel(side)
        if p is not None:
            p.set_title(f"{name}  ▾")

    # =========================================================================
    # SPEC-REM-002 Wave 3 — READ ACCESSORS (read-only snapshots)
    # =========================================================================
    #
    # These getters expose what the dasha panels currently show, so that
    # AppController.read_dasha can return a normalized snapshot to an AI
    # agent without re-running the dasha calculation. They are intentionally
    # defensive: every accessor returns a safe default rather than raising
    # when the GUI is not fully constructed (e.g. unit-test environments,
    # before a chart is loaded).

    def _list_widget_for(self, panel):
        """Resolve the QListWidget for a "left"/"right" panel descriptor."""
        p = self.panel(panel)                 # ValueError on any other side
        return p.list_widget if p is not None else None

    def get_current_system(self, panel):
        """The active dasha system of a panel ('left' | 'right'): the side's mode
        key, except Vimshottari on the left, which keeps its legacy wire name
        "vedanga" (SPEC-DSH-004 D-7: remote clients read it)."""
        mode = self.mode(panel)                     # ValueError on a bad side
        if mode == "vimshottari":
            return self.sides[panel].traits["vimshottari_system"]
        return mode

    def get_current_level(self, panel):
        """The current depth level of a panel's current mode (1-5)."""
        return int(self.sides[panel].checked_level() or 1)

    def get_displayed_rows(self, panel):
        """Snapshot every visible QListWidget entry for a panel.

        Each returned dict contains the row's UserRole data merged with
        a "row_index" and the literal "display_text" the user sees. If
        UserRole is missing (notice rows, separators), only display_text
        and row_index are present.
        """
        list_widget = self._list_widget_for(panel)
        if list_widget is None:
            return []
        rows = []
        try:
            count = list_widget.count()
        except Exception:
            return []
        for i in range(count):
            try:
                item = list_widget.item(i)
            except Exception:
                item = None
            if item is None:
                continue
            try:
                text = item.text()
            except Exception:
                text = ""
            try:
                data = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                data = None
            snapshot = {"row_index": i, "display_text": text}
            if isinstance(data, dict):
                # Shallow copy so callers cannot mutate the live entry
                snapshot.update(data)
            elif data is not None:
                snapshot["raw"] = repr(data)
            rows.append(snapshot)
        return rows


def _offered_or_factory(key, value):
    """`value` when the registry offers it for `key` (or `key` has no fixed
    choices), else the key's factory value."""
    from core import settings_registry
    if not settings_registry.has(key) or settings_registry.get(key).choices is None:
        return value
    return value if settings_registry.valid(key, value) else settings_registry.default(key)
