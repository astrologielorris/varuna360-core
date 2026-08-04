# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Offline Map Widget — interactive OSM map over the SQLite tile cache.

SPEC-MAP-001. The rendering core was replaced 2026-07-26; read §3.1 of the
spec before changing anything here.

The one idea that makes this fast
---------------------------------
The scene is a FIXED reference frame: scene coordinates are always Web
Mercator pixels at `Z_REF`, never at the current zoom. Zoom is therefore a
view transform, not a scene rebuild.

    tile (z,x,y):  setScale(2^(Z_REF-z)),  setPos(x*256*scale, y*256*scale)
    view:          transform scale = 2^(zoom - Z_REF),  zoom is a FLOAT

Consequences, all of which were bugs before:
  * zooming is O(1) and never clears the scene, so no blank frames;
  * tiles from other levels stay valid on screen as a backdrop while finer
    ones stream in;
  * cursor anchoring is Qt's own AnchorUnderMouse instead of hand-rolled
    centerOn arithmetic;
  * overlays (eclipse zones) are drawn once and are zoom-invariant.

All tile I/O lives in `map_tiles.TileWorker` on its own thread (INV-1). This
file must never call sqlite3, urllib, or geopy.
"""

import atexit as _atexit
import math
import os
import threading as _threading
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsPathItem,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
)
from PySide6.QtCore import (
    Signal, Slot, Qt, QPointF, QRectF, QThread, QTimer, QElapsedTimer,
    QVariantAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QPixmap, QPen, QBrush, QColor, QPolygonF, QPainterPath,
    QWheelEvent, QMouseEvent, QImage,
)

from apps.widgets.map_tiles import (
    TILE_SIZE, Z_REF, MIN_TILE_ZOOM, SOFT_MAX_ZOOM, HARD_MAX_ZOOM,
    BASE_KEEP_ZOOM, DEFAULT_DB_PATH, TileWorker, ZoomDetent,
    wheel_zoom_delta,
    lat_lon_to_tile, tile_to_lat_lon, lat_lon_to_pixel, pixel_to_lat_lon,
    lat_lon_to_scene, scene_to_lat_lon, tile_scene_rect,
)

__all__ = [
    "OfflineMapWidget", "OfflineMapPanel", "TILE_SIZE", "DEFAULT_DB_PATH",
    "lat_lon_to_tile", "tile_to_lat_lon", "lat_lon_to_pixel", "pixel_to_lat_lon",
]

#: World extent of the fixed reference frame, in scene units.
WORLD_UNITS = TILE_SIZE * (2 ** Z_REF)

#: Eased transform time for one zoom change (§4.1).
ZOOM_ANIM_MS = 110
#: Viewport-change requests are coalesced over this window, so a pan gesture
#: enqueues one batch instead of one per mouseMoveEvent (RC-2).
REQUEST_DEBOUNCE_MS = 40
#: Levels kept around the current one as a backdrop while tiles stream in.
BACKDROP_LEVELS = 2
#: Extra tile ring loaded outside the viewport so a small pan shows no gap.
PREFETCH_MARGIN_TILES = 1

DRAG_THRESHOLD_PX = 5

#: Pointer-move coalescing for the live Ascendant readout (SPEC-MAP-002 §4.5).
HOVER_THROTTLE_MS = 60
#: One-shot pin landing animation.
PULSE_MS = 420
PULSE_START_PX = 10.0
PULSE_END_PX = 34.0

#: Minimum band width, in degrees of longitude, worth putting a name inside.
#: Bands pinch to a fraction of a degree approaching the polar circle; a name in
#: a sliver lands on its neighbours and reads as a mislabel.
BAND_LABEL_MIN_WIDTH_DEG = 8.0


def _polygon_centroid(coords) -> Tuple[float, float]:
    """A (lat, lon) inside a band, for its label.

    Deliberately the mean of the vertices rather than the true area centroid:
    an Ascendant band is a curved sliver, and its area centroid can fall
    OUTSIDE it where the curve bows. The vertex mean of a band built as
    left-edge-up then right-edge-down always lands between the two edges.
    """
    if not coords:
        return 0.0, 0.0
    lat = sum(c[0] for c in coords) / len(coords)
    lon = sum(c[1] for c in coords) / len(coords)
    return lat, lon


def _is_light_theme() -> bool:
    """Theme polarity, resolved live (never cached — SPEC-THM-001)."""
    try:
        from ui.qt_theme import is_light_theme
        return bool(is_light_theme())
    except Exception:
        return False


#: Every live tile thread, so no exit path can leave one running.
#: A running QThread that reaches either ~QObject or Python's interpreter
#: finalization aborts the process — the first fix attempt relied on the
#: widget's `destroyed` signal, which at interpreter teardown fires too late
#: (or not at all) and still dumped core with the worker mid-`handle_batch`.
_live_threads = []
_live_lock = _threading.Lock()
_atexit_registered = False


def _register_tile_thread(thread, worker):
    global _atexit_registered
    with _live_lock:
        _live_threads.append((thread, worker))
        if not _atexit_registered:
            _atexit_registered = True
            _atexit.register(_stop_all_tile_threads)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(_stop_all_tile_threads)


def _stop_all_tile_threads():
    """Stop every registered tile thread. Runs at app quit and at exit."""
    with _live_lock:
        pending = list(_live_threads)
        _live_threads.clear()
    for thread, worker in pending:
        _stop_tile_thread(thread, worker)


def _stop_tile_thread(thread, worker):
    """Quit a tile thread and wait for it. Idempotent; never raises.

    Deliberately module-level and taking its targets as arguments: some callers
    run while the owning widget is being destroyed, when touching `self` is
    unsafe.
    """
    with _live_lock:
        entry = (thread, worker)
        if entry in _live_threads:
            _live_threads.remove(entry)
    try:
        if worker is not None:
            worker.stop()
    except Exception:
        pass
    try:
        if thread is not None and thread.isRunning():
            thread.quit()
            if not thread.wait(3000):
                thread.terminate()
                thread.wait(500)
    except Exception:
        pass


def _background_color() -> QColor:
    """Ocean/background brush from the theme (Rule 20; was hardcoded #b3d1ff)."""
    try:
        from ui.qt_theme import get_theme_colors
        theme = get_theme_colors()
        return QColor(theme["secondary_dark"] if not _is_light_theme()
                      else theme["secondary_light"])
    except Exception:
        return QColor("#0d1b2a")


class OfflineMapWidget(QGraphicsView):
    """Interactive map over cached OpenStreetMap tiles.

    Signals:
        location_clicked(lat, lon): the user clicked a point.
        location_changed(lat, lon): the marker moved.
        zoom_changed(int):          the rendered tile level changed.
        detent_reached():           wheel zoom hit the offline boundary; the
                                    host may show a quiet inline hint.
    """

    location_clicked = Signal(float, float)
    location_changed = Signal(float, float)
    zoom_changed = Signal(int)
    detent_reached = Signal()
    #: Throttled pointer position in lat/lon (SPEC-MAP-002 §4.5). Emitted from a
    #: timer, never straight from mouseMoveEvent — a probe per pointer event
    #: competes with tile decode for the same frame.
    hovered = Signal(float, float)
    #: The pointer left the map; hosts revert their readout to the selection.
    hover_left = Signal()

    #: Internal: view -> worker. Queued because the worker lives in a QThread.
    #: `object` (not `list`) so the tile-key tuples cross untouched by Qt's
    #: QVariantList marshalling.
    _request_batch = Signal(int, object, bool)

    def __init__(self, db_path: str = None, parent=None, allow_network: bool = True,
                 dark_tiles: Optional[bool] = None):
        """
        Args:
            dark_tiles: None (default) follows the app theme live. Pass True or
                False to PIN the palette — offscreen CLI renderers do that so
                their PNG output is deterministic instead of depending on
                whatever theme the user happens to have selected.
        """
        super().__init__(parent)

        self.db_path = db_path or DEFAULT_DB_PATH
        self._dark_override = dark_tiles

        # --- map state ---------------------------------------------------
        self._zoom = 3.0            # float, authoritative
        self._zoom_target = 3.0
        self._tile_level = 3
        self._detent = ZoomDetent(SOFT_MAX_ZOOM, HARD_MAX_ZOOM)
        self._clock = QElapsedTimer()
        self._clock.start()

        self.center_lat = 25.0
        self.center_lon = 0.0
        self._centered_once = False

        self.marker_lat: Optional[float] = None
        self.marker_lon: Optional[float] = None
        self.marker_item: Optional[QGraphicsItem] = None
        self.marker_label_item: Optional[QGraphicsItem] = None
        self._marker_text = ""
        self._pulse_item: Optional[QGraphicsItem] = None
        self._pulse_anim: Optional[QVariantAnimation] = None

        self.overlay_items: list = []
        self._overlay_data: list = []

        # SPEC-MAP-002 INV-3: the Ascendant layer is its OWN list. The Eclipse
        # panel drives this same widget and calls clear_overlays() before every
        # zone draw; sharing one list would mean whichever panel drew last
        # silently erased the other.
        self.ascendant_items: list = []
        self._band_data: list = []
        self._band_labels: dict = {}
        self._graticule_item: Optional[QGraphicsItem] = None
        self._graticule_step: Optional[float] = None
        self._show_graticule = False

        self._dragging = False
        self._did_drag = False
        self._last_mouse_pos = QPointF()
        self._drag_start_pos = QPointF()

        self._tiles = {}            # (z,x,y) -> QGraphicsPixmapItem
        self._pending = set()       # (z,x,y) requested, not yet answered
        self._wanted = set()        # (z,x,y) still relevant to the viewport
        self._gen = 0
        self._dark = (not _is_light_theme() if dark_tiles is None
                      else bool(dark_tiles))
        self._anim_under_mouse = False
        self._alive = True
        self._cached_max = SOFT_MAX_ZOOM   # replaced by the worker's probe
        self._stale_palette = set()
        self._disconnected = False

        self._setup_view()
        self._start_worker(allow_network)

        # Debounce timer for viewport-driven requests.
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(REQUEST_DEBOUNCE_MS)
        self._request_timer.timeout.connect(self._request_visible)

        self._repalette_timer = QTimer(self)
        self._repalette_timer.setSingleShot(True)
        self._repalette_timer.setInterval(120)
        self._repalette_timer.timeout.connect(self._repalette_stale)

        # Hover readout throttle (§4.5). mouseMoveEvent only records; this
        # fires at most every HOVER_THROTTLE_MS and does the emitting.
        self._hover_pos: Optional[Tuple[float, float]] = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_THROTTLE_MS)
        self._hover_timer.timeout.connect(self._emit_hover)
        self.setMouseTracking(True)

        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setDuration(ZOOM_ANIM_MS)
        self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom_anim.valueChanged.connect(self._on_zoom_anim)

        self._prefetch_backdrop()
        self._apply_transform()
        self._schedule_request()

    # =====================================================================
    # Setup
    # =====================================================================

    def _setup_view(self):
        # NOTE: `self.scene` deliberately shadows QGraphicsView.scene() — this
        # is pre-existing public surface (callers do map_widget.scene.addItem).
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.setSceneRect(0, 0, WORLD_UNITS, WORLD_UNITS)

        self.setRenderHint(self.renderHints().SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # The scene is enormous (2^11 * 256 units square) and its contents are
        # a handful of items; a BSP index costs more than it saves.
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)

        self.setBackgroundBrush(QBrush(_background_color()))

    def _start_worker(self, allow_network: bool):
        # The QThread is deliberately UNPARENTED. Parenting it to the widget
        # made Qt delete it inside ~QWidget while it was still running, which
        # aborts the process ("QThread: Destroyed while thread 'map-tiles' is
        # still running") — it dumped core on every test teardown. Instead the
        # thread is stopped from `destroyed`, which fires at the top of
        # ~QObject, before anything is deleted.
        thread = QThread()
        thread.setObjectName("map-tiles")
        worker = TileWorker(self.db_path, allow_network=allow_network)
        worker.moveToThread(thread)
        self._request_batch.connect(worker.handle_batch)
        worker.tile_ready.connect(self._on_tile_ready)
        worker.tile_failed.connect(self._on_tile_failed)
        worker.cached_max_known.connect(self._on_cached_max_known)
        thread.start()

        self._thread = thread
        self._worker = worker
        # Registry + atexit + aboutToQuit: covers explicit close, app quit, and
        # a script/test that just falls off the end.
        _register_tile_thread(thread, worker)
        self.destroyed.connect(lambda *_: _stop_tile_thread(thread, worker))

    # =====================================================================
    # Zoom (SPEC-MAP-001 §4.1 / §4.2)
    # =====================================================================

    def _min_zoom(self) -> float:
        """Zoom at which the world exactly fills the viewport.

        Below this the map would letterbox inside its own background — the
        wide pale border visible in the pre-SPEC-MAP-001 screenshots.
        """
        vp = self.viewport()
        side = max(vp.width(), vp.height(), 1)
        return max(float(MIN_TILE_ZOOM), math.log2(side / TILE_SIZE))

    def _ceiling(self) -> float:
        return self._detent.ceiling

    def _apply_transform(self):
        """Set the view transform from the authoritative float zoom."""
        scale = 2.0 ** (self._zoom - Z_REF)
        self.resetTransform()
        self.scale(scale, scale)

    def _apply_zoom(self, new_zoom: float, under_mouse: bool):
        """Move to `new_zoom`, keeping the anchor point fixed."""
        if abs(new_zoom - self._zoom) < 1e-9:
            return
        factor = 2.0 ** (new_zoom - self._zoom)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse if under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(factor, factor)
        self._zoom = new_zoom

    def _on_zoom_anim(self, value):
        self._apply_zoom(float(value), under_mouse=self._anim_under_mouse)
        self._schedule_request()

    def _zoom_to(self, target: float, under_mouse: bool = True,
                 animate: bool = True):
        target = max(self._min_zoom(), min(self._ceiling(), target))
        if abs(target - self._zoom_target) < 1e-9:
            return
        self._zoom_target = target
        self._anim_under_mouse = under_mouse

        if animate:
            self._zoom_anim.stop()
            self._zoom_anim.setStartValue(float(self._zoom))
            self._zoom_anim.setEndValue(float(target))
            self._zoom_anim.start()
        else:
            self._zoom_anim.stop()
            self._apply_zoom(target, under_mouse)

        # Request the DESTINATION level immediately rather than waiting for the
        # animation, so tiles are already arriving when it lands.
        self._update_tile_level()

    def _update_tile_level(self):
        level = int(round(self._zoom_target))
        level = max(MIN_TILE_ZOOM, min(int(self._ceiling()), level))
        if level != self._tile_level:
            self._tile_level = level
            self.zoom_changed.emit(level)
        # Graticule density follows the zoom, but only rebuilds when the step
        # actually changes — not on every frame of the zoom animation.
        self._update_graticule()
        self._schedule_request()

    def wheelEvent(self, event: QWheelEvent):
        """Continuous zoom with a detent at the offline boundary.

        One notch (120 units) multiplies the scale by ~1.41, so two notches
        make exactly one tile level. The old code turned ANY non-zero delta
        into a full level with no accumulator, which is why a single trackpad
        gesture crossed several levels at once (RC-4).
        """
        fast = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        now_ms = float(self._clock.elapsed())
        delta = wheel_zoom_delta(event.angleDelta().y(), fast=fast)
        if delta == 0.0:
            # Horizontal / pixel-only scroll: no zoom, but the wheel IS active,
            # so it must count against the detent's idle gap.
            self._detent.note_input(now_ms)
            return

        raw_target = self._zoom_target + delta
        was_at_ceiling = self._zoom_target >= self._detent.ceiling - 1e-9

        allowed = self._detent.clamp(raw_target, now_ms, deliberate=fast)

        if (delta > 0 and allowed < raw_target - 1e-9
                and was_at_ceiling and self._detent.at_detent()):
            self.detent_reached.emit()

        self._zoom_to(allowed, under_mouse=True)
        event.accept()

    # --- public zoom API (unchanged signatures) --------------------------

    def set_zoom(self, zoom):
        """Set the zoom level. Accepts int or float; programmatic, so it
        bypasses the wheel detent (an explicit call is deliberate)."""
        target = float(zoom)
        if target > self._detent.ceiling:
            self._detent.unlock()
        self._zoom_to(target, under_mouse=False, animate=False)

    def get_zoom(self) -> int:
        """Current tile level (integer, for display and for callers that
        predate fractional zoom)."""
        return self._tile_level

    def get_zoom_exact(self) -> float:
        return self._zoom

    def zoom_in(self):
        """One whole level; deliberate, so it crosses the detent."""
        self._detent.unlock()
        self._zoom_to(self._zoom_target + 1.0, under_mouse=False)

    def zoom_out(self):
        self._zoom_to(self._zoom_target - 1.0, under_mouse=False)

    # =====================================================================
    # Tiles
    # =====================================================================

    def _visible_scene_rect(self, margin_tiles: int = 0) -> QRectF:
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        if margin_tiles:
            span = TILE_SIZE * (2 ** (Z_REF - self._tile_level)) * margin_tiles
            rect = rect.adjusted(-span, -span, span, span)
        return rect

    def _keys_for(self, level: int, rect: QRectF) -> List[Tuple[int, int, int]]:
        n = 2 ** level
        span = TILE_SIZE * (2 ** (Z_REF - level))
        min_x = max(0, int(math.floor(rect.left() / span)))
        max_x = min(n - 1, int(math.floor(rect.right() / span)))
        min_y = max(0, int(math.floor(rect.top() / span)))
        max_y = min(n - 1, int(math.floor(rect.bottom() / span)))
        return [(level, x, y)
                for x in range(min_x, max_x + 1)
                for y in range(min_y, max_y + 1)]

    def _schedule_request(self):
        if not self._request_timer.isActive():
            self._request_timer.start()

    @Slot()
    def _request_visible(self):
        rect = self._visible_scene_rect(PREFETCH_MARGIN_TILES)
        keys = self._keys_for(self._tile_level, rect)
        self._wanted = set(keys)

        need = [k for k in keys if k not in self._tiles and k not in self._pending]
        if need:
            self._gen += 1
            self._pending.update(need)
            self._request_batch.emit(self._gen, need, self._dark)

        self._cull(rect)

    def _prefetch_backdrop(self):
        """Load z0..BASE_KEEP_ZOOM up front (21 tiles).

        These stay resident for the life of the widget, which is what makes
        INV-2 structural: there is always cover for every point on Earth, so
        no zoom or pan can produce a blank frame.
        """
        keys = []
        for z in range(0, BASE_KEEP_ZOOM + 1):
            n = 2 ** z
            keys.extend((z, x, y) for x in range(n) for y in range(n))
        self._gen += 1
        self._pending.update(keys)
        self._request_batch.emit(self._gen, keys, self._dark)

    def _scene_alive(self) -> bool:
        """Whether it is still safe to touch the scene.

        Tile results arrive through a QUEUED signal, so one can always land
        after the widget has been torn down — Qt has already deleted the C++
        QGraphicsScene while the Python wrapper still exists, and adding an
        item then raises `RuntimeError: Internal C++ object already deleted`.
        Reproduced by a map dialog closing mid-load.
        """
        if not self._alive:
            return False
        try:
            import shiboken6
            return shiboken6.isValid(self.scene)
        except Exception:
            return True

    @Slot(int)
    def _on_cached_max_known(self, value: int):
        """The worker probed the bundled DB for us (INV-1)."""
        self._cached_max = int(value)

    @Slot(int, int, int, int, QImage, bool)
    def _on_tile_ready(self, gen: int, z: int, x: int, y: int, image: QImage,
                       dark: bool):
        key = (z, x, y)
        self._pending.discard(key)
        if not self._scene_alive():
            return

        if bool(dark) != self._dark:
            # The theme changed while this tile was in flight (a network tile
            # can be seconds behind). Install it anyway — a correct-ish tile
            # beats a hole — but queue a re-render, or it would keep the old
            # palette forever since _reload_all_tiles only sees resident items.
            self._stale_palette.add(key)
            self._schedule_repalette()

        from ui.qt_theme import desat_image
        try:
            existing = self._tiles.get(key)
            if existing is not None:
                # Theme swap: replace the pixmap in place so nothing ever blanks.
                image = desat_image(image, fast=True)  # opaque map tile
                existing.setPixmap(QPixmap.fromImage(image))
                return

            if z > BASE_KEEP_ZOOM and key not in self._wanted:
                return  # viewport moved on while this was in flight

            left, top, span = tile_scene_rect(z, x, y)
            image = desat_image(image, fast=True)  # opaque map tile
            item = QGraphicsPixmapItem(QPixmap.fromImage(image))
            item.setPos(left, top)
            item.setScale(span / TILE_SIZE)
            item.setZValue(z)             # finer levels paint over coarser
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene.addItem(item)
            self._tiles[key] = item
        except RuntimeError:
            # Torn down between the guard and here. Nothing to salvage.
            self._alive = False

    @Slot(int, int, int, int)
    def _on_tile_failed(self, gen: int, z: int, x: int, y: int):
        self._pending.discard((z, x, y))

    def _cull(self, rect: QRectF):
        """Drop tiles that are neither backdrop nor near the viewport.

        INV-2: the z<=BASE_KEEP_ZOOM layer is never culled, so every point in
        the scene keeps at least one cover at all times.
        """
        keep_levels = {self._tile_level - d for d in range(BACKDROP_LEVELS + 1)}
        for key in list(self._tiles):
            z, x, y = key
            if z <= BASE_KEEP_ZOOM:
                continue
            if z not in keep_levels:
                self._remove_tile(key)
                continue
            left, top, span = tile_scene_rect(z, x, y)
            if not rect.intersects(QRectF(left, top, span, span)):
                self._remove_tile(key)

    def _remove_tile(self, key):
        item = self._tiles.pop(key, None)
        if item is not None:
            self.scene.removeItem(item)
            del item  # Rule 18: drop the Python ref after Qt hands ownership back

    def _schedule_repalette(self):
        """Coalesce re-renders of tiles that landed in the wrong palette."""
        if self._repalette_timer.isActive():
            return
        self._repalette_timer.start()

    @Slot()
    def _repalette_stale(self):
        keys = [k for k in self._stale_palette if k in self._tiles]
        self._stale_palette.clear()
        keys = [k for k in keys if k not in self._pending]
        if not keys:
            return
        self._gen += 1
        self._pending.update(keys)
        self._request_batch.emit(self._gen, keys, self._dark)

    def _reload_all_tiles(self):
        """Re-request every resident tile (theme change). No blank: items stay
        in the scene and their pixmaps are swapped on arrival."""
        keys = [k for k in self._tiles if k not in self._pending]
        if not keys:
            return
        self._gen += 1
        self._pending.update(keys)
        self._request_batch.emit(self._gen, keys, self._dark)

    def wait_for_tiles(self, timeout_ms: int = 8000) -> bool:
        """Block until the map is QUIESCENT: nothing pending, nothing scheduled.

        OFFSCREEN RENDERING ONLY (the eclipse CLI grabs the widget immediately
        after building it). Never call this from the interactive path — the
        whole point of SPEC-MAP-001 is that the GUI thread does not wait.

        Waiting on `_pending` alone is not enough, and the difference is not
        theoretical: requests are debounced by 40 ms, so at the moment this is
        called `_pending` is often still empty. The old version saw an empty set,
        skipped its loop, and the debounce timer then fired inside its final
        processEvents() — returning False with a batch of 40 tiles freshly
        queued, or worse, letting the CLI grab a half-drawn map. So flush the
        scheduled work first, then require two consecutive quiet observations.
        """
        from PySide6.QtWidgets import QApplication

        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < timeout_ms:
            # Bring forward anything the debouncers are sitting on.
            if self._request_timer.isActive():
                self._request_timer.stop()
                self._request_visible()
            if self._repalette_timer.isActive():
                self._repalette_timer.stop()
                self._repalette_stale()

            QApplication.processEvents()

            if (not self._pending
                    and not self._request_timer.isActive()
                    and not self._repalette_timer.isActive()):
                # Confirm: one more pump must not surface new work.
                QApplication.processEvents()
                if (not self._pending
                        and not self._request_timer.isActive()
                        and not self._repalette_timer.isActive()):
                    return True
                continue

            QThread.msleep(5)

        return not self._pending

    # =====================================================================
    # Position, marker
    # =====================================================================

    def set_position(self, lat: float, lon: float):
        self.center_lat = lat
        self.center_lon = lon
        self._center_on_position()

    def _center_on_position(self):
        sx, sy = lat_lon_to_scene(self.center_lat, self.center_lon)
        self.centerOn(sx, sy)
        self._schedule_request()

    def set_marker(self, lat: float, lon: float, label: str = None,
                   pulse: bool = True):
        """Place the pin. `label` None keeps the current text, "" clears it."""
        moved = (lat, lon) != (self.marker_lat, self.marker_lon)
        self.marker_lat = lat
        self.marker_lon = lon
        if label is not None:
            self.set_marker_label(label)
        self._update_marker()
        if pulse and moved:
            self._play_pulse()
        self.location_changed.emit(lat, lon)

    def set_marker_label(self, text: str):
        """Name shown above the pin. Rebuilt, not edited: the halo offset is
        derived from the text metrics, so a changed string needs a new item."""
        text = text or ""
        if text == self._marker_text and self.marker_label_item is not None:
            return
        self._marker_text = text
        self._drop_item("marker_label_item")
        if not text or not self._scene_alive():
            return
        from apps.widgets.map_chrome import build_place_label
        item = build_place_label(text)
        self.scene.addItem(item)
        self.marker_label_item = item
        self._position_marker_items()

    def clear_marker(self):
        self.marker_lat = None
        self.marker_lon = None
        self._marker_text = ""
        self._stop_pulse()
        for attr in ("marker_item", "marker_label_item"):
            self._drop_item(attr)

    def _drop_item(self, attr: str):
        """Remove a single owned scene item, tolerating a dead scene."""
        item = getattr(self, attr, None)
        if item is None:
            return
        setattr(self, attr, None)
        if self._scene_alive():
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass

    def _update_marker(self):
        if self.marker_lat is None or self.marker_lon is None:
            return
        if not self._scene_alive():
            return

        if self.marker_item is None:
            from apps.widgets.map_chrome import build_pin_item
            item = build_pin_item()
            self.scene.addItem(item)
            self.marker_item = item

        self._position_marker_items()

    def _position_marker_items(self):
        if self.marker_lat is None or self.marker_lon is None:
            return
        sx, sy = lat_lon_to_scene(self.marker_lat, self.marker_lon)
        for item in (self.marker_item, self.marker_label_item, self._pulse_item):
            if item is not None:
                item.setPos(sx, sy)

    # --- landing pulse ---------------------------------------------------

    def _play_pulse(self):
        """One expanding ring, 420 ms. Restarted, never stacked.

        A pulse per click would otherwise accumulate animations and items on a
        user who clicks around the map, each still driving repaints.
        """
        if not self._scene_alive():
            return
        self._stop_pulse()

        from apps.widgets.map_chrome import build_pulse_item
        item = build_pulse_item()
        self.scene.addItem(item)
        self._pulse_item = item
        self._position_marker_items()

        anim = QVariantAnimation(self)
        anim.setDuration(PULSE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_pulse)
        anim.finished.connect(self._stop_pulse)
        self._pulse_anim = anim
        anim.start()

    def _on_pulse(self, t):
        item = self._pulse_item
        if item is None or not self._scene_alive():
            return
        try:
            r = PULSE_START_PX + (PULSE_END_PX - PULSE_START_PX) * float(t)
            item.setRect(QRectF(-r / 2, -r / 2, r, r))
            item.setOpacity(max(0.0, 0.55 * (1.0 - float(t))))
        except RuntimeError:
            self._pulse_item = None

    def _stop_pulse(self):
        anim = self._pulse_anim
        self._pulse_anim = None
        if anim is not None:
            try:
                anim.stop()
                anim.valueChanged.disconnect()
                anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._drop_item("_pulse_item")

    # =====================================================================
    # Ascendant layer (SPEC-MAP-002 §4.3) — separate from overlays, INV-3
    # =====================================================================

    def set_ascendant_bands(self, bands, labels=None):
        """Draw Ascendant sign bands.

        `bands` is a sequence of `(sign_index, coords)` or, preferably,
        `(sign_index, coords, left, right)` as produced by
        `core.ascendant_field.compute_bands` — `coords` the closed polygon,
        `left`/`right` the two open boundary polylines. `labels` maps sign index
        -> name; the widget does not know the zodiac mode and must never guess a
        name.

        A sign may appear MORE THAN ONCE. Above the polar circle a sign can rise
        in two separate places or not at all, so the twelve signs do not map to
        twelve polygons and this method must not assume they do.

        Each polygon is drawn three times, at -360/0/+360 degrees of longitude.
        The bands tile the world, so one of the copies always covers whatever
        part of the wrap the viewport is showing. This is cheaper and far more
        robust than splitting polygons at the dateline — and it is the only
        approach that survives a boundary curve that crosses the antimeridian as
        LATITUDE varies, which any split-and-classify scheme gets wrong.

        Fill and boundary are separate items: the fill carries no pen, and only
        `left`/`right` are stroked, so the latitude where the data stops is not
        drawn as though a sign changed there.
        """
        self.clear_ascendant()
        if not bands or not self._scene_alive():
            return

        from apps.widgets.map_chrome import (
            build_band_item, build_band_edge_item, build_band_label,
        )

        self._band_data = [
            (int(b[0]), list(b[1]),
             list(b[2]) if len(b) > 2 else [],
             list(b[3]) if len(b) > 3 else [])
            for b in bands
        ]
        self._band_labels = dict(labels or {})

        # A sign split above the polar circle owns several polygons, and naming
        # each one printed the same name twice a few hundred pixels apart, which
        # reads as two different bands. Name only the largest piece per sign.
        biggest: dict = {}
        for i, (sign_index, coords, _l, _r) in enumerate(self._band_data):
            score = self._band_extent(coords)
            if score > biggest.get(sign_index, (-1.0, -1))[0]:
                biggest[sign_index] = (score, i)
        label_at = {i for _score, i in biggest.values()}

        for i, (sign_index, coords, left, right) in enumerate(self._band_data):
            if len(coords) < 3:
                continue
            for shift in (-360.0, 0.0, 360.0):
                pts = [lat_lon_to_scene(lat, lon + shift) for lat, lon in coords]
                item = build_band_item(pts, sign_index)
                self.scene.addItem(item)
                self.ascendant_items.append(item)

                for edge in (left, right):
                    if len(edge) < 2:
                        continue
                    epts = [lat_lon_to_scene(lat, lon + shift)
                            for lat, lon in edge]
                    eitem = build_band_edge_item(epts, sign_index)
                    self.scene.addItem(eitem)
                    self.ascendant_items.append(eitem)

            name = (labels or {}).get(sign_index)
            if name and i in label_at and self._band_is_labelable(coords):
                lat_c, lon_c = _polygon_centroid(coords)
                for shift in (-360.0, 0.0, 360.0):
                    label = build_band_label(name, sign_index)
                    sx, sy = lat_lon_to_scene(lat_c, lon_c + shift)
                    label.setPos(sx, sy)
                    self.scene.addItem(label)
                    self.ascendant_items.append(label)

    @staticmethod
    def _band_extent(coords) -> float:
        """How much map a polygon covers, for picking which piece gets the name.

        Bounding-box area in degrees, not a true polygon area: the pieces being
        compared are strips, so the box ranks them the same way and costs nothing.
        """
        if not coords:
            return 0.0
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        return (max(lats) - min(lats)) * (max(lons) - min(lons))

    @staticmethod
    def _band_is_labelable(coords) -> bool:
        """Is this polygon wide enough to be worth naming?

        A sign pinching out near the polar circle can be a fraction of a degree
        across. Naming a sliver puts the text over its neighbours and reads as a
        mislabel, so slivers are drawn but not named. The threshold is in degrees
        of longitude because that is what the band's width actually is.
        """
        if not coords:
            return False
        lons = [c[1] for c in coords]
        return (max(lons) - min(lons)) >= BAND_LABEL_MIN_WIDTH_DEG

    def clear_ascendant(self):
        """Remove the Ascendant layer. Never touches `overlay_items` (INV-3)."""
        self._band_data = []
        self._band_labels = {}
        if not self._scene_alive():
            self.ascendant_items = []
            return
        for item in self.ascendant_items:
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self.ascendant_items = []

    def has_ascendant_bands(self) -> bool:
        return bool(self.ascendant_items)

    # =====================================================================
    # Graticule (§4.6)
    # =====================================================================

    def set_graticule_visible(self, visible: bool):
        self._show_graticule = bool(visible)
        self._update_graticule(force=True)

    def _update_graticule(self, force: bool = False):
        if not self._scene_alive():
            return
        from apps.widgets.map_chrome import (
            build_graticule_item, graticule_step_for_zoom,
        )

        if not self._show_graticule:
            self._drop_item("_graticule_item")
            self._graticule_step = None
            return

        step = graticule_step_for_zoom(self._zoom)
        if not force and step == self._graticule_step:
            return
        self._drop_item("_graticule_item")
        self._graticule_step = step
        item = build_graticule_item(step, lat_lon_to_scene)
        self.scene.addItem(item)
        self._graticule_item = item

    # =====================================================================
    # Overlays (eclipse zones) — zoom-invariant in the fixed frame
    # =====================================================================

    def add_overlay_polygon(self, coords: list, color: str = "#FF000040",
                            border_color: str = "#FF0000", border_width: float = 2.0,
                            persistent: bool = True):
        if len(coords) < 3:
            return None
        if persistent:
            self._overlay_data.append({
                'type': 'polygon', 'coords': list(coords),
                'params': {'color': color, 'border_color': border_color,
                           'border_width': border_width},
            })

        points = [QPointF(*lat_lon_to_scene(lat, lon)) for lat, lon in coords]
        item = QGraphicsPolygonItem(QPolygonF(points))
        item.setBrush(QBrush(QColor(color)))
        pen = QPen(QColor(border_color), border_width)
        pen.setCosmetic(True)   # stay N device px at every zoom
        item.setPen(pen)
        item.setZValue(500)
        self.scene.addItem(item)
        self.overlay_items.append(item)
        return item

    def add_overlay_line(self, coords: list, color: str = "#FF0000",
                         width: float = 2.0, persistent: bool = True):
        if len(coords) < 2:
            return None
        if persistent:
            self._overlay_data.append({
                'type': 'line', 'coords': list(coords),
                'params': {'color': color, 'width': width},
            })

        path = QPainterPath()
        for i, (lat, lon) in enumerate(coords):
            sx, sy = lat_lon_to_scene(lat, lon)
            path.moveTo(sx, sy) if i == 0 else path.lineTo(sx, sy)

        item = QGraphicsPathItem(path)
        pen = QPen(QColor(color), width)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setZValue(500)
        self.scene.addItem(item)
        self.overlay_items.append(item)
        return item

    def clear_overlays(self):
        self._clear_overlay_items()
        self._overlay_data.clear()

    def _clear_overlay_items(self):
        for item in self.overlay_items:
            self.scene.removeItem(item)
        self.overlay_items.clear()

    def _update_overlays(self):
        """No-op since SPEC-MAP-001 D-14.

        Overlays live in the fixed reference frame, so a zoom change cannot
        invalidate them. Kept because `eclipse_panel.py` still wires
        zoom_changed to a redraw; that path is now free instead of quadratic.
        """
        return

    # =====================================================================
    # Theme (INV-6)
    # =====================================================================

    def set_dark_tiles(self, dark: bool):
        if bool(dark) == self._dark:
            return
        self._dark = bool(dark)
        self._reload_all_tiles()

    def clear_icon_cache(self):
        """Re-request every resident tile so it re-desaturates at the current UI
        saturation (SPEC-SAT-001). Tiles are keyed only by (z,x,y) with the
        saturation baked in at fetch, and set_dark_tiles() early-returns when the
        light/dark mode is unchanged — so a saturation-only change would leave
        resident tiles stale (Codex review finding). This is reached by the
        _on_saturation_changed findChildren sweep; desat is re-applied in
        _on_tile_ready on arrival."""
        self._reload_all_tiles()

    def refresh_theme(self):
        """Re-apply background and re-render every resident tile.

        A pinned palette (`dark_tiles=` at construction) is left alone: a CLI
        render must not change because the user switched themes.
        """
        self.setBackgroundBrush(QBrush(_background_color()))
        if self._dark_override is None:
            self.set_dark_tiles(not _is_light_theme())

        # Chrome bakes theme colours into brushes and pens at build time, so a
        # live switch has to REBUILD it. Nothing here is expensive: one pin,
        # one label, one graticule path, and the bands are redrawn from the
        # already-computed geometry without re-probing the engine.
        if self._scene_alive():
            label, lat, lon = self._marker_text, self.marker_lat, self.marker_lon
            self._drop_item("marker_item")
            self._drop_item("marker_label_item")
            self._marker_text = ""
            if lat is not None and lon is not None:
                self._update_marker()
                self.set_marker_label(label)

            if self._band_data:
                bands = list(self._band_data)
                labels = dict(self._band_labels)
                self.set_ascendant_bands(bands, labels)

            self._update_graticule(force=True)

        self.viewport().update()

    # =====================================================================
    # Mouse / lifecycle
    # =====================================================================

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._did_drag = False
            self._drag_start_pos = event.position()
            self._last_mouse_pos = event.position()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.position() - self._last_mouse_pos
            self._last_mouse_pos = event.position()

            total = event.position() - self._drag_start_pos
            if abs(total.x()) > DRAG_THRESHOLD_PX or abs(total.y()) > DRAG_THRESHOLD_PX:
                self._did_drag = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

            if self._did_drag:
                self.horizontalScrollBar().setValue(
                    int(self.horizontalScrollBar().value() - delta.x()))
                self.verticalScrollBar().setValue(
                    int(self.verticalScrollBar().value() - delta.y()))
                # Debounced: one batch per gesture, not one per move event.
                self._schedule_request()
        else:
            # Record only. The probe happens on the throttle timer (§4.5): at
            # ~1 ms per Ascendant probe plus a timezone lookup, doing this
            # inline would spend a whole frame budget per pointer event.
            scene_pos = self.mapToScene(event.position().toPoint())
            lat, lon = scene_to_lat_lon(scene_pos.x(), scene_pos.y())
            if -85.0 <= lat <= 85.0:
                self._hover_pos = (lat, max(-180.0, min(180.0, lon)))
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        super().mouseMoveEvent(event)

    def _emit_hover(self):
        if self._hover_pos is None or not self._alive:
            return
        lat, lon = self._hover_pos
        self.hovered.emit(lat, lon)

    def leaveEvent(self, event):
        self._hover_pos = None
        self._hover_timer.stop()
        self.hover_left.emit()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

            if not self._did_drag:
                scene_pos = self.mapToScene(self._drag_start_pos.toPoint())
                lat, lon = scene_to_lat_lon(scene_pos.x(), scene_pos.y())
                lat = max(-85.0, min(85.0, lat))
                lon = max(-180.0, min(180.0, lon))
                self.set_marker(lat, lon)
                self.location_clicked.emit(lat, lon)

            self._did_drag = False
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        floor = self._min_zoom()
        if self._zoom_target < floor:
            self._zoom_target = floor
            self._apply_zoom(floor, under_mouse=False)
            self._update_tile_level()
        self._schedule_request()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._centered_once:
            self._centered_once = True
            floor = self._min_zoom()
            if self._zoom_target < floor:
                self._zoom_target = floor
                self._apply_zoom(floor, under_mouse=False)
                self._update_tile_level()
            self._center_on_position()
        self._schedule_request()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        """Stop the tile thread. Safe to call more than once."""
        self._alive = False
        # The pulse animation and the hover throttle both call back into the
        # scene. Left running they would fire during teardown, which is the
        # same class of crash the tile-thread registry exists to prevent.
        for timer_attr in ("_hover_timer",):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
        try:
            self._stop_pulse()
        except RuntimeError:
            pass
        worker = getattr(self, "_worker", None)
        # Disconnect first: a result already queued must not reach a scene that
        # is about to go away. Guarded by a flag because shutdown() is called
        # from several paths and a second bare disconnect() only warns.
        if worker is not None and not self._disconnected:
            self._disconnected = True
            for signal in (worker.tile_ready, worker.tile_failed,
                           worker.cached_max_known):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        thread = getattr(self, "_thread", None)
        if thread is None:
            return
        _stop_tile_thread(thread, worker)
        self._thread = None

    # =====================================================================
    # Online-zoom API (unchanged signatures)
    # =====================================================================

    def is_online_zoom(self) -> bool:
        return self._tile_level > self.get_cached_max_zoom()

    def is_online_enabled(self) -> bool:
        return True

    def get_max_zoom(self) -> int:
        return HARD_MAX_ZOOM

    def get_cached_max_zoom(self) -> int:
        """Highest locally cached level.

        Answered from the value the worker probed for us. Calling the worker's
        method directly here would run `sqlite3.connect` on the GUI thread and
        break INV-1 — a public getter is exactly the kind of innocuous-looking
        accessor that smuggles blocking I/O back in.
        """
        return self._cached_max


