# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart health checks without AI (SPEC-LIB-001 §4.9): find damaged chart
files and doubtful timezones in a chart folder, on the app's own.

Every pattern here was found by hand in an earlier audit and is now a rule:

Per file
    ``unreadable``         the app cannot open the chart (for example an hour of 25).
    ``chtk_truncated``     a CHTK file with fewer than 14 lines.
    ``chtk_bad_field``     a date or time line that is not a number in range.
    ``chtk_line_shift``    Kala's gender field holds extra bytes that pushed the
                           lines down: the DST flag line is not -1, 0 or 1 (td-vpz7).
    ``chtk_bad_offset``    line 13 is not an offset or a zone name.
    ``unset_offset``       offset 00:00:00, no DST, at a place that is not on UTC.
    ``kala_atlas``         a place Kala's atlas is known to get wrong (td-no9v).
    ``dst_flag_wrong``     the zone is right but the DST flag disagrees with the date.
    ``dst_baked``          the DST hour is in the stored offset and the flag adds it again (td-fkvx).
    ``offset_sign``        the offset has the wrong sign (east and west swapped).
    ``offset_floor``       a half-hour offset one hour too far west (td-256o).
    ``base_zone_wrong``    the stored standard offset is not the zone's.
    ``offset_minutes``     after 1970, an offset that is off by less than an hour.
    ``no_coordinates``     latitude and longitude both 0.
    ``mojibake_name``      the name has broken accents (for example "Ã©" for "é").

Across files (same person or event)
    ``timezone_conflict``  same name and local time with another offset or place,
                           or birth moments a whole number of hours apart.
    ``rectification``      same name and day, Ascendants more than 0.5° apart.
    ``different_dates``    same name, another birth date.
    ``same_moment``        same birth moment and place under unrelated names.

Levels: ``error`` the file is damaged; ``warning`` the timezone is wrong for
the date (1970 and later, where zone history is reliable); ``check`` the same
finding before 1970, where a city may have changed zone since (the check
itself can be wrong, so look by hand); ``info`` worth knowing.

