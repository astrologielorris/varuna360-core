# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The app settings request service, Qt-free half (SPEC-SET-003 §4.5b, D-14).

An AI changes one of the APP's own settings (what the Settings tab shows)
only through this service: ``settings.py set --app`` from a terminal, and the
in-app task tool ``set_app_setting`` (both engines). This module holds what
needs no Qt and no writable settings manager:

- ``check_request``: the request itself is acceptable. The key exists in
  the registry, is a calculation setting (``rules.cli == "calculation"``,
  D-16) classified ``rules.writable == "ai"`` (INV-17: the consent, the
  app's toggle and every other protected key are refused ``protected``),
  belongs to the app's edition, and the value passes the entry's type,
  choices, bounds and ``rules.validate``. One classification with
  ``settings.py`` (``cli_store.check``), so the two can never disagree.
- ``toggle_on`` / ``read_saved``: the app's toggle
  ``ai.allow_app_settings_changes``, read FRESH from the saved settings file
  (instances do not hot-reload each other, so switching it off in any window
  takes effect for the next request everywhere). Unreadable, missing,
  legacy or anything but ``true``: off.
- ``preflight``: both, in that order; a refusal never needs a writable
  manager, so a refused request leaves the settings file byte-identical.
- ``RequestMemory``: request ids, scoped to one app instance, remembered
  10 minutes. The same id with the same payload returns the first reply
  without applying again; the same id with another payload is refused.
- ``reply_message``: the words for a reply, through the pending-copy gate
  (``cli_text``): the approved D-14 and D-17 sentences verbatim, every other
  reply in its structured form until its draft is approved (D-21).

Replies are plain dicts: ``{"status": ..., ...}`` with status ``applied``
(``key``, ``value``), ``refused`` (``reason``, ``key``), ``stale`` (``key``,
``current``), ``not_saved`` (``key``, ``error``) or ``no_app``.

The GUI-thread transaction (lock check, fresh toggle, ``seen``, set and
synchronous save, restore on failure, change notification) is
``managers/app_settings_requests.py``; the transport is ``core/app_endpoint``.
"""
from __future__ import annotations

import copy
import errno
import json
import logging
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.settings_registry import cli_store, cli_text

_log = logging.getLogger(__name__)

OP = "set_app_setting"
TOGGLE_KEY = "ai.allow_app_settings_changes"
REQUEST_TTL_S = 600.0                   # request ids are remembered 10 minutes

# Reply statuses (spec §4.5b).
APPLIED, REFUSED, STALE, NOT_SAVED, NO_APP = (
    "applied", "refused", "stale", "not_saved", "no_app")

# Refusal reasons. The first five are cli_store's own codes (one vocabulary
# with settings.py).
UNKNOWN_KEY = cli_store.UNKNOWN_KEY
OTHER_EDITION = cli_store.OTHER_EDITION
PROTECTED = cli_store.PROTECTED
NOT_CALCULATION = cli_store.NOT_CALCULATION
BAD_VALUE = cli_store.BAD_VALUE
TOGGLE_OFF = "toggle_off"               # D-14: the app's toggle is off
MCP_OFF = "mcp_off"                     # SPEC-LMCP-001 INV-6: AI apps switched off
MCP_KEY = "ai.mcp.enabled"
LOCKED = "locked"                       # the key is locked in the app (the user's lock)
DUPLICATE_ID = "duplicate_id"           # a request id reused with another payload
BAD_REQUEST = "bad_request"             # the request object itself is malformed
WINDOW_CLOSED = "window_closed"         # the task's own window is gone (D-18)
TARGET_GONE = "target_gone"             # settings.py's chosen instance went away
TIMEOUT = "timeout"                     # no reply within the client's timeout
BUSY = "busy"                           # the settings file lock stayed held
ENDPOINT_UNAVAILABLE = "endpoint_unavailable"   # an app runs (liveness marker) without a reachable endpoint
# AI setting redesign (td-bztjj, SPEC-EDN-001 D-3): a key that decides where
# data goes or what it costs (``ai_access.ASK_FIRST``) is changed only once the
# user allows it in the AI setting panel; every other route is refused this.
ASK_FIRST = "ask_first"
# The machine field of an ``applied`` planet size scale that left the
# user's locked planets as they were (fix RD-7): their names.
KEPT_FIELD = "kept"

# Which message key each reply shows (cli_text). A refusal reason not listed
# here shows the generic ``app.refused`` structured form.
_REASON_KEYS = {
    TOGGLE_OFF: "set.app_refused",      # approved D-14, verbatim
    PROTECTED: "set.protected",         # approved D-17, verbatim
    UNKNOWN_KEY: "set.unknown_key",
    OTHER_EDITION: "set.unknown_key",
    NOT_CALCULATION: "set.not_calculation",
    BAD_VALUE: "set.bad_value",
    LOCKED: "app.locked",
    WINDOW_CLOSED: "app.window_closed",
    BUSY: "app.busy",
    ENDPOINT_UNAVAILABLE: "app.endpoint_unavailable",
    ASK_FIRST: "app.ask_first",
}


# ``outcome`` of a reply whose effect cannot be known (W6b fix round 1): a
# timeout, or a target that closed after the request reached it. The app may
# have applied the change: such a reply never says nothing changed.
OUTCOME_UNKNOWN = "unknown"


def transport_refusal(reason: str, key: Optional[str] = None,
                      delivered: bool = True) -> Dict[str, Any]:
    """A refusal produced by the transport, not by the app: ``timeout``
    always carries ``outcome: unknown``; any other reason carries it when
    the request may have been delivered."""
    if reason == TIMEOUT or delivered:
        return refusal(reason, key, outcome=OUTCOME_UNKNOWN)
    return refusal(reason, key)


def refusal(reason: str, key: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
    reply = {"status": REFUSED, "reason": reason}
    if key is not None:
        reply["key"] = key
    reply.update(fields)
    return reply


# ------------------------------------------------------------------ checks

def check_request(key: Any, value: Any, edition: str,
                  app_keys: bool = False, panel: bool = False) -> Optional[Dict[str, Any]]:
    """None when ``key`` = ``value`` may be requested from an app of
    ``edition`` (``lite`` or ``pro``), else the refusal. Order: unknown key,
    other edition, protected (INV-17), not a calculation key (D-16), bad value.
    ``app_keys`` (the in-app request service, AI setting redesign td-bztjj):
    app keys classified ``ai`` are requestable too; the terminal routes
    (``settings.py set --app``, the offline route) leave it False, so D-16
    holds there. ``panel``: the AI setting panel's Allow (in-process only,
    fix RD-3): the ``ai_access.PANEL_ONLY`` keys too. Never touches a file."""
    reason = cli_store.check(key, value, edition, app_keys=app_keys, panel=panel)
    if reason is None and not (panel and is_panel_only(key)):
        # INV-17, stated directly: only an entry classified ``ai`` is
        # requestable (cli_store.check implies it for calculation keys).
        from core import settings_registry as registry
        from core.settings_registry.rules import WRITABLE_AI
        rules = registry.get(key).rules
        if rules is None or rules.writable != WRITABLE_AI:
            reason = PROTECTED
    if reason is None:
        return None
    if reason == BAD_VALUE:
        return refusal(BAD_VALUE, key, value=value, choices=cli_store.allowed_values(key))
    return refusal(reason, key if isinstance(key, str) else None)


def needs_asking(key: Any) -> bool:
    """True when ``key`` is a registry key the AI may change only once the
    user allows it (``ai_access.ASK_FIRST``, SPEC-EDN-001 D-3)."""
    from core.settings_registry.ai_access import ASK_FIRST
    return isinstance(key, str) and key in ASK_FIRST


def is_panel_only(key: Any) -> bool:
    """True for a calculation key the AI setting panel alone may change, on
    the user's Allow (``ai_access.PANEL_ONLY``, fix RD-3)."""
    from core.settings_registry.ai_access import PANEL_ONLY
    return isinstance(key, str) and key in PANEL_ONLY


