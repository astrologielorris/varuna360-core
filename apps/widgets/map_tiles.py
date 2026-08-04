# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Tile engine for the offline map — SPEC-MAP-001 §4.3 / §4.4.

Everything in this module exists to keep tile I/O OFF the GUI thread
(SPEC-MAP-001 INV-1). The view layer (`offline_map_widget.py`) never touches
SQLite or the network; it emits a batch request and receives QImages back.

Layout
------
    OfflineMapWidget  --requested(gen, keys, dark)-->  TileWorker
      (GUI thread)                                     (QThread "map-tiles")
                                                         |
                                                         |  bundled DB  (read-only)
                                                         |  online DB   (user data dir)
                                                         |  ThreadPoolExecutor(4) -> OSM
                                                         v
    OfflineMapWidget  <--tile_ready(gen, z,x,y, QImage)--

QPixmap may only be constructed on the GUI thread, so the worker hands back
QImage (which is safe to build anywhere and is implicitly shared, so the
queued-signal hop does not copy the pixels).

Measured costs per tile on this cache (2026-07-26):
    SQLite lookup    0.034 ms      PNG decode      0.25 ms
    dark transform   0.113 ms      (pixel-wise would be 2.31 ms)
A 50-tile viewport is therefore ~20 ms of worker time and 0 ms of GUI time.
"""

import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

# --------------------------------------------------------------------------
# Constants (SPEC-MAP-001 §4.1, §4.2)
# --------------------------------------------------------------------------

TILE_SIZE = 256

MIN_TILE_ZOOM = 0
#: Highest level present in the bundled cache. Measured: the DB holds z0-z7 and
#: z7 is complete (16383/16384 tiles). Wheel zoom stops here (the detent).
SOFT_MAX_ZOOM = 7
#: Absolute ceiling, reachable only by a deliberate gesture. D-16: ~76 m/px,
#: whose ~0.04 arcmin longitude precision is already far below birth-time
#: uncertainty, so going deeper buys nothing an astrologer can use.
HARD_MAX_ZOOM = 11
#: The scene's fixed reference frame (SPEC-MAP-001 §3.1 / D-1).
Z_REF = HARD_MAX_ZOOM

#: Levels kept resident forever so the map is never blank (INV-2). z0-z2 is
#: 21 in-world tiles, roughly 5 MB of QPixmap.
BASE_KEEP_ZOOM = 2

#: A failed online fetch is not retried inside this window. Without it, one pan
#: gesture re-issued every failed 5 s-timeout fetch dozens of times (RC-2).
FAIL_TTL_SEC = 60.0

MAX_NET_WORKERS = 4
NET_TIMEOUT_SEC = 4.0
MAX_ONLINE_ROWS = 20000

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)"

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "map_tiles_cache.db",
)

TileKey = Tuple[int, int, int]  # (zoom, x, y)


# --------------------------------------------------------------------------
# Web Mercator (unchanged semantics — these are the historical helpers)
# --------------------------------------------------------------------------

def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Lat/lon -> integer tile indices, clamped to the world."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_to_lat_lon(x: float, y: float, zoom: int) -> Tuple[float, float]:
    """Fractional tile coords -> lat/lon at that point."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def lat_lon_to_pixel(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Lat/lon -> world pixel coords at `zoom`."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n * TILE_SIZE
    return x, y


def pixel_to_lat_lon(px: float, py: float, zoom: int) -> Tuple[float, float]:
    """World pixel coords at `zoom` -> lat/lon."""
    return tile_to_lat_lon(px / TILE_SIZE, py / TILE_SIZE, zoom)


def lat_lon_to_scene(lat: float, lon: float) -> Tuple[float, float]:
    """Lat/lon -> scene coords in the FIXED reference frame (SPEC-MAP-001 §3.1).

    This is the only conversion the view layer should use: scene coordinates
    never change with zoom, which is what makes overlays zoom-invariant and
    zoom itself a pure view transform.
    """
    return lat_lon_to_pixel(lat, lon, Z_REF)


def scene_to_lat_lon(sx: float, sy: float) -> Tuple[float, float]:
    """Scene coords in the fixed reference frame -> lat/lon."""
    return pixel_to_lat_lon(sx, sy, Z_REF)


