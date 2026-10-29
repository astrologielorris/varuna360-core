# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""F10: cycle the retinue strength source (SPEC-RST-001 D-18, td-ry783).

One press writes the next value of ``chart.retinue_strength_source`` in the
registry's order (duc -> digbala -> uccha -> chesta -> duc) through the settings
manager, exactly the value the Settings combo would store, then redraws the
chart hosts the Settings Apply tail redraws for these keys (SPEC-RST-001 §4.4),
each view once, the views on screen now and the hidden ones when shown
(``redraw_strength_hosts``). No parallel delivery, no loading overlay.

Rule 4b: the window gets no new attribute. The QAction is a child of the window
(found by its shortcut), and the cycler lives in the action's slot closure.
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
                               QPlainTextEdit, QTextEdit)

from core import planet_strength_glow as psg
from core import settings_registry as registry
from core.retinue_strength import KEY_ON, KEY_SOURCE, SOURCES

SHORTCUT = "F10"
ACTION_TEXT = "Cycle Retinue Strength &Source"


def next_source(current: str) -> str:
    """The value after ``current`` in the registry order; an unknown value
    restarts at the first one."""
    order = tuple(registry.choice_values(KEY_SOURCE)) or SOURCES
    if current not in order:
        return order[0]
    return order[(order.index(current) + 1) % len(order)]


def source_label(value: str) -> str:
    """The Settings combo's own label for ``value`` (e.g. "Digbala")."""
    for choice in registry.get(KEY_SOURCE).choices or ():
        if getattr(choice, "value", None) == value:
            return choice.label or str(value)
    return str(value)


def typing_in_text_field() -> bool:
    """True while the keyboard focus is in a widget the user types into."""
    w = QApplication.focusWidget()
    if w is None:
        return False
    if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return not getattr(w, "isReadOnly", lambda: False)()
    return isinstance(w, QComboBox) and w.isEditable()


class StrengthSourceCycler:
    """Writes the next source, redraws the hosts, keeps the Settings combo in
    step and says what happened in the status bar."""

    def __init__(self, gui):
        self._gui = gui

    def cycle(self):
        if typing_in_text_field():
            return None
        from managers.settings_manager import get_settings
        s = get_settings()
        if s.is_locked(KEY_SOURCE):
            self.say("Strength source is locked in Settings")
            return None
        default = registry.default(KEY_SOURCE)
        value = next_source(s.get(KEY_SOURCE, default))
        s.persist_runtime_change(KEY_SOURCE, value)
        self._sync_settings_combo(value)
        enabled = bool(s.get(KEY_ON, registry.default(KEY_ON)))
        # Display off: INV-1, no view reads the source, so nothing to redraw.
        if enabled:
            self.redraw_hosts()
        suffix = "" if enabled else " (display off)"
        self.say(f"Strength source: {source_label(value)}{suffix} ({SHORTCUT})")
        return value

    def select(self, source):
        """The Strength panel keys (SPEC-RST-001 D-20): ``source`` turns the
        display on with that source; None turns it off, and the PLANET key with it
        (D-21). Same path as F10: write through ``persist_runtime_change``, keep the
        Settings page in step, redraw with the Apply tail's calls. A locked key
        leaves everything as it is."""
        from managers.settings_manager import get_settings
        s = get_settings()
        keys = (KEY_ON, KEY_SOURCE) if source is not None else (KEY_ON,)
        planet_off = source is None and s.get(psg.KEY_MODE, psg.MANUAL) == psg.STRENGTH
        if planet_off:
            keys += (psg.KEY_MODE,)           # off takes PLANET with it: both or neither
        from managers.dignity_overlay import leave_dignity   # td-m6xyo: DIGNITY is exclusive
        dignity_off = source is not None and s.get(psg.KEY_MODE, psg.MANUAL) == "dignity"
        if dignity_off:
            keys += (psg.KEY_MODE,)
        if any(s.is_locked(k) for k in keys):
            self.say("Strength source is locked in Settings")
            return None
        if dignity_off:
            leave_dignity(s, self.write_mode)
        self.write_source(s, source)
        if planet_off:                        # read before the write: the panel's interlock
            self.write_mode(s, psg.MANUAL)   # may have stored it already; the combo follows
        s.flush()
        self.redraw_hosts()
        return source

    def select_planet(self, on):
        """The PLANET key (D-21). On: glow mode Strength, and when no strength key
        is lit, DUC Bala lights too (PLANET never works alone). Off: glow mode
        Manual; the strength key stays as it is. Same writes as ``select``; when
        no strength key changes only the auras change, so only the planet
        post-passes run again (R2 review: the full redraw cost 0.85 to 2.2 s)."""
        from managers.settings_manager import get_settings
        s = get_settings()
        need_source = bool(on) and not bool(s.get(KEY_ON, registry.default(KEY_ON)))
        keys = (psg.KEY_MODE,) + ((KEY_ON, KEY_SOURCE) if need_source else ())
        if any(s.is_locked(k) for k in keys):
            self.say("Planet glow is locked in Settings")
            return None
        if need_source:
            self.write_source(s, "duc")
        self.write_mode(s, psg.STRENGTH if on else psg.MANUAL)
        s.flush()
        if need_source:
            self.redraw_hosts()              # the retinue cells light too
        else:
            from apps.widgets.planet_decoration_refresh import refresh_planet_passes
            refresh_planet_passes()
        return bool(on)

    def write_source(self, s, source):
        """Write the on/off and source keys (no disk write, no redraw)."""
        if source is not None:
            s.persist_runtime_change(KEY_SOURCE, source, save=False)
            self._sync_settings_combo(source)
        s.persist_runtime_change(KEY_ON, source is not None, save=False)
        self._sync_settings_check(source is not None)

    def interlock(self, s, key):
        """D-21 for a single-key writer (Apply, Reset, remote ``set_setting``, the
        AI), called from the Strength panel's settings subscription: the display
        turned off sets Manual; Strength with the display off lights DUC Bala.
        Settings controls follow; the writer's own tail redraws. Locked keys
        are left alone."""
        if s.get(psg.KEY_MODE, psg.MANUAL) != psg.STRENGTH or bool(s.get(KEY_ON, registry.default(KEY_ON))):
            return
        if key.startswith(KEY_ON):
            self.write_mode(s, psg.MANUAL)
        elif key.startswith(psg.KEY_MODE) and not (s.is_locked(KEY_ON) or s.is_locked(KEY_SOURCE)):
            self.write_source(s, "duc")
        s.flush()

    def write_mode(self, s, mode):
        s.persist_runtime_change(psg.KEY_MODE, mode, save=False)
        page = getattr(getattr(self._gui, "settings_tab", None), "chart_display_tab", None)
        combo = getattr(page, "planet_glow_combo", None)
        idx = combo.findData(mode) if combo is not None else -1
        if idx >= 0:
            with QSignalBlocker(combo):
                combo.setCurrentIndex(idx)

    def _sync_settings_check(self, on):
        page = getattr(getattr(self._gui, "settings_tab", None), "chart_display_tab", None)
        box = getattr(page, "retinue_strength_cb", None)
        if box is not None:
            with QSignalBlocker(box):
                box.setChecked(bool(on))

    def redraw_hosts(self):
        """The Settings Apply tail's redraw for the strength keys (§4.4), each
        view once, the hidden ones when shown (planet_decoration_refresh.py)."""
        redraw_strength_hosts(getattr(self._gui, "wheel_view", None))

    def _sync_settings_combo(self, value):
        page = getattr(getattr(self._gui, "settings_tab", None), "chart_display_tab", None)
        combo = getattr(page, "retinue_strength_source_combo", None)
        if combo is None:
            return
        idx = combo.findData(value)
        if idx >= 0:
            with QSignalBlocker(combo):
                combo.setCurrentIndex(idx)

    def say(self, text):
        bar = getattr(self._gui, "statusBar", None) if self._gui is not None else None
        if callable(bar):
            bar().showMessage(text, 3000)


