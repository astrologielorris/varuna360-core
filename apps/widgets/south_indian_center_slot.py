# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""One drawing kind on one vector South Indian view (SPEC-VAC-001 §4.0): its pushed state,
model cache, status, signals and switch-on animation (moved out of
``south_indian_center_pass`` in W6, which keeps the binding, the precedence and the API)."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid

from core import center_geometry as cg


class CenterStatusSignal(QObject):
    """Carries one drawing kind's status and the binding revision to its panel (§4.6)."""
    changed = Signal(str, int)


class CenterSlot:
    """One drawing kind on one view: its pushed state, model cache, status, signals and
    switch-on animation. The animation reaches its item through a weak reference only
    (INV-8)."""

    def __init__(self, kind):
        self.kind = kind
        self.state = None
        self.models = weakref.WeakKeyDictionary()
        self.anim = None
        self.anim_requested = False
        self.item_ref = None
        self.drawn_with = None          # (style, request) of the item on screen (W6 S1)
        self.status = (cg.EMPTY, "off")
        self.signal = CenterStatusSignal()
        self.kind_signal = kind.make_signal()

    @property
    def on(self):
        return bool(self.state is not None and self.state.on)

    def publish(self, status, revision):
        """A new (center kind, reason): both signals, the kind's own one-argument one
        first (its exact SPEC-TJK-003 contract), then the shared (reason, revision)."""
        if status != self.status:
            self.status = status
            if self.kind_signal is not None:
                self.kind_signal.changed.emit(status[1])
            self.signal.changed.emit(status[1], revision)

    def full_model(self, chart, request):
        key = (request.aditya_mode, request.western_names, request.language)
        try:
            bucket = self.models.setdefault(chart, {})
        except TypeError:          # a chart that cannot be weak-referenced: no cache
            bucket = {}
        if key not in bucket:
            bucket[key] = self.kind.full_model(chart)
        return bucket[key]

    def draw(self, scene, style, request):
        model = self.kind.select(self.full_model(request.chart, request), self.state)
        item = self.kind.make_item(model, style, request, self.elapsed)
        scene.addItem(item)
        self.item_ref = weakref.ref(item)
        self.drawn_with = (style, request)
        del item
        if self.anim_requested:
            self.anim_requested = False
            self.start_animation(self.kind.animation_ms(model))

    def start_animation(self, duration_ms):
        from PySide6.QtCore import QVariantAnimation
        if self.kind.reduce_motion():
            return
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(int(duration_ms))
        anim.valueChanged.connect(self.on_tick)
        anim.finished.connect(self.on_finished)
        self.anim = anim
        anim.start()

    def elapsed(self):
        """Milliseconds into the switch-on animation; None = finished (full drawing)."""
        return None if self.anim is None else float(self.anim.currentTime())

    def item(self):
        item = self.item_ref() if self.item_ref is not None else None
        return item if item is not None and isValid(item) else None

    def on_tick(self, _value):
        item = self.item()
        if item is not None:
            item.update()

    def on_finished(self):
        self.anim = None
        self.on_tick(None)

    def stop(self, *_args):
        """End a running animation at its final state and forget the item. Called at
        the start of every center draw, i.e. right after the rebuild's scene.clear()."""
        anim, self.anim, self.item_ref, self.drawn_with = self.anim, None, None, None
        if anim is not None and isValid(anim):   # stop() emits no finished; dropped after
            anim.stop()