Charts before 1900 skip the zone checks (local mean time). Nothing here
writes a chart; the results go to the library's ``.library/checks``.
"""
import contextlib
import io
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.library import names
from core.library.merge import ASC_LIMIT, _asc_gap, _tz_conflict
from core.library.survey import _ascendant, chart_files, moment_key

LEVELS = ("error", "warning", "check", "info")
ZONE_CHECK_FROM = 1900   # local mean time before: no zone check
RELIABLE_FROM = 1970     # zone history reliable from here
_MOJIBAKE = re.compile("[ÃÂ][\u0080-¿]")

# Places Kala's atlas files in the wrong zone (2026-07-15 audit, td-no9v):
# (label, lat, lon, from date, the standard offset Kala writes).
KALA_ATLAS_ERRORS = (
    ("Juneau, Alaska", 58.30, -134.42, (1983, 10, 30), -8.0),
    ("Boise, Idaho", 43.61, -116.20, (1900, 1, 1), -8.0),
)


def finding(code: str, level: str, message: str, **details) -> dict:
    return {"code": code, "level": level, "message": message, **details}


def _hours(value: float) -> str:
    sign = "-" if value < 0 else "+"
    value = abs(value)
    h, m = int(value), int(round((value - int(value)) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


# ---------------------------------------------------------------- CHTK text
def chtk_structure(path: Path) -> List[dict]:
    """Damage visible in the CHTK text itself, before any reading."""
    from core.chtk_text import normalize_chtk_timezone, read_chtk_text, split_chtk_lines
    lines = split_chtk_lines(read_chtk_text(path))
    out = []
    if len(lines) < 14:
        return [finding("chtk_truncated", "error",
                        f"The file has {len(lines)} lines; a chart file has at least 14.")]
    fields = (("year", 1, -13000, 17000), ("month", 2, 1, 12), ("day", 3, 1, 31),
              ("hour", 4, 0, 23), ("minute", 5, 0, 59), ("second", 6, 0, 60))
    for label, i, low, high in fields:
        text = lines[i].strip()
        try:
            value = float(text)
        except ValueError:
            out.append(finding("chtk_bad_field", "error",
                               f"Line {i + 1} ({label}) is {text!r}, not a number.", line=i + 1))
            continue
        if not low <= value <= high:
            out.append(finding("chtk_bad_field", "error",
                               f"Line {i + 1} ({label}) is {text}, outside {low} to {high}.",
                               line=i + 1))
    flag = lines[13].strip()
    if flag not in ("-1", "0", "1", "2"):  # 2 = war time / double summer time
        gender = lines[7]
        why = (" The gender line holds extra characters, which pushed the lines below it down."
               if len(gender.strip()) > 1 else "")
        out.append(finding("chtk_line_shift", "error",
                           f"Line 14 (DST flag) is {flag!r}, not -1, 0, 1 or 2.{why}"))
    offset = lines[12].strip()
    if not normalize_chtk_timezone(offset)[1]:  # the reader's own test
        out.append(finding("chtk_bad_offset", "error",
                           f"Line 13 (timezone) is {offset!r}, not an offset such as 05:00:00; "
                           "the app reads the chart at UTC+0."))
    return out


# ---------------------------------------------------------------- timezone
_ZONES: Dict[tuple, Optional[str]] = {}


def zone_at(lat: float, lon: float) -> Optional[str]:
    key = (round(lat, 3), round(lon, 3))
    if key not in _ZONES:
        from core import tz_finder
        try:
            _ZONES[key] = tz_finder.timezone_at(lat, lon)
        except Exception:  # noqa: BLE001 - no finder: no zone check
            _ZONES[key] = None
    return _ZONES[key]


def true_offsets(zone: str, local: tuple, dst_hint: bool) -> Optional[tuple]:
    """(total, standard) hours the zone used at this local time; for a time
    that happens twice (or never), the reading the chart's DST flag points to."""
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(zone)
        naive = datetime(*local[:5])
    except Exception:  # noqa: BLE001 - unknown zone or date outside datetime
        return None
    best = None
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        total = aware.utcoffset().total_seconds() / 3600.0
        dst = (aware.dst() or timedelta(0)).total_seconds() / 3600.0
        pick = (total, total - dst)
        if best is None or bool(dst) == dst_hint:
            best = pick
    return best


def _near(a: float, b: float, tol: float = 1 / 120) -> bool:
    return abs(a - b) <= tol


def timezone_findings(f: dict) -> List[dict]:
    """The timezone rules, on one chart's facts (local, lat, lon, base, dst)."""
    year = f["local"][0]
    if year < ZONE_CHECK_FROM:
        return []
    zone = zone_at(f["lat"], f["lon"])
    if not zone or zone in ("UTC", "Etc/UTC"):
        return []
    base, dst = f["base"], f["dst"]
    stored = base + dst
    truth = true_offsets(zone, f["local"], dst > 0)
    if truth is None:
        return []
    total, standard = truth
    if _near(stored, total, 1 / 60):
        return []
    level = "warning" if year >= RELIABLE_FROM else "check"
    said = f"The file says {_hours(stored)}; {zone} used {_hours(total)} on that date."
    if abs(stored - total) < 0.9:
        if year < RELIABLE_FROM:
            return []  # minutes only, before 1970: zone history too uncertain
        return [finding("offset_minutes", "warning", said, zone=zone,
                        stored=stored, true=total)]
    common = {"zone": zone, "stored": stored, "true": total}
    if _near(base, 0) and _near(dst, 0):
        return [finding("unset_offset", level,
                        "The offset is 00:00:00 with no DST: the timezone was "
                        f"probably never set. {zone} used {_hours(total)} on that date.",
                        **common)]
    for label, lat, lon, since, wrong in KALA_ATLAS_ERRORS:
        if abs(f["lat"] - lat) < 0.5 and abs(f["lon"] - lon) < 0.5 \
                and tuple(f["local"][:3]) >= since and _near(base, wrong):
            return [finding("kala_atlas", "warning",
                            f"Kala's atlas files {label} in the wrong zone. {said}",
                            place=label, **common)]
    if _near(base, standard):
        state = "in force" if total > standard else "not in force"
        return [finding("dst_flag_wrong", level,
                        f"The zone is right but the DST flag is wrong: daylight saving "
                        f"was {state} on that date. {said}", **common)]
    if dst > 0 and _near(base, standard + dst):
        return [finding("dst_baked", level,
                        "The DST hour is already inside the stored offset and the DST "
                        f"flag adds it a second time. {said}", **common)]
    if not _near(standard, 0) and _near(base, -standard):
        return [finding("offset_sign", level,
                        "The offset has the wrong sign (east and west swapped): the file "
                        f"has {_hours(base)}, {zone} had {_hours(standard)}. {said}", **common)]
    if not _near(base % 1, 0) and _near(base, standard - 1):
        return [finding("offset_floor", level,
                        "A half-hour offset was rounded one hour too far west. "
                        f"{said}", **common)]
    return [finding("base_zone_wrong", level,
                    f"The standard offset is not this place's: the file has "
                    f"{_hours(base)}, {zone} had {_hours(standard)}. {said}", **common)]


