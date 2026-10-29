# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The DIGNITY key: the dignity overlay on the chart planets, exclusive with the
Strength display (SPEC-DIG-001 §4.2, td-m6xyo).

On = ``chart.planet_glow_mode`` "dignity" AND the strength display off (no
Strength key lit, no Ember Aura). A Strength key or PLANET lit leaves "dignity"
(``StrengthSourceCycler.select`` / ``select_planet``). Every other writer (Apply,
Reset, remote ``set_setting``, the AI) is repaired by ``interlock``, subscribed
for the window's life by ``install_interlock`` when the window builds its menus
(one owner of the rule, whatever panels the window has). Same fast path as the Strength keys:
``persist_runtime_change``, the Settings page controls kept in step with signals
blocked, the Apply tail's three redraw calls.
"""
from __future__ import annotations

from core import planet_dignity as pd
from core import planet_strength_glow as psg
from core import settings_registry as registry
from core.retinue_strength import KEY_ON

MODE_KEY = psg.KEY_MODE


def is_on(get) -> bool:
    return pd.dignity_on(get)


class DignitySwitch:
    """Writes the DIGNITY key and keeps it exclusive with the strength display."""

    def __init__(self, gui):
        self._gui = gui

    def _cycler(self):
        from managers.retinue_strength_shortcut import StrengthSourceCycler
        return StrengthSourceCycler(self._gui)

    def select(self, on):
        """DIGNITY on: mode "dignity" and the strength display off. Off: mode
        "manual". A locked key leaves everything as it is."""
        from managers.settings_manager import get_settings
        s = get_settings()
        strength_on = bool(s.get(KEY_ON, registry.default(KEY_ON)))
        keys = (MODE_KEY,) + ((KEY_ON,) if on and strength_on else ())
        if any(s.is_locked(k) for k in keys):
            self._cycler().say("Planet glow is locked in Settings")
            return None
        cycler = self._cycler()
        cycler.write_mode(s, pd.DIGNITY if on else psg.MANUAL)
        if on and strength_on:
            cycler.write_source(s, None)     # the strength display off, its source kept
        s.flush()
        if on and strength_on:
            cycler.redraw_hosts()            # the Ember Auras come off: the full redraw
        else:
            # only the overlay changes: take it off / put it on the finished scenes
            # (td-m6xyo: the full redraw rebuilt every host, 0.8 to 1.8 s a click)
            from apps.widgets.dignity_overlay_refresh import refresh_overlays
            refresh_overlays()
        return bool(on)

    def interlock(self, s, key):
        """Repair a single-key writer that left both on: the strength display
        turned on while "dignity" -> mode Manual; the mode set to "dignity"
        while the strength display is on -> display off. Locked keys are left
        alone. Returns True when something was written."""
        if not (is_on(s.get) and bool(s.get(KEY_ON, registry.default(KEY_ON)))):
            return False
        cycler = self._cycler()
        if key.startswith(KEY_ON) and not s.is_locked(MODE_KEY):
            cycler.write_mode(s, psg.MANUAL)
        elif not key.startswith(KEY_ON) and not s.is_locked(KEY_ON):
            # the mode written, or an ancestor ("chart", "*") holding both: Dignity wins
            cycler.write_source(s, None)
        else:
            return False
        s.flush()
        return True


def leave_dignity(s, write_mode):
    """Strength side hook (``StrengthSourceCycler``): a Strength key lit while
    "dignity" -> mode Manual first. ``write_mode(s, mode)`` writes and keeps the
    Settings combo in step. Returns True when it wrote."""
    if s.get(MODE_KEY, psg.MANUAL) != pd.DIGNITY:
        return False
    write_mode(s, psg.MANUAL)
    return True


def install_interlock(gui, settings=None):
    """INV-2 for every single-key writer, owned here for the window's life:
    a write of the glow mode or of the strength display that leaves both on is
    repaired (``DignitySwitch.interlock``). Called once when the window builds
    its menus; dropped when ``gui`` is destroyed. Returns the callback."""
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    switch = DignitySwitch(gui)

    def _changed(key, _value):
        switch.interlock(settings, key)

    for key in (MODE_KEY, KEY_ON):
        settings.on_changed(key, _changed)

    def _drop(*_):
        for key in (MODE_KEY, KEY_ON):
            settings.remove_on_changed(key, _changed)
    destroyed = getattr(gui, "destroyed", None)
    if destroyed is not None:
        destroyed.connect(_drop)
    return _changed
