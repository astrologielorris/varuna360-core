# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Vedic center of the vector South Indian view (SPEC-VAC-001 §3.1, §4.2).

The Vedic drawing KIND of the shared center pass (``south_indian_center_pass``, reached
through its kind table): its full model (``karakas_aspects.vedic_full_model``, the matrix's
own data, INV-4), selection, item, animation length and tour hook, which the binding of
each view calls, and the public Vedic API (``set_vedic_center``, ``vedic_center_status``,
``vedic_center_model``) as one-line wrappers of the shared push API. The binding, the
precedence and the animation live in the shared pass.
"""
from __future__ import annotations

from core import vedic_center as vc
from core.capabilities.karakas_aspects import vedic_full_model
from apps.widgets import south_indian_center_pass as cp
from apps.widgets.center_drawing_item import CenterKind
from apps.widgets.south_indian_vedic_center import (VedicCenterItem, animation_total_ms,
                                                    palette)
from apps.widgets.south_indian_vedic_tour import tour_draw  # noqa: F401  (the kind's tour hook)

KIND = vc.VEDIC
LABEL = "Vedic"


# ------------------------------------------------------------ the drawing kind
_ITEM = CenterKind(VedicCenterItem, palette, lambda model: len(model.drawn_casts),
                   animation_total_ms)
make_item, animation_ms = _ITEM.make_item, _ITEM.animation_ms
reduce_motion = cp.reduce_motion              # a test replaces this name


def make_signal():
    """No kind-specific signal: the shared ``changed(reason, revision)`` carries it."""
    return None


def full_model(chart):
    return vedic_full_model(chart)


def select(full, state):
    return vc.select(full, state.min_virupas, state.lit_casters, state.lit_receivers)


# ------------------------------------------------------------ the push API
def set_vedic_center(target, state, animate=True):
    """Push a ``VedicCenterState`` to a South Indian host (or its vector view). Only the
    vector child draws; the classic theme's center is untouched. Returns True when the
    state changed."""
    return cp.set_center_drawing(target, KIND, state, animate)


def vedic_center_status(target):
    """The Vedic reason: the precedence reason when the Vedic drawing is the drawn kind
    (``shown``, ``off``, ``time_adjust``, ``guide``, ``no_chart``, ``varga``,
    ``compass``), ``inactive`` (ON while the panel shows the Tajika mode), ``off``, or
    ``not_vector``."""
    return cp.center_drawing_status(target, KIND)[0]


def vedic_center_model(target):
    """The ``VedicModel`` the drawing shows now (for the capture and the CLI), or None."""
    return cp.center_drawing_model(target, KIND)
