# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Publish the app's LIVE frame to the tools (AIC plan 2, Lorris 2026-10-01).

The tools must calculate in the frame on screen, or they cannot be used to
debug the app: zodiac mode, chart ayanamsa, house system, nakshatra
coordinates, outer planets, both dasha ayanamsas, the year length and the ZR
choices. The saved file can lag the screen (a locked setting is never written
back; another app instance may have saved last), so this manager:

- registers ``live_values`` as the in-process provider (tools the app runs);
- writes this instance's own ``live_frame.<pid>.json`` next to
  ``app_settings.json`` the moment the values change, for CLIs started from a
  terminal while the app is open. ``publish()`` is called from the app's real
  change points: the state store (zodiac mode, house system), the zodiac
  settings manager after it applies a frame (``ZodiacSettingsManager._apply``,
  ``notify_dasha``), the dasha setters (``DashaManager``: year length, side
  ayanamsa, right mode), the outer planets toggle and the settings keys the
  live values read. It writes only on change, so calling it often is cheap.
  A 1 s timer stays as a safety net (and rewrites the file if it went
  missing). The heartbeat (touching the file every ``HEARTBEAT_SECONDS``) runs
  on a small daemon thread (``live_state.Heartbeat``), not on the GUI thread,
  so a GUI thread blocked for minutes does not make the tools drop the frame;
  it is stopped at exit before the file is retired;
- records ``activated_at`` when one of this instance's windows becomes the
  active window and writes it at once, so a reader with two instances open
  takes the one the user is using;
- retires only its own file at exit, so another open instance stays visible.

Reads the GUI's own state, never writes it (Rule 4b). See
core/capabilities/live_state.py for the reader side.
"""
from __future__ import annotations

import functools
import logging
import os
import sys
import time
import weakref
from contextlib import contextmanager

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from core.capabilities import live_state
from core.capabilities.setting_defaults import setting_default


def _log():
    """The app's diagnostics logger (the rotating file), else this module's."""
    try:
        from core.diagnostics import get_logger
        return get_logger("live_frame")
    except Exception:
        return logging.getLogger(__name__)


# Settings keys whose change can change the live values (SPEC-SET-003 §4.6,
# "publishing needs a trigger, not only a key"): the union of the ``watch``
# prefixes the live registry entries declare, leaves and typed sections
# alike, never a list kept here. A live entry with no ``watch`` is a test
# failure (test_live_frame_registry, T-8 trigger half): add ``watch=`` to the
# entry, not a key here. Zodiac keys are applied by ZodiacSettingsManager
# (deferred), which publishes itself after applying; these cover the values
# read straight from the settings, and a zero-delay publish catches any
# deferred apply. The GUI signals connected in _connect_change_points (the
# state store, the outer planets and view toggle actions, the tropical rim
# button) are the change points of a LOCKED key, which writes no setting.
def _watched_settings():
    from core.settings_registry import entries
    return tuple(sorted({e.watch for e in entries(live=True) if e.watch}))


WATCHED_SETTINGS = _watched_settings()

# WHAT is published is the settings registry's declaration (SPEC-SET-003 §4.6,
# INV-6): every ``live=True`` entry, leaves and typed sections alike. There is
# no key list here. HOW each entry is read is its ``live_reader``:
#
# - a GUI attribute path (``state.aditya_mode``, ``wheel_view.show_element_pies``,
#   ``dasha_state.left.ayanamsa`` under ``dasha_manager``), read off the GUI's
#   own objects because a locked setting is never written back
#   (persist_runtime_change) and another instance may have saved last;
# - an action (``outer_planets_action``...): its ``isChecked()``, set before
#   the setting is written;
# - ``chart_stack``: the chart view on screen (VIEW_BY_STACK_INDEX);
# - ``qt_theme.<fn>``: the ui.qt_theme module state ChartGUI.__init__ and the
#   Settings Fonts page set (SPEC-FONT-001), one flat display.fonts.<area> key
#   per area (a live key is looked up whole);
# - a typed section's getter (``get_chart_display``...): the whole block as
#   the renderers read it (stored values merged over the defaults);
# - no reader, ``dasha.*``: ``DashaManager.shared_option`` (INV-16, W3g): this
#   session's pick of a locked ZR option, else the stored
#   value, never ``stored()`` directly;
# - no reader otherwise: the in-memory setting, ``stored(key)``.
#
# A GUI object that does not exist (a reduced host, a test) falls back to
# ``stored(key)`` and is logged once at DEBUG (``_fallback``); on a booted
# ChartGUI, Core or Pro, every declared reader must resolve (a test failure
# otherwise, W5 F4); a key never stored falls back to ``setting_default(key)``
# (the registry's factory value, never a copy that can drift), so an instance
# that never stored the key still publishes what it draws. Rule 4b: every
# reader READS the GUI, none writes it.
_MISSING = object()

# Readers whose GUI object was missing, logged once each (DEBUG): on a real
# booted ChartGUI every declared reader resolves (test_live_frame_registry,
# reader resolution, Core and Pro); the stored() fallback is for a reduced
# host, never a silent cover for a misspelled declaration.
_unresolved_logged = set()


def _fallback(entry, reader, stored):
    if reader not in _unresolved_logged:
        _unresolved_logged.add(reader)
        try:
            _log().debug("live reader %r of %s did not resolve on this host; "
                         "publishing the stored value", reader, entry.key)
        except Exception:
            pass
    return stored()


def _live_entries():
    from core.settings_registry import entries
    return entries(live=True)


def _attr_path(root, path):
    """getattr chain along a dotted path; _MISSING when any step is absent."""
    node = root
    for part in path.split("."):
        node = getattr(node, part, _MISSING)
        if node is _MISSING:
            return _MISSING
    return node


def _font_value(reader, key):
    """A ``qt_theme.<fn>`` reader: the scale factor, or one area's size."""
    from ui import qt_theme
    fn = getattr(qt_theme, reader[len("qt_theme."):])
    return fn(key.rsplit(".", 1)[1]) if key.startswith("display.fonts.") else fn()


