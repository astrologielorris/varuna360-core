# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The command-line tools' own settings file, ``cli_settings.json``
(SPEC-SET-003 §4.5a, D-12).

One canonical, versioned document in the user-data folder::

    {"version": 1, "advanced": {"on": bool, "since": iso}, "values": {key: value}}

- Written ONLY here (``AI_tools/cli/settings.py`` is the one caller), with an
  atomic replace under a file lock around the whole read-modify-write, so two
  ``settings.py`` processes setting different keys both survive and a process
  killed mid-write leaves the previous file intact.
- Read lock-free by every terminal CLI (an atomic replace never shows a half
  file), and never created by a read: a missing file is an empty store.
- Every load is validated against the registry, the edition,
  ``rules.cli == "calculation"`` (D-16) and INV-17: an invalid, protected,
  app-family or other-edition value is IGNORED (the next layer answers) and
  reported apart in ``Store.ignored``, never used as a source.
- A malformed file raises ``BadStore`` (every terminal CLI stops with exit 2
  naming the file and ``settings.py reset``); a file from a newer version
  raises ``NewerStore`` (refused everywhere, plain ``reset`` included).
  ``reset`` moves a bad file aside as ``cli_settings.bad-<timestamp>.json``
  (never deleted) and writes an empty valid store with advanced mode off;
  ``reset(discard_newer=True)`` moves a newer file aside the same way.
- A write the file system refuses (folder, lock file, temp file, replace)
  raises ``StoreWriteFailed`` (exit 2, never a traceback, never called a
  malformed file); the previous file is left as it was.

The app and the capture replay never open this file (INV-4b): only the
terminal context of ``effective.py`` reads it. Qt-free.
"""
from __future__ import annotations

import copy
import json
import os
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

STORE_FILENAME = "cli_settings.json"
LOCK_SUFFIX = ".lock"
STORE_VERSION = 1
BAD_PREFIX = "cli_settings.bad-"
LOCK_TIMEOUT_S = 10.0

# Why a stored value (or a requested one) is not used: machine codes, the
# keys of the structured diagnostics (``status``, ``--json``).
UNKNOWN_KEY = "unknown_key"
OTHER_EDITION = "other_edition"
NOT_CALCULATION = "not_calculation"
PROTECTED = "protected"
BAD_VALUE = "bad_value"

_THREAD_LOCK = threading.RLock()


class StoreError(Exception):
    """The store cannot be used. ``code`` names the case, ``path`` the file."""

    code = "store_error"

    def __init__(self, path: Path, detail: str = ""):
        super().__init__(f"{self.code}: {path}" + (f" ({detail})" if detail else ""))
        self.path = Path(path)
        self.detail = detail


class BadStore(StoreError):
    code = "bad_file"


class NewerStore(StoreError):
    code = "newer_version"

    def __init__(self, path: Path, version: Any):
        super().__init__(path, f"version {version}")
        self.version = version


class StoreBusy(StoreError):
    code = "busy"


class StoreWriteFailed(StoreError):
    """The file system refused a write (folder, lock file, temp file, replace,
    set-aside move): never reported as a malformed file, the previous store is
    left as it was (W6 review F3). ``errno`` / ``reason`` are the OS facts."""

    code = "write_failed"

    def __init__(self, path: Path, exc: OSError):
        self.errno = exc.errno
        self.reason = exc.strerror or str(exc)
        super().__init__(Path(exc.filename) if exc.filename else path,
                         f"{self.errno_name}: {self.reason}")

    @property
    def errno_name(self) -> str:
        """The symbolic errno (``ENOSPC``), the same on every OS; the number
        when the OS gives none."""
        import errno as _errno
        if self.errno is None:
            return "unknown"
        return _errno.errorcode.get(self.errno, str(self.errno))


@contextmanager
def _write_guard(path: Path):
    """Any OSError of a write step becomes ``StoreWriteFailed``."""
    try:
        yield
    except StoreError:
        raise
    except OSError as exc:
        raise StoreWriteFailed(path, exc) from exc


@dataclass
class Store:
    """A validated snapshot of the file. ``values`` holds only the usable
    values; ``ignored`` maps every other stored key to the reason code."""
    path: Optional[Path]
    exists: bool = False
    advanced_on: bool = False
    advanced_since: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)
    ignored: Dict[str, str] = field(default_factory=dict)

    def describe(self) -> Dict[str, Any]:
        return {"path": str(self.path) if self.path else None,
                "exists": self.exists,
                "advanced": {"on": self.advanced_on, "since": self.advanced_since},
                "values": copy.deepcopy(self.values),
                "ignored": dict(sorted(self.ignored.items()))}


# ------------------------------------------------------------------ where

def store_dir() -> Optional[Path]:
    """The user-data folder (``VARUNA360_USER_DATA_DIR`` honoured), found
    read-only, exactly as the read-only settings view finds the app's file."""
    from core.capabilities.settings_view import resolve_settings_dir
    return resolve_settings_dir()


