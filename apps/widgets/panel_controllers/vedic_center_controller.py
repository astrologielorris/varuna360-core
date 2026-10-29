# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The state owner of the Vedic center drawing (SPEC-VAC-001 §4.5).

Owns on/off and min_virupas (settings ``chart.vedic_center_on`` /
``chart.vedic_center_min_virupas``) and the two lit sets by role (lit casters, lit
receivers; runtime only, D-4). The shared ``CenterDrawingController`` builds the toggle,
the key headers of the Aspects V matrix, the rail and the tour key, pushes the real state
to the main South Indian host, follows its status (toggle tooltip, focus hold owner
"vedic") and tears down; this class is the Vedic drawing: split-role keys, lane tint,
counts, rail ticks, tour steps and the panel's current model (``VedicPanelData``) that
serves the key, cell and tick tooltips.

No manager import: the settings object is injected (``info_panels.create_center_controllers``).
"""
from __future__ import annotations

from functools import partial

from apps.widgets.panel_controllers.center_drawing_controller import (
    CenterDrawingController, CenterParts, main_host)
from apps.widgets.panel_controllers.vedic_center_capture import observation_of
from core.settings_registry.center_keys import VEDIC_CENTER_KEYS
from core.vedic_center import BODY_ORDER, CASTERS, VEDIC, VedicCenterState, tour_steps

KEY_ON, KEY_MIN = VEDIC_CENTER_KEYS          # declared in the settings registry
NO_LIT = (frozenset(), frozenset())          # (lit casters, lit receivers)


def sign_name_of(gui, index: int) -> str:
    """A sign's name in the main host's frame (zodiac mode, label set, language)."""
    from apps.widgets.south_indian_center_pass import model_request, vector_child
    from core.aditya_mode import displayed_sign_name
    child = vector_child(main_host(gui))
    if child is None:                        # no South Indian host: the Aditya names
        return displayed_sign_name(index, None, False)
    request = model_request(child)
    return displayed_sign_name(index, request.aditya_mode, request.western_names,
                               request.language)


def full_model_of(state):
    """The Vedic full model of the active chart (the matrix's data, INV-4), or None."""
    chart = getattr(state, "active_chart", None) if state is not None else None
    if not chart:
        return None
    try:
        from core.capabilities.karakas_aspects import vedic_full_model
        return vedic_full_model(chart)
    except Exception as e:
        print(f"[Vedic center] aspects unavailable: {e}")
        return None


class VedicCenterController(CenterDrawingController):
    """Eager; created by ``info_panels.create_center_controllers`` and kept in the center
    drawing registry only (no ``ChartGUI`` attribute, INV-12)."""

    KIND = VEDIC
    KEY_ON, KEY_MIN = KEY_ON, KEY_MIN
    TABLE = "aspects_table"
    NO_LIT = NO_LIT

    def __init__(self, gui, settings):
        from apps.panels.vedic_center_keys import VedicPanelData
        self._data = VedicPanelData(partial(sign_name_of, gui))     # read while building
        super().__init__(gui, settings)
        if self._widgets.rail is not None:
            self._widgets.rail.tick_text = self._data.tick_text

    # ------------------------------------------------------------ the drawing's hooks
    def _parts(self):
        from apps.panels import vedic_center_keys as keys
        return CenterParts(keys.VedicCenterToggle,
                           partial(keys.install_key_headers, texts=self._data),
                           keys.VedicVirupaRail, keys.VedicTourKey,
                           partial(keys.VedicCellMarks, texts=self._data))

    @staticmethod
    def _as_lit(lit):
        """``(casters, receivers)``; an empty value lights nothing."""
        pair = tuple(lit or ())
        return NO_LIT if not pair else (frozenset(pair[0]), frozenset(pair[1]))

    def _make_state(self, on):
        return VedicCenterState(on, self._min, *self._lit)

    @staticmethod
    def _push_state(host, state):
        from apps.widgets.south_indian_vedic_pass import set_vedic_center
        set_vedic_center(host, state)

    def _lit_after_press(self, key):
        """A key press ``(role, body)`` toggles the body in that role's set only."""
        from apps.panels.vedic_center_keys import CASTER
        role, body = key
        casters, receivers = set(self._lit[0]), set(self._lit[1])
        (casters if role == CASTER else receivers).symmetric_difference_update({body})
        return casters, receivers

    def _header_lit(self):
        casters, receivers = self._lit
        return receivers, casters                # (horizontal, vertical) headers

    @staticmethod
    def _model(host):
        from apps.widgets.south_indian_vedic_pass import vedic_center_model
        return vedic_center_model(host)

    _tour_steps = staticmethod(tour_steps)          # drawn casts, then Yutis (§4.6)

    def _show_step(self, key, label):
        from apps.widgets.south_indian_vedic_tour import set_vedic_tour_focus
        return set_vedic_tour_focus(main_host(self._gui), key, label)

    def _clear_focus(self):
        import shiboken6
        from apps.widgets.south_indian_vedic_tour import set_vedic_tour_focus
        host = main_host(self._gui)
        if host is not None and shiboken6.isValid(host):
            set_vedic_tour_focus(host, None)

    def _ring(self, key):
        import shiboken6
        from apps.panels.vedic_center_keys import ring_cells
        cells = self._widgets.cells
        if cells is not None and shiboken6.isValid(cells):
            cells.show_cells(ring_cells(key))

    def _counts(self):
        return self._data.counts(self._min, *self._lit)

    def _ticks(self):
        return self._data.ticks()

    def observation(self):                   # the AI capture's view (§4.8, W6 R8)
        return observation_of(self, getattr(self._state, "active_chart", None))

    # ------------------------------------------------------------ state + chart
    def apply_state(self, **changes):
        """The one update path (shared), then the lit lanes of the matrix (§3.5)."""
        changed = super().apply_state(**changes)
        self._show_lanes()
        return changed

    def _show_lanes(self):
        import shiboken6
        cells = self._widgets.cells
        if cells is None or not shiboken6.isValid(cells):
            return
        casters, receivers = self._lit if self._on else NO_LIT
        cells.show_lanes([CASTERS.index(b) for b in CASTERS if b in casters],
                         [BODY_ORDER.index(b) for b in BODY_ORDER if b in receivers])

    def _on_chart_changed(self):
        """New chart or zodiac mode (Yutis follow the signs): new model, ticks, counts."""
        self._data.set_full(full_model_of(self._state))
        super()._on_chart_changed()

    _on_mode_changed = _on_chart_changed
