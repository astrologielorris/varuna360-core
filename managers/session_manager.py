# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Session Manager - Persist and restore chart sessions across app restarts

This module handles:
- Auto-save session on app close
- Auto-save every 30 seconds (crash protection)
- Restore dialog on startup
- Session file management per profile

Uses PySide6 (Qt6) for the restore dialog.
"""

import json
import os
import platform
import threading
import tempfile
import shutil
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from utils.debug import debug_print

# Try to import Qt (PySide6)
try:
    # QMessageBox is deliberately NOT imported (SPEC-SES-001 INV-1). A save
    # failure must never raise a modal dialog; the Settings banner surfaces it
    # instead. Keeping it out of the import list makes reintroducing one a
    # visible act rather than a one-line accident.
    from PySide6.QtWidgets import (
        QDialog, QLabel, QPushButton,
        QVBoxLayout, QHBoxLayout, QWidget
    )
    from PySide6.QtCore import QTimer, Qt
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

CTK_AVAILABLE = False  # Legacy Tkinter/CustomTkinter support removed

# Project root is one level up: managers/ -> chart_calculation/
_MANAGERS_DIR = Path(__file__).parent
PROJECT_ROOT = _MANAGERS_DIR.parent


def _get_log():
    """Diagnostics logger, or None. Lazy + defensive (SPEC-SES-001 §4.3)."""
    try:
        from core.diagnostics import get_logger
        return get_logger("session")
    except Exception:
        return None


def _fallback_profiles_dir():
    """Writable-of-last-resort profiles directory (SPEC-SES-001 INV-6).

    The platform config root — the same place bootstrap.json already lives:
      macOS    ~/Library/Application Support/varuna360/profiles
      Windows  %USERPROFILE%/.varuna360/profiles
      Linux    $XDG_CONFIG_HOME/varuna360/profiles

    Chosen over a temp dir because it survives reboot: relocating a user's
    session somewhere that evaporates would turn a "we could not save" problem
    into a "we saved it and then lost it" problem.

    Computed locally rather than imported from state.user_data because
    state/__init__.py imports panel_mixin, which imports PySide6 — and this
    module must stay importable without Qt.
    """
    system = platform.system()
    if system == "Windows":
        # Must not be ~/Documents/varuna360: on case-insensitive NTFS that is
        # the same folder as the default data dir ~/Documents/Varuna360, so
        # the "writable of last resort" would have been the very directory we
        # just proved unwritable. See state.user_data._bootstrap_dir().
        return Path.home() / ".varuna360" / "profiles"
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "varuna360" / "profiles"


def _translate_mode(mode):
    """Translate old enum values from saved sessions to current names."""
    if mode == "zodiac":
        return "aditya"
    if mode == "classic":
        return "tropical_classic"
    return mode


def _merge_now() -> str:
    """UTC now, ISO. Isolated so a clock-module import failure cannot break a
    restore — the baseline is bookkeeping, the restore is the user's data."""
    try:
        from managers.session_merge import utc_now_iso
        return utc_now_iso()
    except Exception:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()


def _selected_chart_id(memory_panel):
    """The uuid of the selected chart, or None. Never raises."""
    try:
        index = getattr(memory_panel, 'current_index', -1)
        charts = getattr(memory_panel, 'charts', None) or []
        if 0 <= index < len(charts) and isinstance(charts[index], dict):
            return charts[index].get('id') or None
    except Exception:                                   # noqa: BLE001
        pass
    return None


def _stamp_floor(last_saved) -> str:
    """The `updated_at` given to an entry that has none (SPEC-SES-002 §4.5).

    `last_saved` is written NAIVE LOCAL (`datetime.now().isoformat()`), and
    the merge compares aware UTC instants. Reading a naive string as UTC is
    the tempting one-liner and it is wrong by the whole UTC offset — four
    hours here — always in the direction that makes the entry look OLDER than
    it is, which is the direction where a deletion beats a real edit.

    Falls back to now: an unreadable or absent date is not evidence of age,
    and "as old as the file" is a claim we can only make when the file says
    so.
    """
    from datetime import datetime, timezone
    if isinstance(last_saved, str) and last_saved.strip():
        try:
            parsed = datetime.fromisoformat(last_saved.strip())
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()        # attach the LOCAL zone
            return parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            pass
    return _merge_now()


