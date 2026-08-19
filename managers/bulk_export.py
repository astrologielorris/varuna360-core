# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Give a file to the charts that never got one (SPEC-EXPORT-001, td-2by9).

SPEC-PERSIST-001 makes every NEW chart write a file. It deliberately rewrites
nothing that already exists, so the charts created before it — 234 of 708
live panel entries at the time of writing — still exist only inside
session.json. One corrupt or regenerated session file and they are gone.
This is the manual sweep that fixes that, on the user's command.

TWO STAGES, AND THEY ARE NOT THE SAME KIND OF EVIDENCE (D-8)

* **Stage 1 — the entry names a file that exists.** Certain. Skip it
  silently; there is nothing to do and nothing to ask.
* **Stage 2 — the chart index holds a chart at the same position.** A
  PROBABILITY, not a fact. It FLAGS for confirmation and never skips on its
  own, because a wrong skip here is the one outcome this whole feature
  exists to prevent: the chart stays file-less and the user believes it was
  handled.

Exact equality never fires as a duplicate test — the Ascendant moves about
0.0042 deg/s, so two saves of "the same" chart differ in the sixth decimal.
A tolerance is required, and it is stated here rather than discovered.

Transits are excluded by design (D-11): a transit is a moment, not a person,
and 21 of the file-less entries are transits. They get a per-chart "save as
event" action instead, not a place in a bulk sweep of birth charts.

The engine is Qt-free and returns a report. The GUI runs it off the main
thread — an orphan has no stored longitudes, so deciding stage 2 costs a
chart BUILD per orphan, and doing that on the GUI thread would freeze the
window for as long as it takes.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

#: Degrees. Two positions closer than this are treated as the same chart for
#: the purposes of ASKING. ~0.0042 deg/s of Ascendant motion means this is
#: about a second of birth time — tight enough that two different people are
#: not flagged, loose enough that a re-save of one chart is.
POSITION_TOLERANCE_DEG = 0.01

SKIPPED_HAS_FILE = "has_file"
SKIPPED_TRANSIT = "transit"
FLAGGED_POSSIBLE_DUPLICATE = "possible_duplicate"


@dataclass
class ExportPlan:
    """What a sweep would do, before it does any of it."""
    to_write: List[Dict[str, Any]] = field(default_factory=list)
    flagged: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.to_write) + len(self.flagged) + len(self.skipped)


@dataclass
class ExportResult:
    written: List[str] = field(default_factory=list)
    failed: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    flagged: List[Dict[str, Any]] = field(default_factory=list)


def _has_existing_file(entry: Dict[str, Any]) -> bool:
    """Stage 1. Certain evidence, so it may skip silently."""
    import os
    path = entry.get("chtk_path")
    return bool(path) and os.path.exists(str(path))


def _is_transit(entry: Dict[str, Any]) -> bool:
    if entry.get("is_transit"):
        return True
    name = str((entry.get("recipe") or {}).get("name") or entry.get("person_name") or "")
    return name.strip().lower().startswith("now ")


def index_positions(index_entries) -> List[Dict[str, Any]]:
    """The stage-2 haystack: (sun_lon, ascendant_lon) per indexed file.

    Entries without both longitudes are dropped rather than defaulted — a
    missing position that compares equal to another missing position would
    flag every one of them against every other.
    """
    out = []
    for entry in index_entries or []:
        if not isinstance(entry, dict):
            continue
        sun, asc = entry.get("sun_lon"), entry.get("ascendant_lon")
        if sun is None or asc is None:
            continue
        try:
            out.append({"sun_lon": float(sun), "ascendant_lon": float(asc),
                        "filepath": entry.get("filepath"),
                        "name": entry.get("name", "")})
        except (TypeError, ValueError):
            continue
    return out


def _angular_gap(a: float, b: float) -> float:
    """Separation in degrees, wrapping at 360.

    Plain subtraction calls 359.999 and 0.001 half a circle apart, so a
    chart saved either side of 0 Aries would never match itself.
    """
    diff = abs(float(a) - float(b)) % 360.0
    return min(diff, 360.0 - diff)


def find_position_match(sun_lon, asc_lon, haystack,
                        tolerance: float = POSITION_TOLERANCE_DEG):
    """The indexed chart at this position, or None. A HINT, never a verdict."""
    if sun_lon is None or asc_lon is None:
        return None
    for candidate in haystack:
        if (_angular_gap(sun_lon, candidate["sun_lon"]) <= tolerance
                and _angular_gap(asc_lon, candidate["ascendant_lon"]) <= tolerance):
            return candidate
    return None


