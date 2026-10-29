# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Avastha panel controller — Phase 4 W2.7 (LAZY + sidereal-aware).

Migration source: managers/panel_update_manager.py:712-829.

LAZY mode (lazy=True): defers refresh until set_visible(True) is called.
Wired by apps/panels/info_panels.py:switch_to_avastha → set_visible(True),
and by switch_to_aspects/switch_to_shame/switch_to_tajika_* → set_visible(False).

Always D1. Does not react to varga changes.

Pre-mortem fixes embedded:
- pm-20260503-003: lazy-deferred chart and mode events (separate pending flags)
- pm-20260503-007: trigger is button-click, not non-existent QWidget.shown signal
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from apps.widgets.panel_controllers.duc_method import current_duc_method, subscribe_duc_method
from state import PanelControllerBase


class AvasthaController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events. Lazy.
    Always uses D1 regardless of active varga.

    7x7 drishti/yuti relationship matrix with dignity diagonal, shame pairs,
    DUAL/FRIEND/ENEMY/NEUTRAL classifications, and a TOTALS row.
    """

    # SPEC-AVA-001: the Avastha panel cycles through the pure view plus four
    # strength-refined views. "pure" is the original matrix; the rest scale every
    # influence by the influencer's bala (Duc = DUC Bala, by the strength.duc_method
    # setting, SPEC-STR-001 §7.5; a change of it refreshes like a chart change).
    VIEW_ORDER = ["pure", "duc", "dig", "uccha", "cheshta"]
    # View -> the label shown on the Avastha tab button (SPEC-AVA-001 §4).
    VIEW_LABEL = {"pure": "Avastha", "duc": "Duc", "dig": "Dig",
                  "uccha": "Uccha", "cheshta": "Chesta"}

    # Row geometry (SPEC-AVA-001 §12.2, rev4). Matrix occupies rows 0-6.
    ROW_TOTAL = 7
    ROW_POS = 8
    ROW_NEG = 9
    ROW_SIGN = 10
    ROW_HORA = 11
    ROW_TRIMSAMSA = 12

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)
        self._view = "pure"
        # col_idx -> {"aditya_sign", "hora_type", "trim_type"} for retinue-cell
        # clicks (SPEC-AVA-001 §12.5). Rebuilt on every refresh.
        self._retinue_cols = {}
        # The chart the table currently shows (None = not rendered): the AI
        # capture marks the Avastha region 'stale' otherwise (SPEC-AIC-001 INV-2).
        self.rendered_chart = None
        subscribe_duc_method(self, gui)

    def current_view(self):
        return self._view

    def view_label(self):
        return self.VIEW_LABEL.get(self._view, "Avastha")

    def set_view(self, view):
        """Set the active view (no refresh — the caller refreshes once)."""
        if view in self.VIEW_ORDER:
            self._view = view

    def cycle_view(self):
        """Advance pure -> duc -> dig -> uccha -> cheshta -> pure.

        Does NOT refresh (SPEC-AVA-001 §4, pre-mortem #6: the caller triggers a
        single refresh) — returns the new view so the caller can relabel the tab.
        """
        idx = self.VIEW_ORDER.index(self._view)
        self._view = self.VIEW_ORDER[(idx + 1) % len(self.VIEW_ORDER)]
        return self._view

    def refresh_view(self):
        """Public re-render of the current view — used by the tab-button cycle
        wiring (info_panels.on_tab2_click), which changes the view while the
        panel is already visible (set_visible is a no-op on True->True).

        SPEC-LAYOUT-001 B.6: a held controller (its panel folded, the Chart tab
        hidden) does not render; the refresh waits for the unfold drain. A
        render here satisfies any deferred or scheduled chart refresh too, so
        the unfold / the stale timer does not render a second time (MED-1)."""
        if not self._effective_visible():
            self._pending_chart_refresh = True
            return
        self._pending_chart_refresh = False
        self._chart_refresh_scheduled = False
        self._refresh()

    def sign_popup_summary(self, sign_name, ring=None, being_type=None):
        """Sign-avastha summary for a SectorInfoDialog, in the ACTIVE view.

        SPEC-AVA-003 §4.2: the single entry the wheel popup, the panel cell
        click and the Planetary Condition link all call. Works while the
        controller is still lazy/hidden (no avastha_table needed) and BEFORE the
        panel was ever opened — current_view() is 'pure' then. Never refreshes
        the panel, never caches balas (D-7). On any error the popup still opens
        with the structure alone (returns None)."""
        chart = getattr(self._state, "active_chart", None) if self._state else None
        if not chart:
            return None
        try:
            from AI_tools.AI_main_function.avastha_sign import sign_summary_for_chart
            return sign_summary_for_chart(
                chart, self._state.aditya_mode, self._view,
                sign_name, ring, being_type, current_duc_method())
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    def sign_popup_summaries(self, sign_name, ring=None, being_type=None):
        """All five view summaries for a SectorInfoDialog (SPEC-AVA-003 §11.2).

        The popup's in-popup view switch needs every view ready at open so a
        switch never calls the engine (D-20). One matrix build + one bala pass +
        five summarize_sign, via Half B. Works while the controller is still
        lazy/hidden and never refreshes the panel; returns None on any error so
        the popup still opens with the structure alone."""
        chart = getattr(self._state, "active_chart", None) if self._state else None
        if not chart:
            return None
        try:
            from AI_tools.AI_main_function.avastha_sign import sign_summaries_all_views
            return sign_summaries_all_views(
                chart, self._state.aditya_mode, sign_name, ring, being_type,
                current_duc_method())
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    def follow_popup(self, dialog, sign_name, ring=None, being_type=None):
        """Keep an open sign popup's summaries on the DUC Bala method: a change
        of it (Settings Apply, remote set_setting, an AI request) recomputes
        them from the chart and frame the popup OPENED on, captured now, never
        a chart loaded since (td-7zu14, SPEC-STR-001 §7.5)."""
        chart = getattr(self._state, "active_chart", None) if self._state else None
        if chart is None:
            return
        from functools import partial
        from apps.widgets.sector_popup_follow import follow_duc_method, sector_summaries
        follow_duc_method(dialog, partial(sector_summaries, chart, self._state.aditya_mode,
                                          sign_name, ring, being_type))

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        """Render the current view (pure or a strength-refined one, SPEC-AVA-001).

        One calculation for panel, CLI and MCP (SPEC-AIC-001 INV-1): the grid is
        core/capabilities/avastha.avastha_grid, get_avastha's data. It holds the
        two-chart rule (matrix and retinue rows on the sidereal-rebuilt chart,
        balas on the active chart), the pure and refined cell texts, the
        POS/NEG/TOTAL display split and the per-cell categories and tooltips.
        This method only puts them in the table.
        """
        gui = self._gui
        if not hasattr(gui, "avastha_table"):
            return
        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        gui.avastha_table.clearContents()
        self.rendered_chart = None
        try:
            from core.capabilities.avastha import avastha_grid
            view = self._view if self._view in self.VIEW_ORDER else "pure"
            grid = avastha_grid(chart, self._state.aditya_mode, view, current_duc_method())

            center = Qt.AlignmentFlag.AlignCenter
            cell_categories = {}

            def _put(row, col, cell):
                item = QTableWidgetItem(cell["text"])
                item.setTextAlignment(center)
                if cell.get("tooltip"):
                    item.setToolTip(cell["tooltip"])
                gui.avastha_table.setItem(row, col, item)
                if cell.get("category") is not None:
                    cell_categories[(row, col)] = cell["category"]

            for row_idx, row in enumerate(grid["matrix"]):
                for col_idx, cell in enumerate(row):
                    _put(row_idx, col_idx, cell)
            for row_idx, label in ((self.ROW_TOTAL, "TOTAL"), (self.ROW_POS, "POS"),
                                   (self.ROW_NEG, "NEG"), (self.ROW_SIGN, "SIGN"),
                                   (self.ROW_HORA, "HORA"),
                                   (self.ROW_TRIMSAMSA, "TRIMSAMSA")):
                for col_idx, cell in enumerate(grid[label]):
                    _put(row_idx, col_idx, cell)
            # col_idx -> the beings a SIGN/HORA/TRIMSAMSA click opens (§12.5)
            self._retinue_cols = dict(enumerate(grid["columns"]))

            if hasattr(gui, "avastha_delegate"):
                gui.avastha_delegate.update_categories(cell_categories)
                gui.avastha_table.viewport().update()
            self.rendered_chart = chart

        except Exception as e:
            import traceback
            print(f"Error updating Avastha ({self._view}): {e}")
            traceback.print_exc()

    def open_retinue_dialog(self, row, col):
        """Open the being description for a clicked SIGN/HORA/TRIMSAMSA cell.

        SPEC-AVA-001 §12.5 / D10: reuse the existing SectorInfoDialog surface,
        focused on the clicked being. Always shows the full Theme/Healthy/
        Afflicted set — never a computed "afflicted" flag (D11).
        """
        if row not in (self.ROW_SIGN, self.ROW_HORA, self.ROW_TRIMSAMSA):
            return
        info = self._retinue_cols.get(col)
        if not info or not info.get("aditya_sign"):
            return

        focus_ring = None
        focus_type = None
        layer = "sign"
        if row == self.ROW_HORA:
            focus_ring, focus_type, layer = "hora", info.get("hora_type"), "hora"
        elif row == self.ROW_TRIMSAMSA:
            focus_ring, focus_type, layer = "trimsamsa", info.get("trim_type"), "trimsamsa"

        # SPEC-AVA-003 §11.2: pass all five view summaries so the cell click opens
        # the popup at the cell's depth and the panel's current view, with the
        # in-popup view switch ready and that being highlighted.
        summaries = self.sign_popup_summaries(info["aditya_sign"], focus_ring, focus_type)

        try:
            from apps.widgets.sector_dialog import SectorInfoDialog
            dlg = SectorInfoDialog(
                info["aditya_sign"], focus_ring=focus_ring,
                focus_type=focus_type, avastha_summaries=summaries, layer=layer,
                view=self.current_view(), parent=self._gui)
            self.follow_popup(dlg, info["aditya_sign"], focus_ring, focus_type)
            dlg.exec()
            dlg.deleteLater()      # else hidden child dialogs pile up (Codex review)
        except Exception as e:
            import traceback
            print(f"Error opening retinue dialog: {e}")
            traceback.print_exc()
