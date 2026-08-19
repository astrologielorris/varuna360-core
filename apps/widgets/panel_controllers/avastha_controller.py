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

from state import PanelControllerBase


class AvasthaController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events. Lazy.
    Always uses D1 regardless of active varga.

    7x7 drishti/yuti relationship matrix with dignity diagonal, shame pairs,
    DUAL/FRIEND/ENEMY/NEUTRAL classifications, and a TOTALS row.
    """

    # SPEC-AVA-001: the Avastha panel cycles through the pure view plus four
    # strength-refined views. "pure" is the original matrix; the rest scale every
    # influence by the influencer's bala (Duc = mean of Dig/Uccha/Cheshta).
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
        panel is already visible (set_visible is a no-op on True->True)."""
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
                sign_name, ring, being_type)
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
                chart, self._state.aditya_mode, sign_name, ring, being_type)
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        if self._view == "pure":
            self._refresh_pure()
        else:
            self._refresh_refined(self._view)

    def _refresh_pure(self):
        gui = self._gui
        if not hasattr(gui, "avastha_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.avastha_table.clearContents()

        try:
            from AI_tools.AI_main_function.avastha import (
                get_drishti_yuti_data, ASPECTING_PLANETS, REL_SYMBOL,
            )

            if self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")

            planets = chart

            data = get_drishti_yuti_data(planets)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shamed_planets = data["shamed_planets"]
            shame_pairs = data.get("shame_pairs", set())

            cell_categories = {}
            planet_order = list(ASPECTING_PLANETS)

            # Diagonal = self-conjunction base 60 x dignity multiplier
            # (SPEC-AVA-001 rev3: EX=120, MK=105, OH=90, none/debilitated=60).
            from core.avastha_totals import SELF_BASE, dignity_multiplier

            for row_idx, aspecting in enumerate(planet_order):
                for col_idx, aspected in enumerate(planet_order):
                    if aspecting == aspected:
                        dig = dignity_data.get(aspecting)
                        val = SELF_BASE * dignity_multiplier(
                            dig["virupas"] if dig else 0)
                        if dig:
                            abbr = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
                            label = abbr.get(dig["type"], "?")
                            # No "=" separator: 6+ chars elide in the ~45px
                            # stretch columns ("EX=120" -> "EX=1…").
                            text = f"{label}{val:.0f}"
                            cell_categories[(row_idx, col_idx)] = "PROUD"
                        else:
                            text = f"{val:.0f}"
                    else:
                        entry = matrix.get((aspecting, aspected))
                        if entry is None or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                            text = "."
                        else:
                            vr = entry["virupas"] if entry.get("is_yuti") else entry["virupas"]
                            rel = entry["relationship"]
                            sym = REL_SYMBOL.get(rel, " ")

                            if (aspecting, aspected) in shame_pairs:
                                if rel in ("NEUTRAL", "N/A"):
                                    sym = "-"
                                text = f"{vr:.0f}{sym}!"
                                cell_categories[(row_idx, col_idx)] = "SHAME"
                            elif rel == "DUAL":
                                text = f"{vr:.0f}±"
                                cell_categories[(row_idx, col_idx)] = "DUAL"
                            else:
                                text = f"{vr:.0f}{sym}"
                                if rel in ("FRIEND", "ENEMY", "NEUTRAL"):
                                    cell_categories[(row_idx, col_idx)] = rel

                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    gui.avastha_table.setItem(row_idx, col_idx, item)

            # TOTAL row (7) + POS row (8) + NEG row (9) — SPEC-AVW-001 T1 +
            # SPEC-AVA-001 §12.3. split_expression is the shared spine; TOTAL is
            # rendered as POS + NEG so the rev4 invariant holds float-exact.
            from core.avastha_totals import split_expression
            col_totals, pos_list, neg_list = [], [], []
            for col_idx, aspected in enumerate(planet_order):
                up, aff = split_expression(
                    aspected, planet_order, matrix, dignity_data, shame_pairs)
                total = up + aff
                col_totals.append(total)
                pos_list.append(up)
                neg_list.append(aff)
                item = QTableWidgetItem(f"{total:.0f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gui.avastha_table.setItem(self.ROW_TOTAL, col_idx, item)

            # POS/NEG (8/9) + SIGN/HORA/TRIMSAMSA (10/11/12) — pure integers.
            self._render_bottom_rows(
                gui, planet_order, planets, self._state.aditya_mode,
                pos_list, neg_list, col_totals, cell_categories, decimals=0)

            if hasattr(gui, "avastha_delegate"):
                gui.avastha_delegate.update_categories(cell_categories)
                gui.avastha_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating Avastha: {e}")
            traceback.print_exc()

    def _refresh_refined(self, view):
        """Render a strength-refined view (duc/dig/uccha/cheshta) — SPEC-AVA-001.

        Reuses the exact 7x7 + TOTAL + SIGN geometry of the pure view. Each
        off-diagonal cell = yuti scaled by the influencer's bala; the diagonal
        is the planet's own bala x dignity multiplier (EX x2, MK x1.75, OH x1.5);
        a plain neutral is visual-only (0 in totals), but a SHAME subtracts the
        shamer's A-scaled lack — the starved amount, never more (rev5 §3.1).
        A DUAL gives (S-scaled) and takes (A-scaled) and shows its NET
        contribution (rev4.1 §13).
        """
        gui = self._gui
        if not hasattr(gui, "avastha_table"):
            return

        active_chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not active_chart:
            return

        gui.avastha_table.clearContents()

        try:
            from AI_tools.AI_main_function.avastha import (
                get_drishti_yuti_data, ASPECTING_PLANETS,
            )
            from core.avastha_refined import refined_matrix, REFINE_KEYS
            from core.bala_calculator import get_all_bala_data

            # Matrix chart: sidereal-rebuilt like the pure path (sidereal signs).
            matrix_chart = active_chart
            if self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                matrix_chart = rebuild_chart(active_chart, mode="sidereal")

            data = get_drishti_yuti_data(matrix_chart)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shame_pairs = data.get("shame_pairs", set())

            # Balas follow the STRENGTH PANEL (SPEC-AVA-001 §6): pass the ACTIVE
            # chart (not the sidereal matrix chart) — get_all_bala_data handles
            # sidereal internally exactly like strength_controller.
            balas = get_all_bala_data(active_chart)

            planet_order = list(ASPECTING_PLANETS)
            key = view if view in REFINE_KEYS else "duc"
            rm = refined_matrix(planet_order, matrix, dignity_data,
                                shame_pairs, balas, key)

            cell_categories = {}

            for row_idx, actor in enumerate(planet_order):
                for col_idx, target in enumerate(planet_order):
                    tooltip = None
                    if actor == target:
                        # Diagonal: own bala x dignity multiplier; the EX/MK/OH
                        # label marks WHICH dignity amplified it.
                        val, dtype = rm["diagonal"][actor]
                        if dtype:
                            abbr = {"exaltation": "EX", "mulatrikona": "MK",
                                    "own_sign": "OH"}
                            label = abbr.get(dtype, "?")
                            # Integer + no "=": "EX=80.6" (7 chars) elides in the
                            # ~45px columns; "EX81" always fits. Full precision
                            # stays in the CLI/JSON and the popup dialog.
                            text = f"{label}{val:.0f}"
                            cell_categories[(row_idx, col_idx)] = "PROUD"
                        else:
                            text = f"{val:.1f}"
                    else:
                        cell = rm["cells"].get((actor, target))
                        if cell is None:
                            text = "."
                        else:
                            marker = "!" if cell["is_shame"] else ""
                            # A two-sided cell (DUAL, or a shame over a friendly
                            # base) shows the NET give-take (rev4.1 §13/D13,
                            # rev5), which may be negative; the tooltip spells
                            # out the two sides. Category is never recolored by
                            # the net's sign.
                            text = f"{cell['value']:.1f}{cell['symbol']}{marker}"
                            cell_categories[(row_idx, col_idx)] = cell["category"]
                            if cell["is_shame"] and cell["relationship"] == "FRIEND":
                                # A shame never gives. The friendship gives and
                                # the shame takes — say which is which.
                                tooltip = (f"friendship gives {cell['give']:.1f} / "
                                           f"shame takes {cell['take']:.1f}")
                            elif cell["two_sided"]:
                                # DUAL base (shamed or not): both sides were
                                # already on, so neither is the shame's doing.
                                tooltip = (f"dual gives {cell['give']:.1f} / "
                                           f"takes {cell['take']:.1f}")
                            elif cell["is_shame"]:
                                tooltip = (f"shames: takes {cell['take']:.1f} "
                                           f"({actor}'s bala lack)")

                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if tooltip:
                        item.setToolTip(tooltip)
                    gui.avastha_table.setItem(row_idx, col_idx, item)

            # TOTAL row (7) + POS row (8) + NEG row (9) — refined, one decimal.
            # POS/NEG come straight from refined_matrix (SPEC-AVA-001 §12.3);
            # TOTAL == POS + NEG float-exact by construction.
            col_totals, pos_list, neg_list = [], [], []
            for col_idx, target in enumerate(planet_order):
                total = rm["totals"][target]
                col_totals.append(total)
                pos_list.append(rm["pos"][target])
                neg_list.append(rm["neg"][target])
                item = QTableWidgetItem(f"{total:.1f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gui.avastha_table.setItem(self.ROW_TOTAL, col_idx, item)

            # POS/NEG (8/9) + SIGN/HORA/TRIMSAMSA (10/11/12). Retinue rows follow
            # the matrix chart (sidereal-rebuilt in sidereal mode), one decimal.
            self._render_bottom_rows(
                gui, planet_order, matrix_chart, self._state.aditya_mode,
                pos_list, neg_list, col_totals, cell_categories, decimals=1)

            if hasattr(gui, "avastha_delegate"):
                gui.avastha_delegate.update_categories(cell_categories)
                gui.avastha_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating refined Avastha ({view}): {e}")
            traceback.print_exc()

    def _render_bottom_rows(self, gui, planet_order, sign_chart, aditya_mode,
                            pos_list, neg_list, col_totals, cell_categories,
                            decimals):
        """Render the POS/NEG/SIGN/HORA/TRIMSAMSA rows (SPEC-AVA-001 §12).

        Shared by the pure and refined views (only the precision and the source
        chart differ). Populates ``self._retinue_cols`` so a click on a retinue
        cell can resolve the being (§12.5). ``sign_chart`` is the matrix chart
        (sidereal-rebuilt in sidereal mode) — the retinue rows are frame-dependent
        like the SIGN row.
        """
        from core.chart_helpers import (
            get_planet_sign_index, get_planet_in_sign_longitude,
            ADITYA_NAMES, TROPICAL_NAMES,
        )
        from core.avastha_totals import sign_total_category, display_split
        from AI_tools.AI_main_function.retinue import (
            get_hora, get_trimsamsa_being, ADITYA_SIGN_ORDER,
        )

        center = Qt.AlignmentFlag.AlignCenter
        sign_names = ADITYA_NAMES if aditya_mode == "aditya" else TROPICAL_NAMES
        self._retinue_cols = {}

        def _put(row, col, text, category=None, tooltip=None):
            item = QTableWidgetItem(text)
            item.setTextAlignment(center)
            if tooltip:
                item.setToolTip(tooltip)
            gui.avastha_table.setItem(row, col, item)
            if category is not None:
                cell_categories[(row, col)] = category

        for col_idx, target in enumerate(planet_order):
            pos = pos_list[col_idx]
            neg = neg_list[col_idx]

            # POS: green (FRIEND) when > 0, neutral at 0. NEG: red (ENEMY) when
            # < 0 (keeps its minus sign), neutral at 0. (§12.4) display_split
            # keeps the DISPLAYED invariant POS + NEG = TOTAL (NEG absorbs the
            # rounding residue); categories follow the displayed strings so a
            # rendered "0" is never tinted.
            pos_s, neg_s, _ = display_split(pos, neg, decimals)
            _put(self.ROW_POS, col_idx, pos_s,
                 "FRIEND" if float(pos_s) > 0 else "NEUTRAL")
            _put(self.ROW_NEG, col_idx, neg_s,
                 "ENEMY" if float(neg_s) < 0 else "NEUTRAL")

            # SIGN — colored by the planet's TOTAL (boosted/afflicted), as before.
            sign_idx = get_planet_sign_index(sign_chart, target, default=-1)
            in_range = 0 <= sign_idx < 12
            sign_text = sign_names[sign_idx] if in_range else "?"
            aditya_sign = ADITYA_SIGN_ORDER[sign_idx] if in_range else None
            sign_tip = (f"{aditya_sign} / {TROPICAL_NAMES[sign_idx]}"
                        if aditya_sign else None)
            _put(self.ROW_SIGN, col_idx, sign_text,
                 sign_total_category(col_totals[col_idx]), sign_tip)

            col_info = {"aditya_sign": aditya_sign,
                        "hora_type": None, "trim_type": None}

            if aditya_sign:
                deg = get_planet_in_sign_longitude(sign_chart, target)
                hora = get_hora(aditya_sign, deg)
                trim = get_trimsamsa_being(aditya_sign, deg)

                side = hora.get("side", "?")
                # Sun-hora being name follows the current mode's sign label
                # (§12.5); Naga-hora being is the fixed Naga name.
                hora_disp = sign_text if side == "Aditya" else hora.get("being_name", "?")
                _put(self.ROW_HORA, col_idx, hora_disp,
                     "HORA_ADITYA" if side == "Aditya" else "HORA_NAGA",
                     f"{hora.get('being_name', '?')} "
                     f"({side} side, {hora.get('lord', '?')} hora)")
                col_info["hora_type"] = "aditya" if side == "Aditya" else "naga"

                btype = trim.get("being_type", "")
                trim_name = trim.get("being_name", "?")
                _put(self.ROW_TRIMSAMSA, col_idx, trim_name,
                     "TRIM_" + str(btype).upper(),
                     f"{trim_name} ({btype}, {trim.get('element', '?')})")
                col_info["trim_type"] = str(btype).lower()
            else:
                _put(self.ROW_HORA, col_idx, "?")
                _put(self.ROW_TRIMSAMSA, col_idx, "?")

            self._retinue_cols[col_idx] = col_info

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
            dlg.exec()
            dlg.deleteLater()      # else hidden child dialogs pile up (Codex review)
        except Exception as e:
            import traceback
            print(f"Error opening retinue dialog: {e}")
            traceback.print_exc()