def _normalise(entry, value):
    """The value as the renderers consume it: the cusp glow mode is a step of
    its 3-cycle (ChartGUI._cycle_cusp_glow), the wheel house display one of
    its two modes (SPEC-WHD-001), an empty sign language the default, and a
    bool-typed entry a bool (an action's checked state, a wheel flag)."""
    key = entry.key
    if key == "chart.cusp_glow_mode":
        return (int(value) % 3 if isinstance(value, int) and not isinstance(value, bool)
                else setting_default(key))
    if key == "chart.wheel_house_display":
        return value if value in ("sign_based", "standard_western") else setting_default(key)
    if key == "zodiac.sign_language":
        return value or setting_default(key)
    if entry.type is bool:
        return bool(value)
    return value


def read_live_entry(entry, gui, settings, shared=None):
    """One registry entry's live value (see the module comment above).
    ``shared(key)``: the runtime owner's read for the session-pick keys; None
    makes them read the stored value (a host with no DashaManager)."""
    from core.settings_registry.schema import KIND_SECTION
    key, reader = entry.key, entry.live_reader

    def stored():
        return settings.get(key, setting_default(key))

    if entry.kind == KIND_SECTION:
        return getattr(settings, reader)()
    if reader is None:
        if key.startswith("dasha.") and shared is not None:
            return _normalise(entry, shared(key))
        return _normalise(entry, stored())
    if reader.startswith("qt_theme."):
        return _font_value(reader, key)
    if reader == "chart_stack":
        stack = getattr(gui, reader, None)
        view = None
        if stack is not None and hasattr(stack, "currentIndex"):
            from state.chart_state import VIEW_BY_STACK_INDEX
            view = VIEW_BY_STACK_INDEX.get(stack.currentIndex())
        return view if view is not None else _fallback(entry, reader, stored)
    if reader.endswith("_action"):
        action = getattr(gui, reader, None)
        value = action.isChecked() if action is not None else _fallback(entry, reader, stored)
        return _normalise(entry, value)
    root = getattr(gui, "dasha_manager", None) if reader.startswith("dasha_state.") else gui
    value = _attr_path(root, reader)
    return _normalise(entry, _fallback(entry, reader, stored) if value is _MISSING else value)


