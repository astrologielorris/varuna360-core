# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart sources: moments and entries (design.md §4.2, D3, D5).

A **moment** is what gets computed; an **entry** is what the user sees and
opens. Entries point to moments; two files with the same birth data compute once.

**Moment key rounding.** ``MomentKey`` holds integers so equality is exact:

- ``jd_s = round(jd_ut * 86400)``: whole seconds of UT (int64 holds it);
- ``lat_e4``, ``lon_e4 = round(deg * 1e4)``: about 11 m;
- ``offset_min = round(utc_offset_hours * 60)``: Cards of Truth reads the
  local birth date, so two charts at one UT instant with different offsets
  are different moments.

The rounding absorbs float noise from recomputing a JD; it is not a fuzzy match.
A moment's computation uses the ``jd_ut`` / ``lat`` / ``lon`` first stored for
the key (at most half a second and 5e-5 degrees from any other entry's).

Files are read through ``BirthDataManager.create_birth_data_from_file(path,
canonicalize=False)`` (house rule 4; it inverts the CHTK timezone sign). A
session recipe is already converted: its ``utcoffset`` is the standard-sign
total offset, and its JD comes from ``chart_factory.jd_from_recipe``, the rule
``build_chart_from_recipe`` uses. Nothing here writes a chart file or a session.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NewType

from core import chart_kind
from core.chart_factory import jd_from_birth_data, jd_from_recipe, timedec_to_hms
from core.chart_search.errors import Unreadable
from managers.birth_data_manager import BirthDataManager

CHART_SUFFIXES = frozenset({".chtk", ".toml"})

#: ``file:<absolute path>`` or ``session:<profile>:<uuid>``.
EntryId = NewType("EntryId", str)


@dataclass(frozen=True)
class MomentKey:
    jd_s: int
    lat_e4: int
    lon_e4: int
    offset_min: int

    @classmethod
    def of(
        cls, jd_ut: float, lat: float, lon: float, utc_offset_hours: float
    ) -> MomentKey:
        return cls(
            jd_s=round(jd_ut * 86400),
            lat_e4=round(lat * 1e4),
            lon_e4=round(lon * 1e4),
            offset_min=round(utc_offset_hours * 60),
        )

    def encode(self) -> str:
        """``"<jd_s>:<lat_e4>:<lon_e4>:<offset_min>"``, the ``moments.key`` column."""
        return f"{self.jd_s}:{self.lat_e4}:{self.lon_e4}:{self.offset_min}"

    @classmethod
    def decode(cls, key: str) -> MomentKey:
        """The inverse of ``encode``."""
        jd_s, lat_e4, lon_e4, offset_min = (int(part) for part in key.split(":"))
        return cls(jd_s, lat_e4, lon_e4, offset_min)


@dataclass(frozen=True)
class Moment:
    key: MomentKey
    jd_ut: float
    lat: float
    lon: float
    utc_offset_hours: float


class EntryKind(StrEnum):
    """Written by ``ChartMemoryPanel.add_chart(..., kind=...)``; inferred when absent."""

    BIRTH = "birth"
    TRANSIT = "transit"  # Now, dasha moment
    EVENT = "event"  # eclipse, lunar
    TRIAL = "trial"  # birth-time-finder candidates


@dataclass(frozen=True)
class FileOrigin:
    path: str  # absolute
    mtime: float
    size: int


@dataclass(frozen=True)
class SessionOrigin:
    profile: str
    session_id: str  # the session chart's uuid
    chtk_path: (
        str | None
    )  # kept when the file is stale or not scanned yet (folder filter)
    unsaved_changes: bool  # the file exists and is indexed, but its moment differs


@dataclass(frozen=True)
class Entry:
    entry_id: EntryId
    moment: Moment
    origin: FileOrigin | SessionOrigin
    name: str
    place: str
    country: str
    notes: str
    kind: EntryKind
    birth_local: str  # "YYYY-MM-DD HH:MM:SS", the chart's own local time

    @property
    def path(self) -> str | None:
        """The file to open or folder-filter on (a session entry's ``chtk_path``)."""
        if isinstance(self.origin, FileOrigin):
            return self.origin.path
        return self.origin.chtk_path


@dataclass(frozen=True)
class Loaded:
    """A file entry that a profile's session holds with the same moment."""

    entry_id: EntryId
    profile: str
    session_id: str


@dataclass(frozen=True)
class FileState:
    mtime: float
    size: int


# ------------------------------------------------------------------- folders


@dataclass(frozen=True)
class FolderScan:
    """An incremental scan. ``unchanged`` paths keep their rows; ``removed``
    paths are gone from disk; previously unreadable files that are unchanged
    are neither re-parsed nor re-reported here (the store still lists them)."""

    entries: tuple[Entry, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]
    unreadable: tuple[Unreadable, ...]


class ScanCancelled(Exception):
    """A folder scan stopped by its ``cancelled`` callback (SPEC-FIND-005
    §3.10). Raised before the caller writes anything."""


#: Scan progress reports at most this often (as compute's, FIND-003 §4).
SCAN_PROGRESS_INTERVAL_S = 0.1


def scan_folders(
    folders: Sequence[Path],
    known: Mapping[str, FileState],
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> FolderScan:
    """Walk ``.chtk`` / ``.toml`` under ``folders``; ``known`` is the store's
    ``(mtime, size)`` per path, entries and unreadable alike. Never raises for
    one file. ``progress(done, total)`` is throttled; ``total`` 0 means the
    files are still being discovered. ``cancelled()`` is polled per directory
    and per file and raises ``ScanCancelled``; the scan writes nothing, so a
    cancel leaves the store as it was."""
    stop = cancelled or (lambda: False)
    last = [0.0]

    def report(done: int, total: int, *, force: bool = False) -> None:
        now = time.monotonic()
        if progress is not None and (force or now - last[0] >= SCAN_PROGRESS_INTERVAL_S):
            last[0] = now
            progress(done, total)

    report(0, 0, force=True)
    files = _chart_files(folders, stop)
    entries: list[Entry] = []
    unchanged: list[str] = []
    unreadable: list[Unreadable] = []
    seen: set[str] = set()
    for done, path in enumerate(files):
        if stop():
            raise ScanCancelled()
        report(done, len(files))
        if path in seen:  # overlapping folders
            continue
        seen.add(path)
        try:
            st = os.stat(path)
        except OSError as exc:
            unreadable.append(Unreadable(path, _describe(exc)))
            continue
        if known.get(path) == FileState(st.st_mtime, st.st_size):
            unchanged.append(path)
            continue
        result = _read_stat(path, st)
        if isinstance(result, Entry):
            entries.append(result)
        else:
            unreadable.append(result)
    report(len(files), len(files), force=True)
    removed = tuple(p for p in known if p not in seen and not os.path.exists(p))
    return FolderScan(tuple(entries), tuple(unchanged), removed, tuple(unreadable))


def read_file(path: Path) -> Entry | Unreadable:
    """One chart file (the single-file upsert when the app touches a file)."""
    abs_path = os.path.abspath(path)
    try:
        st = os.stat(abs_path)
    except OSError as exc:
        return Unreadable(abs_path, _describe(exc))
    return _read_stat(abs_path, st)


def _chart_files(
    folders: Sequence[Path], cancelled: Callable[[], bool] = lambda: False
) -> list[str]:
    """Absolute ``.chtk`` / ``.toml`` paths under ``folders``, sorted per folder.
    A missing or unreadable folder yields nothing."""
    paths: list[str] = []
    for folder in folders:
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(os.path.abspath(folder)):
            if cancelled():
                raise ScanCancelled()
            # Hidden folders (the library's .library admin), Find Chart's own
            # "trash" and Kala's "CHTK backup" folders are not charts to search
            # (SPEC-LIB-001 D-32).
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and d.lower() not in ("chtk backup", "trash")]
            found.extend(
                os.path.join(dirpath, name)
                for name in filenames
                if os.path.splitext(name)[1].lower() in CHART_SUFFIXES
            )
        paths.extend(sorted(found))
    return paths


def _read_stat(path: str, st: os.stat_result) -> Entry | Unreadable:
    try:
        birth_data = BirthDataManager.create_birth_data_from_file(
            path, canonicalize=False
        )
        return _file_entry(path, st, birth_data)
    # One file never stops a scan (principle 6). The readers fail with I/O,
    # decode (UnicodeError, TOMLDecodeError), missing-line and bad-number errors.
    except (
        OSError,
        ValueError,
        LookupError,
        TypeError,
        AttributeError,
        ArithmeticError,
    ) as exc:
        return Unreadable(path, _describe(exc), st.st_mtime, st.st_size)


def _file_entry(
    path: str, st: os.stat_result, birth_data: Mapping[str, object]
) -> Entry:
    name = str(birth_data.get("name") or "")
    moment = _moment(
        jd_from_birth_data(birth_data),
        float(birth_data["latitude"]),
        float(birth_data["longitude"]),
        float(birth_data["utc_offset_hours"]),
    )
    birth_local = _local_string(
        int(birth_data["local_year"]),
        int(birth_data["local_month"]),
        int(birth_data["local_day"]),
        int(birth_data["local_hour"]),
        int(birth_data["local_minute"]),
        int(birth_data["local_second"]),
    )
    return Entry(
        entry_id=EntryId(f"file:{path}"),
        moment=moment,
        origin=FileOrigin(path, st.st_mtime, st.st_size),
        name=name,
        place=str(birth_data.get("city") or ""),
        country=str(birth_data.get("country") or ""),
        notes=str(birth_data.get("notes") or ""),
        kind=_infer(None, False, name),
        birth_local=birth_local,
    )


# ------------------------------------------------------------------ sessions


@dataclass(frozen=True)
class CurrentSession:
    """The running app's profile, read from memory rather than disk."""

    profile: str
    charts: Sequence[Mapping[str, object]]  # session.json ``charts[]`` shape


@dataclass(frozen=True)
class SessionScan:
    entries: tuple[
        Entry, ...
    ]  # session: entries (no file, stale, unsaved, not scanned)
    loaded: tuple[Loaded, ...]  # session charts merged into file entries
    unreadable: tuple[
        Unreadable, ...
    ]  # a corrupt session.json, a chart without a usable recipe
    #: Profiles whose session.json could not be read: a sync keeps their rows
    #: rather than reading "no charts" into them.
    damaged: tuple[str, ...] = ()


def read_sessions(
    profiles_dir: Path,
    current: CurrentSession | None,
    file_moments: Mapping[str, MomentKey],
) -> SessionScan:
    """Every profile's ``session.json`` (the current one from ``current``).
    ``file_moments`` is the store's moment per indexed file path: a session
    chart whose ``chtk_path`` is there with the same key merges into it."""
    entries: list[Entry] = []
    loaded: list[Loaded] = []
    unreadable: list[Unreadable] = []
    damaged: list[str] = []
    sessions: list[tuple[str, Sequence[object]]] = []
    if current is not None:
        sessions.append((current.profile, current.charts))
    for profile, charts in _disk_sessions(profiles_dir, current):
        if isinstance(charts, Unreadable):
            unreadable.append(charts)
            damaged.append(profile)
        else:
            sessions.append((profile, charts))
    for profile, charts in sessions:
        for chart in charts:
            result = _session_chart(profile, chart, file_moments)
            if isinstance(result, Entry):
                entries.append(result)
            elif isinstance(result, Loaded):
                loaded.append(result)
            else:
                unreadable.append(result)
    return SessionScan(tuple(entries), tuple(loaded), tuple(unreadable), tuple(damaged))


def infer_kind(chart: Mapping[str, object]) -> EntryKind:
    """The entry's Find Chart kind, from its written ``kind`` (a Find Chart
    kind, or one of the app's ``core.chart_kind`` kinds) or, for entries saved
    before ``kind`` existed, from ``is_transit`` and the chart's name."""
    recipe = chart.get("recipe")
    name = recipe.get("name") if isinstance(recipe, Mapping) else None
    return _infer(chart.get("kind"), bool(chart.get("is_transit")), name)


def kind_field(entry: Mapping[str, object]) -> dict[str, object]:
    """``{"kind": ...}`` when the entry carries one, else ``{}``: code that
    copies entry fields by hand splats this so an absent kind stays absent."""
    return {"kind": entry["kind"]} if entry.get("kind") is not None else {}


#: The app's own chart kinds (``core.chart_kind``, written on every session
#: entry) folded into Find Chart's four.
_FROM_APP_KIND = {
    chart_kind.BIRTH: EntryKind.BIRTH,
    chart_kind.TRANSIT: EntryKind.TRANSIT,
    chart_kind.DASHA_MOMENT: EntryKind.TRANSIT,
    chart_kind.ECLIPSE: EntryKind.EVENT,
    chart_kind.LUNAR: EntryKind.EVENT,
    chart_kind.EXPLORATION: EntryKind.EVENT,
    chart_kind.BIRTH_TIME_FINDER: EntryKind.TRIAL,
}


def _infer(written: object, is_transit: bool, name: object) -> EntryKind:
    """A Find Chart kind as written; else the app's kind (``chart_kind.entry_kind``:
    the written app kind, or its legacy classification from ``is_transit`` and
    the names the app gives its event charts), folded into the four."""
    if isinstance(written, str) and written in {k.value for k in EntryKind}:
        return EntryKind(written)
    entry = {
        "kind": written,
        "is_transit": is_transit,
        "recipe": {"name": name if isinstance(name, str) else ""},
    }
    return _FROM_APP_KIND[chart_kind.entry_kind(entry)]


def _disk_sessions(
    profiles_dir: Path, current: CurrentSession | None
) -> list[tuple[str, Sequence[object] | Unreadable]]:
    """``charts[]`` of every profile on disk but the current one. A profile
    without ``session.json`` has no charts; a corrupt one is reported."""
    if not profiles_dir.is_dir():
        return []
    skip = current.profile if current is not None else None
    found: list[tuple[str, Sequence[object] | Unreadable]] = []
    for profile_dir in sorted(profiles_dir.iterdir()):
        session_path = profile_dir / "session.json"
        if profile_dir.name == skip or not session_path.is_file():
            continue
        profile = profile_dir.name
        source = f"session:{profile}"
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # JSONDecodeError, UnicodeDecodeError
            found.append((profile, Unreadable(source, _describe(exc))))
            continue
        charts = data.get("charts") if isinstance(data, dict) else None
        if not isinstance(charts, list):
            found.append((profile, Unreadable(source, "no charts[] list")))
            continue
        found.append((profile, charts))
    return found


def _session_chart(
    profile: str, chart: object, file_moments: Mapping[str, MomentKey]
) -> Entry | Loaded | Unreadable:
    if not isinstance(chart, Mapping):
        return Unreadable(f"session:{profile}", "a chart that is not an object")
    session_id = chart.get("id")
    if not isinstance(session_id, str) or not session_id:
        return Unreadable(f"session:{profile}", "a chart without an id")
    source = f"session:{profile}:{session_id}"
    recipe = chart.get("recipe")
    if not isinstance(recipe, Mapping):
        return Unreadable(source, "no recipe")
    try:
        moment = _moment(
            jd_from_recipe(recipe),
            float(recipe["lat"]),
            float(recipe["lon"]),
            float(recipe["utcoffset"]),
        )
        hour, minute, second = timedec_to_hms(float(recipe["timedec"]))
        birth_local = _local_string(
            int(recipe["year"]),
            int(recipe["month"]),
            int(recipe["day"]),
            hour,
            minute,
            second,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return Unreadable(source, f"unusable recipe: {_describe(exc)}")

    raw_path = chart.get("chtk_path")
    chtk_path = (
        os.path.abspath(raw_path) if isinstance(raw_path, str) and raw_path else None
    )
    file_key = file_moments.get(chtk_path) if chtk_path is not None else None
    if file_key == moment.key:
        return Loaded(EntryId(f"file:{chtk_path}"), profile, session_id)
    return Entry(
        entry_id=EntryId(source),
        moment=moment,
        origin=SessionOrigin(
            profile=profile,
            session_id=session_id,
            chtk_path=chtk_path,
            unsaved_changes=file_key is not None,
        ),
        name=str(recipe.get("name") or ""),
        place=str(recipe.get("city") or ""),
        country=str(recipe.get("country") or ""),
        notes=str(recipe.get("notes") or ""),
        kind=infer_kind(chart),
        birth_local=birth_local,
    )


# ------------------------------------------------------------------- helpers


def _moment(jd_ut: float, lat: float, lon: float, utc_offset_hours: float) -> Moment:
    return Moment(
        MomentKey.of(jd_ut, lat, lon, utc_offset_hours),
        jd_ut,
        lat,
        lon,
        utc_offset_hours,
    )


def _local_string(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> str:
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"