def plan_export(entries, haystack=None, position_fn: Optional[Callable] = None,
                include_transits: bool = False) -> ExportPlan:
    """Decide what to write WITHOUT writing anything.

    `position_fn(entry) -> (sun_lon, asc_lon)` builds the chart for an
    orphan. It is a parameter because it is the expensive part: the caller
    supplies a real builder off the GUI thread, and a test supplies a stub.
    Passing None skips stage 2 entirely — every orphan is then written, which
    is the safe direction (a duplicate file is recoverable; a chart that
    exists nowhere is not).
    """
    plan = ExportPlan()
    haystack = haystack or []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if _has_existing_file(entry):
            plan.skipped.append({"entry": entry, "reason": SKIPPED_HAS_FILE})
            continue
        if _is_transit(entry) and not include_transits:
            plan.skipped.append({"entry": entry, "reason": SKIPPED_TRANSIT})
            continue
        match = None
        if position_fn is not None and haystack:
            try:
                sun_lon, asc_lon = position_fn(entry)
                match = find_position_match(sun_lon, asc_lon, haystack)
            except Exception:
                # A chart that cannot be built cannot be compared. Writing it
                # is still the right answer: the worst case is a duplicate
                # file, and the alternative is leaving it file-less forever.
                match = None
        if match is not None:
            plan.flagged.append({"entry": entry, "reason": FLAGGED_POSSIBLE_DUPLICATE,
                                 "match": match})
        else:
            plan.to_write.append(entry)
    return plan


def export_entries(entries, chart_folder=None, chart_format=None,
                   progress_fn: Optional[Callable] = None) -> ExportResult:
    """Write one file per entry through the SHARED writer.

    Deliberately `persist_birth_data`, not a second writer: format, folder,
    collision handling and atomicity are decided in one place, and a bulk
    sweep that drifted from the creation path would produce a database with
    two dialects in it.
    """
    from core.chart_factory import metadata_from_recipe
    from managers.chart_creation_pipeline import persist_birth_data
    from managers.birth_data_manager import BirthDataManager

    result = ExportResult()
    for index, entry in enumerate(entries or []):
        recipe = (entry or {}).get("recipe")
        name = (recipe or {}).get("name") or entry.get("person_name") or "Unknown"
        try:
            if not isinstance(recipe, dict):
                raise ValueError("entry has no recipe")
            birth_data, _meta = metadata_from_recipe(recipe)
            if "local_year" not in birth_data:
                # metadata_from_recipe returns the flat legacy shape; the
                # writer needs the CANONICAL one, or it reads the offset as
                # a base rather than a total and stores the chart an hour
                # out (the same trap the creation path documents).
                birth_data = BirthDataManager.create_from_form_data({
                    "name": name,
                    "year": recipe["year"], "month": recipe["month"],
                    "day": recipe["day"],
                    "hour": int(recipe["timedec"]),
                    "minute": int(round((recipe["timedec"] % 1) * 60)),
                    "second": 0,
                    "timezone": _offset_string(recipe),
                    "dst": recipe.get("time_change_flag", 0) or 0,
                    "time_mode": "Local",
                    "latitude": recipe["lat"], "longitude": recipe["lon"],
                    "city": recipe.get("city", ""),
                    "country": recipe.get("country", ""),
                    "gender": recipe.get("gender", "Unknown"),
                    "iana_timezone": recipe.get("timezone", ""),
                })
            path, _fmt, error = persist_birth_data(
                birth_data, name=name, chart_folder=chart_folder,
                chart_format=chart_format,
                julian_day=recipe.get("julian_day"))
            if error:
                result.failed.append({"name": name, "error": error})
            else:
                result.written.append(path)
        except Exception as e:                              # noqa: BLE001
            result.failed.append({"name": name, "error": f"{type(e).__name__}: {e}"})
        if progress_fn:
            try:
                progress_fn(index + 1, len(entries), name)
            except Exception:
                pass
    return result


def _offset_string(recipe) -> str:
    """The STANDARD base offset as '+HH:MM:SS' — the form-data convention.

    The recipe carries the TOTAL offset, so the DST amount has to come off
    before it is handed to a field that means "base"; leaving it in stores
    the chart an hour out. Seconds-preserving (td-5mg6).
    """
    from core.time_utils import format_offset_from_hours
    total = float(recipe.get("utcoffset") or 0.0)
    dst = recipe.get("dst_offset_hours")
    if dst is None:
        flag = recipe.get("time_change_flag", 0) or 0
        dst = float(flag) if flag in (1, 2) else 0.0
    return format_offset_from_hours(total - float(dst))
