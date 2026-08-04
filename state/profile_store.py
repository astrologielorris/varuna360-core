# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
ProfileStore — Layer-B per-profile session persistence (Phase 4 W4).

Opaque JSON passthrough: stores whatever dict SessionManager hands it,
returns whatever it has. No schema knowledge, no version migration —
SessionManager (Layer D) owns those concerns.

Pre-mortem fix pm-20260503-008: atomic write via temp + fsync + os.replace.

SPEC-SES-001 hardening (2026-07-25):
  - UNIQUE temp names (INV-4). The old fixed `session.json.tmp` was a
    concurrency hazard, not a safety mechanism — see save_profile().
  - Bounded retry on transient OSError (INV-5).
  - The real exception is captured in `last_error` instead of discarded (INV-3).
  - allow_nan=False: a NaN used to serialize to bare `NaN`, which is invalid
    JSON, so the save reported success and the session became permanently
    unloadable.
  - relocate(), so SessionManager can move the store to a writable folder
    without the two objects' paths silently diverging (INV-6).
"""
import contextlib
import copy
import errno
import json
import os
import tempfile
import time
import warnings
from pathlib import Path

# SPEC-SES-001 §4.2. Attempt 1 is immediate; these are the delays BEFORE
# attempts 2 and 3. Total added latency in the worst case is 0.55 s, on a
# path that already only runs every 30 s.
_RETRY_DELAYS = (0.15, 0.40)

# Errors where waiting 0.55 s and trying again cannot possibly help. The
# retry loop runs on the GUI thread, so every retry of a hopeless error is a
# visible freeze bought for nothing — and autosave fires every 30 s, so on a
# full disk that is a stutter every half minute for as long as the app is
# open. Fail fast instead and let the health banner say why.
_TERMINAL_ERRNOS = {
    errno.ENOSPC,        # disk full
    errno.EROFS,         # read-only filesystem
    errno.ENAMETOOLONG,  # path too long (a real Windows case)
    errno.EISDIR,
    errno.ENOTDIR,
    errno.EFBIG,
}
if hasattr(errno, "EDQUOT"):     # not defined on every platform
    _TERMINAL_ERRNOS.add(errno.EDQUOT)

# Transient by nature: another writer, a scanner, a sync daemon, momentary fd
# exhaustion. These are worth a short retry.
_TRANSIENT_ERRNOS = {
    errno.EBUSY,
    errno.EAGAIN,
    errno.EINTR,
    errno.EMFILE,
    errno.ENFILE,
}
if hasattr(errno, "ETXTBSY"):
    _TRANSIENT_ERRNOS.add(errno.ETXTBSY)

# Windows sharing/lock violations. Windows reports a file held open by another
# process as PermissionError, which on POSIX would mean a genuine, permanent
# permission denial. Same Python exception, opposite prognosis — so the
# platform has to be part of the decision.
_WINDOWS_TRANSIENT_WINERRORS = {
    5,   # ERROR_ACCESS_DENIED, commonly transient under antivirus
    32,  # ERROR_SHARING_VIOLATION, the OneDrive / second-instance case
    33,  # ERROR_LOCK_VIOLATION
}


def _is_retryable(exc):
    """True when re-attempting this OSError has a real chance of succeeding.

    Unknown errnos default to retryable: two extra attempts costs 0.55 s,
    while wrongly giving up costs the user their session. The asymmetry
    decides the default.
    """
    code = getattr(exc, "errno", None)

    if os.name == "nt":
        winerror = getattr(exc, "winerror", None)
        if winerror in _WINDOWS_TRANSIENT_WINERRORS:
            return True
        # On Windows EACCES/EPERM usually means "someone has it open", not
        # "you may not have it".
        if code in (errno.EACCES, errno.EPERM):
            return True
    else:
        # On POSIX they mean exactly what they say, and no amount of waiting
        # changes a mode bit or a TCC denial.
        if code in (errno.EACCES, errno.EPERM):
            return False

    if code in _TERMINAL_ERRNOS:
        return False
    if code in _TRANSIENT_ERRNOS:
        return True
    return True


# Default shape returned for missing profiles. SessionManager fills in real
# values; this is the boot-from-nothing fallback.
DEFAULT_SESSION = {
    "version": "1.0",
    "charts": [],
}

# Types json.dump handles natively. Anything else in the payload is a bug.
_JSON_SAFE = (str, int, float, bool, type(None))

# How a load went (SPEC-SES-002 INV-7). The VALUE cannot say — an unreadable
# file and an empty one both come back as DEFAULT_SESSION — so the caller has
# to be told, or it merges against "you have no charts" and writes that.
LOAD_OK = "ok"
LOAD_MISSING = "missing"        # no file yet: an honest empty baseline
LOAD_SALVAGED = "salvaged"      # real data, but possibly older than the last removal
LOAD_UNREADABLE = "unreadable"  # nothing could be read at all

#: INV-7a. Refusing to save protects the file; refusing FOREVER loses
#: everything in memory instead, and a permanently corrupt file never heals on
#: its own. The third consecutive refusal moves the damaged file aside — never
#: deletes it — and writes.
CORRUPT_SKIP_LIMIT = 3


def _get_log():
    """Diagnostics logger, or None if unavailable.

    Imported lazily and defensively: this module sits underneath the GUI and
    is imported by CLI tools, so a logging problem must never stop a save from
    being attempted.
    """
    try:
        from core.diagnostics import get_logger
        return get_logger("session")
    except Exception:
        return None


def _describe_type_error(data, _path="", _depth=0):
    """Return the key path of the first non-JSON-serializable value found.

    Example: 'charts[37].recipe.notes -> datetime.date'

    json.dump's own TypeError says only "Object of type date is not JSON
    serializable" — which of 375 chart entries is at fault is left as an
    exercise. This walks the payload and names it, so a poisoned recipe can be
    found from a user's bug report without reproducing anything.

    Returns "" when nothing unserializable is found (the TypeError came from
    somewhere else, e.g. a NaN under allow_nan=False).
    """
    if _depth > 12:
        return ""
    try:
        if isinstance(data, dict):
            for key, value in data.items():
                # Non-string keys are themselves a json.dump failure.
                if not isinstance(key, (str, int, float, bool, type(None))):
                    return f"{_path} -> key of type {type(key).__name__}"
                found = _describe_type_error(value, f"{_path}.{key}", _depth + 1)
                if found:
                    return found
            return ""
        if isinstance(data, (list, tuple)):
            for index, value in enumerate(data):
                found = _describe_type_error(
                    value, f"{_path}[{index}]", _depth + 1
                )
                if found:
                    return found
            return ""
        if isinstance(data, float) and (data != data or data in (
                float("inf"), float("-inf"))):
            # NaN / Infinity: serializable only with allow_nan=True, which we
            # deliberately disable because the result is not valid JSON.
            return f"{_path.lstrip('.')} -> {data!r}"
        if not isinstance(data, _JSON_SAFE):
            return f"{_path.lstrip('.')} -> {type(data).__name__}"
        return ""
    except Exception:
        return ""



# --- advisory locking (SPEC-SES-002 §4.1) -----------------------------------
# fcntl on POSIX, msvcrt on Windows. Both are ADVISORY and both are released
# by the kernel when the holding process dies, so an instance that crashes
# mid-merge cannot leave the other one locked out — the failure mode a
# hand-rolled lock file would have.

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None
try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


def _acquire_lock(handle, timeout_s: float) -> bool:
    """Try to take an exclusive lock on `handle` within `timeout_s`.

    Polls rather than blocking: a blocking acquire on the GUI thread would
    hang the window for as long as the other process holds it, and the
    caller's contract is to SKIP a contended save, not to wait for it.
    """
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        try:
            if _fcntl is not None:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                return True
            if _msvcrt is not None:
                handle.seek(0)
                _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
                return True
            return True          # no primitive available: do not block saves
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)


def _release_lock(handle) -> None:
    try:
        if _fcntl is not None:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
        elif _msvcrt is not None:
            handle.seek(0)
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass          # the kernel releases it on close either way


class ProfileStore:
    """Per-profile session.json store.

    Layout: {profiles_dir}/{profile_id}/session.json
    """

    def __init__(self, profiles_dir):
        """Args:
            profiles_dir: directory containing per-profile subdirs.
                Each profile_id maps to {profiles_dir}/{profile_id}/session.json.
        """
        self._profiles_dir = Path(profiles_dir)
        # SPEC-SES-001 INV-3. The last save failure as "TypeError: ...",
        # or None after any success. SessionManager reads this to build the
        # health state the Settings banner shows; before this existed the
        # exception was discarded and the user got invented advice about
        # disk space.
        self.last_error = None
        # How the last load actually went (§4.5 / INV-7). See load_profile.
        self.last_load_status = LOAD_OK
        # INV-7a: consecutive saves skipped because the file could not be
        # trusted, per profile. Refusing forever is its own data loss — the
        # charts in memory never reach the disk — so the third refusal moves
        # the damaged file aside and writes.
        self._corrupt_skips = {}

    @property
    def profiles_dir(self):
        return self._profiles_dir

    def relocate(self, new_profiles_dir):
        """Point the store at a different directory (SPEC-SES-001 INV-6).

        SessionManager calls this when its startup writability probe fails and
        it falls back to a secondary folder.

        This method exists because SessionManager and ProfileStore hold
        SEPARATE copies of the directory (session_manager.py copies
        `profile_store.profiles_dir` at construction). Relocating only the
        manager's copy would silently split the two writers: save_session()
        would write to the new folder while mark_properly_closed() kept
        writing to the old one, and the session would never be marked closed.
        """
        self._profiles_dir = Path(new_profiles_dir)

    def _session_path(self, profile_id: str) -> Path:
        return self._profiles_dir / profile_id / "session.json"

    def load_profile(self, profile_id: str) -> dict:
        """Return profile data, or a fresh DEFAULT_SESSION copy if missing.

        Never raises. Corrupt JSON is logged and treated as default — keeps
        the app bootable when a profile file is hand-edited and broken.

        HOW it read is recorded in `last_load_status` (SPEC-SES-002 INV-7,
        §4.5). The return value alone cannot say: an unreadable file and an
        empty one both come back as DEFAULT_SESSION, so a merge that trusted
        the value treated "I could not read your charts" as "you have none"
        and wrote over them. A salvaged read is real data but not a
        trustworthy BASELINE — it may predate the last removal, and unioning
        it resurrects deleted charts.

        `missing` is deliberately NOT a failure: a profile with no file yet is
        an honest empty baseline, and refusing to save into one would mean a
        new profile could never write its first chart.
        """
        path = self._session_path(profile_id)
        self.last_load_status = LOAD_OK
        if not path.exists():
            self.last_load_status = LOAD_MISSING
            return copy.deepcopy(DEFAULT_SESSION)
        log = _get_log()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                warnings.warn(f"ProfileStore.load_profile: {path} is not a JSON object — returning default")
                self.last_load_status = LOAD_UNREADABLE
                return copy.deepcopy(DEFAULT_SESSION)
            return data
        except Exception as e:
            warnings.warn(f"ProfileStore.load_profile failed for {path}: {e}")
            if log:
                log.error("load failed for %s: %s — attempting recovery", path, e)

            # OBSERVED IN THE WILD (2026-07-25, profiles/argentina): a
            # session.json holding 42 valid charts followed by 635 bytes of a
            # previous, longer file. Signature of the fixed-temp-name race:
            # writer B truncated and wrote a SHORTER payload into the temp
            # file writer A still had open, and A's later writes landed past
            # B's end. Returning DEFAULT_SESSION here means the user opens
            # Varuna360 and every chart is simply gone.
            recovered = self._recover_corrupt(path, log)
            if recovered is not None:
                self.last_load_status = LOAD_SALVAGED
                return recovered
            self.last_load_status = LOAD_UNREADABLE
            return copy.deepcopy(DEFAULT_SESSION)

    def _recover_corrupt(self, path: Path, log=None):
        """Salvage a session from a damaged file. Returns dict or None.

        Two strategies, cheapest first:
          1. Decode the longest valid JSON PREFIX. Trailing garbage from an
             interleaved write leaves the real document fully intact in front
             of it, so this typically recovers every chart.
          2. Fall back to session.json.bak, which the app has been writing on
             every save since forever and never once read.

        Never raises: recovery failing must not stop the app booting.
        """
        # 1. Longest valid prefix.
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            obj, end = json.JSONDecoder().raw_decode(raw.lstrip())
            if isinstance(obj, dict):
                charts = len(obj.get("charts", []))
                trailing = len(raw) - end
                warnings.warn(
                    f"ProfileStore: recovered {charts} chart(s) from the valid "
                    f"prefix of {path} ({trailing} trailing bytes ignored)"
                )
                if log:
                    log.warning(
                        "recovered %d chart(s) from valid prefix of %s "
                        "(%d trailing bytes ignored)", charts, path, trailing
                    )
                return obj
        except Exception:
            pass

        # 2. The backup nobody ever read.
        try:
            backup = path.with_suffix(".json.bak")
            if backup.exists():
                with open(backup, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if log:
                        log.warning("recovered %d chart(s) from %s",
                                    len(data.get("charts", [])), backup)
                    return data
        except Exception:
            pass

        if log:
            log.error("could not recover %s; starting from an empty session", path)
        return None

    def save_profile(self, profile_id: str, data: dict) -> bool:
        """Atomic write. Returns True on success, False on any failure.

        Never raises: SessionManager owns the decision about what a failure
        means for the user (SPEC-SES-001 §4.1). On failure `self.last_error`
        holds the real exception as "TypeError: ..." — that string is what the
        Settings banner shows, so it must stay short and human-readable, never
        a traceback.

        Retry policy (INV-5): up to 3 attempts, retrying ONLY on OSError.
        A json.dump TypeError is deterministic — retrying it just burns 0.55 s
        and hides which chart entry is poisoned. See _describe_type_error.
        """
        path = self._session_path(profile_id)
        log = _get_log()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            warnings.warn(f"ProfileStore.save_profile mkdir failed for {path.parent}: {e}")
            if log:
                log.error("save mkdir failed for %s: %s", path.parent, self.last_error)
            return False

        attempts = len(_RETRY_DELAYS) + 1
        for attempt in range(1, attempts + 1):
            try:
                self._write_once(path, data)
                self.last_error = None
                return True

            except OSError as e:
                # A cloud-sync daemon, an antivirus scanner or a second app
                # instance holding the target for the length of one rename is
                # worth retrying. A full disk or a read-only filesystem is
                # not: this loop runs on the GUI thread, so retrying a
                # hopeless error only freezes the window.
                self.last_error = f"{type(e).__name__}: {e}"
                if attempt < attempts and _is_retryable(e):
                    if log:
                        log.warning(
                            "save attempt %d/%d failed for %s (%s) — retrying",
                            attempt, attempts, path, self.last_error,
                        )
                    time.sleep(_RETRY_DELAYS[attempt - 1])
                    continue
                if attempt < attempts and log:
                    log.error(
                        "save failed for %s with a terminal error, not "
                        "retrying: %s", path, self.last_error,
                    )
                warnings.warn(f"ProfileStore.save_profile failed for {path}: {e}")
                if log:
                    log.error(
                        "save FAILED for %s after %d attempts: %s",
                        path, attempts, self.last_error,
                    )
                return False

            except Exception as e:
                # Deterministic. Almost always a non-JSON-serializable value
                # that rode into a chart recipe. Name the exact key path so
                # the offending entry can be found without a debugger.
                detail = ""
                if isinstance(e, (TypeError, ValueError)):
                    detail = _describe_type_error(data)
                self.last_error = f"{type(e).__name__}: {e}"
                if detail:
                    self.last_error += f" (at {detail})"
                warnings.warn(f"ProfileStore.save_profile failed for {path}: {e}")
                if log:
                    log.error("save FAILED for %s (not retried): %s",
                              path, self.last_error)
                return False

        return False  # unreachable; keeps static analysis honest

    # -- SPEC-SES-002: locked read-modify-write ---------------------------

    #: How long to wait for the other instance's merge before giving up.
    #: A merge is roughly a millisecond; anything beyond this is a stuck
    #: process, and blocking the GUI thread is worse than skipping one tick.
    LOCK_TIMEOUT_S = 0.25

    def _lock_path(self, profile_id: str) -> Path:
        return self._session_path(profile_id).with_suffix(".lock")

    @contextlib.contextmanager
    def _profile_lock(self, profile_id: str):
        """A kernel advisory lock on a sibling session.lock (SPEC-SES-002 §4.1).

        Yields True when held, False when it could not be taken in time —
        the caller must then SKIP the save (INV-7), never write unlocked.

        This is NOT the lifetime single-instance guard SPEC-SES-001 OPEN-2
        proposed and SPEC-SES-002 still rejects: it is held across one
        read-merge-write and prevents nothing else, so running the app beside
        --lite or beside the visual harness is unaffected. It also has no
        stale-lock failure mode — the kernel releases an advisory lock
        unconditionally when the holder dies, so there is no liveness
        heuristic here to get wrong.

        Degrades to "held" where no locking primitive is available, because
        the merge is still a large improvement over the unconditional
        overwrite it replaces.
        """
        path = self._lock_path(profile_id)
        handle = None
        acquired = False
        try:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = open(path, "a+b")
            except OSError as e:
                warnings.warn(f"ProfileStore: cannot open lock {path}: {e}")
                yield True          # no lock file, but never skip the save
                return
            acquired = _acquire_lock(handle, self.LOCK_TIMEOUT_S)
            yield acquired
        finally:
            if handle is not None:
                if acquired:
                    _release_lock(handle)
                try:
                    handle.close()
                except OSError:
                    pass

    def fence(self, profile_id: str):
        """(st_mtime_ns, st_size, st_ino) for the profile's session file.

        The cheap half of §4.1: inside the lock, an unchanged fence means
        nobody else wrote, so the merge can be skipped and the
        single-instance case stays one stat plus the write it already did.
        st_ino is included because os.replace installs the TEMP file's inode,
        so "is this still the file I read?" is close to exact rather than a
        guess from size and mtime.
        """
        try:
            st = self._session_path(profile_id).stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def save_profile_merged(self, profile_id: str, build_fn, fence=None):
        """Locked read -> build_fn(on_disk) -> write. Returns (ok, info).

        `build_fn(on_disk_dict_or_None) -> dict` runs INSIDE the lock, and is
        passed None when the fence still matches (nothing changed, no merge
        needed).

        The layering is deliberate (§4.1): this class writes the file, so the
        LOCK belongs here, but it takes an opaque dict and knows nothing
        about panel entries, tombstones or status messages — so the MERGE
        stays with the caller. Two classes owning one file is how the bug
        this fixes came to exist.

        info["skipped"] is True when the lock could not be taken; the caller
        must treat that as "did not save" (INV-7), not as a failure to
        report to the user — the next tick will try again.
        """
        info = {"skipped": False, "merged": False, "fence": None,
                "quarantined": None, "load_status": LOAD_OK}
        with self._profile_lock(profile_id) as held:
            if not held:
                info["skipped"] = True
                self.last_error = "another instance is saving"
                return False, info
            current = self.fence(profile_id)
            on_disk = None
            if fence is None or current != fence:
                on_disk = self.load_profile(profile_id)
                info["load_status"] = self.last_load_status
                if self.last_load_status in (LOAD_UNREADABLE, LOAD_SALVAGED):
                    # INV-7 / §4.5. Neither of these may be a merge baseline.
                    # An unreadable file returns DEFAULT_SESSION, so merging
                    # it means unioning against "no charts" and writing that
                    # over whatever the other instance had. A salvaged read
                    # is real data but may predate the last removal, so
                    # unioning it resurrects deleted charts.
                    skips = self._corrupt_skips.get(profile_id, 0) + 1
                    self._corrupt_skips[profile_id] = skips
                    if skips < CORRUPT_SKIP_LIMIT:
                        info["skipped"] = True
                        self.last_error = (
                            f"session file {self.last_load_status}; save "
                            f"skipped ({skips}/{CORRUPT_SKIP_LIMIT})")
                        return False, info
                    # INV-7a: it is not healing. Move it aside and write.
                    info["quarantined"] = self._quarantine(profile_id)
                    self._corrupt_skips[profile_id] = 0
                    on_disk = None      # nothing trustworthy to merge against
                else:
                    self._corrupt_skips[profile_id] = 0
                info["merged"] = on_disk is not None
            data = build_fn(on_disk)
            if data is None:
                # The merge refused (INV-7: a merge failure never causes an
                # overwrite). Not an error to report — a skipped save.
                info["skipped"] = True
                return False, info
            ok = self.save_profile(profile_id, data)
            info["fence"] = self.fence(profile_id)
            return ok, info

    @contextlib.contextmanager
    def profile_lock(self, profile_id: str):
        """Hold the cross-process session lock across a read-modify-write.

        PUBLIC because `save_profile_merged` is not the only shape a writer
        needs. `sync_favorites_profile` reads the session, reconciles it
        against `favorites.json`, may rewrite that file too, and only then
        writes — it cannot express that as one merge callback, and before
        this it simply wrote unlocked. SPEC-SES-002 §4.6/AC-6: every writer
        of session.json participates, or the lock protects nothing.

        Yields True when the lock was taken and False when it was not. A
        caller that gets False must not write.
        """
        with self._profile_lock(profile_id) as held:
            yield held

    def _quarantine(self, profile_id: str):
        """Move a damaged session aside. Returns the new path, or None.

        RENAMED, never deleted (INV-7a). The file is the user's charts in an
        unreadable state, and unreadable is not the same as worthless — the
        2026-07-25 case recovered 42 charts from one by hand. A `.corrupt`
        file next to the session is what makes that possible; overwriting it
        is what makes it impossible.

        Failing to quarantine does NOT block the write. The alternative is an
        app that can never save again because it cannot rename a file.
        """
        from datetime import datetime
        path = self._session_path(profile_id)
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = path.with_name(f"session.corrupt-{stamp}.json")
            index = 1
            while target.exists():           # two crashes in one second
                target = path.with_name(f"session.corrupt-{stamp}-{index}.json")
                index += 1
            os.replace(str(path), str(target))
            log = _get_log()
            if log:
                log.error("quarantined unreadable session %s -> %s", path, target)
            warnings.warn(f"ProfileStore: quarantined unreadable session to {target}")
            return str(target)
        except Exception as e:                              # noqa: BLE001
            warnings.warn(f"ProfileStore: could not quarantine {path}: {e}")
            return None

    def _write_once(self, path: Path, data: dict):
        """One temp-write + fsync + rename. Raises on any failure.

        The temp name is UNIQUE per writer (SPEC-SES-001 INV-4). The previous
        implementation used the fixed name `session.json.tmp`, which turned
        the temp+rename crash-safety idiom into a concurrency hazard: with two
        app instances running (nothing in the codebase prevents that), the
        second instance's open(..., "w") truncates the first's in-flight write,
        and whichever renames second gets FileNotFoundError — PermissionError
        on Windows. Timer-phase dependent, hence "it fails at times".

        os.replace is atomic, not exclusive: atomicity guarantees no reader
        sees a half-written file. It says nothing about two writers racing.
        """
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix="session_", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None  # fdopen owns it now
                # allow_nan=False: json's default emits bare NaN/Infinity,
                # which are NOT valid JSON. Such a file saves "successfully"
                # and then fails to load forever. A visible save failure is
                # strictly better than silent permanent loss.
                json.dump(data, handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def profile_exists(self, profile_id: str) -> bool:
        return self._session_path(profile_id).exists()

    def list_profiles(self) -> list:
        """Return sorted list of profile IDs that have a session.json file."""
        if not self._profiles_dir.exists():
            return []
        return sorted(
            d.name for d in self._profiles_dir.iterdir()
            if d.is_dir() and (d / "session.json").exists()
        )
