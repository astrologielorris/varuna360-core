# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The only SQL (design.md §4.5). The store knows no astrology: it holds
entries, moments and rows, and answers "which moments have rows matching
these constraints".

**Two handles, one file.** ``StoreReader`` is cheap to open (no creation, no
migration, ``PRAGMA query_only``, short busy timeout), for searches and the
headless CLI; ``StoreWriter`` owns creation and the schema check, for sync,
scan and compute. Two writers may run at once (the app; ``chart_index``):
WAL, every batch in ``BEGIN IMMEDIATE``, idempotent upserts, so they can
duplicate work but never corrupt it. A long-lived reader that gets
"database disk image is malformed" on an FTS MATCH reopens and retries once
(FTS5 automerge by another writer), it is not corruption.

**Invalidation (D10).** ``meta.schema_version != SCHEMA_VERSION``: a reader
raises ``NoIndexError("schema_mismatch")``; a writer discards the contents and
creates an empty store (it is a cache; the sources are the truth). The discard
drops every table inside one ``BEGIN IMMEDIATE``, so a concurrent writer sees
the old schema or the new one, never half of either; only a file that is not
a database at all is unlinked. An extractor version bump makes its rows count
as missing. Every computation is stamped with ``stamp.computation_stamp()``.

**Export and import** (varuna/50). ``export_store`` writes a consistent,
compacted copy (``VACUUM INTO``). ``StoreWriter.import_computations`` merges
another index's computed results by moment key into the moments this store
already has; entries are never imported (their paths and sessions belong to
the machine that wrote them), so on a new machine the folders are synced
first and the import fills their charts.

**Sets of ids** travel as one JSON array parameter (``json_each``), never as
temp tables (a reader is query-only) or as one placeholder per id (SQLite's
variable limit).
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import NewType, Self, TypeVar

from core.chart_search.errors import (
    BadStoreFileError,
    InvariantError,
    NoIndexError,
    SnapshotRetry,
    StoreBusyError,
    Unreadable,
)
from core.chart_search.extractors.base import Row
from core.chart_search.sources import (
    Entry,
    EntryId,
    EntryKind,
    FileOrigin,
    FileState,
    Loaded,
    Moment,
    MomentKey,
    SessionOrigin,
)
from core.chart_search.system import Projection

SCHEMA_VERSION = 2
BUSY_TIMEOUT_MS = 5000  # writers; one retry per batch, then StoreBusyError
READER_BUSY_TIMEOUT_MS = 250

MomentId = NewType("MomentId", int)
ProjectionId = NewType("ProjectionId", int)

SCHEMA_SQL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE moments (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,                 -- MomentKey.encode()
    jd_ut REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
    utc_offset REAL NOT NULL                  -- hours
);

CREATE TABLE entries (
    rid INTEGER PRIMARY KEY,                  -- the FTS rowid; stable across VACUUM
    id TEXT NOT NULL UNIQUE,                  -- EntryId
    moment_id INTEGER NOT NULL REFERENCES moments(id),
    origin TEXT NOT NULL CHECK (origin IN ('file', 'session')),
    path TEXT,                                -- file path, or a session entry's chtk_path
    profile TEXT, session_id TEXT,            -- session entries only
    name TEXT NOT NULL, place TEXT NOT NULL, country TEXT NOT NULL, notes TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('birth', 'transit', 'event', 'trial')),
    birth_local TEXT NOT NULL,
    file_mtime REAL, file_size INTEGER,       -- file entries only
    unsaved_changes INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE INDEX entries_moment ON entries(moment_id);
CREATE INDEX entries_path ON entries(path);
CREATE INDEX entries_session ON entries(profile, origin);

CREATE TABLE entry_loaded (                   -- file entries a session holds unchanged
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    profile TEXT NOT NULL, session_id TEXT NOT NULL,
    PRIMARY KEY (entry_id, profile, session_id)
);
CREATE INDEX entry_loaded_profile ON entry_loaded(profile);

CREATE VIRTUAL TABLE entries_fts USING fts5(
    name, place, country, notes, content='entries', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER entries_fts_insert AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, name, place, country, notes)
    VALUES (new.rid, new.name, new.place, new.country, new.notes);
END;
CREATE TRIGGER entries_fts_delete AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, name, place, country, notes)
    VALUES ('delete', old.rid, old.name, old.place, old.country, old.notes);
END;
CREATE TRIGGER entries_fts_update AFTER UPDATE OF name, place, country, notes ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, name, place, country, notes)
    VALUES ('delete', old.rid, old.name, old.place, old.country, old.notes);
    INSERT INTO entries_fts(rowid, name, place, country, notes)
    VALUES (new.rid, new.name, new.place, new.country, new.notes);
END;

CREATE TABLE unreadable (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, error TEXT NOT NULL);

CREATE TABLE projections (
    id INTEGER PRIMARY KEY,
    extractor_id TEXT NOT NULL, key TEXT NOT NULL,   -- Projection.key
    UNIQUE (extractor_id, key)
);

CREATE TABLE computations (
    moment_id INTEGER NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    projection_id INTEGER NOT NULL REFERENCES projections(id),
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    error TEXT,
    extractor_version INTEGER NOT NULL, app_version TEXT NOT NULL, computed_at REAL NOT NULL,
    PRIMARY KEY (moment_id, projection_id)
);

CREATE TABLE properties (
    moment_id INTEGER NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    projection_id INTEGER NOT NULL REFERENCES projections(id),
    subject TEXT NOT NULL, property TEXT NOT NULL, value NOT NULL,   -- INTEGER or TEXT
    q1 TEXT, q2 TEXT
);
CREATE INDEX properties_lookup ON properties(projection_id, property, subject, value, q1, q2);
CREATE INDEX properties_moment ON properties(moment_id, projection_id);

CREATE TABLE extractor_costs (extractor_id TEXT PRIMARY KEY, mean_seconds REAL NOT NULL,
                              samples INTEGER NOT NULL);
