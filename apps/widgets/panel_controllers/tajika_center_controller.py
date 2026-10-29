# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The state owner of the Tajika center drawing (SPEC-TJK-003 §4.5).

Owns on/off and min_virupas (settings ``chart.tajika_center_on`` /
``chart.tajika_center_min_virupas``) and the lit set (runtime only, D-5). It builds the
toggle, the two key headers and the virupa rail, pushes a ``TajikaCenterState`` to the
main South Indian host on every change, follows the host's status signal for the
toggle tooltip and the info column's focus hold, and drops everything on teardown.

ONE update path: panel actions, startup hydration and Settings Apply / Reset / remote
writes all go through ``apply_state``, which ignores a write equal to the state.

The shared machinery (update path, push, status, hold, tour, widgets, registry and the
panel-mode owner ``CenterModeSync``) is ``CenterDrawingController`` (SPEC-VAC-001 §4.0);
this class is the Tajika drawing: its keys, matrix, state, counts, ticks and tour steps.
The real ON/OFF is pushed whatever the panel mode; the mode decides which drawing shows.
"""
from __future__ import annotations

from core.settings_registry.center_keys import TAJIKA_CENTER_KEYS
from core.tajika_center import TajikaCenterState
from apps.widgets.panel_controllers.center_drawing_controller import (  # noqa: F401
    KEY_TOUR, RAIL_DELAY_MS, CenterDrawingController, CenterParts)

KEY_ON, KEY_MIN = TAJIKA_CENTER_KEYS         # declared in the settings registry


class TajikaCenterController(CenterDrawingController):
    """Eager; created by ``info_panels.create_center_controllers`` and owned by the center
    drawing registry only (no ``ChartGUI`` attribute, SPEC-VAC-001 W6 G1)."""

    KIND = "tajika"
    KEY_ON, KEY_MIN = KEY_ON, KEY_MIN
    TABLE = "tajika_matrix_table"

    # ------------------------------------------------------------ old names (tests, capture)
    _toggle = property(lambda self: self._widgets.toggle)
    _headers = property(lambda self: self._widgets.headers)
    _rail = property(lambda self: self._widgets.rail)
    _tour_key = property(lambda self: self._widgets.tour_key)
    _cell_ring = property(lambda self: self._widgets.cells)
    _tour_timer = property(lambda self: self._tour.timer)

    def touring(self) -> bool:
        return self._tour.touring()

    def tajika_mode(self) -> bool:
        return self.in_mode()

    def _tour_step(self):
        self._tour.step()

    # ------------------------------------------------------------ the drawing's hooks
    def _parts(self):
        from apps.panels import tajika_center_keys as keys
        return CenterParts(keys.TajikaCenterToggle, keys.install_key_headers, keys.VirupaRail,
                           keys.TajikaTourKey, keys.TajikaCellRing)

    @staticmethod
    def _as_lit(lit):
        return frozenset(lit)

    def _make_state(self, on):
        return TajikaCenterState(on, self._min, self._lit)

    @staticmethod
    def _push_state(host, state):
        from apps.widgets.south_indian_tajika_pass import set_tajika_center
        set_tajika_center(host, state)

    def _lit_after_press(self, body):
        lit = set(self._lit)
        lit.symmetric_difference_update({body})
        return lit

    def _header_lit(self):
        return self._lit, self._lit             # a body's row and column key: one state

    @staticmethod
    def _model(host):
        from apps.widgets.south_indian_tajika_pass import tajika_center_model
        return tajika_center_model(host)

    @staticmethod
    def _tour_steps(model):
        return tuple((a.body1, a.body2) for a in model.drawn)

    def _show_step(self, pair, label):
        from apps.widgets.south_indian_tajika_tour import set_tajika_tour_focus
        return set_tajika_tour_focus(getattr(self._gui, "chart_view", None), pair, label)

    def _clear_focus(self):
        import shiboken6
        from apps.widgets.south_indian_tajika_tour import set_tajika_tour_focus
        view = getattr(self._gui, "chart_view", None)
        if view is not None and shiboken6.isValid(view):
            set_tajika_tour_focus(view, None)

    def _ring(self, pair):
        import shiboken6
        ring = self._widgets.cells
        if ring is None or not shiboken6.isValid(ring):
            return
        horizontal, vertical = self._headers if len(self._headers) == 2 else (None, None)
        if pair is None or horizontal is None:
            ring.show_cells(())
            return
        cols = {horizontal.body(i): i for i in range(horizontal.count())}
        rows = {vertical.body(i): i for i in range(vertical.count())}
        b1, b2 = pair
        cells = [(rows[r], cols[c]) for r, c in ((b1, b2), (b2, b1)) if r in rows and c in cols]
        ring.show_cells(cells)

    # ------------------------------------------------------------ capture (§4.8)
    def observation(self):
        """The AI capture's view of the drawing (§4.8), or None while the toggle is OFF."""
        if not (self._alive and self._on):
            return None
        from AI_tools.AI_main_function.tajika import TAJIKA_SHORT_NAMES
        reason = self.reason() if self.tajika_mode() else "tajika_mode_off"
        shown, total = self._rail._counts if self._rail is not None else (0, 0)
        return {"status": "shown" if reason == "shown" else "hidden", "reason": reason,
                "min_virupas": self._min,
                "lit": sorted(TAJIKA_SHORT_NAMES[b] for b in self._lit) if self._lit else "all",
                "shown": shown, "total": total}

    # ------------------------------------------------------------ rail data
    def _aspects(self):
        chart = getattr(self._state, "active_chart", None) if self._state else None
        if not chart:
            return []
        try:
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
            return calculate_all_tajika_aspects(chart).get("aspects_within_orb", [])
        except Exception as e:
            print(f"[Tajika center] aspects unavailable: {e}")
            return []

    def _counts(self):
        aspects = self._aspects()
        lit = self._lit
        shown = sum(1 for a in aspects if float(a.get("virupas", 0)) >= self._min
                    and (not lit or a.get("body1") in lit or a.get("body2") in lit))
        return shown, len(aspects)

    def _ticks(self):
        from apps.delegates.highlight_delegate import TajikaHighlightDelegate
        from core.tajika_center import category_of
        colours = TajikaHighlightDelegate.get_category_colors()
        ticks = []
        for a in self._aspects():
            v = float(a.get("virupas", 0))
            cat = category_of(v, a.get("relationship", ""))
            ticks.append((v, colours.get(cat, ("", "#808080"))[1]))
        return ticks
