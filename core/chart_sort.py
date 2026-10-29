# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sort with AI's file mover (SPEC-FIND-005 §4.9) and Rate and Sort's
filing (SPEC-LIB-002 §4.8): file the charts Search Web downloaded into
``celebrity_unsorted`` into the chart folder's subfolders. Qt-free, no AI.

Three steps, so nothing moves unseen (INV-9):

1. a proposal: ``core.chart_sort_ai.propose`` asks the AI (Pro and up), or
   ``proposal_from_ratings`` builds one from the user's ratings (every
   edition). Nothing is written.
2. ``apply``: the user's confirmed moves, each revalidated (allowed folder,
   source unchanged since the preview, destination free). The intent log is
   written before the first move (a log that cannot be written stops the
   sort) and each move is journaled when done.
3. ``undo``: move back what the last applied sort moved and is unchanged.

Safety rules kept from the panel's first version: a folder name the AI gives
must be an existing subfolder or one of ``SAFE_FOLDERS`` (anything else
becomes Unclassified), the destination must resolve inside the chart folder,
and an existing file is never overwritten.

Lite ships this module and not ``chart_sort_ai`` (SPEC-EDN-002 INV-2).
The moved charts wait for REBUILD INDEX (SPEC-FIND-003 §3.5).
"""


from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

UNSORTED_FOLDER = "celebrity_unsorted"
LOG_NAME = "sort_log.json"
#: The notice shows from this many waiting charts.
SORT_THRESHOLD = 5
#: Folders the AI may use besides the existing subfolders.
SAFE_FOLDERS = ("Personal", "Unclassified", "Miscellaneous")
PERSONAL = "Personal"
UNCLASSIFIED = "Unclassified"
CHART_SUFFIXES = (".chtk", ".toml")


#: Proposal file format (``proposal_to_json``).
PROPOSAL_VERSION = 2

#: ``SortError.kind`` values; the panel maps each to its own neutral text.
NO_KEY, NO_CHARTS, NETWORK, BAD_ANSWER, LOG, UNDO_NONE, BAD_PROPOSAL, BUSY = (
    "no_key",
    "no_charts",
    "network",
    "bad_answer",
    "log",
    "undo_none",
    "bad_proposal",
    "busy",
)

LOCK_NAME = ".sort.lock"
CANCELLED = "stopped before this chart (cancelled)"


class SortError(Exception):
    """A sort step that cannot go on. ``kind`` is one of the kinds above;
    the message never names the AI vendor (INV-7); ``detail`` keeps the
    underlying error for logs."""

    def __init__(self, message: str, kind: str = BAD_ANSWER, detail: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class ChartFile:
    filename: str
    name: str
    path: str


#: (size, sha256 hex): what a file was when the user saw it in the preview.
Fingerprint = tuple[int, str]


@dataclass(frozen=True)
class Move:
    """One proposed move. ``filename`` is its id (unique in the unsorted
    folder). ``flag`` is ``"personal"``, ``"unclassified"`` or ``""``;
    ``reason`` is the AI's own words; ``fingerprint`` the source when
    proposed."""

    filename: str
    name: str
    folder: str
    reason: str = ""
    flag: str = ""
    fingerprint: Fingerprint | None = None


@dataclass(frozen=True)
class Proposal:
    unsorted_dir: str
    database: str
    folders: tuple[str, ...]  # existing subfolders, then SAFE_FOLDERS
    moves: tuple[Move, ...]
    #: Waiting charts the AI gave no folder for (they stay where they are).
    left: tuple[str, ...] = ()


@dataclass(frozen=True)
class MoveResult:
    filename: str
    name: str
    folder: str
    moved: bool
    error: str = ""


@dataclass(frozen=True)
class SortReport:
    results: tuple[MoveResult, ...]
    log_path: str
    #: Private claims recovery could not give back (their name was taken):
    #: kept, named here (spec 4.9).
    stuck: tuple[str, ...] = ()
    #: This sort's journal entry ("id"): Undo of this result names it, so a
    #: newer sort is never undone in its place (round 9).
    entry_id: str = ""

    @property
    def moved(self) -> int:
        return sum(1 for r in self.results if r.moved)

    @property
    def failed(self) -> int:
        return len(self.results) - self.moved


@dataclass(frozen=True)
class UndoReport:
    restored: int
    skipped: tuple[tuple[str, str], ...]  # (filename, reason)
    stuck: tuple[str, ...] = ()  # as SortReport.stuck


def fingerprint(path: Path) -> Fingerprint:
    data = path.read_bytes()
    return (len(data), hashlib.sha256(data).hexdigest())


# ------------------------------------------------------------------ folders


def unsorted_dir(database: str | Path) -> Path:
    """Where Search Web saves new charts: ``<first chart folder>/celebrity_unsorted``."""
    return Path(database) / UNSORTED_FOLDER


def _chart_paths(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in folder.iterdir()
        # A symlink is never a chart to sort (round 10: moving an alias
        # renames its target, an unselected file).
        if not p.is_symlink()
        and p.is_file()
        and p.suffix.lower() in CHART_SUFFIXES
        and not claimed_name(p)
    )


def count_unsorted(folder: str | Path) -> int:
    """Charts waiting in ``folder`` (.chtk and .toml); 0 when it is missing."""
    try:
        return len(_chart_paths(Path(folder)))
    except OSError:
        return 0


def chart_name(path: Path) -> str:
    """A chart file's person name: CHTK line 1 (UTF-16-LE), TOML ``name``;
    the file stem when unreadable. Never writes the file."""
    try:
        if path.suffix.lower() == ".toml":
            from core.toml_chart import TOMLChartReader

            raw = TOMLChartReader().read_toml_file(str(path), canonicalize=False)
            return (raw.get("name") or "").strip() or path.stem
        content = path.read_bytes().decode("utf-16-le", errors="ignore")
        return content.split("\n")[0].strip().strip("﻿") or path.stem
    except Exception:
        return path.stem


def chart_files(folder: str | Path) -> tuple[ChartFile, ...]:
    return tuple(
        ChartFile(p.name, chart_name(p), str(p)) for p in _chart_paths(Path(folder))
    )


def categories(database: str | Path) -> tuple[str, ...]:
    """The chart folder's subfolders, the unsorted folder left out."""
    root = Path(database)
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            d.name
            for d in root.iterdir()
            if d.is_dir() and d.name != UNSORTED_FOLDER and not d.name.startswith(".")
        )
    )