# ---------------------------------------------------------------- one file
def read_facts(path: Path, root: Path) -> dict:
    """What the checks need from one chart, read through the app's loader."""
    from core.chart_loading import load_birth_data_and_jd
    from core.toml_chart import TOMLChartWriter
    rel = path.relative_to(root).as_posix()
    facts = {"rel": rel, "ext": path.suffix.lower()}
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        bd, jd = load_birth_data_and_jd(str(path), canonicalize=False)
    lat, lon = float(bd["latitude"]), float(bd["longitude"])
    base, dst = TOMLChartWriter._recover_offsets(bd)
    lib = ((bd.get("_toml_extra") or {}).get("_top") or {}).get("library") or {}
    facts.update(
        name=(bd.get("name") or "").strip(), jd=float(jd), lat=lat, lon=lon,
        asc=_ascendant(jd, lat, lon),
        local=[int(bd.get(k) or 0) for k in ("local_year", "local_month", "local_day",
                                             "local_hour", "local_minute")],
        base=float(base), dst=float(dst or 0.0),
        offset=round(float(base) + float(dst or 0.0), 6),
        sources=list(lib.get("sources") or []),
        gender=bd.get("gender") or "",
        place=", ".join(str(bd.get(k)).strip() for k in ("city", "country")
                        if str(bd.get(k) or "").strip()),
        notes=(bd.get("notes") or "").strip())
    return facts


def check_file(path: Path, root: Path) -> tuple:
    """(facts or None, findings) for one chart file."""
    out = []
    if path.suffix.lower() == ".chtk":
        try:
            out += chtk_structure(path)
        except Exception as exc:  # noqa: BLE001
            out.append(finding("unreadable", "error", f"The file cannot be read: {exc}"))
            return None, out
    try:
        facts = read_facts(path, root)
    except Exception as exc:  # noqa: BLE001 - the app itself cannot open it
        if not any(f["level"] == "error" for f in out):
            out.append(finding("unreadable", "error", f"The app cannot open this chart: {exc}"))
        return None, out
    if _near(facts["lat"], 0, 1e-6) and _near(facts["lon"], 0, 1e-6):
        out.append(finding("no_coordinates", "warning",
                           "Latitude and longitude are both 0: the place was never set."))
    else:
        out += timezone_findings(facts)
    if _MOJIBAKE.search(facts["name"]) and names.repair(facts["name"]) != facts["name"]:
        out.append(finding("mojibake_name", "info",
                           f"The name has broken accents; it should read "
                           f"{names.repair(facts['name'])!r}."))
    return facts, out


# ---------------------------------------------------------------- across files
def _timezone_conflict(a: dict, b: dict) -> bool:
    """The merge rule (same local time, another offset or place; or a whole-hour
    gap), kept to charts less than a day apart with different offsets when the
    local times differ: same offset and place at another hour is a birth-time
    question (rectification), and another date is not a timezone."""
    if abs(a["jd"] - b["jd"]) > 1.0 or not _tz_conflict(a, b):
        return False
    return a["local"] == b["local"] or not _near(a["offset"], b["offset"], 1e-6)