def store_path(folder: Optional[Path] = None) -> Optional[Path]:
    folder = store_dir() if folder is None else Path(folder)
    return None if folder is None else Path(folder) / STORE_FILENAME


def empty_document() -> Dict[str, Any]:
    return {"version": STORE_VERSION, "advanced": {"on": False, "since": None},
            "values": {}}


# ------------------------------------------------------------- validation

def _edition(edition: Optional[str]) -> str:
    if edition is not None:
        return edition
    from core.edition import current_edition
    return current_edition()


def is_protected(entry) -> bool:
    """INV-17: a key ``settings.py``, ``--set`` and the request service may
    never write. A calculation key is writable only when classified ``ai``;
    the consent and the app's toggle are protected app keys."""
    from core.settings_registry.rules import APP_PROTECTED, CLI_CALCULATION, WRITABLE_AI
    rules = entry.rules
    if rules is None:
        return True
    if rules is APP_PROTECTED:
        return True
    return rules.cli == CLI_CALCULATION and rules.writable != WRITABLE_AI


def check_key(key: str, edition: Optional[str] = None) -> Optional[str]:
    """None when ``key`` may hold a tools' value, else the reason code (in
    this order: unknown, other edition, protected, not a calculation key)."""
    from core import settings_registry as registry
    from core.settings_registry.rules import CLI_CALCULATION
    if not isinstance(key, str) or not registry.has(key):
        return UNKNOWN_KEY
    entry = registry.get(key)
    if entry.edition == "pro" and _edition(edition) == "lite":
        return OTHER_EDITION
    if is_protected(entry):
        return PROTECTED
    if entry.rules is None or entry.rules.cli != CLI_CALCULATION:
        return NOT_CALCULATION
    return None


def check_app_key(key: str, edition: Optional[str] = None) -> Optional[str]:
    """``check_key`` for the IN-APP request service (AI setting redesign,
    td-bztjj): calculation keys and app keys alike, when classified
    ``rules.writable == "ai"`` (INV-17). Order: unknown, other edition,
    protected (an unclassified, protected or not-``ai`` entry). ``settings.py``
    and ``--set`` keep ``check_key`` (calculation keys only, D-16)."""
    from core import settings_registry as registry
    from core.settings_registry.rules import WRITABLE_AI
    if not isinstance(key, str) or not registry.has(key):
        return UNKNOWN_KEY
    entry = registry.get(key)
    if entry.edition == "pro" and _edition(edition) == "lite":
        return OTHER_EDITION
    if is_protected(entry) or entry.rules.writable != WRITABLE_AI:
        return PROTECTED
    return None


def check_panel_key(key: str, edition: Optional[str] = None) -> Optional[str]:
    """``check_app_key`` for the AI setting PANEL (fix RD-3): also the
    ``ai_access.PANEL_ONLY`` calculation keys, which the panel changes on
    the user's Allow only. Every other route keeps ``check_app_key`` or
    ``check_key``."""
    from core import settings_registry as registry
    from core.settings_registry.ai_access import PANEL_ONLY
    if isinstance(key, str) and key in PANEL_ONLY and registry.has(key):
        entry = registry.get(key)
        if entry.edition == "pro" and _edition(edition) == "lite":
            return OTHER_EDITION
        return None
    return check_app_key(key, edition)


