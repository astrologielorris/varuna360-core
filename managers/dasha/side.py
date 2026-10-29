# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""One dasha side (SPEC-DSH-004 §3.1): ONE class, two instances (left, right).

A `DashaSide` owns the per-mode renderers of its side (created lazily from the
mode registry, one instance per mode) and dispatches every panel event to the
renderer of the side's current mode. Nothing in here, and nothing in a renderer,
names a side: the only per-side data is `SIDE_TRAITS` (accent colour, shortcut
label), kept so the two panels stay distinguishable on screen (§3.3).

Per-side generation (INV-9): `later()` schedules a delayed callback that runs
only if no render, mode switch, chart reset or close happened on THIS side in the
meantime; the other side never cancels it.
"""

import importlib

from PySide6.QtCore import QTimer

from managers.dasha.modes import mode_spec, next_mode

# The only place the two sides differ (SPEC-DSH-004 §3.3).
SIDE_TRAITS = {
    "left": {"accent": "orange", "label": "Left", "shortcut": "Shift+F7",
             "vimshottari_system": "vedanga"},      # legacy remote wire name (D-7)
    "right": {"accent": "cyan", "label": "Right", "shortcut": "F7",
              "vimshottari_system": "vimshottari"},
}


class DashaSide:
    """Dispatches one side's panel events to its current mode's renderer."""

    def __init__(self, manager, name):
        if name not in SIDE_TRAITS:
            raise ValueError(f"side must be 'left' or 'right', got {name!r}")
        self.manager = manager
        self.name = name
        self.traits = SIDE_TRAITS[name]
        self._renderers = {}
        self._gen = 0

    # -- state / widgets ---------------------------------------------------- #

    @property
    def state(self):
        return self.manager.dasha_state.side(self.name)

    @property
    def panel(self):
        return self.manager.panel(self.name)

    @property
    def mode(self):
        return self.state.mode

    def renderer(self, mode=None):
        """The renderer instance for `mode` (default: the current mode)."""
        key = mode or self.state.mode
        r = self._renderers.get(key)
        if r is None:
            module, cls = mode_spec(key).renderer.split(":")
            r = getattr(importlib.import_module(module), cls)(self.manager, self.name)
            self._renderers[key] = r
        return r

    # -- generation --------------------------------------------------------- #

    def invalidate(self):
        """Cancel this side's pending delayed callbacks and abort an in-flight
        Vimshottari render of this side (its own render token)."""
        self._gen += 1
        self.renderer("vimshottari").invalidate()

    def later(self, ms, fn):
        """Run `fn` after `ms` unless this side was invalidated meanwhile."""
        gen = self._gen

        def _fire(g=gen):
            if self._gen == g:
                fn()
        QTimer.singleShot(ms, _fire)

    # -- reshape / render --------------------------------------------------- #

    def configure(self, mode):
        """Reshape the panel for `mode` and re-list (the ONLY reshaper). Writes
        the side's mode and applies the mode-entry reset. Returns False when the
        panel is not built yet (state written, nothing drawn)."""
        self.invalidate()
        st = self.state
        st.reset_mode_entry(mode)      # raises on an unknown mode BEFORE the write
        st.mode = mode
        p = self.panel
        if p is None:
            return False
        spec = mode_spec(mode)
        r = self.renderer(mode)
        if hasattr(r, "before_shape"):
            r.before_shape()           # dynamic title resolved before set_shape
        p.set_shape(**shape_of(spec))
        r.enter(p)
        r.render()
        return True

    def update(self):
        """Re-list for the CURRENT mode (no reshape)."""
        self.renderer().render()

    # -- event verbs (mode-routed) ------------------------------------------ #

    def set_level(self, level):
        self.renderer().set_level(level)

    def on_drill(self, item):
        self.renderer().on_drill(item)

    def on_select(self, item):
        self.renderer().on_select(item)

    def nav_prev(self):
        self.renderer().nav_prev()

    def nav_next(self):
        self.renderer().nav_next()

    def on_title_clicked(self):
        self.renderer().on_title_clicked()

    def checked_level(self):
        return self.renderer().checked_level()

    def context_cycle_offset(self):
        return self.renderer().context_cycle_offset()

    def cycle_mode(self):
        return next_mode(self.state.mode)


def shape_of(spec):
    """`DashaPanelWidget.set_shape` kwargs for a ModeSpec (KEEP = the renderer
    writes that title field itself)."""
    from apps.panels.dasha_panel import KEEP
    return dict(
        levels=spec.levels, nav=spec.nav,
        title=spec.title_static if spec.title_static is not None else KEEP,
        title_tooltip=spec.title_tooltip if spec.title_tooltip is not None else KEEP,
        title_enabled=spec.title_enabled)
