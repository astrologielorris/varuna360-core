# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The state owner shared by the center drawings (SPEC-VAC-001 §4.0, §4.5).

``CenterDrawingController``: on/off and min_virupas (two settings keys of the drawing), the
lit keys (runtime only), ONE update path (``apply_state``, equal writes ignored), the push to
the main South Indian host, the status that names the toggle tooltip (``toggle_tooltip``),
the focus hold (owner = the drawing kind), the tour and teardown. ``CenterTour``: the tour's
sequence, index, timer and key lamp. ``CenterPanelWidgets``: a drawing's toggle, key headers,
rail, tour key and cell marks (its ``CenterParts``). ``CenterModeSync``: the ONE owner of the
panel mode (``set_center_mode`` at startup and on every ``aspects_stack.currentChanged``).
The registry (``center_drawing_registry``, re-exported): controllers keyed by ``id(gui)``.
Settings are injected (no manager import). A subclass gives ``KIND``, keys, table and hooks:
``_parts``, ``_as_lit``, ``_make_state``, ``_push_state``, ``_lit_after_press``, ``_header_lit``,
``_counts``, ``_ticks``, ``_model``, ``_tour_steps``, ``_show_step``, ``_clear_focus``, ``_ring``.
"""
from __future__ import annotations

import weakref
from typing import Callable, NamedTuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QStackedLayout

from apps.widgets.panel_controllers.center_drawing_notice import toggle_tooltip, with_notice
from apps.widgets.panel_controllers.center_drawing_registry import (  # noqa: F401
    _REGISTRY, _SYNC, PanelLinks, _entry, center_controller, center_controllers,
    create_center_controller, register_center_controller, release_center_controllers,
    unregister)
from core.i18n import t
from state import PanelControllerBase

KEY_TOUR = "chart.aspect_tour_seconds"       # seconds per step of a tour (SPEC-TJK-003 D-9)
RAIL_DELAY_MS = 30                            # debounce: one redraw 30 ms after the drag settles


# ------------------------------------------------------------ mode sync entry (§4.5)
def ensure_mode_sync(gui):
    """The GUI's ``CenterModeSync`` (created and synced once), or None without a panel."""
    stack = getattr(gui, "aspects_stack", None)
    if stack is None:
        return center_controller(gui, _SYNC)
    entry = _entry(gui)
    if entry.get(_SYNC) is None:
        entry[_SYNC] = CenterModeSync(gui, stack, main_host)
        entry[_SYNC].sync()
    return entry[_SYNC]


def main_host(gui):
    """The main South Indian host of the GUI (where the drawings are pushed)."""
    return getattr(gui, "chart_view", None)


def tour_step_ms(settings) -> int:
    """The Settings tab's seconds per step, read when a tour starts; a value the registry
    would refuse (garbage in a settings file, NaN, out of 0.5-10) -> default."""
    from core import settings_registry as registry
    seconds = settings.get(KEY_TOUR, None)
    if not registry.valid(KEY_TOUR, seconds):
        seconds = registry.default(KEY_TOUR)
    return int(round(1000 * float(seconds)))


def _persist(settings, on, min_virupas):
    """A user action writes the changed keys; ``(key, value, changed)`` each. The rail
    value is written without saving: one disk write when the drag settles."""
    write = getattr(settings, "persist_runtime_change", settings.set)
    if on[2]:
        write(on[0], on[1])
    if min_virupas[2]:
        write(min_virupas[0], min_virupas[1], save=False)


# ------------------------------------------------------------ mode (§3.1, §4.5)
class CenterModeSync:
    """Sets the main host's mode from ``gui._aspects_mode`` at creation and on every
    ``aspects_stack.currentChanged``; holds the stack, the host getter and a weak GUI ref."""

    def __init__(self, gui, stack, host_of: Callable):
        self._gui_ref = weakref.ref(gui)
        self._stack = stack
        self._host_of = host_of
        self._alive = True
        stack.currentChanged.connect(self.sync)

    def mode(self):
        gui = self._gui_ref()
        return None if gui is None else getattr(gui, "_aspects_mode", "vedic")

    def sync(self, *_):
        """One ``set_center_mode`` (the binding ignores an equal mode)."""
        from apps.widgets.south_indian_center_pass import set_center_mode
        gui = self._gui_ref()
        if not self._alive or gui is None:
            return False
        return set_center_mode(self._host_of(gui), self.mode())

    def teardown(self, *_):
        if not self._alive:
            return
        self._alive = False
        try:
            self._stack.currentChanged.disconnect(self.sync)
        except (RuntimeError, TypeError):
            pass