def check(key: str, value: Any, edition: Optional[str] = None,
          app_keys: bool = False, panel: bool = False) -> Optional[str]:
    """None when ``value`` may be used for ``key`` by the tools, else the
    reason code. The value passes the registry's type, choices, bounds and
    ``rules.validate`` (``registry.valid``). ``app_keys``: the in-app request
    service's classification (``check_app_key``), else ``check_key``'s."""
    from core import settings_registry as registry
    reason = (check_panel_key if panel else check_app_key if app_keys
              else check_key)(key, edition)
    if reason is not None:
        return reason
    try:
        ok = registry.valid(key, value)
    except Exception:
        ok = False
    return None if ok else BAD_VALUE


def allowed_values(key: Any) -> Optional[list]:
    """The values ``key`` accepts as one flat list (the ``choices`` field of
    a ``set.bad_value`` refusal): its choices, or true and false for a
    switch. None for an unknown key or one without a fixed list (free text,
    a list, a mapping)."""
    from core import settings_registry as registry
    if not isinstance(key, str) or not registry.has(key):
        return None
    values = registry.choice_values(key)
    if values is not None:
        return list(values)
    if registry.get(key).type is bool:
        return [True, False]
    return None


_TRUE =("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def parse_value(key: str, text: str) -> Any:
    """The typed value of a command-line ``text`` for ``key`` (ValueError when
    it cannot be one): booleans as true/false, numbers as numbers, lists and
    dicts as JSON, strings as given. Validity is ``check``'s job."""
    from core import settings_registry as registry
    entry = registry.get(key)
    kinds = entry.type if isinstance(entry.type, tuple) else (entry.type,)
    text = str(text)
    if type(None) in kinds and text.strip().lower() in ("null", "none"):
        return None
    if bool in kinds:
        low = text.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"{key}: expected true or false")
    if int in kinds:
        return int(text.strip())
    if float in kinds:
        return float(text.strip())
    if list in kinds or dict in kinds:
        value = json.loads(text)
        if not isinstance(value, tuple(k for k in kinds if k in (list, dict))):
            raise ValueError(f"{key}: expected JSON {' or '.join(k.__name__ for k in kinds)}")
        return value
    return text


