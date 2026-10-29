# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Read-only survey of a chart folder: one row of facts per chart file (§4.1).

Every file is read through the app's loading path (``load_birth_data_and_jd``,
``canonicalize=False``) and opened read only (INV-1, INV-8). Nothing is written.
"""
import contextlib
import hashlib
import io
import re
from pathlib import Path
from typing import Iterator, Optional

CHART_EXTS = (".chtk", ".toml")
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def chart_files(root: Path) -> list:
    """Every .chtk and .toml file under ``root``, sorted by relative path."""
    root = Path(root)
    return sorted((p for p in root.rglob("*")
                   if p.suffix.lower() in CHART_EXTS and p.is_file()),
                  key=lambda p: p.relative_to(root).as_posix())


def _ascendant(jd: float, lat: float, lon: float) -> Optional[float]:
    try:
        import swisseph as swe
        _, ascmc = swe.houses(jd, lat, lon, b"C")
        return round(float(ascmc[0]), 4)
    except Exception:  # noqa: BLE001 - polar or invalid input: no Ascendant
        return None


def _line8(path: Path) -> str:
    from core.chtk_text import read_chtk_text, split_chtk_lines
    lines = split_chtk_lines(read_chtk_text(path))
    return lines[7].strip() if len(lines) > 7 else ""


def origin(path: Path, rel: str, data: bytes) -> str:
    """``ai-made``, ``varuna-toml``, ``kala-chtk`` or ``unknown`` (§4.5)."""
    parts = rel.split("/")
    stem = Path(rel).stem
    if any(_DATED.match(p) for p in parts[:-1]) or ("_" in stem and " " not in stem):
        return "ai-made"
    if path.suffix.lower() == ".toml":
        return "varuna-toml" if data.lstrip().startswith(b"spec") else "unknown"
    try:
        g = _line8(path)
    except Exception:  # noqa: BLE001
        return "unknown"
    # Varuna360 writes 1 / 2; a letter (alone or with Kala's blob) is Kala's own.
    return "kala-chtk" if g[:1].lower() in ("m", "f") else "unknown"


def survey_file(path: Path, root: Path) -> dict:
    """One survey row; ``error`` is set when the app cannot read the chart."""
    from core.chart_loading import load_birth_data_and_jd
    from core.toml_chart import TOMLChartWriter
    rel = path.relative_to(root).as_posix()
    row = {"rel": rel, "folder": str(Path(rel).parent.as_posix()), "file": path.name,
           "ext": path.suffix.lower(), "sha1": None}
    try:
        data = path.read_bytes()
        stat = path.stat()
        row.update(size=stat.st_size, mtime=int(stat.st_mtime),
                   sha1=hashlib.sha1(data).hexdigest(), origin=origin(path, rel, data))
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            bd, jd = load_birth_data_and_jd(str(path), canonicalize=False)
        lat, lon = float(bd["latitude"]), float(bd["longitude"])
        base, dst = TOMLChartWriter._recover_offsets(bd)
        top = (bd.get("_toml_extra") or {}).get("_top") or {}
        notes = (bd.get("notes") or "").strip()
        row.update(
            name=(bd.get("name") or "").strip(), gender=bd.get("gender") or "",
            jd=float(jd), lat=lat, lon=lon, asc=_ascendant(jd, lat, lon),
            local=[int(bd.get(k) or 0) for k in ("local_year", "local_month", "local_day",
                                                 "local_hour", "local_minute")],
            offset=round(float(base) + float(dst or 0.0), 6),
            notes_len=len(notes))
        if isinstance(top.get("rating"), dict):
            row["rating"] = top["rating"]
    except Exception as exc:  # noqa: BLE001 - any read failure is a skip reason
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def survey(root: Path) -> Iterator[dict]:
    """Survey rows for every chart file under ``root``, in path order."""
    root = Path(root)
    for path in chart_files(root):
        yield survey_file(path, root)


def moment_key(row: dict) -> tuple:
    """This spec's copy key (§2): JD to the minute, lat and lon to 0.1°."""
    return (round(row["jd"] * 1440), round(row["lat"], 1), round(row["lon"], 1))
