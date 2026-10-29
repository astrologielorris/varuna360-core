# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""App -> Find Chart store (design.md §4.1, §4.6, D4).

Feeds the store, not the panel, so the index follows the session while the
Find Chart tab is closed and ``ChartGUI`` does not grow. Three kinds of event:

- **Session**: every successful session save and every Find Chart show. JSON
  only (``sync.sync_sessions``): no folder walk, no chart file read; the
  current profile comes from memory. A save that changed nothing is skipped.
- **Single file** the app itself wrote or trashed (save, web download, CHTK
  creation, trash): one entry upserted or removed (FIND-003 §3.5 as extended
  by Q8). Never a folder scan.
- **New moments** that either brought are computed for the current search
  system: Positions, plus every extractor the user already computed in that
  system. Only under ``compute.CONSENT_THRESHOLD_S``: anything bigger is the
  panel's to ask about (Q4), never background work the user did not choose.

Everything runs on one worker thread, in order, each job with its own store
connection; nothing here blocks the UI thread. Qt-free, so it is testable
without an app. A failed job is logged and dropped: the store is a cache and
the next sync or REBUILD INDEX repairs it.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path

from core.chart_search import compute, sync
from core.chart_search.extractors import positions, registry
from core.chart_search.extractors.base import Extractor
from core.chart_search.search import Scope, Sources
from core.chart_search.sources import CurrentSession, Entry, EntryKind
from core.chart_search.store import StoreReader, StoreWriter
from core.chart_search.system import SearchSystem
from managers.chart_creation_pipeline import CHART_FOLDER_ENV
from utils.debug import debug_print

_instance: FindChartSync | None = None


def current() -> FindChartSync | None:
    """The running app's sync (None in a CLI or a test without one)."""
    return _instance


def default_system() -> SearchSystem:
    """The default search system: the app's live frame and settings, as
    ``search_charts`` resolves it."""
    from core.capabilities.inputs import LibraryInput
    from core.capabilities.settings_view import SettingsView

    view = SettingsView.load()
    return SearchSystem.from_frame(LibraryInput.resolve(view).frame, view)


class ForgetSuperseded(Exception):
    """A folder forget whose folder list changed again before it wrote: it
    wrote nothing (review r12: a re-added folder must keep its charts)."""