def group_findings(rows: List[dict]) -> List[dict]:
    """Rules across charts of the same person or event."""
    out = []
    by_name = defaultdict(list)
    for r in rows:
        key = names.normalise(r["name"])
        if key:
            by_name[key].append(r)
    for key, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        days = defaultdict(list)
        for r in group:
            days[tuple(r["local"][:3])].append(r)
        conflict_rels = set()
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if _timezone_conflict(a, b):
                    conflict_rels |= {a["rel"], b["rel"]}
                    out.append(finding(
                        "timezone_conflict", "warning",
                        f"Two charts of {a['name']!r} disagree on the timezone: "
                        f"{_hours(a['offset'])} and {_hours(b['offset'])}. One of them is wrong.",
                        files=[a["rel"], b["rel"]]))
        if len(days) > 1:
            out.append(finding(
                "different_dates", "info",
                f"{group[0]['name']!r} has {len(days)} different birth dates: "
                f"{', '.join(f'{d[0]}-{d[1]:02d}-{d[2]:02d}' for d in sorted(days))}.",
                files=sorted(r["rel"] for r in group)))
        for day, same in sorted(days.items()):
            same = [r for r in same if r["rel"] not in conflict_rels and r.get("asc") is not None]
            ascs = sorted({round(r["asc"], 1) for r in same})
            if len(same) > 1 and any(_asc_gap(same[0], r) > ASC_LIMIT for r in same[1:]):
                out.append(finding(
                    "rectification", "info",
                    f"{same[0]['name']!r} has {len(same)} charts on the same day with "
                    f"different birth times (Ascendants {', '.join(f'{a:.1f}°' for a in ascs)}).",
                    files=sorted(r["rel"] for r in same)))
    by_moment = defaultdict(list)
    for r in rows:
        by_moment[moment_key(r)].append(r)
    for _key, group in by_moment.items():
        if len(group) < 2:
            continue
        unrelated = [r for r in group[1:] if not names.compatible(group[0]["name"], r["name"])]
        if unrelated:
            out.append(finding(
                "same_moment", "info",
                "These charts share one birth moment and place but have unrelated names: "
                + ", ".join(repr(r["name"]) for r in [group[0]] + unrelated) + ".",
                files=sorted(r["rel"] for r in [group[0]] + unrelated)))
    return out


# ---------------------------------------------------------------- the run
def _skipped(rel: str) -> bool:
    """Hidden folders (``.library``), trash and Kala's own backup folders."""
    parts = rel.split("/")[:-1]
    return any(p.startswith(".") or p.lower() in ("trash", "chtk backup") for p in parts)


