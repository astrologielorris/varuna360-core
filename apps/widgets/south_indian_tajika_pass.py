# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Tajika center of the vector South Indian view (SPEC-TJK-003 §3.1, §4.2, §4.3).

The Tajika drawing KIND of the shared center pass (``south_indian_center_pass``,
SPEC-VAC-001 §4.0): its full model, selection, item, animation length and tour hook,
which the binding of each view calls, and the public Tajika API (``set_tajika_center``,
``tajika_center_status``, ``tajika_status_signal``, ``tajika_center_model``) as one-line
wrappers of the shared push API. The binding, the precedence hook and the animation live
in the shared pass.
"""
from __future__ import annotations

from core import tajika_center as tc
from apps.widgets import south_indian_center_pass as cp
from apps.widgets.center_drawing_item import CenterKind
from apps.widgets.south_indian_tajika_center import (TajikaCenterItem, TajikaStatusSignal,
                                                     animation_total_ms, palette)
from apps.widgets.south_indian_tajika_tour import tour_draw  # noqa: F401  (the kind's tour hook)

KIND = tc.TAJIKA
LABEL = "Tajika"


# ------------------------------------------------------------ the drawing kind
_ITEM = CenterKind(TajikaCenterItem, palette, lambda model: len(model.drawn), animation_total_ms)
make_item, animation_ms = _ITEM.make_item, _ITEM.animation_ms
make_signal = TajikaStatusSignal              # the ``changed(reason)`` of SPEC-TJK-003 §3.1
reduce_motion = cp.reduce_motion              # a test replaces this name


def full_model(chart):
    from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
    result = calculate_all_tajika_aspects(chart)
    return tc.build_full_model(tc.chart_positions(chart), result.get("aspects_within_orb", []))


def select(full, state):
    return tc.select(full, state.min_virupas, state.lit)


def _binding(view, create=False):
    """The view's Tajika slot (state, animation, status), or None."""
    return cp.center_slot(view, KIND, create)


def _vector_child(target):
    return cp.vector_child(target)


def _choice(view, binding):
    return cp.choice(view, binding.state if binding else None, KIND)


# ------------------------------------------------------------ the push API
def set_tajika_center(target, state, animate=True):
    """Push a ``TajikaCenterState`` to a South Indian host (or its vector view) and
    redraw it. Only the vector child draws; the classic theme's center is untouched.
    Returns True when the state changed."""
    return cp.set_center_drawing(target, KIND, state, animate)


def tajika_center_status(target):
    """The reason of the last precedence (§4.3): ``shown``, ``off``, ``time_adjust``,
    ``guide``, ``no_chart``, ``varga``, ``compass``, ``inactive`` (ON while the panel
    shows the Vedic mode), or ``not_vector`` when the host shows the classic theme or
    the target is not a South Indian view."""
    return cp.center_drawing_status(target, KIND)[0]


def tajika_status_signal(target):
    """The ``changed(reason)`` signal of the target's vector view, or None."""
    slot = cp.center_slot(target, KIND, create=True)
    return None if slot is None else slot.kind_signal


def tajika_center_model(target):
    """The ``CenterModel`` the drawing shows now (for the capture and the CLI), or None."""
    return cp.center_drawing_model(target, KIND)