def tile_scene_rect(z: int, x: int, y: int) -> Tuple[float, float, float]:
    """Where tile (z,x,y) sits in the reference frame: (left, top, size)."""
    span = TILE_SIZE * (2 ** (Z_REF - z))
    return x * span, y * span, span


# --------------------------------------------------------------------------
# Dark tiles (SPEC-MAP-001 §4.4 / D-7, D-17)
# --------------------------------------------------------------------------

#: CSS hue-rotate(180deg) matrix, applied to the INVERTED source. Inverting
#: alone turns OSM water brown; the hue rotation brings it back to blue.
_HUE180 = (
    (-0.574, 1.430, 0.144),
    (0.426, 0.430, 0.144),
    (0.426, 1.430, -0.856),
)

#: D-17: lift the result so minor roads and small labels do not crush to black.
DARK_GAMMA = 0.72

#: Memo of source ARGB -> dark ARGB. OSM tiles reuse a tiny palette, so this
#: saturates almost immediately and the transform becomes a dict lookup.
_dark_memo = {}
_dark_memo_lock = threading.Lock()

_GAMMA_LUT = [int(round(255.0 * ((v / 255.0) ** DARK_GAMMA))) for v in range(256)]


def dark_argb(argb: int, gamma: bool = True) -> int:
    """Convert one ARGB color to its dark-map equivalent.

    Set `gamma=False` for the raw invert+hue-rotate result (the T-4 oracle
    values are specified pre-gamma).
    """
    key = (argb, gamma)
    with _dark_memo_lock:
        hit = _dark_memo.get(key)
    if hit is not None:
        return hit

    a = (argb >> 24) & 0xFF
    inv = (255 - ((argb >> 16) & 0xFF),
           255 - ((argb >> 8) & 0xFF),
           255 - (argb & 0xFF))

    out = []
    for row in _HUE180:
        v = row[0] * inv[0] + row[1] * inv[1] + row[2] * inv[2]
        # ROUND, do not truncate. Each matrix row sums to 1.0 only within float
        # error (0.426+0.430+0.144 == 0.9999999999999999), so truncation turned
        # pure white into #fffefe and darkened every channel by up to 1/255.
        c = int(round(max(0.0, min(255.0, v))))
        out.append(_GAMMA_LUT[c] if gamma else c)

    result = (a << 24) | (out[0] << 16) | (out[1] << 8) | out[2]
    with _dark_memo_lock:
        _dark_memo[key] = result
    return result


def darken_image(image: QImage) -> QImage:
    """Return `image` recolored for dark mode.

    Every tile in the bundled cache is palettized (81 % Format_Mono, 19 %
    Format_Indexed8), so this rewrites at most 256 color-table entries instead
    of 65 536 pixels — 0.113 ms/tile against 2.31 ms for the pixel-wise form,
    with a bit-identical result. A non-palettized image is returned unchanged
    rather than paid for pixel by pixel.
    """
    table = image.colorTable()
    if not table:
        return image
    image.setColorTable([dark_argb(c) for c in table])
    return image


# --------------------------------------------------------------------------
# Tile storage
# --------------------------------------------------------------------------

_ONLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tiles (
    zoom INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    tile_image BLOB NOT NULL,
    last_used REAL NOT NULL,
    PRIMARY KEY (zoom, x, y)
);
"""


def online_db_path() -> str:
    """Where fetched tiles persist.

    INV-5: never the bundled `map_tiles_cache.db`. That file is git-tracked at
    86 MB and its large-file warning is intentional; growing it would put every
    browsed tile into the repository.
    """
    from core.tz_finder import writable_cache_dir
    return os.path.join(writable_cache_dir(), "map_tiles_online.db")


class _Connections:
    """Per-thread SQLite connections.

    SQLite connections are not shareable across threads, and the worker plus
    four network threads all touch these databases. `threading.local()` gives
    each its own handle; WAL mode lets the writers proceed concurrently.
    """

    def __init__(self, bundled_path: str, online_path: str):
        self.bundled_path = bundled_path
        self.online_path = online_path
        self._local = threading.local()
        self._zooms: Optional[List[int]] = None
        self._zooms_lock = threading.Lock()

    def bundled(self) -> Optional[sqlite3.Connection]:
        conn = getattr(self._local, "bundled", None)
        if conn is not None:
            return conn
        if not self.bundled_path or not os.path.exists(self.bundled_path):
            self._local.bundled = None
            return None
        try:
            # INV-5: read-only URI. A stray INSERT raises instead of mutating
            # the tracked 86 MB binary.
            uri = "file:{}?mode=ro".format(self.bundled_path.replace("?", "%3f"))
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            conn.execute("PRAGMA query_only=ON")
        except Exception:
            conn = None
        self._local.bundled = conn
        return conn

    def online(self) -> Optional[sqlite3.Connection]:
        conn = getattr(self._local, "online", None)
        if conn is not None:
            return conn
        try:
            path = self.online_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            conn = sqlite3.connect(path, timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_ONLINE_SCHEMA)
            conn.commit()
        except Exception:
            conn = None
        self._local.online = conn
        return conn

    def available_zooms(self) -> List[int]:
        with self._zooms_lock:
            if self._zooms is not None:
                return self._zooms
        conn = self.bundled()
        zooms: List[int] = []
        if conn is not None:
            try:
                zooms = [r[0] for r in conn.execute(
                    "SELECT DISTINCT zoom FROM tiles ORDER BY zoom")]
            except Exception:
                zooms = []
        with self._zooms_lock:
            self._zooms = zooms
        return zooms

    def cached_max_zoom(self) -> int:
        zooms = self.available_zooms()
        return max(zooms) if zooms else SOFT_MAX_ZOOM


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------

class TileWorker(QObject):
    """Loads tiles off the GUI thread and hands back QImages.

    Lives in a QThread owned by the view. All slots run on that thread; network
    fetches fan out to a small pool from there.
    """

    tile_ready = Signal(int, int, int, int, QImage, bool)  # gen,z,x,y,image,dark
    tile_failed = Signal(int, int, int, int)               # gen, z, x, y
    #: Emitted once the bundled DB has been probed, so the GUI never has to
    #: open SQLite itself to answer get_cached_max_zoom() (INV-1).
    cached_max_known = Signal(int)

    def __init__(self, bundled_path: str = None, online_path: str = None,
                 allow_network: bool = True, parent=None):
        super().__init__(parent)
        self._conns = _Connections(
            bundled_path if bundled_path is not None else DEFAULT_DB_PATH,
            online_path if online_path is not None else online_db_path(),
        )
        self._allow_network = allow_network
        self._pool: Optional[ThreadPoolExecutor] = None
        self._guard = threading.Lock()
        self._fail_until = {}          # TileKey -> monotonic deadline
        self._inflight = set()         # TileKey currently being fetched
        self._current_gen = 0
        self._net_calls = 0            # T-6 probe
        self._stopping = False
        self._announced_max = False

    # -- lifecycle ---------------------------------------------------------

    def _ensure_pool(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=MAX_NET_WORKERS, thread_name_prefix="map-net")
        return self._pool

    def stop(self):
        """Ask the worker to abandon any in-progress batch and release the pool.

        Callable from ANY thread (teardown runs on the GUI thread). Setting the
        flag first means a long batch stops emitting instead of running to
        completion while the interpreter is being finalised — that was raising
        mid-`handle_batch` at exit.
        """
        self._stopping = True
        pool, self._pool = self._pool, None
        if pool is not None:
            try:
                # cancel_futures matters: closing a zoom-8 viewport with no
                # network left dozens of queued 4 s timeouts to drain, and
                # ThreadPoolExecutor's atexit hook JOINS its threads, so the
                # whole app took ~ceil(tiles/4)*4 s to exit.
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:      # Python < 3.9
                pool.shutdown(wait=False)
            except Exception:
                pass

    @Slot()
    def shutdown(self):
        """Deprecated alias for `stop()`."""
        self.stop()

    # -- introspection (used by the view and by tests) ---------------------

    def cached_max_zoom(self) -> int:
        return self._conns.cached_max_zoom()

    def net_call_count(self) -> int:
        with self._guard:
            return self._net_calls

    # -- request handling --------------------------------------------------

    @Slot(int, object, bool)
    def handle_batch(self, gen: int, keys: Sequence[TileKey], dark: bool):
        """Load a batch of tiles. Runs on the worker thread.

        Every key in the batch is answered with exactly one `tile_ready` or
        `tile_failed`, even if a newer batch has since arrived. Bailing out
        early on a stale generation would strand the view's `_pending` entries
        and those tiles would never load again. Local reads cost ~0.4 ms, so
        finishing a superseded batch is cheaper than tracking the leak; the
        expensive path (network) is where `gen` earns its keep, below.
        """
        with self._guard:
            self._current_gen = gen

        if not self._announced_max:
            # First batch: probe the DB here, on the worker thread, and tell the
            # GUI. get_cached_max_zoom() used to reach sqlite3.connect directly
            # from the GUI thread, which violated INV-1.
            self._announced_max = True
            self.cached_max_known.emit(self._conns.cached_max_zoom())

        for key in keys:
            if self._stopping:
                return
            try:
                z, x, y = key
                data = self._read_local(z, x, y)
                if data is not None:
                    image = self._decode(data, dark)
                    if image is not None:
                        self.tile_ready.emit(gen, z, x, y, image, dark)
                        continue
                self._maybe_fetch(gen, z, x, y, dark)
            except Exception:
                # One bad tile must not abandon the rest of the batch, and a
                # teardown race must not raise out of a Qt slot.
                try:
                    self.tile_failed.emit(gen, key[0], key[1], key[2])
                except Exception:
                    return

    def _read_local(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Bundled cache first, then the persisted online cache."""
        conn = self._conns.bundled()
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=?",
                    (z, x, y)).fetchone()
                if row and row[0]:
                    return row[0]
            except Exception:
                pass

        conn = self._conns.online()
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=?",
                    (z, x, y)).fetchone()
                if row and row[0]:
                    try:
                        conn.execute(
                            "UPDATE tiles SET last_used=? WHERE zoom=? AND x=? AND y=?",
                            (time.time(), z, x, y))
                        conn.commit()
                    except Exception:
                        pass
                    return row[0]
            except Exception:
                pass
        return None

    @staticmethod
    def _decode(data: bytes, dark: bool) -> Optional[QImage]:
        image = QImage()
        if not image.loadFromData(data):
            return None
        if dark:
            image = darken_image(image)
        return image

    def _maybe_fetch(self, gen: int, z: int, x: int, y: int, dark: bool):
        """Queue an online fetch, honouring the negative cache and dedup."""
        if not self._allow_network or z <= self._conns.cached_max_zoom():
            self.tile_failed.emit(gen, z, x, y)
            return

        key = (z, x, y)
        now = time.monotonic()
        with self._guard:
            # INV-8, and the only place `gen` is load-bearing: a network round
            # trip for a viewport the user has already left is pure waste.
            if gen != self._current_gen:
                self.tile_failed.emit(gen, z, x, y)
                return
            deadline = self._fail_until.get(key)
            if deadline is not None and deadline > now:
                self.tile_failed.emit(gen, z, x, y)   # RC-2: do not retry yet
                return
            if key in self._inflight:
                # Another batch is already fetching it; that batch will answer.
                self.tile_failed.emit(gen, z, x, y)
                return
            self._inflight.add(key)

        self._ensure_pool().submit(self._fetch_job, gen, z, x, y, dark)

    def _fetch_job(self, gen: int, z: int, x: int, y: int, dark: bool):
        """Runs on a network pool thread."""
        key = (z, x, y)
        if self._stopping:
            # The map closed while this sat in the queue. Do not open a socket.
            with self._guard:
                self._inflight.discard(key)
            return
        data = None
        try:
            with self._guard:
                self._net_calls += 1
            request = urllib.request.Request(
                OSM_TILE_URL.format(z=z, x=x, y=y),
                headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=NET_TIMEOUT_SEC) as response:
                data = response.read()
        except Exception:
            data = None

        try:
            if self._stopping:
                return
            if data:
                self._store_online(z, x, y, data)
                image = self._decode(data, dark)
                if image is not None:
                    self.tile_ready.emit(gen, z, x, y, image, dark)
                    return
            with self._guard:
                self._fail_until[key] = time.monotonic() + FAIL_TTL_SEC
            self.tile_failed.emit(gen, z, x, y)
        finally:
            with self._guard:
                self._inflight.discard(key)

    def _store_online(self, z: int, x: int, y: int, data: bytes):
        conn = self._conns.online()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT OR REPLACE INTO tiles (zoom,x,y,tile_image,last_used) "
                "VALUES (?,?,?,?,?)", (z, x, y, data, time.time()))
            conn.commit()
            self._trim_online(conn)
        except Exception:
            pass

    @staticmethod
    def _trim_online(conn: sqlite3.Connection):
        """Bound the online cache; drop the least recently used overflow."""
        try:
            count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            if count <= MAX_ONLINE_ROWS:
                return
            conn.execute(
                "DELETE FROM tiles WHERE rowid IN ("
                "  SELECT rowid FROM tiles ORDER BY last_used ASC LIMIT ?)",
                (count - MAX_ONLINE_ROWS,))
            conn.commit()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Zoom input curve (SPEC-MAP-001 §4.1 / §4.2) — pure, so T-2/T-3 need no GUI
