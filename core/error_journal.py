# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Local error journal and after-boot runtime hooks (SPEC-AIR-001 §4.1).

A module of its own on purpose: ``core.diagnostics`` is reachable from the
South Indian renderer and sits under the SI architecture ratchet (down-only
budgets), so new diagnostics code lives here rather than growing it.

No Qt.
"""
import os
import sys
from pathlib import Path

from core.diagnostics import _log_root, get_logger, redact_home


# ---------------------------------------------------------------------------
# Local error journal (SPEC-AIR-001 §4.1)
# ---------------------------------------------------------------------------
# One JSON object per line in {bootstrap}/logs/errors.jsonl: unhandled
# exceptions (the runtime hooks below) and handled failures the AI surfaces
# record themselves (record_event). LOCAL ONLY (AIR-001 INV-8): nothing in
# this module sends anything anywhere. The AI's diagnostic tools read it, after
# the user agreed and through the scrubber (core.privacy_scrub).
#
# Entries are stored redact_home()'d. The full scrub (names, places, dates)
# needs the chart library and runs at READ time, when the library is known.
#
# Like the rest of this module: NOTHING HERE MAY RAISE.

import json as _json
import threading as _threading
import time as _time
import traceback as _traceback
import uuid as _uuid

JOURNAL_NAME = "errors.jsonl"
JOURNAL_MAX_ENTRIES = 500
JOURNAL_MESSAGE_CHARS = 2000
JOURNAL_FRAMES = 20
JOURNAL_FRAME_CHARS = 400
# A storm of the same error (a paint loop raising every frame) increments a
# counter in memory and rewrites the file at most this often.
JOURNAL_FLUSH_SECONDS = 2.0

SURFACES = ("ai_capture", "ai_search", "ai_settings", "partner_reading", "app")

_journal_lock = _threading.RLock()
_last_key = None
_last_entry = None
_last_flush = 0.0
_dirty = False
_in_handler = _threading.local()


def journal_path():
    """{bootstrap}/logs/errors.jsonl (the file may not exist yet)."""
    return _log_root() / JOURNAL_NAME


def _app_version():
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text(
            encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _format_traceback(exc_type, exc_value, exc_tb):
    """The last JOURNAL_FRAMES frames, each capped, home-redacted."""
    try:
        frames = _traceback.extract_tb(exc_tb)[-JOURNAL_FRAMES:]
        lines = []
        for f in frames:
            line = f'File "{f.filename}", line {f.lineno}, in {f.name}'
            if f.line:
                line += f": {f.line.strip()}"
            lines.append(redact_home(line)[:JOURNAL_FRAME_CHARS])
        return lines
    except Exception:
        return []


def _read_entries():
    try:
        path = journal_path()
        if not path.is_file():
            return []
        out = []
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
        return out
    except Exception:
        return []


class _FileLock:
    """Best-effort cross-process lock (two app instances share the logs
    folder). Falls back to no lock: losing one journal line is better than
    blocking or raising inside an exception handler."""

    def __init__(self, path):
        self._path = path
        self._handle = None

    def __enter__(self):
        try:
            self._handle = open(self._path, "a+")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            if self._handle is not None:
                if os.name == "nt":
                    import msvcrt
                    try:
                        self._handle.seek(0)
                        msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                self._handle.close()
        except Exception:
            pass
        return False


def _write_entries(entries):
    """Rewrite the journal atomically (temp file + os.replace)."""
    root = _log_root()
    root.mkdir(parents=True, exist_ok=True)
    path = journal_path()
    tmp = root / f".{JOURNAL_NAME}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        for entry in entries[-JOURNAL_MAX_ENTRIES:]:
            handle.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _flush_locked():
    """Persist the pending in-memory entry. Caller holds _journal_lock."""
    global _dirty, _last_flush
    if not _dirty or _last_entry is None:
        return
    with _FileLock(_log_root() / ".errors.lock"):
        entries = _read_entries()
        if entries and entries[-1].get("id") == _last_entry.get("id"):
            entries[-1] = dict(_last_entry)
        else:
            entries.append(dict(_last_entry))
        _write_entries(entries)
    _dirty = False
    _last_flush = _time.monotonic()


def flush_journal():
    """Write a pending repeated-error count now (called at exit). Never raises."""
    try:
        with _journal_lock:
            _flush_locked()
    except Exception:
        pass


def record_event(surface, kind, message, *, exc_type=None, traceback_lines=None,
                 correlation_id=None, detail=None):
    """Append one entry to the local error journal. Never raises.

    For HANDLED failures the runtime hooks never see: an engine that would
    not start, a tool that raised, a relay that answered 502, a timeout, a
    refusal. `surface` is one of SURFACES ("app" for anything else).
    Returns the entry id, or None when nothing could be written.
    """
    global _last_key, _last_entry, _dirty
    try:
        entry = _new_entry(surface, kind, message, exc_type, traceback_lines,
                           correlation_id, detail)
        key = (entry["surface"], entry["kind"], entry["exc_type"] or "",
               entry["message"], entry["traceback"][-1] if entry["traceback"] else "",
               entry["correlation_id"] or "", entry["detail"] or "")
        with _journal_lock:
            if key == _last_key and _last_entry is not None:
                return _repeat_locked(entry["ts"])
            # A different error: persist the previous one's final count first.
            _flush_locked()
            _last_key = key
            _last_entry = entry
            _dirty = True
            _flush_locked()
            return entry["id"]
    except Exception:
        return None


def _new_entry(surface, kind, message, exc_type, traceback_lines, correlation_id, detail):
    now = _time.time()
    return {
        "id": _uuid.uuid4().hex[:12],
        "ts": now,
        "last_ts": now,
        "app_version": _app_version(),
        "surface": surface if surface in SURFACES else "app",
        "kind": str(kind or "error")[:40],
        "exc_type": str(exc_type)[:120] if exc_type else None,
        "message": redact_home(str(message or ""))[:JOURNAL_MESSAGE_CHARS],
        "traceback": list(traceback_lines or []),
        "thread": _threading.current_thread().name[:60],
        "count": 1,
        "correlation_id": str(correlation_id)[:80] if correlation_id else None,
        "detail": redact_home(str(detail))[:JOURNAL_MESSAGE_CHARS] if detail else None,
    }


def _repeat_locked(now):
    """The same error again: count it, rewrite the file at most every
    JOURNAL_FLUSH_SECONDS. Caller holds _journal_lock."""
    global _dirty
    _last_entry["count"] = int(_last_entry.get("count", 1)) + 1
    _last_entry["last_ts"] = now
    _dirty = True
    if _time.monotonic() - _last_flush >= JOURNAL_FLUSH_SECONDS:
        _flush_locked()
    return _last_entry.get("id")


def record_exception(surface, exc_type, exc_value, exc_tb, kind="unhandled",
                     correlation_id=None):
    """record_event for an exception triple. Never raises."""
    try:
        name = getattr(exc_type, "__name__", str(exc_type))
        return record_event(
            surface, kind, f"{name}: {exc_value}", exc_type=name,
            traceback_lines=_format_traceback(exc_type, exc_value, exc_tb),
            correlation_id=correlation_id)
    except Exception:
        return None


def read_journal(since_seconds=None, surface=None, limit=None):
    """Journal entries, newest first, optionally filtered. Never raises.
    Entries are redact_home()'d only: scrub before anything leaves."""
    try:
        flush_journal()
        entries = _read_entries()
        if since_seconds is not None:
            cutoff = _time.time() - float(since_seconds)
            entries = [e for e in entries
                       if float(e.get("last_ts") or e.get("ts") or 0) >= cutoff]
        if surface:
            entries = [e for e in entries if e.get("surface") == surface]
        entries.reverse()
        return entries[:limit] if limit else entries
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Runtime hooks (SPEC-AIR-001 §4.1)
# ---------------------------------------------------------------------------
# Installed ONCE the main window exists. Before that, the PyInstaller startup
# hook (build_windows.py CRASH_HOOK_SOURCE) owns sys.excepthook on Windows: a
# failure before the window exists is a failed START, and showing "could not
# start" and exiting is right. After boot it is wrong: that hook would show
# the box and sys.exit(1) on any exception in any Qt slot. So these hooks
# REPLACE it; they never chain to the previous hook. Do NOT "fix" this by
# calling the saved previous hook.
#
# They chain only to the interpreter's ORIGINAL hooks (sys.__excepthook__,
# threading.__excepthook__), which print to stderr in a source run and are
# harmless where stderr is gone.

