# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Geocoding with a local tier, a persistent cache, and a real rate limiter.

SPEC-MAP-001 §4.5. Three tiers, cheapest first:

  1. `core.world_capitals.WORLD_CAPITALS` — in-process, microseconds.
  2. A persistent SQLite cache in the user data dir — a repeat search or a
     revisited place never touches the network again.
  3. Nominatim.

Only tier 3 can block, and callers on a GUI thread must reach it through
`GeocodeWorker` (below) rather than calling `forward()` directly.

Why the rate limiter is here
----------------------------
`tools/geocoding.py` used to run an unconditional `time.sleep(1.2)` before
every Nominatim call, on the GUI thread, even when the answer came from its
own hardcoded city table and no request was made. Nominatim's policy is one
request per second *between actual requests*, so the correct implementation
sleeps only the remainder since the last real call — which in practice is
zero.
"""

import os
import sqlite3
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

__all__ = [
    "GeocodeResult", "forward", "reverse", "cache_lookup",
    "GeocodeWorker", "nominatim_call_count", "reset_for_tests",
]

USER_AGENT = "Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)"
NOMINATIM_MIN_INTERVAL = 1.1
NOMINATIM_TIMEOUT = 5

_rate_lock = threading.Lock()
_last_call_at = 0.0
_nominatim_calls = 0

_cache_lock = threading.Lock()
_cache_conn = None

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS geocode (
    key TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    city TEXT,
    country TEXT,
    label TEXT,
    stored_at REAL NOT NULL
);
"""


class GeocodeResult:
    """A resolved place. `source` is one of local | cache | network."""

    __slots__ = ("lat", "lon", "city", "country", "label", "source")

    def __init__(self, lat, lon, city="", country="", label="", source="network"):
        self.lat = lat
        self.lon = lon
        self.city = city or ""
        self.country = country or ""
        self.label = label or ", ".join(p for p in (self.city, self.country) if p)
        self.source = source

    def __repr__(self):
        return (f"GeocodeResult({self.lat:.5f}, {self.lon:.5f}, "
                f"{self.label!r}, source={self.source})")


# --------------------------------------------------------------------------
# Persistent cache
# --------------------------------------------------------------------------

def _cache_path() -> str:
    from core.tz_finder import writable_cache_dir
    return os.path.join(writable_cache_dir(), "geocode_cache.db")


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


