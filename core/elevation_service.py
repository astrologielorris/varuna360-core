# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""WI-7 / SPEC-ELEV-001 — a real map→elevation lookup for the New & Edit form.

DISPLAY-ONLY. Chart calculation uses lat/lon exclusively; elevation is never
persisted (CHTK has no field for it) and must never enter ``collect_data()``.
This service exists so the resolved-place chip can show the ground height, a
NEW capability Lorris asked for — nothing downstream reads it.

Modeled on ``core/geocode_service.py``: a sqlite cache in the same user-data
dir, a stdlib-only network tier (NO new pip dependency — venv rule), and a
generation-guarded ``QRunnable`` worker so a late landing after the pin moved is
dropped. Two keyless providers behind one signature; Open-Meteo first, the
flakier open-elevation as fallback.

Attribution (required by Open-Meteo's terms): the elevation chip's tooltip
carries ``ATTRIBUTION``; SPEC-ELEV-001 records the obligation.
"""

import json
import math
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

#: Shown in the chip tooltip and recorded in SPEC-ELEV-001. Open-Meteo's terms
#: require crediting them and the underlying Copernicus dataset.
ATTRIBUTION = "Elevation © Open-Meteo.com / Copernicus GLO-90"

USER_AGENT = "Varuna360/1.0 (astrology; elevation lookup)"

#: Per-provider socket timeout. Two providers ⇒ worst-case ~2x off the GUI
#: thread; also bounds the WI-4-shared shutdown drain.
PROVIDER_TIMEOUT = 3.0

#: Plausible terrestrial elevation band (m). The Dead Sea shore is ~-430 m and
#: Everest ~8849 m; anything outside this is a malformed/garbage response, not a
#: place a person was born, so it degrades to None (chip shows "elev —").
MIN_ELEVATION_M = -500.0
MAX_ELEVATION_M = 9000.0

_cache_lock = threading.Lock()
_cache_conn = None
_rate_lock = threading.Lock()
_network_calls = 0

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS elevation (
    key TEXT PRIMARY KEY,
    elevation REAL NOT NULL,
    stored_at REAL NOT NULL
);
"""

#: Rows are tiny; this is a hygiene cap, not a space concern (mirrors geocode).
MAX_CACHE_ROWS = 5000


# --------------------------------------------------------------------------
# Persistent cache (~100 m grid so a pin nudge re-uses the neighbour)
# --------------------------------------------------------------------------

def _cache_path() -> str:
    from core.tz_finder import writable_cache_dir
    return os.path.join(writable_cache_dir(), "elevation_cache.db")


def _conn() -> Optional[sqlite3.Connection]:
    global _cache_conn
    with _cache_lock:
        if _cache_conn is not None:
            return _cache_conn
        try:
            conn = sqlite3.connect(_cache_path(), timeout=5.0,
                                   check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_CACHE_SCHEMA)
            conn.commit()
            _cache_conn = conn
        except Exception:
            _cache_conn = None
        return _cache_conn


def _cache_key(lat: float, lon: float) -> str:
    # 3 decimals ≈ 110 m at the equator — the plan's ~100 m grid. A pin dragged
    # a few metres lands on the same key and never hits the network twice.
    return f"{lat:.3f},{lon:.3f}"


def cache_lookup(lat: float, lon: float) -> Optional[float]:
    conn = _conn()
    if conn is None:
        return None
    try:
        with _cache_lock:
            row = conn.execute(
                "SELECT elevation FROM elevation WHERE key=?",
                (_cache_key(lat, lon),)).fetchone()
    except Exception:
        return None
    return float(row[0]) if row else None


def cache_store(lat: float, lon: float, elevation: float):
    conn = _conn()
    if conn is None:
        return
    try:
        with _cache_lock:
            conn.execute(
                "INSERT OR REPLACE INTO elevation (key, elevation, stored_at) "
                "VALUES (?,?,?)",
                (_cache_key(lat, lon), float(elevation), time.time()))
            count = conn.execute(
                "SELECT COUNT(*) FROM elevation").fetchone()[0]
            if count > MAX_CACHE_ROWS:
                conn.execute(
                    "DELETE FROM elevation WHERE key IN ("
                    "  SELECT key FROM elevation ORDER BY stored_at ASC LIMIT ?)",
                    (count - MAX_CACHE_ROWS,))
            conn.commit()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _coords_valid(lat, lon) -> bool:
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _sane_elevation(value) -> Optional[float]:
    """Coerce a provider (or cached) value to a plausible float, else None."""
    # A JSON boolean survives float() as 1.0/0.0 and would render "elev 1 m" for
    # `{"elevation":[true]}` — a fact nobody measured. Reject it before float().
    if isinstance(value, bool):
        return None
    try:
        m = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: float(huge_int) raises rather than returning inf; an
        # uncaught one would abort the provider loop before the fallback ran.
        return None
    if not math.isfinite(m):
        return None
    if not (MIN_ELEVATION_M <= m <= MAX_ELEVATION_M):
        return None
    return m


# --------------------------------------------------------------------------
# Network tier (stdlib urllib; tests monkeypatch _urlopen_json)
# --------------------------------------------------------------------------

def _urlopen_json(url: str, timeout: float) -> Optional[dict]:
    """GET ``url`` and parse JSON. Returns None on ANY failure (never raises).

    The single seam tests patch to stay offline; the real callers below only
    ever see a dict-or-None.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    global _network_calls
    with _rate_lock:
        _network_calls += 1
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _fetch_open_meteo(lat: float, lon: float) -> Optional[float]:
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon})
    data = _urlopen_json(
        "https://api.open-meteo.com/v1/elevation?" + q, PROVIDER_TIMEOUT)
    if not isinstance(data, dict):
        return None
    arr = data.get("elevation")
    if not isinstance(arr, list) or not arr:
        return None
    return _sane_elevation(arr[0])


def _fetch_open_elevation(lat: float, lon: float) -> Optional[float]:
    q = urllib.parse.urlencode({"locations": f"{lat},{lon}"})
    data = _urlopen_json(
        "https://api.open-elevation.com/api/v1/lookup?" + q, PROVIDER_TIMEOUT)
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    return _sane_elevation(first.get("elevation"))


#: Providers tried in order; the first sane float wins.
_PROVIDERS = (_fetch_open_meteo, _fetch_open_elevation)


def lookup(lat, lon, use_cache: bool = True) -> Optional[float]:
    """Resolve ground elevation in metres. MAY BLOCK — never call on the GUI
    thread (go through ``ElevationWorker``).

    Returns a plausible float, or None when coordinates are invalid or no
    provider yields a sane value.
    """
    if not _coords_valid(lat, lon):
        return None
    lat = float(lat)
    lon = float(lon)
    if use_cache:
        hit = _sane_elevation(cache_lookup(lat, lon))
        if hit is not None:
            return hit   # a corrupt/legacy row that fails validation re-fetches
    for provider in _PROVIDERS:
        m = provider(lat, lon)
        if m is not None:
            if use_cache:
                cache_store(lat, lon, m)
            return m
    return None


def network_call_count() -> int:
    """Test probe: real HTTP GETs this process has attempted."""
    with _rate_lock:
        return _network_calls


def reset_for_tests():
    global _network_calls
    with _rate_lock:
        _network_calls = 0


# --------------------------------------------------------------------------
# Qt bridge (generation-guarded worker, mirrors GeocodeWorker / INV-8)
# --------------------------------------------------------------------------

class _Signals(QObject):
    finished = Signal(int, object)   # generation, float|None


class _Job(QRunnable):
    def __init__(self, signals, gen, lat, lon):
        super().__init__()
        self._signals = signals
        self._gen = gen
        self._lat = lat
        self._lon = lon

    def run(self):
        try:
            result = lookup(self._lat, self._lon)
        except Exception:
            result = None
        self._signals.finished.emit(self._gen, result)


class ElevationWorker(QObject):
    """Runs elevation lookups off the GUI thread with a generation guard.

    Every request bumps the generation; a landing whose generation is stale is
    dropped, so a slow lookup for the OLD pin can never overwrite the elevation
    of the place the user has since moved to.
    """

    resolved = Signal(object)   # float|None, current generation only

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gen = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_finished)

    def cancel(self):
        """Invalidate every in-flight request AND drop queued-but-unstarted
        jobs. The generation guard stops a stale result from PAINTING, but only
        clearing the queue stops a burst of picks from piling obsolete HTTP work
        that the newest request then waits behind (GPT-sol WI-7 finding 1).
        ``clear()`` removes not-yet-started runnables; a running one finishes
        (uninterruptible network) but its landing is dropped by the guard."""
        self._gen += 1
        self._pool.clear()

    def request(self, lat: float, lon: float) -> int:
        # Latest-request coalescing at the queue: drop obsolete queued jobs so
        # the newest coordinate is not stuck behind stale ones.
        self._pool.clear()
        self._gen += 1
        self._pool.start(_Job(self._signals, self._gen, lat, lon))
        return self._gen

    @Slot(int, object)
    def _on_finished(self, gen: int, result):
        if gen != self._gen:
            return   # superseded
        self.resolved.emit(result)

    def wait(self, timeout_ms: int = 8000) -> bool:
        """Offscreen/test helper. Never call from the interactive path."""
        return self._pool.waitForDone(timeout_ms)
