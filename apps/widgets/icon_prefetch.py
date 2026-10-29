# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Decode the 2048 px planet and sign art off the GUI thread, once per file.

The first chart after start-up asks for every planet and sign image at each
view's own size: ~50 decodes of 2048x2048 webp files on the GUI thread, the
7 s freeze after the window appears (2026-10-23 probe, Lite). The art stays
full size (Lorris, 2026-10-23); only where and how often it is decoded moves.

The app remembers which (file, size) pairs it used (``icon_prefetch.json`` in
the user data folder). At the next start two worker threads decode each of
those files ONCE and scale it to every remembered size while the window is
being built; Qt releases the GIL while it decodes. Same calls as the loaders
(QImage, smooth scale, aspect kept), so the pixels are identical; the loaders
still desaturate and make the QPixmap on the GUI thread.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

_ROOT = Path(__file__).resolve().parents[2]
_FILE = "icon_prefetch.json"
_MAX_KEYS = 400
_WORKERS = 2

_lock = threading.Lock()
_ready = {}      # (path, size) -> scaled QImage (not desaturated)
_pending = {}    # path -> Future of its decode
_used = set()    # (path, size) asked for in this session
_pool = None


def scaled_image(path, size):
    """``path`` scaled to ``size`` (aspect kept, smooth), or None when it
    cannot be read. Served from the prefetch when it has it; waits for a
    decode of the same file already running instead of starting a second."""
    key = (str(Path(path).resolve()), int(size))
    _used.add(key)
    with _lock:
        image = _ready.get(key)
    future = _pending.get(key[0])
    if image is None and future is not None:
        try:
            future.result()
        except Exception:   # noqa: BLE001  cancelled at quit, or unreadable: decode here
            pass
        with _lock:
            image = _ready.get(key)
    if image is None:
        source = QImage(key[0])
        if source.isNull():
            return None
        image = _scaled(source, key[1])
    return image


def start(app):
    """Begin the prefetch of the remembered pairs; remember this session's
    pairs on quit. Silent when nothing is remembered yet (first start)."""
    global _pool
    app.aboutToQuit.connect(_on_quit)
    by_path = {}
    for rel, size in _read_keys():
        by_path.setdefault(str(_ROOT / rel), set()).add(int(size))
    if not by_path or _pool is not None:
        return
    _pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="icon-prefetch")
    for path, sizes in by_path.items():
        _pending[path] = _pool.submit(_decode, path, sorted(sizes))


def _scaled(source, size):
    return source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def _decode(path, sizes):
    source = QImage(path)
    if source.isNull():
        return
    out = {(path, size): _scaled(source, size) for size in sizes}
    with _lock:
        _ready.update(out)


def _store():
    from state.user_data import get_user_data_dir
    folder = get_user_data_dir()
    return Path(folder) / _FILE if folder else None


def _read_keys():
    try:
        store = _store()
        rows = json.loads(store.read_text(encoding="utf-8")) if store else []
        return [(str(r[0]), int(r[1])) for r in rows[:_MAX_KEYS]
                if isinstance(r, list) and len(r) == 2]
    except (OSError, ValueError, TypeError):
        return []


def _on_quit():
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
    rows = set()
    for path, size in _used:
        try:
            rows.add((Path(path).relative_to(_ROOT).as_posix(), size))
        except ValueError:
            continue   # outside the app folder: never remembered
    if not rows:
        return
    try:
        store = _store()
        if store:
            store.write_text(json.dumps(sorted(rows)[:_MAX_KEYS]), encoding="utf-8")
    except OSError:
        pass