"""
# Differences from design.md §4.5, decided here: entries gain origin, profile and
# session_id (a session entry needs them to open); the FTS triggers are part of
# the implementation; projections drop fields_json (the key is the JSON).
# Schema 2: entries get an INTEGER PRIMARY KEY ``rid`` as the FTS content rowid
# (the implicit rowid of a TEXT-keyed table may change on VACUUM, which would
# silently point the external-content index at the wrong entries).

_T = TypeVar("_T")

_ENTRY_COLUMNS = (
    "e.id, e.origin, e.path, e.profile, e.session_id, e.name, e.place, e.country, "
    "e.notes, e.kind, e.birth_local, e.file_mtime, e.file_size, e.unsaved_changes, "
    "e.moment_id, m.key, m.jd_ut, m.lat, m.lon, m.utc_offset"
)
_DISTINCT_COLUMNS = frozenset({"subject", "value", "q1", "q2"})


def store_path(*, writable: bool = False) -> Path:
    """``<data dir>/cache/.find_chart_store_<os>.sqlite`` (per-OS name: entries
    hold absolute paths).

    Readers (the default) find the data dir WITHOUT creating anything:
    ``resolve_settings_dir`` makes no folder, writes no probe file and no
    bootstrap pointer, so a query (find_chart, chart_index status/export, the
    export duplicate check) never creates or migrates user storage. Only the
    writer (``writable=True``, ``StoreWriter.open``) goes through
    ``get_user_data_dir``, which may create the folder."""
    from state.user_data import get_default_data_dir, get_user_data_dir

    if writable:
        data_dir = get_user_data_dir() or get_default_data_dir()
    else:
        from core.capabilities.settings_view import resolve_settings_dir

        data_dir = resolve_settings_dir() or get_default_data_dir()
    return (
        Path(data_dir)
        / "cache"
        / f".find_chart_store_{platform.system().lower()}.sqlite"
    )


@dataclass(frozen=True)
class RowConstraint:
    """One filter in store terms. ``None`` = unconstrained (any subject, value
    or qualifier); ``subjects`` is matched with ``IN``."""

    subjects: tuple[str, ...] | None
    property: str
    value: int | str | None
    q1: str | None = None
    q2: str | None = None


@dataclass(frozen=True)
class EntryRow:
    """An entry as stored, plus the profiles it is loaded in."""

    entry: Entry
    moment_id: MomentId
    loaded_in: tuple[str, ...]


@dataclass(frozen=True)
class CoverageCounts:
    in_scope: int
    computed: int  # ok at the current extractor version
    failed: int
    stale_app_versions: tuple[str, ...]  # stamps other than the running version
    stale: int = 0  # ok moments stamped with another app version


@dataclass(frozen=True)
class ComputationState:
    """A moment's computation at one extractor version (compute's plan)."""

    ok: bool
    app_version: str
    error: str | None = None  # the failure text of a failed computation


@dataclass(frozen=True)
class StoreStatus:
    path: Path
    entries: int
    moments: int
    unreadable: tuple[Unreadable, ...]


@dataclass(frozen=True)
class ImportReport:
    """Counts over the imported file's moments that have a computation."""

    moments_matched: int  # a chart of this store
    #: no chart here with these exact birth data (not synced yet, another
    #: library, or the same rounded moment with different exact inputs)
    moments_skipped: int
    taken: int  # computations copied: missing here, older version, or failed here
    kept: int  # computations this store already had as good


@dataclass(frozen=True)
class Computed:
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Failed:
    error: str  # "<ExceptionType>: <message>", or "contract: ..." (extractors.base)


Outcome = Computed | Failed


def export_store(dest: Path, path: Path | None = None) -> None:
    """A consistent, compacted copy of the store at ``dest`` (``VACUUM INTO``,
    safe while writers run), replacing ``dest``. Raises ``NoIndexError``, and
    ``BadStoreFileError`` when ``dest`` is the store itself."""
    path = path or store_path()
    if not path.is_file():
        raise NoIndexError("missing")
    if dest.exists() and dest.resolve() == path.resolve():
        raise BadStoreFileError("cannot export the chart index onto itself")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.name}.partial-{os.getpid()}")
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
    )
    try:
        if _schema_version(conn) != SCHEMA_VERSION:
            raise NoIndexError("schema_mismatch")
        conn.execute("VACUUM INTO ?", (str(partial),))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    os.replace(partial, dest)


def _bump_revision(conn: sqlite3.Connection, before: int) -> None:
    """Inside a write transaction that changed something: a new revision
    token (random, so a recreated store never repeats an old one)."""
    if conn.total_changes == before:
        return
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('revision', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (uuid.uuid4().hex,),
    )