class FindChartSync:
    def __init__(
        self,
        *,
        profiles_dir: Callable[[], Path] = sync.profiles_dir,
        system: Callable[[], SearchSystem] = default_system,
    ) -> None:
        self._profiles_dir = profiles_dir
        self._system = system
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="find-chart-sync"
        )
        self._closing = threading.Event()
        self._pending: list[Future[None]] = []
        self._last_session: tuple[str, str] | None = None  # profile, snapshot
        # The folder list's generation: a forget writes only if no change
        # came after it, checked and written under the lock (review r12).
        self._folders_lock = threading.Lock()
        self._folders_generation = 0
        #: root -> generation of its latest removal (review r13: shared by
        #: every panel, so a recreated panel dates removals the same way).
        self.removed_at: dict[str, int] = {}

    # ---------------------------------------------------------------- lifecycle
    def install(self) -> FindChartSync:
        """Make this the app's sync (``current()``)."""
        global _instance
        _instance = self
        return self

    def close(self) -> None:
        """Drop queued jobs, stop a running compute after its moment; does not
        wait for it (the store keeps every finished batch)."""
        global _instance
        self._closing.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if _instance is self:
            _instance = None

    def flush(self, timeout: float | None = None) -> None:
        """Wait for every job queued so far (tests, a clean shutdown). A
        job's failure is its caller's (``report``), never raised here; a
        timeout still is."""
        pending, self._pending = self._pending, []
        _done, not_done = wait(pending, timeout)
        if not_done:
            raise TimeoutError(f"{len(not_done)} index job(s) still running")

    # ------------------------------------------------------------------ events
    def session_saved(
        self, profile: str, charts: Sequence[Mapping[str, object]]
    ) -> None:
        """The session manager wrote ``profile``'s ``charts`` (session.json
        shape). Skipped when the charts are the ones synced last."""
        raw = _snapshot(charts)
        if self._last_session == (profile, raw):
            return
        self._last_session = (profile, raw)
        self._submit(self._sync_sessions, CurrentSession(profile, json.loads(raw)))

    def panel_shown(self, current: CurrentSession | None) -> Future[None] | None:
        """Find Chart came on screen: every profile, unconditionally (another
        window may have changed one). ``current`` None reads the running
        profile from disk too. Returns the job (the panel refreshes when it is
        done), None once closing."""
        if current is not None:
            raw = _snapshot(current.charts)
            self._last_session = (current.profile, raw)
            current = CurrentSession(current.profile, json.loads(raw))
        return self._submit(self._sync_sessions, current)

    def file_written(self, path: str | os.PathLike[str]) -> Future[None] | None:
        """The app saved or downloaded a chart file: upsert it, compute it.
        Returns the job (None when suppressed or closing)."""
        if _suppressed():
            return None
        return self._submit(self._sync_file, Path(path))

    def file_indexed(self, path: str | os.PathLike[str]) -> None:
        """The file's entry is already upserted (``chart_creation_pipeline``
        does it in line): compute it."""
        if not _suppressed():
            self._submit(self._compute, _file_scope(Path(path)))

    def folders_changed(
        self,
        folders: Sequence[str | os.PathLike[str]],
        current: CurrentSession | None,
    ) -> Future[None] | None:
        """The chart folder list is now ``folders``: forget the files under
        none of them, then sync the sessions (a loaded chart among them stays,
        as a session entry; ``current`` as in ``panel_shown``). Never a scan.
        Returns the job (None once closing); it fails when the forget does
        (the transaction rolled back), so the panel can say so, and with
        ``ForgetSuperseded`` when a later ``folder_list_changed`` came before
        its write (it then writes nothing)."""
        if current is not None:
            raw = _snapshot(current.charts)
            self._last_session = (current.profile, raw)
            current = CurrentSession(current.profile, json.loads(raw))
        generation = self.folder_list_changed()
        job = self._submit(
            self._forget_folders,
            tuple(Path(f) for f in folders),
            current,
            generation,
            report=True,
        )
        if job is not None:
            job.generation = generation  # the panel dates what it settles
        return job

    def folder_list_changed(self) -> int:
        """The folder list changed (a folder added back, say): any forget
        queued before now is superseded. Returns the new generation."""
        with self._folders_lock:
            self._folders_generation += 1
            return self._folders_generation

    def file_removed(self, path: str | os.PathLike[str]) -> Future[None] | None:
        """The app moved a chart file away (trash): forget its entry. Returns
        the job (None when suppressed or closing)."""
        if _suppressed():
            return None
        return self._submit(self._forget, str(Path(path)))

    # -------------------------------------------------------------------- jobs
    def _submit(
        self, job: Callable[..., None], *args: object, report: bool = False
    ) -> Future[None] | None:
        """``report``: the future fails when the job does (its caller acts
        on the outcome, review r10); otherwise a failure is only logged."""
        if self._closing.is_set():
            return None
        self._pending = [f for f in self._pending if not f.done()]
        future = self._executor.submit(_reported if report else _logged, job, *args)
        self._pending.append(future)
        return future

    def _sync_sessions(self, current: CurrentSession | None) -> None:
        with StoreWriter.open() as store:
            sync.sync_sessions(store, self._profiles_dir(), current)
        self._compute(Scope(sources=Sources.LOADED))

    def _sync_file(self, path: Path) -> None:
        with StoreWriter.open() as store:
            item = sync.sync_file(store, path)
        if isinstance(item, Entry):
            self._compute(_file_scope(path))

    def _forget(self, path: str) -> None:
        with StoreWriter.open() as store:
            store.forget_paths((path,))
            store.collect_moments()

    def _forget_folders(
        self,
        folders: tuple[Path, ...],
        current: CurrentSession | None,
        generation: int | None = None,
    ) -> None:
        """A folder left the list (a scope change, FIND-005 §3.7): its files
        leave the index and the sessions are reconciled, in one transaction
        and with NO compute (round 9: a folder edit never computes; a
        session save keeps its own small unasked compute)."""
        if generation is not None and generation != self._folders_generation:
            raise ForgetSuperseded()  # cheap early out; checked again below
        held = False
        try:
            with StoreWriter.open() as store, store.atomically():
                sync.forget_folders(store, folders)
                sync.sync_sessions(store, self._profiles_dir(), current)
                # The lock covers only the final check and the commit (review
                # r13: a folder edit on the GUI thread never waits for the
                # forget's work): a change after the check waits for the
                # commit; one before it rolls the transaction back.
                self._folders_lock.acquire()
                held = True
                if generation is not None and generation != self._folders_generation:
                    raise ForgetSuperseded()
        finally:
            if held:
                self._folders_lock.release()

    def _compute(self, scope: Scope) -> None:
        """What ``scope`` lacks in the current system, if it is small enough
        to run unasked."""
        if self._closing.is_set():
            return
        system = self._system()
        with StoreWriter.open() as store:
            with store.snapshot():  # one state for the whole plan (review r16)
                work = compute.plan(store, system, _wanted(store, system), scope)
            if work.empty or work.needs_consent():
                return
            compute.run(store, work, _no_progress, self._closing.is_set)


def _wanted(store: StoreReader, system: SearchSystem) -> tuple[Extractor, ...]:
    """Positions (REBUILD INDEX's own), and every extractor already computed
    in ``system`` somewhere: a new chart joins what the user searches."""
    return tuple(
        e
        for e in registry.EXTRACTORS
        if e.id == positions.EXTRACTOR.id
        or store.projection_id(e.projection(system)) is not None
    )


def _file_scope(path: Path) -> Scope:
    """Exactly the entry of ``path`` (a folder filter on the file itself
    matches its path), whatever its kind."""
    return Scope(
        sources=Sources.FOLDERS,
        folders=(str(path),),
        include_fileless=False,
        kinds=frozenset(EntryKind),
    )


def _snapshot(charts: Sequence[Mapping[str, object]]) -> str:
    """The charts as canonical JSON: the worker's own copy (the memory
    panel's dicts stay on the UI thread) and the unchanged-save check."""
    return json.dumps(list(charts), sort_keys=True, default=str)


def _suppressed() -> bool:
    """A harness or test run's writes are not part of the user's database
    (``chart_creation_pipeline.index_new_chart_file``): they stay out."""
    return bool(os.environ.get(CHART_FOLDER_ENV))


def _no_progress(_update: compute.Progress) -> None:
    pass


def _logged(job: Callable[..., None], *args: object) -> None:
    try:
        job(*args)
    except Exception as exc:  # noqa: BLE001 - a cache sync never reaches the user
        debug_print(f"[FIND-SYNC] {job.__name__} failed: {type(exc).__name__}: {exc}")


def _reported(job: Callable[..., None], *args: object) -> None:
    """``_logged``, then the failure still reaches the job's future."""
    try:
        job(*args)
    except Exception as exc:
        debug_print(f"[FIND-SYNC] {job.__name__} failed: {type(exc).__name__}: {exc}")
        raise
