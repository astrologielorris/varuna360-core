# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The panel's store writers (design.md §4.6, SPEC-FIND-003 §5).

``FolderSyncWorker`` is REBUILD INDEX's folder half: the only folder scan the
panel runs, started only by ``FindChartPanel._build_index_async`` with the
user's consent. ``ComputeWorker`` is a ``QThread`` that waits on
``compute_process.run`` (the compute itself runs in a low-priority child
process held to a CPU share, so the app stays fast), started only by
``FindChartPanel._start_compute`` with its consent flag.
``StoreFileWorker`` runs the Index menu's export and import (varuna/50).
Each opens its own ``StoreWriter`` on its own thread (the compute's in
its child process). ``StoreReadWorker`` is the one reader: the search's
store reads off the GUI thread (``FindChartPanel._refresh_in_background``).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from core.chart_search import compute, compute_process, sync

#: Workers a closing panel let go, referenced until they finish: a QThread
#: destroyed while it runs aborts the app (review r10).
_PARKED: set = set()
#: Sort with AI's detached workers (``sort_with_ai.detach_worker``): kept
#: here so the quit join needs no AI module (SPEC-EDN-002 P4).
DETACHED_SORT: set = set()
#: Running store reads (``start_read``): referenced until they end, never
#: parented to a panel, and never a ``store_released`` (they write nothing).
_READS: set = set()
#: Every result signal a panel worker may carry.
_RESULT_SIGNALS = ("synced", "error", "progress", "cancelled", "committing", "done")