_hooks_installed = False
_fault_handle = None


def _excepthook(exc_type, exc_value, exc_tb):
    if getattr(_in_handler, "active", False):
        return  # a failure inside the handler must not re-enter it
    _in_handler.active = True
    try:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        record_exception("app", exc_type, exc_value, exc_tb)
        try:
            get_logger("crash").error(
                "UNCAUGHT %s", redact_home("".join(
                    _traceback.format_exception(exc_type, exc_value, exc_tb))))
        except Exception:
            pass
        try:
            if sys.stderr is not None:
                sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        _in_handler.active = False


def _thread_excepthook(args):
    if getattr(_in_handler, "active", False):
        return
    _in_handler.active = True
    try:
        if args.exc_type is SystemExit:
            return
        record_exception("app", args.exc_type, args.exc_value, args.exc_traceback,
                         kind="thread")
        try:
            if sys.stderr is not None:
                _threading.__excepthook__(args)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        _in_handler.active = False


def asyncio_exception_handler(surface):
    """A ``loop.set_exception_handler`` callable that journals under
    `surface`, then defers to the loop's default handler."""
    def handler(loop, context):
        try:
            exc = context.get("exception")
            if exc is not None:
                record_exception(surface, type(exc), exc, exc.__traceback__,
                                 kind="async")
            else:
                record_event(surface, "async", context.get("message", "asyncio error"))
        except Exception:
            pass
        try:
            loop.default_exception_handler(context)
        except Exception:
            pass
    return handler


def journaled(surface, kind="worker"):
    """Decorator for a QThread ``run`` (or any worker body): an exception is
    journaled and swallowed instead of vanishing in the thread."""
    def wrap(func):
        import functools

        @functools.wraps(func)
        def inner(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                record_exception(surface, *sys.exc_info(), kind=kind)
                return None
        return inner
    return wrap


def install_runtime_hooks():
    """Install the after-boot hooks once. Never raises. Returns True when
    installed by this call."""
    global _hooks_installed, _fault_handle
    if _hooks_installed:
        return False
    try:
        sys.excepthook = _excepthook
        _threading.excepthook = _thread_excepthook
        _hooks_installed = True
    except Exception:
        return False
    try:
        import atexit
        atexit.register(flush_journal)
    except Exception:
        pass
    # Frozen builds already send faulthandler to a file (startup hook); a
    # source run printed it to stderr only.
    if not getattr(sys, "frozen", False):
        try:
            import faulthandler
            root = _log_root()
            root.mkdir(parents=True, exist_ok=True)
            # Kept open for the process lifetime: faulthandler writes to it
            # from a signal handler after a hard crash.
            _fault_handle = open(root / "faulthandler.log", "a",
                                 encoding="utf-8", errors="replace")
            faulthandler.enable(file=_fault_handle, all_threads=True)
        except Exception:
            pass
    return True
