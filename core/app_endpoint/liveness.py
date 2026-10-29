# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""App instance liveness markers (SPEC-SET-003 §4.5b, W6b fix F3, F7, F3-R1). Qt-free.

A running app instance publishes ``<user-data>/app_instances/<pid>.json``::

    {"v": 1, "pid": 1234, "start_time": 5678}

as the FIRST thing its startup does (before it reads the settings file), and
independently of its request endpoint: an instance whose endpoint could not
start (a broken discovery folder, a Windows ACL that failed closed) is still
known to be running. The marker holds no secret.

It is the offline route's exclusion: ``settings.py set --app`` writes the
settings file offline only when no live instance exists, checked under the
settings-file lock (``app_requests.offline_set``). The app publishes its
marker and only then waits for that same lock before it reads the file, so an
offline writer either finished before the app's read or sees the marker and
refuses (``app_requests.startup_wait``).

When that marker cannot be published (W6b fix F3-R1: ``app_instances`` is a
regular file, the folder is unwritable, the disk is full), ``establish``
falls back, in this order, and every reader (``alive_instances``) scans all
three:

1. the fallback marker ``<user-data>/app_instance.<pid>.json`` (the same
   document, directly in the user-data folder: no sub-folder to collide
   with). ONE fixed name pattern, ``FALLBACK_PREFIX`` + pid + ``SUFFIX``;
2. the sentinel ``<user-data>/app_instance.<pid>.lock``: a kernel lock held
   on it for the life of the process (``state.profile_store``'s advisory
   lock: flock on Linux and macOS, msvcrt on Windows). A reader counts it
   alive while its lock cannot be taken; the kernel releases it when the
   process dies, whatever its PID becomes later.

A reader ignores a marker whose process is gone, or whose PID now belongs to
another process (start time changed): the discovery files' rule
(``discovery._same_process``). The marker is removed at interpreter exit;
one left by a crash is ignored, and pruned by the next publisher.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
from typing import List, Optional

from core.app_endpoint import discovery

PROTOCOL_VERSION = 1
FOLDER_NAME = "app_instances"
SUFFIX = ".json"
FALLBACK_PREFIX = "app_instance."          # <folder>/app_instance.<pid>.json / .lock
SENTINEL_SUFFIX = ".lock"

MARKER = "marker"
FALLBACK_MARKER = "fallback_marker"
SENTINEL = "sentinel"

_published = {}          # resolved folder -> (kind, path), for this process
_sentinels = {}          # resolved folder -> the open, locked sentinel handle


def markers_dir(folder) -> Path:
    return Path(folder) / FOLDER_NAME


def marker_path(folder, pid: Optional[int] = None) -> Path:
    return markers_dir(folder) / f"{os.getpid() if pid is None else int(pid)}{SUFFIX}"


def fallback_marker_path(folder, pid: Optional[int] = None) -> Path:
    pid = os.getpid() if pid is None else int(pid)
    return Path(folder) / f"{FALLBACK_PREFIX}{pid}{SUFFIX}"


def sentinel_path(folder, pid: Optional[int] = None) -> Path:
    pid = os.getpid() if pid is None else int(pid)
    return Path(folder) / f"{FALLBACK_PREFIX}{pid}{SENTINEL_SUFFIX}"


def _key(folder) -> str:
    return os.path.abspath(str(folder))


def published_kind(folder) -> Optional[str]:
    """How this process is known to be alive in ``folder`` (``MARKER``,
    ``FALLBACK_MARKER``, ``SENTINEL``), or None."""
    entry = _published.get(_key(folder))
    if entry is None:
        return None
    kind, path = entry
    if kind == SENTINEL:
        return kind if _key(folder) in _sentinels else None
    return kind if path.exists() else None


def is_published(folder) -> bool:
    """True when this process published its marker (any kind) in ``folder``
    and it is still there."""
    return published_kind(folder) is not None


def _doc() -> dict:
    pid = os.getpid()
    return {"v": PROTOCOL_VERSION, "pid": pid,
            "start_time": discovery.process_start_time(pid)}


def _write_atomic(tmp: Path, final: Path) -> None:
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_doc(), fh, sort_keys=True)
            fh.flush()
        os.replace(tmp, final)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _remember(folder, kind: str, path: Path) -> Path:
    key = _key(folder)
    if key not in _published and key not in _sentinels:
        atexit.register(remove, folder)
    _published[key] = (kind, path)
    return path


def publish(folder) -> Path:
    """Publish this process's marker in user-data folder ``folder`` at its
    primary place (idempotent; atomic: written beside, then moved into
    place). Prunes the markers of instances that are gone. Raises OSError on
    failure."""
    entry = _published.get(_key(folder))
    if entry is not None and entry[0] == MARKER and entry[1].exists():
        return entry[1]
    target = markers_dir(folder)
    target.mkdir(parents=True, exist_ok=True)
    prune_stale(folder)
    final = marker_path(folder)
    _write_atomic(target / f"{os.getpid()}.tmp", final)
    return _remember(folder, MARKER, final)


