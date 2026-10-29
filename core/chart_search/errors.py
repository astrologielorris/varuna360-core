# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart error taxonomy (design.md §4.10).

Three kinds of failure, kept apart on purpose:

- **Raised** (``ChartSearchError``): the caller asked for something that cannot
  be answered (a bad system field, a bad filter, no store, a busy store). Each
  carries the capability error code it becomes (``error_type``); the
  ``search_charts`` capability re-raises it as an ``OptionError`` with that type,
  the catalog's existing pattern for typed errors.
- **Recorded** (``Unreadable``, ``computations.status = failed``): one source or
  one moment x extractor failed. Data, never raised: a scan or a compute run
  never stops on one chart (principle 6).
- **Invariant** (``InvariantError``): our own code broke a rule it guarantees
  (a projection row missing right after its upsert). Raised, never caught.

Partial coverage and a stale app-version stamp are not errors: they are
reported in ``search.Coverage``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal


class ChartSearchError(Exception):
    """A request Find Chart cannot answer. ``error_type`` is the capability code."""

    error_type: ClassVar[str] = "chart_search_error"


class BadSystemError(ChartSearchError):
    """An unknown search-system field or a value it cannot take (ayanamsa 97
    while the libaditya reconciliation is pending, an unknown house system)."""

    error_type = "bad_option"

    def __init__(self, field: str, value: object, valid: tuple[object, ...]) -> None:
        self.field = field
        self.value = value
        self.valid = valid
        choices = ", ".join(str(v) for v in valid)
        if field in _system_fields():
            message = (
                f"search_system.{field} cannot be {value!r}; valid values: {choices}"
            )
        else:
            message = f"unknown search-system field {field!r}; valid fields: {choices}"
        super().__init__(message)


def _system_fields() -> frozenset[str]:
    from core.chart_search.system import Field

    return frozenset(f.value for f in Field)


class BadFilterError(ChartSearchError):
    """Unknown subject or property, a value or label that does not resolve, an
    undeclared qualifier. ``valid`` lists what is valid at the failing level
    (subjects of the property, values of the property, qualifier names)."""

    error_type = "bad_filter"

    def __init__(self, message: str, valid: tuple[str, ...]) -> None:
        self.message = message
        self.valid = valid
        super().__init__(f"{message}; valid: {', '.join(valid)}" if valid else message)


class NoIndexError(ChartSearchError):
    """No store file, or one whose ``meta.schema_version`` differs. A reader
    never repairs it; ``chart_index refresh`` (or REBUILD INDEX) does."""

    error_type = "no_index"

    def __init__(self, reason: Literal["missing", "schema_mismatch"]) -> None:
        self.reason = reason
        what = (
            "no chart index"
            if reason == "missing"
            else "the chart index schema differs"
        )
        super().__init__(f"{what}; run: python -m AI_tools.cli.chart_index refresh")


class BadStoreFileError(ChartSearchError):
    """An index file to import is missing, not a Find Chart index, written at
    another schema, or the store itself."""

    error_type = "bad_store_file"


class StoreBusyError(ChartSearchError):
    """A write batch still locked out after ``busy_timeout`` and one retry."""

    error_type = "store_busy"


class SnapshotRetry(StoreBusyError):
    """A read snapshot could not continue on its connection (an FTS index
    another writer merged meanwhile, review r16): the whole read restarts on
    a fresh reader, exactly as for a busy store."""


class InvariantError(RuntimeError):
    """A broken guarantee of this package's own code. The message starts with
    ``invariant:`` and names what would have to break."""


@dataclass(frozen=True)
class Unreadable:
    """A source that produced no entry. ``source`` is a file path, or
    ``session:<profile>`` / ``session:<profile>:<uuid>`` for a session or one
    of its charts. Files are recorded in the ``unreadable`` table with their
    mtime and size (not re-parsed while unchanged); sessions are re-read on
    every sync and only reported."""

    source: str
    error: str
    mtime: float | None = None
    size: int | None = None