def direct_write_refusal(key: Any, value: Any, edition: str,
                         settings, panel_only: bool = False) -> Optional[Dict[str, Any]]:
    """The policy of a write that does not go through the request service
    (the Pro remote ``set_setting``, fix RD-1), the service's own, before
    anything is written. None = the write may go on; else the refusal:

    - ``check_request`` with the in-app classification: a key outside the
      registry (app and runtime state included), a protected key (the
      consents, the app's toggle, the screenshot notice flag) or one not
      classified ``ai``, a panel-only key, a bad value;
    - ``ask_first``: such a key changes only on the AI setting panel's
      Allow, in-process; no request field (``confirmed``) counts;
    - ``locked``: the user's lock, saved or in this window's memory (a
      planet size scale is refused only when every planet is locked; the
      locked ones are kept, ``planet_sizes.kept_planets``).

    ``settings``: the window's ``SettingsManager``. ``panel_only``: the
    panel-only keys (``ai_access.PANEL_ONLY``) are ordinary preferences on
    this route (the Pro remote, Lorris 2026-10-11: agents drive the app
    through it for reference collection and tests); they stay refused on
    every request route."""
    refused = check_request(key, value, edition, app_keys=True,
                            panel=panel_only and is_panel_only(key))
    if refused is not None:
        return refused
    if needs_asking(key):
        return refusal(ASK_FIRST, key, value=copy.deepcopy(value))
    path = getattr(settings, "_config_path", None)
    saved = read_saved(path) if isinstance(path, (str, os.PathLike)) else None

    def locked(k):
        return saved_locked(saved, k) or bool(settings.is_locked(k))
    if lock_covers(locked, key):
        return refusal(LOCKED, key)
    from core.settings_registry import planet_sizes
    kept = planet_sizes.kept_planets(key, locked)
    if kept and len(kept) == len(planet_sizes.PLANETS):
        return refusal(LOCKED, key)
    return None