def flag_for(folder: str) -> str:
    if folder == PERSONAL:
        return "personal"
    if folder == UNCLASSIFIED:
        return "unclassified"
    return ""


def _fingerprint_or_none(path: Path) -> Fingerprint | None:
    try:
        return fingerprint(path)
    except OSError:
        return None


#: Rate and Sort's filing folders (SPEC-LIB-002 D-10), created on first use.
RATED_FOLDERS = ("Private", "Public", "Research")


def proposal_from_ratings(
    database: str | Path, moves: Sequence[tuple[str, str]]
) -> Proposal:
    """A version-2 proposal built locally from rated charts (SPEC-LIB-002
    §4.8): ``moves`` are ``(file name in the unsorted folder, folder)``.
    No network; ``apply`` and ``undo`` then work as for an AI proposal.
    A file not directly in the unsorted folder cannot be proposed."""
    folder = unsorted_dir(database)
    existing = categories(database)
    folders = RATED_FOLDERS + tuple(
        f for f in existing + SAFE_FOLDERS if f not in RATED_FOLDERS
    )
    charts = {c.filename: c for c in chart_files(folder)}
    out = []
    for filename, target in moves:
        chart = charts.get(filename)
        if chart is None:
            raise SortError(f"{filename!r} is not in the unsorted folder.", BAD_PROPOSAL)
        if target not in folders:
            raise SortError(f"the folder {target!r} is not one of the allowed folders", BAD_PROPOSAL)
        out.append(Move(filename, chart.name, target, f"rated: {target}", flag_for(target),
                        _fingerprint_or_none(Path(chart.path))))
    left = tuple(name for name in charts if name not in {m.filename for m in out})
    return Proposal(str(folder), str(database), folders, tuple(out), left)


# -------------------------------------------------------------------- apply
#
# sort_log.json is a list of sorts. Each sort: timestamp, "moves" (the intent:
# every planned move with source, destination and fingerprint, written before
# the first move) and per move "moved" (set and written right after it
# moved). A crash between a move and its journal write is reconciled from the
# files (``_reconcile``). Every write is atomic (temp file, then replace).