# ------------------------------------------------------------ the drawing's parts
class CenterParts(NamedTuple):
    """The widget factories of one drawing (its own body sets, labels and texts)."""
    toggle: Callable              # () -> CenterToggle
    install_headers: Callable     # (table) -> (horizontal, vertical) PlanetKeyHeader
    rail_class: type              # the VirupaRail class info_panels put under the table
    tour_key: Callable            # (parent) -> TourKey
    cell_marks: Callable          # (table) -> CellMarks


class CenterPanelWidgets:
    """One drawing's toggle (after the swap), key headers, rail, tour key and cell marks."""

    def __init__(self):
        self.toggle = self.rail = self.tour_key = self.cells = None
        self.headers = ()

    def build(self, header, swap, table, parts: CenterParts, actions):
        """``actions`` = (toggle, press(body), rail moved(value), tour) callables."""
        toggle, press, rail_moved, tour = actions
        self.toggle = parts.toggle()
        layout = header.layout()
        layout.insertWidget(layout.indexOf(swap) + 1, self.toggle)
        self.toggle.clicked.connect(toggle)
        self.headers = parts.install_headers(table)
        for h in self.headers:
            h.on_key = press
        page = table.parentWidget()
        self.rail = page.findChild(parts.rail_class) if page is not None else None
        if self.rail is not None:
            self.rail.valueChanged.connect(rail_moved)
            self.tour_key = place_tour_key(self.rail, parts.tour_key)
            self.tour_key.clicked.connect(tour)
            self.cells = parts.cell_marks(table)

    def sync(self, on, header_lit, value, visible, counts):
        """``counts`` is a callable (shown, total), called only when there is a rail."""
        if self.toggle is not None:
            self.toggle.set_on(on)
            self.toggle.setVisible(visible)
        for h, lit in zip(self.headers, header_lit):
            h.set_lit(lit if on else ())
        if self.rail is not None:
            self.rail.set_value(value)
        self.set_counts(counts)

    def set_counts(self, counts):
        if self.rail is not None:
            self.rail.set_counts(*counts())

    def refresh_size(self):
        """Font / scale change (``relayout_info_panels``): the rail re-fits its height."""
        if self.rail is not None:
            self.rail.refresh_size()
        if self.tour_key is not None:
            self.tour_key.refresh_size(self.rail.height())

    def drop(self):
        self.toggle = self.rail = self.tour_key = self.cells = None
        self.headers = ()


def place_tour_key(rail, make_key):
    """The tour key at the right end of the rail row (SPEC-TJK-003 §4.9): rail, then key."""
    page = rail.parentWidget().layout()
    index = page.indexOf(rail)
    page.removeWidget(rail)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    key = make_key(rail.parentWidget())
    key.refresh_size(rail.height())
    row.addWidget(rail, 1)
    row.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
    page.insertLayout(index, row)
    return key


# ------------------------------------------------------------ tour (§4.6)
class CenterTour:
    """One pass over a drawing's marks: ``show(step, label)`` focuses a step (False -> the
    tour ends), ``clear()`` drops the focus, ``ring(step or None)`` marks the matrix.
    ``revision``: the binding revision at the start (an older status never stops it)."""

    def __init__(self, show, clear, ring):
        self._show, self._clear, self._ring = show, clear, ring
        self._steps = ()
        self._index = 0
        self.key = None               # the TourKey whose lamp shows the tour
        self.revision = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.step)

    def touring(self) -> bool:
        return bool(self._steps)

    def is_stale(self, revision) -> bool:
        """A status event older than this tour's start (it cannot stop the tour)."""
        return isinstance(revision, int) and self.revision is not None and revision < self.revision

    def start(self, steps, step_ms, revision, now=True):
        self._steps = tuple(steps)
        self._index = 0
        self.revision = revision
        if self.key is not None:
            self.key.set_playing(True)
        if now:
            self.step()
        if self._steps:
            self.timer.start(step_ms)

    def step(self):
        if self._index >= len(self._steps):
            self.stop()                      # one pass
            return
        step = self._steps[self._index]
        label = f"{self._index + 1} / {len(self._steps)}"
        self._index += 1
        if not self._show(step, label):
            self.stop()
            return
        self._ring(step)

    def stop(self):
        """End the tour: timer, focus, matrix ring and the key's lamp."""
        if not self._steps:
            return
        import shiboken6
        self._steps = ()
        if shiboken6.isValid(self.timer):
            self.timer.stop()
        if self.key is not None and shiboken6.isValid(self.key):
            self.key.set_playing(False)
        self._clear()
        self._ring(None)

    def shutdown(self):
        import shiboken6
        if shiboken6.isValid(self.timer):     # gone with the application
            self.timer.stop()


