# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The running app's LIVE frame, for the tools (AIC plan 2, Lorris 2026-10-01).

A tool must calculate in the frame the user is LOOKING at: if the screen is in
sidereal with ayanamsa 98 and Placidus, a CLI run for debugging must be too.
The saved ``app_settings.json`` is not enough: a locked setting is never
written back (``persist_runtime_change``), and some dasha choices are runtime
only. So the app publishes its live values, and ``SettingsView`` puts them
above the saved file (argument > live app > saved file > factory):

- tools the app runs itself get them directly: ``live_settings()`` (in-process
  capabilities) or the ``VARUNA360_LIVE_SETTINGS`` environment variable
  (subprocess CLIs);
- a CLI started from a terminal while the app is open reads the app's live
  file in the settings folder (below).

Live files: each app instance publishes its OWN ``live_frame.<pid>.json``
(two instances can run at once, full and ``--lite``), rewritten when its values
change and touched (mtime) every few seconds as a heartbeat by a small daemon
thread (``Heartbeat``), so a GUI thread busy for minutes does not make the
tools drop the frame still on screen. Each file records its process start time
(``start_time``). A reader honours only files whose process is alive, is the
same process (its start time now equals the recorded one: a crashed instance's
file is ignored when its PID was reused) AND whose heartbeat is recent
(``HEARTBEAT_WINDOW``), and among those takes the instance whose window the
user activated last: the greatest ``activated_at`` (the last time one of its
windows became the active window), ties broken by ``changed_at`` (the last
time its values changed). A later ``changed_at`` alone never wins over a later
activation: the user changes settings in the window they are using, so a
background instance's values changing afterwards come from a programmatic
change (remote control, automation) and must not take the terminal away from
the window the user activated last. Instances that never recorded an
activation (no window activation event, e.g. offscreen, or an older app build)
compete by ``changed_at`` only when NO instance has an ``activated_at``. An instance retires only its own file at exit;
one quitting never hides another instance that is still open. The old single
``live_frame.json`` is no longer read.

Keys are settings dot-keys (``zodiac.mode``, ``dasha.left.ayanamsa_id``...), so
the live overlay needs no second mapping. Qt-free.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

LIVE_ENV = "VARUNA360_LIVE_SETTINGS"
LIVE_PREFIX = "live_frame."
LIVE_SUFFIX = ".json"
RETIRED_FILENAME = "live_frame.closed"   # the last retired file (bounded: one)
HEARTBEAT_SECONDS = 10.0       # the app touches its file this often
HEARTBEAT_WINDOW = 120.0       # a reader ignores a file not touched for longer

_provider: Optional[Callable[[], Dict]] = None


def set_live_settings_provider(fn: Optional[Callable[[], Dict]]) -> None:
    """The GUI registers a callable returning its live settings dict."""
    global _provider
    _provider = fn


def live_settings() -> Optional[Dict]:
    """The live values of the app running in THIS process, or None."""
    if _provider is None:
        return None
    try:
        values = _provider()
    except Exception:
        return None
    return dict(values) if isinstance(values, dict) else None


def live_env(values: Optional[Dict]) -> Dict[str, str]:
    """Environment entries that hand ``values`` to a subprocess CLI."""
    return {LIVE_ENV: json.dumps(values, sort_keys=True)} if values else {}


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259            # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_start_time(pid: int):
    """The start time of process ``pid``, or None when it cannot be read.

    A value that stays the same for the life of the process and differs for
    another process later given the same PID: Linux ``/proc/<pid>/stat``
    field 22 (clock ticks after boot), Windows ``GetProcessTimes`` creation
    time (100 ns units), other POSIX systems psutil's ``create_time`` when
    psutil is installed (else None: the check is skipped there). Never raises."""
    try:
        pid = int(pid)
        if pid <= 0:
            return None
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/stat", "rb") as fh:
                raw = fh.read().decode("ascii", "replace")
            # the command name (field 2) is in parentheses and may hold spaces
            fields = raw[raw.rindex(")") + 2:].split()
            return int(fields[19])              # field 22 (fields start at 3)
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                    return None
                created = times[0]
                return (created.dwHighDateTime << 32) | created.dwLowDateTime
            finally:
                kernel32.CloseHandle(handle)
        try:
            import psutil                      # only if already installed
        except ImportError:
            return None
        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _same_process(pid: int, doc: Dict) -> bool:
    """True when ``pid`` is alive and is the process that wrote ``doc``: its
    start time now equals the recorded ``start_time``. A file that recorded
    none (the platform could not read it) is judged on the PID alone."""
    if not _pid_alive(pid):
        return False
    recorded = doc.get("start_time") if isinstance(doc, dict) else None
    if recorded is None:
        return True
    current = process_start_time(pid)
    return current is not None and current == recorded


def live_filename(pid: Optional[int] = None) -> str:
    """The live file name of one app instance (this process by default)."""
    return f"{LIVE_PREFIX}{os.getpid() if pid is None else int(pid)}{LIVE_SUFFIX}"


def _pid_of(name: str) -> Optional[int]:
    """The PID in a live file name, or None for any other file."""
    if not (name.startswith(LIVE_PREFIX) and name.endswith(LIVE_SUFFIX)):
        return None
    core = name[len(LIVE_PREFIX):-len(LIVE_SUFFIX)]
    return int(core) if core.isdigit() else None


def _time_field(doc: Dict, key: str, default) -> float:
    value = doc.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0.0
    return float(value)


def _activated_field(doc: Dict) -> Optional[float]:
    """The recorded ``activated_at``, or None when the instance never recorded
    one (missing, null, or not a number)."""
    value = doc.get("activated_at")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value)


