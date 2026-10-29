# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The drawings in the center of the vector South Indian view (SPEC-VAC-001 §3.1, §4.0): a
binding per vector view (weak dictionary) wraps the rebuild's medallion callable; it holds the
panel ``mode`` and one slot per kind. ``KINDS``: static lazy loaders (no dynamic import)."""
from __future__ import annotations

import weakref
from dataclasses import replace
from functools import partial
from types import SimpleNamespace

from core import center_geometry as cg
from apps.widgets.south_indian_center_slot import CenterSlot

SHOWN_PROPERTY = "center_drawing_shown"     # scene property read by exchange_chain_centre
MODEL_ERROR = "model_error"                  # status reason: the model failed, no item (W5 review)


def _tajika():
    from apps.widgets import south_indian_tajika_pass as module
    return module


def _vedic():
    from apps.widgets import south_indian_vedic_pass as module
    return module


# The drawing kinds, in priority order: with no mode set and both slots ON, the first wins.
KINDS = (("tajika", _tajika), ("vedic", _vedic))
_LOADERS = dict(KINDS)
_BINDINGS = weakref.WeakKeyDictionary()      # vector view -> _Binding


def reduce_motion():
    """``ui.reduce_motion``: no switch-on animation."""
    from managers.settings_manager import get_settings
    try:
        return bool(get_settings().get_reduce_motion())
    except Exception:
        return False


class _Binding:
    """One view's drawings: the panel mode, one slot per kind (table order) and the
    revision that every mode change and state change increments (§4.6)."""

    def __init__(self):
        self.mode = None
        self.slots = {}
        self.revision = 0

    def slot(self, kind_name, create=False):
        found = self.slots.get(kind_name)
        if found is None and create and kind_name in _LOADERS:
            found = self.slots[kind_name] = CenterSlot(_LOADERS[kind_name]())
            self.slots = {k: self.slots[k] for k, _ in KINDS if k in self.slots}  # table order
        return found

    def drawn_kind(self):
        """The kind whose precedence runs: the mode's kind (None when the table has no
        such kind); with no mode, the first ON slot, else the first slot."""
        if self.mode is not None:
            return self.mode if self.mode in _LOADERS else None
        names = list(self.slots)
        on = [k for k in names if self.slots[k].on]
        return (on or names or [None])[0]

    def set_state(self, kind_name, state, redraw, animate=True):
        """Store a kind's pushed state. A rebuild only when that kind is (or becomes) the
        drawn kind, else a status-only publication; an OFF -> ON of the drawn kind asks
        the next drawing for the switch-on animation. An equal state is ignored."""
        slot = self.slot(kind_name, create=True)
        if slot is None or state == slot.state:
            return False
        before, was_on = self.drawn_kind(), slot.on
        slot.state = state
        self.revision += 1
        after = self.drawn_kind()
        if kind_name not in (before, after):
            slot.publish((None, "inactive" if slot.on else "off"), self.revision)
            return True
        slot.anim_requested = bool(animate and kind_name == after and slot.on and not was_on)
        redraw()
        return True

    def set_mode(self, kind_name, redraw):
        """Which drawing may show. One redraw, never an animation; an equal mode is
        ignored (no redraw, no signal)."""
        if kind_name == self.mode:
            return False
        self.mode = kind_name
        self.revision += 1
        for slot in self.slots.values():
            slot.anim_requested = False
        redraw()
        return True

    def publish(self, drawn, status):
        """After a precedence: the drawn kind gets it, every other slot ``inactive``
        (ON) or ``off``."""
        for name, slot in self.slots.items():
            other = (None, "inactive" if slot.on else "off")
            slot.publish(status if name == drawn else other, self.revision)

    def stop(self, *_args):
        for slot in self.slots.values():
            slot.stop()


def _binding(view, create=False):
    found = _BINDINGS.get(view)
    if found is None and create:
        found = _BINDINGS.setdefault(view, _Binding())
        view.destroyed.connect(found.stop)
    return found


def vector_child(target):
    """The vector view behind a host (or the view itself); None for anything else,
    including the inert mini view (SIC-003 INV-6)."""
    child = getattr(target, "vector_view", target)
    return child if getattr(child, "center_box_enabled", False) and hasattr(child, "center") else None


# ------------------------------------------------------------ the rebuild's hook
def center_draw(view, style, request):
    """The zero-argument medallion callable ``draw_chrome`` runs (INV-2)."""
    return partial(_draw_center, view, style, request)


def choice(view, state, drawn):
    """The center precedence of ``view`` for a drawing in ``state`` (or None)."""
    center = view.center
    return cg.center_choice(
        time_adjust=center.time_adjust_mode, guide_active=bool(view.guide.enabled),
        has_chart=view._chart is not None, state=state, varga_code=view._varga_code,
        compass_active=view.placement_frame is not None,
        transit_active=center._transit_overlay_active, center_varga=center._center_varga_code,
        drawn=drawn)


def _draw_center(view, style, request):
    binding = _binding(view)
    if binding is None:
        return view.center._draw_medallion(view.scene, style, request)
    binding.stop()
    drawn = binding.drawn_kind()
    slot = binding.slots.get(drawn)
    status = choice(view, slot.state if slot is not None else None, drawn or cg.DRAWING)
    if slot is not None and status[0] == drawn and not _model_ready(slot, request):
        status = (cg.EMPTY, MODEL_ERROR)             # no item: not shown, the chains come back
    binding.publish(drawn, status)
    shown = slot is not None and status[0] == drawn
    view.scene.setProperty(SHOWN_PROPERTY, shown)                 # the exchange chains step aside
    if not shown:
        return view.center._draw_medallion(view.scene, style, request)
    view.center._draw_medallion(view.scene, style, replace(request, chart=None))
    slot.draw(view.scene, style, request)
    slot.kind.tour_draw(view)                                     # the tour's overlay (§4.9)
    return None


def redraw(view):
    """After a state or mode change (W6 S1): when a drawing is on screen and the drawn
    kind stays shown, only the center drawing and the tour overlay are replaced (the
    medallion is already the plain one); every other case is the full rebuild."""
    if not _redraw_center(view, _binding(view)):
        view.draw_full_chart()


def _shown_slot(binding):
    """The slot whose drawing is on screen: the statuses are still the last drawing's
    (a redraw publishes them), and its item is alive."""
    return next((s for s in binding.slots.values()
                 if s.status[1] == "shown" and s.item() is not None), None)


def _redraw_center(view, binding):
    shown, drawn = _shown_slot(binding), binding.drawn_kind()
    slot = binding.slots.get(drawn)
    if shown is None or shown.drawn_with is None or slot is None:
        return False
    style, request = shown.drawn_with
    status = choice(view, slot.state, drawn)
    if status[0] != drawn or not _model_ready(slot, request):
        return False
    old = [s.item() for s in binding.slots.values()]
    binding.stop()
    for item in (i for i in old if i is not None):
        view.scene.removeItem(item)
        item.deleteLater()
    slot.draw(view.scene, style, request)
    for other in binding.slots.values():            # the drawn kind's overlay is placed again
        other.kind.tour_draw(view)
    binding.publish(drawn, status)
    return True


def _model_ready(slot, request):            # the full model builds (cached for the draw)
    try:
        slot.full_model(request.chart, request)
        return True
    except Exception as e:
        print(f"[SI VECTOR] {slot.kind.LABEL} center skipped: {e}")
        return False


# ------------------------------------------------------------ the push API
def set_center_drawing(target, kind_name, state, animate=True):
    """Push a drawing kind's state to a South Indian host (or its vector view). Only the
    vector child draws; the classic theme's center is untouched. Returns True when the
    state changed."""
    child = vector_child(target)
    if child is None:
        return False
    return _binding(child, create=True).set_state(kind_name, state, partial(redraw, child), animate)


def set_center_mode(target, kind_name):
    """Set which drawing may show (``CenterModeSync`` and the CLI dispatch only).
    Returns True when the mode changed (one redraw)."""
    child = vector_child(target)
    if child is None:
        return False
    return _binding(child, create=True).set_mode(kind_name, partial(redraw, child))


def center_slot(target, kind_name, create=False):
    """The kind's slot on the target's vector view (signals, state), or None."""
    child = vector_child(target)
    binding = _binding(child, create) if child is not None else None
    return binding.slot(kind_name, create) if binding is not None else None


def center_drawing_status(target, kind_name):
    """(reason, revision): the drawn kind's precedence reason (``shown``, ``off``, ``guide``...,
    ``model_error``), else ``inactive`` (ON) / ``off``; ``not_vector`` off the vector view."""
    child = vector_child(target)
    if child is None or getattr(target, "active_view", child) is not child:
        return "not_vector", 0
    binding = _binding(child)
    slot = binding.slots.get(kind_name) if binding is not None else None
    return (slot.status[1] if slot is not None else "off"), (binding.revision if binding else 0)


def center_status_signal(target, kind_name):
    """The kind's ``changed(reason, revision)`` signal on the target's vector view, or None."""
    slot = center_slot(target, kind_name, create=True)
    return None if slot is None else slot.signal


def center_drawing_model(target, kind_name):
    """The model the kind's drawing shows now (for the capture and the CLI), or None."""
    child = vector_child(target)
    slot = center_slot(child, kind_name) if child is not None else None
    if slot is None or slot.status[1] != "shown":
        return None
    return slot.kind.select(slot.full_model(child._chart, model_request(child)), slot.state)


def center_drawing_painted_model(target, kind_name, chart=None):
    """The model the kind's drawing item last PAINTED on the target's vector view, when it
    was built for ``chart`` (default: the view's chart); None otherwise (never painted,
    painted for an earlier chart). The capture's ``drawn`` (W6 R8)."""
    child = vector_child(target)
    slot = center_slot(child, kind_name) if child is not None else None
    item = slot.item() if slot is not None else None
    chart = child._chart if chart is None and child is not None else chart
    if item is None or chart is None:
        return None
    try:
        built = tuple(slot.models.get(chart, {}).values())
    except TypeError:                       # a chart that cannot be weak-referenced
        return None
    model = item._model                     # both drawing items keep their model there
    return model if any(full is model.full for full in built) else None


def center_drawing_shown(view):
    """True while a drawing holds the center of ``view`` (the exchange chains step aside)."""
    return bool(view.scene.property(SHOWN_PROPERTY))


def model_request(view):
    return SimpleNamespace(aditya_mode=view._aditya_mode, western_names=view._use_western_names,
                           language=view.sign_language)
