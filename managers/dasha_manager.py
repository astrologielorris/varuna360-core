# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dasha Manager - Handles Vedanga and Vimshottari dasha navigation and display

This module manages:
- Dasha level navigation (1-5)
- 120-year cycle navigation
- Click-to-expand functionality
- Dasha list updates and formatting
- Parent chain tracking for sub-dasha display

Extracted from core_gui_qt.py to reduce complexity and improve maintainability.
"""

import logging
import weakref

from PySide6.QtWidgets import QListWidgetItem, QListWidget, QMenu, QApplication
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtCore import Qt, QTimer

from managers.dasha import engine
from apps.panels.dasha_panel import DashaPanelWidget, KEEP

logger = logging.getLogger(__name__)


# ZRPanelState moved to managers/dasha_state.py (td-1bpk w1-2); it now lives on
# DashaState.zr, exposed here as the `zr_state` property so existing ZR code and
# pro/remote_control.py are untouched.


class DashaManager:
    """
    Manages Vedanga and Vimshottari dasha navigation and display.

    This class handles:
    - Level selection (1-5 sub-dasha levels)
    - 120-year cycle navigation (past/current/future)
    - Click-to-expand parent chain tracking
    - List widget population and highlighting

    Heavy GUI operations are delegated back to the main window via self.gui reference.
    """

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
        # config is honoured at boot, exactly as those inits do today. zr_state
        # is now the `zr_state` property -> dasha_state.zr (below).
        from managers.dasha_state import DashaState
        from managers.settings_manager import get_settings
        self.dasha_state = DashaState.from_settings(get_settings())

        # td-t761 w2-2 (SPEC-DSH-002): ONE VimshottariSideController per side
        # replaces the two byte-identical renderers + their paired helpers. The
        # twelve public method names below stay as one-line delegations (remote
        # control, panels, core_gui and the tests call them). The right controller
        # is mode-blind — the manager's mode dispatchers call it only in
        # vimshottari mode, exactly as they called update_vimshottari_dasha today.
        from managers.dasha.side_controller import VimshottariSideController
        self._left_ctl = VimshottariSideController(self, "left")
        self._right_ctl = VimshottariSideController(self, "right")

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
            # configure_right_panel(None) (orchestrator NIT).
            from managers.dasha_state import (
                LEFT_DEFAULT_AYANAMSA, RIGHT_DEFAULT_AYANAMSA, DEFAULT_RIGHT_MODE,
                DEFAULT_YEAR_LENGTH)
            _leaf_defaults = {
                "dasha.left.ayanamsa_id": LEFT_DEFAULT_AYANAMSA,
                "dasha.right.ayanamsa_id": RIGHT_DEFAULT_AYANAMSA,
                "dasha.right.mode": DEFAULT_RIGHT_MODE,
                "display.date_format": "MM/DD/YYYY",
                "dasha.year_length.nakshatra": DEFAULT_YEAR_LENGTH,   # SPEC-DSH-003
            }

            def _make_reconcile_cb(_leaf, _default):
                def _cb(_key=None, _value=None, _ref=self_ref,
                        _leaf=_leaf, _default=_default):
                    mgr = _ref()
                    if mgr is None:
                        return
                    from managers.settings_manager import get_settings as _gs
                    mgr._pending_settings[_leaf] = _gs().get(_leaf, _default)
                    t = mgr._settings_reconcile_timer
                    if t is not None:
                        t.start()
                return _cb

            settings = get_settings()
            for _k, _d in _leaf_defaults.items():
                settings.on_changed(_k, _make_reconcile_cb(_k, _d))
        except Exception:
            pass

    def _reconcile_pending_settings(self):
        """Fire handler for the deferred settings-reconciliation timer
        (td-1bpk w1-2, plan rev 3.3). Acts ONLY on the keys recorded in
        _pending_settings since the last stop, with the recorded values.

        Order (so the right panel re-lists at most once AND with the right
        ayanamsa):
          1. dasha.right.ayanamsa_id -> set_ayanamsa("right", value, persist=
             False, relist=False, reset="navigation") STATE-ONLY first, so the
             mode reshape below re-lists with the NEW id (sol BLOCKER fix).
          2. dasha.right.mode -> if valid AND differs from runtime,
             configure_right_panel(value) (reshapes + re-lists the right through
             the new mode and the id from step 1); unknown mode -> warning.
          3. right ayanamsa changed but no reshape re-listed it -> re-list now.
          4. dasha.left.ayanamsa_id -> set_ayanamsa("left", value, persist=False,
             relist=True, reset="navigation") (re-lists the left).
          5. display.date_format -> re-list each side through its current mode,
             skipping a side steps 1-4 already re-listed.

        Guards (same as the old _on_date_format_changed): GUI C++ object gone
        (shiboken6.isValid false) -> return; no chart -> drop the pending set
        silently. Neither set_ayanamsa(persist=False) nor configure_right_panel
        writes a setting, so a fire never re-arms the timer.
        """
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
            relisted = {"left": False, "right": False}
            # SPEC-DSH-003: adopt the year length FIRST, state-only, so every
            # re-list below already runs on it. A bogus stored value is
            # warned and ignored (boot falls back the same way).
            year_changed = False
            if "dasha.year_length.nakshatra" in pending:
                try:
                    year_changed = self.set_year_length(
                        pending["dasha.year_length.nakshatra"], relist=False)
                except ValueError as exc:
                    logger.warning("Ignoring reconciled dasha year length: %s", exc)
            # ADOPT THE RIGHT AYANAMSA FIRST, STATE-ONLY (sol BLOCKER fix). The
            # mode reshape below re-lists the right panel, so the new ayanamsa
            # must already be in DashaState BEFORE it runs — otherwise the
            # reshape re-lists Vimshottari with the OLD ayanamsa and the new id
            # is then adopted with no re-list, leaving runtime/widget/remote
            # disagreeing (stale rows).
            right_ayan_pending = "dasha.right.ayanamsa_id" in pending
            if right_ayan_pending:
                self.set_ayanamsa("right", pending["dasha.right.ayanamsa_id"],
                                  persist=False, relist=False, reset="navigation")
            # Mode next: the reshape re-lists the right through the new mode AND
            # the ayanamsa just adopted (Settings Reset from vimshottari/zr sends
            # mode + right ayanamsa together — exactly one right re-list).
            right_reshaped = False
            if "dasha.right.mode" in pending:
                mode = pending["dasha.right.mode"]
                if mode not in self.VALID_RIGHT_MODES:
                    logger.warning(
                        "Ignoring unknown reconciled right dasha mode %r", mode)
                elif mode != self.dasha_state.right_mode:
                    self.configure_right_panel(mode)
                    relisted["right"] = True
                    right_reshaped = True
            # Ayanamsa changed but no reshape re-listed the right: re-list now.
            if right_ayan_pending and not right_reshaped:
                self.update_right_panel()
                relisted["right"] = True
            if "dasha.left.ayanamsa_id" in pending:
                self.set_ayanamsa("left", pending["dasha.left.ayanamsa_id"],
                                  persist=False, relist=True, reset="navigation")
                relisted["left"] = True
            # Year length adopted above; re-list whichever side is not already.
            if "display.date_format" in pending or year_changed:
                if not relisted["left"]:
                    self.update_vedanga_dasha()
                if not relisted["right"]:
                    self.update_right_panel()
        except Exception:
            logger.warning("settings reconciliation failed", exc_info=True)

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
    # DASHA STATE API (td-1bpk w1-2, SPEC-DSH-002)
    #
    # The manager owns `self.dasha_state`; these are the ONLY mutation and read
    # entry points for the 12 retired ChartGUI attributes. `zr_state` and
    # `right_mode` are read-only projections; ZR code keeps writing dasha_state.zr
    # fields through the `zr_state` property object.
    # =========================================================================

    @property
    def zr_state(self):
        """The ZR panel state (SPEC-ZR-001), now DashaState.zr."""
        return self.dasha_state.zr

    @property
    def right_mode(self):
        """The right panel's current mode (vimshottari | nisarga | zr)."""
        return self.dasha_state.right_mode

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
            self.update_vedanga_dasha()
            self.update_cycle_label_vedanga()
            self.update_right_panel()
            self.update_cycle_label_vimshottari()
        return changed

    def side_level(self, side):
        """STORED Vimshottari-family level for 'left' | 'right' (not mode-routed;
        Nisarga level is dasha_state.nisarga_level, read by get_current_level)."""
        return self.dasha_state.side(side).level

    def cycle_offset(self, side):
        """120-year cycle offset for 'left' | 'right'."""
        return self.dasha_state.side(side).cycle_offset

    def rows(self, side):
        """Cached dasha rows for 'left' | 'right' (or None)."""
        return self.dasha_state.side(side).rows

    # =========================================================================
    # PANEL OWNERSHIP (td-9xlc w3-2, SPEC-DSH-002 §4.10)
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
        """Construct the DashaPanelWidget for `side`, store it, wire its nine
        signals to the manager's existing public names (the exact targets the
        ChartGUI delegators called before the cutover), and return it. ChartGUI
        assigns the return value to gui.vedanga_panel / gui.vimshottari_panel."""
        from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
        # Each factory's EXACT title caret per side (rev 1.7 fold 2): left ▾
        # (vedanga v:93-96), right ▼ (vimshottari vm:98-102). The manager
        # normalises both to ▾ on the first _update_dasha_title, so this only
        # affects the pre-load title; the pixel grab records the title text and
        # asserts BASE == HEAD per side.
        caret = "▾" if side == "left" else "▼"
        title_text = f"{get_ayanamsa_name(self.ayanamsa(side))}  {caret}"
        accent = "orange" if side == "left" else "cyan"
        swap = (side == "right")
        panel = DashaPanelWidget(
            side, accent=accent, title_text=title_text, swap=swap,
            swap_icon_getter=(lambda: getattr(self.gui, "_make_swap_icon", None)),
            parent=parent)
        if side == "left":
            self.left_panel = panel
            panel.level_requested.connect(self.set_vedanga_level)
            panel.drill_requested.connect(self.on_vedanga_clicked)
            panel.select_requested.connect(self.on_vedanga_select)
            panel.prev_requested.connect(self.navigate_vedanga_previous)
            panel.next_requested.connect(self.navigate_vedanga_next)
            panel.title_clicked.connect(
                lambda: self.gui._change_dasha_ayanamsa("vedanga"))
            panel.context_menu_requested.connect(
                lambda pos, p=panel: self.show_dasha_context_menu(
                    p.list_widget, pos, "vedanga"))
            panel.lord_filter_changed.connect(
                lambda: self.refresh_dasha_lord_highlights("vedanga"))
        else:
            self.right_panel = panel
            panel.level_requested.connect(self.set_right_level)
            panel.drill_requested.connect(self.on_right_clicked)
            panel.select_requested.connect(self.on_right_select)
            panel.prev_requested.connect(self.on_right_nav_prev)
            panel.next_requested.connect(self.on_right_nav_next)
            panel.title_clicked.connect(self.on_right_title_clicked)
            panel.swap_requested.connect(self.gui._cycle_right_dasha)
            panel.context_menu_requested.connect(
                lambda pos, p=panel: self.show_dasha_context_menu(
                    p.list_widget, pos, (self.right_mode or "vimshottari")))
            panel.lord_filter_changed.connect(
                lambda: self.refresh_dasha_lord_highlights("vimshottari"))
        # rev 1.7 fold 1: initialise the checked level button from the current
        # side state before returning (the per-mode rule of D-W3-4), rather than
        # leaving the widget's construction-time set_level_checked(1).
        self.sync_level_buttons(side)
        return panel

    def _right_checked_level(self):
        """The level index the RIGHT panel's buttons should show, per mode: the
        stored value reset_mode_entry / reset_for_chart just wrote."""
        mode = self._normalize_right_mode(self.dasha_state.right_mode)
        if mode == "nisarga":
            return self.dasha_state.nisarga_level
        if mode == "zr":
            return self.dasha_state.zr.level
        return self.dasha_state.right.level

    def sync_level_buttons(self, side=None):
        """Reflect the STORED level on the panel's level buttons (SPEC-DSH-002
        §4.10 D-W3-4). `side` in {None, 'left', 'right'} (None = both). Skips a
        panel that is not built. The single external level-button writer: the
        old `for i,b: setChecked(i==0)` loops at the chart-context and ayanamsa
        sites route here."""
        if side not in (None, "left", "right"):
            raise ValueError(f"side must be None, 'left' or 'right', got {side!r}")
        if side in (None, "left") and self.left_panel is not None:
            self.left_panel.set_level_checked(self.dasha_state.left.level)
        if side in (None, "right") and self.right_panel is not None:
            self.right_panel.set_level_checked(self._right_checked_level())

    def refresh_panel_styles(self):
        """Re-apply theme + fonts to both dasha panels (the mixin replay). The
        ONLY caller of the panels' replay: core_gui._refresh_panel_styles routes
        its former dasha block here. Skips a panel that is not built."""
        for p in (self.left_panel, self.right_panel):
            if p is not None:
                p.refresh_fonts()

    def reset_for_chart(self):
        """Chart-context reset (decision 2): clear ALL navigation on a new chart.
        Delegates to DashaState.reset_for_chart (both sides offset=True, Nisarga
        level 1, ZR drill + result reset), clears the selection highlight on both
        list delegates, and refreshes both cycle labels. Does NOT relist — the
        caller relists (chart load / HD recompute)."""
        # Abort any in-flight render on both sides (w2-2): a new chart makes a
        # suspended Vimshottari-family render stale (SPEC-DSH-002 render token).
        self._left_ctl.invalidate()
        self._right_ctl.invalidate()
        self.dasha_state.reset_for_chart()
        for p in (self.left_panel, self.right_panel):
            if p is not None and p.delegate is not None:
                p.delegate.update_selected_row(None)
        self.update_cycle_label_vedanga()
        self.update_cycle_label_vimshottari()
        # w3-2 D-W3-4: the level-button reset that used to live in the three
        # external loops after each reset_for_chart() call is now the LAST
        # statement here — same widget writes, same order on every path.
        self.sync_level_buttons()

    def invalidate_renders(self):
        """Abort any in-flight Vimshottari-family render on BOTH sides by bumping
        each side controller's render token (SPEC-DSH-002 render token, w2-4).

        For chart-close / teardown paths that clear the dasha list widgets DIRECTLY
        (no renderer, no reset_for_chart): a render suspended at a `_pump` would
        otherwise resume and append rows to the just-emptied lists. Callers invoke
        this immediately BEFORE such a direct clear."""
        self._left_ctl.invalidate()
        self._right_ctl.invalidate()

    def reset_mode_entry(self, mode):
        """Targeted reset when the right panel (re)enters `mode` (SPEC-DSH-002):
        thin wrapper over DashaState.reset_mode_entry. configure_right_panel
        calls it; Settings Apply uses it for the zr-unchanged branch."""
        self.dasha_state.reset_mode_entry(mode)

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
            if side == "left":
                self.update_vedanga_dasha()
                self.update_cycle_label_vedanga()
            else:
                self.update_right_panel()
                self.update_cycle_label_vimshottari()
        if changed and hasattr(self.gui, "zodiac_settings"):
            self.gui.zodiac_settings.notify_dasha(f"dasha.{side}.ayanamsa_id")

    def set_cycle_offset(self, side, offset):
        """SOLE cycle-offset writer outside DashaState (GLM r3-7). Validates
        `side` (ValueError) and coerces `offset` to int, writes the DashaState
        field, and refreshes that side's cycle label. Relists nothing itself —
        navigate_* relist after calling it."""
        st = self.dasha_state.side(side)            # ValueError on bad side
        st.cycle_offset = int(offset)
        if side == "left":
            self.update_cycle_label_vedanga()
        else:
            self.update_cycle_label_vimshottari()

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
    # LEVEL MANAGEMENT
    # =========================================================================

    def _auto_build_parent_chain(self, dasha_data, target_level, panel="vimshottari"):
        """Build a parent chain from the current (is_current) dasha entries
        (SPEC-DSH-002 w2-2 seam): delegates to the side controller of `panel`.
        Kept as a retained manager name so the MagicMock at
        test_remote_control.py:1633 and the call-count spies keep intercepting;
        the body lives in VimshottariSideController.auto_build_chain."""
        ctl = self._left_ctl if panel == "vedanga" else self._right_ctl
        return ctl.auto_build_chain(dasha_data, target_level)

    def set_vedanga_level(self, level):
        """Set Vedanga dasha display level (1-5) — delegates to the left controller."""
        self._left_ctl.set_level(level)

    def set_vimshottari_level(self, level):
        """Set Vimshottari dasha display level (1-5) — delegates to the right controller."""
        self._right_ctl.set_level(level)

    # =========================================================================
    # CYCLE NAVIGATION
    # =========================================================================

    def navigate_vedanga_previous(self):
        """Navigate to previous 120-year Vedanga cycle."""
        self._left_ctl.navigate(-1)

    def navigate_vedanga_next(self):
        """Navigate to next 120-year Vedanga cycle."""
        self._left_ctl.navigate(1)

    def navigate_vimshottari_previous(self):
        """Navigate to previous 120-year Vimshottari cycle."""
        self._right_ctl.navigate(-1)

    def navigate_vimshottari_next(self):
        """Navigate to next 120-year Vimshottari cycle."""
        self._right_ctl.navigate(1)

    # =========================================================================
    # CLICK HANDLERS
    # =========================================================================

    def on_vimshottari_clicked(self, item):
        """Handle click on Vimshottari dasha item to expand or select."""
        self._right_ctl.on_clicked(item)

    def on_vedanga_clicked(self, item):
        """Handle click on Vedanga dasha item to expand or select."""
        self._left_ctl.on_clicked(item)

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

    def on_vimshottari_select(self, item):
        """Single click on Vimshottari: select this period, move ▶ marker. The
        nisarga early-return stays HERE (Nisarga has no per-period select); the
        selection body delegates to the right controller."""
        if self.dasha_state.right_mode == 'nisarga':
            return
        self._right_ctl.on_select(item)

    def on_vedanga_select(self, item):
        """Single click on Vedanga: select this period, move ▶ marker."""
        self._left_ctl.on_select(item)

    # =========================================================================
    # CONTEXT MENU HANDLERS
    # =========================================================================

    def show_dasha_context_menu(self, list_widget, pos, dasha_type):
        """Show right-click context menu for a dasha list item.

        Args:
            list_widget: The QListWidget (left/right panel's list_widget)
            pos: Position of the right-click
            dasha_type: "vedanga" or "vimshottari" (used for cycle offset)
        """
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
            if dasha_type == "vedanga":
                cycle_offset = self.dasha_state.left.cycle_offset
            elif dasha_type in ("nisarga", "zr"):
                # ZR has no 120-year cycling; its jd is already absolute
                # (GPT Sol W2 review finding 5 / F5).
                cycle_offset = 0
            else:
                cycle_offset = self.dasha_state.right.cycle_offset
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
            for i in range(gui.tab_widget.count()):
                if gui.tab_widget.tabText(i) == "Transit":
                    gui.tab_widget.setCurrentIndex(i)
                    break
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
                is_transit=True,
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

    def refresh_dasha_lord_highlights(self, panel="vedanga"):
        """Recompute karaka/cusp/WS lord highlights from combo selections and
        push updated row sets to the delegate."""
        p = self.left_panel if panel == "vedanga" else self.right_panel
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

    def scroll_to_vedanga_row(self, row):
        """Scroll the Vedanga list to `row` — delegates to the left controller."""
        self._left_ctl.scroll_to_row(row)

    def scroll_to_vimshottari_row(self, row):
        """Scroll the Vimshottari list to `row` — delegates to the right controller."""
        self._right_ctl.scroll_to_row(row)

    def _age_str(self, entry_jd, years_offset=0):
        """Compute 'Xy Zm' age string from birth date to a dasha period start.

        w2-2: delegates to the pure engine (engine.age_text via the LEFT
        controller — both sides compute identically, so ONE delegation). Kept as a
        retained manager method (seam) so the renderer calls it per row and its
        spies keep firing. The engine computes both endpoints in the fixed
        astronomical calendar (an age is a DURATION, invariant to the display
        calendar toggle, byte-equivalent to core/zodiacal_releasing._age_ym); the
        120-year cycle offset is applied ONCE as `years_offset`."""
        return self._left_ctl.age_str(entry_jd, years_offset)

    def update_cycle_label_vedanga(self):
        """Update Vedanga cycle indicator label — delegates to the left controller."""
        self._left_ctl.update_cycle_label()

    def update_cycle_label_vimshottari(self):
        """Update Vimshottari cycle indicator label — delegates to the right controller."""
        self._right_ctl.update_cycle_label()

    # =========================================================================
    # TITLE UPDATE
    # =========================================================================

    def _update_dasha_title(self, panel):
        """Update the dasha panel title button text to reflect the current ayanamsa."""
        from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
        if panel == "vedanga":
            name = get_ayanamsa_name(self.dasha_state.left.ayanamsa)
            p = self.left_panel
        else:
            name = get_ayanamsa_name(self.dasha_state.right.ayanamsa)
            p = self.right_panel
        if p is not None:
            p.set_title(f"{name}  \u25be")

    # =========================================================================
    # MAIN UPDATE METHODS
    # =========================================================================

    def update_vedanga_dasha(self):
        """Update the Vedanga (left) dasha list — delegates to the left controller."""
        self._left_ctl.update()

    def update_vimshottari_dasha(self):
        """Update the Vimshottari (right) dasha list — delegates to the right
        controller. Called only in vimshottari mode by the right-panel dispatchers;
        the legacy Vimshottari-named public methods stay mode-blind (no new guard)."""
        self._right_ctl.update()

    # =========================================================================
    # NISARGA DASHA (Natural Planetary Ages)
    # =========================================================================

    def set_nisarga_level(self, level):
        """Set Nisarga dasha display level (1=periods+maturation, 2=sub-periods)."""
        self.dasha_state.nisarga_level = level
        self.update_nisarga_dasha()

    def update_nisarga_dasha(self):
        """Update the right panel with Nisarga dasha data.

        Level 1: 7 natural periods + separator + 9 maturation ages at bottom
        Level 2: Sub-periods (each main period divided into 12)

        Reuses the right panel's list widget (right_panel.list_widget).
        """
        # Nisarga replaces the shared right list: abort any in-flight Vimshottari
        # render so its stale rows can never land here (w2-2, SPEC-DSH-002).
        self._right_ctl.invalidate()
        p = self.right_panel
        if p is not None:
            p.set_title("Planetary Ages")
        lst = p.list_widget                 # AttributeError pre-build, as today
        lst.clear()

        # Clear any leftover highlights
        if p is not None and p.delegate is not None:
            p.delegate.update_highlights(set())
            p.delegate.update_maturation_highlights(set())

        chart = self.gui.current_chart_data
        if not chart:
            return

        birth_y = chart.get('year')
        birth_m = chart.get('month')
        birth_d = chart.get('day')
        if not all([birth_y, birth_m, birth_d]):
            return

        try:
            from core.nisarga_dasha import format_nisarga_level1, format_nisarga_level2

            level = self.dasha_state.nisarga_level

            if level == 2:
                entries = format_nisarga_level2(birth_y, birth_m, birth_d)
            else:
                entries = format_nisarga_level1(birth_y, birth_m, birth_d)

            highlight_rows = set()
            maturation_rows = set()

            for i, entry in enumerate(entries):
                item = QListWidgetItem(entry['text'])
                item.setData(Qt.ItemDataRole.UserRole, entry)

                # Make separator rows non-selectable
                if entry.get('is_separator'):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

                lst.addItem(item)

                # Track highlights: primary for current period, gold for maturation
                if entry.get('is_current'):
                    highlight_rows.add(i)
                if entry.get('is_maturation'):
                    maturation_rows.add(i)

            # Update delegate highlights
            if p is not None and p.delegate is not None:
                p.delegate.update_highlights(highlight_rows)
                p.delegate.update_maturation_highlights(maturation_rows)
                lst.viewport().update()

            # Scroll to current period (prefer period highlight over maturation)
            scroll_rows = highlight_rows if highlight_rows else maturation_rows
            if scroll_rows:
                current_row = min(scroll_rows)
                QTimer.singleShot(100, lambda: self.scroll_to_vimshottari_row(current_row))

            # Refresh karaka/lord highlights after Nisarga list is populated
            self.refresh_dasha_lord_highlights("vimshottari")

        except Exception as e:
            import traceback
            print(f"Error updating Nisarga dasha: {e}")
            traceback.print_exc()

    # =========================================================================
    # RIGHT-PANEL DISPATCHER (SPEC-ZR-001 §3.6, W5a)
    # =========================================================================
    #
    # One place reshapes the right dasha panel, one place re-lists it. Every
    # lifecycle path (boot, F7/swap, settings apply, session restore, chart
    # load, memory select, refresh) routes through these instead of an inline
    # an inline mode check with a silent Vimshottari fallthrough.
    # dasha_state.right_mode (the `right_mode` property) is the single source of
    # truth for the current mode (SPEC-DSH-002); configure_right_panel owns
    # writing it. W5b appends "zr" to VALID_RIGHT_MODES and adds its branch.

    VALID_RIGHT_MODES = ("vimshottari", "nisarga", "zr")
    DEFAULT_RIGHT_MODE = "nisarga"

    def _normalize_right_mode(self, mode):
        """Coerce an unknown persisted mode to the default with ONE warning.

        Prevents a bogus `dasha.right.mode` (or a future mode this build does
        not know) from silently rendering as Vimshottari (review R1-4).
        """
        if mode in self.VALID_RIGHT_MODES:
            return mode
        logger.warning(
            "Unknown right dasha mode %r; falling back to %r",
            mode, self.DEFAULT_RIGHT_MODE,
        )
        return self.DEFAULT_RIGHT_MODE

    _RIGHT_MODE_STATUS = {
        "nisarga": "Right panel: Planetary Ages (F7 to switch)",
        "vimshottari": "Right panel: Vimshottari Dasha (F7 to switch)",
        "zr": "Right panel: Zodiacal Releasing (F7 to switch)",
    }

    # w3-2 D-W3-3 (SPEC-DSH-002 §4.10): immutable STRUCTURAL reshape data per
    # right-panel mode (levels, nav, static title fields). KEEP = "the renderer
    # writes it" (dynamic title). configure_right_panel feeds a row to
    # right_panel.set_shape(); the per-mode data resets + the renderer follow.
    _RIGHT_SHAPES = {
        "vimshottari": dict(levels=5, nav="cycle", title=KEEP,
                            title_tooltip="Click to change ayanamsa",
                            title_enabled=True),
        "nisarga": dict(levels=5, nav="hidden", title="Planetary Ages",
                        title_tooltip="Natural Planetary Ages (F7 to switch back)",
                        title_enabled=False),
        "zr": dict(levels=4, nav="strip", title=KEEP, title_tooltip=KEEP,
                   title_enabled=True),
    }

    def configure_right_panel(self, mode, announce=True):
        """Reshape the right panel for `mode` (title, nav, level buttons, level
        reset) and re-list. The ONLY reshaper. Sets `dasha_state.right_mode` and
        applies the targeted mode-entry reset for that mode (reset_mode_entry).

        Call on every mode CHANGE (F7/swap, settings) with announce=True — the
        F7 status message is user-action feedback and belongs to the toggle, not
        the reshape primitive. Boot and session restore pass announce=False so
        they do not flash "Right panel: ... - F7 to switch" at startup (GPT Sol
        W5a review finding 2). Chart load / memory select / ordinary refresh do
        NOT reshape; they call `update_right_panel()`.
        """
        # A reshape makes any in-flight Vimshottari render of the right list stale
        # (w2-2): bump the right render token so it aborts at its next pump before
        # it can repopulate the reshaped list (SPEC-DSH-002).
        self._right_ctl.invalidate()
        mode = self._normalize_right_mode(mode)
        self.dasha_state.right_mode = mode
        # Targeted reset for the entered mode (SPEC-DSH-002): the reshape no
        # longer touches levels/chains — this is the single source of that reset.
        self.dasha_state.reset_mode_entry(mode)
        # w3-2 change 6 (D-W3-3): with no right panel built yet, the state is
        # written above and we RETURN before the reshape / renderer / status
        # message. Today the reshape helpers raised AttributeError on the first
        # missing widget after these writes; production never reaches this (boot
        # reshape at core_gui :804 runs after :797; the dispatcher tests pass a
        # Mock right_panel).
        if self.right_panel is None:
            return
        # Vimshottari's title is dynamic: resolve it immediately before set_shape
        # (verbatim of core_gui 1828) so the shape row can leave title = KEEP.
        if mode == "vimshottari":
            self._update_dasha_title("vimshottari")
        # w3-2 change 5: one reshape through the widget (title -> nav -> levels).
        self.right_panel.set_shape(**self._RIGHT_SHAPES[mode])
        if mode == "vimshottari":
            # Releasing uses this same label for its context strip. Restore the
            # preserved 120-year cycle caption when returning to Vimshottari.
            self.update_cycle_label_vimshottari()
        # Per-mode data resets (the "after set_shape, before render" column).
        d = self.right_panel.delegate
        if mode == "vimshottari":
            if d is not None:
                d.update_maturation_highlights(set())
        elif mode == "zr":
            if d is not None:
                # Clear EVERY delegate channel before the ZR list fills the
                # period one (verbatim of the old per-mode ZR configure helper).
                d.update_highlights(set())
                d.update_maturation_highlights(set())
                d.update_selected_row(None)
                d.update_karaka_highlights(set())
                d.update_cusp_lord_highlights(set())
                d.update_whole_sign_highlights(set())
        # Renderer.
        if mode == "nisarga":
            self.update_nisarga_dasha()
        elif mode == "zr":
            self.update_zr_dasha()
        else:  # vimshottari
            self.update_vimshottari_dasha()
        if announce:
            msg = self._RIGHT_MODE_STATUS.get(mode)
            if msg:
                self.gui.statusBar().showMessage(msg, 3000)

    def update_right_panel(self):
        """Re-list the right panel for the CURRENT mode (no reshape)."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "nisarga":
            self.update_nisarga_dasha()
        elif mode == "zr":
            self.update_zr_dasha()
        else:  # vimshottari
            self.update_vimshottari_dasha()

    def set_right_level(self, level):
        """Route a right-panel level change to the current mode's setter."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "nisarga":
            self.set_nisarga_level(level)
        elif mode == "zr":
            self.set_zr_level(level)
        else:  # vimshottari
            self.set_vimshottari_level(level)

    def on_right_clicked(self, item):
        """Route a double-click (drill) to the current mode. Nisarga does not
        drill, so it is a no-op there (matches the prior behaviour)."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "nisarga":
            return
        if mode == "zr":
            self.on_zr_double_click(item)
            return
        self.on_vimshottari_clicked(item)

    def on_right_select(self, item):
        """Route a single-click (select / move ▶) to the current mode."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "nisarga":
            return
        if mode == "zr":
            self.on_zr_select(item)
            return
        self.on_vimshottari_select(item)

    def on_right_nav_prev(self):
        """Route the nav prev-button. In ZR it is "back one level"; in Nisarga a
        no-op (w2-2, sol delta 1: a programmatic prev must NOT replace the Nisarga
        list with Vimshottari rows — the arrows are hidden in Nisarga, so this is
        reachable only programmatically); otherwise the 120-year previous cycle."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "zr":
            self.zr_back_one_level()
        elif mode == "nisarga":
            return
        else:
            self.navigate_vimshottari_previous()

    def on_right_nav_next(self):
        """Route the nav next-button. In ZR the next button is hidden (stray call
        is a no-op); in Nisarga a no-op too (w2-2, sol delta 1: see on_right_nav_prev);
        otherwise the 120-year next-cycle navigation."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "zr":
            return
        if mode == "nisarga":
            return
        self.navigate_vimshottari_next()

    def on_right_title_clicked(self):
        """Right title-button click, dispatched by mode. Vimshottari opens the
        ayanamsha dialog; Nisarga is a no-op (the button is disabled there);
        ZR raises the releaser menu (DESIGN DECISION 2)."""
        mode = self._normalize_right_mode(self.get_current_system("right"))
        if mode == "vimshottari":
            self.gui._change_dasha_ayanamsa("vimshottari")
        elif mode == "zr":
            self._show_zr_releaser_menu()
        # nisarga: no-op

    # =========================================================================
    # ZODIACAL RELEASING (SPEC-ZR-001 W5b, DESIGN DECISIONS 1..5, 8)
    # =========================================================================

    # w3-2 D-W3-3: the old ZR right-panel configure helper and the nav-default
    # restore helper are retired. Their widget reshape is now
    # right_panel.set_shape(nav="strip") / set_shape(nav="cycle"|"hidden") + the
    # delegate clears in configure_right_panel; the level reset rides set_shape's
    # set_level_checked(1).

    def _zr_settings(self):
        from managers.settings_manager import get_settings
        s = get_settings()
        st = self.zr_state
        st.releaser = s.get("dasha.zr.releaser", "spirit")
        st.spirit_shift = bool(s.get("dasha.zr.spirit_shift", True))
        st.show_age = bool(s.get("dasha.zr.show_age", False))
        st.anchor = s.get("dasha.zr.anchor", "birth")
        return st

    def update_zr_dasha(self):
        """Re-list the ZR panel for the current level (DESIGN DECISION 1/8).

        Drives the SHARED compute_zr() so the panel and the CLI produce identical
        periods (INV-5). One level is listed at a time; the strip shows parents.
        """
        # ZR replaces the shared right list: abort any in-flight Vimshottari render
        # so its stale rows can never land here (w2-2, SPEC-DSH-002).
        self._right_ctl.invalidate()
        gui = self.gui
        p = self.right_panel
        lst = p.list_widget
        lst.clear()
        if p.delegate is not None:
            p.delegate.update_highlights(set())

        chart = gui.current_chart_data
        if not chart:                       # DD8: no chart -> cleared, no notice
            self.zr_state.result = None
            self._set_zr_title(None)
            return

        st = self._zr_settings()
        mode = gui.state.aditya_mode
        ayan = getattr(gui, 'chart_sidereal_ayanamsa_id', 100)
        use_western = getattr(gui, 'use_western_names', False)

        from AI_tools.AI_main_function.zodiacal_releasing import compute_zr
        try:
            result = compute_zr(
                chart, mode=mode, ayanamsa=ayan, releaser=st.releaser,
                spirit_shift=st.spirit_shift, anchor=st.anchor,
                horizon_years=150, levels=1,
            )
        except ValueError as e:             # DD8: cannot resolve -> one notice row
            self.zr_state.result = None
            self._set_zr_title(None)
            msg = ("  Zodiacal Releasing needs a birth time"
                   if "birth time" in str(e) else "  Releaser cannot be computed: %s" % e)
            item = QListWidgetItem(msg)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, {"is_separator": True})
            lst.addItem(item)
            self._update_zr_strip(None, mode, use_western)
            return
        except Exception as e:
            print(f"Error updating ZR dasha: {e}")
            import traceback
            traceback.print_exc()
            return

        self.zr_state.result = result
        # Drop a parent chain left over from a different chart or zodiac frame
        # before drilling with it (W6 review MAJOR 1). A pure label toggle keeps
        # positions/instants, so a valid chain survives; a chart load or a
        # zodiac-SYSTEM change moves them and the chain is reset to level 1.
        self._zr_reset_chain_if_stale(result)
        p.set_level_checked(self.zr_state.level)
        self._set_zr_title(result, mode=mode, use_western=use_western)

        display_rows = self._zr_display_rows(result)
        meta = self._zr_meta(result, mode, use_western)

        from core.zodiacal_releasing import format_level, zr_tooltip
        birth_jd = result["birth_jd_utc"]
        entries = format_level(
            display_rows, self.zr_state.level, now_jd=result["target_jd"],
            mode=mode, use_western=use_western, show_age=st.show_age,
            birth_jd=birth_jd, tz_offset_hours=result["tz_offset_hours"],
        )

        highlight_rows = set()
        for i, entry in enumerate(entries):
            item = QListWidgetItem(entry["text"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(zr_tooltip(entry, meta))
            lst.addItem(item)
            if entry["is_current"]:
                highlight_rows.add(i)

        if p.delegate is not None:
            p.delegate.update_highlights(highlight_rows)
            lst.viewport().update()
        if highlight_rows:
            row = min(highlight_rows)
            QTimer.singleShot(100, lambda: self.scroll_to_vimshottari_row(row))

        self._update_zr_strip(result, mode, use_western)

    def _zr_reset_chain_if_stale(self, result):
        """Reset the ZR drill chain when it no longer belongs to `result`.

        The chain caches Period rows (pos + absolute start_jd). The generic dasha
        resets on chart load / memory select / zodiac-system change clear only
        Vimshottari and Nisarga state, so a chain drilled on the previous chart
        or frame would make `_zr_display_rows` tile the wrong periods. Validate
        the top parent against the new L1 rows; on any mismatch (different chart,
        different zodiac system) drop to level 1. A pure label toggle recomputes
        with identical positions/instants, so the chain still matches and stays.
        """
        st = self.zr_state
        if st.level <= 1 or not st.parent_chain:
            st.level = 1
            st.parent_chain = []
            return
        l1 = [r for r in result["rows"] if r["level"] == 1]
        top = st.parent_chain[0]
        matches = any(
            r["pos"] == top.get("pos")
            and abs(r["start_jd"] - top.get("start_jd", -1e18)) < 1e-6
            for r in l1)
        if not matches or len(st.parent_chain) < st.level - 1:
            st.level = 1
            st.parent_chain = []

    def _zr_display_rows(self, result):
        """The Period rows to show at the current level, per the parent chain."""
        st = self.zr_state
        rows = result["rows"]           # L1 + L2 (interleaved) from build()
        lvl = st.level
        if lvl == 1:
            return [r for r in rows if r["level"] == 1]
        if lvl == 2:
            parent = st.parent_chain[0]
            return [r for r in rows if r["level"] == 2
                    and r["parent_pos"] == parent["pos"]
                    and parent["start_jd"] <= r["start_jd"] < parent["end_jd"]]
        # levels 3 and 4: drill the L2 row in the chain.
        from core.zodiacal_releasing import drill
        drilled = drill(st.parent_chain[1], result["fortune_pos"])
        if lvl == 3:
            return [r for r in drilled if r["level"] == 3]
        l3 = st.parent_chain[2]
        return [r for r in drilled if r["level"] == 4
                and r["parent_pos"] == l3["pos"]
                and l3["start_jd"] <= r["start_jd"] < l3["end_jd"]]

    def _zr_meta(self, result, mode, use_western):
        from core.aditya_mode import displayed_sign_name
        return {
            "mode": mode, "use_western": use_western,
            "tz_offset_hours": result["tz_offset_hours"],
            "birth_jd": result["birth_jd_utc"],
            "releaser_token": result["label_token"], "lot_label": result.get("lot_label"),
            "releaser_pos": result["releaser_pos"],
            "releaser_sign_label": displayed_sign_name(result["releaser_pos"], mode, use_western),
            "fortune_pos": result["fortune_pos"],
            "fortune_sign_label": displayed_sign_name(result["fortune_pos"], mode, use_western),
        }

    def _set_zr_title(self, result, mode=None, use_western=False):
        """Title button text from the label_token (DESIGN DECISION 2)."""
        p = self.right_panel
        if p is None:
            return
        if result is None:
            # sol 5: BASE renderer order is setEnabled(True) FIRST, then setText ->
            # setToolTip (the manager owns the panel, so this direct enable is
            # allowed). Authorised change 5 is the RESHAPE order only, not this.
            p.title_btn.setEnabled(True)
            p.set_title("Releasing: Spirit ▼", tooltip="Click to choose the releaser")
            return
        from core.aditya_mode import displayed_sign_name
        tok = result["label_token"]
        if tok == "spirit":
            text = "Releasing: Spirit ▼"
        elif tok == "spirit_shifted":
            text = "Releasing: Spirit* ▼"
        elif tok == "fortune":
            text = "Releasing: Fortune ▼"
        elif tok == "lot":
            text = "Releasing: %s ▼" % result.get("lot_label", "Lot")
        else:
            text = "Releasing: %s ▼" % displayed_sign_name(
                result["releaser_pos"], mode or self.gui.state.aditya_mode, use_western)
        tip = "Click to choose the releaser"
        if tok == "spirit_shifted":
            tip += ". Spirit was shifted out of Fortune's sign."
        p.title_btn.setEnabled(True)          # sol 5: enable BEFORE setText/setToolTip
        p.set_title(text, tooltip=tip)

    def _update_zr_strip(self, result, mode, use_western):
        """Context strip (DESIGN DECISION 3): prev-btn visibility + cycle label."""
        p = self.right_panel
        if p is None:
            return
        st = self.zr_state
        from core.aditya_mode import displayed_sign_name
        if st.level == 1 or result is None:
            fsign = (displayed_sign_name(result["fortune_pos"], mode, use_western)
                     if result else "")
            text = ("Peaks from Fortune in %s" % fsign) if result else ""
        else:
            crumbs = [displayed_sign_name(pp["pos"], mode, use_western)
                      for pp in st.parent_chain]
            text = " › ".join(crumbs)           # ›
        p.set_strip(prev_visible=(st.level > 1), text=text)

    def set_zr_level(self, level):
        """Jump to a level via the level buttons. Going deeper without an
        explicit drill builds the chain from the current period at each depth."""
        level = max(1, min(4, int(level)))
        st = self.zr_state
        result = st.result
        if result is None:
            st.level = 1
            self.update_zr_dasha()
            return
        if level == 1:
            st.level = 1
            st.parent_chain = []
        else:
            chain = self._zr_auto_chain(result, level)
            if len(chain) < level - 1:
                # Not enough context to reach that depth; stay where valid.
                level = len(chain) + 1
            st.parent_chain = chain[:level - 1]
            st.level = level
        self.update_zr_dasha()

    def _zr_auto_chain(self, result, target_level):
        """Build a parent chain to target_level from the CURRENT period at each
        depth (used when a level button is pressed without drilling)."""
        from core.zodiacal_releasing import find_current, drill
        rows = result["rows"]
        now = result["target_jd"]
        chain = []
        l1 = [r for r in rows if r["level"] == 1]
        i1 = find_current(l1, now, 1)
        if i1 < 0:
            return chain
        chain.append(l1[i1])
        if target_level == 2:
            return chain
        l2 = [r for r in rows if r["level"] == 2
              and r["parent_pos"] == l1[i1]["pos"]
              and l1[i1]["start_jd"] <= r["start_jd"] < l1[i1]["end_jd"]]
        i2 = find_current(l2, now, 2)
        if i2 < 0:
            return chain
        chain.append(l2[i2])
        if target_level == 3:
            return chain
        drilled = drill(l2[i2], result["fortune_pos"])
        l3 = [r for r in drilled if r["level"] == 3]
        i3 = find_current(l3, now, 3)
        if i3 < 0:
            return chain
        chain.append(l3[i3])
        return chain

    def on_zr_double_click(self, item):
        """Drill one level deeper into the double-clicked row."""
        st = self.zr_state
        if st.level >= 4 or st.result is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or entry.get("is_separator"):
            return
        # Reconstruct the Period row for this entry from the displayed set.
        display_rows = self._zr_display_rows(st.result)
        row = next((r for r in display_rows
                    if r["level"] == entry["level"] and r["pos"] == entry["pos"]
                    and abs(r["start_jd"] - entry["start_jd"]) < 1e-6), None)
        if row is None:
            return
        st.parent_chain = st.parent_chain[:st.level - 1] + [row]
        st.level += 1
        if self.right_panel is not None:
            self.right_panel.set_level_checked(st.level)
        self.update_zr_dasha()

    def on_zr_select(self, item):
        """Single click: move the ▶ current-marker to the clicked row (no drill).

        Parity with Vimshottari's _select_dasha_entry (W6 review MAJOR 3): update
        is_current AND the leading current glyph on every displayed row, not just
        the delegate highlight, so read_dasha and the title summary follow the
        selection. ZR lists one level at a time, so every visible row is a peer.
        The row text is "{cur}{mark} ...": char 0 is the ▶/space current glyph,
        char 1 is the peak mark — rewrite char 0 only.
        """
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or entry.get("is_separator"):
            return
        from core.zodiacal_releasing import _MARK_CURRENT
        lst = self.right_panel.list_widget
        highlight = set()
        for i in range(lst.count()):
            it = lst.item(i)
            e = it.data(Qt.ItemDataRole.UserRole)
            if not e or e.get("is_separator"):
                continue
            is_this = it is item
            e["is_current"] = is_this
            text = it.text()
            if text:
                it.setText((_MARK_CURRENT if is_this else " ") + text[1:])
            it.setData(Qt.ItemDataRole.UserRole, e)
            if is_this:
                highlight.add(i)
        if self.right_panel.delegate is not None:
            self.right_panel.delegate.update_highlights(highlight)
            lst.viewport().update()

    def zr_back_one_level(self):
        """Pop one ancestor off the chain and go up a level (DD3 back button)."""
        st = self.zr_state
        if st.level <= 1:
            return
        st.level -= 1
        st.parent_chain = st.parent_chain[:st.level - 1]
        if self.right_panel is not None:
            self.right_panel.set_level_checked(st.level)
        self.update_zr_dasha()

    def _show_zr_releaser_menu(self):
        """Releaser QMenu on the title button (DESIGN DECISION 2)."""
        from ui.qt_theme import get_theme_colors
        from managers.settings_manager import get_settings
        gui = self.gui
        s = get_settings()
        cur_releaser = s.get("dasha.zr.releaser", "spirit")
        mode = gui.state.aditya_mode
        use_western = getattr(gui, 'use_western_names', False)
        from core.aditya_mode import displayed_sign_name

        theme = get_theme_colors()
        menu = QMenu(self.right_panel.title_btn)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]}; }}
            QMenu::item:selected {{ background-color: {theme["secondary_light"]}; }}
        """)
        group = QActionGroup(menu)
        group.setExclusive(True)

        def _releaser_action(parent, label, key):
            act = QAction(label, parent)
            act.setCheckable(True)
            act.setChecked(cur_releaser == key)
            group.addAction(act)
            act.triggered.connect(lambda _=False, k=key: self._pick_zr_releaser(k))
            return act

        menu.addAction(_releaser_action(menu, "Spirit", "spirit"))
        menu.addAction(_releaser_action(menu, "Fortune", "fortune"))
        from core.lots import LOT_REGISTRY, LOT_ORDER
        lots_menu = menu.addMenu("From a lot")
        lots_menu.setStyleSheet(menu.styleSheet())
        for name in LOT_ORDER:
            lots_menu.addAction(_releaser_action(
                lots_menu, LOT_REGISTRY[name]["label"], f"lot:{name}"))
        submenu = menu.addMenu("From a sign")
        submenu.setStyleSheet(menu.styleSheet())
        for i in range(12):
            submenu.addAction(_releaser_action(
                submenu, displayed_sign_name(i, mode, use_western), f"sign:{i}"))
        menu.addSeparator()

        shift_act = QAction("Shift Spirit out of Fortune's sign", menu)
        shift_act.setCheckable(True)
        shift_act.setChecked(bool(s.get("dasha.zr.spirit_shift", True)))
        shift_act.triggered.connect(
            lambda checked: self._set_zr_option("dasha.zr.spirit_shift", checked))
        menu.addAction(shift_act)


        btn = self.right_panel.title_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _pick_zr_releaser(self, key):
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("dasha.zr.releaser", key)
        self.update_zr_dasha()

    def _set_zr_option(self, settings_key, value):
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change(settings_key, bool(value))
        self.update_zr_dasha()

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
        if panel == "left":
            return self.left_panel.list_widget if self.left_panel is not None else None
        if panel == "right":
            return self.right_panel.list_widget if self.right_panel is not None else None
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def get_current_system(self, panel):
        """Return the active dasha system for a panel.

        - "left" → always "vedanga"
        - "right" → "vimshottari" or "nisarga" depending on
          ``self.dasha_state.right_mode``
        """
        if panel == "left":
            return "vedanga"
        if panel == "right":
            return self.dasha_state.right_mode or "vimshottari"
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def get_current_level(self, panel):
        """Return the current depth level for a panel (1-5)."""
        if panel == "left":
            return int(self.dasha_state.left.level or 1)
        if panel == "right":
            system = self.get_current_system("right")
            if system == "nisarga":
                return int(self.dasha_state.nisarga_level or 1)
            if system == "zr":
                return int(self.zr_state.level or 1)
            return int(self.dasha_state.right.level or 1)
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

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