class OfflineMapPanel(QWidget):
    """Map plus zoom controls, coordinate readout and a capital quick-select.

    Retained for callers that want the whole assembly; the Edit Chart sub-tab
    embeds the bare OfflineMapWidget instead.
    """

    location_selected = Signal(float, float, str, str)

    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        control_bar = QHBoxLayout()
        control_bar.setSpacing(10)

        self.coord_label = QLabel("Click map to select location")
        self.coord_label.setStyleSheet("font-family: monospace; padding: 5px;")
        control_bar.addWidget(self.coord_label)
        control_bar.addStretch()

        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setFixedSize(30, 30)
        self.zoom_out_btn.setToolTip("Zoom out")
        control_bar.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("Zoom: 3")
        self.zoom_label.setMinimumWidth(60)
        control_bar.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedSize(30, 30)
        self.zoom_in_btn.setToolTip("Zoom in (past the offline limit if needed)")
        control_bar.addWidget(self.zoom_in_btn)

        self.capital_combo = QComboBox()
        self.capital_combo.setMinimumWidth(150)
        self.capital_combo.addItem("Quick Select Capital...")
        self._populate_capitals()
        control_bar.addWidget(self.capital_combo)

        layout.addLayout(control_bar)

        self.map_widget = OfflineMapWidget(self.db_path, self)
        layout.addWidget(self.map_widget, stretch=1)

    def _populate_capitals(self):
        try:
            from tools.capitals_data import WORLD_CAPITALS
            for capital in sorted(WORLD_CAPITALS.keys()):
                self.capital_combo.addItem(capital)
        except ImportError:
            pass

    def _connect_signals(self):
        self.map_widget.location_clicked.connect(self._on_location_clicked)
        self.map_widget.zoom_changed.connect(self._update_zoom_label)
        self.zoom_in_btn.clicked.connect(self.map_widget.zoom_in)
        self.zoom_out_btn.clicked.connect(self.map_widget.zoom_out)
        self.capital_combo.currentTextChanged.connect(self._on_capital_selected)

    def _on_location_clicked(self, lat: float, lon: float):
        self._show_coords(lat, lon)
        city, country = self._nearest_capital(lat, lon)
        self.location_selected.emit(lat, lon, city, country)

    def _show_coords(self, lat: float, lon: float):
        self.coord_label.setText(
            f"{abs(lat):.6f}° {'N' if lat >= 0 else 'S'}, "
            f"{abs(lon):.6f}° {'E' if lon >= 0 else 'W'}")

    @staticmethod
    def _nearest_capital(lat: float, lon: float) -> Tuple[str, str]:
        """Instant offline placeholder. No network: INV-1."""
        try:
            from tools.capitals_data import WORLD_CAPITALS
        except ImportError:
            return "", ""
        best, best_dist = None, float('inf')
        for name, data in WORLD_CAPITALS.items():
            d = (lat - data.get('lat', 0)) ** 2 + (lon - data.get('lon', 0)) ** 2
            if d < best_dist:
                best_dist, best = d, (name, data.get('country', ''))
        return best if best else ("", "")

    def _update_zoom_label(self, *_):
        self.zoom_label.setText(f"Zoom: {self.map_widget.get_zoom()}")

    def _on_capital_selected(self, capital_name: str):
        if capital_name == "Quick Select Capital..." or not capital_name:
            return
        try:
            from tools.capitals_data import WORLD_CAPITALS
        except ImportError:
            return
        data = WORLD_CAPITALS.get(capital_name)
        if not data:
            return
        lat, lon = data.get('lat', 0), data.get('lon', 0)
        self.map_widget.set_marker(lat, lon)
        self.map_widget.set_position(lat, lon)
        self.map_widget.set_zoom(SOFT_MAX_ZOOM)
        self._update_zoom_label()
        self._show_coords(lat, lon)
        self.location_selected.emit(lat, lon, capital_name, data.get('country', ''))

        self.capital_combo.blockSignals(True)
        self.capital_combo.setCurrentIndex(0)
        self.capital_combo.blockSignals(False)

    # --- public API ------------------------------------------------------

    def set_marker(self, lat: float, lon: float):
        self.map_widget.set_marker(lat, lon)
        self.map_widget.set_position(lat, lon)
        self._show_coords(lat, lon)

    def get_marker_position(self) -> Optional[Tuple[float, float]]:
        if self.map_widget.marker_lat is not None:
            return (self.map_widget.marker_lat, self.map_widget.marker_lon)
        return None
