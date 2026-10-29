# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one choke point for settings an AI writes (SPEC-SET-003 §4.5b, AI
setting redesign fix round 3).

While an AI-originated command runs (every Pro remote command, every request
the in-app request service handles), ``ai_writer()`` marks the writer as AI.
``SettingsManager``'s write paths (``set``, through which every section,
map and preset write goes, the locks, the full reset, the API keys file;
installed by ``guard`` right under the class) call ``check`` with the key
they are about to write; in that context the registered policy
(``managers.ai_write_policy``) decides, and a refused write raises
``AIWriteRefused`` before anything changes. Outside the context (the user's
own clicks, the AI setting panel's Allow) ``check`` does nothing.

A refused write ends the whole command: ``ai_writer`` puts back every value
it had written (memory and saved file, ``ai_write_restore``): never part of
them. Stdlib only (the settings manager imports this module; the policy
registers itself here).
"""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

Checker = Callable[[Any, str, Any], Optional[Dict[str, Any]]]

_CHECKERS: List[Checker] = []
_ROLLBACK: List[Callable] = []     # the path-wise rollback (ai_write_restore)
_STATE = threading.local()


class AIWriteRefused(BaseException):
    """A write an AI-originated command may not make; ``reply`` is the
    refusal (``{"status": "refused", "reason": ..., "key": ...}``).

    A ``BaseException`` on purpose: the app's ``except Exception`` guards
    around a settings write must not swallow a refusal (the command would
    answer ``ok``). Only ``ai_writer`` and the two dispatchers catch it."""

    def __init__(self, reply: Dict[str, Any]):
        super().__init__(f"refused ({reply.get('reason')}): {reply.get('key')}")
        self.reply = dict(reply)


def register_rollback(fn: Callable) -> None:   # the policy: ai_write_restore.roll_back
    _ROLLBACK[:] = [fn]


def register_checker(checker: Checker) -> None:
    """The policy (idempotent): ``checker(settings, key, value)`` -> None or a refusal."""
    if checker not in _CHECKERS:
        _CHECKERS.append(checker)


def active() -> bool:
    """True while an AI-originated command runs on this thread."""
    return bool(getattr(_STATE, "frames", None))


def _frame() -> Optional[Dict[str, Any]]:
    frames = getattr(_STATE, "frames", None)
    return frames[-1] if frames else None


def check(settings: Any, key_path: str, value: Any) -> None:
    """Before every settings write of ``key_path``: outside an AI context nothing;
    inside, the policy decides (a refusal raises; no policy: refused, fail closed)."""
    frame = _frame()
    if frame is None:
        return
    replies = [checker(settings, key_path, value) for checker in _CHECKERS] or [
        {"status": "refused", "reason": "unavailable", "key": key_path}]
    for reply in filter(None, replies):   # remembered: a Qt slot may swallow the raise
        frame.setdefault("refused", reply)
        raise AIWriteRefused(reply)
    for each in _STATE.frames:            # every open command, nested ones too
        _remember(each, settings)
        each["written"].setdefault(id(settings), []).append(key_path)


def _remember(frame: Dict[str, Any], settings: Any) -> None:
    """Snapshot ``settings`` the first time this command writes to it."""
    key = id(settings)
    if key in frame["snapshots"]:
        return
    path = getattr(settings, "_config_path", None)
    saved = None
    if isinstance(path, str):
        try:
            with open(path, "rb") as fh:
                saved = fh.read()
        except OSError:
            saved = None
    frame["snapshots"][key] = (settings, copy.deepcopy(getattr(settings, "_settings", None)),
                               list(getattr(settings, "_pending_writes", [])), path, saved)


def _roll_back(frame: Dict[str, Any]) -> List[str]:
    """Put back what the refused command wrote (the policy registers
    ``ai_write_restore.roll_back``); returns the dot-paths put back."""
    for fn in _ROLLBACK:
        return fn(frame["snapshots"], frame["written"], _write_back)
    return []


def _write_back(path: str, data: bytes) -> None:
    import os
    import tempfile
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".ai_rollback_", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:                                             # pragma: no cover
        try:
            os.unlink(tmp)
        except OSError:
            pass


def edition() -> Optional[str]:
    """The edition the running AI command was given (``ai_writer``)."""
    frame = _frame()
    return frame.get("edition") if frame is not None else None


def origin() -> Optional[str]:
    """``"remote"`` while a Pro remote command runs (``ai_writer``)."""
    frame = _frame()
    return frame.get("origin") if frame is not None else None


@contextmanager
def ai_writer(edition: Optional[str] = None, origin: Optional[str] = None,
              on_undone: Optional[Callable[[List[str]], None]] = None):
    """Mark the writes made inside as AI-originated (see the module); a
    refused write rolls back the command's earlier writes and re-raises.
    ``edition``: for the policy (default: the running one). ``origin``:
    ``"remote"`` for the Pro remote (panel-only keys are ordinary there).
    ``on_undone(keys)``: run after a rollback, outside this command, so the
    window shows the keys put back (``setting_live_apply.readopt``)."""
    frames = getattr(_STATE, "frames", None)
    if frames is None:
        frames = _STATE.frames = []
    frame = {"snapshots": {}, "written": {}, "edition": edition, "origin": origin}
    frames.append(frame)
    undone: List[str] = []
    try:
        yield
        if frame.get("refused"):          # refused, then swallowed on the way (R4-N1)
            raise AIWriteRefused(frame["refused"])
    except AIWriteRefused:
        undone = _roll_back(frame)
        raise
    finally:
        frames.remove(frame)
        if undone and on_undone is not None:
            try:
                on_undone(undone)
            except Exception:                                   # pragma: no cover
                pass


def _wrap(method, path_of):
    """``method`` with ``check`` first (``path_of``: what it writes, or None)."""
    import functools
    if getattr(method, "_ai_guarded", False):
        return method

    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        written = path_of(self, *args, **kwargs)
        if written is not None:
            check(self, *written)
        return method(self, *args, **kwargs)
    guarded._ai_guarded = True
    return guarded


def guard(cls) -> None:
    """Put ``check`` in front of every write path of ``SettingsManager``
    (called right under the class, which so does not grow: SI ratchet).
    ``set`` covers section, map and preset writes, section resets and
    ``persist_runtime_change``. Idempotent."""
    cls.set = _wrap(cls.set, lambda self, key_path, value, *a, **k: (key_path, value))
    cls.set_locked = _wrap(cls.set_locked,
                           lambda self, key_path, locked, *a, **k: ("locks." + key_path, locked))
    cls.reset_to_defaults = _wrap(cls.reset_to_defaults,
                                  lambda self, section=None, *a, **k: None if section else ("", None))
    cls._save_env = _wrap(cls._save_env, lambda self, *a, **k: ("env", None))