def _live_candidates(folder: Path, now: float):
    """(activated_at or None, changed_at, mtime, values) for every live file a
    reader may honour: its process alive, its heartbeat within
    HEARTBEAT_WINDOW. ``read_live`` picks among them."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for name in names:
        pid = _pid_of(name)
        if pid is None:
            continue
        path = Path(folder) / name
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime > HEARTBEAT_WINDOW or not _pid_alive(pid):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("pid") != pid:
            continue
        if not _same_process(pid, doc):         # the PID was reused
            continue
        values = doc.get("settings")
        if not isinstance(values, dict):
            continue
        out.append((_activated_field(doc),
                    _time_field(doc, "changed_at", doc.get("written_at", 0.0)),
                    mtime, values))
    return out


def _pick_instance(found):
    """The candidate whose window the user activated last: the greatest
    ``activated_at``, then ``changed_at``, then the file mtime. Candidates
    without an ``activated_at`` take part only when none has one (then by
    ``changed_at``, then mtime)."""
    activated = [c for c in found if c[0] is not None]
    pool = activated or found
    return max(pool, key=lambda c: (c[0] or 0.0, c[1], c[2]))


def read_live(folder: Optional[Path]) -> Optional[Dict]:
    """The live values for a tool: the environment first, else the live file
    of the app instance whose window the user activated last (greatest
    ``activated_at``, ties by ``changed_at``; instances with no recorded
    activation compete by ``changed_at`` only when none has one), among the
    instances that are alive and recently heartbeating (see the module
    docstring)."""
    raw = os.environ.get(LIVE_ENV)
    if raw:
        try:
            values = json.loads(raw)
            if isinstance(values, dict):
                return values
        except ValueError:
            pass
    if folder is None:
        return None
    found = _live_candidates(Path(folder), time.time())
    if not found:
        return None
    return _pick_instance(found)[3]


def write_live_or_raise(folder: Path, values: Dict, changed_at: Optional[float] = None,
                        activated_at: Optional[float] = None,
                        error: Optional[str] = None) -> None:
    """Publish ``values`` in this instance's own live file (the APP calls
    this, never a tool). ``changed_at`` is when the values last changed (now
    by default; a rewrite of unchanged values keeps the original time);
    ``activated_at`` when one of the instance's windows last became active
    (None: never). ``error``: why the app could not read its live values
    (LiveFrameManager.last_error), recorded as ``"error"`` so the problem is
    findable in the file; the key is absent when there is none. Atomic
    replace; raises on failure (``write_live`` is the non-raising form)."""
    folder = Path(folder)
    now = time.time()
    doc = {"pid": os.getpid(), "start_time": _own_start_time(),
           "written_at": now,
           "changed_at": now if changed_at is None else changed_at,
           "activated_at": activated_at,
           "settings": values}
    if error is not None:
        doc["error"] = error
    tmp = folder / f"{LIVE_PREFIX}{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, sort_keys=True, indent=1)
    os.replace(tmp, folder / live_filename())


def write_live(folder: Path, values: Dict, changed_at: Optional[float] = None,
               activated_at: Optional[float] = None) -> bool:
    """``write_live_or_raise``, returning False on any failure (never raises)."""
    try:
        write_live_or_raise(folder, values, changed_at, activated_at)
        return True
    except Exception:
        return False


_OWN_START = []


def _own_start_time():
    """This process's start time (read once)."""
    if not _OWN_START:
        _OWN_START.append(process_start_time(os.getpid()))
    return _OWN_START[0]


def touch_live(folder: Path) -> bool:
    """The heartbeat: refresh this instance's live file mtime. False when the
    file is gone (the caller rewrites it) or on any failure (never raises)."""
    try:
        os.utime(Path(folder) / live_filename(), None)
        return True
    except Exception:
        return False


class Heartbeat:
    """Touch this instance's live file every ``interval`` seconds from a
    daemon thread, so the heartbeat keeps going while the GUI thread is busy
    (a long calculation, a modal loop). It only touches the file (mtime): the
    values are written by the GUI thread (``write_live``), and a missing file
    is not recreated here (``os.utime`` creates nothing). ``stop()`` ends the
    thread and waits for it briefly; never raises."""

    def __init__(self, folder: Path, interval: float = HEARTBEAT_SECONDS):
        self._folder = Path(folder)
        self._interval = float(interval)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.beats = 0                          # successful touches (tests, diagnostics)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="live-frame-heartbeat",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if touch_live(self._folder):
                self.beats += 1

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            try:
                thread.join(timeout)
            except Exception:
                pass


def _retire(path: Path) -> None:
    os.replace(path, path.with_name(RETIRED_FILENAME))


def clear_live(folder: Path) -> None:
    """Retire this instance's own live file at app exit (never another's)."""
    try:
        _retire(Path(folder) / live_filename())
    except Exception:
        pass


def retire_stale(folder: Path) -> None:
    """Retire live files left by instances that are gone (a crash): process
    dead, or its PID now another process (start time changed), and heartbeat
    older than HEARTBEAT_WINDOW. The app calls this at start so crashed
    instances do not pile up files; readers already ignore them. Never
    touches a file a reader could honour."""
    now = time.time()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        pid = _pid_of(name)
        if pid is None or pid == os.getpid():
            continue
        path = Path(folder) / name
        try:
            if now - path.stat().st_mtime <= HEARTBEAT_WINDOW:
                continue
            if _pid_alive(pid):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        doc = json.load(fh)
                except (OSError, ValueError):
                    continue
                if _same_process(pid, doc):
                    continue
            _retire(path)
        except Exception:
            continue
