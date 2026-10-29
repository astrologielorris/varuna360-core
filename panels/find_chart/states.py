# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart states table as texts (SPEC-FIND-005 §3.7 "States"), and
the Library's coverage rows (§3.7 "Coverage snapshot"). Qt-free: the status
bar, the trail and the Library display what these return, the host decides
which state it is in.

Status bar states, each a ``StatusState(text, tone, cancel_label)``:

- ``no_index()``: "No index: REBUILD INDEX" (trail: ``TRAIL_NO_INDEX``);
- ``syncing(done, total)``: the scan's progress line text (total 0 while
  discovering = indeterminate), CANCEL;
- ``sync_cancelled()``: "Rebuild cancelled: nothing changed";
- ``sync_writing()``: "Updating the index" after the commit point, CANCEL
  reads "Cancel the computation"; ``computation_cancelled()`` once the writes
  finish after that cancel;
- ``sync_failed(reason)``: "Rebuild failed: <reason>" (error);
- ``store_busy(retrying)``: "The index is busy, retrying" / "Index busy: try
  again";
- ``computing(what, done, total, already)``: the compute progress text, CANCEL;
- ``compute_failed()``: "Some charts could not be computed" with the RETRY
  notice action (``COMPUTE_FAILED_NOTICE``);
- stale rings: tooltip ``STALE_TOOLTIP`` ("computed by an older version").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from core.chart_search.extractors import registry
from core.chart_search.search import Coverage

NORMAL = ""
WARN = "warn"
ERROR = "error"

CANCEL = "CANCEL"
CANCEL_COMPUTATION = "Cancel the computation"
TRAIL_NO_INDEX = "No index yet"
STALE_TOOLTIP = "computed by an older version"
COMPUTE_FAILED_NOTICE = ("Some charts could not be computed", "RETRY")
#: A compute that stopped on an error (review r8 #7): the batches written
#: before it are kept; RESUME runs what that compute had left.
COMPUTE_STOPPED_NOTICE = ("The compute stopped on an error", "RESUME")


@dataclass(frozen=True)
class StatusState:
    """One status bar line: its text, its tone (``""``, ``"warn"``,
    ``"error"``) and, while a job runs, the CANCEL button's label (``None`` =
    no job)."""

    text: str
    tone: str = NORMAL
    cancel_label: str | None = None


def no_index() -> StatusState:
    return StatusState("No index: REBUILD INDEX", WARN)


def syncing(done: int, total: int) -> StatusState:
    if total <= 0:
        return StatusState("Reading chart folders", NORMAL, CANCEL)
    return StatusState(f"Reading chart folders: {done:,} / {total:,}", NORMAL, CANCEL)


def sync_cancelled() -> StatusState:
    return StatusState("Rebuild cancelled: nothing changed")


def sync_writing() -> StatusState:
    return StatusState("Updating the index", NORMAL, CANCEL_COMPUTATION)


def computation_cancelled() -> StatusState:
    return StatusState("Index refreshed; computation cancelled")


def sync_failed(reason: str) -> StatusState:
    reason = (reason or "").strip() or "unknown error"
    return StatusState(f"Rebuild failed: {reason}", ERROR)


def store_busy(retrying: bool) -> StatusState:
    if retrying:
        return StatusState("The index is busy, retrying", WARN)
    return StatusState("Index busy: try again", WARN)


def computing(what: str, done: int, total: int, already: int = 0) -> StatusState:
    return StatusState(progress_text(what, done, total, already), NORMAL, CANCEL)


def compute_failed() -> StatusState:
    return StatusState(f"{COMPUTE_FAILED_NOTICE[0]}: {COMPUTE_FAILED_NOTICE[1]}", WARN)


# ----------------------------------------------------------------- texts
# Kept from the retired coverage strip (W8): the CLI, the trail and the
# status bar name an extractor and a run alike.


def extractor_label(extractor_id: str) -> str:
    """The extractor's own label (``registry.label``), shared with the CLI and
    ``search_charts``."""
    return registry.label(extractor_id)


def coverage_text(coverage: tuple[Coverage, ...]) -> str:
    """``"Positions 5,012/5,012 · Avasthas 1,240/5,012 (3 failed)"``, plus the
    other app versions a stored result was computed with."""
    parts = []
    stale: set[str] = set()
    for item in coverage:
        if not item.in_scope:  # nothing to cover: say nothing
            continue
        part = f"{extractor_label(item.extractor_id)} {item.computed:,}/{item.in_scope:,}"
        if item.failed:
            part += f" ({item.failed:,} failed)"
        parts.append(part)
        stale.update(item.computed_with)
    text = " · ".join(parts)
    if stale:
        text += f" · computed with {', '.join(sorted(stale))}; recompute to be sure"
    return text


def progress_text(what: str, done: int, total: int, already: int) -> str:
    """``"Computing Positions: 120/800 (900 already computed)"``: a run
    covers only what is missing, so its total is not the chart count."""
    text = f"Computing {what}: {done:,}/{total:,}"
    if already:
        text += f" ({already:,} already computed)"
    return text


def incomplete(coverage: tuple[Coverage, ...]) -> tuple[str, ...]:
    """Extractor ids with charts left to compute (failed ones excluded: they
    need RETRY)."""
    return tuple(c.extractor_id for c in coverage if c.computed + c.failed < c.in_scope)


def recomputable(coverage: tuple[Coverage, ...]) -> tuple[str, ...]:
    """Extractor ids with failures or results from another app version."""
    return tuple(c.extractor_id for c in coverage if c.failed or c.computed_with)