def _refresh_vector(view):
    """A vector view's own refresh (``sync_all_south_indian_hosts``): its finish,
    then its draw. False: a disposed owner, left alone."""
    from apps.widgets import south_indian_vector_view as siv
    if not siv._accepts_appearance_refresh(view):
        return False
    from apps.widgets.additional_bodies import refresh_vector
    from managers.settings_manager import get_settings
    s = get_settings()
    refresh_vector(view, s.get('display.south_indian_vector_finish', registry.default('display.south_indian_vector_finish')),
                   s.get('display.sign_display', registry.default('display.sign_display')))
    return True


def _draw_host_child(view):
    from apps.widgets import south_indian_vector_view as siv
    if not (isinstance(view, siv.SouthIndianVectorView) and _refresh_vector(view)):
        view.draw_full_chart()


def redraw_strength_hosts(wheel=None):
    """The Settings Apply tail's redraw for the strength keys (SPEC-RST-001 §4.4:
    ``sync_all_south_indian_hosts`` + ``sync_all_chart_hosts`` + ``apply_retinue``),
    each view drawn once (R2 review: vector views were drawn twice), now when on
    screen, else at its next show (``when_shown``). Returns the views drawn now."""
    import shiboken6
    from apps.widgets import chart_host_registry as hosts
    from apps.widgets import south_indian_vector_view as siv
    from apps.widgets.planet_decoration_refresh import when_shown
    from apps.widgets.retinue_display import apply_retinue
    done, in_host = 0, set()
    for host in list(siv._LIVE_HOSTS):
        try:
            host.sync_style()
        except RuntimeError:                  # a deleted host: never blocks the others
            siv._LIVE_HOSTS.discard(host)
            continue
        for child in (host.classic_view, host.vector_view):
            in_host.add(child)
            done += when_shown(child, "strength_redraw", _draw_host_child)
    for view in list(siv._LIVE_VECTOR_VIEWS):
        if view in in_host:
            continue                          # its host drew it: never twice
        if not shiboken6.isValid(view):
            siv._LIVE_VECTOR_VIEWS.discard(view)
            continue
        done += when_shown(view, "strength_redraw", _refresh_vector)
    for view in list(hosts._LIVE_CHART_HOSTS):
        if not shiboken6.isValid(view):
            hosts._LIVE_CHART_HOSTS.discard(view)
            continue
        done += when_shown(view, "strength_redraw", lambda v: v.reload_display_settings())
    if wheel is not None:
        apply_retinue(wheel)                  # the main wheel: drawn now or when shown
    return done


def install_strength_source_action(gui, menu) -> QAction:
    """Add the F10 action to ``menu`` (the View menu), parented to the window."""
    cycler = StrengthSourceCycler(gui)
    action = QAction(ACTION_TEXT, gui)
    action.setShortcut(QKeySequence(SHORTCUT))
    action.setStatusTip(
        "Cycle the retinue strength source: "
        + " / ".join(source_label(v) for v in registry.choice_values(KEY_SOURCE))
        + f" ({SHORTCUT})")
    action.triggered.connect(lambda _=False: cycler.cycle())
    menu.addAction(action)
    return action
