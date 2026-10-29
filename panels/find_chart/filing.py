# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart panel's file mover worker, in every edition (SPEC-FIND-005
§4.9, SPEC-LIB-002 §4.8): ``SortWorker`` runs ``core.chart_sort``'s
``apply`` and ``undo`` off the GUI thread for Rate and Sort's filing and for
Sort with AI, with the stop helpers and the result texts.

No AI here: Lite ships this module (SPEC-EDN-002 INV-2). The request phase
"propose" runs only with an engine that has ``propose``, which
``sort_with_ai.SortWorker`` (Pro and up) supplies.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from PySide6.QtCore import QThread, Signal, Slot

from core import chart_sort
from core.chart_sort import Move, Proposal, SortError, SortReport, UndoReport

log = logging.getLogger(__name__)

PROPOSE, APPLY, UNDO = "propose", "apply", "undo"


#: How long a request may finish on panel close before it is detached (ms).
REQUEST_WAIT_MS = 3000


REBUILD_NUDGE = "Rebuild Index to search the moved charts"


_MESSAGES = {
    chart_sort.NO_KEY: "Sort with AI needs an AI key. Add one in Settings.",
    chart_sort.NO_CHARTS: "There are no unsorted charts to file.",
    chart_sort.NETWORK: (
        "The AI service could not be reached. Check your connection and try again."
    ),
    chart_sort.BAD_ANSWER: "The AI's answer could not be read. Nothing was moved. Try again.",
    chart_sort.LOG: (
        "The sort log could not be read or written, so nothing more was moved. "
        "Check sort_log.json in the unsorted folder."
    ),
    chart_sort.UNDO_NONE: "There is no sort to undo.",
    chart_sort.BAD_PROPOSAL: (
        "This proposal no longer matches your chart folder. Ask the AI again."
    ),
    chart_sort.BUSY: "Another sort is running. Try again shortly.",
}


_GENERIC = "The sort could not finish. Nothing more was moved. Try again."


def message_for(kind: str) -> str:
    """Neutral text for a ``SortError.kind`` (INV-7: "the AI", "the AI
    service", never a vendor or the key's setting name)."""
    return _MESSAGES.get(kind, _GENERIC)


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def result_text(report: SortReport, left: Sequence[str] = ()) -> str:
    """ "Sorted 11 charts (1 could not be moved, 1 had no proposal)"."""
    parts = []
    if report.failed:
        parts.append(f"{report.failed:,} could not be moved")
    if left:
        parts.append(f"{len(left):,} had no proposal")
    text = f"Sorted {_plural(report.moved, 'chart')}"
    return text + (f" ({', '.join(parts)})" if parts else "")


def undo_text(report: UndoReport) -> str:
    text = f"Moved back {_plural(report.restored, 'chart')}"
    if report.skipped:
        text += f" ({len(report.skipped):,} stayed where the sort put them)"
    return text


#: Detached workers, referenced until ``finished`` (never destroyed running);
#: the set lives with the panel's parked workers, which Lite ships too.
from panels.find_chart.workers import DETACHED_SORT as _DETACHED  # noqa: E402


