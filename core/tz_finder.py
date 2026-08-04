# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Process-wide TimezoneFinder singleton with background warm-up.

SPEC-MAP-001 INV-7: exactly one TimezoneFinder per process, reached through one
accessor.

Why this module exists (measured 2026-07-26): constructing a TimezoneFinder
costs **788 ms** (it loads the shapefile binaries); a `timezone_at()` query
afterwards costs **0.7 ms**. Before this module the app paid that 788 ms
repeatedly on the GUI thread:

  * `apps/panels/edit_map_subtab.py`  — a class-level cache, so once per
    session, but paid inside the first map click.
  * `tools/geocoding.py`              — a fresh instance per geocode.
  * `AI_tools/.../text_to_chtk.py`    — a *second* fresh instance in the same
    `resolve_location()` call.

So a single Add Chart burned ~1.6 s constructing two throwaway finders.

Usage:
    from core.tz_finder import start_warmup, timezone_at

    start_warmup()                 # non-blocking, idempotent; call when a
                                   # location UI opens
    tz = timezone_at(lat, lon)     # blocks only if warm-up has not finished

Threading contract: construction happens on the warm-up thread, queries are
serialised by `_query_lock`. TimezoneFinder instances are not documented as
thread-safe, so every query goes through that lock (uncontended cost is
negligible next to the 0.7 ms lookup).
"""

import threading
from typing import Optional

__all__ = [
    "start_warmup",
    "get_timezone_finder",
    "timezone_at",
    "timezone_at_or_offset",
    "is_ready",
    "construction_count",
    "reset_for_tests",
]

_state_lock = threading.Lock()
_query_lock = threading.Lock()
_ready = threading.Event()

_instance = None
_warming = False
_failed = False
_construction_count = 0  # T-8 probe: must be <= 1 for a whole session


def _build():
    """Construct the finder. Runs on whichever thread got here first."""
    global _instance, _construction_count, _failed, _warming
    try:
        from timezonefinder import TimezoneFinder
        finder = TimezoneFinder()
    except Exception:
        with _state_lock:
            _failed = True
            _warming = False
        _ready.set()
        return None

    with _state_lock:
        _instance = finder
        _construction_count += 1
        _warming = False
    _ready.set()
    return finder


def start_warmup() -> None:
    """Begin constructing the finder on a daemon thread.

    Idempotent and never blocks. Call this the moment a location-picking
    surface is created, so the 788 ms is spent while the user is still
    looking at the map rather than inside their first click.
    """
    global _warming
    with _state_lock:
        if _instance is not None or _warming or _failed:
            return
        _warming = True
    threading.Thread(target=_build, name="tzfinder-warmup", daemon=True).start()


def is_ready() -> bool:
    """True when a query will not block."""
    with _state_lock:
        return _instance is not None


def get_timezone_finder(timeout: Optional[float] = None):
    """Return the shared TimezoneFinder, or None if timezonefinder is absent.

    If a warm-up is in flight this waits for it (bounded by `timeout`) instead
    of building a second instance — building two is exactly the waste this
    module exists to remove. If no warm-up ever started, this builds it here.
    """
    global _warming
    with _state_lock:
        if _instance is not None:
            return _instance
        if _failed:
            return None
        warming = _warming

    if warming:
        _ready.wait(timeout)
        with _state_lock:
            return _instance

    # Nobody warmed it up; build synchronously on the caller's thread.
    with _state_lock:
        if _instance is not None:
            return _instance
        if _failed:
            return None
        _warming = True
    return _build()


def timezone_at(lat: float, lon: float, timeout: Optional[float] = None) -> Optional[str]:
    """IANA timezone name for a coordinate, or None.

    Note the keyword names: timezonefinder uses `lng`, not `lon`.
    """
    finder = get_timezone_finder(timeout=timeout)
    if finder is None:
        return None
    try:
        with _query_lock:
            return finder.timezone_at(lat=lat, lng=lon)
    except Exception:
        return None


def timezone_at_or_offset(lat: float, lon: float,
                          timeout: Optional[float] = None) -> str:
    """A timezone name for ANY coordinate — never None.

    `timezone_at()` returns None for every point outside a timezone polygon,
    which means **every click on open water**. Callers that treated None as "no
    change" therefore kept the PREVIOUS location's timezone: pick Paris, then
    pick a spot in the Atlantic, and the form still said Europe/Paris. For a
    birth chart that is a silently wrong chart.

    Falling back to the nautical zone for the longitude is both correct for a
    point at sea and impossible to confuse with a stale value.

    NOTE the inverted sign: POSIX `Etc/GMT-5` is UTC+5, not UTC-5.
    """
    name = timezone_at(lat, lon, timeout=timeout)
    if name:
        return name
    hours = int(round(max(-180.0, min(180.0, lon)) / 15.0))
    hours = max(-12, min(12, hours))
    return f"Etc/GMT{-hours:+d}"


def construction_count() -> int:
    """How many TimezoneFinder objects this process has built (T-8)."""
    with _state_lock:
        return _construction_count


#: Caches live in their own subdirectory, never loose in the base directory.
#: In dev mode `get_user_data_dir()` IS the project root, so writing there
#: dropped geocode_cache.db-wal / map_tiles_online.db-shm straight into the
#: repo — `*.db` is gitignored but the SQLite sidecars are not.
CACHE_SUBDIR = "map_cache"


def writable_cache_dir() -> str:
    """A directory the app may write caches into. Never raises.

    Prefers the configured user data dir. Falls back to the OS cache location
    rather than the install directory: `get_user_data_dir()` returns None on a
    packaged first run, and writing beside the bundled files can hit a
    read-only install.
    """
    import os
    import tempfile

    candidates = []
    try:
        from state.user_data import get_user_data_dir
        base = get_user_data_dir()
        if base:
            candidates.append(os.path.join(str(base), CACHE_SUBDIR))
    except Exception:
        pass

    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
            "varuna360", CACHE_SUBDIR))
    candidates.append(os.path.join(tempfile.gettempdir(), "varuna360", CACHE_SUBDIR))

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except Exception:
            continue
    return tempfile.gettempdir()


def reset_for_tests() -> None:
    """Drop the singleton so a test can count constructions from zero."""
    global _instance, _warming, _failed, _construction_count
    with _state_lock:
        _instance = None
        _warming = False
        _failed = False
        _construction_count = 0
    _ready.clear()
