# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Entry sync: sources -> store (design.md §4.6, D4). Qt-free; shared by
``chart_index refresh``, REBUILD INDEX and the app's session sync.

``sync_folders`` is the folder half and needs consent (FIND-003 §3.1): only a
user action calls it. ``sync_sessions`` reads JSON only and runs whenever the
app's session changes. Each store call is its own transaction, so a sync cut
short leaves every row it wrote consistent; the next sync finishes the job.
Folders go first: the session merge reads the indexed files' moments.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.chart_search.errors import InvariantError, NoIndexError, Unreadable
from core.chart_search.sources import (
    CurrentSession,
    Entry,
    FileState,
    FolderScan,
    ScanCancelled,
    Loaded,
    SessionOrigin,
    read_file,
    read_sessions,
    scan_folders,
)
from core.chart_search.store import StoreReader, StoreWriter

#: Where the app keeps profiles when no user data folder is set (as
#: ``managers.session_manager``: the project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def profiles_dir() -> Path:
    """``<user data dir>/profiles``, as the app's session manager resolves it."""
    from state.user_data import get_user_data_dir

    return Path(get_user_data_dir() or _PROJECT_ROOT) / "profiles"


@dataclass(frozen=True)
class FolderSync:
    updated: int  # files added or re-parsed
    unchanged: int
    removed: int  # files gone from disk or under no folder of the list
    unreadable: tuple[Unreadable, ...]  # new or changed files that did not parse


@dataclass(frozen=True)
class SessionSync:
    profiles: tuple[str, ...]  # profiles whose rows were replaced
    entries: int  # session entries (no file, stale, unsaved)
    loaded: int  # session charts merged into file entries
    unreadable: tuple[Unreadable, ...]  # damaged sessions, unusable charts
    damaged: tuple[str, ...]  # profiles kept as they were (session.json unreadable)


def sync_folders(
    store: StoreWriter,
    folders: Sequence[Path],
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    discard: bool = False,
    committing: Callable[[], None] | None = None,
) -> FolderSync:
    """Incremental: unchanged mtime and size are skipped, changed files
    re-parsed, missing files forgotten. ``folders`` is the whole list: a file
    under none of them is forgotten too (``forget_folders``). Never raises for
    one file. ``discard`` (Full Rebuild) empties the store after the scan, so
    a cancelled scan (``ScanCancelled``, raised before any write) keeps the
    store whole. ``progress`` and ``cancelled``: ``scan_folders``;
    ``cancelled`` is checked once more after the scan, then ``committing()``
    marks the commit point (it may raise ``ScanCancelled`` itself): from
    there nothing cancels the writes. The panel's worker opens no writer
    before its commit point (``scan_for_sync`` then ``commit_scan``)."""
    known = {} if discard else store.file_states()
    scan = scan_for_sync(folders, known, progress=progress, cancelled=cancelled)
    if committing is not None:
        committing()
    return commit_scan(store, scan, folders, discard=discard)


def known_file_states(path: Path | None = None) -> dict[str, FileState]:
    """The indexed files' ``(mtime, size)``, read only: ``{}`` when there is
    no store or an incompatible one (the scan then reads every file). Opens
    no writer, so it creates and replaces nothing."""
    try:
        with StoreReader.open(path) as reader:
            return reader.file_states()
    except NoIndexError:
        return {}


def scan_for_sync(
    folders: Sequence[Path],
    known: dict[str, FileState],
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> FolderScan:
    """The scan half of ``sync_folders``: writes nothing; ``cancelled`` is
    checked once more after the last file (``ScanCancelled``)."""
    scan = scan_folders(folders, known, progress=progress, cancelled=cancelled)
    if cancelled is not None and cancelled():
        raise ScanCancelled()
    return scan


def commit_scan(
    store: StoreWriter,
    scan: FolderScan,
    folders: Sequence[Path],
    *,
    discard: bool = False,
) -> FolderSync:
    """The write half of ``sync_folders``, after the commit point: one
    transaction, so a Full Rebuild's discard and refill land together or
    not at all (review r8: a failure keeps the previous index)."""
    with store.atomically():
        if discard:
            store.discard()
        store.upsert_entries(scan.entries)
        store.record_unreadable(scan.unreadable)
        store.forget_paths(scan.removed)
        outside = forget_folders(store, folders)
    return FolderSync(
        len(scan.entries),
        len(scan.unchanged),
        len(scan.removed) + outside,
        scan.unreadable,
    )


def forget_folders(store: StoreWriter, folders: Sequence[Path]) -> int:
    """The folder list is now ``folders``: files under none of them leave the
    index (varuna/43). No scan, so no consent needed (FIND-003 §3.4 is about
    reading folders). A loaded chart among them becomes a session entry at
    the next session sync. Returns the entries removed."""
    return store.forget_outside([str(folder) for folder in folders])


def sync_file(store: StoreWriter, path: Path) -> Entry | Unreadable:
    """One file the app itself wrote (FIND-003 §3.5): its entry, or its
    unreadable row. Computing the new moment is the caller's business."""
    item = read_file(path)
    if isinstance(item, Entry):
        store.upsert_entries((item,))
    else:
        store.record_unreadable((item,))
    return item


def sync_sessions(
    store: StoreWriter, profiles_dir: Path, current: CurrentSession | None = None
) -> SessionSync:
    """Every profile's session replaces its rows; a profile whose session is
    gone loses them; a damaged ``session.json`` keeps them."""
    scan = read_sessions(profiles_dir, current, store.file_moments())
    entries: dict[str, list[Entry]] = defaultdict(list)
    for entry in scan.entries:
        if not isinstance(entry.origin, SessionOrigin):
            raise InvariantError(
                f"invariant: read_sessions yields session entries, got {entry.entry_id!r}"
            )
        entries[entry.origin.profile].append(entry)
    loaded: dict[str, list[Loaded]] = defaultdict(list)
    for item in scan.loaded:
        loaded[item.profile].append(item)
    profiles = sorted(
        (store.session_profiles() | entries.keys() | loaded.keys())
        - frozenset(scan.damaged)
    )
    for profile in profiles:
        store.replace_session(
            profile, entries.get(profile, ()), loaded.get(profile, ())
        )
    return SessionSync(
        tuple(profiles),
        len(scan.entries),
        len(scan.loaded),
        scan.unreadable,
        scan.damaged,
    )