def _read_log(path: Path) -> list:
    """The journal; ``[]`` only when it does not exist. An unreadable,
    malformed or wrongly shaped journal raises ``SortError(kind=LOG)``
    before anything moves: it may hold the only undo history, so it is never
    replaced."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SortError(
            "The sort log cannot be read, so nothing was moved. Check "
            f"{path.name} in the unsorted folder.",
            LOG,
            str(exc),
        ) from exc
    if not isinstance(data, list) or not all(_valid_entry(e) for e in data):
        raise SortError(
            f"The sort log has an unexpected form, so nothing was moved. Check {path.name}.",
            LOG,
        )
    return data


def _valid_entry(entry: object) -> bool:
    """A sort of this format (``moves``), or a sort of the format before it
    (``assignments`` only: kept as history, never undoable)."""
    if not isinstance(entry, dict):
        return False
    if "moves" not in entry:
        return isinstance(entry.get("assignments"), list)
    moves = entry["moves"]
    if not isinstance(moves, list) or not isinstance(entry.get("undone", False), bool):
        return False
    return all(_valid_move(m) for m in moves)


def _valid_move(move: object) -> bool:
    if not isinstance(move, dict):
        return False
    for key in ("filename", "source", "destination"):
        if not isinstance(move.get(key), str) or not move[key]:
            return False
    fp = move.get("fingerprint")
    if not (
        isinstance(fp, list)
        and len(fp) == 2
        and isinstance(fp[0], int)
        and not isinstance(fp[0], bool)
        and isinstance(fp[1], str)
        and len(fp[1]) == 64
    ):
        return False
    for key in ("claim", "incoming", "undo_claim", "undo_incoming"):
        if move.get(key) is not None and not isinstance(move[key], str):
            return False
    for key in ("incoming_id", "undo_incoming_id"):
        ident = move.get(key)
        if ident is not None and not (
            isinstance(ident, list)
            and len(ident) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in ident)
        ):
            return False
    for key in ("phase", "undo_phase"):
        if move.get(key) not in (None, PUBLISHING, PUBLISHED):
            return False
    return isinstance(move.get("moved", False), bool) and isinstance(
        move.get("restored", False), bool
    )


@contextmanager
def _locked(folder: Path):
    """One apply or undo at a time per unsorted folder (panel and CLI alike),
    from the journal read to its last write: an OS lock on ``.sort.lock``
    (``flock`` / ``msvcrt.locking``), held for the whole operation and
    released by the OS if the process dies. The file is never deleted, so
    no takeover protocol is needed. A second operation gets
    ``SortError(kind=BUSY)`` and moves nothing."""
    lock = folder / LOCK_NAME
    try:
        handle = open(lock, "a+b")  # noqa: SIM115 - held for the operation
    except OSError as exc:
        raise SortError("The sort log could not be written.", LOG, str(exc)) from exc
    try:
        try:
            _os_lock(handle)
        except OSError:
            raise SortError("Another sort is running, try again shortly.", BUSY) from None
        try:
            yield
        finally:
            _os_unlock(handle)
    finally:
        handle.close()


def _os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass  # closing the handle releases it anyway


def _write_log(path: Path, log: list) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(log, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise SortError(
            "The sort log could not be written, nothing more was moved.", LOG, str(exc)
        ) from exc


def _destination(database: Path, folder: str, filename: str) -> Path:
    root = database.resolve()
    target_dir = (database / folder).resolve()
    if not target_dir.is_relative_to(root) or target_dir == root:
        raise SortError(f"Folder {folder!r} is outside the chart folder.", BAD_PROPOSAL)
    return target_dir / filename


CLAIM_PREFIX = ".sort-claim-"
INCOMING_PREFIX = ".sort-incoming-"
PROBE_PREFIX = ".sort-probe-"
_PRIVATE = (CLAIM_PREFIX, INCOMING_PREFIX, PROBE_PREFIX)
#: Journal phases of a copy across file systems, written by versions before
#: review r8 (which refuse such moves); still read so recovery can finish
#: an interrupted one: identity journaled, then the no-replace rename
#: (``publishing``), then done (``published``).
PUBLISHING = "publishing"
PUBLISHED = "published"
NO_SAFE_RENAME = (
    "this file system cannot move a file without a risk of overwriting "
    "another, so nothing was moved"
)
#: A move across drives is refused (review r8): a copy then a delete cannot
#: prove the copy survived a writer, so the chart stays and the user moves it.
CROSS_DEVICE = (
    "that folder is on another drive, so nothing was moved; move this chart "
    "by hand"
)


def _private(prefix: str, path: Path) -> Path:
    return path.with_name(f"{prefix}{uuid.uuid4().hex[:12]}-{path.name}")


def claimed_name(path: Path) -> str | None:
    """The original file name a private sort file (a claim, or a copy on
    its way in) stands for, else None."""
    name = path.name
    for prefix in _PRIVATE:
        if name.startswith(prefix):
            tag, sep, original = name[len(prefix):].partition("-")
            if sep and len(tag) == 12 and original:
                return original
    return None


_RENAME_NOREPLACE = 1  # Linux renameat2 flag
_RENAME_EXCL = 0x4  # macOS renamex_np flag
_AT_FDCWD = -100


def _libc():
    import ctypes

    return ctypes, ctypes.CDLL(None, use_errno=True)


class NoAtomicRename(OSError):
    """The file system offers no atomic no-replace rename."""


def rename_noreplace(src: Path, dst: Path) -> None:
    """Atomically rename ``src`` to ``dst``, failing with ``FileExistsError``
    when ``dst`` exists (never replacing it). Windows' rename never
    replaces; Linux uses ``renameat2(RENAME_NOREPLACE)``, macOS
    ``renamex_np(RENAME_EXCL)``. Anywhere else, or on a file system without
    the flag, it raises ``NoAtomicRename``: a hard link then an unlink is
    not atomic (review r7 #1), so the sort fails closed instead. Raises
    ``OSError(EXDEV)`` across file systems (callers copy then)."""
    if os.name == "nt":
        os.rename(src, dst)
        return
    import errno

    try:
        ctypes, libc = _libc()
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            rc = libc.renameat2(
                _AT_FDCWD, os.fsencode(src), _AT_FDCWD, os.fsencode(dst), _RENAME_NOREPLACE
            )
        elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
            rc = libc.renamex_np(os.fsencode(src), os.fsencode(dst), _RENAME_EXCL)
        else:
            rc = None
    except OSError:
        rc = None
    if rc == 0:
        return
    if rc is None:
        raise NoAtomicRename(errno.ENOTSUP, "no atomic no-replace rename", str(src))
    err = ctypes.get_errno()
    if err == errno.EEXIST:
        raise FileExistsError(err, os.strerror(err), str(dst))
    if err in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
        raise NoAtomicRename(err, os.strerror(err), str(src))
    raise OSError(err, os.strerror(err), str(src))


#: st_dev -> whether that file system renames without replacing.
_NOREPLACE: dict[int, bool] = {}


def supports_noreplace(folder: Path) -> bool:
    """Whether ``folder``'s file system has an atomic no-replace rename,
    probed once per file system with two private files of this call's
    own. A sort checks both folders before it claims anything."""
    if os.name == "nt":
        return True
    try:
        dev = os.stat(folder).st_dev
    except OSError:
        return False
    if dev in _NOREPLACE:
        return _NOREPLACE[dev]
    # The probe files live in a directory this call created exclusively
    # (round 10: cleanup must never reach a file another writer owns).
    try:
        box = Path(tempfile.mkdtemp(prefix=PROBE_PREFIX, dir=folder))
    except OSError:
        return False  # not cached: a full disk, say
    first, second = box / "a", box / "b"
    mine: list[Path] = []  # only what this call created or renamed itself
    try:
        with open(first, "xb"):
            pass
        mine.append(first)
        try:
            rename_noreplace(first, second)
            mine[:] = [second]
            ok = True
        except NoAtomicRename:
            ok = False
    except OSError:
        return False
    finally:
        for probe in mine:
            probe.unlink(missing_ok=True)
        try:
            box.rmdir()
        except OSError:
            pass  # another file appeared in the private directory: it stays
    _NOREPLACE[dev] = ok
    return ok


def _identity(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_dev, st.st_ino


def _move_no_replace(
    source: Path, dest: Path, expected: Sequence | None, note: Callable[..., None]
) -> None:
    """Move ``source`` to ``dest`` without ever replacing or deleting a file
    this call did not create, and only with the previewed bytes (INV-9,
    reviews r4 to r8). ``note(field, value, write=True)`` journals the
    private claim name BEFORE it exists, so a crash is recovered from the
    journal (``_recover``), never guessed from the disk.

    1. Claim: ``source`` is renamed to a private ``.sort-claim-*`` name in
       its folder (journaled first). The public name is then free: a file
       saved there meanwhile is another writer's and is never touched. The
       claim owns the pathname, not the content: a writer holding the file
       open can still change it, so the bytes are checked again after the
       rename.
    2. The claim is checked against ``expected``.
    The claim rename itself is no-replace too: a file already at the
       private name (round 9 #1) refuses the move and stays.
    3. Publish: an atomic no-replace rename to ``dest``. A file at ``dest``
       fails the move; nothing is overwritten.
    4. The bytes at ``dest`` are checked again; changed meanwhile, the file
       goes back (if ``dest`` still is this file) and the move fails.
    Only renames within one file system: a ``dest`` on another drive is
    refused before anything is claimed (review r8: a copy then a delete
    cannot prove the copy survived a writer), and so is a file system
    without an atomic no-replace rename (r7 #1).
    On any refusal the claim gets ``source`` back by a no-replace rename;
    if a newer file took that name, the claim stays (journaled) and the
    error names it."""
    dest.parent.mkdir(exist_ok=True)
    if os.stat(source.parent).st_dev != os.stat(dest.parent).st_dev:
        raise SortError(CROSS_DEVICE, BAD_PROPOSAL)
    if not (supports_noreplace(source.parent) and supports_noreplace(dest.parent)):
        raise SortError(NO_SAFE_RENAME, BAD_PROPOSAL)
    claim = _private(CLAIM_PREFIX, source)
    note("claim", str(claim))
    try:
        # No-replace even for a fresh private name (round 9 #1): a file
        # already at that name (planted after the journal named it) stays.
        rename_noreplace(source, claim)
    except FileNotFoundError:
        note("claim", None)
        raise SortError("it is no longer where the preview saw it", BAD_PROPOSAL) from None
    except FileExistsError:
        note("claim", None)
        raise SortError(
            "a file already has the sort's private name, so nothing was moved",
            BAD_PROPOSAL,
        ) from None
    try:
        if claim.is_symlink():  # replaced by a link after the check
            raise SortError("it is a link, not a chart file", BAD_PROPOSAL)
        if expected is not None and fingerprint(claim) != tuple(expected):
            raise SortError("the file changed since the preview", BAD_PROPOSAL)
        mine = _identity(claim)
        try:
            rename_noreplace(claim, dest)
        except FileExistsError:
            raise SortError(
                "a file with this name is already in that folder", BAD_PROPOSAL
            ) from None
        except OSError as exc:
            if exc.errno == errno.EXDEV:  # a mount point below the check
                raise SortError(CROSS_DEVICE, BAD_PROPOSAL) from None
            raise
        # Published by rename: the claim name is gone, the file is ``dest``.
        if expected is not None and fingerprint(dest) != tuple(expected):
            if _identity(dest) == mine:
                rename_noreplace(dest, claim)  # take it back to the claim
            else:  # pragma: no cover - a replacement in a microsecond window
                note("claim", None)
                raise SortError("the file changed during the move", BAD_PROPOSAL)
            raise SortError("the file changed during the move", BAD_PROPOSAL)
        note("claim", None, write=False)
    except BaseException as exc:
        if claim.exists() and not _restore(claim, source):
            raise SortError(
                f"{exc} (a newer file now has its name; it was kept as {claim.name})",
                BAD_PROPOSAL,
            ) from exc
        if not claim.exists():
            note("claim", None)
        raise


def _restore(claim: Path, original: Path) -> bool:
    """Give the claimed file its original name back, never replacing a file
    that now has it. False (the claim stays) when the name is taken or the
    file system offers no safe no-replace rename."""
    try:
        rename_noreplace(claim, original)
    except OSError:
        return False
    return True


#: Journal fields of a move's private names, per direction: (claim field,
#: the name the claim stands for, the name it goes to, incoming field, its
#: identity field, phase field).
_DIRECTIONS = (
    ("claim", "source", "destination", "incoming", "incoming_id", "phase"),
    ("undo_claim", "destination", "source", "undo_incoming", "undo_incoming_id",
     "undo_phase"),
)


def _check_private_paths(log: list, folder: Path) -> None:
    """Every move record must stay inside the sort folders: the source in
    this unsorted folder, the destination in the recorded subfolder of its
    chart folder (symlinks resolved), one file name for both; every private
    name a record holds must be this move's own (a claim beside the name it
    stands for, a copy beside where it goes, each with its prefix and that
    file name). Checked for every record, done or pending, so neither
    recovery nor Undo moves a file the user never saw (reviews r7 #4, r8
    #2). A log that fails is refused whole before any file is touched.
    Entries of the older format (``assignments`` only) are inert history."""
    unsorted = folder.resolve()
    root = unsorted.parent

    def own(path: str, prefix: str, beside: Path) -> bool:
        p = Path(path)
        return (
            p.name.startswith(prefix)
            and p.parent.resolve() == beside.parent.resolve()
            and claimed_name(p) == beside.name
        )

    def bound(record: dict) -> bool:
        source, dest = Path(record["source"]), Path(record["destination"])
        target_dir = dest.parent.resolve()
        folder_name = record.get("folder")
        return (
            source.parent.resolve() == unsorted
            and source.name == dest.name == record["filename"]
            and isinstance(folder_name, str)
            and bool(folder_name)
            and target_dir == (root / folder_name).resolve()
            and target_dir.is_relative_to(root)
            and target_dir not in (root, unsorted)
            and (not dest.is_symlink())
            and (not source.is_symlink())
        )

    for entry in log:
        if not isinstance(entry, dict):
            continue
        for record in entry.get("moves", []):
            ok = bound(record)
            for claim_key, origin_key, target_key, incoming_key, _i, _p in _DIRECTIONS:
                origin, target = Path(record[origin_key]), Path(record[target_key])
                if record.get(claim_key):
                    ok = ok and own(record[claim_key], CLAIM_PREFIX, origin)
                if record.get(incoming_key):
                    ok = ok and own(record[incoming_key], INCOMING_PREFIX, target)
            if not ok:
                raise SortError(
                    "The sort log names files outside the sort folders, so nothing "
                    "was moved. Check it in the unsorted folder.",
                    LOG,
                )


def _same(path: Path, ident) -> bool:
    try:
        return ident is not None and _identity(path) == tuple(ident)
    except OSError:
        return False


def _recover(log: list, log_path: Path) -> list[Path]:
    """Finish what a crash interrupted, from the journal only (under the
    operation lock, after the journal and its private names were validated).
    Recovery NEVER deletes a claim and never removes a published file
    (round 9: a writer holding the file open can change it after any check,
    so no check makes a deletion safe). Per journaled move and direction:

    - the claim gets its own name back by a no-replace rename, or stays
      (journaled) and is returned when that name is taken;
    - a private copy that never published (``incoming`` still at its
      private name, a journal from before r8) is removed only once THIS
      recovery has restored its claim (so the original bytes are back at
      their name) and it is still the journaled identity; with no claim to
      restore it may be the only copy left (round 10), so it stays,
      journaled, and is returned;
    - a copy that did publish stays where it is: with the claim restored,
      the chart exists twice and the user keeps the one they want.
    A private file the journal does not name is left alone."""
    _check_private_paths(log, log_path.parent)
    stuck: list[Path] = []
    changed = False
    for entry in log:
        if not isinstance(entry, dict):
            continue
        for record in entry.get("moves", []):
            for claim_key, origin_key, _target_key, incoming_key, id_key, phase_key in _DIRECTIONS:
                incoming = record.get(incoming_key)
                ident = record.get(id_key)
                claim = record.get(claim_key)
                if not (incoming or claim or record.get(phase_key) or ident):
                    continue
                claim_path = Path(claim) if claim else None
                restored = False
                if claim_path is not None and claim_path.exists():
                    if not _restore(claim_path, Path(record[origin_key])):
                        stuck.append(claim_path)
                        continue
                    restored = True
                if incoming and Path(incoming).exists():
                    if not (restored and _same(Path(incoming), ident)):
                        stuck.append(Path(incoming))  # maybe the only copy
                        continue
                    Path(incoming).unlink()  # never published; original restored
                for key in (claim_key, incoming_key, id_key, phase_key):
                    record[key] = None
                changed = True
    if changed:
        _write_log(log_path, log)
    return stuck


def _noter(record: dict, log_path: Path, log: list, prefix: str = "") -> Callable[..., None]:
    def note(field: str, value, write: bool = True) -> None:
        record[prefix + field] = value
        if write:
            _write_log(log_path, log)

    return note


def _source(folder: Path, filename: str) -> Path:
    """The direct child ``filename`` of ``folder``, never through a link
    (round 10: a resolved alias would move its target under the alias's
    name and write a journal its own recovery refuses)."""
    if not filename or filename in (".", "..") or Path(filename).name != filename:
        raise SortError(f"{filename!r} is not in the unsorted folder.", BAD_PROPOSAL)
    source = folder.resolve() / filename
    if source.is_symlink():
        raise SortError(f"{filename!r} is a link, not a chart file.", BAD_PROPOSAL)
    return source


def _check(proposal: Proposal, move: Move, by_name: dict[str, Move]) -> tuple[Path, Path, Move]:
    """Revalidate one chosen move against its proposal and the disk: the
    proposal's own move (the caller may only change its folder), a folder in
    the whitelist, a source still as previewed, a free destination."""
    original = by_name.get(move.filename)
    if original is None:
        raise SortError("it was not in the preview", BAD_PROPOSAL)
    if move.folder not in proposal.folders:
        raise SortError(f"the folder {move.folder!r} is not one of the allowed folders", BAD_PROPOSAL)
    source = _source(Path(proposal.unsorted_dir), move.filename)
    if not source.is_file():
        raise SortError("the file is no longer in the unsorted folder", BAD_PROPOSAL)
    if original.fingerprint is None or fingerprint(source) != tuple(original.fingerprint):
        raise SortError("the file changed since the preview", BAD_PROPOSAL)
    dest = _destination(Path(proposal.database), move.folder, move.filename)
    if dest.exists():
        raise SortError("a file with this name is already in that folder", BAD_PROPOSAL)
    chosen = replace(original, folder=move.folder, flag=flag_for(move.folder))
    return source, dest, chosen


def _bind(proposal: Proposal, database: str | Path | None) -> None:
    """The proposal acts on the chart folder it names, whose unsorted folder
    it names, and (when given) on the caller's chart folder only."""
    root = Path(proposal.database).resolve()
    if Path(proposal.unsorted_dir).resolve() != unsorted_dir(root).resolve():
        raise SortError("This proposal names another unsorted folder.", BAD_PROPOSAL)
    if database is not None and Path(database).resolve() != root:
        raise SortError(
            "This proposal is for another chart folder; propose again.", BAD_PROPOSAL
        )


def apply(
    proposal: Proposal,
    chosen: Sequence[Move | str] | None = None,
    *,
    database: str | Path | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SortReport:
    """Move the confirmed charts. ``chosen``: the reviewed moves, as the
    proposal's ``Move`` objects with only ``folder`` possibly edited (the
    preview's target combo), or file names; default every proposed move.
    Each is revalidated (``_check``); a refused one is reported, never moved.
    ``database`` binds the proposal to the caller's chart folder. The intent
    log is written before the first move (``SortError(kind=LOG)`` if it
    cannot be) and each move is journaled as soon as it is done.
    ``cancelled`` is polled between files."""
    _bind(proposal, database)
    folder = Path(proposal.unsorted_dir)
    with _locked(folder):
        return _apply(proposal, chosen, folder, cancelled or (lambda: False))


def _apply(proposal, chosen, folder: Path, cancelled) -> SortReport:
    by_name = {m.filename: m for m in proposal.moves}
    picked: list[Move] = []
    for item in proposal.moves if chosen is None else chosen:
        if isinstance(item, str):
            item = by_name.get(item, Move(item, item, ""))
        picked.append(item)

    results: list[MoveResult | None] = []
    planned: list[tuple[int, Path, Path, Move]] = []
    for move in picked:
        try:
            source, dest, ok = _check(proposal, move, by_name)
        except (SortError, OSError) as exc:
            results.append(MoveResult(move.filename, move.name, move.folder, False, str(exc)))
            continue
        planned.append((len(results), source, dest, ok))
        results.append(None)

    log_path = folder / LOG_NAME
    log = _read_log(log_path)
    stuck = _recover(log, log_path)  # a crash mid-move: finished from the journal
    entry = {
        "id": uuid.uuid4().hex,
        "version": PROPOSAL_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "moves": [
            {
                "filename": m.filename,
                "name": m.name,
                "folder": m.folder,
                "reason": m.reason,
                "source": str(source),
                "destination": str(dest),
                "fingerprint": list(m.fingerprint),
                "moved": False,
            }
            for _i, source, dest, m in planned
        ],
    }
    if planned:
        log.append(entry)
        _write_log(log_path, log)  # fail closed: nothing has moved yet

    stopped = ""
    for record, (index, source, dest, move) in zip(entry["moves"], planned, strict=True):
        if not stopped and cancelled():
            stopped = CANCELLED
        if stopped:
            results[index] = MoveResult(move.filename, move.name, move.folder, False, stopped)
            continue
        try:
            # Revalidated right before this move: a chart that changed while
            # earlier ones moved is refused, never moved (INV-9).
            source, dest, move = _check(proposal, move, by_name)
            _move_no_replace(source, dest, move.fingerprint, _noter(record, log_path, log))
        except (SortError, OSError) as exc:
            results[index] = MoveResult(move.filename, move.name, move.folder, False, str(exc))
            continue
        record["moved"] = True
        results[index] = MoveResult(move.filename, move.name, move.folder, True)
        try:
            _write_log(log_path, log)
        except SortError as exc:
            stopped = str(exc)  # this move is reconciled from the files later
    return SortReport(
        tuple(r for r in results if r is not None),
        str(log_path),
        tuple(str(p) for p in stuck),
        entry["id"] if planned else "",
    )


# --------------------------------------------------------------------- undo


def _reconcile(record: dict) -> bool:
    """Did this logged move happen? Journaled, or (a crash between the move
    and its journal write) its destination holds the previewed file and its
    source is gone."""
    if record.get("moved"):
        return True
    if record.get("restored"):
        return False
    dest = Path(record.get("destination") or "")
    source = Path(record.get("source") or "")
    expected = record.get("fingerprint")
    if not dest.name or not expected or source.exists() or not dest.is_file():
        return False
    try:
        return fingerprint(dest) == tuple(expected)
    except OSError:
        return False


def _last(log: list) -> dict | None:
    for entry in reversed(log):
        if isinstance(entry, dict) and not entry.get("undone"):
            if any(_reconcile(m) for m in entry.get("moves", [])):
                return entry
    return None


def last_sort(folder: str | Path) -> dict | None:
    """The last applied sort that moved something and is not undone; None
    too when the journal cannot be read (``undo`` then says why)."""
    try:
        return _last(_read_log(Path(folder) / LOG_NAME))
    except SortError:
        return None


def undo(
    folder: str | Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    entry_id: str | None = None,
) -> UndoReport:
    """Move back what the last sort moved: only a file still at its new place
    with its previewed content, whose old place is free. Others are skipped
    and named. The sort is then marked undone (undo again raises); a cancel
    between files journals what came back and leaves the rest undoable."""
    folder = Path(folder)
    with _locked(folder):
        return _undo(folder, cancelled or (lambda: False), entry_id)


def _undo(folder: Path, cancelled, entry_id: str | None = None) -> UndoReport:
    log_path = folder / LOG_NAME
    log = _read_log(log_path)
    stuck = _recover(log, log_path)  # a crash mid-move: finished from the journal
    entry = _last(log)
    if entry is None:
        if stuck:  # nothing to undo, but recovery kept files: say where
            return UndoReport(0, (), tuple(str(p) for p in stuck))
        raise SortError("There is no sort to undo.", UNDO_NONE)
    if entry_id is not None and entry.get("id") != entry_id:
        # The result on screen is not the last sort any more (a newer one,
        # or another folder's journal): never undo something else (round 9).
        raise SortError(
            "That sort is no longer the last one in this folder, so nothing was "
            "moved back.",
            UNDO_NONE,
        )
    restored = 0
    skipped: list[tuple[str, str]] = []
    interrupted = False
    for record in entry["moves"]:
        if not _reconcile(record):
            continue
        if cancelled():
            interrupted = True
            skipped.append((record.get("filename", ""), CANCELLED))
            continue
        dest = Path(record.get("destination", ""))
        source = Path(record.get("source", ""))
        name = record.get("filename", dest.name)
        if source.parent.resolve() != folder.resolve():
            skipped.append((name, "the log names another folder"))
            continue
        if not dest.is_file():
            skipped.append((name, "it is no longer where the sort put it"))
            continue
        expected = record.get("fingerprint")
        if expected and fingerprint(dest) != tuple(expected):
            skipped.append((name, "it changed since it was sorted"))
            continue
        if source.exists():
            skipped.append((name, "a file with this name is back in the unsorted folder"))
            continue
        try:
            _move_no_replace(dest, source, expected, _noter(record, log_path, log, "undo_"))
        except (SortError, OSError) as exc:
            skipped.append((name, str(exc)))
            continue
        record["moved"] = False
        record["restored"] = True
        restored += 1
    if not interrupted:
        entry["undone"] = True
    _write_log(log_path, log)
    return UndoReport(restored, tuple(skipped), tuple(str(p) for p in stuck))


# ------------------------------------------------------------------ JSON I/O


def proposal_to_json(proposal: Proposal) -> dict:
    data = asdict(proposal)
    data["version"] = PROPOSAL_VERSION
    data["moves"] = [asdict(m) for m in proposal.moves]
    return data


def proposal_from_json(data: dict) -> Proposal:
    """A proposal file (``propose --out``); ``SortError(kind=BAD_PROPOSAL)``
    for another version or a malformed file."""
    if not isinstance(data, dict) or data.get("version") != PROPOSAL_VERSION:
        raise SortError("This proposal file is from another version; propose again.", BAD_PROPOSAL)
    try:
        moves = tuple(
            Move(**{**m, "fingerprint": tuple(m["fingerprint"]) if m.get("fingerprint") else None})
            for m in data["moves"]
        )
        return Proposal(
            unsorted_dir=data["unsorted_dir"],
            database=data["database"],
            folders=tuple(data["folders"]),
            moves=moves,
            left=tuple(data.get("left", ())),
        )
    except (KeyError, TypeError) as exc:
        raise SortError("This proposal file cannot be read.", BAD_PROPOSAL, str(exc)) from exc