def partial_text(names: str, missing: int) -> str:
    """The trail's partial state: "Avasthas not computed for 600 charts"
    (the action reads "COMPUTE (about 2 minutes)")."""
    return f"{names} not computed for {missing:,} {_plural(missing, 'chart')}"


def partial_action(duration: str) -> str:
    return f"COMPUTE (about {duration})"


# ----------------------------------------------------------------- counts


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def counts_text(charts: int, moments: int) -> str:
    """The status bar's "7,659 charts · 5,720 moments"."""
    return (
        f"{charts:,} {_plural(charts, 'chart')} · {moments:,} {_plural(moments, 'moment')}"
    )


def index_count_text(n: int) -> str:
    """The Library INDEX line: "7,659 charts in the index"."""
    if n <= 0:
        return TRAIL_NO_INDEX
    return f"{n:,} {_plural(n, 'chart')} in the index"


def short_path(path: str) -> str:
    """The status bar's short database path: its folder and file name
    ("cache/.find_chart_store_linux.sqlite")."""
    if not path:
        return ""
    p = PurePath(path)
    if p.parent.name:
        return f"{p.parent.name}/{p.name}"
    return p.name or str(p)


def cpu_text(percent: int) -> str:
    """The Library's CPU share line (without its Settings link)."""
    return f"Computing at {int(percent)} % of one core"


# ----------------------------------------------------------------- coverage


#: Button kinds, in the order the row shows them, with their count attribute.
ACTION_KINDS: tuple[tuple[str, str, str], ...] = (
    ("compute", "COMPUTE", "missing"),
    ("retry", "RETRY", "failed"),
    ("recompute", "RECOMPUTE", "stale"),
)


@dataclass(frozen=True)
class CoverageRow:
    """What one Library coverage row (and its status bar ring) shows."""

    extractor_id: str
    label: str
    count_text: str  # "5,120 of 5,720 birth moments"
    actions: tuple[tuple[str, str], ...]  # (kind, "COMPUTE 600"), nonzero only
    done: bool  # every count zero over a non-empty scope
    empty: bool  # nothing in scope
    fraction: float  # ring: computed / in_scope
    stale: bool  # small dot on the ring
    tooltip: str


def complete(c: Coverage) -> bool:
    """Counted in "COVERAGE k/9": a non-empty scope, every moment computed
    at the running version, none failed, none stale."""
    return c.in_scope > 0 and c.missing == 0 and c.failed == 0 and c.stale == 0


def coverage_counter(snapshot: tuple[Coverage, ...]) -> str:
    """The status bar's "COVERAGE 6/9"."""
    return f"COVERAGE {sum(complete(c) for c in snapshot)}/{len(snapshot)}"


def ring_fraction(c: Coverage) -> float:
    return c.computed / c.in_scope if c.in_scope > 0 else 0.0


def elsewhere_text(c: Coverage) -> str:
    """The ``Coverage.elsewhere`` explanation kept in the tooltip."""
    lines = []
    for item in c.elsewhere:
        fields = ", ".join(f"{name.replace('_', ' ')} {value}" for name, value in item.fields)
        where = f" ({fields})" if fields else ""
        lines.append(
            f"Computed in another system{where} for {item.computed:,} "
            f"{_plural(item.computed, 'moment')}"
        )
    return "\n".join(lines)


def coverage_tooltip(c: Coverage, noun: str = "birth moments") -> str:
    label = extractor_label(c.extractor_id)
    lines = [f"{label}: {c.computed:,} of {c.in_scope:,} {noun} computed"]
    if c.missing > 0:
        lines.append(f"{c.missing:,} not computed yet")
    if c.failed:
        lines.append(f"{c.failed:,} could not be computed")
    if c.stale:
        versions = f" ({', '.join(c.computed_with)})" if c.computed_with else ""
        lines.append(f"{c.stale:,} {STALE_TOOLTIP}{versions}")
    extra = elsewhere_text(c)
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def coverage_row(c: Coverage, noun: str = "birth moments") -> CoverageRow:
    """One coverage item as a Library row: one button per nonzero count,
    COMPUTE n (missing), RETRY n (failed), RECOMPUTE n (stale); DONE when all
    are zero; an empty scope shows neither."""
    actions = tuple(
        (kind, f"{word} {getattr(c, attr):,}")
        for kind, word, attr in ACTION_KINDS
        if getattr(c, attr) > 0
    )
    singular = noun[:-1] if noun.endswith("s") else noun
    return CoverageRow(
        extractor_id=c.extractor_id,
        label=extractor_label(c.extractor_id),
        count_text=f"{c.computed:,} of {c.in_scope:,} {singular if c.in_scope == 1 else noun}",
        actions=actions,
        done=c.in_scope > 0 and not actions,
        empty=c.in_scope == 0,
        fraction=ring_fraction(c),
        stale=c.stale > 0,
        tooltip=coverage_tooltip(c, noun),
    )


def scope_moments(snapshot: tuple[Coverage, ...]) -> int:
    """The COVERAGE header's moment count (every item shares the scope)."""
    return max((c.in_scope for c in snapshot), default=0)


#: A removed folder's charts could not leave the index (review r10): they
#: stay out of every search, and the next opening of the panel tries again.
FORGET_FAILED_TEXT = (
    "The charts of a removed folder could not be taken out of the index. "
    "They stay out of the results; Find Chart tries again when it next opens."
)