def lock_covers(locked: Callable[[str], bool], key: str) -> bool:
    """True when ``key`` or one of its groups is locked (fix round 3, R3-3:
    a lock on ``chart_display`` or ``chart_display.planet_sizes`` covers
    every leaf under it). ``locked``: the lock test of one exact path."""
    parts = str(key).split(".")
    return any(locked(".".join(parts[:n])) for n in range(len(parts), 0, -1))


def read_saved(path) -> Optional[Dict[str, Any]]:
    """The saved settings document at ``path``, read only (never created,
    never locked). None when missing, unreadable or not a JSON object."""
    try:
        with open(Path(path), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def saved_value(saved: Optional[Dict[str, Any]], key: str, default: Any = None) -> Any:
    node: Any = saved
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def toggle_on(saved: Optional[Dict[str, Any]]) -> bool:
    """The app's toggle in a saved settings document: on only when it is
    exactly ``true`` (missing, legacy, damaged or any other value: off)."""
    return saved_value(saved, TOGGLE_KEY, False) is True


def saved_locked(saved: Optional[Dict[str, Any]], key: str) -> bool:
    """The user's lock on ``key`` in a saved settings document (the flat
    ``locks`` dict keyed by the full dot path, as ``SettingsManager``
    writes it). W6b fix F2: requests are refused from THIS state, read with
    the toggle, never from a manager's in-memory copy alone (instances do not
    hot-reload each other's locks; ``SettingsManager.set`` ignores locks)."""
    locks = saved.get("locks") if isinstance(saved, dict) else None
    return isinstance(locks, dict) and bool(locks.get(key, False))


# A request made for an AI app outside Varuna360 (SPEC-LMCP-001 INV-6): set
# around one request by its caller (the MCP process's offline route, the
# window's service for ``origin: "mcp"``); every authorization of that request,
# the one under the settings lock included, then also needs ``ai.mcp.enabled``
# in the saved file. The app's own AI tasks never set it.
import contextvars as _contextvars                                  # noqa: E402
MCP_ORIGIN = _contextvars.ContextVar("varuna360_mcp_origin", default=False)


def mcp_refusal(saved_settings: Optional[Dict[str, Any]],
                key: Any = None) -> Optional[Dict[str, Any]]:
    """``mcp_off`` when the current request is an AI app's and the saved file
    does not say ``ai.mcp.enabled: true``; else None."""
    if MCP_ORIGIN.get() and saved_value(saved_settings, MCP_KEY, False) is not True:
        return refusal(MCP_OFF, key if isinstance(key, str) else None)
    return None


def preflight(key: Any, value: Any, edition: str,
              saved_settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The read-only preflight (spec §4.5b): ``check_request``, then the
    key's lock and the toggle in ``saved_settings`` (the saved file, read
    fresh by the caller, ``read_saved``). None = go on; else the refusal.
    The offline route runs it again under the settings-file lock."""
    refused = check_request(key, value, edition)
    if refused is not None:
        return refused
    if lock_covers(lambda path: saved_locked(saved_settings, path), key):
        return refusal(LOCKED, key)
    if not toggle_on(saved_settings):
        return refusal(TOGGLE_OFF, key)
    return mcp_refusal(saved_settings, key)


def parse_request(request: Dict[str, Any]):
    """(key, value, seen, seen_given) of an endpoint request, or a
    ``bad_request`` refusal. ``seen`` absent or null = not given."""
    if not isinstance(request, dict) or "key" not in request or "value" not in request:
        return refusal(BAD_REQUEST)
    key = request.get("key")
    if not isinstance(key, str):
        return refusal(BAD_REQUEST)
    seen = request.get("seen")
    return key, request.get("value"), seen, seen is not None


# ------------------------------------------------------------------ request ids

def payload_fingerprint(key: Any, value: Any, seen: Any) -> str:
    """What makes two requests the same request (id reuse check)."""
    return json.dumps({"key": key, "value": value, "seen": seen},
                      sort_keys=True, ensure_ascii=False, default=repr)


class RequestMemory:
    """Request ids of one app instance, remembered ``ttl`` seconds.
    Thread-safe; ``clock`` is injectable for tests.

    An id is RESERVED before its request runs (W6b fix round 1, leftover):
    a second request with the same id that arrives while the first is still
    in flight waits for the first reply (same payload) or is refused
    ``duplicate_id`` (another payload); it never runs ``compute`` again. The
    endpoint applies on the GUI thread one at a time, so this guards direct
    callers from other threads; a re-entrant call with an id in flight on
    the SAME thread is refused ``busy`` (waiting would never end)."""

    IN_FLIGHT_WAIT_S = 30.0

    def __init__(self, ttl: float = REQUEST_TTL_S,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl = float(ttl)
        self._clock = clock
        # id -> [time, fingerprint, reply or None while in flight, done event, owner thread]
        self._seen: Dict[str, list] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        for rid in [r for r, e in self._seen.items()
                    if e[2] is not None and now - e[0] >= self.ttl]:
            del self._seen[rid]

    def handle(self, request_id: str, fingerprint: str,
               compute: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        """The reply to request ``request_id``: the first reply again when
        the id was seen with the same payload, a ``duplicate_id`` refusal
        when it was seen with another, else ``compute()`` (remembered)."""
        with self._lock:
            now = self._clock()
            self._expire(now)
            known = self._seen.get(request_id)
            if known is None:
                entry = [now, fingerprint, None, threading.Event(), threading.get_ident()]
                self._seen[request_id] = entry
        if known is not None:
            if known[1] != fingerprint:
                return refusal(DUPLICATE_ID)
            if known[2] is None:
                if known[4] == threading.get_ident():
                    return refusal(BUSY)
                known[3].wait(self.IN_FLIGHT_WAIT_S)
                if known[2] is None:
                    return refusal(BUSY)
            return copy.deepcopy(known[2])
        try:
            reply = compute()
        except BaseException:
            with self._lock:
                if self._seen.get(request_id) is entry:
                    del self._seen[request_id]
            entry[3].set()
            raise
        with self._lock:
            entry[0] = self._clock()
            entry[2] = copy.deepcopy(reply)
        entry[3].set()
        return reply

    def __len__(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return len(self._seen)


# ------------------------------------------------------------------ words

def message_key(reply: Dict[str, Any]) -> str:
    """The cli_text key a reply is shown with."""
    status = reply.get("status")
    if status == APPLIED:
        return "app.offline_applied" if reply.get("offline") else "app.applied"
    if status in (STALE, NOT_SAVED, NO_APP):
        return "app." + status
    if reply.get("reason") == BAD_VALUE:
        # W6d fix F2: no fixed list of values (``choices`` null) = its own
        # pending key; the approved sentence always names the choices.
        return cli_text.bad_value_key(reply.get("choices"))
    return _REASON_KEYS.get(reply.get("reason"), "app.refused")


def reply_message(reply: Dict[str, Any]) -> str:
    """The reply in words: approved wording verbatim, else the structured
    form ``<key>: <field>=<value> ...`` (never a marker, never empty).

    A reply field that is present with the value None (a tool request's
    ``value: null``, a saved ``current`` that is null) is passed on as a
    fact: the approved words show ``null`` (W6d fix F1/F3), the reply's own
    JSON field keeps its null."""
    key = message_key(reply)
    fields = {k: v for k, v in reply.items()
              if k not in ("status", "offline", "v", "id", "target", "message")}
    if key == "app.refused":
        fields = {"reason": reply.get("reason"), **fields}
    else:
        fields.pop("reason", None)          # the message key already says it
    return cli_text.message(key, **fields)


# ------------------------------------------------------------------ the settings file lock
#
# The offline route (no app running), app startup and the app's request
# transaction share the lock the app's SettingsManager already takes around
# every save: ``app_settings.json.lock`` in the user-data folder
# (``state.profile_store``'s advisory lock: flock on Linux and macOS, msvcrt on
# Windows). An offline write holds it from its re-check (no live endpoint, no
# live instance marker) to its save; an app starting publishes its marker,
# then waits for the lock before it reads the file (``startup_wait``), so it
# starts with the change or the offline write refuses.

SETTINGS_FILENAME = "app_settings.json"
LOCK_SUFFIX = ".lock"
STARTUP_WAIT_S = 5.0          # app startup logs a still-held settings lock every this many seconds
OFFLINE_LOCK_S = 10.0         # settings.py waits at most this long for the lock
SERVICE_LOCK_S = 3.0          # the app's request transaction waits at most this long (busy)


class SettingsBusy(Exception):
    """The settings file lock stayed held for the whole wait."""


class TransactionThreadError(RuntimeError):
    """``SettingsTransaction.reentrant`` called from a thread that does not
    own the transaction (or on one not held)."""


def settings_path(folder) -> Path:
    return Path(folder) / SETTINGS_FILENAME


def _lock_path(folder) -> Path:
    return Path(str(settings_path(folder)) + LOCK_SUFFIX)


class SettingsTransaction:
    """The settings-file transaction (W6b fix F1): the kernel lock on
    ``app_settings.json.lock`` held by this process from the authoritative
    read of the saved file (``read``) to the commit (the ``os.replace`` of
    the manager's save, inside ``reentrant()``). Another process's save, a
    revocation of the toggle or a lock from another window included, lands
    either before the read (and is seen) or after the commit.

    Inside ``reentrant()`` the SettingsManager's own save takes the lock
    again without waiting: it opens its own handle, and an advisory lock on
    another handle of the same file would refuse it, although this process
    already holds it. That exemption is scoped to the THREAD that holds the
    transaction and to the SAME lock file (``st_dev``/``st_ino``); any other
    thread, and any other file, goes through the real lock as before.

    The transaction belongs to the thread that entered it (W6b fix round 2,
    leftover 1): ``reentrant()`` from any other thread raises
    ``TransactionThreadError``, so handing the object to a worker can never
    give that worker the exemption."""

    def __init__(self, folder, timeout: float):
        self.folder = Path(folder)
        self.timeout = float(timeout)
        self.handle = None
        self.owner = None                 # thread ident of the entering thread

    def __enter__(self):
        import state.profile_store as profile_store
        self.handle = open(_lock_path(self.folder), "a+b")
        if not profile_store._acquire_lock(self.handle, self.timeout):
            self.handle.close()
            self.handle = None
            raise SettingsBusy(str(_lock_path(self.folder)))
        self.owner = threading.get_ident()
        return self

    def __exit__(self, *exc):
        import state.profile_store as profile_store
        if self.handle is not None:
            try:
                profile_store._release_lock(self.handle)
            finally:
                self.handle.close()
                self.handle = None
                self.owner = None
        return False

    def read(self) -> Optional[Dict[str, Any]]:
        """The saved settings document, read under the lock (authoritative
        until the transaction ends)."""
        return read_saved(settings_path(self.folder))

    def identity(self):
        return _file_identity(self.handle)

    def reentrant(self):
        """Context: this thread's settings-manager saves on the SAME lock
        file succeed at once (this process holds it); nothing else changes.
        Only the thread that entered the transaction may call it."""
        if self.handle is None:
            raise TransactionThreadError("the settings transaction is not held")
        if threading.get_ident() != self.owner:
            raise TransactionThreadError(
                "the settings transaction belongs to another thread")
        return _reentry(self.identity())


# Backward-compatible name (W6b): the offline route's lock.
_HeldLock = SettingsTransaction


def _file_identity(handle):
    import os
    try:
        info = os.fstat(handle.fileno())
    except (OSError, ValueError, AttributeError):
        return None
    return (info.st_dev, info.st_ino)


_reentry_guard = threading.Lock()
_reentry_state = {"depth": 0, "acquire": None, "release": None}
_reentry_local = threading.local()


def _held_by_this_thread(handle) -> bool:
    held = getattr(_reentry_local, "held", None)
    if not held:
        return False
    ident = _file_identity(handle)
    return ident is not None and ident in held


def _reentrant_acquire(handle, timeout_s):
    if _held_by_this_thread(handle):
        return True
    return _reentry_state["acquire"](handle, timeout_s)


def _reentrant_release(handle):
    if _held_by_this_thread(handle):
        return None
    return _reentry_state["release"](handle)


def _reentry(ident):
    from contextlib import contextmanager
    import state.profile_store as profile_store

    @contextmanager
    def scope():
        if ident is None:
            raise OSError("the settings lock file cannot be identified")
        with _reentry_guard:
            if _reentry_state["depth"] == 0:
                _reentry_state["acquire"] = profile_store._acquire_lock
                _reentry_state["release"] = profile_store._release_lock
                profile_store._acquire_lock = _reentrant_acquire
                profile_store._release_lock = _reentrant_release
            _reentry_state["depth"] += 1
        held = getattr(_reentry_local, "held", None)
        if held is None:
            held = _reentry_local.held = []
        held.append(ident)
        try:
            yield
        finally:
            held.remove(ident)
            with _reentry_guard:
                _reentry_state["depth"] -= 1
                if _reentry_state["depth"] == 0:
                    if profile_store._acquire_lock is _reentrant_acquire:
                        profile_store._acquire_lock = _reentry_state["acquire"]
                    if profile_store._release_lock is _reentrant_release:
                        profile_store._release_lock = _reentry_state["release"]
                    _reentry_state["acquire"] = _reentry_state["release"] = None
    return scope()


# ------------------------------------------------------------------ app startup (F3, F3-R1)

NO_FOLDER = "no_folder"                 # no user-data folder yet: nothing to write offline
SETTINGS_LOCK = "settings_lock"         # no marker of any kind: the settings lock is kept
LOCK_UNOPENABLE = "lock_unopenable"     # the lock file cannot be opened (a detail, never an exclusion)
MAX_WAIT = "max_wait"                   # a bounded wait ran out, the lock held elsewhere (tests)
MAX_WAIT_UNOPENABLE = "max_wait_unopenable"  # a bounded wait ran out, the lock unopenable
STARTUP_POLL_S = 0.1                    # the lock is tried this often while waiting
EXCLUSION_RETRY_S = 1.0                 # an unopenable lock: the markers are retried this often


class StartupResult(dict):
    """What ``startup_wait`` established (a dict, so it logs and serialises
    as is; true when the read that follows is protected).

    ``protected``: the app may read its settings now. ``exclusion``: how an
    offline ``settings.py set --app`` is kept out from here on: ``marker`` /
    ``fallback_marker`` / ``sentinel`` (``core.app_endpoint.liveness``),
    ``settings_lock`` (none of the three could be published: this process
    keeps the settings-file lock until its endpoint or a marker is published,
    ``release_startup_hold``) or ``no_folder``. ``lock``: ``lock_unopenable``
    when the settings-file lock could not be opened and a marker excludes the
    offline route on its own (W6b fix F3-R2: an unopenable lock is never an
    exclusion; without a marker the startup waits until the lock opens).
    ``waited``: seconds spent waiting for the lock. ``errors``: why markers
    failed, and why the lock could not be opened. ``reason``: why it is not
    protected (``max_wait``, a bounded test wait)."""

    def __bool__(self) -> bool:
        return bool(self.get("protected"))

    @property
    def protected(self) -> bool:
        return bool(self.get("protected"))

    @property
    def exclusion(self) -> Optional[str]:
        return self.get("exclusion")


class _StartupHold:
    """The settings-file lock kept by this process while it has no marker of
    any kind (F3-R1, last resort): an offline writer arriving meanwhile waits
    and is refused ``busy``. The holding thread (the GUI thread, which reads
    and saves the settings) passes its own lock calls through
    (``SettingsTransaction.reentrant``); any other thread waits as for
    another process. Released when the endpoint or a marker is published
    (``release_startup_hold``), else at process exit by the kernel."""

    def __init__(self):
        self.tx = None
        self.scope = None
        self.folder = None

    def keep(self, folder, tx: "SettingsTransaction") -> None:
        scope = tx.reentrant()
        scope.__enter__()
        self.tx, self.scope, self.folder = tx, scope, Path(folder)

    def held(self, folder=None) -> bool:
        if self.tx is None:
            return False
        return folder is None or Path(folder) == self.folder

    def release(self) -> bool:
        if self.tx is None:
            return False
        tx, scope = self.tx, self.scope
        self.tx = self.scope = self.folder = None
        try:
            scope.__exit__(None, None, None)
        finally:
            tx.__exit__(None, None, None)
        return True


_startup_hold = _StartupHold()


def startup_hold_active(folder=None) -> bool:
    return _startup_hold.held(folder)


def release_startup_hold() -> bool:
    """Drop the last-resort settings-lock hold (called by the endpoint's
    owner once the endpoint or a marker is published). Must run on the
    thread that took it. True when there was one."""
    released = _startup_hold.release()
    if released:
        _log.info("startup: settings lock hold released (instance now discoverable)")
    return released


def _current_uid() -> Optional[int]:
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else None


def _repair_lock_permission(folder, exc: OSError) -> bool:
    """W6b fix F3-R2: the settings-file lock could not be opened because of
    its own permission bits. When it is a regular file of THIS user (same
    uid; POSIX only), give its owner read and write again and say so in the
    log; True when repaired (the caller retries at once). Anything else (a
    folder at the lock's name, another owner, an unwritable folder, a
    process-local error such as EMFILE, Windows) is not repaired: False, and
    the caller keeps waiting."""
    if getattr(exc, "errno", None) not in (errno.EACCES, errno.EPERM):
        return False
    uid = _current_uid()
    if uid is None:
        return False
    path = _lock_path(folder)
    try:
        info = os.lstat(path)
    except OSError:
        return False
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or mode & 0o600 == 0o600:
        return False
    try:
        os.chmod(path, mode | 0o600)
    except OSError as chmod_exc:
        _log.warning("startup: the settings lock file %s cannot be opened (%s) and its "
                     "permission could not be repaired (%s)", path, exc, chmod_exc)
        return False
    _log.warning("startup: the settings lock file %s could not be opened (%s); it belongs "
                 "to this user, so its permission was repaired (%03o -> %03o)",
                 path, exc, mode, mode | 0o600)
    return True


class _Exclusion:
    """This process's liveness marker for ``folder`` (any kind), retried at
    most every ``EXCLUSION_RETRY_S`` while the settings lock cannot be
    opened: the marker is then the only exclusion there can be."""

    def __init__(self, folder, kind: Optional[str], errors: list):
        self.folder, self.kind, self.errors = folder, kind, errors
        self._next = time.monotonic() + EXCLUSION_RETRY_S

    def establish(self) -> Optional[str]:
        from core.app_endpoint import liveness
        try:
            self.kind = liveness.establish(self.folder)
        except OSError as exc:
            self.kind = None
            self._note(str(exc))
        return self.kind

    def __call__(self) -> bool:
        if self.kind is None and time.monotonic() >= self._next:
            self._next = time.monotonic() + EXCLUSION_RETRY_S
            self.establish()
        return self.kind is not None

    def _note(self, error: str) -> None:
        if error not in self.errors:
            self.errors.append(error)


def _acquire_startup_lock(folder, timeout: float, max_wait: Optional[float],
                          on_wait: Optional[Callable[[float], None]],
                          exclusion: Optional[_Exclusion] = None):
    """Wait for the settings-file lock: (transaction held, waited, reason).

    reason: None (held); ``lock_unopenable`` (the lock cannot be opened, and
    ``exclusion`` reports a marker: the read may go on without the lock);
    ``max_wait`` (the bound ran out, the lock held by another process);
    ``max_wait_unopenable`` (the bound ran out, the lock unopenable and no
    marker published).

    An unopenable lock is NOT an exclusion (W6b fix F3-R2): nothing keeps
    another process from repairing it and writing. A lock file of this user
    that only its permission bits keep closed is repaired
    (``_repair_lock_permission``, logged); otherwise this waits as for a held
    lock, retrying the markers, until the lock opens or a marker is
    published. Logs every ``timeout`` seconds; ``on_wait(waited)`` is called
    after every failed try (the collaborator's in-app signal)."""
    start = time.monotonic()
    next_log = timeout
    errors = exclusion.errors if exclusion is not None else []
    while True:
        tx = SettingsTransaction(folder, STARTUP_POLL_S)
        cause = None
        try:
            tx.__enter__()
            return tx, time.monotonic() - start, None
        except SettingsBusy:
            pass
        except OSError as exc:
            if _repair_lock_permission(folder, exc):
                continue
            cause = f"settings lock: {type(exc).__name__}: {exc}"
            if cause not in errors:
                errors.append(cause)
                _log.warning("startup: the settings file lock cannot be opened: %s", exc)
            if exclusion is not None and exclusion():
                return None, time.monotonic() - start, LOCK_UNOPENABLE
        waited = time.monotonic() - start
        if on_wait is not None:
            on_wait(waited)
        if waited >= next_log:
            if cause is None:
                _log.warning("startup: the settings file lock is held by another process "
                             "(%.0f s); still waiting before reading the settings", next_log)
            else:
                _log.warning("startup: the settings file lock cannot be opened and no "
                             "marker is published (%.0f s); still waiting before reading "
                             "the settings (%s)", next_log, cause)
            next_log += timeout
        if max_wait is not None and waited >= max_wait:
            return None, waited, MAX_WAIT if cause is None else MAX_WAIT_UNOPENABLE
        if cause is not None:
            time.sleep(STARTUP_POLL_S)        # the open fails at once: do not spin


def startup_wait(folder=None, timeout: float = STARTUP_WAIT_S, *,
                 max_wait: Optional[float] = None,
                 on_wait: Optional[Callable[[float], None]] = None) -> StartupResult:
    """App startup, before ANYTHING reads the settings file (W6b fix F3,
    F3-R1, F3-R2).

    1. Make this instance known to be alive (``liveness.establish``): the
       marker, else the fallback marker in the user-data folder, else the
       sentinel lock. From then on an offline ``settings.py set --app`` that
       takes the settings-file lock sees it (checked under that lock) and
       refuses.
    2. Take the settings-file lock. A holder is either an offline writer
       that has not checked the markers yet (it will refuse, and release) or
       one already past that check, which commits and releases: once the
       lock is ours, nothing can write offline any more, so the app's first
       read sees every committed offline write and no later one can land
       under it. With an exclusion from step 1 the lock is released at once;
       without one it is KEPT (``exclusion: settings_lock``) until the
       endpoint or a marker is published (``release_startup_hold``), so an
       offline writer arriving in between is refused ``busy``.
    3. A lock file that cannot be opened is not an exclusion (F3-R2). A lock
       file of this user closed only by its permission bits is repaired
       (logged). Otherwise the startup waits, as for a held lock, retrying
       the markers: it goes on when the lock opens (step 2) or when a marker
       is published (``lock: lock_unopenable``, the marker excludes).

    The wait has no limit (logged every ``timeout`` seconds; a kernel lock is
    held only by a live process and released at its exit); ``max_wait``
    bounds it for tests (then not protected, ``reason: max_wait`` or
    ``max_wait_unopenable``). ``on_wait(waited)`` runs after every failed
    try. A missing user-data folder returns at once and creates nothing:
    there is no settings file to write offline (the offline route refuses a
    missing file), and the endpoint's owner publishes the marker once the app
    runs. ``folder``: the user-data folder (default: the one the app will
    load, found read only). Returns a ``StartupResult``; the caller acts on
    it (``managers.app_settings_requests.startup_hook``)."""
    if folder is None:
        from core.capabilities.settings_view import resolve_settings_dir
        folder = resolve_settings_dir()
    if folder is None or not Path(folder).is_dir():
        return StartupResult(protected=True, exclusion=NO_FOLDER, waited=0.0, errors=[])
    errors = []
    exclusion = _Exclusion(folder, None, errors)
    if exclusion.establish() is None:
        _log.warning("startup: no liveness marker in %s (%s); keeping the settings "
                     "lock until the instance is discoverable", folder, "; ".join(errors))
    tx, waited, reason = _acquire_startup_lock(folder, timeout, max_wait, on_wait, exclusion)
    waited = round(waited, 3)
    kind = exclusion.kind
    if reason == LOCK_UNOPENABLE:
        # The lock cannot be opened, but a marker is published: an offline
        # writer that opens the lock (after a repair) sees it and refuses.
        return StartupResult(protected=True, exclusion=kind, lock=LOCK_UNOPENABLE,
                             waited=waited, errors=errors)
    if tx is None:
        return StartupResult(protected=False, exclusion=kind, waited=waited,
                             errors=errors, reason=reason)
    if kind is None and waited >= STARTUP_POLL_S:
        kind = exclusion.establish()          # the obstacle may be gone after a wait
    if kind is not None:
        tx.__exit__(None, None, None)
        return StartupResult(protected=True, exclusion=kind, waited=waited, errors=errors)
    _startup_hold.keep(folder, tx)
    return StartupResult(protected=True, exclusion=SETTINGS_LOCK, held=True,
                         waited=waited, errors=errors)


def secure_running_instance(folder, endpoint_started: Optional[bool] = None) -> Dict[str, Any]:
    """The endpoint owner's half (``AppEndpointServer.start_in``, F3-R1,
    F3-R2): the same exclusion as ``startup_wait`` for an instance that is
    already running. Called once BEFORE the endpoint starts
    (``endpoint_started`` None: establish a marker of any kind) and once
    after it (True/False). A marker or a published endpoint releases the
    startup hold; neither keeps it, or takes it now when this process has
    none (an app constructed without ``startup_wait``).

    It never returns after the endpoint failed without a marker, the endpoint
    or a held lock, except for the accepted bounded case: the lock HELD by
    another live process for ``OFFLINE_LOCK_S`` (an app constructed without
    ``startup_wait``, the test/developer path; logged). A lock that cannot be
    opened is repaired when it is this user's file closed by its permission
    bits (logged), else waited for without a limit, logged every
    ``STARTUP_WAIT_S`` seconds, retrying the markers. Returns
    ``{"exclusion": ..., "errors": [...]}``. Never raises."""
    out: Dict[str, Any] = {"exclusion": None, "errors": []}
    if not folder or not Path(folder).is_dir():
        return out
    exclusion = _Exclusion(folder, None, out["errors"])
    out["exclusion"] = exclusion.establish()
    if endpoint_started is None:
        return out
    if out["exclusion"] is not None or endpoint_started:
        out["exclusion"] = out["exclusion"] or "endpoint"
        release_startup_hold()
        return out
    if _startup_hold.held(folder):
        out["exclusion"] = SETTINGS_LOCK
        return out
    while True:
        tx, _waited, reason = _acquire_startup_lock(folder, STARTUP_WAIT_S,
                                                    OFFLINE_LOCK_S, None, exclusion)
        if reason != MAX_WAIT_UNOPENABLE:
            break
    if reason == LOCK_UNOPENABLE:
        out["exclusion"] = exclusion.kind
        return out
    if tx is None:
        out["errors"].append(f"settings lock: {reason}")
        _log.warning("app instance not discoverable and the settings lock not "
                     "taken (%s): an offline write is not excluded", reason)
        return out
    if exclusion.kind is not None or (_waited >= STARTUP_POLL_S
                                      and exclusion.establish() is not None):
        tx.__exit__(None, None, None)
        out["exclusion"] = exclusion.kind
        return out
    _startup_hold.keep(folder, tx)
    out["exclusion"] = SETTINGS_LOCK
    return out


def offline_set(folder, key: Any, value: Any, seen: Any = None, *, edition: str,
                endpoints_alive: Callable[[], bool],
                lock_timeout: float = OFFLINE_LOCK_S) -> Dict[str, Any]:
    """The offline route of ``settings.py set --app`` (spec §4.5b), used only
    when no app endpoint was alive when the command started.

    1. Read-only preflight (key, value, edition, the key's lock and the
       toggle in the saved file): a refusal never takes the lock, never constructs a writable
       manager, so the folder is byte-identical (also for a missing or a
       legacy settings file, whose toggle reads off).
    2. Take the settings file lock (bounded; held: ``busy``), re-check that
       no endpoint is alive (an app started meanwhile: ``busy``, the next try
       goes to it), preflight again on the file as it is now (the saved lock
       included: a locked key is refused ``locked``, W6b fix F2), check
       ``seen``.
    3. Construct the app's ``SettingsManager`` on that folder, set the key and
       save ONCE, all under the lock (the manager's own first-run and
       migration bookkeeping included, as on any app start).

    Replies as the app's own: ``applied`` with ``offline: true``,
    ``refused``, ``stale``, ``not_saved``."""
    folder = Path(folder)
    path = settings_path(folder)
    refused = preflight(key, value, edition, read_saved(path))
    if refused is not None:
        return refused
    try:
        with SettingsTransaction(folder, lock_timeout) as held:
            # Under the lock: an app that started meanwhile (its endpoint, or
            # only its liveness marker, which every app publishes before it
            # waits for this lock and reads the file, W6b fix F3) excludes
            # the offline write. The next try goes to it.
            from core.app_endpoint import liveness
            if endpoints_alive() or liveness.alive_instances(folder):
                return refusal(BUSY, key)
            saved = held.read()
            refused = preflight(key, value, edition, saved)
            if refused is not None:
                return refused
            from core import settings_registry as registry
            current = saved_value(saved, key, _MISSING_VALUE)
            if current is _MISSING_VALUE:
                current = registry.default(key)
            if seen is not None and current != seen:
                return {"status": STALE, "key": key, "current": copy.deepcopy(current)}
            with held.reentrant():
                from managers.settings_manager import SettingsManager
                manager = SettingsManager(config_dir=str(folder))
                ok = manager.set(key, copy.deepcopy(value))
            if not ok:
                return {"status": NOT_SAVED, "key": key,
                        "error": manager.last_error or "save failed"}
    except SettingsBusy:
        return refusal(BUSY, key)
    except OSError as exc:
        return {"status": NOT_SAVED, "key": key, "error": f"{type(exc).__name__}: {exc}"}
    return {"status": APPLIED, "key": key, "value": copy.deepcopy(value), "offline": True}


_MISSING_VALUE = object()