def run(root: Path, progress: Optional[Callable[[int, int], None]] = None,
        cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Check every chart under ``root``. ``progress(done, total)`` after each
    file; ``cancelled()`` stops the run (the result says ``cancelled``)."""
    root = Path(root)
    paths = [p for p in chart_files(root) if not _skipped(p.relative_to(root).as_posix())]
    files, rows, done = [], [], 0
    for i, path in enumerate(paths):
        if cancelled():
            break
        facts, found = check_file(path, root)
        rel = path.relative_to(root).as_posix()
        if facts:
            rows.append(facts)
        if found:
            files.append({"rel": rel, "name": facts["name"] if facts else path.stem,
                          "sources": facts["sources"] if facts else [],
                          "findings": found})
        done = i + 1
        if progress:
            progress(i + 1, len(paths))
    groups = [] if cancelled() else group_findings(rows)
    counts = defaultdict(int)
    for f in files:
        for x in f["findings"]:
            counts[x["code"]] += 1
    for g in groups:
        counts[g["code"]] += 1
    return {"root": str(root), "when": datetime.now().isoformat(timespec="seconds"),
            "checked": done, "readable": len(rows),
            "files_total": len(paths), "cancelled": cancelled(),
            "counts": dict(sorted(counts.items())), "files": files, "groups": groups}


# ---------------------------------------------------------------- saving
TITLES = {
    "unreadable": "Charts the app cannot open",
    "chtk_truncated": "Cut-off chart files",
    "chtk_bad_field": "Date or time lines out of range",
    "chtk_line_shift": "Shifted lines (DST flag line holds something else)",
    "chtk_bad_offset": "Timezone line that is not an offset",
    "unset_offset": "Timezone never set (00:00:00)",
    "kala_atlas": "Places Kala's atlas gets wrong",
    "dst_flag_wrong": "DST flag wrong for the date",
    "dst_baked": "DST hour counted twice",
    "offset_sign": "Offset with the wrong sign",
    "offset_floor": "Half-hour offset one hour off",
    "base_zone_wrong": "Wrong standard offset for the place",
    "offset_minutes": "Offset a few minutes off",
    "no_coordinates": "Place never set (0, 0)",
    "mojibake_name": "Broken accents in the name",
    "timezone_conflict": "Copies that disagree on the timezone",
    "rectification": "Same day, different birth times",
    "different_dates": "Same name, different birth dates",
    "same_moment": "Same moment, unrelated names",
    "ai_local": "Found by the local model (check by hand)",
}


def report_lines(result: dict) -> List[str]:
    """The plain report, grouped by finding, most serious first."""
    lines = [f"# Chart check, {result['when'][:16].replace('T', ' ')}", "",
             f"Folder: {result['root']}", "", f"Charts checked: {result['checked']} "
             f"of {result['files_total']}" + (" (stopped before the end)" if result["cancelled"]
                                              else ""), ""]
    items = defaultdict(list)
    for f in result["files"]:
        for x in f["findings"]:
            src = f" (from {f['sources'][0]})" if f.get("sources") else ""
            items[(x["level"], x["code"])].append((f["rel"] + src, x["message"]))
    for g in result["groups"]:
        items[(g["level"], g["code"])].append((" + ".join(g["files"]), g["message"]))
    if not items:
        lines += ["No problem found.", ""]
    for level in LEVELS:
        for (lv, code), rows in sorted(items.items()):
            if lv != level:
                continue
            lines += [f"## {TITLES.get(code, code)} ({len(rows)}, {level})", ""]
            lines += [f"- {rel}: {msg}" for rel, msg in sorted(rows)]
            lines.append("")
    lines += ["Levels: error = the file is damaged; warning = the timezone is wrong for "
              "the date; check = the same before 1970, where the check itself can be wrong "
              "for a city that changed zone, so look by hand; info = worth knowing.", ""]
    return lines


def save(result: dict, library_root: Path) -> Path:
    """Write ``.library/checks/<stamp>.json``, ``latest.json`` and ``REPORT.md``
    (owner only: the report names private charts). Returns the report path."""
    import json
    from core.library import admin
    folder = admin.folder(Path(library_root), "checks")
    stamp = result["when"].replace(":", "").replace("-", "")
    text = json.dumps(result, ensure_ascii=False, indent=1)
    admin.write_text(folder / f"{stamp}.json", text)
    admin.write_text(folder / "latest.json", text)
    report = folder / "REPORT.md"
    admin.write_text(report, "\n".join(report_lines(result)))
    return report


def latest(library_root: Path) -> Optional[dict]:
    from core.library import admin
    return admin.read_json(Path(library_root) / admin.ADMIN / "checks" / "latest.json", None)


def summary(result: dict) -> List[tuple]:
    """(level, title, count) per finding kind, most serious first."""
    level_of = {}
    for f in result["files"]:
        for x in f["findings"]:
            level_of[x["code"]] = x["level"]
    for g in result["groups"]:
        level_of[g["code"]] = g["level"]
    rows = [(level_of.get(c, "check"), TITLES.get(c, c), n)
            for c, n in result["counts"].items() if n]
    return sorted(rows, key=lambda r: (LEVELS.index(r[0]), -r[2], r[1]))