# --------------------------------------------------------------------------

#: Wheel divisor. One notch is 120 units, so a notch multiplies the scale by
#: 2^(1/2) ≈ 1.41 and two notches make exactly one tile level. The old code
#: turned ANY non-zero delta into a full level, which is why one trackpad
#: gesture crossed several (RC-4).
WHEEL_DIVISOR = 240.0
WHEEL_DIVISOR_FAST = 120.0
#: A second scroll this long after hitting the detent is read as deliberate.
DETENT_MS = 350.0


def wheel_zoom_delta(angle_delta_y: float, fast: bool = False) -> float:
    """Zoom levels contributed by one wheel event."""
    return angle_delta_y / (WHEEL_DIVISOR_FAST if fast else WHEEL_DIVISOR)


class ZoomDetent:
    """The offline detent (D-15 / INV-4).

    Wheel zoom stops at `soft_max`. Crossing requires a wheel event arriving
    after at least `DETENT_MS` of **no wheel input at all** — a gap the hand
    does not produce mid-gesture, but a deliberate second scroll always does.
    Dropping back below `soft_max` re-arms it.

    The gate measures the IDLE GAP between consecutive wheel events, not the
    time since the clamp engaged. That distinction is the whole correctness of
    this class: the first implementation timed from the clamp, and the real
    on-screen harness immediately broke it — twelve notches of a fast flick
    span ~400 ms of wall clock once Qt processes tile signals between them, so
    the flick outran a 350 ms window and crossed the detent anyway. Gap-based,
    a flick can last all day and still never unlock.

    Kept free of Qt so T-3 can drive it with a fake clock.
    """

    def __init__(self, soft_max: int = SOFT_MAX_ZOOM, hard_max: int = HARD_MAX_ZOOM):
        self.soft_max = float(soft_max)
        self.hard_max = float(hard_max)
        self.ceiling = self.soft_max
        self._clamped = False
        self._last_event_ms: Optional[float] = None

    def unlock(self):
        """Deliberate crossing (the + button, Ctrl+wheel)."""
        self.ceiling = self.hard_max
        self._clamped = False

    def note_input(self, now_ms: float):
        """Record wheel activity that produces no zoom change.

        Horizontal scrolling and pixel-only wheel events have
        `angleDelta().y() == 0`, so they never reach `clamp()`. Without this the
        wheel could be busy the whole time and the detent would still see an
        idle gap: scroll sideways at the boundary for 350 ms, then one notch up,
        and it unlocked even though input never stopped.
        """
        self._last_event_ms = now_ms

    def clamp(self, target: float, now_ms: float, deliberate: bool = False) -> float:
        """Return the zoom actually allowed for `target`.

        `now_ms` is the timestamp of THIS wheel event.
        """
        gap = (float('inf') if self._last_event_ms is None
               else now_ms - self._last_event_ms)
        self._last_event_ms = now_ms

        if deliberate:
            self.unlock()
            return min(target, self.hard_max)

        if target > self.ceiling:
            # Unlock only when the clamp is already armed AND the wheel went
            # quiet in between. Both conditions matter: the first blocked notch
            # arms it, and only a real pause can then release it.
            if self._clamped and gap >= DETENT_MS:
                self.ceiling = self.hard_max
                self._clamped = False
                return min(target, self.ceiling)
            self._clamped = True
            return self.ceiling

        # Re-arm once the user is comfortably back inside cached territory.
        if target < self.soft_max:
            self.ceiling = self.soft_max
            self._clamped = False
        return target

    def at_detent(self) -> bool:
        return self._clamped and self.ceiling == self.soft_max