# ------------------------------------------------------------------ reading

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_iso_timestamp(value: Any) -> bool:
    """An ISO-8601 date-time string ``datetime.fromisoformat`` reads (a
    trailing ``Z`` accepted as UTC on every Python this app ships with)."""
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def _parse_document(path: Path, raw: bytes) -> Dict[str, Any]:
    """The document, shape-checked: BadStore / NewerStore otherwise."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BadStore(path, f"not JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise BadStore(path, "not a JSON object")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise BadStore(path, "no valid version")
    if version > STORE_VERSION:
        raise NewerStore(path, version)
    if set(doc) != {"version", "advanced", "values"}:
        raise BadStore(path, "unexpected fields")
    advanced = doc["advanced"]
    if (not isinstance(advanced, dict) or set(advanced) != {"on", "since"}
            or not isinstance(advanced["on"], bool)):
        raise BadStore(path, "bad advanced block")
    # W6 review F5: on = true records WHEN (an ISO-8601 timestamp that
    # parses); on = false has no since (null). Anything else is a bad file.
    if advanced["on"]:
        if not _is_iso_timestamp(advanced["since"]):
            raise BadStore(path, "advanced.since is not an ISO-8601 timestamp")
    elif advanced["since"] is not None:
        raise BadStore(path, "advanced.since without advanced mode")
    if not isinstance(doc["values"], dict):
        raise BadStore(path, "values is not an object")
    return doc


def _read_raw(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BadStore(path, f"unreadable: {exc}") from None


def _snapshot(path: Optional[Path], doc: Optional[Dict[str, Any]],
              edition: Optional[str]) -> Store:
    if doc is None:
        return Store(path=path, exists=False)
    store = Store(path=path, exists=True,
                  advanced_on=bool(doc["advanced"]["on"]),
                  advanced_since=doc["advanced"]["since"])
    for key, value in doc["values"].items():
        reason = check(key, value, edition)
        if reason is None:
            store.values[key] = copy.deepcopy(value)
        else:
            store.ignored[key] = reason
    return store


def load(folder: Optional[Path] = None, edition: Optional[str] = None) -> Store:
    """The validated store of ``folder`` (default: the user-data folder).
    Never writes, never creates. A missing file (or no folder at all) is an
    empty store. Raises BadStore / NewerStore."""
    path = store_path(folder)
    if path is None:
        return Store(path=None)
    raw = _read_raw(path)
    if raw is None:
        return Store(path=path)
    return _snapshot(path, _parse_document(path, raw), edition)


# ------------------------------------------------------------------ writing

@contextmanager
def _locked(path: Path):
    """The process lock and the file lock (``cli_settings.json.lock``) around a
    whole read-modify-write, the pattern ``SettingsManager._save`` uses."""
    import state.profile_store as profile_store
    with _THREAD_LOCK:
        with _write_guard(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(str(path) + LOCK_SUFFIX, "a+b")
        with handle:
            if not profile_store._acquire_lock(handle, LOCK_TIMEOUT_S):
                raise StoreBusy(path, "locked by another process")
            try:
                yield
            finally:
                profile_store._release_lock(handle)


def _write(path: Path, doc: Dict[str, Any]) -> None:
    from core.fs_safety import write_bytes_atomic
    text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False, allow_nan=False)
    write_bytes_atomic(path, (text + "\n").encode("utf-8"), prefix="." + STORE_FILENAME + ".")


def _require_path(folder: Optional[Path]) -> Path:
    path = store_path(folder)
    if path is None:
        raise BadStore(Path(STORE_FILENAME), "no user-data folder")
    return path


def update(change: Callable[[Dict[str, Any]], None], folder: Optional[Path] = None,
           edition: Optional[str] = None) -> Store:
    """Read, ``change(doc)`` in place, write back atomically, all under the
    lock. A bad or newer file is never overwritten (BadStore / NewerStore).
    Returns the validated store as written."""
    path = _require_path(folder)
    with _locked(path):
        raw = _read_raw(path)
        doc = empty_document() if raw is None else _parse_document(path, raw)
        change(doc)
        _parse_document(path, json.dumps(doc).encode("utf-8"))   # still canonical
        with _write_guard(path):
            _write(path, doc)
    return _snapshot(path, doc, edition)


def set_value(key: str, value: Any, folder: Optional[Path] = None,
              edition: Optional[str] = None) -> Store:
    """Store a tools' value. The caller checked it (``check``); checked again
    here so no path writes a value a load would ignore."""
    reason = check(key, value, edition)
    if reason is not None:
        raise ValueError(f"{key}: {reason}")

    def change(doc):
        doc["values"][key] = copy.deepcopy(value)
    return update(change, folder, edition)


def unset_value(key: str, folder: Optional[Path] = None,
                edition: Optional[str] = None) -> Store:
    def change(doc):
        doc["values"].pop(key, None)
    return update(change, folder, edition)


def set_advanced(on: bool, folder: Optional[Path] = None,
                 edition: Optional[str] = None, now: Optional[str] = None) -> Store:
    """Advanced mode on (recording ``since``) or off."""
    def change(doc):
        doc["advanced"] = ({"on": True, "since": now or _now_iso()} if on
                           else {"on": False, "since": None})
    return update(change, folder, edition)


def _aside_name(folder: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = folder / f"{BAD_PREFIX}{stamp}.json"
    n = 1
    while candidate.exists():
        n += 1
        candidate = folder / f"{BAD_PREFIX}{stamp}-{n}.json"
    return candidate


def _repair_temp_name(path: Path) -> Path:
    """A fresh temp name beside the store for a repair's new file."""
    import uuid
    return path.parent / f".{STORE_FILENAME}.repair-{os.getpid()}-{uuid.uuid4().hex}.tmp"


def _copy_aside(raw: bytes, moved: Path) -> None:
    """The bad file's exact bytes as ``moved`` (exclusive create, synced).
    A copy, not a rename: the active file stays in place until the new one
    replaces it in one step."""
    handle = open(moved, "xb")      # never over an existing file
    try:
        with handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _discard(moved)             # the partial copy this call created
        raise


def _discard(path: Path) -> None:
    """Best-effort removal of a file THIS repair created (its temp, or its
    aside copy while the original is still the active file)."""
    try:
        path.unlink()
    except OSError:
        pass


_REPAIR_TEMP_GLOB = "." + STORE_FILENAME + ".repair-*.tmp"