class StoreReader:
    """Not thread-safe: one thread at a time (the handle may move between
    threads, as the compute worker's does)."""

    def __init__(
        self, path: Path, conn: sqlite3.Connection, busy_ms: int, query_only: bool
    ) -> None:
        self._path = path
        self._conn = conn
        self._busy_ms = busy_ms
        self._query_only = query_only
        self._atomic = False  # inside StoreWriter.atomically()
        self._in_snapshot = False  # a read-only context's snapshot

    @classmethod
    def open(cls, path: Path | None = None) -> StoreReader:
        """Raises ``NoIndexError`` (missing file or schema mismatch) and
        ``StoreBusyError`` while another connection holds a lock."""
        path = path or store_path()
        if not path.is_file():
            raise NoIndexError("missing")
        try:
            conn = _connect(path, READER_BUSY_TIMEOUT_MS, query_only=True)
        except sqlite3.OperationalError as exc:
            if _is_busy(exc):
                raise StoreBusyError(f"the chart index is locked: {exc}") from exc
            raise
        try:
            version = _schema_version(conn)
        except sqlite3.DatabaseError as exc:
            conn.close()
            if _is_busy(exc):  # contention, not damage (review r5 #3)
                raise StoreBusyError(f"the chart index is locked: {exc}") from exc
            raise NoIndexError("schema_mismatch") from exc  # not a database at all
        if version != SCHEMA_VERSION:
            conn.close()
            raise NoIndexError("schema_mismatch")
        return cls(path, conn, READER_BUSY_TIMEOUT_MS, query_only=True)

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        """A read-only handle used as a context is ONE snapshot (review
        r15, FIND-004 §4.1): every query inside it sees the same committed
        state, so a search never joins one entry with another birth's rows
        when a writer commits midway. Keep the block short."""
        if self._query_only:
            self._conn.execute("BEGIN")
            self._in_snapshot = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._in_snapshot:
            self._in_snapshot = False
            try:
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                pass
        self.close()

    @contextmanager
    def snapshot(self):
        """Every read inside the block sees ONE committed state (review r16):
        a planner's candidate, state and exact-moment reads never straddle
        another writer's commit; a search and its diagnosis, an Ask AI tool
        call and its name scrub (SPEC-FIND-006 §7) read one state. WAL
        readers never block a writer. Joins a snapshot or transaction already
        open; on a writer it takes no write lock (a deferred transaction).
        Never hold it across a compute, a child-process wait or a dialog."""
        if self._in_snapshot or self._atomic or self._conn.in_transaction:
            yield self
            return
        self._conn.execute("BEGIN")
        self._in_snapshot = True
        try:
            yield self
        finally:
            self._in_snapshot = False
            if self._conn.in_transaction:
                try:
                    self._conn.execute("COMMIT")
                except sqlite3.Error:
                    pass

    def revision(self) -> str:
        """A token every committed write changes (any writer: the app, the
        CLI, an import, a rebuild; review r16): a cache keyed on it never
        outlives a change made outside the panel. Empty for a store no write
        has changed since this version."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'revision'"
        ).fetchone()
        return "" if row is None else str(row[0])

    def _reopen(self) -> None:
        self._conn.close()
        self._conn = _connect(self._path, self._busy_ms, query_only=self._query_only)

    def generation(self) -> tuple[int, int, float]:
        """``(entries, highest rowid, latest updated_at)``: changes when an
        entry is added, removed or updated (a rename keeps its rowid but not
        its ``updated_at``), so a name scrub built at one generation knows
        when it is stale. Read only."""
        count, top, updated = self._conn.execute(
            "SELECT count(*), coalesce(max(rid), 0), coalesce(max(updated_at), 0) "
            "FROM entries"
        ).fetchone()
        return int(count), int(top), float(updated)

    def entry_names(self) -> tuple[str, ...]:
        """Every entry's name (the Ask AI library scrub). Read only."""
        return tuple(row[0] for row in self._conn.execute("SELECT name FROM entries"))

    def entry_places(self) -> tuple[str, ...]:
        """Every distinct birth place and country of the store (the problem
        report scrub, SPEC-AIR-001 §3.3). Read only."""
        out: set[str] = set()
        for place, country in self._conn.execute(
            "SELECT DISTINCT place, country FROM entries"
        ):
            for value in (place, country):
                if value and str(value).strip():
                    out.add(str(value).strip())
        return tuple(sorted(out))

    def entry_paths(self) -> tuple[str, ...]:
        """Every entry's chart file path (its stem names the person). Read only."""
        return tuple(
            str(row[0]) for row in self._conn.execute(
                "SELECT DISTINCT path FROM entries WHERE path IS NOT NULL AND path != ''"
            )
        )

    def entry_folders(self) -> tuple[str, ...]:
        """Every folder holding a chart file of the store (the Ask AI path
        scrub): each entry path's parent, distinct. Read only."""
        folders = {
            str(Path(row[0]).parent)
            for row in self._conn.execute(
                "SELECT DISTINCT path FROM entries WHERE path IS NOT NULL AND path != ''"
            )
        }
        return tuple(sorted(folders))

    # ------------------------------------------------------------- entries
    def candidates(
        self,
        text: str,
        *,
        paths_under: Sequence[str] | None,
        include_fileless: bool,
        loaded_only: bool,
        kinds: frozenset[str],
        paths_hidden: Sequence[str] = (),
        paths_forgetting: Sequence[str] = (),
        paths_retained: Sequence[str] = (),
    ) -> tuple[EntryRow, ...]:
        """FTS (``text`` as prefix terms; empty = every entry) ∩ scope ∩ kinds.
        ``paths_under`` None = no folder filter; file-less entries are kept
        only if ``include_fileless``. File-less means no path at all: a
        session entry that kept its ``chtk_path`` (stale, not scanned yet) is
        folder-filtered on it. ``paths_hidden``: entries under these folders
        are left out (an unticked folder under Sources All). ``paths_forgetting``:
        a FILE entry under these folders is left out unless it is loaded
        (``Scope.forgetting``) or under one of ``paths_retained``."""
        if not kinds:
            return ()
        clauses = ["e.kind IN (SELECT value FROM json_each(?))"]
        params: list[object] = [json.dumps(sorted(kinds))]
        match = _fts_query(text)
        if match:
            clauses.append(
                "e.rid IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)"
            )
            params.append(match)
        if paths_under is not None:
            under, under_params = _under("e.path", paths_under)
            params += under_params
            scope = f"(e.path IS NOT NULL AND {under})"
            if include_fileless:
                scope = f"({scope} OR e.path IS NULL)"
            clauses.append(scope)
        elif not include_fileless:
            clauses.append("e.path IS NOT NULL")
        if paths_hidden:
            hidden, hidden_params = _under("e.path", paths_hidden)
            clauses.append(f"(e.path IS NULL OR NOT {hidden})")
            params += hidden_params
        if paths_forgetting:
            going, going_params = _under("e.path", paths_forgetting)
            kept, kept_params = _under("e.path", paths_retained)
            clauses.append(
                f"NOT (e.origin = 'file' AND {going} AND NOT {kept} AND NOT EXISTS "
                "(SELECT 1 FROM entry_loaded l WHERE l.entry_id = e.id))"
            )
            params += going_params + kept_params
        if loaded_only:
            clauses.append(
                "(e.origin = 'session' OR EXISTS "
                "(SELECT 1 FROM entry_loaded l WHERE l.entry_id = e.id))"
            )
        sql = (
            f"SELECT {_ENTRY_COLUMNS} FROM entries e JOIN moments m ON m.id = e.moment_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY e.id"
        )

        def query() -> list[sqlite3.Row]:
            return self._conn.execute(sql, params).fetchall()

        rows = self._fts_retry(query) if match else query()
        loaded = self._loaded_in(row["id"] for row in rows)
        return tuple(_entry_row(row, loaded.get(row["id"], ())) for row in rows)

    def _fts_retry(self, query: Callable[[], _T]) -> _T:
        """An FTS MATCH on a connection that predates another writer's
        automerge can fail as "malformed"; a fresh connection reads it fine."""
        try:
            return query()
        except sqlite3.DatabaseError as exc:
            if "malformed" not in str(exc):
                raise
            enclosed = getattr(self._conn, "in_transaction", False)
            if self._in_snapshot or self._atomic or enclosed:
                # Never a new connection inside a snapshot or an enclosing
                # transaction (review r16, r17: a reopen would roll an
                # atomic block back and leave later writes autocommitted): the
                # whole read restarts on a fresh reader instead, as for a
                # busy store (the panel retries; a CLI reports busy).
                raise SnapshotRetry(
                    f"the chart index changed during the read: {exc}"
                ) from exc
            self._reopen()
            return query()

    def _loaded_in(self, entry_ids: Iterable[str]) -> dict[str, tuple[str, ...]]:
        profiles: dict[str, set[str]] = {}
        for entry_id, profile in self._conn.execute(
            "SELECT entry_id, profile FROM entry_loaded "
            "WHERE entry_id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(entry_ids)),),
        ):
            profiles.setdefault(entry_id, set()).add(profile)
        return {key: tuple(sorted(value)) for key, value in profiles.items()}

    def file_states(self) -> dict[str, FileState]:
        """Every known path, entries and unreadable alike (incremental scan)."""
        return {
            path: FileState(mtime, size)
            for path, mtime, size in self._conn.execute(
                "SELECT path, file_mtime, file_size FROM entries WHERE origin = 'file' "
                "UNION ALL SELECT path, mtime, size FROM unreadable "
                "WHERE mtime IS NOT NULL AND size IS NOT NULL"
            )
        }

    def file_moments(self) -> dict[str, MomentKey]:
        """Moment per indexed file path (session merge)."""
        return {
            path: MomentKey.decode(key)
            for path, key in self._conn.execute(
                "SELECT e.path, m.key FROM entries e JOIN moments m ON m.id = e.moment_id "
                "WHERE e.origin = 'file'"
            )
        }

    def library_entries(self) -> tuple[tuple, ...]:
        """``(path, name, birth_local, moment key, mtime, size, place, country)``
        of every file entry (Rate and Sort, SPEC-LIB-002 §4.3). Read only."""
        return tuple(self._conn.execute(
            "SELECT e.path, e.name, e.birth_local, m.key, e.file_mtime, e.file_size, "
            "e.place, e.country "
            "FROM entries e JOIN moments m ON m.id = e.moment_id WHERE e.origin = 'file'"
        ))

    def session_profiles(self) -> frozenset[str]:
        """Profiles with session entries or loaded rows (a sync clears the ones
        whose session is gone)."""
        return frozenset(
            profile
            for (profile,) in self._conn.execute(
                "SELECT profile FROM entries WHERE origin = 'session' "
                "UNION SELECT profile FROM entry_loaded"
            )
        )

    def status(self) -> StoreStatus:
        (entries,) = self._conn.execute("SELECT count(*) FROM entries").fetchone()
        (moments,) = self._conn.execute("SELECT count(*) FROM moments").fetchone()
        unreadable = tuple(
            Unreadable(path, error, mtime, size)
            for path, mtime, size, error in self._conn.execute(
                "SELECT path, mtime, size, error FROM unreadable ORDER BY path"
            )
        )
        return StoreStatus(self._path, entries, moments, unreadable)

    # ------------------------------------------------------------ properties
    def projection_id(self, projection: Projection) -> ProjectionId | None:
        """None when no compute ever started for it. A projection can exist
        with no ``ok`` row (every moment failed): ``any_computed``."""
        row = self._conn.execute(
            "SELECT id FROM projections WHERE extractor_id = ? AND key = ?",
            (projection.extractor_id, projection.key),
        ).fetchone()
        return None if row is None else ProjectionId(row[0])

    def matching(
        self,
        projection_id: ProjectionId,
        constraint: RowConstraint,
        among: frozenset[MomentId],
    ) -> frozenset[MomentId]:
        sql = (
            "SELECT DISTINCT moment_id FROM properties WHERE projection_id = ? "
            "AND property = ? AND moment_id IN (SELECT value FROM json_each(?))"
        )
        params: list[object] = [projection_id, constraint.property, _ids(among)]
        if constraint.subjects is not None:
            sql += " AND subject IN (SELECT value FROM json_each(?))"
            params.append(json.dumps(constraint.subjects))
        for column, wanted in (
            ("value", constraint.value),
            ("q1", constraint.q1),
            ("q2", constraint.q2),
        ):
            if wanted is not None:
                sql += f" AND {column} = ?"
                params.append(wanted)
        return frozenset(MomentId(mid) for (mid,) in self._conn.execute(sql, params))

    def computed(
        self,
        projection_id: ProjectionId,
        extractor_version: int,
        among: frozenset[MomentId],
    ) -> frozenset[MomentId]:
        """Moments with an ``ok`` computation at this version."""
        return frozenset(
            MomentId(mid)
            for (mid,) in self._conn.execute(
                "SELECT moment_id FROM computations WHERE projection_id = ? "
                "AND status = 'ok' AND extractor_version = ? "
                "AND moment_id IN (SELECT value FROM json_each(?))",
                (projection_id, extractor_version, _ids(among)),
            )
        )

    def any_computed(self, projection_id: ProjectionId, extractor_version: int) -> bool:
        """Whether any moment has an ``ok`` computation at this version."""
        return (
            self._conn.execute(
                "SELECT 1 FROM computations WHERE projection_id = ? "
                "AND status = 'ok' AND extractor_version = ? LIMIT 1",
                (projection_id, extractor_version),
            ).fetchone()
            is not None
        )

    def coverage(
        self,
        projection_id: ProjectionId | None,
        extractor_version: int,
        among: frozenset[MomentId],
        running_version: str,
    ) -> CoverageCounts:
        """A computation at another extractor version counts as missing, ok or
        failed (a version bump retries failures)."""
        if projection_id is None:
            return CoverageCounts(len(among), 0, 0, ())
        computed = failed = stale_count = 0
        stale: set[str] = set()
        for status, app_version, count in self._conn.execute(
            "SELECT status, app_version, count(*) FROM computations "
            "WHERE projection_id = ? AND extractor_version = ? "
            "AND moment_id IN (SELECT value FROM json_each(?)) "
            "GROUP BY status, app_version",
            (projection_id, extractor_version, _ids(among)),
        ):
            if status == "ok":
                computed += count
                if app_version != running_version:
                    stale.add(app_version)
                    stale_count += count
            else:
                failed += count
        return CoverageCounts(
            len(among), computed, failed, tuple(sorted(stale)), stale_count
        )

    def computed_elsewhere(
        self,
        extractor_id: str,
        extractor_version: int,
        among: frozenset[MomentId],
        exclude: ProjectionId | None,
    ) -> tuple[tuple[str, int], ...]:
        """``(projection key, moments computed ok)`` for every other projection
        of this extractor at this extractor version, over ``among``, most
        computed first (``coverage[].computed_elsewhere``, plan R10). Read
        only; failures and other extractor versions are not counted."""
        return tuple(
            (key, count)
            for key, count in self._conn.execute(
                "SELECT p.key, count(*) FROM computations c "
                "JOIN projections p ON p.id = c.projection_id "
                "WHERE p.extractor_id = ? AND c.extractor_version = ? "
                "AND c.status = 'ok' AND p.id IS NOT ? "
                "AND c.moment_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY p.key ORDER BY count(*) DESC, p.key",
                (extractor_id, extractor_version, exclude, _ids(among)),
            )
        )

    def states(
        self,
        projection_id: ProjectionId,
        extractor_version: int,
        among: frozenset[MomentId],
    ) -> dict[MomentId, ComputationState]:
        """Moments computed at this extractor version, ok or failed; a moment
        absent from the result is missing."""
        return {
            MomentId(mid): ComputationState(status == "ok", app_version, error)
            for mid, status, app_version, error in self._conn.execute(
                "SELECT moment_id, status, app_version, error FROM computations "
                "WHERE projection_id = ? AND extractor_version = ? "
                "AND moment_id IN (SELECT value FROM json_each(?))",
                (projection_id, extractor_version, _ids(among)),
            )
        }

    def moment_of(self, entry_id: str) -> MomentId | None:
        """The moment an entry points to now; None when it is gone."""
        row = self._conn.execute(
            "SELECT moment_id FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return None if row is None else MomentId(row[0])

    def moments(self, moment_ids: frozenset[MomentId]) -> dict[MomentId, Moment]:
        """The stored moments; one collected meanwhile is absent."""
        return {
            MomentId(mid): Moment(MomentKey.decode(key), jd_ut, lat, lon, offset)
            for mid, key, jd_ut, lat, lon, offset in self._conn.execute(
                "SELECT id, key, jd_ut, lat, lon, utc_offset FROM moments "
                "WHERE id IN (SELECT value FROM json_each(?))",
                (_ids(moment_ids),),
            )
        }

    def rows_for(
        self,
        projection_id: ProjectionId,
        moment_ids: frozenset[MomentId],
        subjects: tuple[str, ...],
        property_name: str,
        q1: str | None = None,
    ) -> dict[MomentId, dict[str, int | str]]:
        """Result columns (Asc/Sun/Moon D1 signs): moment -> subject -> value.
        ``q1`` narrows a qualified property to one row per subject (varga D1)."""
        sql = (
            "SELECT moment_id, subject, value FROM properties WHERE projection_id = ? "
            "AND property = ? AND subject IN (SELECT value FROM json_each(?)) "
            "AND moment_id IN (SELECT value FROM json_each(?))"
        )
        params: list[object] = [
            projection_id,
            property_name,
            json.dumps(subjects),
            _ids(moment_ids),
        ]
        if q1 is not None:
            sql += " AND q1 = ?"
            params.append(q1)
        result: dict[MomentId, dict[str, int | str]] = {}
        for mid, subject, value in self._conn.execute(sql, params):
            result.setdefault(MomentId(mid), {})[subject] = value
        return result

    def moment_rows(
        self,
        projection_id: ProjectionId,
        moment_ids: frozenset[MomentId],
        *,
        property_name: str | None = None,
        q1_values: tuple[str, ...] | None = None,
    ) -> dict[MomentId, tuple[Row, ...]]:
        """Every stored row of these moments at one projection (the Find Chart
        inspector and its extra result columns, SPEC-FIND-005)."""
        sql = (
            "SELECT moment_id, subject, property, value, q1, q2 FROM properties "
            "WHERE projection_id = ? AND moment_id IN (SELECT value FROM json_each(?)) "
        )
        params: list[object] = [projection_id, _ids(moment_ids)]
        if property_name is not None:
            sql += " AND property = ?"
            params.append(property_name)
        if q1_values is not None:
            sql += " AND q1 IN (SELECT value FROM json_each(?))"
            params.append(json.dumps(q1_values))
        result: dict[MomentId, list[Row]] = {}
        for mid, subject, prop, value, q1, q2 in self._conn.execute(sql + " ORDER BY rowid", params):
            result.setdefault(MomentId(mid), []).append(
                Row(subject, prop, value, q1, q2)
            )
        return {mid: tuple(rows) for mid, rows in result.items()}

    def distinct(
        self,
        projection_id: ProjectionId,
        property_name: str,
        column: str,
        **fixed: str | int | tuple[str, ...],
    ) -> tuple[str | int, ...]:
        """Cascading dropdowns: ``SELECT DISTINCT <column>`` (value, q1 or q2).
        ``fixed`` narrows on the other columns (subject, value, q1, q2); a
        tuple (a subject group's members) is matched with ``IN``."""
        unknown = ({column} | fixed.keys()) - _DISTINCT_COLUMNS
        if unknown:
            raise ValueError(
                f"distinct: unknown column(s) {sorted(unknown)}; "
                f"valid: {sorted(_DISTINCT_COLUMNS)}"
            )
        sql = (
            f"SELECT DISTINCT {column} FROM properties WHERE projection_id = ? "
            f"AND property = ? AND {column} IS NOT NULL"
        )
        params: list[object] = [projection_id, property_name]
        for name, value in sorted(fixed.items()):
            if isinstance(value, tuple):
                sql += f" AND {name} IN (SELECT value FROM json_each(?))"
                params.append(json.dumps(value))
            else:
                sql += f" AND {name} = ?"
                params.append(value)
        return tuple(
            value
            for (value,) in self._conn.execute(sql + f" ORDER BY {column}", params)
        )

    def mean_cost(self, extractor_id: str) -> float | None:
        row = self._conn.execute(
            "SELECT mean_seconds FROM extractor_costs WHERE extractor_id = ?",
            (extractor_id,),
        ).fetchone()
        return None if row is None else row[0]


class StoreWriter(StoreReader):
    @classmethod
    def open(cls, path: Path | None = None) -> StoreWriter:
        """Creates the store, or discards it on a schema mismatch. Raises
        ``StoreBusyError`` when another writer holds the lock throughout."""
        path = path or store_path(writable=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = _writer_connection(path)
        except sqlite3.DatabaseError as exc:
            if "not a database" not in str(exc):
                raise
            for suffix in ("", "-wal", "-shm"):
                Path(f"{path}{suffix}").unlink(missing_ok=True)
            conn = _writer_connection(path)
        writer = cls(path, conn, BUSY_TIMEOUT_MS, query_only=False)
        try:
            writer._write(_ensure_schema)
        except BaseException:
            writer.close()
            raise
        return writer

    @contextmanager
    def atomically(self):
        """Every write inside the block is ONE ``BEGIN IMMEDIATE`` transaction:
        all of it commits, or none (a Full Rebuild's discard and refill,
        review r8: a failure never leaves an emptied index). Busy at the
        start: ``StoreBusyError``; any error inside rolls everything back."""
        if self._atomic:
            yield self
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            before = self._conn.total_changes
        except sqlite3.OperationalError as exc:
            if _is_busy(exc):
                raise StoreBusyError(
                    f"the chart index stayed locked by another writer: {exc}"
                ) from exc
            raise
        self._atomic = True
        try:
            yield self
            _bump_revision(self._conn, before)
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        finally:
            self._atomic = False

    def _write(self, mutate: Callable[[sqlite3.Connection], _T]) -> _T:
        """``mutate`` in one ``BEGIN IMMEDIATE`` transaction, rolled back on any
        error. Busy after ``busy_timeout``: one retry, then ``StoreBusyError``.
        ``mutate`` must be safe to run twice (it is, being plain SQL over its
        arguments). Inside ``atomically()`` it joins that transaction."""
        if self._atomic:
            return mutate(self._conn)
        for attempt in range(2):
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                before = self._conn.total_changes
                result = mutate(self._conn)
                _bump_revision(self._conn, before)
                self._conn.execute("COMMIT")
                return result
            except BaseException as exc:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                if not _is_busy(exc):
                    raise
                if attempt == 1:
                    raise StoreBusyError(
                        f"the chart index stayed locked by another writer: {exc}"
                    ) from exc
        raise InvariantError("invariant: the retry loop returns or raises")

    # Entries. Each call is one transaction.
    def upsert_entries(self, entries: Sequence[Entry]) -> None:
        """Moves an entry to a new moment when its key changed."""

        def mutate(conn: sqlite3.Connection) -> None:
            for entry in entries:
                _upsert(conn, entry)

        self._write(mutate)

    def remove_entries(self, entry_ids: Sequence[EntryId]) -> None:
        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM entries WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(list(entry_ids)),),
            )

        self._write(mutate)

    def replace_session(
        self, profile: str, entries: Sequence[Entry], loaded: Sequence[Loaded]
    ) -> None:
        """A profile's session entries and loaded rows replace the previous ones;
        vanished session ids lose their rows. A loaded row whose file entry is
        gone (another writer forgot it meanwhile) is dropped."""
        for entry in entries:
            if not (
                isinstance(entry.origin, SessionOrigin)
                and entry.origin.profile == profile
            ):
                raise InvariantError(
                    f"invariant: replace_session({profile!r}) got {entry.entry_id!r}, "
                    "which is not a session entry of that profile"
                )
        for item in loaded:
            if item.profile != profile:
                raise InvariantError(
                    f"invariant: replace_session({profile!r}) got a loaded row of "
                    f"profile {item.profile!r}"
                )

        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM entries WHERE origin = 'session' AND profile = ? "
                "AND id NOT IN (SELECT value FROM json_each(?))",
                (profile, json.dumps([entry.entry_id for entry in entries])),
            )
            conn.execute("DELETE FROM entry_loaded WHERE profile = ?", (profile,))
            for entry in entries:
                _upsert(conn, entry)
            conn.executemany(
                "INSERT OR IGNORE INTO entry_loaded (entry_id, profile, session_id) "
                "SELECT ?1, ?2, ?3 WHERE EXISTS (SELECT 1 FROM entries WHERE id = ?1)",
                [(item.entry_id, item.profile, item.session_id) for item in loaded],
            )

        self._write(mutate)

    def record_unreadable(self, items: Sequence[Unreadable]) -> None:
        """File sources only (sessions are re-read on every sync and only
        reported). An unreadable file loses its entry."""

        def mutate(conn: sqlite3.Connection) -> None:
            for item in items:
                if item.source.startswith("session:"):
                    continue
                conn.execute(
                    "INSERT INTO unreadable (path, mtime, size, error) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, "
                    "size = excluded.size, error = excluded.error",
                    (item.source, item.mtime, item.size, item.error),
                )
                conn.execute(
                    "DELETE FROM entries WHERE origin = 'file' AND path = ?",
                    (item.source,),
                )

        self._write(mutate)

    def forget_paths(self, paths: Sequence[str]) -> None:
        """Files gone from disk: their entries and unreadable rows."""
        ids = json.dumps(list(paths))

        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM entries WHERE origin = 'file' "
                "AND path IN (SELECT value FROM json_each(?))",
                (ids,),
            )
            conn.execute(
                "DELETE FROM unreadable WHERE path IN (SELECT value FROM json_each(?))",
                (ids,),
            )

        self._write(mutate)

    def forget_outside(self, folders: Sequence[str]) -> int:
        """Files under none of ``folders`` (a folder taken off the list): their
        entries and unreadable rows; returns the entries removed. Session
        entries stay, whatever their path. Moments are left to
        ``collect_moments``."""
        under, params = _under("path", folders)

        def mutate(conn: sqlite3.Connection) -> int:
            removed = conn.execute(
                f"DELETE FROM entries WHERE origin = 'file' AND NOT {under}", params
            ).rowcount
            conn.execute(f"DELETE FROM unreadable WHERE NOT {under}", params)
            return removed

        return self._write(mutate)

    def collect_moments(self) -> int:
        """Delete moments no entry points to (and their rows); returns the count."""

        def mutate(conn: sqlite3.Connection) -> int:
            return conn.execute(
                "DELETE FROM moments WHERE id NOT IN (SELECT moment_id FROM entries)"
            ).rowcount

        return self._write(mutate)

    def discard(self) -> None:
        """Empty the store (Full Rebuild): every entry, row and measured cost.
        The sources are the truth; the next folder and session sync refill it."""
        self._write(_recreate)

    # Compute.
    def ensure_projection(self, projection: Projection) -> ProjectionId:
        def mutate(conn: sqlite3.Connection) -> ProjectionId:
            conn.execute(
                "INSERT INTO projections (extractor_id, key) VALUES (?, ?) "
                "ON CONFLICT(extractor_id, key) DO NOTHING",
                (projection.extractor_id, projection.key),
            )
            (pid,) = conn.execute(
                "SELECT id FROM projections WHERE extractor_id = ? AND key = ?",
                (projection.extractor_id, projection.key),
            ).fetchone()
            return ProjectionId(pid)

        return self._write(mutate)

    def write_batch(
        self,
        projection_id: ProjectionId,
        extractor_version: int,
        app_version: str,
        results: Sequence[tuple[MomentId, Outcome]],
        *,
        inputs: Mapping[MomentId, Moment] | None = None,
        projection: Projection | None = None,
    ) -> None:
        """One ``BEGIN IMMEDIATE`` transaction: each moment's old rows replaced by
        its outcome's, and its ``computations`` row. Raises ``StoreBusyError``.
        A moment collected meanwhile (its entries moved) is skipped.
        Identity (reviews r14, r15, FIND-004 §4.1): ``inputs`` are the exact
        moments the outcomes were computed for (key AND the stored jd_ut,
        lat, lon and offset: two moments can share a rounded key),
        ``projection`` the projection; checked inside the transaction, so a moment or projection id reused by
        another writer meanwhile (a Full Rebuild recreating the store) never
        receives another birth's rows: a mismatched moment is skipped, a
        mismatched projection skips the batch."""

        def mutate(conn: sqlite3.Connection) -> None:
            now = time.time()
            if projection is not None:
                found = conn.execute(
                    "SELECT 1 FROM projections WHERE id = ? AND extractor_id = ? AND key = ?",
                    (projection_id, projection.extractor_id, projection.key),
                ).fetchone()
                if found is None:
                    return
            for moment_id, outcome in results:
                row = conn.execute(
                    "SELECT key, jd_ut, lat, lon, utc_offset FROM moments WHERE id = ?",
                    (moment_id,),
                ).fetchone()
                if row is None:
                    continue
                if inputs is not None:
                    want = inputs.get(moment_id)
                    if want is None or tuple(row) != (
                        want.key.encode(), want.jd_ut, want.lat, want.lon,
                        want.utc_offset_hours,
                    ):
                        continue  # the id now names another moment
                conn.execute(
                    "DELETE FROM properties WHERE moment_id = ? AND projection_id = ?",
                    (moment_id, projection_id),
                )
                if isinstance(outcome, Computed):
                    conn.executemany(
                        "INSERT INTO properties "
                        "(moment_id, projection_id, subject, property, value, q1, q2) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                moment_id,
                                projection_id,
                                r.subject,
                                r.property,
                                r.value,
                                r.q1,
                                r.q2,
                            )
                            for r in outcome.rows
                        ],
                    )
                    status, error = "ok", None
                else:
                    status, error = "failed", outcome.error
                conn.execute(
                    "INSERT INTO computations (moment_id, projection_id, status, error, "
                    "extractor_version, app_version, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(moment_id, projection_id) DO UPDATE SET "
                    "status = excluded.status, error = excluded.error, "
                    "extractor_version = excluded.extractor_version, "
                    "app_version = excluded.app_version, computed_at = excluded.computed_at",
                    (
                        moment_id,
                        projection_id,
                        status,
                        error,
                        extractor_version,
                        app_version,
                        now,
                    ),
                )

        self._write(mutate)

    def import_computations(self, source: Path) -> ImportReport:
        """Another index's computed results (an ``export_store`` file, or the
        store of another installation) merged into this one's moments, matched
        by moment key and projection key; entries are not imported. A
        computation is taken when this store has none for that moment and
        projection, has one at an older extractor version, or failed where the
        file's is ok at the same version. Measured costs fill only extractors
        never measured here. One transaction. Raises ``BadStoreFileError``."""
        if not source.is_file():
            raise BadStoreFileError(f"no such file: {source}")
        if source.resolve() == self._path.resolve():
            raise BadStoreFileError("cannot import the chart index into itself")
        try:
            probe = sqlite3.connect(
                f"{source.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
            )
            try:
                version = _schema_version(probe)
            finally:
                probe.close()
        except sqlite3.DatabaseError as exc:
            raise BadStoreFileError(
                f"{source} is not a Find Chart index: {exc}"
            ) from exc
        if version != SCHEMA_VERSION:
            raise BadStoreFileError(
                f"{source} is a Find Chart index of schema {version}, this "
                f"version reads schema {SCHEMA_VERSION}"
            )

        def mutate(conn: sqlite3.Connection) -> ImportReport:
            conn.execute("DROP TABLE IF EXISTS temp.import_offer")
            # Every computation of the file on a moment this store has.
            conn.execute(
                "CREATE TEMP TABLE import_offer AS SELECT lm.id AS moment_id, "
                "sc.moment_id AS src_moment, sc.projection_id AS src_projection, "
                "sp.extractor_id, sp.key, sc.status, sc.error, "
                "sc.extractor_version, sc.app_version, sc.computed_at, "
                "NULL AS projection_id, 0 AS take "
                "FROM src.computations sc "
                "JOIN src.moments sm ON sm.id = sc.moment_id "
                "JOIN main.moments lm ON lm.key = sm.key "
                # The exact inputs too (review r16): one rounded key can
                # hold two births whose facts differ near a boundary.
                "AND lm.jd_ut = sm.jd_ut AND lm.lat = sm.lat "
                "AND lm.lon = sm.lon AND lm.utc_offset = sm.utc_offset "
                "JOIN src.projections sp ON sp.id = sc.projection_id"
            )
            conn.execute(
                "INSERT INTO projections (extractor_id, key) "
                "SELECT DISTINCT extractor_id, key FROM temp.import_offer WHERE true "
                "ON CONFLICT(extractor_id, key) DO NOTHING"
            )
            conn.execute(
                "UPDATE temp.import_offer SET projection_id = (SELECT p.id "
                "FROM projections p WHERE p.extractor_id = import_offer.extractor_id "
                "AND p.key = import_offer.key)"
            )
            conn.execute(
                "UPDATE temp.import_offer SET take = 1 WHERE NOT EXISTS ("
                "SELECT 1 FROM computations lc "
                "WHERE lc.moment_id = import_offer.moment_id "
                "AND lc.projection_id = import_offer.projection_id "
                "AND (lc.extractor_version > import_offer.extractor_version "
                "OR (lc.extractor_version = import_offer.extractor_version "
                "AND (lc.status = 'ok' OR import_offer.status = 'failed'))))"
            )
            conn.execute(
                "DELETE FROM properties WHERE (moment_id, projection_id) IN "
                "(SELECT moment_id, projection_id FROM temp.import_offer WHERE take)"
            )
            conn.execute(
                "INSERT INTO properties "
                "(moment_id, projection_id, subject, property, value, q1, q2) "
                "SELECT o.moment_id, o.projection_id, "
                "sp.subject, sp.property, sp.value, sp.q1, sp.q2 "
                "FROM temp.import_offer o JOIN src.properties sp "
                "ON sp.moment_id = o.src_moment AND sp.projection_id = o.src_projection "
                "WHERE o.take"
            )
            conn.execute(
                "INSERT INTO computations (moment_id, projection_id, status, error, "
                "extractor_version, app_version, computed_at) "
                "SELECT moment_id, projection_id, status, error, extractor_version, "
                "app_version, computed_at FROM temp.import_offer WHERE take "
                "ON CONFLICT(moment_id, projection_id) DO UPDATE SET "
                "status = excluded.status, error = excluded.error, "
                "extractor_version = excluded.extractor_version, "
                "app_version = excluded.app_version, computed_at = excluded.computed_at"
            )
            conn.execute(
                "INSERT OR IGNORE INTO extractor_costs "
                "SELECT extractor_id, mean_seconds, samples FROM src.extractor_costs"
            )
            taken, offered, matched = conn.execute(
                "SELECT coalesce(sum(take), 0), count(*), count(DISTINCT moment_id) "
                "FROM temp.import_offer"
            ).fetchone()
            (with_results,) = conn.execute(
                "SELECT count(DISTINCT moment_id) FROM src.computations"
            ).fetchone()
            conn.execute("DROP TABLE temp.import_offer")
            return ImportReport(matched, with_results - matched, taken, offered - taken)

        # ATTACH cannot run inside a transaction; the file is only read.
        self._conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        try:
            return self._write(mutate)
        finally:
            self._conn.execute("DETACH DATABASE src")

    def record_cost(
        self, extractor_id: str, seconds_per_moment: float, samples: int
    ) -> None:
        """Folds a measurement over ``samples`` moments into the running mean."""
        if samples <= 0:
            return

        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO extractor_costs (extractor_id, mean_seconds, samples) "
                "VALUES (?, ?, ?) ON CONFLICT(extractor_id) DO UPDATE SET "
                "mean_seconds = (mean_seconds * samples + excluded.mean_seconds * "
                "excluded.samples) / (samples + excluded.samples), "
                "samples = samples + excluded.samples",
                (extractor_id, seconds_per_moment, samples),
            )

        self._write(mutate)


