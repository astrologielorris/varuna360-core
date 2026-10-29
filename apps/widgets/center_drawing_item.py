# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""What the two center drawing items and their kinds share (SPEC-VAC-001 §4.0, W6 R2, R3).

The Tajika and Vedic items are ``QGraphicsObject`` subclasses with the same set-up (hover
on, no mouse buttons, z, DeviceCoordinateCache, scene tag), the same reveal timing (a
stagger inside a 700 ms budget, a 250 ms fade per layer, the studs popping over 250 ms) and
the same hover tooltip. They keep ``QGraphicsObject`` as their base (the SI architecture
guard protects a registered class's bases), so the shared part is these functions.

``CenterKind``: one drawing kind's item factory and animation length, which the kind
modules (``south_indian_tajika_pass``, ``south_indian_vedic_pass``) bind as their
``make_item`` and ``animation_ms``.
"""
from __future__ import annotations

from functools import partial
from typing import Callable, NamedTuple, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolTip

STUD_POP_MS = 250.0             # the studs pop 0.6 -> 1
FADE_MS = 250.0                 # one layer's fade in
STAGGER_BUDGET_MS = 700.0       # every layer has started by then
STAGGER_MAX_MS = 60.0


def stagger_ms(count: int) -> float:
    """The delay between two layers of a reveal of ``count`` layers."""
    return min(STAGGER_MAX_MS, STAGGER_BUDGET_MS / max(1, count))


def reveal_alpha(t_ms: Optional[float], begin_ms: float) -> float:
    """A layer's alpha at ``t_ms`` into the reveal when its fade begins at ``begin_ms``;
    1 when the reveal is over (``t_ms`` None)."""
    if t_ms is None:
        return 1.0
    return max(0.0, min(1.0, (t_ms - begin_ms) / FADE_MS))


def setup_item(item, z: float, tag: str):
    """Hover tooltips, no mouse buttons (INV-6), the z, the device cache and the tag."""
    item.setAcceptHoverEvents(True)
    item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    item.setZValue(z)
    item.setCacheMode(item.CacheMode.DeviceCoordinateCache)
    item.setData(Qt.ItemDataRole.UserRole, tag)


def hover_tooltip(item, event):
    """Show the item's ``tooltip_at`` text under the pointer, or hide the tooltip."""
    text = item.tooltip_at(event.pos().x(), event.pos().y())
    QToolTip.showText(event.screenPos(), text) if text else QToolTip.hideText()


def _sign_name(displayed_sign_name, request, index):
    return displayed_sign_name(index, request.aditya_mode, request.western_names, request.language)


class CenterKind(NamedTuple):
    """One drawing kind's item: its class, palette, drawn count and animation length."""
    item_class: type
    palette: Callable
    count: Callable[[object], int]              # the model's layers that fade in
    total_ms: Callable[[int], float]            # the animation length for that count

    def make_item(self, model, style, request, elapsed):
        from core.aditya_mode import displayed_sign_name
        from ui.qt_theme import scaled_tier_size
        names = partial(_sign_name, displayed_sign_name, request)
        return self.item_class(model, self.palette(style), elapsed, names,
                               scaled_tier_size(26, "chart_labels"))

    def animation_ms(self, model) -> float:
        return self.total_ms(self.count(model))
