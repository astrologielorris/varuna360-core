# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The library as Rate and Sort sees it, and the visit queue (SPEC-LIB-002
§3.3, §4.3). Qt-free.

``build(database, library_root, entries, state)`` groups the index's file
entries under the first chart folder: by the LIB-001 record id where the
manifest knows the file, else by the store's moment key (D-16). It reads the
store rows it is given, the state file and the manifest: no chart file
(INV-8). ``refresh_mirror`` is the one step that reads chart files (each
``.toml`` whose size or time changed), run in a worker before ``build``.

``visit(lib, size)`` picks the charts of a visit, in order: (1) the unsorted
downloads, (2) opened in the last 30 days, (3) a guess below 0.5 confidence,
(4) the rest; most copies first inside (3) and (4). Rated groups, skipped
groups and ``.chtk`` charts outside the unsorted folder are left out.
"""
import functools
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from core.library import admin, profile as profile_mod, rating
from core.library.state import State

UNSORTED = "celebrity_unsorted"  # core.chart_sort.UNSORTED_FOLDER
OPENED_DAYS = 30
LOW_CONFIDENCE = 0.5
AI_WEIGHT = 0.6
_SKIP_PARTS = ("trash", "chtk backup")


@dataclass
class Chart:
    path: str
    rel: str            # relative to the first chart folder
    name: str
    birth_local: str
    group: str
    mtime: Optional[float] = None
    size: Optional[int] = None
    place: str = ""

    # Read once per visit and per stats pass on 10,000 charts (INV-8): plain
    # attributes, set when the chart is made and when CONVERT AND RATE renames it.
    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.chtk = self.path.lower().endswith(".chtk")
        self.unsorted = self.rel.split("/", 1)[0] == UNSORTED
        self.no_birth_time = self.birth_local.endswith(" 12:00:00")


@dataclass
class Group:
    id: str
    charts: List[Chart] = field(default_factory=list)
    record: Optional[dict] = None          # the manifest row
    rating: dict = field(default_factory=dict)   # confirmed (mirror)
    rated_path: str = ""
    guess: dict = field(default_factory=dict)    # row -> {value, confidence, source}
    written: Optional[tuple] = None   # fingerprint after this session's confirm (UNDO)

    @functools.cached_property
    def main(self) -> Chart:
        """The chart shown and rated: the unsorted download first, else the
        manifest's file, else the first ``.toml``."""
        charts = sorted(self.charts, key=lambda c: (not c.unsorted, c.chtk, c.rel))
        if self.record and not charts[0].unsorted:
            for c in charts:
                if c.rel == self.record.get("_rel"):
                    return c
        return charts[0]

    @property
    def copies(self) -> int:
        return max(len(self.charts), int((self.record or {}).get("copies") or 1))

    @property
    def confirmed(self) -> bool:
        return "who" in self.rating and "known" in self.rating

    def zone(self) -> Optional[str]:
        if self.confirmed:
            return rating.zone(self.rating["who"], self.rating["known"])
        g = self.guess
        if "who" in g and "known" in g:
            return rating.zone(g["who"]["value"], g["known"]["value"])
        return None


@dataclass
class Library:
    database: str
    library_root: str
    groups: Dict[str, Group]
    profile: dict
    opened: Dict[str, float] = field(default_factory=dict)
    skipped: set = field(default_factory=set)

    def group_of(self, path: str) -> Optional[Group]:
        for g in self.groups.values():
            if any(c.path == path for c in g.charts):
                return g
        return None


def _inside(path: str, folder: str) -> Optional[str]:
    """``path`` relative to ``folder`` (``/``-separated), or None when it is
    outside, hidden, in a trash or in a CHTK backup folder (string-only: it
    runs once per indexed chart)."""
    prefix = os.path.normpath(folder).rstrip(os.sep) + os.sep
    path = os.path.normpath(path)
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix):].split(os.sep)
    if any(p.startswith(".") for p in parts) or any(p.lower() in _SKIP_PARTS for p in parts[:-1]):
        return None
    return "/".join(parts)


_MANIFEST_CACHE: Dict[str, tuple] = {}


def _manifest_by_path(library_root: Path) -> Dict[str, dict]:
    """Records by absolute path, read again only when ``manifest.jsonl``
    changed (size, time, file): the sheet reads the library on every open and
    RUN NOW, and the manifest of 5,000 charts is a 4 MB file. Read only."""
    path = Path(library_root) / admin.ADMIN / "manifest.jsonl"
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        stamp = None
    key = str(library_root)
    hit = _MANIFEST_CACHE.get(key)
    if stamp is not None and hit is not None and hit[0] == stamp:
        return hit[1]
    out = {}
    for rec in admin.read_manifest(library_root).values():
        if rec.get("path"):
            out[os.path.normcase(str(Path(library_root) / rec["path"]))] = rec
    if stamp is not None:
        _MANIFEST_CACHE[key] = (stamp, out)
    return out


def _stem(path: str) -> str:
    """``Path(path).stem`` without building a Path (once per chart per run)."""
    name = os.path.basename(path)
    i = name.rfind(".")
    return name[:i] if 0 < i < len(name) - 1 else name


