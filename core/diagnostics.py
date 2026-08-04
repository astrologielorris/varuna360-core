# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Rotating diagnostics log (SPEC-SES-001 §4.3).

WHY THIS EXISTS
---------------
Until now every failure inside the session-save path was reported with
`debug_print()` (a no-op without --debug), `print()`, or `traceback.print_exc()`.
The shipped Windows build is built `--windowed` (build_windows.py:105), which
discards stdout and stderr entirely. So in the only environment where the bug
actually bites users, the evidence went nowhere and every user report was
unactionable.

WHERE THE LOG LIVES, AND WHY NOT THE DATA DIR
---------------------------------------------
`{bootstrap_dir}/logs/varuna360.log`, NOT `{user_data_dir}/logs/`.

The single most important failure this log has to capture is "the user data
directory is not writable" — a log inside that directory could not be written
at exactly the moment it is needed. The bootstrap directory is in the user's
home, is the same place `bootstrap.json` already lives, and is writable in
every scenario where the process can run at all.

THIS MODULE MUST NOT IMPORT PySide6
-----------------------------------
`state/__init__.py` imports `state.panel_mixin`, which imports PySide6. So
`from state.user_data import ...` would pull Qt into every CLI tool in
AI_tools/ that wants to log. That is why `_log_root()` recomputes the platform
switch locally instead of importing it.

The duplication is deliberate and guarded: `test/test_diagnostics.py`
asserts `_bootstrap_root() == state.user_data._bootstrap_dir()`, so the two
cannot drift apart silently. Do NOT "clean this up" by importing user_data.

NOTHING HERE MAY RAISE
----------------------
Every public function swallows its own errors. A logging failure must never
become a second failure on top of the one being logged — that is how a
diagnostics feature turns a degraded app into a crashed one.
"""
import logging
import os
import platform
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 512 * 1024
BACKUP_COUNT = 3
LOGGER_NAME = "varuna360"

_configured = False
_log_path = None


def _bootstrap_root():
    """Platform config root. Mirrors state.user_data._bootstrap_dir().

    Kept in sync by test/test_diagnostics.py::test_bootstrap_root_matches_user_data.
    """
    system = platform.system()
    if system == "Windows":
        # NOT ~/Documents/varuna360. NTFS is case-insensitive, so that path
        # and the default data dir ~/Documents/Varuna360 are the SAME folder,
        # which put the log inside the directory whose failures it exists to
        # record. A dot-prefixed directory is still visible in Explorer
        # (Windows hides by FILE_ATTRIBUTE_HIDDEN, not by a leading dot, and
        # CreateDirectoryW never sets that attribute), so this stays findable
        # without colliding.
        return Path.home() / ".varuna360"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "varuna360"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "varuna360"


def _log_root():
    return _bootstrap_root() / "logs"


def log_path():
    """Absolute path of the log file, or None if logging could not start.

    The Settings banner uses this for its "Open Log Folder" button, so it must
    stay callable even when configuration failed.
    """
    _configure()
    return _log_path


def _configure():
    """Attach the rotating file handler once. Never raises."""
    global _configured, _log_path
    if _configured:
        return
    _configured = True  # set first: a failure below must not retry every call

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # Do not let records climb to the root logger, whose default handler
    # writes to the stderr that --windowed builds have thrown away.
    logger.propagate = False

    try:
        root = _log_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / "varuna360.log"
        handler = RotatingFileHandler(
            path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        logger.addHandler(handler)
        _log_path = path
    except Exception:
        # No log file. Degrade to a null handler so callers can still call
        # .info()/.error() unconditionally without an AttributeError.
        logger.addHandler(logging.NullHandler())
        _log_path = None


def get_logger(subsystem=""):
    """Return a logger that writes to the rotating file. Never raises."""
    _configure()
    name = f"{LOGGER_NAME}.{subsystem}" if subsystem else LOGGER_NAME
    return logging.getLogger(name)


# A path segment directly under profiles/ is a profile ID, and in this
# product a profile is very often a CLIENT: "profiles/Marie Dupont/".
# Matches both separators so a Windows path is covered too.
_PROFILE_SEGMENT = re.compile(r"(profiles[/\\])([^/\\'\"]+)")


def redact_home(text):
    """Strip identifying path components (SPEC-SES-001 INV-8).

    Two substitutions:
      1. the user's home directory becomes '~'
      2. the profile-name segment becomes '<profile>'

    Applied to everything leaving the machine in a bug report, and to the
    preview the user is shown, so the two are identical. Paths are the most
    common way a real name leaks out of an otherwise anonymous payload:
    /Users/marie-claire/... names the person.

    (2) exists because (1) alone was not enough. Home redaction turns

        <home>/Documents/Varuna360/profiles/Marie Dupont/session.json

    into

        ~/Documents/Varuna360/profiles/Marie Dupont/session.json

    and the client's name is still in the payload. OSError messages embed the
    failing path verbatim, and that message is what lands in `last_error`,
    which the bug report sends. So the leak needed no unusual conditions at
    all: any permission error on any client profile would have carried that
    client's name to the server.

    Redaction happens at read/send time, never at write time, so the on-disk
    log the astrologer reads themselves keeps the real paths.

    Note both substitutions are deliberately lossy. Knowing WHICH profile
    failed is not needed to diagnose a write failure; knowing that a profile
    write failed is.
    """
    if not text:
        return text
    try:
        result = str(text)
        home = str(Path.home())
        if home and home != os.sep:
            result = result.replace(home, "~")
        result = _PROFILE_SEGMENT.sub(r"\1<profile>", result)
        return result
    except Exception:
        return str(text)


def describe_environment():
    """Non-identifying environment facts for a bug report (SPEC-SES-001 §4.5).

    Deliberately excludes hostname, username and locale — they identify the
    machine and its owner without helping diagnose a file-write failure.
    """
    info = {
        "platform": "unknown",
        "python": "unknown",
        "qt": None,
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    try:
        info["platform"] = platform.platform()
    except Exception:
        pass
    try:
        info["python"] = platform.python_version()
    except Exception:
        pass
    try:
        from PySide6 import __version__ as _pyside_version
        info["qt"] = _pyside_version
    except Exception:
        info["qt"] = None
    return info


def read_log_tail(max_lines=200):
    """Return the last `max_lines` of the log, home-redacted. Never raises."""
    _configure()
    if not _log_path:
        return ""
    try:
        with open(_log_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return redact_home("".join(lines[-max_lines:]))
    except Exception:
        return ""
