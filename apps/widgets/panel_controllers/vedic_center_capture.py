# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The AI capture's view of the Vedic center drawing (SPEC-VAC-001 §4.8, W6 R8).

``VedicCenterController.observation()`` returns ``observation_of(controller, chart)``, as
the Tajika controller's own ``observation()`` does for its drawing; the capture
(``apps.ai_capture.regions``) only calls the hook. The picture on screen comes from the
pass's public ``center_drawing_painted_model``, never from the binding's internals.
"""
from __future__ import annotations

from apps.widgets.panel_controllers.center_drawing_controller import main_host
from core.vedic_center import BODY_ORDER, CODE_OF, VEDIC


def _codes(names) -> list:
    return [CODE_OF[n] for n in BODY_ORDER if n in names]


def lit_codes_by_role(casters, receivers):
    """Codes per role; ``"all"`` for both while no key is lit (every cast is drawn)."""
    if not casters and not receivers:
        return "all", "all"
    return _codes(casters), _codes(receivers)


def observation_of(ctrl, chart):
    """SPEC-VAC-001 §4.8, or None while the toggle is OFF: the current state (the
    controller's applied values; ``vedic_mode_off`` in the Tajika mode) and ``drawn``, the
    picture on screen (the painted model; null unless shown for ``chart``). During a rail
    drag the two differ: the pending value, then the painted one."""
    from apps.widgets.south_indian_center_pass import center_drawing_painted_model
    state = ctrl.state
    if not state.on:
        return None
    reason = ctrl.reason() if ctrl.in_mode() else "vedic_mode_off"
    casters, receivers = lit_codes_by_role(state.lit_casters, state.lit_receivers)
    painted = None
    if reason == "shown" and chart is not None:
        painted = center_drawing_painted_model(main_host(ctrl._gui), VEDIC, chart)
    drawn = None
    if painted is not None:
        p_casters, p_receivers = lit_codes_by_role(painted.lit_casters, painted.lit_receivers)
        drawn = {"min_virupas": painted.min_virupas, "lit_casters": p_casters,
                 "lit_receivers": p_receivers, "shown": painted.shown, "total": painted.total}
    return {"status": "shown" if reason == "shown" else "hidden", "reason": reason,
            "min_virupas": state.min_virupas, "lit_casters": casters,
            "lit_receivers": receivers, "drawn": drawn}