class JobRelay(QObject):
    """One worker's results, received on the GUI thread (a QObject there,
    so cross-thread signals queue to it) and handed to the panel only while
    the relay is valid and ``owns()`` still holds (review r12). A queued
    delivery can still run after its signal was disconnected; it then lands
    here and is dropped, so a stopped, replaced or old job never releases a
    slot, starts a compute or loads a chart. ``invalidate()`` at shutdown."""

    _MAX = 6

    def __init__(self, owns: Callable[[], bool], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._owns = owns
        self._handlers: list[Callable[..., None]] = []
        self.valid = True

    def bind(self, signal, handler: Callable[..., None]) -> None:
        index = len(self._handlers)
        if index >= self._MAX:
            raise ValueError("JobRelay: too many signals")
        self._handlers.append(handler)
        signal.connect(getattr(self, f"_h{index}"))

    def invalidate(self) -> None:
        self.valid = False

    def _call(self, index: int, args: tuple) -> None:
        if self.valid and self._owns():
            self._handlers[index](*args)

    def _h0(self, *args):
        self._call(0, args)

    def _h1(self, *args):
        self._call(1, args)

    def _h2(self, *args):
        self._call(2, args)

    def _h3(self, *args):
        self._call(3, args)

    def _h4(self, *args):
        self._call(4, args)

    def _h5(self, *args):
        self._call(5, args)


def relay_for(worker, owns: Callable[[], bool], parent: QObject) -> JobRelay:
    """A relay owned by ``parent`` (the panel), kept on the worker."""
    relay = JobRelay(owns, parent)
    worker._relay = relay
    return relay


def invalidate(worker) -> None:
    relay = getattr(worker, "_relay", None)
    if relay is not None:
        relay.invalidate()


class _Notifier(QObject):
    store_released = Signal()


_NOTIFIER: list = []


def notifier() -> _Notifier:
    """The app-lifetime notifier (review r14): ``store_released`` fires
    when a parked worker ends, so the live panel catches up."""
    if not _NOTIFIER:
        _NOTIFIER.append(_Notifier())
    return _NOTIFIER[0]


def disconnect_results(worker: QThread) -> None:
    """No new result of ``worker`` reaches the panel. A delivery already
    queued may still run (PySide6 delivers it): its relay drops it
    (``invalidate``, review r12)."""
    invalidate(worker)
    import warnings

    for name in _RESULT_SIGNALS:
        signal = getattr(worker, name, None)
        if signal is None or not hasattr(signal, "disconnect"):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass


def parked(kind: type) -> bool:
    """A worker of ``kind`` a closed panel parked is still running: it owns
    the store until it ends, for every panel (review r13)."""
    return any(isinstance(w, kind) and w.isRunning() for w in list(_PARKED))


def folder_writer_parked() -> bool:
    """A folder sync a closed panel parked is still running (it may still
    publish its old folder list: forgets wait for it, review r12)."""
    return parked(FolderSyncWorker)


def join_parked() -> None:
    """Application quit: every parked worker (and every detached sort
    worker) is cancelled and joined with no time cap, whatever panel parked
    it (review r11: parking outlives a panel, not the process)."""
    for worker in list(_PARKED) + list(DETACHED_SORT) + list(_READS):
        try:
            if hasattr(worker, "cancel"):
                worker.cancel()
            worker.wait()
        except RuntimeError:  # already deleted
            pass
        _PARKED.discard(worker)
        DETACHED_SORT.discard(worker)
        _READS.discard(worker)


def park(worker: QThread) -> None:
    """Results off, no parent, referenced until ``finished``, then deleted."""
    disconnect_results(worker)
    worker.setParent(None)
    if not worker.isRunning():
        worker.deleteLater()
        return
    _PARKED.add(worker)

    def gone(w=worker):
        _PARKED.discard(w)
        w.deleteLater()
        try:
            notifier().store_released.emit()  # queued to the live panels
        except RuntimeError:
            pass

    worker.finished.connect(gone)
    if not worker.isRunning():  # it ended between the check and the connect
        gone()
from core.chart_search.compute import ComputePlan, Progress
from core.chart_search.sources import CurrentSession, ScanCancelled
from core.chart_search.store import StoreReader, StoreWriter, store_path


class FolderSyncWorker(QThread):
    """Folders, then sessions (their merge reads the files' moments).
    ``progress(done, total)`` is throttled (total 0: still discovering);
    ``cancel`` stops the folder scan before anything is written and emits
    ``cancelled`` instead of ``synced`` (SPEC-FIND-005 §3.10)."""

    synced = Signal(object)  # sync.FolderSync
    error = Signal(str)
    progress = Signal(int, int)  # files done, total (0: discovering)
    cancelled = Signal()
    #: The commit point is passed: the writes run to the end, CANCEL now
    #: means "cancel the computation that follows" (``cancel_after_commit``).
    committing = Signal()

    def __init__(
        self,
        folders: Sequence[Path],
        profiles_dir: Path,
        current: CurrentSession | None,
        *,
        discard: bool = False,
    ) -> None:
        super().__init__()
        self._folders = tuple(folders)
        self._profiles_dir = profiles_dir
        self._current = current
        self._discard = discard
        self._lock = threading.Lock()
        self._cancel = False
        self._committed = False
        self.cancel_after_commit = False

    def cancel(self) -> None:
        """Before the commit point: stop the scan (nothing written). After
        it: ``cancel_after_commit`` is set, and the panel starts no compute
        when the sync ends."""
        with self._lock:
            if self._committed:
                self.cancel_after_commit = True
            else:
                self._cancel = True

    def _is_cancelled(self) -> bool:
        with self._lock:
            return self._cancel

    def _commit(self) -> None:
        """The one cancellation boundary: under the lock, a cancel that
        landed first stops here (``ScanCancelled``); otherwise the commit
        point is passed and a later cancel only skips the compute."""
        with self._lock:
            if self._cancel:
                raise ScanCancelled()
            self._committed = True
        self.committing.emit()

    def run(self) -> None:
        """Scan without a writer (a missing or incompatible store is left as
        it is until the commit point), then open the writer and apply."""
        try:
            known = {} if self._discard else sync.known_file_states()
            scan = sync.scan_for_sync(
                self._folders,
                known,
                progress=self.progress.emit,
                cancelled=self._is_cancelled,
            )
            self._commit()
            with StoreWriter.open() as store, store.atomically():
                # One transaction with the session sync too: a Full Rebuild
                # that fails anywhere keeps the previous index (review r8).
                result = sync.commit_scan(
                    store, scan, self._folders, discard=self._discard
                )
                sync.sync_sessions(store, self._profiles_dir, self._current)
            self.synced.emit(result)
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - reported in the panel's status
            compute.report_failure("folder sync failed", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}")


class ComputeWorker(QThread):
    """``compute.run`` off the UI thread, in a child process at
    ``cpu_percent`` of one core (``compute_process``). Progress arrives
    throttled (``compute.PROGRESS_INTERVAL_S``, FIND-003 §4); ``cancel`` stops
    it after the current moment, keeping every finished batch."""

    progress = Signal(str, int, int)  # extractor id, done, total
    done = Signal(object)  # compute.ComputeReport
    error = Signal(str)

    def __init__(self, plan: ComputePlan, cpu_percent: int) -> None:
        super().__init__()
        self.plan = plan
        self.cpu_percent = cpu_percent
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            report = compute_process.run(
                self.plan,
                store_path(writable=True),
                self._progress,
                self._cancel.is_set,
                cpu_percent=self.cpu_percent,
            )
            self.done.emit(report)
        except Exception as exc:  # noqa: BLE001 - reported in the coverage strip
            compute.report_failure("compute failed", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}")

    def _progress(self, update: Progress) -> None:
        self.progress.emit(update.extractor_id, update.done, update.total)


class StoreFileWorker(QThread):
    """Export or import (varuna/50) off the UI thread: ``job`` returns the
    status text, or raises."""

    done = Signal(str, bool)  # status text, refresh after it
    error = Signal(str)

    def __init__(self, job: Callable[[], str], refresh: bool = False) -> None:
        super().__init__()
        self._job = job
        self._refresh = refresh

    def run(self) -> None:
        try:
            self.done.emit(self._job(), self._refresh)
        except Exception as exc:  # noqa: BLE001 - reported in the panel
            compute.report_failure("index file operation failed", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}")


class StoreReadWorker(QThread):
    """One read of the store off the GUI thread: ``job(store)`` runs in one
    read-only snapshot of the store at ``path``; ``done`` carries what it
    returns, ``error`` why it could not (the panel then reads on its own
    thread, where every store state has its message)."""

    done = Signal(object)
    error = Signal(str)

    def __init__(self, path: Path, job: Callable[[StoreReader], object]) -> None:
        super().__init__()
        self._path = path
        self._job = job

    def run(self) -> None:
        try:
            with StoreReader.open(self._path) as store:
                value = self._job(store)
        except Exception as exc:  # noqa: BLE001 - the panel reads again itself
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(value)


def start_read(worker: StoreReadWorker) -> None:
    """Start ``worker``, referenced until it ends, then deleted. Its results
    reach the panel through a relay (``relay_for``), which drops them once
    the panel is gone or a newer search ran."""
    _READS.add(worker)

    def gone(w=worker):
        _READS.discard(w)
        relay = getattr(w, "_relay", None)
        try:
            if relay is not None:  # its delivery, queued before, already ran
                relay.deleteLater()
        except RuntimeError:  # the panel, its parent, is gone with it
            pass
        w.deleteLater()

    worker.finished.connect(gone)
    worker.start()


def disconnect_web(worker) -> None:
    """Search Web's results no longer reach the panel (its own signal names;
    a queued one is dropped by its relay)."""
    import warnings

    invalidate(worker)
    for name in ("finished", "status"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                getattr(worker, name).disconnect()
            except (RuntimeError, TypeError, AttributeError):
                pass
