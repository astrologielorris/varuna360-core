# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one compute loop (design.md §4.6, D9). Driven by the panel's QThread
worker and by ``chart_index compute``; headless searches never call it.

``plan`` is read only and cheap: what is missing and what it will cost.
``run`` does the work in batches of ``BATCH_SIZE`` moments, one transaction per
batch per extractor, so a cancel or a crash loses at most one batch and the
next plan resumes. One moment x extractor failing is recorded, never raised,
and reported (``report_failure``): the first failure of each extractor in a run
with its traceback, then a count at the end of the run.

**Moment-major.** ``run`` walks the batch moment by moment and hands one
``MomentCharts`` to every extractor that needs the moment, so Positions,
Dignity and Avasthas in one system build the chart once. The chart's build
time is measured against the first extractor that asks for it: the recorded
costs are what a run of the same extractor set takes, not an exact split.
"""

from __future__ import annotations

import sys
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from core.diagnostics import get_logger
from core.chart_search.extractors.base import Extractor, MomentCharts, Row
from core.chart_search.search import Scope, candidates
from core.chart_search.sources import Moment
from core.chart_search.stamp import computation_stamp
from core.chart_search.store import (
    ComputationState,
    Computed,
    Failed,
    MomentId,
    Outcome,
    StoreReader,
    StoreWriter,
)
from core.chart_search.system import Projection, SearchSystem
from core.chart_search.taxonomy import PropertySpec, Value, ValueKind

BATCH_SIZE = 50
#: Above this estimate, the first compute asks (with "Don't ask again").
#: Measured (design.md §4.6): about 200-300 moments of one extractor, while
#: any first compute over a 5,000-chart library (160 s or more) asks.
CONSENT_THRESHOLD_S = 10.0
#: Used for an extractor never measured on this machine. Above every measured
#: cost (highest: Positions in Sidereal mode, 0.063 s): guessing high costs one
#: extra prompt, guessing low starts a long run unasked.
UNMEASURED_COST_S = 0.1
#: FIND-003 §4: progress at most this often.
PROGRESS_INTERVAL_S = 0.1


@dataclass(frozen=True)
class PlanItem:
    extractor: Extractor
    projection: Projection
    missing: tuple[MomentId, ...]  # visible-query moments first
    estimate_s: float
    in_scope: int  # moments, not entries: two files of one birth compute once

    @property
    def already(self) -> int:
        """In-scope moments left out: computed (or failed, unless retried)."""
        return self.in_scope - len(self.missing)


@dataclass(frozen=True)
class ComputePlan:
    system: SearchSystem
    items: tuple[PlanItem, ...]  # only extractors with something missing
    #: The exact moment inputs a direct action was consented for (the
    #: inspector's chart, review r15): a moment whose stored inputs differ
    #: when the run reads it (another writer rebuilt the index) is skipped.
    expected: tuple[tuple[MomentId, Moment], ...] = ()

    @property
    def estimate_s(self) -> float:
        return sum(item.estimate_s for item in self.items)

    @property
    def empty(self) -> bool:
        return not any(item.missing for item in self.items)

    def needs_consent(self, threshold_s: float = CONSENT_THRESHOLD_S) -> bool:
        return self.estimate_s > threshold_s


@dataclass(frozen=True)
class Progress:
    extractor_id: str
    done: int
    total: int


@dataclass(frozen=True)
class ExtractorReport:
    extractor_id: str
    computed: int
    failed: int
    seconds: float


@dataclass(frozen=True)
class ComputeReport:
    items: tuple[ExtractorReport, ...]
    cancelled: bool


def plan(
    store: StoreReader,
    system: SearchSystem,
    extractors: tuple[Extractor, ...],
    scope: Scope,
    *,
    priority: frozenset[MomentId] = frozenset(),
    retry_failed: bool = False,
    recompute_stale: bool = False,
    among: frozenset[MomentId] | None = None,
) -> ComputePlan:
    """Missing = in-scope moments without an ``ok`` computation at the current
    extractor version (and, with ``retry_failed``, the failed ones). The
    app-version stamp does not make a row missing; Recompute does that
    explicitly: ``recompute_stale`` adds the ``ok`` rows stamped with another
    app version (with ``retry_failed``, the panel's Recompute). ``among``
    restricts the work to those in-scope moments (the Find Chart inspector's
    one chart, SPEC-FIND-005 §3.6). Every read runs in ONE snapshot (review
    r16), joined when the caller already holds one."""
    with store.snapshot():
        return _plan(store, system, extractors, scope, priority,
                     retry_failed, recompute_stale, among)


def _plan(store, system, extractors, scope, priority, retry_failed,
          recompute_stale, among) -> ComputePlan:
    moments = frozenset(row.moment_id for row in candidates(store, scope))
    if among is not None:
        moments &= among
    running = computation_stamp()
    items: list[PlanItem] = []
    planned: set[MomentId] = set()
    for extractor in extractors:
        projection = extractor.projection(system)
        pid = store.projection_id(projection)
        states = {} if pid is None else store.states(pid, extractor.version, moments)
        missing = tuple(
            sorted(
                (
                    mid
                    for mid in moments
                    if _missing(states.get(mid), retry_failed, recompute_stale, running)
                ),
                key=lambda mid: (mid not in priority, mid),
            )
        )
        if not missing:
            continue
        planned.update(missing)
        cost = store.mean_cost(extractor.id)
        per_moment = UNMEASURED_COST_S if cost is None else cost
        items.append(
            PlanItem(
                extractor,
                projection,
                missing,
                len(missing) * per_moment,
                len(moments),
            )
        )
    # The exact moments planned, read in the caller's snapshot (review r15):
    # a run computes a moment only while the store still holds exactly it.
    expected = tuple(sorted(store.moments(frozenset(planned)).items()))
    return ComputePlan(system, tuple(items), expected)


def _missing(
    state: ComputationState | None,
    retry_failed: bool,
    recompute_stale: bool,
    running: str,
) -> bool:
    if state is None:
        return True
    if not state.ok:
        return retry_failed
    return recompute_stale and state.app_version != running


def run(
    store: StoreWriter,
    plan: ComputePlan,
    progress: Callable[[Progress], None],
    cancelled: Callable[[], bool],
) -> ComputeReport:
    """``progress`` is called at most every ~100 ms (FIND-003 §4); ``cancelled``
    is polled between moments. Records the measured cost per extractor.
    Raises ``StoreBusyError`` only when a batch cannot be written."""
    running = computation_stamp()
    items = plan.items
    pids = {
        item.extractor.id: store.ensure_projection(item.projection) for item in items
    }
    wanted = {item.extractor.id: frozenset(item.missing) for item in items}
    tally = {item.extractor.id: _Tally() for item in items}
    report = _Throttled(progress)

    # Each item lists its visible-query moments first; a moment goes where it
    # ranks best in any item, so every item's priority survives the merge.
    rank: dict[MomentId, int] = {}
    for item in items:
        for index, mid in enumerate(item.missing):
            rank[mid] = min(rank.get(mid, index), index)
    order = sorted(rank, key=lambda mid: (rank[mid], mid))

    stopped = False
    for start in range(0, len(order), BATCH_SIZE):
        batch = order[start : start + BATCH_SIZE]
        moments = store.moments(frozenset(batch))
        results: dict[str, list[tuple[MomentId, Outcome]]] = {
            item.extractor.id: [] for item in items
        }
        expected = dict(plan.expected)
        for mid in batch:
            if cancelled():
                stopped = True
                break
            moment = moments.get(mid)
            if moment is None or expected.get(mid) != moment:
                # Not the birth the plan was made for, or a plan without its
                # exact moment (review r16: fail closed): skipped.
                moment = None
            charts = None if moment is None else MomentCharts(moment)
            for item in items:
                eid = item.extractor.id
                if mid not in wanted[eid]:
                    continue
                count = tally[eid]
                count.done += 1
                if moment is not None and charts is not None:
                    began = time.perf_counter()
                    outcome = _outcome(
                        item.extractor,
                        moment,
                        item.projection,
                        charts,
                        trace=count.failed == 0,
                    )
                    count.seconds += time.perf_counter() - began
                    results[eid].append((mid, outcome))
                    if isinstance(outcome, Computed):
                        count.computed += 1
                    else:
                        count.failed += 1
                report(Progress(eid, count.done, len(item.missing)))
        # Written even when cancelled mid-batch: those moments are done.
        for item in items:
            outcomes = results[item.extractor.id]
            if outcomes:
                store.write_batch(
                    pids[item.extractor.id],
                    item.extractor.version,
                    running,
                    outcomes,
                    inputs={mid: moments[mid] for mid, _o in outcomes},
                    projection=item.projection,
                )
        if stopped:
            break
    report.flush()

    for eid, count in tally.items():
        measured = count.computed + count.failed
        if measured:
            store.record_cost(eid, count.seconds / measured, measured)
        if count.failed:
            report_failure(f"{eid}: {count.failed:,} of {measured:,} moments failed")
    return ComputeReport(
        tuple(
            ExtractorReport(eid, count.computed, count.failed, count.seconds)
            for eid, count in tally.items()
        ),
        stopped,
    )


@dataclass
class _Tally:
    done: int = 0  # progress: computed, failed, or skipped (moment collected)
    computed: int = 0
    failed: int = 0
    seconds: float = 0.0


class _Throttled:
    """Passes on at most one ``Progress`` per ``PROGRESS_INTERVAL_S``; ``flush``
    delivers the last one held back per extractor, so the caller sees the end."""

    def __init__(self, sink: Callable[[Progress], None]) -> None:
        self._sink = sink
        self._last = float("-inf")
        self._held: dict[str, Progress] = {}

    def __call__(self, update: Progress) -> None:
        now = time.monotonic()
        if now - self._last >= PROGRESS_INTERVAL_S:
            self._last = now
            self._held.pop(update.extractor_id, None)
            self._sink(update)
        else:
            self._held[update.extractor_id] = update

    def flush(self) -> None:
        for update in self._held.values():
            self._sink(update)
        self._held.clear()


def report_failure(message: str, exc: BaseException | None = None) -> None:
    """A compute failure to the terminal and to the app log, with ``exc``'s
    traceback. The store keeps only the one-line reason, which is not enough
    to find the cause."""
    get_logger("find_chart").warning(message, exc_info=exc)
    print(f"[FIND_CHART] {message}", file=sys.stderr)
    if exc is not None:
        traceback.print_exception(exc, file=sys.stderr)


def _outcome(
    extractor: Extractor,
    moment: Moment,
    projection: Projection,
    charts: MomentCharts,
    *,
    trace: bool,
) -> Outcome:
    """One moment x extractor, never raising (principle 6). With ``trace``, a
    failure is also reported; ``run`` asks for the first per extractor only,
    as one cause usually fails every moment."""
    try:
        rows = extractor.extract(moment, projection, charts)
    except Exception as exc:  # noqa: BLE001 - recorded, never raised (principle 6)
        if trace:
            report_failure(
                f"{extractor.id} failed at jd {moment.jd_ut} ({projection.key}); "
                "its later failures in this run are counted only",
                exc,
            )
        return Failed(f"{type(exc).__name__}: {exc}")
    violation = contract_violation(extractor, rows)
    if violation is not None:
        if trace:
            report_failure(f"{violation} at jd {moment.jd_ut} ({projection.key})")
        return Failed(violation)
    return Computed(rows)


def contract_violation(extractor: Extractor, rows: Sequence[Row]) -> str | None:
    """``"contract: ..."`` for the first row breaking ``extractors.base``'s
    contract (declared property, listed subject, value in the domain,
    qualifiers filled to the declared count from their closed sets, one row per
    subject and qualifiers unless the property is ``multi``); None if none."""
    specs = {spec.name: spec for spec in extractor.properties}
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for row in rows:
        where = f"contract: {extractor.id} {row.subject}.{row.property}"
        spec = specs.get(row.property)
        if spec is None:
            return f"{where}: property not declared"
        if row.subject not in spec.subjects:
            return f"{where}: subject not declared"
        if not _in_domain(spec, row.value):
            return f"{where}: value {row.value!r} outside its domain"
        for index, value in enumerate((row.q1, row.q2)):
            if index >= len(spec.qualifiers):
                if value is not None:
                    return f"{where}: q{index + 1} {value!r} not declared"
                continue
            qualifier = spec.qualifiers[index]
            if value is None:
                return f"{where}: qualifier {qualifier.name} missing"
            if qualifier.values is not None and value not in qualifier.values:
                return f"{where}: {qualifier.name} {value!r} not declared"
        key = (row.subject, row.property, row.q1, row.q2)
        if not spec.multi and key in seen:
            return f"{where}: more than one row ({row.q1}, {row.q2})"
        seen.add(key)
    return None


def _in_domain(spec: PropertySpec, value: Value) -> bool:
    """Exact type (a bool is not an ordinal), then membership."""
    expected = int if spec.kind is ValueKind.ORDINAL else str
    return type(value) is expected and value in spec.values