def view_toggle_values(gui, settings):
    """The chart view toggles on screen, as settings dot-keys: the live
    ``chart.*`` entries read off a GUI object (the chart stack's current page,
    the F5 / F6 / F11 and outer-planets actions, the main wheel's own
    attributes for the pies, the cusp glow mode, the tropical rim and the
    house display mode), falling back to the setting only when that object
    does not exist."""
    return {e.key: read_live_entry(e, gui, settings)
            for e in _live_entries()
            if e.key.startswith("chart.") and e.live_reader}


def chart_font_values():
    """The font sizes the chart views paint with (SPEC-FONT-001), as settings
    dot-keys: the live entries whose reader is a ``qt_theme`` function
    (display.font_scale and one flat display.fonts.<area> key per area)."""
    return {e.key: _font_value(e.live_reader, e.key) for e in _live_entries()
            if e.live_reader and e.live_reader.startswith("qt_theme.")}


# Publication batch (SPEC-SET-003 §4.6, W5-fix2 P2). One Settings Apply writes
# several keys, and each write fires a change point (the watched-settings
# callback, its zero-delay follow-up, the poll timer, a focus change). Some
# live values are read from the store (display.sign_display), others off the
# GUI objects that adopt the store only in the Apply's tail (the wheel's house
# display and cusp glow), so a publication between the first write and the
# end of the tail is a logically mixed frame another process can read and
# keep (SettingsView.load copies it). Inside a batch every publication is
# deferred; leaving the outermost batch publishes once, after the tail, the
# completed frame. A reader therefore sees the previous complete frame or the
# new complete one, never a mix. Released in ``finally``: a failing Apply never
# leaves publishing suspended. Process-wide (GUI thread only): the Settings
# page that opens it does not hold the window; every manager in the process
# defers, and each publishes once when the batch closes.
#
# A batch that ends in an exception (W5-fix3 P2): the writes before the
# failure are in the store but the tail that makes the views adopt them never
# ran, so the store is not what is on screen. The batch's ``reconcile`` is that
# adoption tail (the Settings page's chart_display_changed, the remote
# command's window tail): it runs, still inside the batch, so the views adopt
# the partially written store, and the closing publication is then the frame
# on screen. The exception is re-raised.
#
# Adoption is a RESULT, not a call that returned (W5-fix4 P2): a tail adopts
# only when it completes. A tail reached through a Qt signal must report its
# slots' outcome (``emit_adoption``: Qt reports a slot's exception through
# sys.excepthook and returns from emit() normally) and raise AdoptionFailed,
# so a failing slot is a failing tail like any other.
#
# When there is no tail to run, or the tail fails, the views' state is
# unknown: every live value that changed since the last adopted frame is HELD
# at its adopted value, in the file and the in-process provider, by every
# publication path (the close, the queued follow-up, the poll, a focus
# change). A hold on key K is released only when K is adopted (W5-fix4 P2):
# a later tail that OWNS K completes (``owns``: the keys the tail makes the
# views re-read), or K's live value moves away from the unadopted value
# (something on screen changed it since). A completed tail that does not own K
# (an unrelated remote command) leaves the hold in place.
#
# Each manager keeps the last adopted frame of the open batch: its
# publication when the outermost batch opened, updated for the owned keys each
# time a tail completes inside the batch; a failed batch holds what differs
# from it.
_batch_depth = 0
_batch_unadopted = False    # a failure left store writes no tail adopted
_batch_failure = None       # "<Type>: <message>" of that failure (diagnostics)
_managers = weakref.WeakSet()
_RECONCILED = "_live_frame_reconciled"


class AdoptionFailed(RuntimeError):
    """An adoption tail did not complete: the views did not re-read the store."""


def emit_adoption(signal, what="adoption tail"):
    """Emit ``signal`` (an adoption tail reached through Qt) and return only
    when every slot it reached completed; raise AdoptionFailed otherwise.

    PySide reports an exception raised in a slot through ``sys.excepthook``
    and returns from ``emit()`` normally, so the return of ``emit()`` is no
    proof that the views adopted anything. The hook is wrapped for the
    duration of the (synchronous, same-thread) emit, every report is still
    forwarded to the hook that was installed (printed / logged as before),
    and any exception reported during the emit fails the adoption."""
    errors = []
    previous = sys.excepthook

    def hook(typ, exc, tb):
        errors.append(exc)
        try:
            previous(typ, exc, tb)
        except Exception:
            pass
    sys.excepthook = hook
    try:
        signal.emit()
    finally:
        sys.excepthook = previous
    if errors:
        first = errors[0]
        raise AdoptionFailed(f"{what}: {type(first).__name__}: {first}") from first


