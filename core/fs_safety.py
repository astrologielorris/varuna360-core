# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Filesystem safety helpers that have to behave the same on Windows.

Two unrelated-looking problems live here because they share one root cause:
the code was written and tested on Linux, and Windows disagrees about both
of them.

1. ATOMIC WRITES (atomic_write_json)
   The temp-file + rename idiom is only crash-safe if
     - the temp name is UNIQUE per writer, and
     - the promotion uses os.replace, not os.rename.
   A FIXED temp name turns the idiom into a concurrency hazard: two writers
   open the same temp path, the second truncates the first's in-flight write,
   and whichever renames second promotes a half-written file or fails with
   FileNotFoundError. This is not theoretical here — the owner runs the full
   app and the --lite build at the same time against the same data directory.
   os.rename is the second trap: on POSIX it silently overwrites the
   destination, on Windows it raises FileExistsError as soon as the
   destination exists. Every os.rename-based "atomic" write therefore works on
   Linux and fails on Windows on the SECOND save.

2. FILENAMES (windows_safe_filename)
   Windows rejects  < > : " / \\ | ? *  and control characters, rejects
   trailing dots and trailing spaces, and reserves the DOS device names
   (CON, PRN, AUX, NUL, COM1-9, LPT1-9) even with an extension: CON.chtk is
   just as unopenable as CON. Astrology chart names routinely carry a colon
   (a time) or a slash (a date), so this is a live failure mode, not an
   edge case.

This module imports nothing outside the standard library on purpose: it sits
under settings/persistence code that CLI tools import, and must never pull Qt.
"""
import errno
import json
import os
import re
import tempfile
import time
from pathlib import Path

# Delays BEFORE attempts 2 and 3. Shape borrowed from state/profile_store.py so
# the two retry policies stay recognisably the same thing.
RETRY_DELAYS = (0.15, 0.40)

# Characters Windows forbids anywhere in a path component.
_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# DOS device names. Reserved with OR without an extension, case-insensitive.
WINDOWS_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

# Windows sharing violations. A file locked by OneDrive, an antivirus scanner
# or a second app instance reports these; they are transient and worth a retry.
_WINERROR_SHARING_VIOLATION = 32
_WINERROR_LOCK_VIOLATION = 33
# ERROR_ACCESS_DENIED. A genuine permission problem OR a delete-pending file.
# Treated as NON-transient: retrying an ACL denial just adds half a second of
# latency to an error the user has to fix by hand anyway.
_WINERROR_ACCESS_DENIED = 5


def is_transient_oserror(exc) -> bool:
    """True when `exc` is a lock/contention failure that a retry may clear.

    The distinction matters most on Windows, where a file locked by a
    OneDrive sync pass and a file the user genuinely may not write both
    surface as PermissionError with errno 13. Only the winerror code tells
    them apart, so use it whenever it is present.
    """
    if not isinstance(exc, OSError):
        return False

    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        if winerror in (_WINERROR_SHARING_VIOLATION, _WINERROR_LOCK_VIOLATION):
            return True
        if winerror == _WINERROR_ACCESS_DENIED:
            return False
        # Any other winerror: fall through to the errno check below.

    if exc.errno in (errno.EAGAIN, errno.EBUSY, errno.EINTR, errno.ETXTBSY):
        return True

    if exc.errno == errno.EACCES and winerror is None and os.name == "nt":
        # Windows without a winerror attribute (some wrapped exceptions).
        # Ambiguous, so retry: a wasted 0.55 s beats losing the save.
        return True

    # FileNotFoundError during a rename is the signature of a temp file that
    # another writer clobbered. It clears on the next attempt.
    if isinstance(exc, FileNotFoundError):
        return True

    return False


def _fsync_dir(directory):
    """Best-effort fsync of a directory so the rename itself is durable.

    Not supported on Windows (opening a directory fails), hence best-effort.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_bytes_atomic(path, payload: bytes, *, prefix=None,
                       retries=len(RETRY_DELAYS), mode=None,
                       sleep=time.sleep) -> None:
    """Write `payload` to `path` atomically. Raises the last error on failure.

    - UNIQUE temp file in the SAME directory (same filesystem, so os.replace
      cannot fall back to a copy).
    - flush + fsync before the rename, so the promoted file has real bytes on
      disk rather than a page-cache promise.
    - os.replace, which is atomic on POSIX AND on Windows, and unlike
      os.rename does not care whether the destination already exists.
    - bounded retry, but ONLY on a transient OSError (see is_transient_oserror).

    `sleep` is injectable so tests do not have to spend real seconds.
    """
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    prefix = prefix or (path.name + ".")

    attempts = retries + 1
    last_exc = None
    for attempt in range(1, attempts + 1):
        fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=prefix,
                                        suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = None  # fdopen owns the descriptor now
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                try:
                    os.chmod(tmp_path, mode)
                except OSError:
                    pass
            os.replace(tmp_path, path)
            _fsync_dir(directory)
            return
        except BaseException as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                tmp_path.unlink()
            except OSError:
                pass
            if isinstance(exc, OSError) and is_transient_oserror(exc) \
                    and attempt < attempts:
                last_exc = exc
                sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                continue
            raise
    if last_exc is not None:
        raise last_exc


