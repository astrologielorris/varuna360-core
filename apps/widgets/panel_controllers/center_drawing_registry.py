# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The registry of the center drawing controllers (SPEC-VAC-001 §4.5): their ONE owner (no
``ChartGUI`` attribute, INV-12; W6 G1), keyed by ``id(gui)``. ``_entry`` makes an entry and
connects the GUI's ``destroyed`` once (it drops the entry; a release only empties it).
``PanelLinks``: a controller's panel connections and matrix, all cut on its teardown."""
from __future__ import annotations

from contextlib import suppress
from functools import partial

from PySide6.QtCore import QTimer

_SYNC = "mode_sync"                           # the registry entry of the CenterModeSync
_REGISTRY = {}                                # id(gui) -> {kind: controller, _SYNC: sync}


def register_center_controller(gui, kind, controller):
    """Keep ``controller`` for (gui, kind); returns it."""
    _entry(gui)[kind] = controller
    return controller


def _entry(gui):
    """The GUI's entry, made only here with its one drop on the GUI's ``destroyed``."""
    entry = _REGISTRY.get(id(gui))
    if entry is None:
        entry = _REGISTRY[id(gui)] = {}
        gui.destroyed.connect(partial(_release, id(gui), True))
    return entry


def center_controller(gui, kind):
    """The registered controller of ``kind`` for this GUI, or None."""
    return _REGISTRY.get(id(gui), {}).get(kind)


def center_controllers(gui):
    """Every registered drawing controller of this GUI (the mode sync excluded)."""
    return tuple(c for k, c in _REGISTRY.get(id(gui), {}).items() if k != _SYNC)


def release_center_controllers(gui):
    """Tear down every controller (and the mode sync) of this GUI."""
    _release(id(gui))


def _release(key, drop=False, *_):
    entry = (_REGISTRY.pop(key, None) if drop else _REGISTRY.get(key)) or {}
    items = tuple(entry.values())
    entry.clear()
    for item in items:
        item.teardown()


def unregister(gui, kind, controller):
    """A controller's own teardown: drop it; the last one takes the mode sync along."""
    entry = _REGISTRY.get(id(gui))
    if entry is None or entry.get(kind) is not controller:
        return
    del entry[kind]
    if not any(k != _SYNC for k in entry):
        _release(id(gui))


def ensure_center_controllers(gui, classes, settings):
    """The controllers of ``classes`` in that order, the same ones on a second call (W6 G1). A
    new aspects stack releases them all and the sync; one on an older table is replaced."""
    sync = center_controller(gui, _SYNC)
    if sync is not None and sync._stack is not getattr(gui, "aspects_stack", None):
        release_center_controllers(gui)
    return tuple(create_center_controller(gui, cls, settings) for cls in classes)


def create_center_controller(gui, cls, settings):
    """One controller per (GUI, kind), connected to the state, its first chart refresh
    scheduled; a second call returns it, unless torn down or built on an older table."""
    found = center_controller(gui, cls.KIND)
    if found is not None and getattr(found, "_alive", False):
        table = getattr(getattr(found, "_links", None), "table", None)
        if table is getattr(gui, getattr(cls, "TABLE", ""), None):
            return found
        found.teardown()
    controller = cls(gui, settings)            # registers itself while it builds
    state = getattr(gui, "state", None)
    if state is not None:
        controller.connect_to_state(state)
        if state.active_chart:
            QTimer.singleShot(0, controller._on_chart_changed)
    return controller


class PanelLinks:
    """The panel connections of one controller and the matrix it was built on."""

    def __init__(self, table):
        self.table = table
        self._links = []

    def add(self, signal, slot, *kind):
        signal.connect(slot, *kind)
        self._links.append((signal, slot))

    def cut(self):
        for signal, slot in self._links:
            with suppress(RuntimeError, TypeError):      # the sender is already gone
                signal.disconnect(slot)
        self._links = []
        self.table = None