def _owner(owns):
    """``owns`` as a predicate on a live key: None = the whole frame (a tail
    that declares no ownership re-reads everything), a callable as is, else a
    collection of keys."""
    if owns is None:
        return lambda _key: True
    if callable(owns):
        return owns
    keys = frozenset(owns)
    return keys.__contains__


def _describe(exc):
    return f"{type(exc).__name__}: {exc}"


def batch_open():
    """True while a publication batch is open (tests, diagnostics)."""
    return _batch_depth > 0


def _tail_completed(owns):
    """An adoption tail completed inside the batch: the owned keys are
    adopted (each manager releases their holds and takes them into the
    batch's adopted frame)."""
    pred = _owner(owns)
    for manager in list(_managers):
        manager._adopted(pred)


@contextmanager
def publication_batch(reconcile=None, owns=None):
    """Defer every live-frame publication until the block (outermost) ends,
    then publish each manager's completed frame once.

    ``reconcile``: the batch's adoption tail (a no-argument callable), which
    the block ends with; run again inside the batch when the block raises, so
    the published frame is the one the views adopted. ``owns``: the live keys
    that tail makes the views re-read (None: all of them); only those are
    released from a hold when it completes (see the comment above)."""
    global _batch_depth, _batch_unadopted, _batch_failure
    if _batch_depth == 0:
        _batch_unadopted, _batch_failure = False, None
        for manager in list(_managers):
            manager._open_batch()
    _batch_depth += 1
    try:
        yield
    except BaseException as exc:
        if not getattr(exc, _RECONCILED, False):
            failure = exc
            if reconcile is not None and isinstance(exc, Exception):
                try:
                    reconcile()
                except Exception as rexc:
                    failure = rexc
                    try:
                        _log().warning("live frame: the adoption tail failed after %r; "
                                       "holding the last adopted values: %r", exc, rexc)
                    except Exception:
                        pass
                else:
                    failure = None
                    _tail_completed(owns)
                    try:
                        setattr(exc, _RECONCILED, True)     # an outer batch: done
                    except Exception:
                        pass
            if failure is not None:
                _batch_unadopted, _batch_failure = True, _describe(failure)
        raise
    else:
        if reconcile is not None:
            _tail_completed(owns)       # the block ended with its tail
    finally:
        _batch_depth -= 1
        if _batch_depth == 0:
            unadopted, failure = _batch_unadopted, _batch_failure
            _batch_unadopted, _batch_failure = False, None
            for manager in list(_managers):
                manager._flush_batch(unadopted=unadopted, failure=failure)


def batched_publication(fn=None, *, reconcile=None, owns=None):
    """Decorator form of publication_batch, for a settings writer whose
    writes and adoption tail must publish as one frame (Chart Display Apply
    and Reset). ``reconcile(self)``: the method's adoption tail, run when the
    method raises; ``owns``: the keys it adopts (publication_batch)."""
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tail = None
            if reconcile is not None:
                tail = functools.partial(reconcile, *args[:1])
            with publication_batch(reconcile=tail, owns=owns):
                return func(*args, **kwargs)
        return wrapper
    return decorate(fn) if fn is not None else decorate