def atomic_write_json(path, data, *, indent=2, ensure_ascii=False,
                      allow_nan=False, prefix=None, mode=None,
                      sleep=time.sleep) -> None:
    """Serialise `data` and write it atomically. Raises on failure.

    allow_nan defaults to False: json's default emits bare NaN/Infinity, which
    are NOT valid JSON. Such a file saves "successfully" and then fails to load
    forever. A visible save failure is strictly better than silent permanent
    loss. (Same reasoning as state/profile_store.py.)

    Serialisation happens BEFORE the temp file is created, so a TypeError in
    the payload never leaves a stray temp file behind.
    """
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii,
                      allow_nan=allow_nan)
    write_bytes_atomic(path, text.encode("utf-8"), prefix=prefix, mode=mode,
                       sleep=sleep)


def is_reserved_windows_name(name: str) -> bool:
    """True when `name` collides with a DOS device name.

    The check is on the stem: CON, con, CON.chtk and con.tar.gz are all
    unusable on Windows.
    """
    if not name:
        return False
    stem = name.split(".", 1)[0].strip()
    return stem.upper() in WINDOWS_RESERVED_NAMES


def windows_safe_filename(name, default="chart", max_length=120,
                          replacement="_") -> str:
    """Return a single path COMPONENT that is legal on Windows and POSIX.

    Deliberately narrow: it fixes only what Windows rejects. It does not
    lowercase, does not collapse spaces, does not transliterate. A name that
    is already safe comes back byte-identical, so wiring this into an existing
    call site cannot rename anybody's existing files.

    Handled:
      - < > : " / \\ | ? * and control characters  -> `replacement`
      - leading/trailing whitespace, trailing dots -> stripped
      - reserved DOS device names (CON, NUL, COM1) -> suffixed with `_`
      - empty / all-illegal result                 -> `default`
      - over-long names                            -> truncated to max_length

    NOT handled here, on purpose: NTFS case-insensitivity. Two names differing
    only in case are legal inputs and mapping them together would silently
    merge unrelated data. Callers that create DIRECTORIES from user names must
    resolve that with unique_name() instead.
    """
    if name is None:
        return default
    text = str(name)

    text = _FORBIDDEN_RE.sub(replacement, text)
    # Trailing dots and spaces: Windows silently drops them on create, so
    # "Chart." and "Chart" become the same file and a later open("Chart.")
    # fails. Strip instead of trusting the API to be consistent.
    text = text.strip().rstrip(". ")

    if len(text) > max_length:
        text = text[:max_length].rstrip(". ")

    if not text:
        return default

    if is_reserved_windows_name(text):
        # The escape has to go on the STEM. Appending at the very end would
        # turn "CON.chtk" into "CON.chtk_", whose stem is still CON and which
        # Windows still refuses.
        stem, dot, rest = text.partition(".")
        text = f"{stem}{replacement}{dot}{rest}"

    return text


def unique_name(directory, base, suffix="", exists=None) -> str:
    """Return `base` + `suffix`, or a `_2`/`_3` variant, free of CASE clashes.

    NTFS and APFS are case-insensitive, so "Josh" and "josh" are the same
    directory. A plain Path.exists() check written on Linux therefore passes
    on the developer's machine and merges two users' data on the customer's.
    This compares case-folded against the real directory listing instead.

    `exists` is injectable for tests; it takes a case-folded name and returns
    a bool.
    """
    directory = Path(directory)
    if exists is None:
        try:
            taken = {entry.name.casefold() for entry in directory.iterdir()}
        except OSError:
            taken = set()

        def exists(candidate):
            return candidate.casefold() in taken

    candidate = f"{base}{suffix}"
    if not exists(candidate):
        return candidate
    counter = 2
    while True:
        candidate = f"{base}_{counter}{suffix}"
        if not exists(candidate):
            return candidate
        counter += 1