# The repair's commit state (``reset``). PREPARED: the active file still
# holds the original bytes. COMMITTING is set BEFORE the final replace, so an
# interruption anywhere from there on is never taken for "not committed".
_PREPARED, _COMMITTING, _COMMITTED = "prepared", "committing", "committed"


def _signals_to_hold():
    """The signals whose handler runs Python code (Ctrl+C's
    ``KeyboardInterrupt`` and any handler a caller installed): held back
    while the repair commits. Empty where the OS cannot mask signals
    (Windows) or off the main thread (only the main thread runs Python
    signal handlers, and a mask there would not stop delivery)."""
    if not hasattr(signal, "pthread_sigmask"):
        return None
    if threading.current_thread() is not threading.main_thread():
        return None
    held = set()
    for sig in signal.valid_signals():
        try:
            if callable(signal.getsignal(sig)):
                held.add(sig)
        except (OSError, ValueError):
            pass
    return held or None


def _original_still_active(state: str, path: Path, raw: bytes) -> bool:
    """True only while the active file is KNOWN to hold the original bytes:
    before the commit began, or when reading it back proves the replace did
    not happen. Any doubt (it cannot be read, a second interruption) is
    False, so the aside is kept."""
    if state == _PREPARED:
        return True
    if state == _COMMITTED:
        return False
    try:
        return path.read_bytes() == raw
    except BaseException:
        return False


def _clean_orphan_repair_temps(path: Path) -> None:
    """Housekeeping after a completed repair: temp files an earlier repair
    left when it was killed before its replace (under the lock, no other
    repair is running, so every one found is an orphan)."""
    for orphan in path.parent.glob(_REPAIR_TEMP_GLOB):
        _discard(orphan)


def reset(folder: Optional[Path] = None, discard_newer: bool = False,
          edition: Optional[str] = None) -> Optional[Path]:
    """Drop every tools' value and turn advanced mode off, writing an empty
    valid store. A bad file (or, with ``discard_newer``, a newer one) is kept
    aside first as ``cli_settings.bad-<timestamp>.json``, never deleted.
    Returns the set-aside file's path, or None. Plain reset of a newer file
    raises NewerStore (it may hold what a newer app needs).

    W6 fix round 2 (N1): the repair is atomic from every caller's view. Under
    the lock: (1) the fresh store is written to a temp file, (2) the bad
    file's bytes are copied aside, (3) the temp replaces the active file in
    one ``os.replace``. A failure at any step leaves the active file exactly
    as it was (so every CLI keeps stopping with ``store.bad_file`` /
    ``store.newer_version``), removes what this call created, and raises
    StoreWriteFailed. The active file is never absent.

    W6 fix round 3 (N3): the aside is removed only while the active file is
    known to still hold the original bytes. The commit state is set to
    "committing" before the replace, and the signals that run Python
    handlers (Ctrl+C) are held back from just before it until the state is
    "committed" (``pthread_sigmask``; on Windows the state rule alone keeps
    the aside). Once the repair has committed, a Ctrl+C or any failure
    keeps the aside. A completed repair also removes repair temps an earlier
    killed repair left behind."""
    path = _require_path(folder)
    moved = None
    with _locked(path):
        raw = _read_raw(path)
        if raw is not None:
            try:
                _parse_document(path, raw)
            except NewerStore:
                if not discard_newer:
                    raise
                moved = _aside_name(path.parent)
            except BadStore:
                moved = _aside_name(path.parent)
        from core.fs_safety import _fsync_dir
        temp = _repair_temp_name(path)
        aside_made = False
        state = _PREPARED
        held = _signals_to_hold()
        old_mask = None
        try:
            if held:
                old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())
            with _write_guard(path):
                _write(temp, empty_document())                  # (1)
                if moved is not None:
                    _copy_aside(raw, moved)                     # (2)
                    aside_made = True
                if held:
                    signal.pthread_sigmask(signal.SIG_BLOCK, held)
                state = _COMMITTING
                os.replace(temp, path)                          # (3)
                state = _COMMITTED
            _fsync_dir(path.parent)
        except BaseException:
            _discard(temp)
            if aside_made and _original_still_active(state, path, raw):
                _discard(moved)
            raise
        finally:
            if old_mask is not None:
                # A Ctrl+C held back above is raised here, after the commit
                # state is recorded: the aside is already safe.
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        _clean_orphan_repair_temps(path)
    return moved