def _norm(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def cache_lookup(key: str) -> Optional[GeocodeResult]:
    conn = _conn()
    if conn is None:
        return None
    try:
        with _cache_lock:
            row = conn.execute(
                "SELECT lat, lon, city, country, label FROM geocode WHERE key=?",
                (_norm(key),)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return GeocodeResult(row[0], row[1], row[2], row[3], row[4], source="cache")


#: Bound on the persistent geocode cache. Rows are ~100 bytes, so this is a
#: hygiene limit rather than a space concern — an unbounded table that only ever
#: grows is a slow leak nobody notices.
MAX_CACHE_ROWS = 5000


def cache_store(key: str, result: GeocodeResult):
    conn = _conn()
    if conn is None:
        return
    try:
        with _cache_lock:
            conn.execute(
                "INSERT OR REPLACE INTO geocode "
                "(key, lat, lon, city, country, label, stored_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (_norm(key), result.lat, result.lon, result.city,
                 result.country, result.label, time.time()))
            count = conn.execute("SELECT COUNT(*) FROM geocode").fetchone()[0]
            if count > MAX_CACHE_ROWS:
                conn.execute(
                    "DELETE FROM geocode WHERE key IN ("
                    "  SELECT key FROM geocode ORDER BY stored_at ASC LIMIT ?)",
                    (count - MAX_CACHE_ROWS,))
            conn.commit()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Tier 1: local dataset
# --------------------------------------------------------------------------

def _local_lookup(query: str) -> Optional[GeocodeResult]:
    # SPEC-MAP-003: the ONE city table, the union of both sources. Reading a
    # single table with an ImportError fallback missed six well-known cities
    # (New York, Los Angeles, Toronto, Dubai, Mumbai, Sydney), so searching for
    # them skipped the local tier and, offline, found nothing.
    from core.place_naming import capital_table
    WORLD_CAPITALS = capital_table()

    wanted = _norm(query)
    if not wanted:
        return None

    for name, data in WORLD_CAPITALS.items():
        if _norm(name) == wanted:
            return GeocodeResult(data.get('lat', 0.0), data.get('lon', 0.0),
                                 name, data.get('country', ''), source="local")
    # A country name resolves to its capital — "france" should not need a
    # network round trip.
    for name, data in WORLD_CAPITALS.items():
        if _norm(data.get('country', '')) == wanted:
            return GeocodeResult(data.get('lat', 0.0), data.get('lon', 0.0),
                                 name, data.get('country', ''), source="local")
    return None


def local_suggestions(prefix: str, limit: int = 8):
    """Offline as-you-type suggestions.

    Local only, deliberately: Nominatim's usage policy forbids autocomplete
    querying, so the network tier is reached on Enter/Search only.
    """
    from core.place_naming import capital_table   # SPEC-MAP-003: one table
    WORLD_CAPITALS = capital_table()
    p = _norm(prefix)
    if not p:
        return []
    out = []
    for name, data in WORLD_CAPITALS.items():
        country = data.get('country', '')
        if _norm(name).startswith(p) or _norm(country).startswith(p):
            out.append(f"{name}, {country}" if country else name)
            if len(out) >= limit:
                break
    return out


# --------------------------------------------------------------------------
# Tier 3: Nominatim
# --------------------------------------------------------------------------

def _throttle():
    """Sleep only the remainder of the interval since the last REAL call."""
    global _last_call_at
    with _rate_lock:
        wait = NOMINATIM_MIN_INTERVAL - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _geolocator():
    try:
        from geopy.geocoders import Nominatim
    except ImportError:
        return None
    # geopy verifies TLS against the SYSTEM certificate store, not certifi.
    # In a packaged build (Nuitka .app, AppImage) the bundled OpenSSL's
    # default verify path does not exist on the user's machine, so every
    # Nominatim call dies with CERTIFICATE_VERIFY_FAILED — silently, through
    # forward()'s except — and geocoding "just fails" (mac VM test,
    # 2026-08-11). certifi's cacert.pem IS bundled (requests pulls it in),
    # so hand geopy an SSL context built on it. Falls back to the system
    # store when certifi is unavailable (source runs are fine either way).
    ssl_ctx = None
    try:
        import ssl
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_ctx = None
    if ssl_ctx is not None:
        return Nominatim(user_agent=USER_AGENT, timeout=NOMINATIM_TIMEOUT,
                         ssl_context=ssl_ctx)
    return Nominatim(user_agent=USER_AGENT, timeout=NOMINATIM_TIMEOUT)


def _extract(location) -> tuple:
    city = country = ""
    raw = getattr(location, "raw", None) or {}
    address = raw.get("address") or {}
    if address:
        city = (address.get('city') or address.get('town')
                or address.get('village') or address.get('municipality')
                or address.get('state') or "")
        country = address.get('country', '')
    if not city and getattr(location, "address", None):
        parts = location.address.split(", ")
        if len(parts) >= 2:
            city, country = parts[0], parts[-1]
    return city, country


def forward(query: str, use_cache: bool = True) -> Optional[GeocodeResult]:
    """Resolve a place name. MAY BLOCK — never call from the GUI thread."""
    if not query or not query.strip():
        return None

    hit = _local_lookup(query)
    if hit is not None:
        return hit

    if use_cache:
        hit = cache_lookup(query)
        if hit is not None:
            return hit

    geolocator = _geolocator()
    if geolocator is None:
        return None
    try:
        global _nominatim_calls
        _throttle()
        with _rate_lock:
            _nominatim_calls += 1
        location = geolocator.geocode(query, language="en", addressdetails=True)
    except Exception as e:
        # A silent None here cost a full VM round-trip to diagnose the
        # packaged-build SSL failure above. Name the reason, always.
        print(f"[GEOCODE] Nominatim request failed for {query!r}: {e}")
        return None
    if not location:
        return None

    city, country = _extract(location)
    result = GeocodeResult(location.latitude, location.longitude, city, country,
                           getattr(location, "address", ""), source="network")
    if use_cache:
        cache_store(query, result)
    return result


def reverse(lat: float, lon: float, use_cache: bool = True) -> Optional[GeocodeResult]:
    """Name a coordinate. MAY BLOCK — never call from the GUI thread.

    Cached at ~1 km granularity (2 decimal places): a birth place clicked twice
    resolves instantly the second time.
    """
    key = f"@{lat:.2f},{lon:.2f}"
    if use_cache:
        hit = cache_lookup(key)
        if hit is not None:
            return hit

    geolocator = _geolocator()
    if geolocator is None:
        return None
    try:
        global _nominatim_calls
        _throttle()
        with _rate_lock:
            _nominatim_calls += 1
        location = geolocator.reverse(f"{lat}, {lon}", language="en")
    except Exception:
        return None
    if not location:
        return None

    city, country = _extract(location)
    result = GeocodeResult(lat, lon, city, country,
                           getattr(location, "address", ""), source="network")
    if use_cache:
        cache_store(key, result)
    return result


def nominatim_call_count() -> int:
    """T-9 probe: how many real network geocodes this process has made."""
    with _rate_lock:
        return _nominatim_calls


def reset_for_tests():
    global _nominatim_calls, _last_call_at
    with _rate_lock:
        _nominatim_calls = 0
        _last_call_at = 0.0


# --------------------------------------------------------------------------
# Qt bridge
# --------------------------------------------------------------------------

class _Signals(QObject):
    finished = Signal(int, object)   # generation, GeocodeResult|None


class _Job(QRunnable):
    def __init__(self, signals, gen, fn, args):
        super().__init__()
        self._signals = signals
        self._gen = gen
        self._fn = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
        except Exception:
            result = None
        self._signals.finished.emit(self._gen, result)


class GeocodeWorker(QObject):
    """Runs geocoding off the GUI thread, with a generation guard.

    INV-8: every request carries a generation; a response whose generation is
    no longer current is dropped. Without this, clicking two places in quick
    succession lets the first (slower) reverse-geocode overwrite the second
    place's label.
    """

    resolved = Signal(object)   # GeocodeResult, current generation only

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gen = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _Signals(self)
        self._signals.finished.connect(self._on_finished)

    def cancel(self):
        """Invalidate every in-flight request."""
        self._gen += 1

    def request_forward(self, query: str) -> int:
        self._gen += 1
        self._pool.start(_Job(self._signals, self._gen, forward, (query,)))
        return self._gen

    def request_reverse(self, lat: float, lon: float) -> int:
        self._gen += 1
        self._pool.start(_Job(self._signals, self._gen, reverse, (lat, lon)))
        return self._gen

    @Slot(int, object)
    def _on_finished(self, gen: int, result):
        if gen != self._gen:
            return   # superseded — INV-8
        self.resolved.emit(result)

    def wait(self, timeout_ms: int = 8000) -> bool:
        """Offscreen/test helper. Never call from the interactive path."""
        return self._pool.waitForDone(timeout_ms)