class SortWorker(QThread):
    """One engine call off the GUI thread, on immutable inputs."""

    proposed = Signal(object)
    applied = Signal(object)
    undone = Signal(object)
    failed = Signal(str, str)
    progress = Signal(int, int)

    def __init__(self, phase: str, *, database=None, api_key: str = "", post=None,
                 proposal: Proposal | None = None, chosen: Sequence[Move] = (),
                 folder=None, entry_id: str | None = None, engine=None,
                 exclude: Sequence[str] = (), parent=None) -> None:
        super().__init__(parent)
        if phase not in (PROPOSE, APPLY, UNDO):
            raise ValueError(phase)
        self.phase = phase
        self._database = None if database is None else str(database)
        self._api_key = api_key
        self._post = post
        self._proposal = proposal
        self._chosen = tuple(chosen)
        self._folder = None if folder is None else str(folder)
        self._entry_id = entry_id
        self._engine = engine or chart_sort
        self._exclude = exclude if callable(exclude) else tuple(exclude)
        self._cancel = threading.Event()
        self._discarded = False
        self._detached = False
        self._polls = 0
        self._result = None
        self._error: tuple[str, str] | None = None
        self.finished.connect(self._on_finished)

    @classmethod
    def for_propose(cls, database, api_key: str, post=None, **kw) -> SortWorker:
        return cls(PROPOSE, database=database, api_key=api_key, post=post, **kw)

    @classmethod
    def for_apply(cls, proposal: Proposal, chosen: Sequence[Move], database, **kw) -> SortWorker:
        return cls(APPLY, proposal=proposal, chosen=chosen, database=database, **kw)

    @classmethod
    def for_undo(cls, folder, entry_id: str | None = None, **kw) -> SortWorker:
        return cls(UNDO, folder=folder, entry_id=entry_id, **kw)

    # -- control (GUI thread)
    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def discard(self) -> None:
        """Drop the result when it arrives (the switch went off)."""
        self._discarded = True
        self._cancel.set()

    @property
    def discarded(self) -> bool:
        return self._discarded

    @property
    def detached(self) -> bool:
        return self._detached

    # -- thread
    def _poll(self) -> bool:
        """``cancelled`` for the engine: called once before each file."""
        if self.phase == APPLY:
            self.progress.emit(self._polls, len(self._chosen))
        self._polls += 1
        return self._cancel.is_set()

    def run(self) -> None:
        eng = self._engine
        try:
            if self.phase == PROPOSE:
                extra = {"exclude": self._exclude} if self._exclude else {}
                self._result = eng.propose(self._database, self._api_key, post=self._post,
                                           **extra)
            elif self.phase == APPLY:
                self._result = eng.apply(self._proposal, self._chosen,
                                         database=self._database, cancelled=self._poll)
            else:
                extra = {} if self._entry_id is None else {"entry_id": self._entry_id}
                self._result = eng.undo(self._folder, cancelled=self._poll, **extra)
        except SortError as exc:
            log.info("sort %s failed (%s): %s", self.phase, exc.kind, exc.detail or exc)
            self._error = (exc.kind, message_for(exc.kind))
        except Exception as exc:  # noqa: BLE001 - reported, never raised in a thread
            log.warning("sort %s failed: %s", self.phase, exc)
            self._error = ("error", message_for("error"))

    @Slot()
    def _on_finished(self) -> None:
        """GUI thread: deliver, unless discarded or detached."""
        if self._detached:
            _DETACHED.discard(self)
            self.deleteLater()
            return
        if self._discarded:
            return
        if self._error is not None:
            self.failed.emit(*self._error)
        elif self.phase == PROPOSE:
            self.proposed.emit(self._result)
        elif self.phase == APPLY:
            self.applied.emit(self._result)
        else:
            self.undone.emit(self._result)


def _disconnect_all(worker: SortWorker) -> None:
    import warnings

    for sig in (worker.proposed, worker.applied, worker.undone, worker.failed, worker.progress):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass


def detach_worker(worker: SortWorker) -> None:
    """Signals off, no parent, referenced until ``finished``, then deleted."""
    worker._detached = True
    _disconnect_all(worker)
    worker.setParent(None)
    if worker.isRunning():
        _DETACHED.add(worker)
    else:
        worker.deleteLater()


def discard_request(worker: SortWorker | None) -> None:
    """The switch went off: a running request's result is dropped."""
    if worker is not None and worker.phase == PROPOSE:
        worker.discard()


def needs_finishing(worker: SortWorker | None) -> bool:
    return worker is not None and worker.phase in (APPLY, UNDO) and worker.isRunning()


def stop_worker(worker: SortWorker | None, *, app_quit: bool = False) -> bool:
    """§4.9 per phase. True when the worker has returned (the host may drop
    it), False when it was detached and keeps running on its own."""
    if worker is None or not worker.isRunning():
        return True
    if worker.phase == PROPOSE:
        worker.discard()
        if worker.wait(REQUEST_WAIT_MS):
            return True
        detach_worker(worker)
        return False
    worker.cancel()
    if app_quit:
        worker.wait()  # no time cap: the current file and its journal finish
        return True
    detach_worker(worker)
    return False