def publish_fallback(folder) -> Path:
    """The fallback marker ``<folder>/app_instance.<pid>.json`` (F3-R1).
    Raises OSError on failure."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    final = fallback_marker_path(folder)
    _write_atomic(folder / f"{FALLBACK_PREFIX}{os.getpid()}.tmp", final)
    return _remember(folder, FALLBACK_MARKER, final)


def hold_sentinel(folder) -> Path:
    """The sentinel ``<folder>/app_instance.<pid>.lock``, locked by this
    process until it exits (F3-R1). Raises OSError when it cannot be created
    or locked."""
    import state.profile_store as profile_store
    key = _key(folder)
    if key in _sentinels:
        return sentinel_path(folder)
    if profile_store._fcntl is None and profile_store._msvcrt is None:
        raise OSError("no advisory lock primitive: a sentinel would prove nothing")
    path = sentinel_path(folder)
    handle = open(path, "a+b")
    try:
        if not profile_store._acquire_lock(handle, 0.0):
            raise OSError(f"sentinel lock not taken: {path}")
        # A pruner that unlinked the file between our open and our lock would
        # leave us locking an inode nobody can find: check it is still the
        # file at that path.
        info, now = os.fstat(handle.fileno()), os.stat(path)
        if (info.st_dev, info.st_ino) != (now.st_dev, now.st_ino):
            raise OSError(f"sentinel replaced while locking: {path}")
    except BaseException:
        handle.close()
        raise
    _sentinels[key] = handle
    return _remember(folder, SENTINEL, path)


def establish(folder) -> str:
    """Make this process known to be alive in ``folder``: the primary
    marker, else the fallback marker, else the sentinel lock. Returns the
    kind established (idempotent). Raises OSError (all three reasons) when
    none can be."""
    kind = published_kind(folder)
    if kind is not None:
        return kind
    # Prune first, whichever place this process ends up publishing in: a
    # dead instance's fallback marker or free sentinel goes even while the
    # primary folder stays broken (W6b fix round 3 leftover).
    prune_stale(folder)
    errors = []
    for kind, step in ((MARKER, publish), (FALLBACK_MARKER, publish_fallback),
                       (SENTINEL, hold_sentinel)):
        try:
            step(folder)
            return kind
        except OSError as exc:
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")
    raise OSError("; ".join(errors))


def remove(folder) -> bool:
    """Remove this process's marker or sentinel (at exit). Never raises."""
    key = _key(folder)
    entry = _published.pop(key, None)
    handle = _sentinels.pop(key, None)
    if handle is not None:
        try:
            import state.profile_store as profile_store
            profile_store._release_lock(handle)
        except Exception:
            pass
        try:
            handle.close()
        except OSError:
            pass
    path = entry[1] if entry is not None else marker_path(folder)
    try:
        if entry is None or entry[0] != SENTINEL:
            doc = _read(path)
            if doc is not None and doc.get("pid") != os.getpid():
                return False
        os.unlink(path)
        return True
    except OSError:
        return False


def _read(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _pid_of(name: str) -> Optional[int]:
    if not name.endswith(SUFFIX):
        return None
    core = name[:-len(SUFFIX)]
    return int(core) if core.isdigit() else None


def _fallback_pid(name: str, suffix: str) -> Optional[int]:
    if not (name.startswith(FALLBACK_PREFIX) and name.endswith(suffix)):
        return None
    core = name[len(FALLBACK_PREFIX):-len(suffix)]
    return int(core) if core.isdigit() else None


def _live(path: Path, pid: int) -> bool:
    doc = _read(path)
    if doc is None or doc.get("v") != PROTOCOL_VERSION or doc.get("pid") != pid:
        return False
    return discovery._same_process(pid, doc)


def _sentinel_held(path: Path) -> bool:
    """True when another process holds the sentinel's lock (alive). Never
    creates the file."""
    import state.profile_store as profile_store
    try:
        handle = open(path, "r+b")
    except OSError:
        return False
    try:
        if profile_store._acquire_lock(handle, 0.0):
            profile_store._release_lock(handle)
            return False
        return True
    finally:
        handle.close()


def _scan(folder):
    """(pid, kind, path) for every marker-shaped file in ``folder``."""
    directory = markers_dir(folder)
    try:
        for name in os.listdir(directory):
            pid = _pid_of(name)
            if pid is not None:
                yield pid, MARKER, directory / name
    except OSError:
        pass
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        pid = _fallback_pid(name, SUFFIX)
        if pid is not None:
            yield pid, FALLBACK_MARKER, Path(folder) / name
            continue
        pid = _fallback_pid(name, SENTINEL_SUFFIX)
        if pid is not None:
            yield pid, SENTINEL, Path(folder) / name


def alive_instances(folder, include_self: bool = False) -> List[int]:
    """The PIDs of the app instances alive in user-data folder ``folder``
    (primary markers, fallback markers and sentinels; stale ones ignored).
    This process is left out unless ``include_self``: an app never asks
    whether it may write offline."""
    if folder is None:
        return []
    found = set()
    for pid, kind, path in _scan(folder):
        if pid == os.getpid():
            if include_self and is_published(folder):
                found.add(pid)
            continue
        if kind == SENTINEL:
            if _sentinel_held(path):
                found.add(pid)
        elif _live(path, pid):
            found.add(pid)
    return sorted(found)


def prune_stale(folder) -> int:
    """Remove markers (and leftover ``.tmp`` files) of instances that are
    gone, primary and fallback; sentinels of dead PIDs whose lock is free.
    Never touches a live instance's marker. Returns the count."""
    removed = 0
    places = [(markers_dir(folder), "")]
    places.append((Path(folder), FALLBACK_PREFIX))
    for directory, prefix in places:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if prefix and not name.startswith(prefix):
                continue
            stem, _dot, ext = name[len(prefix):].rpartition(".")
            if ext not in ("json", "tmp", "lock") or not stem.isdigit():
                continue
            if ext == "lock" and not prefix:
                continue
            pid = int(stem)
            if pid == os.getpid():
                continue
            path = directory / name
            if ext == "json" and _live(path, pid):
                continue
            if ext in ("tmp", "lock") and discovery.live_state._pid_alive(pid):
                continue                    # being written / possibly held
            if ext == "lock" and _sentinel_held(path):
                continue
            try:
                os.unlink(path)
                removed += 1
            except OSError:
                continue
    return removed