class SessionManager:
    """
    Manages session persistence for chart memory.
    Sessions are stored per-profile in profiles/{profile_name}/session.json
    """

    # 3.1 (SPEC-SES-002 §4.5): entries carry `updated_at`, the document
    # carries `tombstones` and `current_chart_id`. A 3.0 file still restores —
    # the only branch that compares is `version < '3.0'` for the v2 migration,
    # and restore stamps whatever arrives without one.
    VERSION = "3.1"
    AUTO_SAVE_INTERVAL = 30000  # 30 seconds in milliseconds

    def __init__(self, app, profiles_dir=None, profile_store=None):
        """
        Initialize the session manager.

        Args:
            app: The main CoreChartApp instance (Tkinter) or QMainWindow (Qt)
            profiles_dir: Optional custom profiles directory
            profile_store: Optional state.ProfileStore instance. When provided,
                load/save delegate to it (Phase 4 W4); when None, falls back
                to the legacy in-class file I/O for backwards compat.
        """
        self.app = app
        self._profile_store = profile_store

        # Detect framework type
        self.is_qt = QT_AVAILABLE and hasattr(app, 'centralWidget')
        self.is_ctk = not self.is_qt and hasattr(app, 'root')

        # Set up profiles directory (in project root)
        if profiles_dir:
            self.profiles_dir = Path(profiles_dir)
        elif profile_store is not None:
            # Honor the store's directory so disk layout stays consistent
            self.profiles_dir = Path(profile_store.profiles_dir)
        else:
            from state.user_data import get_user_data_dir
            data_dir = get_user_data_dir() or PROJECT_ROOT
            self.profiles_dir = data_dir / "profiles"

        # Current profile (default until profile system is implemented)
        self.current_profile = "default"

        # Auto-save timer (QTimer for Qt, int for Tkinter)
        self._auto_save_timer = None

        # Track if we've restored this session (to avoid double prompts)
        self._session_restored = False

        # Thread safety for file operations (prevents race conditions)
        self._file_lock = threading.RLock()
        # SPEC-SES-002 §4.1: the cheap half. Recorded after every successful
        # read and write; an unchanged fence inside the lock means nobody
        # else wrote, so the single-instance case stays one stat plus the
        # write it already did. None forces a merge on the first save.
        self._session_fence = None
        # INV-10: when this instance last saw the file. Older than the
        # tombstone window means it can no longer prove its unmatched entries
        # were not deleted while it slept, so disk becomes authoritative for
        # removals.
        self._session_baseline = None
        # §4.5: the removal records this instance carries. NOT the panel's
        # pending list — that one is drained after every successful write, so
        # holding the records only there meant the next save wrote none and
        # the fast path stripped them off the file entirely.
        self._tombstones = []

        # Auto-save pause DEPTH (used during profile switching).
        #
        # A counter, not a bool. The pause has to span the WHOLE switch —
        # ProfileManager.switch_profile() pauses for the save-and-flip, and
        # ProfileManager._on_profile_selected() pauses across the clear +
        # restore that follows it. With a bool, the inner resume would unpause
        # in the middle of the outer region, which is precisely the race this
        # counter exists to close (SPEC-SES-001 §8, profile-switch autosave
        # race). Nesting only works if resume undoes exactly one pause.
        self._auto_save_pause_depth = 0

        # --- Session save health (SPEC-SES-001 §4.1) --------------------
        # Replaces the old _consecutive_failures / _failure_threshold pair
        # that drove a modal QMessageBox. There is no dialog any more
        # (INV-1); this state is what the Settings banner renders.
        self._consecutive_failures = 0
        self._total_failures = 0
        self._skipped_charts = 0
        self._last_error = None
        self._last_error_at = None
        self._last_success_at = None
        self._relocated = False
        self._configured_dir = self.profiles_dir
        self._health_listeners = []

        # ORDER MATTERS. The preflight runs FIRST because _ensure_profile_dir()
        # calls mkdir(), which raises PermissionError on a read-only parent —
        # uncaught, during __init__, i.e. the app would not start at all. That
        # is strictly worse than the dialog this spec set out to remove, and it
        # is exactly the macOS read-only/TCC-denied case. Preflight relocates
        # to a writable folder first; only then do we create the profile dir.
        #
        # INV-6: prove the folder is writable BEFORE the first autosave tick,
        # and relocate rather than fail if it is not. Without this, a macOS
        # user who declines the ~/Documents TCC prompt, or a frozen build that
        # fell back to the read-only bundle, fails every save forever.
        self._preflight_writable()

        # Now safe: profiles_dir has been proven writable, or relocated to one
        # that is. Still guarded — INV-2 says a storage problem degrades saving
        # and nothing else, and that has to hold during construction too.
        self._ensure_profile_dir()

        # Sweep temp files orphaned by a previous crash. One such file was
        # found in this repo during the SPEC-SES-001 investigation:
        # profiles/research_hd/session_3xkgojwd.tmp, 844 KB, a complete and
        # valid session whose rename never happened. Nothing ever cleaned it.
        self._sweep_stale_temps()

    def _ensure_profile_dir(self):
        """Create profiles directory structure if needed. Never raises.

        Called during __init__ and on profile switch. It used to propagate
        PermissionError, which meant a read-only or TCC-denied data folder
        prevented the app from starting instead of merely preventing saves
        (SPEC-SES-001 INV-2). The failure is recorded in health and surfaced
        in Settings; the app carries on.
        """
        try:
            profile_dir = self.profiles_dir / self.current_profile
            profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            self._last_error_at = datetime.now().isoformat(timespec="seconds")
            log = _get_log()
            if log:
                log.error("could not create profile dir %s: %s",
                          self.profiles_dir / self.current_profile, e)

    # ------------------------------------------------------------------
    # Session save health (SPEC-SES-001 §4.1)
    # ------------------------------------------------------------------

    def add_health_listener(self, callback):
        """Register a callable invoked with a health dict on every change.

        A plain callback list rather than a Qt signal: SessionManager is a
        POPO shared with the Tkinter path, and retrofitting QObject onto it
        to gain one signal would drag Qt into a class that CLI tools import.
        Saves happen on the GUI thread, so listeners are called there too.

        Bound methods are held WEAKLY. The usual listener is a banner widget's
        method, and the settings tab can be rebuilt (lazy tab construction,
        edition switch). A strong reference would pin every superseded tab —
        and its whole widget tree — in memory for the life of the process, and
        SessionManager outlives all of them. Weak refs let dead listeners fall
        off instead.
        """
        import weakref
        try:
            ref = weakref.WeakMethod(callback)
        except TypeError:
            # Plain function or lambda: nothing else holds it, so a weak ref
            # would die immediately. Keep these strongly.
            ref = callback
        if ref not in self._health_listeners:
            self._health_listeners.append(ref)

    @property
    def health(self):
        """Current save-health snapshot. Read by the Settings banner.

        state is one of:
          "ok"        nothing wrong this run — banner hidden
          "degraded"  the LATEST attempt failed, or charts were dropped (orange)
          "failing"   >= 2 consecutive failures (red)
          "recovered" failed earlier, latest attempt succeeded (orange)
          "relocated" configured folder unusable, saving elsewhere (orange)

        "relocated" outranks the others: saves may be succeeding, but not
        where the user thinks, which is the thing they need told.

        WHY "degraded" EXISTS. Without it, one failure produced
        consecutive=1, total=1 → "recovered", whose banner reads "Saving is
        working again" — while saving was in fact broken, for the 30 seconds
        until the next tick, and again after every post-recovery failure. A
        persistence warning that lies is worse than no warning at all.
        "recovered" now requires an actual success since the last failure.
        """
        if self._relocated:
            state = "relocated"
        elif self._consecutive_failures >= 2:
            # 2, not 3. Each counted failure is already 3 retried writes
            # (SPEC-SES-001 §4.2), so 2 means ~6 failed writes over ~60 s.
            # With no modal to fear, there is no reason to under-report.
            state = "failing"
        elif self._consecutive_failures == 1 or self._skipped_charts:
            state = "degraded"
        elif self._total_failures > 0:
            state = "recovered"
        else:
            state = "ok"
        return {
            "state": state,
            "session_dir": self.profiles_dir / self.current_profile,
            "configured_dir": self._configured_dir / self.current_profile,
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "skipped_charts": self._skipped_charts,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "last_success_at": self._last_success_at,
        }

    def _emit_health(self):
        """Notify listeners, pruning dead ones. Never raises — a broken
        listener must not break saving, which is the whole point of INV-2."""
        import weakref
        snapshot = self.health
        alive = []
        for entry in list(self._health_listeners):
            callback = entry() if isinstance(entry, weakref.WeakMethod) else entry
            if callback is None:
                continue  # widget was destroyed — drop the entry
            alive.append(entry)
            try:
                callback(snapshot)
            except RuntimeError:
                # "Internal C++ object already deleted" — the Python wrapper
                # outlived its Qt widget. Drop it rather than log every tick.
                alive.pop()
            except Exception as e:
                debug_print(f"[SESSION] health listener failed: {e}")
        self._health_listeners = alive

    def _record_save_result(self, success, error=None):
        """Update health state after one save attempt. Never shows UI."""
        previous = self.health["state"]
        previous_error = self._last_error
        now = datetime.now().isoformat(timespec="seconds")
        if success:
            self._consecutive_failures = 0
            # Keep last_error when charts were dropped: the save "succeeded"
            # but something is still wrong, and the banner needs to say what.
            if not self._skipped_charts:
                self._last_error = None
            self._last_success_at = now
        else:
            self._consecutive_failures += 1
            self._total_failures += 1
            self._last_error = error
            self._last_error_at = now
            log = _get_log()
            if log:
                log.error(
                    "session save failed (consecutive=%d) for %s: %s",
                    self._consecutive_failures,
                    self.profiles_dir / self.current_profile,
                    error,
                )
        # Emit on a changed ERROR as well as a changed state. While stuck in
        # "failing", the state does not change but last_error / last_error_at
        # do, and an open Settings page would otherwise show the first error
        # forever while a different one recurs every 30 s.
        if self.health["state"] != previous or self._last_error != previous_error:
            self._emit_health()

    def _probe_writable(self, directory):
        """Write and delete a probe file. Returns (ok, error_string).

        An os.access() check is not enough: it consults permission bits, and
        misses macOS TCC denial, read-only mounts, full disks and quota
        limits — every scenario this is meant to catch. Only a real write
        proves writability.
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".varuna360_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True, None
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _recover_relocated_sessions(self):
        """Adopt sessions stranded in the fallback tree by an earlier run.

        The gap this closes (SPEC-SES-001 H3):
          Boot N   configured folder unwritable -> relocate -> the user's work
                   for that whole session is saved into the fallback tree.
          User fixes the permissions / grants the macOS folder access.
          Boot N+1 configured folder probes fine -> no relocation -> restore
                   reads the OLD configured session.json, and everything from
                   boot N is stranded with no path back through the UI.

        That is silent user-data loss caused by our own recovery mechanism,
        which is worse than the failure it was recovering from.

        Only ever copies FORWARD (fallback -> configured) and only when the
        fallback copy is strictly newer, so a stale fallback left over from an
        old incident can never clobber current work. The configured file is
        moved to trash/ first, never overwritten in place.
        """
        try:
            fallback = _fallback_profiles_dir()
            if fallback == self.profiles_dir or not fallback.is_dir():
                return

            log = _get_log()
            adopted = []
            for source in fallback.glob("*/session.json"):
                profile = source.parent.name
                target = self.profiles_dir / profile / "session.json"
                try:
                    observed_mtime = (target.stat().st_mtime
                                      if target.exists() else None)
                    if observed_mtime is not None and \
                            observed_mtime >= source.stat().st_mtime:
                        continue  # configured copy is current — leave it alone

                    # Never adopt a file we cannot restore from. Overwriting
                    # the user's current work with a stranded CORRUPT session
                    # would turn a recovery into a second data loss.
                    try:
                        with open(source, "r", encoding="utf-8") as handle:
                            payload = json.load(handle)
                        if not isinstance(payload, dict) or "charts" not in payload:
                            raise ValueError("missing 'charts' key")
                    except Exception as e:
                        if log:
                            log.warning(
                                "not adopting stranded session for %s: it does "
                                "not parse (%s)", profile, e,
                            )
                        continue

                    target.parent.mkdir(parents=True, exist_ok=True)

                    # Stage first. shutil.copy2 straight onto the live target
                    # is not atomic, so an interruption mid-copy leaves a
                    # truncated session.json - the exact failure this whole
                    # recovery path exists to undo.
                    temp_fd, temp_name = tempfile.mkstemp(
                        dir=str(target.parent), prefix="adopt_", suffix=".tmp"
                    )
                    os.close(temp_fd)
                    try:
                        shutil.copy2(str(source), temp_name)

                        if observed_mtime is not None:
                            # Keep a copy, not a move: until os.replace runs,
                            # target must never be missing.
                            trash = (self.profiles_dir.parent / "trash"
                                     / "superseded_sessions")
                            trash.mkdir(parents=True, exist_ok=True)
                            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                            shutil.copy2(
                                str(target),
                                str(trash / f"{profile}_{stamp}_session.json"),
                            )

                            # TOCTOU guard. Two app instances run at once in
                            # normal use (the full app and --lite share this
                            # tree), so the target can be rewritten between
                            # the mtime check above and this point. Adopting
                            # then would discard work that is NEWER than what
                            # we are about to install.
                            if target.stat().st_mtime != observed_mtime:
                                if log:
                                    log.warning(
                                        "skipped adopting %s: the configured "
                                        "session changed underneath us",
                                        profile,
                                    )
                                continue

                        os.replace(temp_name, target)
                        adopted.append(profile)
                    finally:
                        try:
                            if os.path.exists(temp_name):
                                os.unlink(temp_name)
                        except OSError:
                            pass
                except Exception:
                    continue

            if adopted and log:
                log.info(
                    "adopted %d session(s) stranded in the fallback folder "
                    "by an earlier run: %s", len(adopted), ", ".join(adopted)
                )
        except Exception as e:
            debug_print(f"[SESSION] relocated-session recovery skipped: {e}")

    def _preflight_writable(self):
        """Verify the profiles dir is writable; relocate if not (INV-6)."""
        ok, error = self._probe_writable(self.profiles_dir)
        if ok:
            # The configured folder works now. If a previous run had to fall
            # back, its sessions are sitting in the other tree — bring them
            # home before anything reads the configured one.
            self._recover_relocated_sessions()
            return

        fallback = _fallback_profiles_dir()
        log = _get_log()
        if log:
            log.error(
                "profiles dir not writable (%s): %s — relocating to %s",
                self.profiles_dir, error, fallback,
            )

        if fallback == self.profiles_dir:
            # Already there and still failing. Nothing better to try; the
            # banner will show "failing" as soon as the first save runs.
            # Count it. Otherwise a folder that is known-unwritable at boot
            # reports "ok" until the first autosave tick fails 30 s later —
            # the banner stays hidden during exactly the window where the
            # user is opening charts that will not be kept.
            self._last_error = error
            self._last_error_at = datetime.now().isoformat(timespec="seconds")
            self._consecutive_failures = max(self._consecutive_failures, 2)
            self._total_failures += 1
            self._emit_health()
            return

        ok2, error2 = self._probe_writable(fallback)
        if not ok2:
            if log:
                log.error("fallback dir also not writable (%s): %s",
                          fallback, error2)
            # Count it. Otherwise a folder that is known-unwritable at boot
            # reports "ok" until the first autosave tick fails 30 s later —
            # the banner stays hidden during exactly the window where the
            # user is opening charts that will not be kept.
            self._last_error = error
            self._last_error_at = datetime.now().isoformat(timespec="seconds")
            self._consecutive_failures = max(self._consecutive_failures, 2)
            self._total_failures += 1
            self._emit_health()
            return

        self.profiles_dir = fallback
        self._relocated = True
        self._last_error = error
        self._last_error_at = datetime.now().isoformat(timespec="seconds")

        # CRITICAL: the store holds its OWN copy of the directory. Relocating
        # only this object would split the two writers — save_session() would
        # write to the new folder while mark_properly_closed() kept using the
        # old one, so the session would never be marked closed.
        if self._profile_store is not None:
            try:
                self._profile_store.relocate(fallback)
            except AttributeError:
                # Older store without relocate(): safer to keep both objects
                # pointing at the original folder than to let them diverge.
                self.profiles_dir = self._configured_dir
                self._relocated = False
                if log:
                    log.error("store has no relocate(); staying on %s",
                              self._configured_dir)
                return

        self._ensure_profile_dir()
        self._emit_health()

    def _sweep_stale_temps(self, max_age_hours=24):
        """Move orphaned session_*.tmp files to trash/. Never raises.

        These accumulate when the process dies between the temp write and the
        rename. Per the project-wide rule they are moved, never deleted: a
        complete session sitting in a temp file may be the only surviving copy
        of someone's chart list.
        """
        try:
            cutoff = time.time() - (max_age_hours * 3600)
            # Trash lives beside the profiles, NOT under PROJECT_ROOT. In a
            # frozen build PROJECT_ROOT is sys._MEIPASS (read-only), so the
            # mkdir would fail and the sweep would silently no-op forever in
            # exactly the builds users run.
            trash = self.profiles_dir.parent / "trash" / "stale_session_temps"
            moved = 0
            for temp in self.profiles_dir.glob("*/session_*.tmp"):
                try:
                    if temp.stat().st_mtime > cutoff:
                        continue
                    trash.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    shutil.move(str(temp),
                                str(trash / f"{temp.parent.name}_{stamp}_{temp.name}"))
                    moved += 1
                except Exception:
                    continue
            if moved:
                log = _get_log()
                if log:
                    log.info("swept %d stale session temp file(s) to %s",
                             moved, trash)
        except Exception as e:
            debug_print(f"[SESSION] stale temp sweep skipped: {e}")

    def _get_session_path(self, profile_name=None):
        """Get path to session file for given profile."""
        profile = profile_name or self.current_profile
        return self.profiles_dir / profile / "session.json"

    def _create_backup(self, file_path: Path) -> bool:
        """
        Promote the current session file to .bak, but ONLY if it is intact.

        A backup is only worth anything if it is a file you can restore FROM.
        The original version of this method copied the primary over the backup
        unconditionally on every save, which means one corrupt primary was
        enough to destroy the last good copy on the very next autosave tick:

            boot N    write is interrupted           -> session.json corrupt
            boot N+1  autosave calls _create_backup  -> .bak := corrupt primary
                      (both copies now unrecoverable)

        That is not hypothetical. A profile in the live database was found with
        a truncated session.json and a byte-identical truncated .bak, so the
        recovery path had already been overwritten before anyone reached for it.

        So: parse and shape-check the primary first, and leave a good backup
        alone rather than replace it with a bad one. The copy itself also goes
        through a temp file plus os.replace, because a half-finished copy2 into
        the real .bak path has exactly the same failure mode it is meant to
        prevent.

        Args:
            file_path: File to back up

        Returns:
            True if the backup now reflects a valid primary (or there is
            nothing to back up), False if the primary was unusable or the
            copy failed. False is NOT fatal to the save that follows.
        """
        if not file_path.exists():
            return True

        backup_path = file_path.with_suffix('.json.bak')

        # Validate BEFORE touching the backup. INV-7: never trade a good
        # backup for an unvalidated one.
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if not isinstance(payload, dict) or "charts" not in payload:
                raise ValueError("missing 'charts' key")
        except Exception as e:
            debug_print(f"[SESSION] Primary is not restorable, keeping existing "
                        f"backup untouched: {e}")
            log = _get_log()
            if log:
                log.warning(
                    "session file at %s did not validate (%s); existing backup "
                    "left in place", file_path, e,
                )
            return False

        temp_fd, temp_name = tempfile.mkstemp(
            dir=str(backup_path.parent), prefix=".bak-", suffix=".tmp"
        )
        try:
            os.close(temp_fd)
            shutil.copy2(file_path, temp_name)
            os.replace(temp_name, backup_path)
            return True
        except Exception as e:
            debug_print(f"[SESSION] Backup failed: {e}")
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass
            return False

    # ------------------------------------------------------------------
    # Auto-save pause (profile switching)
    # ------------------------------------------------------------------

    @property
    def _auto_save_paused(self):
        """True while any pause region is open. Read-mostly compat shim."""
        return self._auto_save_pause_depth > 0

    @_auto_save_paused.setter
    def _auto_save_paused(self, value):
        # Kept so older code (and tests) that assigned the flag directly still
        # work. Assigning False force-clears every nesting level, which is why
        # nothing in the app should use it — pause/resume or the context
        # manager below are the supported surface.
        self._auto_save_pause_depth = 1 if value else 0

    def pause_auto_save(self):
        """Pause auto-save (use during profile switching).

        Re-entrant: each call must be matched by exactly one resume, so an
        outer region stays paused while an inner one opens and closes.
        """
        self._auto_save_pause_depth += 1
        debug_print(f"[SESSION] Auto-save paused (depth {self._auto_save_pause_depth})")

    def resume_auto_save(self):
        """Close one pause region opened by pause_auto_save()."""
        if self._auto_save_pause_depth > 0:
            self._auto_save_pause_depth -= 1
        debug_print(f"[SESSION] Auto-save resumed (depth {self._auto_save_pause_depth})")

    @contextmanager
    def auto_save_paused(self):
        """Pause auto-save for the duration of the block.

        The `finally` is the point: an exception anywhere inside a profile
        switch must not leave the app with auto-save off for the rest of the
        run. A permanently-paused autosave saves nothing at all, which is a
        worse failure than the race it was guarding against.
        """
        self.pause_auto_save()
        try:
            yield
        finally:
            self.resume_auto_save()

    def has_previous_session(self):
        """Check if a previous session exists and has charts."""
        # Phase 4 W4: delegate to ProfileStore when available
        if self._profile_store is not None:
            if not self._profile_store.profile_exists(self.current_profile):
                return False, 0, False
            data = self._profile_store.load_profile(self.current_profile)
            charts = data.get('charts', [])
            return len(charts) > 0, len(charts), data.get('properly_closed', True)

        session_path = self._get_session_path()
        if not session_path.exists():
            return False, 0, False

        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            charts = data.get('charts', [])
            chart_count = len(charts)
            properly_closed = data.get('properly_closed', True)

            return chart_count > 0, chart_count, properly_closed
        except Exception as e:
            debug_print(f"[SESSION] Error checking session: {e}")
            return False, 0, True

    def _show_qt_restore_dialog(self, chart_count, properly_closed):
        """
        Show restore dialog using Qt (PySide6).

        Args:
            chart_count: Number of charts in session
            properly_closed: Whether app closed properly

        Returns:
            True if user chose to restore, False otherwise
        """
        from ui.qt_theme import get_theme_colors, scaled_area_px

        # Build dialog message
        if not properly_closed:
            title = "Restore Session"
            message = f"Application didn't close properly.\nRestore previous session?\n\n({chart_count} charts)"
        else:
            title = "Restore Session"
            message = f"Restore previous session?\n\n({chart_count} charts)"

        theme = get_theme_colors()

        # Create dialog
        dialog = QDialog(self.app)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(380, 170)
        dialog.setModal(True)

        # Layout
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Message label — SPEC-THM-001 G14 live theme color.
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"""
            QLabel {{
                color: {theme["secondary_text"]};
                font-size: {scaled_area_px('info_text')}px;
                background: transparent;
            }}
        """)
        layout.addWidget(msg_label)

        # Button layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Result variable
        result = {'restore': False}

        def on_restore():
            result['restore'] = True
            dialog.accept()

        def on_start_fresh():
            result['restore'] = False
            dialog.accept()

        # Restore button (primary - green)
        restore_btn = QPushButton("Restore")
        restore_btn.setFixedSize(120, 36)
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #27AE60;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-size: {scaled_area_px('info_text')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #219A52;
            }}
        """)
        restore_btn.clicked.connect(on_restore)
        btn_layout.addWidget(restore_btn)

        # Start Fresh button (secondary) — SPEC-THM-001 G14 live theme colors.
        fresh_btn = QPushButton("Start Fresh")
        fresh_btn.setFixedSize(120, 36)
        fresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                font-size: {scaled_area_px('info_text')}px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
            }}
        """)
        fresh_btn.clicked.connect(on_start_fresh)
        btn_layout.addWidget(fresh_btn)

        layout.addLayout(btn_layout)

        # Show dialog and wait
        dialog.exec()

        return result['restore']

    def _show_ctk_restore_dialog(self, chart_count, properly_closed):
        """Legacy CTK dialog — no longer used. Falls back to Qt dialog."""
        debug_print("[SESSION] CTK dialog removed — use Qt dialog instead")
        return self._show_qt_restore_dialog(chart_count, properly_closed)

    def show_restore_dialog_if_needed(self):
        """
        Show restore dialog if there's a previous session.
        Automatically detects Qt vs CustomTkinter and uses appropriate dialog.

        Returns:
            True if session was restored, False otherwise
        """
        has_session, chart_count, properly_closed = self.has_previous_session()

        if not has_session:
            return False

        # Dispatch to appropriate dialog based on framework
        if self.is_qt:
            user_wants_restore = self._show_qt_restore_dialog(chart_count, properly_closed)
        elif self.is_ctk:
            user_wants_restore = self._show_ctk_restore_dialog(chart_count, properly_closed)
        else:
            debug_print("[SESSION] No supported GUI framework detected")
            return False

        # Perform restore if requested
        if user_wants_restore:
            self.restore_session()
            self._session_restored = True
            return True
        else:
            # Clear the improperly closed flag
            self.mark_properly_closed()
            return False

    def restore_session_silently(self, preserve_current_chart=False):
        """Silently restore previous session without showing a dialog.

        Args:
            preserve_current_chart: If True, save current chart before restoring and add it back

        Returns:
            True if session was restored, False otherwise
        """
        has_session, chart_count, properly_closed = self.has_previous_session()

        if not has_session:
            return False

        _preserved_recipe = None
        _preserved_sp = {}
        if preserve_current_chart and self.app.state.active_chart is not None:
            debug_print("[SESSION] Preserving current chart before restore")
            from core.chart_factory import recipe_from_chart
            _active = self.app.state.active_chart
            _preserved_sp = getattr(self.app.state, 'source_params', None) or {}
            # SPEC-IMPORT-001 §6.3: the additive metadata lives in the
            # source_params['birth_data'] deepcopy (the Chart object does not
            # carry it); forward it so it survives session restore.
            _preserved_bd = _preserved_sp.get('birth_data', {}) or {}
            _preserved_recipe = recipe_from_chart(
                _active,
                timezone=getattr(self.app, 'current_timezone', 'UTC'),
                city=getattr(self.app, 'city', ''),
                country=getattr(self.app, 'birth_country', ''),
                rodden=_preserved_bd.get('rodden'),
                tags=_preserved_bd.get('tags'),
                notes=_preserved_bd.get('notes'),
                julian_day=_preserved_bd.get('julian_day'),
                dst_offset_hours=_preserved_bd.get('dst_offset_hours'),
            )

        debug_print(f"[SESSION] Auto-restoring previous session ({chart_count} charts)")
        success = self.restore_session(skip_auto_select=preserve_current_chart)
        if success:
            self._session_restored = True

            if _preserved_recipe is not None and hasattr(self.app, 'chart_memory_panel') and self.app.chart_memory_panel:
                import uuid
                memory_panel = self.app.chart_memory_panel
                entry = {
                    'id': str(uuid.uuid4()),
                    'recipe': _preserved_recipe,
                    'mode': _preserved_sp.get('mode', 'aditya'),
                    'ayanamsa': _preserved_sp.get('ayanamsa', 1),
                    'chtk_path': getattr(self.app, 'loaded_chtk_path', None),
                    'is_transit': False,
                    '_chart': None,
                }
                from core.chart_factory import metadata_from_recipe
                recipe = entry['recipe']
                _bd, _bm = metadata_from_recipe(recipe)
                # BUG-1 (SPEC-IMPORT-002): recover recipe-dropped TOML keys
                # (_toml_extra/_original_gender) from the source .toml if present.
                self._recover_dropped_toml_keys(entry.get('chtk_path'), _bd)
                entry['person_name'] = recipe['name']
                entry['city'] = recipe['city']
                entry['country'] = recipe['country']
                entry['birth_data'] = _bd
                entry['birth_metadata'] = _bm
                entry['planets_data'] = {}
                entry['aditya_mode'] = entry['mode']
                entry['source_params'] = None
                # §4.5: a fourth creation path, and it builds its entry by
                # hand rather than through add_chart, so the panel's stamp
                # never reaches it. Unstamped means a later deletion of this
                # chart cannot be proven newer than it, and the removal does
                # not propagate to the other window.
                entry['updated_at'] = _merge_now()
                memory_panel.charts.append(entry)
                memory_panel._insertion_order.append(entry['id'])
                memory_panel.refresh()
                debug_print(f"[SESSION] Added current chart back to memory (total: {len(memory_panel.charts)} charts)")

        return success

    def save_session(self, mark_closed=False, force=False):
        """
        Save current session to disk using atomic writes.

        Args:
            mark_closed: If True, mark session as properly closed
            force: Write even while auto-save is paused. ONLY the deliberate
                "save the outgoing profile" call inside
                ProfileManager.switch_profile() may set this — see below.

        Returns:
            bool: True if save succeeded, False otherwise
        """
        # THE PAUSE GUARD (SPEC-SES-001 §8, profile-switch autosave race).
        #
        # During a profile switch, current_profile already points at the NEW
        # profile while the memory panel still holds the OLD profile's charts
        # (or a half-restored list — restore pumps the Qt event loop, so a
        # 30 s autosave tick CAN land in the middle of it). Any write in that
        # window puts one profile's charts into another profile's session.json
        # and the overwritten charts are gone. That is silent cross-profile
        # data loss, and it was observed as reachable, not theorised.
        #
        # The guard lives HERE rather than at the call sites on purpose. Only
        # _auto_save_tick() used to check the pause flag, so every other route
        # into a save — remove_chart, clear_all, rename, the closeEvent — went
        # straight through it. Sequencing pause/resume correctly at one call
        # site is a rule a future caller can forget; refusing to write while
        # paused is one a caller cannot defeat by accident.
        #
        # Returning True (not False) is deliberate: a suppressed save is not a
        # failure and must not move the health state (INV-2). The data is
        # still in memory and the next tick, ~30 s later, writes it.
        if self._auto_save_pause_depth > 0 and not force:
            debug_print("[SESSION] Save skipped (auto-save paused: profile switch)")
            return True

        # Acquire lock to prevent concurrent access
        with self._file_lock:
            try:
                # Get chart memory panel
                if not hasattr(self.app, 'chart_memory_panel') or not self.app.chart_memory_panel:
                    debug_print("[SESSION] No chart memory panel, skipping save")
                    return True  # Not an error, just nothing to save

                memory_panel = self.app.chart_memory_panel

                # Build session data (save even if empty - this clears the session file)
                session_data = {
                    'version': self.VERSION,
                    'last_saved': datetime.now().isoformat(),
                    'properly_closed': mark_closed,
                    'current_chart_index': memory_panel.current_index,
                    # §4.7 / N-5. The index is a POSITION into a list the
                    # merge reorders, so after a merge that dropped an earlier
                    # entry it points at a different person's chart. The id is
                    # what the selection actually means; the index stays for
                    # older builds reading the same file.
                    'current_chart_id': _selected_chart_id(memory_panel),
                    'ui_state': {
                        'aditya_mode': self.app.state.aditya_mode,
                        'background_num': getattr(self.app, 'background_num', 1),
                        'planet_size': getattr(self.app, 'planet_size', 60),
                        # Dasha ayanamsa settings
                        'vedanga_ayanamsa': getattr(self.app, 'vedanga_ayanamsa', 100),
                        'vimshottari_ayanamsa': getattr(self.app, 'vimshottari_ayanamsa', 98),
                        'right_dasha_mode': getattr(self.app, 'right_dasha_mode', 'nisarga'),
                        # Chart zodiac (sidereal) settings
                        'chart_zodiac': getattr(self.app, 'chart_zodiac', 'tropical'),
                        'chart_sidereal_ayanamsa_id': getattr(self.app, 'chart_sidereal_ayanamsa_id', 100),
                    },
                    'charts': [],
                    # SPEC-SES-002 INV-3/INV-4: the removals this instance
                    # made. Without them the merge resurrects every deleted
                    # chart from the other instance's list, and nothing could
                    # be deleted at all while two windows are open.
                    'tombstones': self._collect_tombstones(memory_panel),
                }

                # One bad entry must not cost the user every other chart.
                # `entry['recipe']` was the only unguarded direct index in
                # this method: a single entry without that key raised
                # KeyError, which failed the WHOLE save, on every tick,
                # forever — 130 charts lost because of one.
                skipped = []
                for entry in memory_panel.charts:
                    recipe = entry.get('recipe')
                    if not isinstance(recipe, dict):
                        skipped.append(entry.get('id', '<no id>'))
                        continue
                    chtk_path = entry.get('chtk_path')
                    chart_data = {
                        'id': entry.get('id', ''),
                        'recipe': recipe,
                        'mode': entry.get('mode', 'aditya'),
                        'ayanamsa': entry.get('ayanamsa', 1),
                        # str() because a Path here is not JSON-serializable
                        # and would fail the entire save. Callers pass str
                        # today; nothing enforced it.
                        'chtk_path': str(chtk_path) if chtk_path is not None else None,
                        'is_transit': entry.get('is_transit', False),
                    }
                    # SPEC-SES-002 §4.5. CARRIED, never minted here: the merge
                    # reads it to decide which of two copies of a chart is the
                    # newer, and a value invented at save time would say "this
                    # changed now" on every tick for entries nobody touched.
                    if entry.get('updated_at'):
                        chart_data['updated_at'] = entry['updated_at']
                    session_data['charts'].append(chart_data)

                # A dropped chart is PERMANENT LOSS at the next restore, so it
                # must not hide behind a successful save. Skipping keeps the
                # other 130 charts (the alternative — failing the whole save
                # on one bad entry — loses everything), but the user is told.
                self._skipped_charts = len(skipped)
                if skipped:
                    detail = ", ".join(str(s) for s in skipped[:10])
                    self._last_error = (
                        f"{len(skipped)} chart(s) could not be saved "
                        f"(no usable recipe): {detail}"
                    )
                    log = _get_log()
                    if log:
                        log.warning(
                            "skipped %d chart entr%s with no usable recipe: %s",
                            len(skipped),
                            "y" if len(skipped) == 1 else "ies",
                            detail,
                        )

                # Prepare file path
                session_path = self._get_session_path()
                session_path.parent.mkdir(parents=True, exist_ok=True)

                # Create backup before writing (enables recovery)
                self._create_backup(session_path)

                # SPEC-SES-002 INV-1/INV-2: read, merge and write are ONE
                # operation under a kernel advisory lock. Before this, two
                # instances sharing profiles/ each wrote their whole chart
                # list every 30 s with no read-before-write, so whichever
                # saved last erased what the other had added. Lorris runs the
                # full app and --lite together, so that was a supported
                # workflow quietly losing charts.
                success = self._save_merged(session_data, mark_closed=mark_closed)

                if success:
                    debug_print(f"[SESSION] Saved {len(session_data['charts'])} charts to {session_path}")
                    error = None
                else:
                    error = getattr(self._profile_store, "last_error", None) \
                        or "save returned False (no detail available)"
                    debug_print(f"[SESSION] Save failed: {error}")

            except Exception as e:
                success = False
                error = f"{type(e).__name__}: {e}"
                debug_print(f"[SESSION] Error saving session: {error}")
                log = _get_log()
                if log:
                    log.exception("unexpected error building/saving session")

        # Health is recorded OUTSIDE the lock, deliberately.
        #
        # The previous code raised a modal QMessageBox from in here, while
        # holding _file_lock. A modal dialog runs a NESTED Qt event loop, so
        # the 30 s autosave QTimer kept firing behind it; each tick re-entered
        # this method (the RLock is re-entrant, so nothing blocked), failed
        # again, re-crossed the threshold and stacked ANOTHER dialog. The
        # counter reset only ran after the user dismissed the box, so it never
        # broke the cycle. Leave the app unattended with a persistent cause —
        # a read-only folder, a denied macOS TCC prompt — and you returned to
        # a wall of stacked modals.
        #
        # SPEC-SES-001 INV-1: there is no dialog now, at any frequency. The
        # Settings banner shows this state instead. Do NOT reintroduce a
        # QMessageBox here with a "only once" flag; the shape is wrong, not
        # the frequency.
        self._record_save_result(success, error)
        return bool(success)

    def _migrate_v2_entry(self, old_entry):
        """Convert a v2.x chart entry to v3.0 recipe format (SPEC-MEM-002 S8.3)."""
        import uuid
        from core.chart_factory import make_recipe
        from utils.path_translator import translate_path

        bd = old_entry.get('birth_data') or {}
        sp = old_entry.get('source_params') or {}
        sp_bd = sp.get('birth_data') or {}
        pd = old_entry.get('planets_data') or {}

        name = old_entry.get('person_name') or bd.get('name') or sp_bd.get('name') or ''

        def _pick(key, *sources, default=None):
            for src in sources:
                v = src.get(key)
                if v is not None:
                    return v
            return default

        year = _pick('year', bd, sp_bd, pd, default=2000)
        month = _pick('month', bd, sp_bd, pd, default=1)
        day = _pick('day', bd, sp_bd, pd, default=1)

        timedec = _pick('timedec', bd, sp_bd)
        if timedec is None:
            h = pd.get('hour') if pd.get('hour') is not None else 0
            m = pd.get('minute') if pd.get('minute') is not None else 0
            s = pd.get('second') if pd.get('second') is not None else 0
            timedec = h + m / 60.0 + s / 3600.0

        utcoffset = _pick('utcoffset', bd, sp_bd, pd)
        if utcoffset is None:
            utcoffset = _pick('utc_offset_hours', bd, sp_bd, pd)
        if utcoffset is None:
            utcoffset = 0.0
        lat = _pick('lat', bd, sp_bd, default=_pick('latitude', pd, default=0.0))
        lon = _pick('lon', bd, sp_bd, default=_pick('longitude', pd, default=0.0))
        tz = bd.get('iana_timezone') or old_entry.get('detected_timezone') or 'UTC'
        city = old_entry.get('city') or bd.get('city') or ''
        country = old_entry.get('country') or bd.get('country') or ''

        # SPEC-IMPORT-001 §6.8: a v2 chart MAY carry additive metadata in its
        # birth_data (e.g. CHTK `notes` populated by read_notes, or tags/rodden
        # from a TOML-origin chart saved before T1 reshaped the recipe). The old
        # migrator dropped these silently. Pull them None-safely (same .get style
        # as _pick) so make_recipe re-emits them (it omits None per §6.3).
        rodden = _pick('rodden', bd, sp_bd)
        tags = _pick('tags', bd, sp_bd)
        notes = _pick('notes', bd, sp_bd)
        julian_day = _pick('julian_day', bd, sp_bd, pd)
        dst_offset_hours = _pick('dst_offset_hours', bd, sp_bd)
        # BUG-11 (SPEC-IMPORT-002): the v2 migrator extracted 5 metadata fields
        # but never gender, so a migrated chart lost its gender on session
        # restore. Gender may live in birth_data OR source_params.birth_data;
        # default to make_recipe's own 'Unknown' so a missing value is a no-op.
        gender = _pick('gender', bd, sp_bd, default='Unknown')

        all_empty = (not bd and not sp_bd and not pd)
        if all_empty:
            print(f"Warning: chart '{name}' has no reconstruction data, skipping migration")
            return None

        raw_path = old_entry.get('chtk_path')
        translated_path = translate_path(raw_path) if raw_path else None

        return {
            'id': old_entry.get('id', str(uuid.uuid4())),
            'recipe': make_recipe(
                name=name, year=year, month=month, day=day,
                timedec=timedec, utcoffset=utcoffset, timezone=tz,
                lat=lat, lon=lon, city=city, country=country,
                gender=gender,
                rodden=rodden, tags=tags, notes=notes,
                julian_day=julian_day, dst_offset_hours=dst_offset_hours,
            ),
            'mode': _translate_mode(old_entry.get('aditya_mode') or sp.get('mode') or 'aditya'),
            'ayanamsa': sp.get('ayanamsa', 1),
            'chtk_path': translated_path,
            'is_transit': old_entry.get('is_transit', False),
            '_chart': None,
        }

    @staticmethod
    def _recover_dropped_toml_keys(chtk_path, birth_data):
        """BUG-1 (SPEC-IMPORT-002): re-merge recipe-dropped TOML keys on restore.

        The recipe is the serialization spine but cannot carry ``_toml_extra``
        (unknown TOML keys), ``_original_gender`` casing, or an explicit
        ``dst_offset=0.0`` marker, so a TOML chart loses them across a session
        save/restore. When the source ``.toml`` still exists on disk, re-read it
        (``canonicalize=False`` — NEVER mutate user files during restore, CRITICAL
        TRAP #5) and fill back ONLY keys that are absent/None in ``birth_data`` so
        a recipe-carried value is never overridden. Approach A from the bug list:
        targeted, recipe unchanged, handles the 99% case where the file has not
        moved. If the file is gone the keys stay dropped (acceptable degradation).
        """
        if not chtk_path or not str(chtk_path).lower().endswith('.toml'):
            return
        from pathlib import Path as _P
        if not _P(str(chtk_path)).exists():
            return
        try:
            from core.toml_chart import TOMLChartReader
            file_bd = TOMLChartReader().read_toml_file(
                str(chtk_path), canonicalize=False)
        except Exception as exc:  # noqa: BLE001 - never block restore on one file
            debug_print(f"[SESSION] BUG-1 _toml_extra recovery failed for "
                        f"{chtk_path}: {exc}")
            return
        # WHITELIST ONLY the keys the recipe genuinely cannot carry. A blind merge
        # of every file key would poison the canonical dict: the raw TOML reader
        # returns utc_offset_hours as BASE (standard only), but the recipe carries
        # the TOTAL (INVARIANT m14). Copying the raw BASE over a None canonical slot
        # leaves utc_offset_hours (BASE) contradicting utcoffset (TOTAL) and silently
        # drops DST downstream. _original_gender and the explicit dst_offset=0.0
        # marker both live INSIDE _toml_extra, so recovering it suffices; the bare
        # _original_gender top-level key (if the reader also emits one) is included
        # for completeness.
        _TOML_ONLY_KEYS = ('_toml_extra', '_original_gender')
        for k in _TOML_ONLY_KEYS:
            v = file_bd.get(k)
            if v is not None and birth_data.get(k) is None:
                birth_data[k] = v

    def restore_session(self, skip_auto_select=False):
        """Restore session from disk.

        Args:
            skip_auto_select: If True, don't auto-select any chart after restore
        """
        try:
            # Phase 4 W4: delegate read to ProfileStore when available
            if self._profile_store is not None:
                if not self._profile_store.profile_exists(self.current_profile):
                    debug_print("[SESSION] No session file to restore")
                    return False
                data = self._profile_store.load_profile(self.current_profile)
                # SPEC-SES-002: this instance's list now matches the file, so record
                # WHEN and WHICH file. The baseline is what INV-10 compares against the
                # tombstone window; the fence lets the next save skip the merge when
                # nobody else has written.
                self._session_baseline = _merge_now()
                self._session_fence = self._profile_store.fence(self.current_profile)
            else:
                session_path = self._get_session_path()
                if not session_path.exists():
                    debug_print("[SESSION] No session file to restore")
                    return False

                with open(session_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            # Verify version compatibility
            version = data.get('version', '1.0')
            if version != self.VERSION:
                # Not a problem by itself: every 3.x file restores, and a 3.0
                # one is upgraded in place on the next save. Worth a line so a
                # genuinely older file is visible in the log.
                debug_print(f"[SESSION] Session version {version} (this build writes {self.VERSION})")

            # Restore UI state
            ui_state = data.get('ui_state', {})
            if ui_state:
                from state.events import SetZodiacMode
                from managers.settings_manager import get_settings
                # Guard restore: a locked zodiac.mode must not be clobbered by
                # session restore (which fires ~500ms after boot).
                if not get_settings().is_locked("zodiac.mode"):
                    session_mode = _translate_mode(ui_state.get('aditya_mode', 'aditya'))
                    if session_mode != self.app.state.aditya_mode:
                        self.app.state.dispatch(SetZodiacMode(mode=session_mode))
                self.app.background_num = ui_state.get('background_num', 1)
                self.app.planet_size = ui_state.get('planet_size', 60)
                # Restore dasha ayanamsa settings. Guard each side by its lock key so
                # a locked dasha config (frozen in app_settings.json) is not clobbered
                # by session restore (which fires ~500ms after boot). Grouped per side.
                if not get_settings().is_locked("dasha.left.ayanamsa_id"):
                    self.app.vedanga_ayanamsa = ui_state.get('vedanga_ayanamsa', 100)
                if not get_settings().is_locked("dasha.right.ayanamsa_id"):
                    self.app.vimshottari_ayanamsa = ui_state.get('vimshottari_ayanamsa', 98)
                if not get_settings().is_locked("dasha.right.mode"):
                    self.app.right_dasha_mode = ui_state.get('right_dasha_mode', 'nisarga')
                # Restore chart zodiac (sidereal) settings. Lock-aware per
                # SPEC-KUTA-AYA-001 3.1a: a locked zodiac.mode / zodiac.ayanamsa_id must
                # survive session restore (which fires ~500ms after boot), and a legacy
                # session file lacking the ayanamsa key must NOT silently migrate the
                # boot-time settings value (no bare default). chart_zodiac follows the
                # same lock as zodiac.mode so the two runtime flags cannot disagree.
                if not get_settings().is_locked("zodiac.mode"):
                    # Legacy sessions may carry aditya_mode="sidereal" without a
                    # chart_zodiac key; defaulting to 'tropical' would leave the two
                    # runtime flags disagreeing (state sidereal, chart_zodiac tropical).
                    # Absent key -> derive from the mode already restored above.
                    _cz = ui_state.get('chart_zodiac')
                    if _cz is None:
                        _cz = ("sidereal" if self.app.state.aditya_mode == "sidereal"
                               else "tropical")
                    self.app.chart_zodiac = _cz
                if not get_settings().is_locked("zodiac.ayanamsa_id"):
                    _restored_ayan = ui_state.get('chart_sidereal_ayanamsa_id')
                    if _restored_ayan is not None:
                        self.app.chart_sidereal_ayanamsa_id = _restored_ayan
                        get_settings().persist_runtime_change(
                            "zodiac.ayanamsa_id", _restored_ayan)
                        # Section 7 refresh contract (INV-3 writer): the kuta dock cannot
                        # be open this early, so no recompute is needed here, but any
                        # future session-restored page state would hook it at this point.
                # Restore sidereal mode if it was active (skip if mode is locked or already set)
                if self.app.chart_zodiac == "sidereal" and not get_settings().is_locked("zodiac.mode"):
                    if self.app.state.aditya_mode != "sidereal":
                        self.app.state.dispatch(SetZodiacMode(mode="sidereal"))
                # Update title buttons if they exist
                if hasattr(self.app, 'dasha_manager'):
                    self.app.dasha_manager._update_dasha_title("vedanga")
                    if getattr(self.app, 'right_dasha_mode', 'vimshottari') == 'nisarga':
                        self.app.vimshottari_title_btn.setText("Planetary Ages")
                        self.app.vimshottari_title_btn.setEnabled(False)
                    else:
                        self.app.dasha_manager._update_dasha_title("vimshottari")

            # Restore charts
            charts = data.get('charts', [])
            if not charts:
                debug_print("[SESSION] No charts in session")
                return False

            # Get chart memory panel
            if not hasattr(self.app, 'chart_memory_panel') or not self.app.chart_memory_panel:
                debug_print("[SESSION] No chart memory panel available")
                return False

            memory_panel = self.app.chart_memory_panel

            memory_panel.charts.clear()
            memory_panel._insertion_order.clear()
            memory_panel.current_index = -1

            version = data.get('version', '1.0')
            # SPEC-SES-002 §4.5: an entry with no stamp counts as "oldest
            # forever", so every one of the ~700 pre-3.1 entries would lose
            # every argument it is ever in. The file's own last_saved is the
            # honest floor — the entry provably did not change after it.
            fallback_stamp = _stamp_floor(data.get('last_saved'))
            # §4.5: the file's removal records are adopted, not discarded. A
            # restore that dropped them would put every deletion made before
            # the restart back on the table for the other instance to undo.
            try:
                from managers import session_merge
                self._tombstones = session_merge.prune_tombstones(
                    data.get('tombstones') or [])
            except Exception:
                self._tombstones = []

            for i, chart_data in enumerate(charts):
                # BUG-14 (SPEC-IMPORT-002): guard the ENTIRE per-entry build — entry
                # construction (incl. the v3 `chart_data['recipe']` access and v2
                # migration), metadata_from_recipe, and the recipe['name']/['city']/
                # ['country'] reads — so one corrupted session entry (missing
                # key/recipe) skips only that chart instead of aborting the whole
                # restore and silently losing every chart after it. The continue must
                # skip the append so no half-built entry ever reaches the panel.
                try:
                    entry = self._entry_from_disk(
                        chart_data, version=version, fallback_stamp=fallback_stamp)
                    if entry is None:
                        continue
                    recipe = entry['recipe']

                    memory_panel.charts.append(entry)
                    memory_panel._insertion_order.append(entry['id'])
                    debug_print(f"[SESSION] Added chart {i+1}/{len(charts)}: {recipe['name']}")
                except Exception as exc:
                    debug_print(
                        f"[SESSION] Skipping corrupted chart entry "
                        f"{i+1}/{len(charts)}: {exc}")
                    continue

            # Restore the selected chart (unless skip_auto_select is True).
            if not skip_auto_select:
                saved_index = data.get('current_chart_index', 0)
                # §4.7 / N-5: the ID FIRST. The index is a position into a
                # list the merge reorders, so a 30-second-old index can point
                # at a different person entirely — silent, and it looks like
                # the app opened the wrong chart for no reason. The index
                # remains the fallback for files written before 3.1.
                saved_id = data.get('current_chart_id')
                if saved_id:
                    for position, restored in enumerate(memory_panel.charts):
                        if isinstance(restored, dict) and restored.get('id') == saved_id:
                            saved_index = position
                            break
                debug_print(f"[SESSION] Saved index was: {saved_index}, total charts: {len(memory_panel.charts)}")
                if 0 <= saved_index < len(memory_panel.charts):
                    debug_print(f"[SESSION] Selecting chart at index {saved_index}")
                    memory_panel.select_chart(saved_index)
                elif memory_panel.charts:
                    debug_print(f"[SESSION] Saved index out of range, selecting first chart (index 0)")
                    memory_panel.select_chart(0)
            else:
                debug_print("[SESSION] Skipping auto-select of restored chart")

            # Refresh the memory panel display
            debug_print(f"[SESSION] About to refresh memory panel with {len(memory_panel.charts)} charts")
            memory_panel.refresh()
            debug_print(f"[SESSION] Memory panel refreshed, buttons count: {len(memory_panel.chart_buttons)}")

            debug_print(f"[SESSION] ✅ Successfully restored {len(charts)} charts")
            return True

        except Exception as e:
            debug_print(f"[SESSION] Error restoring session: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _collect_tombstones(self, memory_panel):
        """Every removal record this instance must still write (§4.5).

        Tombstones are INSTANCE STATE, not a per-save message from the panel.
        They were read off `panel.tombstones` alone, and that list is cleared
        after each successful write — so the NEXT save carried none, and on
        the fast path (nobody else wrote, no merge) that empty list was
        written straight over the real one. A deletion survived exactly one
        save, after which any other instance holding the chart put it back.

        Worse in combination with D-14: the window showing the deleted chart
        keeps its row on purpose, and once the record is gone that row is no
        longer a stale display, it is a resurrection waiting for the next
        tick. The spec names this failure in §4.5 and it was built anyway.

        Pruned here so the union cannot grow without bound.
        """
        from managers import session_merge
        pending = list(getattr(memory_panel, 'tombstones', []) or [])
        return session_merge.prune_tombstones(list(self._tombstones) + pending)

    def _entry_from_disk(self, chart_data, version='3.0', fallback_stamp=None):
        """A stored chart -> a panel entry. Returns None when it is unusable.

        Extracted so restore and the cross-instance merge push build entries
        the SAME way. A raw disk dict is not a panel entry: it lacks the
        translated path, the mode translation and the shim fields every
        consumer reads (SPEC-SES-002 §4.2), and pushing one in directly
        breaks the panel in ways that only show up later.

        Raises nothing of its own — the caller decides whether one bad entry
        skips a row or aborts a merge.
        """
        import uuid
        from utils.path_translator import translate_path
        from core.chart_factory import metadata_from_recipe

        if version < '3.0':
            entry = self._migrate_v2_entry(chart_data)
            if entry is None:
                return None
        else:
            if chart_data.get('recipe') is None:
                debug_print("[SESSION] Skipping entry: missing 'recipe' key")
                return None
            raw_path = chart_data.get('chtk_path')
            entry = {
                'id': chart_data.get('id', str(uuid.uuid4())),
                'recipe': chart_data['recipe'],
                'mode': _translate_mode(chart_data.get('mode', 'aditya')),
                'ayanamsa': chart_data.get('ayanamsa', 1),
                'chtk_path': translate_path(raw_path) if raw_path else None,
                'is_transit': chart_data.get('is_transit', False),
                '_chart': None,
            }

        recipe = entry['recipe']
        _bd, _bm = metadata_from_recipe(recipe)
        # BUG-1 (SPEC-IMPORT-002): recover _toml_extra / _original_gender
        # the recipe could not carry, from the source .toml if present.
        self._recover_dropped_toml_keys(entry.get('chtk_path'), _bd)
        entry['person_name'] = recipe['name']
        entry['city'] = recipe['city']
        entry['country'] = recipe['country']
        entry['birth_data'] = _bd
        entry['birth_metadata'] = _bm
        entry['planets_data'] = {}
        entry['aditya_mode'] = entry['mode']
        entry['source_params'] = None
        # Preserve a stored stamp; give the pre-3.1 entries the floor.
        stored = chart_data.get('updated_at') if isinstance(chart_data, dict) else None
        entry['updated_at'] = stored or fallback_stamp or _merge_now()
        return entry

    def _save_merged(self, session_data, mark_closed=False) -> bool:
        """Write `session_data`, merging anything another instance added.

        SPEC-SES-002 INV-1/INV-2. Returns True when the file was written.

        Three things happen inside the lock, and only inside it:
          * the fence is compared (nothing changed -> no merge, fast path);
          * on-disk charts are merged into ours by the rule in
            managers/session_merge.py (union by uuid, additions win,
            removals recorded as tombstones take precedence);
          * the result is written.

        A merge that RAISES returns None from the build function, which the
        store treats as "skip the save" — INV-7: a merge failure never causes
        an overwrite. The next tick tries again with the same data.
        """
        from managers import session_merge

        if self._profile_store is None:
            # No store: there is nothing to take a lock on, and the legacy
            # unlocked write is exactly the bug this method exists to fix.
            # Skipping is the honest outcome; save_session reports it.
            debug_print("[SESSION] No profile store; save skipped (SPEC-SES-002)")
            self._last_error = "no profile store available"
            return False

        merge_stats = {}
        merged_holder = {}

        def _build(on_disk):
            if on_disk is None:
                # Fence matched: nobody else wrote, so there is nothing to
                # push. Cleared rather than left behind — the store may call
                # this more than once, and a stale list from an earlier
                # attempt would push charts that the winning write never made.
                merged_holder.pop("merged", None)
                merged_holder.pop("doc", None)
                return session_data
            try:
                if not isinstance(on_disk, dict):
                    return None              # INV-7
                rebaseline = session_merge.should_rebaseline(self._session_baseline)
                merged, stats = session_merge.merge_session_data(
                    session_data, on_disk, rebaseline=rebaseline)
                merge_stats.update(stats)
                merge_stats["rebaselined"] = rebaseline
                # The CHART LIST, not the session dict. merge_session_data
                # returns a whole document (it merges tombstones too) and the
                # store writes that; the push works on entries. Handing it
                # the document made the push a silent no-op — it type-guards
                # its input, so nothing failed and nothing happened.
                merged_holder["merged"] = merged.get("charts")
                # The DOCUMENT too, for its tombstones: the merged union is
                # what actually reaches the file, and this instance has to
                # carry the other instance's removals forward or its own next
                # fast-path save drops them again (§4.5).
                merged_holder["doc"] = merged
                return merged
            except Exception as e:                      # noqa: BLE001
                # INV-7 again, and deliberately broad: the alternative is an
                # overwrite that drops the other instance's charts.
                debug_print(f"[SESSION] Merge failed, skipping save: {e}")
                self._last_error = f"merge failed: {type(e).__name__}: {e}"
                return None

        ok, info = self._profile_store.save_profile_merged(
            self.current_profile, _build, fence=self._session_fence)

        if ok:
            self._session_fence = info.get("fence")
            self._session_baseline = session_merge.utc_now_iso()
            # The records are on disk now. The panel's pending list is
            # ADOPTED, not dropped: draining it keeps the panel from
            # re-sending the same records every tick, but they have to live
            # on somewhere or the next save writes a document with none and
            # the fast path strips the file's own copy (§4.5).
            try:
                panel = getattr(self.app, 'chart_memory_panel', None)
                document = merged_holder.get("doc") or session_data
                written = document.get('tombstones')
                if isinstance(written, list):
                    self._tombstones = list(written)
                if panel is not None and getattr(panel, 'tombstones', None):
                    panel.tombstones = []
            except Exception:
                pass
            # SPEC-SES-002 §4.2: the merged list goes into the LIVE panel, not
            # only onto disk. Without this the two windows converge in the
            # file and disagree on screen until one of them restarts, which
            # reads as the file having lost the chart.
            #
            # Skipped on a closing save (D-5): pushing into widgets during
            # teardown, and a status message aimed at a window that is going
            # away, are both wrong.
            #
            # And only when this instance RESTORED (INV-5a). With auto-restore
            # off the panel is empty by intent and the fence is unset, so every
            # tick merges the whole file in — pushing that would turn "do not
            # restore my session" into "restore it 30 seconds later", which is
            # the user's setting being overruled by a background timer.
            if (not mark_closed and self._session_restored
                    and "merged" in merged_holder):
                try:
                    self._push_merge_to_panel(session_data, merged_holder["merged"])
                except Exception as exc:                # noqa: BLE001
                    # The disk is already correct at this point. A display
                    # that lags by one restart is not worth taking the save
                    # path down for.
                    debug_print(f"[SESSION] Panel push failed (disk is fine): {exc}")
            added = merge_stats.get("added", 0)
            if added and not mark_closed:
                # Informational, never the sticky-error channel: nothing went
                # wrong, the user simply has charts they did not add here.
                self._report_merge(added, merge_stats)
        elif info.get("skipped"):
            # The reason matters and there are three of them now: the lock is
            # held elsewhere, the merge refused, or the file could not be
            # trusted (INV-7). "another instance holds the lock" was printed
            # for all three, which sends the next person reading the log after
            # a concurrency problem that is not there.
            reason = getattr(self._profile_store, "last_error", None) \
                or "another instance is saving"
            debug_print(f"[SESSION] Save skipped: {reason}")
            if info.get("load_status") in ("unreadable", "salvaged"):
                self._last_error = reason
        if info.get("quarantined"):
            # Not an error — the save succeeded. But the user has a
            # session.corrupt-*.json next to their profile now, and they
            # should be able to find out why from the log rather than by
            # noticing the file.
            debug_print(f"[SESSION] Damaged session moved aside: "
                        f"{info['quarantined']}")
        return ok

    def _safe_entry_from_disk(self, chart_data, version, fallback_stamp=None):
        """`_entry_from_disk` with a per-entry guard, for the merge push.

        Restore already guards every entry individually, for a reason the
        comment there states plainly: one corrupted entry must not cost the
        user every chart after it. The push needs the same guard for the same
        reason — `metadata_from_recipe` indexes recipe keys directly, so a
        single entry written by an older version raises and would otherwise
        abandon the whole push.
        """
        try:
            return self._entry_from_disk(chart_data, version=version,
                                         fallback_stamp=fallback_stamp)
        except Exception as exc:                        # noqa: BLE001
            debug_print(f"[SESSION] Merge push skipped one entry: {exc}")
            return None

    def _push_merge_to_panel(self, session_data, merged):
        """Bring the live panel in line with what was just written (§4.2).

        Returns (added, updated, removed) — counts of rows actually changed.

        Deliberately NOT `ChartMemoryPanel.add_chart`: its heal-on-match does
        `existing.update(chart_entry)`, making the INCOMING entry
        authoritative — the exact inverse of the merge rule that just ran —
        and it sets `current_index`, so a background tick every 30 s would
        move the user's selection out from under them.

        THE ENTRY THE USER IS LOOKING AT IS NEVER TOUCHED (D-14). Pulling the
        displayed chart out of the panel, or swapping its recipe underneath
        the drawn wheel, is a worse failure than one stale row: the row is
        already correct on disk, the tombstone that removed it is in the file,
        and the merge re-derives the same delta on every tick — so it lands by
        itself the moment the selection moves. Nothing has to remember to
        retry.
        """
        panel = getattr(self.app, 'chart_memory_panel', None)
        if panel is None:
            return (0, 0, 0)
        if not isinstance(merged, list):
            # Loud on purpose. This guard once turned a shape mismatch (the
            # session DOCUMENT passed where the chart LIST belongs) into a
            # silent no-op: every save reported success, the file was right,
            # and the panel never moved.
            debug_print(f"[SESSION] Panel push refused a "
                        f"{type(merged).__name__}, expected a list of charts")
            return (0, 0, 0)

        def _by_id(entries):
            out = {}
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                cid = entry.get('id')
                # An id-less entry cannot be matched in EITHER direction, so
                # it is neither an addition nor a removal. Keying on one
                # would delete the pre-uuid rows the merge deliberately keeps.
                if cid:
                    out[str(cid)] = entry
            return out

        ours = _by_id(session_data.get('charts'))
        theirs = _by_id(merged)
        live = {str(e.get('id')): e for e in panel.charts
                if isinstance(e, dict) and e.get('id')}

        selected_id = None
        if 0 <= getattr(panel, 'current_index', -1) < len(panel.charts):
            current = panel.charts[panel.current_index]
            if isinstance(current, dict):
                selected_id = str(current.get('id') or '') or None

        version = session_data.get('version', self.VERSION)
        # An entry that reaches the push without a stamp gets the FILE's
        # floor, the same one restore uses. Minting "now" here would say the
        # chart changed at this tick, which is the one thing §4.5 forbids.
        floor = _stamp_floor(session_data.get('last_saved'))
        added = updated = removed = 0

        # --- removals: gone from the merged list, so a tombstone took them ---
        for cid in list(ours):
            if cid in theirs or cid == selected_id or cid not in live:
                continue
            entry = live[cid]
            # By IDENTITY, not equality. list.remove() compares with ==, and
            # two panel entries for the same chart at the same instant
            # compare equal — so it can delete a different row than the one
            # the tombstone named.
            for index, candidate in enumerate(panel.charts):
                if candidate is entry:
                    del panel.charts[index]
                    if cid in panel._insertion_order:
                        panel._insertion_order.remove(cid)
                    removed += 1
                    break

        # --- updates: the other instance's copy is the newer one -------------
        for cid, entry in theirs.items():
            if cid not in live or cid == selected_id or entry is ours.get(cid):
                continue
            rebuilt = self._safe_entry_from_disk(entry, version, floor)
            if rebuilt is None:
                continue
            target = live[cid]
            target.update(rebuilt)
            # The cached Chart belongs to the OLD recipe. _entry_from_disk
            # clears `_chart`, but the three `_built_*` keys that say what it
            # was built from live only on panel entries, and a stale set there
            # tells select_chart the cache is still valid.
            for key in ('_built_mode', '_built_ayanamsa', '_built_hsys'):
                target.pop(key, None)
            updated += 1

        # --- additions: charts made in the other window ----------------------
        for cid, entry in theirs.items():
            if cid in live:
                continue
            # Transits are excluded (§4.7 OPEN-1 is still unset, so nothing
            # caps them). A "Now" click is a moment, not a person: every one
            # made in one window would land in the other window's visible list
            # forever. They still MERGE onto disk — this only refuses to fill
            # a live panel with them.
            if entry.get('is_transit'):
                continue
            built = self._safe_entry_from_disk(entry, version, floor)
            if built is None:
                continue
            panel.charts.append(built)
            panel._insertion_order.append(built['id'])
            added += 1

        if not (added or updated or removed):
            return (0, 0, 0)

        # current_index is a POSITION, and a removal above may have shifted it.
        # Re-derived from the id so the user keeps looking at the same chart.
        if selected_id is not None:
            for index, entry in enumerate(panel.charts):
                if isinstance(entry, dict) and str(entry.get('id') or '') == selected_id:
                    panel.current_index = index
                    break
            else:
                panel.current_index = -1 if not panel.charts else 0
        panel.refresh()
        debug_print(f"[SESSION] Panel push: +{added} ~{updated} -{removed}")
        return (added, updated, removed)

    def _report_merge(self, added, stats):
        """Say that charts arrived from another window. Best-effort."""
        try:
            word = "chart" if added == 1 else "charts"
            message = f"{added} {word} added from another window"
            if stats.get("rebaselined"):
                message += " (session re-synced after a long idle period)"
            bar = getattr(self.app, "statusBar", None)
            if callable(bar):
                bar().showMessage(message, 8000)
            debug_print(f"[SESSION] {message}")
        except Exception:
            pass

    def mark_properly_closed(self):
        """Mark session as properly closed (no crash).

        SPEC-SES-002 §4.1: this used to open session.json itself and do a
        whole-file read-modify-write outside any cross-process lock — a FULL
        LOST UPDATE at shutdown, reverting everything the other instance had
        saved since this one read the file. Closing one window undid the
        other window's afternoon.

        It now goes through the same locked primitive as every other write.
        """
        with self._file_lock:
            try:
                session_path = self._get_session_path()
                if not session_path.exists():
                    return
                if self._profile_store is None:
                    return

                def _build(on_disk):
                    data = on_disk
                    if data is None:
                        data = self._profile_store.load_profile(self.current_profile)
                    if not isinstance(data, dict):
                        return None          # INV-7: never overwrite blind
                    data['properly_closed'] = True
                    return data

                ok, info = self._profile_store.save_profile_merged(
                    self.current_profile, _build)
                if ok:
                    self._session_fence = info.get("fence")
                elif info.get("skipped"):
                    debug_print("[SESSION] properly_closed skipped (lock busy)")
            except Exception as e:
                debug_print(f"[SESSION] Error marking properly closed: {e}")

    def clear_session(self):
        """Delete the session file for the current profile.

        No callers today, and it stays listed in §4.6 for that reason: it
        removed the file with no cross-process lock, so a future caller would
        have reintroduced the unlocked writer this spec exists to remove —
        and worse than a bad write, since the other instance's next save
        would recreate the file from its own list and the "clear" would look
        random. The lock makes the removal atomic against a save in flight.
        """
        try:
            session_path = self._get_session_path()
            store = self._profile_store
            if store is not None and hasattr(store, 'profile_lock'):
                with store.profile_lock(self.current_profile) as held:
                    if not held:
                        debug_print("[SESSION] Clear skipped: another instance is saving")
                        return
                    if session_path.exists():
                        session_path.unlink()
                        debug_print(f"[SESSION] Cleared session: {session_path}")
                return
            if session_path.exists():
                session_path.unlink()
                debug_print(f"[SESSION] Cleared session: {session_path}")
        except Exception as e:
            debug_print(f"[SESSION] Error clearing session: {e}")

    def start_auto_save(self):
        """Start the auto-save timer for crash protection."""
        if self.is_qt:
            # Qt: Use QTimer
            if QT_AVAILABLE:
                self._auto_save_timer = QTimer()
                self._auto_save_timer.timeout.connect(self._auto_save_tick)
                self._auto_save_timer.start(self.AUTO_SAVE_INTERVAL)
                debug_print("[SESSION] Started Qt auto-save timer (30s interval)")
        elif self.is_ctk:
            # Tkinter: Use after()
            self._schedule_auto_save()
            debug_print("[SESSION] Started Tkinter auto-save timer (30s interval)")

    def _schedule_auto_save(self):
        """Schedule the next auto-save (Tkinter only)."""
        if not self.is_ctk:
            return

        if self._auto_save_timer:
            self.app.root.after_cancel(self._auto_save_timer)

        self._auto_save_timer = self.app.root.after(
            self.AUTO_SAVE_INTERVAL,
            self._auto_save_tick
        )

    def _auto_save_tick(self):
        """Perform auto-save and schedule next one."""
        try:
            # Skip if paused (during profile switching)
            if self._auto_save_paused:
                debug_print("[SESSION] Auto-save skipped (paused)")
                # Still schedule next tick
                if self.is_ctk:
                    self._schedule_auto_save()
                return

            # Save session (not marking as closed - that's only on clean exit)
            self.save_session(mark_closed=False)

            # Schedule next auto-save (Tkinter only - Qt uses repeating QTimer)
            if self.is_ctk:
                self._schedule_auto_save()

        except Exception as e:
            debug_print(f"[SESSION] Auto-save error: {e}")

    def stop_auto_save(self):
        """Stop the auto-save timer."""
        if self._auto_save_timer:
            try:
                if self.is_qt and QT_AVAILABLE:
                    # Qt: Stop QTimer
                    self._auto_save_timer.stop()
                elif self.is_ctk:
                    # Tkinter: Cancel after()
                    self.app.root.after_cancel(self._auto_save_timer)
            except Exception as e:
                debug_print(f"[SESSION] Error stopping auto-save: {e}")
            self._auto_save_timer = None

    def on_app_closing(self):
        """Called when app is closing - save session and mark as properly closed.

        Deliberately NOT force=True. A close event can be delivered while the
        Qt event loop is pumped mid-profile-switch, and at that moment the
        panel holds the wrong profile's charts; forcing the write would put
        them into the incoming profile's session.json on the way out — the
        very loss the pause guard prevents. The outgoing profile was already
        saved by switch_profile(), so at worst this skips marking the incoming
        session properly-closed.
        """
        debug_print("[SESSION] App closing - saving session...")
        self.stop_auto_save()
        self.save_session(mark_closed=True)
        debug_print("[SESSION] Session saved successfully")
