# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Rate and Sort's one path for the sheet and the CLI (SPEC-LIB-002, Rule 24).

``load(database, library_root)``: the index's file entries, the mirror
refreshed, the library built and the profile run (guesses to the state file
only). ``confirm`` writes one ``[rating]`` (INV-2, INV-3) and updates the
mirror at once (D-23); ``restore`` puts the previous table back (UNDO).
Refused while the first chart folder is the old Kala folder (INV-9).
"""
from pathlib import Path
from typing import Optional

from core.library import queue, rating, tables
from core.library.paths import is_kala_folder
from core.library.state import State


class KalaFolder(PermissionError):
    """The first chart folder is the old Kala folder: nothing is rated there."""


KALA_REASON = ("This is Kala's chart folder, kept as a backup. Rating starts once your "
               "library is the first chart folder.")


def entries(store_file: Optional[Path] = None):
    from core.chart_search.store import StoreReader
    with StoreReader.open(store_file) as reader:
        return reader.library_entries()


def load(database, library_root, *, store_file: Optional[Path] = None, rows=None,
         cancelled=lambda: False, run_profile: bool = True):
    """``(lib, state)``; the caller closes ``state``. ``rows``: entries already read."""
    rows = entries(store_file) if rows is None else rows
    state = State(Path(library_root))
    queue.refresh_mirror(state, rows, database, cancelled)
    lib = queue.build(database, library_root, rows, state)
    if run_profile:
        queue.run_profile(lib, state, cancelled=cancelled)
    return lib, state


def guard(database, library_root=None) -> None:
    if is_kala_folder(database, library_root):
        raise KalaFolder(KALA_REASON)


def confirm(state: State, lib, group, values: dict, accepted=(), expect=None,
            today: Optional[str] = None, path: Optional[str] = None) -> tuple:
    """Write the rating of ``group`` to its main chart (or ``path``, one of
    its charts: the file the user rated); returns ``(path, previous raw table
    or None, written table)``."""
    guard(lib.database, lib.library_root)
    chart = group.main if path is None else next(c for c in group.charts if c.path == path)
    if chart.chtk:
        raise ValueError("convert this chart to .toml first")
    table = rating.build(values, accepted, today)
    previous = rating.write(chart.path, table, expect)
    group.written = tables.last_written()   # the bytes this write left: what UNDO expects
    queue.note_rated(state, chart.path, table)
    group.rating, group.rated_path = rating.clean(table), chart.path
    return chart.path, previous, table


def restore(state: State, lib, group, path: str, previous: Optional[dict],
            expect=None) -> None:
    """UNDO of a confirm: the previous ``[rating]``, or none. ``expect``: the
    file's fingerprint right after the confirm; a file changed since then
    (a newer rating) is refused with ``rating.Changed``."""
    guard(lib.database, lib.library_root)
    rating.write(path, previous, expect)
    table = rating.clean(previous) if previous else None
    queue.note_rated(state, path, table)
    if table and "who" in table and "known" in table:
        group.rating, group.rated_path = table, path
    else:
        group.rating, group.rated_path = {}, ""


def private_downloads(database, library_root=None) -> tuple:
    """File names in the unsorted downloads folder that read ``private``
    (a confirmed PRIVATE rating, or a profile guess of PRIVATE): never named
    in an AI request (INV-5, D-17). Reads only that folder's charts."""
    from core import chart_sort
    from core.library import privacy, profile as profile_mod
    if not database:
        return ()
    import os
    import tomllib
    from core.library import admin
    doc = profile_mod.load(Path(library_root)) if library_root else profile_mod.builtin()
    manifest = {}
    if library_root:
        for rec in admin.read_manifest(Path(library_root)).values():
            if rec.get("path"):
                manifest[os.path.normcase(str(Path(library_root) / rec["path"]))] = rec
    held = []
    for chart in chart_sort.chart_files(chart_sort.unsorted_dir(database)):
        table, library, no_time = {}, None, False
        try:
            if chart.filename.lower().endswith(".toml"):
                with open(chart.path, "rb") as f:
                    doc_toml = tomllib.load(f)
                table = doc_toml.get("rating") if isinstance(doc_toml.get("rating"), dict) else {}
                library = doc_toml.get("library") if isinstance(doc_toml.get("library"), dict) else None
                civil = doc_toml.get("civil") or {}
                no_time = str(civil.get("time", ""))[:5] == "12:00"
            else:
                lines = Path(chart.path).read_bytes().decode("utf-16-le").splitlines()
                if not lines or not lines[0].strip("\ufeff ").strip():
                    raise ValueError("no name")
                no_time = lines[4:6] == ["12", "0"]
        except Exception:  # noqa: BLE001 - unreadable: its name is unknown, held
            held.append(chart.filename)
            continue
        rec = manifest.get(os.path.normcase(chart.path)) or {}
        guess = profile_mod.guess(doc, {
            "folders": [chart_sort.UNSORTED_FOLDER], "name": chart.name,
            "stem": Path(chart.path).stem, "no_birth_time": no_time,
            "copies": rec.get("copies") or 1, "variants": rec.get("variant"),
            "origin": rec.get("origin"), "first_seen": rec.get("first_seen")})
        zone = (rating.zone(guess["who"]["value"], guess["known"]["value"])
                if "who" in guess and "known" in guess else None)
        if privacy.effective_privacy({"rating": table, "library": library,
                                      "guess": zone}) == privacy.PRIVATE:
            held.append(chart.filename)
    return tuple(held)