# ------------------------------------------------------------------ helpers


def _connect(path: Path, busy_ms: int, *, query_only: bool) -> sqlite3.Connection:
    """Autocommit mode (``isolation_level=None``): transactions are explicit."""
    conn = sqlite3.connect(
        path, timeout=busy_ms / 1000, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    if query_only:
        conn.execute("PRAGMA query_only = ON")
    return conn


def _writer_connection(path: Path) -> sqlite3.Connection:
    conn = _connect(path, BUSY_TIMEOUT_MS, query_only=False)
    try:
        _set_wal(conn)
        conn.execute("PRAGMA synchronous = NORMAL")
    except BaseException:
        conn.close()
        raise
    return conn


def _set_wal(conn: sqlite3.Connection) -> None:
    """Switching a file to WAL while another connection holds a lock fails
    with SQLITE_BUSY at once, without the busy handler (two writers creating
    the store together). Retried here up to ``BUSY_TIMEOUT_MS``; once the file
    is WAL the pragma is a no-op."""
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
    while True:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc):
                raise
            if time.monotonic() >= deadline:
                raise StoreBusyError(
                    f"the chart index stayed locked by another writer: {exc}"
                ) from exc
            time.sleep(0.01)


def _schema_version(conn: sqlite3.Connection) -> int | None:
    """None when there is no ``meta`` table or no readable version."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    if row is None:
        return None
    try:
        return int(row[0])
    except ValueError:
        return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Inside the writer's transaction: re-checked there, so of two writers
    opening a stale store at once the second sees the first's fresh schema."""
    if _schema_version(conn) == SCHEMA_VERSION:
        return
    _recreate(conn)