def build(database, library_root, entries, state: State, *, now: Optional[float] = None) -> Library:
    """``entries``: ``StoreReader.library_entries()`` rows."""
    database, library_root = str(database), str(library_root)
    manifest = _manifest_by_path(Path(library_root))
    mirror = state.mirror()
    groups: Dict[str, Group] = {}
    for path, name, birth_local, key, mtime, size, *where in entries:
        if not path:
            continue
        rel = _inside(path, database)
        if rel is None:
            continue
        rec = manifest.get(os.path.normcase(path))
        gid = f"rec:{rec['id']}" if rec else f"moment:{key}"
        group = groups.setdefault(gid, Group(gid))
        if rec and group.record is None:
            group.record = dict(rec, _rel=rel)
        place = ", ".join(w.strip(" ,") for w in where if w and w.strip(" ,"))
        group.charts.append(Chart(path, rel, name or Path(path).stem, birth_local or "", gid,
                                  mtime, size, place))
        row = mirror.get(path)
        if row and row[2]:
            table = rating.clean(row[2])
            if "who" in table and "known" in table and not group.confirmed:
                group.rating, group.rated_path = table, path
    lib = Library(database, library_root, groups, profile_mod.load(Path(library_root)),
                  opened=state.opened(), skipped=state.skipped(now))
    cached = state.guesses()
    for gid, g in groups.items():
        if gid in cached:
            g.guess = cached[gid]
    return lib


def refresh_mirror(state: State, entries, database, cancelled=lambda: False) -> int:
    """Read the ``[rating]`` of every ``.toml`` under ``database`` whose size
    or time changed since the mirror saw it; forget paths no longer indexed.
    Returns the number of files read."""
    mirror = state.mirror()
    seen, rows = set(), []
    for path, _n, _b, _k, mtime, size, *_where in entries:
        if not path or not path.lower().endswith(".toml") or _inside(path, str(database)) is None:
            continue
        seen.add(path)
        old = mirror.get(path)
        if old and old[0] == mtime and old[1] == size:
            continue
        if cancelled():
            break
        try:
            table = rating.read(path) or None
        except (OSError, ValueError):
            table = None
        rows.append((path, mtime, size, table))
    state.set_mirror(rows)
    state.forget_mirror([p for p in mirror if p not in seen])
    return len(rows)


def note_rated(state: State, path: str, table: Optional[dict]) -> None:
    """The mirror follows a confirm or an undo at once (D-23)."""
    try:
        st = os.stat(path)
        state.set_mirror([(path, st.st_mtime, st.st_size, table)])
    except OSError:
        pass


def facts(lib: Library, group: Group) -> dict:
    chart = group.main
    rec = group.record or {}
    opened = max((lib.opened.get(c.path, 0) for c in group.charts), default=0) or None
    return {"folders": chart.rel.split("/")[:-1], "name": chart.name,
            "stem": _stem(chart.path), "copies": group.copies,
            "variants": rec.get("variant") if rec else None,
            "no_birth_time": chart.no_birth_time, "origin": rec.get("origin"),
            "first_seen": rec.get("first_seen"), "opened": opened}


def run_profile(lib: Library, state: State, *, now: Optional[float] = None,
                cancelled=lambda: False) -> int:
    """Guess every unrated group with the profile and the AI guesses; the
    result goes to the state file only (INV-2). Returns the guesses made."""
    ai = state.ai_guesses()
    out = {}
    for gid, g in lib.groups.items():
        if cancelled():
            return 0
        if g.confirmed:
            continue
        guess = profile_mod.guess(lib.profile, facts(lib, g), now)
        a = ai.get(gid)
        for row in ("who", "known"):
            if a and a.get(row) is not None and (
                    row not in guess or AI_WEIGHT > guess[row]["confidence"]):
                guess[row] = {"value": a[row], "confidence": AI_WEIGHT, "source": "AI"}
        if guess:
            out[gid] = guess
        g.guess = guess
    version = int((lib.profile.get("profile") or {}).get("version") or 0)
    state.set_guesses(out, version)
    state.set_meta("profile_last_run", {"at": time.time() if now is None else now,
                                        "guesses": sum(len(v) for v in out.values())})
    return len(out)


def _tier(lib: Library, g: Group, now: float) -> Optional[int]:
    if g.confirmed or g.id in lib.skipped:
        return None
    chart = g.main
    if chart.unsorted:
        return 1
    if chart.chtk:
        return None
    if lib.opened and any(now - lib.opened.get(c.path, 0) <= OPENED_DAYS * 86400
                          for c in g.charts):
        return 2
    rows = [g.guess.get(r) for r in ("who", "known")]
    if any(r is None or r["confidence"] < LOW_CONFIDENCE for r in rows):
        return 3
    return 4


def _key(tier: int, g: Group) -> tuple:
    return (tier, -g.copies if tier >= 3 else 0, g.main.name.lower(), g.id)


def ordered(lib: Library, now: Optional[float] = None) -> List[tuple]:
    """``(tier, group)`` of every group waiting, best first."""
    now = time.time() if now is None else now
    out = []
    for g in lib.groups.values():
        tier = _tier(lib, g, now)
        if tier is not None:
            out.append((tier, g))
    out.sort(key=lambda tg: _key(*tg))
    return out


def waiting(lib: Library, now: Optional[float] = None) -> int:
    """"N charts waiting to be rated": tiers 1 to 3 (counted, not sorted)."""
    now = time.time() if now is None else now
    return sum(1 for g in lib.groups.values() if (_tier(lib, g, now) or 9) <= 3)


def visit(lib: Library, size: int, exclude=(), now: Optional[float] = None) -> List[Group]:
    """The next ``size`` groups of a visit, ``exclude`` (group ids already in
    this visit) left out; only the first ``size`` are ordered (INV-8)."""
    import heapq
    now = time.time() if now is None else now
    exclude = set(exclude)
    keyed = ((_key(t, g), g) for g in lib.groups.values()
             if g.id not in exclude and (t := _tier(lib, g, now)) is not None)
    return [g for _k, g in heapq.nsmallest(size, keyed, key=lambda kg: kg[0])]
