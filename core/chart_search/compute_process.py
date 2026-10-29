# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``compute.run`` in a child process at low priority, held to a CPU share
(Lorris, 2026-10-18).

A compute on a worker thread of the app shares the app's interpreter: Python
runs one thread at a time, so while it computes every click, scroll and
repaint waits its turn and the app crawls. A child process has its own
interpreter, so the app's thread never waits for it. The child also runs at
the lowest OS priority (the desktop and the app outrank it) and keeps to
``cpu_percent`` of one core: after each moment it sleeps in proportion to the
time that moment took, so 40 % computes for 0.4 s in every second.

The parent keeps the interface of ``compute.run``: ``progress`` and
``cancelled`` are called on the caller's thread, and the ``ComputeReport`` (or
the child's error) comes back when the child ends. Every finished batch is
already in the store when the child stops, cancelled or not, as in
``compute.run``.

``freeze_support`` in ``run_app.py`` lets a frozen build start the child.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import sys
import time
from collections.abc import Callable
from pathlib import Path

from core.chart_search import compute
from core.chart_search.compute import ComputePlan, ComputeReport, Progress

#: The setting holding the CPU share, 10-100 (factory 40).
CPU_PERCENT_KEY = "ui.find_chart_compute_cpu_percent"


#: How often the parent polls the child's messages and ``cancelled`` (s).
POLL_S = 0.1

#: After Cancel, how long the child may take to finish its chart and write
#: its batch before it is stopped (s). Stopping loses only the unwritten
#: batch: the store's writes are transactions.
CANCEL_GRACE_S = 1.5


class ComputeProcessError(RuntimeError):
    """The child failed: its exception, as text."""


def run(
    plan: ComputePlan,
    store_file: Path,
    progress: Callable[[Progress], None],
    cancelled: Callable[[], bool],
    *,
    cpu_percent: int,
) -> ComputeReport:
    """Run ``plan`` into ``store_file`` in a child process; block until it ends."""
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    stop = context.Event()
    child = context.Process(
        target=_child,
        args=(plan, str(store_file), int(cpu_percent), messages, stop),
        name="find-chart-compute",
        daemon=True,
    )
    child.start()
    cancel_at = None
    try:
        while True:
            if cancel_at is None and cancelled():
                stop.set()
                cancel_at = time.monotonic()
            if cancel_at is not None and time.monotonic() - cancel_at > CANCEL_GRACE_S:
                child.terminate()
                return ComputeReport((), True)
            try:
                kind, value = messages.get(timeout=POLL_S)
            except queue.Empty:
                if not child.is_alive():
                    raise ComputeProcessError(
                        f"the compute process ended (exit code {child.exitcode})"
                    ) from None
                continue
            if kind == "progress":
                progress(Progress(*value))
            elif kind == "done":
                return value
            else:
                raise ComputeProcessError(value)
    finally:
        stop.set()
        child.join(timeout=10)
        if child.is_alive():
            child.terminate()
            child.join()
        messages.close()


def _child(plan, store_file, cpu_percent, messages, stop) -> None:
    """The child's whole life: lowest priority, compute, report."""
    _lowest_priority()
    from core.chart_search.store import StoreWriter

    pace = _Pace(cpu_percent)

    def cancelled() -> bool:
        pace.rest()  # between moments: keep to the CPU share
        return stop.is_set()

    def progress(update: Progress) -> None:
        messages.put(("progress", (update.extractor_id, update.done, update.total)))

    try:
        # A spawned child starts with the engine's default id-255 definition:
        # install the one the plan was made under, or custom-ayanamsa rows are
        # computed with the default and stored as the user's (review 2026-10-23).
        custom = plan.system.custom_ayanamsa
        if custom is not None:
            from libaditya.custom_ayanamsa import set_custom_ayanamsa
            set_custom_ayanamsa(custom.value_deg, custom.year)
        with StoreWriter.open(Path(store_file)) as store:
            report = compute.run(store, plan, progress, cancelled)
        messages.put(("done", report))
    except Exception as exc:  # noqa: BLE001 - sent to the parent, which raises it
        compute.report_failure("compute failed", exc)
        messages.put(("error", f"{type(exc).__name__}: {exc}"))


class _Pace:
    """Sleeps after each stretch of work so the work is ``percent`` % of the
    time: a stretch of ``w`` seconds is followed by ``w * (100 / percent - 1)``.
    The stretch is measured in this process's CPU time, so time the OS gave
    to other programs does not count as work."""

    def __init__(self, percent: int) -> None:
        self._ratio = 100.0 / min(max(percent, 5), 100) - 1.0
        self._mark = time.process_time()

    def rest(self) -> None:
        if self._ratio > 0:
            worked = time.process_time() - self._mark
            if worked > 0:
                time.sleep(worked * self._ratio)
        self._mark = time.process_time()


def _lowest_priority() -> None:
    """The OS's lowest priority for this process (best effort)."""
    try:
        if sys.platform == "win32":
            import ctypes

            idle_priority_class = 0x00000040
            kernel32 = ctypes.windll.kernel32
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), idle_priority_class)
        else:
            os.nice(19)
    except (OSError, AttributeError):
        pass