def _recreate(conn: sqlite3.Connection) -> None:
    """Inside the writer's transaction: an empty store at ``SCHEMA_VERSION``."""
    _drop_everything(conn)
    for statement in _statements(SCHEMA_SQL):
        conn.execute(statement)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _drop_everything(conn: sqlite3.Connection) -> None:
    """Every trigger, view and table of an older (or newer) schema. Virtual
    tables first: dropping one drops its shadow tables."""
    conn.execute("PRAGMA defer_foreign_keys = ON")
    queries = (
        "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')",
        (
            "SELECT type, name FROM sqlite_master WHERE type = 'table' "
            "AND sql LIKE 'CREATE VIRTUAL TABLE%'"
        ),
        (
            "SELECT type, name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY rowid DESC"
        ),
    )
    for query in queries:
        for kind, name in conn.execute(query).fetchall():
            quoted = '"' + name.replace('"', '""') + '"'
            conn.execute(f"DROP {kind.upper()} IF EXISTS {quoted}")


def _statements(script: str) -> Iterator[str]:
    """``script`` split into complete statements (trigger bodies included).
    Not ``executescript``: it commits first, and the schema must be created
    inside the writer's transaction."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer.strip()
            buffer = ""
    if buffer.strip():
        raise InvariantError(f"invariant: SCHEMA_SQL ends mid-statement: {buffer!r}")


def _is_busy(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and (
        exc.sqlite_errorcode & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    )


def _ids(ids: frozenset[MomentId]) -> str:
    return json.dumps(sorted(ids))


def _under(column: str, folders: Sequence[str]) -> tuple[str, list[object]]:
    """``(<column> is one of folders or inside one)`` and its parameters;
    ``(0)`` for no folder. A prefix ends with the separator, so ``/x/charts``
    does not hold ``/x/charts-old``."""
    clauses: list[str] = []
    params: list[object] = []
    for folder in folders:
        folder = os.path.abspath(folder)
        prefix = folder if folder.endswith(os.sep) else folder + os.sep
        clauses.append(f"{column} = ? OR substr({column}, 1, ?) = ?")
        params += [folder, len(prefix), prefix]
    return f"({' OR '.join(clauses) or '0'})", params


def _fts_query(text: str) -> str:
    """Each whitespace-separated word as a quoted prefix term, ANDed; "" when
    there is none. Quoting keeps FTS operators and punctuation literal."""
    terms = []
    for word in text.split():
        word = word.replace('"', "")
        if word:
            terms.append(f'"{word}"*')
    return " ".join(terms)


def _upsert(conn: sqlite3.Connection, entry: Entry) -> None:
    moment = entry.moment
    key = moment.key.encode()
    # A moment's coordinates are the first stored for its key (sources.py).
    conn.execute(
        "INSERT INTO moments (key, jd_ut, lat, lon, utc_offset) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, moment.jd_ut, moment.lat, moment.lon, moment.utc_offset_hours),
    )
    (moment_id,) = conn.execute(
        "SELECT id FROM moments WHERE key = ?", (key,)
    ).fetchone()
    origin = entry.origin
    if isinstance(origin, FileOrigin):
        fields = ("file", None, None, origin.mtime, origin.size, False)
    else:
        fields = (
            "session",
            origin.profile,
            origin.session_id,
            None,
            None,
            origin.unsaved_changes,
        )
    kind, profile, session_id, mtime, size, unsaved = fields
    conn.execute(
        "INSERT INTO entries (id, moment_id, origin, path, profile, session_id, name, "
        "place, country, notes, kind, birth_local, file_mtime, file_size, "
        "unsaved_changes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET moment_id = excluded.moment_id, "
        "origin = excluded.origin, path = excluded.path, profile = excluded.profile, "
        "session_id = excluded.session_id, name = excluded.name, place = excluded.place, "
        "country = excluded.country, notes = excluded.notes, kind = excluded.kind, "
        "birth_local = excluded.birth_local, file_mtime = excluded.file_mtime, "
        "file_size = excluded.file_size, unsaved_changes = excluded.unsaved_changes, "
        "updated_at = excluded.updated_at",
        (
            entry.entry_id,
            moment_id,
            kind,
            entry.path,
            profile,
            session_id,
            entry.name,
            entry.place,
            entry.country,
            entry.notes,
            entry.kind.value,
            entry.birth_local,
            mtime,
            size,
            unsaved,
            time.time(),
        ),
    )
    if isinstance(origin, FileOrigin):
        conn.execute("DELETE FROM unreadable WHERE path = ?", (origin.path,))


def _entry_row(row: sqlite3.Row, loaded_in: tuple[str, ...]) -> EntryRow:
    origin: FileOrigin | SessionOrigin
    if row["origin"] == "file":
        origin = FileOrigin(row["path"], row["file_mtime"], row["file_size"])
    else:
        origin = SessionOrigin(
            row["profile"],
            row["session_id"],
            row["path"],
            bool(row["unsaved_changes"]),
        )
        loaded_in = tuple(sorted({*loaded_in, row["profile"]}))
    moment = Moment(
        MomentKey.decode(row["key"]),
        row["jd_ut"],
        row["lat"],
        row["lon"],
        row["utc_offset"],
    )
    entry = Entry(
        entry_id=EntryId(row["id"]),
        moment=moment,
        origin=origin,
        name=row["name"],
        place=row["place"],
        country=row["country"],
        notes=row["notes"],
        kind=EntryKind(row["kind"]),
        birth_local=row["birth_local"],
    )
    return EntryRow(entry, MomentId(row["moment_id"]), loaded_in)
