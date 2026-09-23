"""The Human Design BodyGraph, as a QGraphicsView.

Four composite items, not hundreds. Every trace, pad, numeral and halo is painted by
``hd_painter`` inside one of four ``QGraphicsItem``s, because a scene holding ~250
independently animated items spends its whole frame budget in Qt's item machinery
rather than in drawing:

    aura      z -10   animated, uncached
    network   z   0   the traces; static per state, DeviceCoordinateCache
    chrome    z  10   centres, terminals, numerals; static per state, cached
    pulse     z  20   animated, uncached, and absent entirely under Calm

The split is exactly the animation boundary. Anything that changes every frame is kept
out of the cached items, so panning, resizing and hovering replay a blit instead of
re-running the whole drawing.

Rule 18: the items own their geometry as plain data and hold no child items, and the
Python references are dropped after ``scene.addItem`` takes ownership.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ui.qt_theme import hd_palette
from . import hd_geometry as G
from . import hd_painter as P
from .hd_channel_names import channel_name

#: The shared clock. 24 fps is enough for a dash travelling a few pixels a frame and a
#: halo breathing over eleven seconds, and leaves the budget to the rest of the app.
FRAME_MS = 42

#: Qt's own ceiling on a cached graphics item, in DEVICE pixels on the longest side.
#: Not configurable and not announced: past it, setCacheMode(DeviceCoordinateCache) is
#: quietly ignored. Measured empirically on this build -- a cached layer 1109 px tall
#: still blitted, one 1173 px tall did not -- and left a little under the observed
#: crossover so the cap holds rather than sits on the edge.
CACHE_CEILING_PX = 1024.0

#: The aura layer repaints once every this many pulse frames. Its breath is an 11 second
#: cycle, so a step of ~0.25 s is far below anything a viewer can resolve.
AURA_EVERY_N_FRAMES = 6
#: One full turn of the pulse. The aura breathes over a longer multiple of the same clock.
PULSE_PERIOD_MS = P.PULSE_PERIOD_MS
AURA_PERIOD_MS = 11000

#: The order the arrow keys walk the centres in: down the body, then the two wings.
#: Anatomical rather than alphabetical, because that is how the chart is read.
KEYBOARD_CENTRE_ORDER = ("head", "ajna", "throat", "g", "sacral", "root",
                         "spleen", "solar", "will")

#: Wheel-zoom bounds, as multiples of the fit scale. Deliberately far outside anything
#: a reader would ask for: they exist so the transform cannot go degenerate, not to
#: express an opinion about how close somebody may look at their own chart.
ZOOM_OUT_LIMIT = 0.2
ZOOM_IN_LIMIT = 12.0

#: How close the pointer must come to a trace, in canvas units, to pick it out.
TRACE_HIT_TOLERANCE = 5.0
#: Radius around a gate's numeral that selects that gate.
GATE_HIT_RADIUS = 8.0
#: How far the pointer must travel with the button down before a click becomes a drag.
#: Small enough that dragging feels immediate, large enough that a click with a shaky
#: hand still pins what it was aimed at.
PAN_SLOP = 4

#: The ordinary channels as flattened polylines, for hit testing. Built once.
_HIT_LINES: tuple | None = None


def _hit_lines() -> tuple:
    """``((key, polyline, bounds), ...)`` for every non-braid channel, built once.

    This is not a micro-optimisation. ``_hit()`` runs on every mouse move, and building
    these there re-sampled every cubic in the graph each time: measured at 70 ms per
    call, which caps pointer feedback near 14 Hz and blocks the animation timer while
    the mouse is moving. The geometry is immutable and identical for every chart, so it
    belongs to the module rather than to the event. Same reasoning as the painter's
    ``_TRACES``; the hit path was simply missed when that one was cached, because the
    benchmark at the time measured painting and nothing measured hovering.

    Each entry carries its bounding box as well. Point-to-polyline is the expensive
    part and almost every channel is nowhere near the pointer, so the box rejects most
    of them on four comparisons.

    Tuples rather than lists: this is shared by every view in the process and must not
    be edited by whatever borrows it.
    """
    global _HIT_LINES
    if _HIT_LINES is None:
        entries = []
        for key in G.CHANNEL_KEYS:
            if G.is_braid(key):
                continue
            line = tuple(G.channel_flat(key, 2.0))
            xs = [p[0] for p in line]
            ys = [p[1] for p in line]
            entries.append((key, line, (min(xs), min(ys), max(xs), max(ys))))
        _HIT_LINES = tuple(entries)
    return _HIT_LINES


class _Layer(QGraphicsItem):
    """One painted slice of the graph. Holds the shared state, never a copy of it."""

    def __init__(self, view: "HDBodygraphView", paint: Callable, cached: bool,
                 pad: float):
        super().__init__()
        self._view = view
        self._paint = paint
        self._pad = pad
        #: whether this layer WANTS caching; whether it gets it depends on the zoom
        self.cacheable = cached
        if cached:
            # a static layer repaints only when the STATE moves, so caching it at device
            # resolution turns a pan or a resize into a blit
            self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def set_cached(self, on: bool) -> None:
        """Turn this layer's cache on or off as the zoom crosses Qt's cliff.

        Past ~1024 device px Qt ignores DeviceCoordinateCache and repaints the layer in
        full anyway, while still doing the bookkeeping for a cache it is not using.
        Saying NoCache there is simply honest: it costs nothing and stops pretending.
        """
        if not self.cacheable:
            return
        mode = (QGraphicsItem.CacheMode.DeviceCoordinateCache if on
                else QGraphicsItem.CacheMode.NoCache)
        if self.cacheMode() != mode:
            self.setCacheMode(mode)

    def boundingRect(self) -> QRectF:
        # Each layer declares only the margin IT actually paints into. A shared generous
        # box would be simpler, but Qt silently drops DeviceCoordinateCache once an
        # item's device-space box passes ~1024 px on a side, and a fat box reaches that
        # cliff sooner. Past it the "cached" layers repaint in full behind every pulse
        # frame, which is the difference between a 15 ms frame and an 80 ms one.
        return P.VIEWBOX.adjusted(-self._pad, -self._pad, self._pad, self._pad)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint(painter, self._view.state)


class HDBodygraphView(QGraphicsView):
    """The graph. Feed it a model with ``update_from_chart``.

    Follows the chart-view kwargs convention: everything the view shows is passed to
    ``update_from_chart(chart, **kwargs)``, and there are no mode setters to fall out of
    step with it.
    """

    #: Emitted when the pointer enters or leaves something nameable, with a short
    #: description for the status line, or an empty string.
    hover_changed = Signal(str)
    #: Emitted when the user clicks a gate, channel or centre. ``(kind, key)``.
    element_clicked = Signal(str, str)
    #: The set of gate numbers currently focused, empty when nothing is. The two planet
    #: columns follow this so a hover on the graph raises the ROWS that put those gates
    #: there -- the chart's two halves answering each other.
    focus_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

        self.state = P.HDGraphState(model={}, palette=hd_palette())
        self._pinned: tuple | None = None
        #: Where the button went down, while it is down; None when it is not.
        self._panning = None
        #: Whether that press has travelled far enough to count as a drag.
        self._panned = False
        self._elapsed = 0

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(P.VIEWBOX)
        self.setScene(self._scene)

        # (z, painter, cached, how far outside VIEWBOX this layer actually paints)
        # The ground bleeds past the viewbox because the aurora is still visible there.
        # MEASURED, not guessed: alpha on the viewbox border peaks at 24/255, which cut
        # off square is the rectangle edge Lorris saw; 60 px out it is 6/255, which is
        # not. Bigger would be safer for the seam and worse for everything else -- the
        # box is what decides when Qt abandons the cache, so 150 px lost the ground its
        # cache at ordinary window sizes, and an uncached ground repaints under every
        # pulse frame.
        for z, paint, cached, pad in ((-20, P.paint_ground, True, 60.0),
                                      (-10, P.paint_auras, False, 80.0),
                                      (0, P.paint_network, True, 14.0),
                                      (10, self._paint_chrome, True, 12.0),
                                      (20, P.paint_pulse, False, 6.0)):
            layer = _Layer(self, paint, cached, pad)
            layer.setZValue(z)
            self._scene.addItem(layer)
            if z == -20:
                self._ground = layer
            elif z == 0:
                self._network = layer
            elif z == 10:
                self._chrome = layer
            elif z == 20:
                self._pulse_layer = layer
            else:
                self._aura = layer
            del layer          # Rule 18: the scene owns it now

        self._aura_countdown = 0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # -- the fonts the numerals are drawn in -------------------------------------------

    def _paint_chrome(self, painter, state) -> None:
        P.paint_centres(painter, state)
        P.paint_terminals(painter, state)
        plain = QFont(self.font())
        plain.setPixelSize(10 if state.label_mode == "hexagrams" else 9)
        plain.setBold(state.label_mode != "hexagrams")
        disc = QFont(self.font())
        disc.setPixelSize(10 if state.label_mode == "hexagrams" else 9)
        disc.setBold(state.label_mode != "hexagrams")
        P.paint_gates(painter, state, plain, disc)

    # -- the public surface -------------------------------------------------------------

    def update_from_chart(self, chart, **kwargs) -> None:
        """Show ``chart`` (an HDModel dict), with any of the view's options.

        Recognised kwargs: ``label_mode``, ``activation_filter``, ``pulse``. Unknown ones
        are ignored rather than raising, so a caller that passes the shared chart-view
        kwargs does not have to know which of them this view understands.
        """
        # normalised at the door: a present-but-wrong-typed field (gates as a list, a
        # None root, an int timestamp) raises from inside paint otherwise, and the view
        # is hosted standalone in tests and tools as well as inside HDPanel
        self.state.model = P.normalise_model(chart)
        self.state.palette = hd_palette()
        for name in ("label_mode", "activation_filter", "pulse"):
            if name in kwargs and kwargs[name] is not None:
                setattr(self.state, name, kwargs[name])
        self._clear_focus(repaint=False)
        self.refresh_theme()
        self._sync_clock()
        self.fit()

    def refresh_theme(self) -> None:
        """Re-read the palette and repaint. Called by the theme registry on a switch."""
        self.state.palette = hd_palette()
        # the view paints no ground of its own: the PAGE's background shows through,
        # so there is no seam between the graph and the panel around it
        self.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self._invalidate_all()

    def fit(self) -> None:
        """Fill the viewport with the graph. The INITIAL and reset scale, nothing else.

        This used to stop at Qt's item-cache ceiling (~1024 device px per side), on the
        reasoning that a graph sitting letterboxed in a larger frame reads as a design
        choice while a pulse at 12 fps reads as a fault. On a 2000 px screen it does not:
        it reads as a small drawing marooned in a huge empty frame, and it made the wheel
        feel stuck, because the clamp was already engaged before the user touched it.
        Filling the space the app gives it is what every other view here does.

        The cost is real and is paid deliberately: past the ceiling the static layers
        stop being cached and repaint behind every animated frame. ``_apply_cache_mode``
        stops Qt maintaining a cache it has silently abandoned, and the pulse can be
        turned off from the toolbar, which is the honest lever for it.
        """
        self.fitInView(P.VIEWBOX, Qt.AspectRatioMode.KeepAspectRatio)
        self._apply_cache_mode()

    def _apply_cache_mode(self) -> None:
        """Cache the static layers only while Qt would actually honour the cache."""
        keep = self.transform().m11() <= self._cache_safe_scale()
        for layer in (self._ground, self._network, self._chrome):
            layer.set_cached(keep)

    def _cache_safe_scale(self) -> float:
        """The largest scale at which every CACHED layer still fits the cache.

        Measured against the widest cached layer, and in device pixels: on a HiDPI
        screen the device pixel ratio multiplies the box, so a 1080-tall window on a
        2x display is already past the ceiling in device terms even though its logical
        size is not.
        """
        ratio = float(self.devicePixelRatioF() or 1.0)
        limit = float("inf")
        for layer in (self._ground, self._network, self._chrome):
            box = layer.boundingRect()
            span = max(box.width(), box.height()) * ratio
            if span > 0:
                limit = min(limit, CACHE_CEILING_PX / span)
        return limit

    def set_option(self, **kwargs) -> None:
        """Change a view option without re-supplying the chart."""
        changed = False
        for name in ("label_mode", "activation_filter", "pulse"):
            if name in kwargs and getattr(self.state, name) != kwargs[name]:
                setattr(self.state, name, kwargs[name])
                changed = True
        if changed:
            self._sync_clock()
            self._invalidate_all()

    # -- the shared animation clock ------------------------------------------------------

    def _motion_allowed(self) -> bool:
        """Calm, and the app-wide reduce-motion setting, both stop the clock.

        Read at the moment it matters rather than cached, so toggling the setting takes
        effect without rebuilding the view.
        """
        if not self.state.pulse:
            return False
        try:
            from managers.settings_manager import get_settings
            if get_settings().get_reduce_motion():
                return False
        except Exception:
            pass                    # a missing settings layer must not stop the view drawing
        return True

    def _sync_clock(self) -> None:
        """Run the timer only when it can be seen and motion is wanted.

        A timer left running behind a hidden tab repaints a scene nobody is looking at,
        which is the difference between an idle app and one that never lets the CPU sleep.
        """
        want = self.isVisible() and self._motion_allowed()
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()
            self.state.phase = 0.0
            self._aura.update()
            self._pulse_layer.update()

    def _tick(self) -> None:
        self._elapsed += FRAME_MS
        self.state.phase = (self._elapsed % PULSE_PERIOD_MS) / PULSE_PERIOD_MS
        self._pulse_layer.update()
        # The auras breathe on an 11 s cycle; the pulse travels on a 2.4 s one. Repainting
        # nine large radial gradients at the pulse's rate is most of the animated cost
        # and buys nothing a viewer can see, so the aura layer redraws at a fraction of
        # the frame rate. A hover is the exception: that swell IS fast, and it repaints
        # through _apply_focus rather than waiting for the next slow frame.
        self._aura_countdown -= 1
        if self._aura_countdown <= 0 or self.state.focus_centres:
            self._aura_countdown = AURA_EVERY_N_FRAMES
            self._aura.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_clock()
        self.fit()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_clock()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    # -- hit testing and focus ------------------------------------------------------------

    def _hit(self, scene_point) -> tuple | None:
        """What is under the pointer: a gate, a braid track, a channel, or a centre.

        Ordered by how precisely the user must aim. A numeral is small and deliberate, so
        it wins; a centre is large and is the fallback. On the braid the TRACK is the
        target rather than the channel, because six overlapping hit paths on shared track
        make "which channel is under the cursor" arbitrary.
        """
        x, y = scene_point.x(), scene_point.y()

        for gate in G.GATES:
            lx, ly = G.gate_label(gate)
            if (lx - x) ** 2 + (ly - y) ** 2 <= GATE_HIT_RADIUS ** 2:
                return ("gate", gate)

        best = None
        from . import hd_curves as C
        for track in G.TRACK_NAMES:
            d = C.distance_to_polyline((x, y), G.track_polyline(track))
            if d <= TRACE_HIT_TOLERANCE and (best is None or d < best[0]):
                best = (d, ("track", track))
        for key, line, (x0, y0, x1, y1) in _hit_lines():
            if (x < x0 - TRACE_HIT_TOLERANCE or x > x1 + TRACE_HIT_TOLERANCE
                    or y < y0 - TRACE_HIT_TOLERANCE or y > y1 + TRACE_HIT_TOLERANCE):
                continue
            d = C.distance_to_polyline((x, y), line)
            if d <= TRACE_HIT_TOLERANCE and (best is None or d < best[0]):
                best = (d, ("channel", key))
        if best is not None:
            return best[1]

        for centre in G.CENTERS:
            if C.point_in_polygon((x, y), G.centre_polygon(centre)):
                return ("centre", centre)
        return None

    def _focus_for(self, hit: tuple) -> tuple[frozenset, frozenset, frozenset, frozenset]:
        """Everything that should stay lit for a given hit.

        Hovering a centre lights the centre, its gates, every channel touching them and
        the centres at their far ends -- so the answer to "what does this centre connect
        to" is the picture, not a list.
        """
        kind, value = hit
        if kind == "centre":
            gates = set(G.CENTER_FACES[value])
        elif kind == "gate":
            gates = {value}
        elif kind == "channel":
            gates = set(G.gates_of_channel(value))
        else:
            gates = {g for k in G.channels_on_track(value)
                     for g in G.gates_of_channel(k)}

        channels = {k for k in G.CHANNEL_KEYS
                    if set(G.gates_of_channel(k)) & gates}
        if kind == "channel":
            channels = {value}
        elif kind == "track":
            channels = set(G.channels_on_track(value))

        all_gates = set(gates)
        for key in channels:
            all_gates |= set(G.gates_of_channel(key))
        centres = {G.centre_of_gate(g) for g in all_gates}
        if kind == "centre":
            centres.add(value)
        tracks = {t for t in G.TRACK_NAMES
                  if set(G.channels_on_track(t)) & channels}
        return (frozenset(centres), frozenset(all_gates),
                frozenset(channels), frozenset(tracks))

    def _apply_focus(self, hit: tuple | None) -> None:
        if hit is None:
            self._clear_focus()
            return
        centres, gates, channels, tracks = self._focus_for(hit)
        self.state.focus_centres = centres
        self.state.focus_gates = gates
        self.state.focus_channels = channels
        self.state.focus_tracks = tracks
        self._invalidate_all()
        self.focus_changed.emit(gates)

    def _clear_focus(self, repaint: bool = True) -> None:
        self.state.focus_centres = frozenset()
        self.state.focus_gates = frozenset()
        self.state.focus_channels = frozenset()
        self.state.focus_tracks = frozenset()
        if repaint:
            self._invalidate_all()
            self.focus_changed.emit(frozenset())

    def focus_gate(self, gate: int | None) -> None:
        """Focus one gate from outside -- a planet row hovered in a side column.

        Ignored while something is pinned: a pin is a deliberate choice, and a stray
        pointer crossing a row must not silently replace it.
        """
        if self._pinned is not None:
            return
        if gate is None:
            self._clear_focus()
            return
        try:
            gate = int(gate)
        except (TypeError, ValueError):
            self._clear_focus()
            return
        if gate not in G.GATES:
            # an activation row carrying a gate this geometry does not have -- a model
            # from a later contract, or a bad one. The row still SHOWS, because hiding
            # the engine's own output would be worse; it simply has nothing to light.
            self._clear_focus()
            return
        self._apply_focus(("gate", gate))

    def _invalidate_all(self) -> None:
        for layer in (self._ground, self._aura, self._network, self._chrome,
                      self._pulse_layer):
            layer.update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._panning is not None:
            self._pan_to(event)
            return
        if self._pinned is not None:
            return
        hit = self._hit(self.mapToScene(event.position().toPoint()))
        self._apply_focus(hit)
        self.hover_changed.emit(describe(hit) if hit else "")
        self._show_cursor(hit)

    def _show_cursor(self, hit) -> None:
        """Say what the pointer would do here.

        An open hand over empty space is a promise that dragging moves something, so it
        is only offered when there is somewhere to move TO: at fit scale the graph fills
        its frame, the scroll range is zero, and a hand cursor there would be a lie.
        """
        if hit is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._can_pan():
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _can_pan(self) -> bool:
        return bool(self.horizontalScrollBar().maximum()
                    or self.verticalScrollBar().maximum())

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._pinned is None:
            self._clear_focus()
            self.hover_changed.emit("")

    def mousePressEvent(self, event):
        """A press might become a drag, so it does not decide anything yet.

        Panning and pinning share the left button, which they have to: the graph is
        zoomable now, so dragging it is the obvious way to move around, and clicking a
        centre is the obvious way to select one. They are told apart by DISTANCE -- a
        press that never travels PAN_SLOP pixels was a click, and the pin is applied on
        release. Deciding on press instead would pin whatever sat under the start of
        every drag.

        Qt's own ScrollHandDrag would do the panning and eat the clicks, which is why it
        is not used here.
        """
        super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = event.position().toPoint()
            self._panned = False

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        travelled = self._panned
        self._panning = None
        self._show_cursor(self._hit(self.mapToScene(event.position().toPoint())))
        if travelled:
            return                      # that was a drag, not a click
        hit = self._hit(self.mapToScene(event.position().toPoint()))
        # a second click on the same thing, or a click on empty space, lets go
        self.pin(None if (hit is None or hit == self._pinned) else hit)

    def _pan_to(self, event) -> None:
        """Drag the graph under the pointer.

        Driven through the scroll bars rather than a transform of our own, which is how
        every other chart view here pans, and which clamps for free: the graph cannot be
        dragged out of its own frame. The bars are hidden (a visible one would cut the
        seam between the page background and the graph) but their RANGE is still live,
        so at fit scale there is nothing to pan and a drag correctly does nothing.
        """
        point = event.position().toPoint()
        delta = point - self._panning
        if not self._panned:
            if abs(delta.x()) < PAN_SLOP and abs(delta.y()) < PAN_SLOP:
                return
            self._panned = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            self._clear_focus()         # a hover highlight left mid-drag reads as stuck
        self._panning = point
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta.x())
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - delta.y())

    def keyPressEvent(self, event):
        """Escape lets go; the arrows walk the centres.

        The graph is the only place some of this chart exists, so it cannot be a
        pointer-only surface. The arrows step through the nine centres in anatomical
        order and pin each in turn, which reaches by keyboard everything a hover
        reaches: the centre, its channels, both gates of each, and the matching rows in
        the two columns.
        """
        key = event.key()
        if key == Qt.Key.Key_Escape:
            # Escape puts the graph back: it lets go of whatever is held, pinned or
            # merely hovered, AND undoes the zoom and the pan. It says so even when
            # nothing was held rather than falling through to a parent that might close
            # the window. One key for "start over" is worth more than two precise ones,
            # because a graph dragged somewhere unexpected needs a way back that the
            # user can guess.
            self._pinned = None
            self._clear_focus()
            self.hover_changed.emit("")
            self.fit()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Left):
            forward = key in (Qt.Key.Key_Down, Qt.Key.Key_Right)
            self._step_centre(1 if forward else -1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.state.focus_centres and self._pinned is None:
                centre = sorted(self.state.focus_centres)[0]
                self.pin(("centre", centre))
            return
        super().keyPressEvent(event)

    def _step_centre(self, direction: int) -> None:
        order = KEYBOARD_CENTRE_ORDER
        current = None
        if self._pinned and self._pinned[0] == "centre":
            current = self._pinned[1]
        if current in order:
            index = (order.index(current) + direction) % len(order)
        else:
            index = 0 if direction > 0 else len(order) - 1
        self.pin(("centre", order[index]))

    def pin(self, hit: tuple | None) -> None:
        """Hold ``hit`` until it is unpinned. ``None`` lets go.

        Public because the side columns and the channel index pin through it: clicking
        a planet row or a channel name is the same act as clicking the graph, and has to
        leave the view in the same state.
        """
        if hit is None:
            self._pinned = None
            self._clear_focus()
            self.hover_changed.emit("")
            return
        self._pinned = hit
        self._apply_focus(hit)
        self.hover_changed.emit(describe(hit))
        self.element_clicked.emit(hit[0], str(hit[1]))

    def wheelEvent(self, event):
        """Zoom about the pointer, freely, in and out.

        This used to stop at the item-cache ceiling and at half the fit scale. On a
        large window the ceiling was already reached by ``fit``, so the wheel did
        nothing at all in the direction people actually turn it -- "stuck", correctly.
        A chart is read by leaning into it; a zoom that refuses to zoom is not a
        performance feature, it is a broken control.

        The remaining bounds are numerical rather than editorial: far enough out that
        the graph is a speck, far enough in that a single gate fills the window, and
        wide enough that neither is ever met in use.
        """
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = self.transform().m11()
        fit_scale = self._fit_scale()
        target = min(max(current * factor, ZOOM_OUT_LIMIT * fit_scale),
                     ZOOM_IN_LIMIT * fit_scale)
        if abs(target - current) < 1e-9:
            return
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(target / current, target / current)
        self._apply_cache_mode()

    def _fit_scale(self) -> float:
        """The scale ``fit`` would choose, without actually applying it."""
        box, port = P.VIEWBOX, self.viewport().rect()
        if box.width() <= 0 or box.height() <= 0:
            return 1.0
        return min(port.width() / box.width(), port.height() / box.height())


def describe(hit: tuple | None) -> str:
    """A short human sentence for the status line."""
    if not hit:
        return ""
    kind, value = hit
    if kind == "gate":
        return f"Gate {value} · {G.centre_of_gate(value)}"
    if kind == "channel":
        a, b = G.gates_of_channel(value)
        return f"Channel {a}-{b} · {channel_name(a, b)}"
    if kind == "track":
        names = ", ".join(G.channels_on_track(value))
        return f"Braid track {value} · carries {names}"
    return f"{value} centre"