class LiveFrameManager(QObject):
    POLL_MS = 1000
    MAX_LOGGED = 20         # distinct errors logged per run (the timer polls 1/s)

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self._last = None
        self._changed_at = None
        self._activated_at = None
        self._folder = None
        self._heartbeat = None      # live_state.Heartbeat (daemon thread)
        self._hooks = []            # (undo callable) for stop()
        # Diagnostics: a failure to read the live values or write the file
        # must never raise into Qt, but must not vanish either. last_error is
        # "<stage>: <Type>: <message>" (None while publishing works); each
        # distinct error is logged once; the file carries it as "error".
        self.last_error = None
        self.error_count = 0
        self._logged_errors = set()
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self.publish)
        # publication_batch: a publication / activation asked for while a
        # batch is open, made once when it closes (_flush_batch).
        self._batch_pending = False
        self._activation_pending = False
        self._batch_snapshot = None     # the frame on screen when a batch opened
        # Live values a failed batch wrote but no tail adopted: key ->
        # (adopted value, unadopted value); see publication_batch.
        self._held = {}
        self._adoption_error = None     # why the current holds exist
        self._stopped = False
        _managers.add(self)

    def start(self):
        from managers.settings_manager import get_settings
        self._stopped = False
        self._folder = os.path.dirname(getattr(get_settings(), "_config_path", "") or "") or None
        live_state.set_live_settings_provider(self.published_values)
        if self._folder:
            live_state.retire_stale(self._folder)     # files of crashed instances
        self._connect_change_points()
        self.publish()
        self._timer.start()
        if self._folder:
            self._heartbeat = hb = live_state.Heartbeat(self._folder)
            hb.start()
            # a manager torn down without stop() (tests) must not leave it beating
            self.destroyed.connect(lambda *_a, hb=hb: hb.stop(timeout=0))
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def _connect_change_points(self):
        """Publish at the app's real change points, not only on the timer."""
        from managers.settings_manager import get_settings
        state = getattr(self.gui, "state", None)
        if state is not None and hasattr(state, "connect"):
            def on_state(reason):
                if reason in ("aditya_mode", "house_system", "current_varga",
                              "human_design_mode", "chart_view_style"):
                    self.publish()
            # batchable: delivered once after a batch, when the whole frame is set
            state.connect(on_state, batchable=True)
            if hasattr(state, "disconnect"):
                self._hooks.append(lambda: state.disconnect(on_state))
        settings = get_settings()
        ref = weakref.ref(self)

        def on_setting(_key, _value, ref=ref):
            obj = ref()
            if obj is None:
                return
            obj.publish()
            QTimer.singleShot(0, obj, lambda: obj.publish())     # after a deferred apply
        for key in WATCHED_SETTINGS:
            settings.on_changed(key, on_setting)
            self._hooks.append(lambda k=key: settings.remove_on_changed(k, on_setting))
            # a GUI torn down without stop() (tests) must not leave callbacks
            self.destroyed.connect(
                lambda *_a, k=key, s=settings, cb=on_setting: s.remove_on_changed(k, cb))
        action = getattr(self.gui, "outer_planets_action", None)
        if action is not None and hasattr(action, "toggled"):
            action.toggled.connect(self._on_outer_toggled)
            self._hooks.append(lambda: action.toggled.disconnect(self._on_outer_toggled))
        # The view toggle actions (F5, F6, Shift+F5, F11): a toggle whose
        # setting is locked writes no setting, so its action is the change
        # point. The handler sets the wheel after the action toggles: publish
        # now and once more after it ran. The "+ Tropical" button writes its
        # setting (chart.show_tropical_rim, watched above) after setting the
        # wheel; its click is a change point too.
        for attr in ("retinue_rings_action", "trimsamsha_degrees_action",
                     "pie_charts_action"):
            act = getattr(self.gui, attr, None)
            if act is not None and hasattr(act, "toggled"):
                act.toggled.connect(self._on_view_toggled)
                self._hooks.append(
                    lambda act=act: act.toggled.disconnect(self._on_view_toggled))
        # F11 cycles (a plain action): its trigger is the change point.
        act = getattr(self.gui, "planet_names_action", None)
        if act is not None and hasattr(act, "triggered"):
            act.triggered.connect(self._on_view_toggled)
            self._hooks.append(lambda: act.triggered.disconnect(self._on_view_toggled))
        dual = getattr(self.gui, "dual_rim_btn", None)
        if dual is not None and hasattr(dual, "clicked"):
            dual.clicked.connect(self._on_view_toggled)
            self._hooks.append(lambda: dual.clicked.disconnect(self._on_view_toggled))
        app = QApplication.instance()
        if app is not None:
            for sig, slot in ((app.applicationStateChanged, self._on_app_state),
                              (app.focusWindowChanged, self._on_focus_window)):
                sig.connect(slot)
                self._hooks.append(lambda sig=sig, slot=slot: sig.disconnect(slot))
            if app.applicationState() == Qt.ApplicationActive and self._owns_focus():
                self.mark_activated()

    def _on_outer_toggled(self, _checked):
        self.publish()

    def _on_view_toggled(self, _checked):
        self.publish()
        QTimer.singleShot(0, self, lambda: self.publish())

    def _owns_focus(self):
        """True when a window of this process has the focus now."""
        app = QApplication.instance()
        return app is not None and app.focusWindow() is not None

    def _on_app_state(self, state):
        if state == Qt.ApplicationActive:
            self.mark_activated()

    def _on_focus_window(self, window):
        # Any window of this process (main window or one of its dialogs) means
        # the user is using this instance.
        if window is not None:
            self.mark_activated()

    def mark_activated(self, when=None):
        """One of this instance's windows became active: record it and write
        it at once, so a terminal tool follows the window the user is using."""
        self._activated_at = time.time() if when is None else when
        if self._stopped or not self._folder:
            return
        if _batch_depth:
            self._activation_pending = True     # written when the batch closes
            return
        values = self._read_values()
        if values is None:
            return
        now = time.time()
        if values != self._last:
            self._changed_at = now
        if self._write(values, self._changed_at):
            self._last = values

    def diagnostics(self):
        """Debug accessor: whether publishing works, and why not."""
        return {"folder": self._folder, "last_error": self.last_error,
                "error_count": self.error_count,
                "published": self._last is not None,
                "held": sorted(self._held),
                "adoption_error": self._adoption_error}

    def _failed(self, stage, exc):
        """Record a failure: status attribute, one log record per distinct
        error, never raised (this runs in Qt slots and timers)."""
        error = f"{stage}: {type(exc).__name__}: {exc}"
        self.last_error = error
        self.error_count += 1
        if error not in self._logged_errors and len(self._logged_errors) < self.MAX_LOGGED:
            self._logged_errors.add(error)
            try:
                _log().warning("live frame %s failed (the tools may read a stale "
                               "frame): %s", stage, error, exc_info=exc)
            except Exception:
                pass

    def _recovered(self):
        if self.last_error is not None:
            try:
                _log().info("live frame published again after: %s", self.last_error)
            except Exception:
                pass
        self.last_error = None

    def published_values(self):
        """What this instance publishes (the file and the in-process provider):
        ``live_values()`` with any value a failed batch left unadopted held at
        its last adopted value (publication_batch, W5-fix3 P2)."""
        return self._apply_hold(self.live_values())

    def _apply_hold(self, values):
        """Replace each held key's unadopted value by its adopted one; a held
        value that moved since (something on screen changed it) is released."""
        if not self._held:
            return values
        values = dict(values)
        for key, (adopted, unadopted) in list(self._held.items()):
            if key in values and values[key] == unadopted:
                values[key] = adopted
            else:
                del self._held[key]
        if not self._held:
            self._adoption_error = None
        return values

    def _open_batch(self):
        """The outermost publication batch opens: remember the frame on screen
        (with any hold), the last adopted frame if the batch fails unadopted."""
        self._batch_snapshot = None
        if not self._folder:
            return
        try:
            self._batch_snapshot = self.published_values()
        except Exception:
            pass        # no snapshot: a failed batch then holds nothing new

    def _adopted(self, owns):
        """A tail owning the keys ``owns(key)`` completed inside the open
        batch: release their holds and take their values (now on screen)
        into the batch's adopted frame."""
        if self._stopped:
            return
        for key in [k for k in self._held if owns(k)]:
            del self._held[key]
        if not self._held:
            self._adoption_error = None
        if self._batch_snapshot is None:
            return
        try:
            now = self.live_values()
        except Exception:
            return
        for key, value in now.items():
            if owns(key):
                self._batch_snapshot[key] = value

    def _hold_unadopted(self, failure=None):
        """A batch failed and no tail adopted its writes: hold every live
        value that differs from the batch's adopted frame at that frame's
        value (a key already held keeps its adopted value)."""
        snapshot, self._batch_snapshot = self._batch_snapshot, None
        if snapshot is None:
            return
        try:
            now = self.live_values()
        except Exception:
            return
        held = False
        for key, value in now.items():
            if key in snapshot and snapshot[key] != value:
                adopted = self._held[key][0] if key in self._held else snapshot[key]
                self._held[key] = (adopted, value)
                held = True
        if held:
            self._adoption_error = failure or self._adoption_error
            try:
                _log().warning("live frame: holding %s at the adopted frame: %s",
                               sorted(self._held), self._adoption_error)
            except Exception:
                pass

    def _read_values(self):
        """published_values(), or None after recording why it failed. The file
        is rewritten with the last good values and the error, so the problem is
        findable there too."""
        try:
            return self.published_values()
        except Exception as exc:
            self._failed("live_values", exc)
            if self._last is not None:
                try:
                    live_state.write_live_or_raise(
                        self._folder, self._last, changed_at=self._changed_at,
                        activated_at=self._activated_at, error=self.last_error)
                except Exception:
                    pass
            return None

    def _write(self, values, changed_at):
        """write the live file; False after recording why it failed."""
        try:
            live_state.write_live_or_raise(self._folder, values, changed_at=changed_at,
                                           activated_at=self._activated_at)
        except Exception as exc:
            self._failed("write_live", exc)
            return False
        self._recovered()
        return True

    def stop(self):
        # Retired: every surviving queued / poll / focus callback is inert from
        # here (W5-fix3 P3: a zero-delay follow-up queued before stop() used
        # to recreate the retired file), and the folder is cleared below.
        self._stopped = True
        self._batch_pending = self._activation_pending = False
        self._timer.stop()
        _managers.discard(self)     # a batch closing later must not rewrite the file
        if self._heartbeat is not None:
            self._heartbeat.stop()          # before the file is retired
            self._heartbeat = None
        for undo in self._hooks:
            try:
                undo()
            except Exception:
                pass
        self._hooks = []
        live_state.set_live_settings_provider(None)
        if self._folder:
            live_state.clear_live(self._folder)
        self._folder = None         # nothing left to publish into

    def live_values(self):
        """The frame on screen, as settings dot-keys (read-only on the GUI):
        every live registry entry through its declared reader
        (read_live_entry), plus the two view values that are not settings."""
        from managers.settings_manager import get_settings
        g = self.gui
        s = get_settings()
        dm = getattr(g, "dasha_manager", None)

        def shared(key):
            """A ZR option as the panels use it (SPEC-SET-003
            INV-16): this session's pick of a locked key, else the stored
            value, read through its runtime owner (DashaManager.shared_option).
            The ZR panel re-reads these on every update and dasha_state.zr only
            refreshes while a side is in ZR mode, so this never reads the state."""
            if dm is not None and hasattr(dm, "shared_option"):
                return dm.shared_option(key, setting_default(key))
            return s.get(key, setting_default(key))

        values = {e.key: read_live_entry(e, g, s, shared) for e in _live_entries()}
        # View values (not settings): the varga and the Human Design mode on
        # screen, so a terminal --tool run with no flag shows the same chart.
        st = getattr(g, "state", None)
        values["view.varga"] = int(getattr(st, "current_varga", 1) or 1)
        values["view.human_design"] = bool(getattr(g, "is_human_design", False))
        return values

    def publish(self):
        """At every change point and every POLL_MS: rewrite the file when the
        values changed, or (keeping its change time) when it went missing.
        The heartbeat touch is the daemon thread's job (``Heartbeat``)."""
        if self._stopped or not self._folder:
            return
        if _batch_depth:
            self._batch_pending = True          # published when the batch closes
            return
        values = self._read_values()
        if values is None:
            return
        now = time.time()
        if values != self._last or self.last_error is not None:
            # (also after a failure: the file then holds the error, rewrite it)
            if self._write(values, now if values != self._last else self._changed_at):
                if values != self._last:
                    self._last, self._changed_at = values, now
            return
        if not os.path.exists(os.path.join(self._folder, live_state.live_filename())):
            self._write(values, self._changed_at)

    def _flush_batch(self, unadopted=False, failure=None):
        """The outermost publication batch closed: one complete publication
        (with the activation time when one was deferred). ``unadopted``: a
        failure no tail adopted (hold what differs from the adopted frame;
        ``failure`` says why). Holds are released per key by the tails that
        own them (_adopted), never here. Never raises: it runs in the batch's
        ``finally``."""
        if self._stopped:
            return
        activation = self._activation_pending
        self._batch_pending = self._activation_pending = False
        try:
            if unadopted:
                self._hold_unadopted(failure)
            self._batch_snapshot = None
            if activation:
                self.mark_activated(self._activated_at)
            else:
                self.publish()
        except Exception as exc:
            self._failed("publish", exc)