# ------------------------------------------------------------ the state owner
class CenterDrawingController(PanelControllerBase):
    """Eager; one per drawing kind and GUI, registered in the registry (see module
    docstring for the hooks a drawing implements)."""

    KIND = ""
    KEY_ON = KEY_MIN = ""
    TABLE = ""                       # the GUI attribute of the drawing's matrix
    NO_LIT = frozenset()

    def __init__(self, gui, settings):
        super().__init__(gui=gui, lazy=False)
        self._settings = settings
        from core import settings_registry as registry
        self._on = bool(settings.get(self.KEY_ON, registry.default(self.KEY_ON)))
        self._min = int(settings.get(self.KEY_MIN, registry.default(self.KEY_MIN)) or 0)
        self._lit = self.NO_LIT
        self._pushed = None
        self._reason = "off"
        self._links = None               # PanelLinks: the panel connections, cut on teardown
        self._rail_timer = QTimer()
        self._rail_timer.setSingleShot(True)
        self._rail_timer.setInterval(RAIL_DELAY_MS)
        self._rail_timer.timeout.connect(self._rail_settled)
        self._tour = CenterTour(self._show_step, self._clear_focus, self._ring)
        self._widgets = CenterPanelWidgets()
        self._alive = False
        self._build()

    # ------------------------------------------------------------ build / teardown
    def _build(self):
        from apps.widgets.south_indian_center_pass import center_status_signal
        gui = self._gui
        table = getattr(gui, self.TABLE, None)
        header = getattr(gui, "aspects_header", None)
        if table is None or header is None:
            return
        self._alive = True
        register_center_controller(gui, self.KIND, self)
        ensure_mode_sync(gui)              # the mode is set before the first push
        self._widgets.build(header, gui.aspects_mode_btn, table, self._parts(),
                            with_notice(self))
        self._tour.key = self._widgets.tour_key
        for key in (self.KEY_ON, self.KEY_MIN):
            self._settings.on_changed(key, self._setting_written)
        links = self._links = PanelLinks(table)
        signal = center_status_signal(main_host(gui), self.KIND)
        if signal is not None:
            # queued: the status changes inside a scene rebuild; the tooltip and the
            # focus hold (a layout change) follow once the rebuild is done
            links.add(signal.changed, self._status_changed, Qt.ConnectionType.QueuedConnection)
        stack = getattr(gui, "aspects_stack", None)
        if stack is not None:
            links.add(stack.currentChanged, self._mode_maybe_changed)
        host = main_host(gui)
        styles = host.layout() if host is not None else None
        if isinstance(styles, QStackedLayout):      # classic <-> vector: no rebuild, no status
            links.add(styles.currentChanged, self._status_changed)
        pages = getattr(gui, "chart_stack", None)
        if pages is not None:                       # wheel / North Indian / other chart pages
            links.add(pages.currentChanged, self._status_changed)
        links.add(table.destroyed, self.teardown)
        self._widgets.sync(self._on, self._header_lit(), self._min, self.in_mode(), self._counts)
        self._push()

    def teardown(self, *_):
        """Drop the settings callbacks (held strongly by the manager), the signal
        connection, the widget references and the registry entry; stop pushing."""
        if not self._alive:
            return
        self._alive = False
        import shiboken6
        if shiboken6.isValid(self._rail_timer):
            self._rail_timer.stop()
        self._tour.shutdown()
        self.stop_tour()                     # the focus lives on the view: drop it
        for key in (self.KEY_ON, self.KEY_MIN):
            try:
                self._settings.remove_on_changed(key, self._setting_written)
            except (KeyError, ValueError):
                pass
        self._links.cut()                    # status, stack, style, page and table links
        if self._state is not None:
            try:
                self._state.disconnect(self._dispatch_state_change)
            except ValueError:
                pass
        self._tour.key = None
        self._widgets.drop()
        self._hold(False)
        unregister(self._gui, self.KIND, self)

    # ------------------------------------------------------------ the one update path
    def apply_state(self, *, on=None, min_virupas=None, lit=None, persist=False):
        """Change any of the three values; equal writes are ignored. ``persist`` writes
        the settings (user action on the panel). Returns True when something changed."""
        new_on = self._on if on is None else bool(on)
        new_min = self._min if min_virupas is None else max(0, min(60, int(min_virupas)))
        new_lit = self._lit if lit is None else self._as_lit(lit)
        if (new_on, new_min, new_lit) == (self._on, self._min, self._lit):
            return False
        self.stop_tour()                     # any panel action ends a tour
        changed_on, changed_min = new_on != self._on, new_min != self._min
        self._on, self._min, self._lit = new_on, new_min, new_lit
        if persist:
            _persist(self._settings, (self.KEY_ON, new_on, changed_on),
                     (self.KEY_MIN, new_min, changed_min))
        self._widgets.sync(self._on, self._header_lit(), self._min, self.in_mode(), self._counts)
        if changed_min and min_virupas is not None and persist:
            self._rail_timer.start()          # a drag: (re)start the debounce, one redraw on settle
        else:
            self._push()
        return True

    # ------------------------------------------------------------ panel actions
    def toggle(self, *_):
        return self.apply_state(on=not self._on, persist=True)

    def press(self, body):
        """A key: toggles the body in its lit set; while OFF it turns the drawing ON."""
        if not body:
            return None
        return self.apply_state(on=True if not self._on else None,
                                lit=self._lit_after_press(body), persist=not self._on)

    def _rail_moved(self, value):
        self.apply_state(min_virupas=value, persist=True)

    def _rail_settled(self):
        flush = getattr(self._settings, "flush", None)
        if callable(flush):
            flush()
        self._push()

    def _setting_written(self, key, value):
        if not self._alive:
            return
        if key == self.KEY_ON:
            self.apply_state(on=bool(value))
        elif key == self.KEY_MIN:
            self.apply_state(min_virupas=int(value or 0))

    def _mode_maybe_changed(self, *_):
        """A page change of the panel: widgets follow; a mode away from this kind ends
        its tour. Never a push (the mode moves through ``CenterModeSync``)."""
        if not self.in_mode():
            self.stop_tour()
        self._widgets.sync(self._on, self._header_lit(), self._min, self.in_mode(), self._counts)
        self._status_changed()

    # ------------------------------------------------------------ state reads
    @property
    def state(self):
        return self._make_state(self._on)

    def in_mode(self) -> bool:
        return getattr(self._gui, "_aspects_mode", "vedic") == self.KIND

    def reason(self) -> str:
        """The status reason the toggle tooltip names (main host not on screen or not
        South Indian: ``not_vector``; ON in the other panel mode: ``<kind>_mode_off``)."""
        from apps.widgets.south_indian_center_pass import center_drawing_status
        host = main_host(self._gui)
        stack = getattr(self._gui, "chart_stack", None)
        if host is None or (stack is not None and stack.currentWidget() is not host):
            return "not_vector"
        reason = center_drawing_status(host, self.KIND)[0]
        return f"{self.KIND}_mode_off" if reason == "inactive" else reason

    # ------------------------------------------------------------ tour
    def tour(self, *_):
        """The Tour key: start a pass over the drawn marks, or stop the running one.
        While OFF the drawing turns ON first and the first step follows the switch-on
        animation. Returns True when a tour started."""
        from apps.widgets.south_indian_center_pass import center_drawing_status
        if self._tour.touring():
            self.stop_tour()
            return False
        if not (self._alive and self.in_mode()):
            return False
        turned_on = not self._on
        if turned_on:
            self.apply_state(on=True, persist=True)
        if self.reason() != "shown":         # hidden (classic, other chart page, Guide...)
            return False
        host = main_host(self._gui)
        model = self._model(host)
        steps = self._tour_steps(model) if model is not None else ()
        if not steps:
            return False
        self._tour.start(steps, tour_step_ms(self._settings),
                         center_drawing_status(host, self.KIND)[1], now=not turned_on)
        return True

    def stop_tour(self):
        self._tour.stop()

    # ------------------------------------------------------------ push + status
    def _push(self):
        if not self._alive:
            return
        state = self._make_state(self._on)
        if state != self._pushed:
            self._pushed = state
            self._push_state(main_host(self._gui), state)
        self._status_changed()

    def _status_changed(self, emitted=None, revision=None, *_):
        if not self._alive:
            return
        self._reason = self.reason() if self._on else "off"
        # suppressed: Guide, varga, classic... ``emitted`` is the reason the queued
        # signal carried: a Guide on/off before the queue runs still stops the tour,
        # unless the event is older than the tour (SPEC-VAC-001 §4.6).
        stale = self._tour.is_stale(revision)
        if self._reason != "shown" or (isinstance(emitted, str) and emitted != "shown" and not stale):
            self.stop_tour()
        if self._widgets.toggle is not None:
            self._widgets.toggle.setToolTip(toggle_tooltip(self._reason))
        self._widgets.set_counts(self._counts)
        self._hold(self._reason == "shown" and self.in_mode(), period=self._on)

    _on_view_changed = _status_changed

    def _hold(self, on, period=False):
        import shiboken6
        stack = getattr(self._gui, "right_panels", None)
        if stack is None or not shiboken6.isValid(stack):
            return
        hold = getattr(stack, "set_focus_hold", None)
        if callable(hold):
            hold(bool(on), period=period, owner=self.KIND)

    def refresh_size(self):
        """Font / scale change (``relayout_info_panels``)."""
        self._widgets.refresh_size()

    def _on_chart_changed(self):
        """New chart: new ticks and counts (the drawing redraws with the view)."""
        self.stop_tour()
        if self._widgets.rail is None:
            return
        self._widgets.rail.set_ticks(self._ticks())
        self._status_changed()
