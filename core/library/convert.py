# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The conversion contract (§4.3b, D-25): one path from a .chtk or .toml source
to a library .toml that keeps the app's birth moment.

The JD comes from ``load_birth_data_and_jd`` and is passed to the writer as
``julian_day`` (never ``encode``'s Gregorian fallback). Kala fields TOML has no
key for go into ``chtk_source``. Each result is read back through the app's
loading path and checked against the source: JD, coordinates, offsets, notes.
"""
import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

FILE_OWNED = ("library", "rating", "biography")
JD_TOLERANCE = 1e-9  # days


class ConversionMismatch(ValueError):
    """The written chart does not read back as its source."""


def _quiet_load(path):
    from core.chart_loading import load_birth_data_and_jd
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        return load_birth_data_and_jd(str(path), canonicalize=False)


def chtk_source(path: Path) -> Optional[dict]:
    """Kala fields TOML has no key for: line 13 verbatim, the muhurtas, and the
    residence section (the lines after the muhurtas, 20 to 27 in a plain file)."""
    from core.chtk_text import read_chtk_text, split_chtk_lines
    lines = split_chtk_lines(read_chtk_text(path))
    out = {}
    if len(lines) > 12:
        out["line_13"] = lines[12]
    try:
        start = lines.index("~end of notes~") + 1
        end = lines.index("~end of muhurtas~", start)
        muhurtas = [ln for ln in lines[start:end] if ln.strip()]
        if muhurtas:
            out["muhurtas"] = muhurtas
        tail = lines[end + 1:]
    except ValueError:
        tail = lines[19:]
    if any(ln.strip() not in ("", "0") for ln in tail):
        out["residence"] = list(tail)
    return out or None


def source_birth_data(path: Path) -> Tuple[dict, float]:
    """The source chart through the app's loading path, with the JD set."""
    bd, jd = _quiet_load(path)
    bd = dict(bd)
    bd["julian_day"] = float(jd)
    return bd, float(jd)


def encode_library_chart(path: Path, tables: dict, name: Optional[str] = None
                         ) -> Tuple[str, dict, float]:
    """``(text, birth_data, jd)`` of the library .toml for one source file.

    ``tables`` are the top-level tables to set (``library``, optionally
    ``rating``); any old file-owned table of the source is dropped first (D-24).
    ``name`` is the record's display name (the most complete name among its
    copies), written instead of the source's own.
    """
    from core.toml_chart import TOMLChartWriter
    path = Path(path)
    bd, jd = source_birth_data(path)
    if name:
        bd["name"] = name
    extra = {t: dict(v) for t, v in (bd.get("_toml_extra") or {}).items()}
    top = {k: v for k, v in extra.get("_top", {}).items() if k not in FILE_OWNED}
    if path.suffix.lower() == ".chtk":
        kala = chtk_source(path)
        if kala:
            top["chtk_source"] = kala
    ordered = {"library": tables["library"]} if tables.get("library") else {}
    for key in ("rating", "biography"):
        if tables.get(key):
            ordered[key] = tables[key]
    ordered.update(top)
    extra["_top"] = ordered
    bd["_toml_extra"] = extra
    return TOMLChartWriter().encode(bd), bd, jd


def download_to_toml(birth_data: dict, output_dir: Path) -> Optional[Path]:
    """Search Web's download as a ``.toml`` in ``output_dir`` (D-37). The web
    result is written by the canonical CHTK writer in a scratch folder (Rule 6),
    then converted by this contract and checked; the CHTK is not kept. The name
    never overwrites a file: "Name.toml", then "Name 2.toml"."""
    from core.chtk_writer import create_chtk_from_web_data
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v360_web_") as scratch:
        chtk = create_chtk_from_web_data(birth_data, Path(scratch), verbose=False)
        if not chtk:
            return None
        text, bd, jd = encode_library_chart(Path(chtk), {})
        # A download is not a Kala chart: no chtk_source.
        top = (bd.get("_toml_extra") or {}).get("_top") or {}
        if "chtk_source" in top:
            from core.toml_chart import TOMLChartWriter
            top.pop("chtk_source")
            text = TOMLChartWriter().encode(bd)
        check(text, bd, jd, Path(scratch))
        stem = Path(chtk).stem
    for n in range(1, 1000):
        target = output_dir / (f"{stem}.toml" if n == 1 else f"{stem} {n}.toml")
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return target
    return None


def _notes(bd: dict) -> str:
    return (bd.get("notes") or "").strip()


def check(text: str, source_bd: dict, jd: float, scratch_dir: Path) -> None:
    """Read ``text`` back through the app's loading path and compare it with
    the source; raises ConversionMismatch naming the first field that differs."""
    import tomllib
    from core.toml_chart import TOMLChartWriter
    tomllib.loads(text)
    fd, tmp = tempfile.mkstemp(dir=str(scratch_dir), suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        back, back_jd = _quiet_load(tmp)
    finally:
        os.unlink(tmp)
    checks = (
        ("jd", abs(back_jd - jd) <= JD_TOLERANCE),
        ("latitude", float(back["latitude"]) == float(source_bd["latitude"])),
        ("longitude", float(back["longitude"]) == float(source_bd["longitude"])),
        ("offsets", TOMLChartWriter._recover_offsets(back)
         == TOMLChartWriter._recover_offsets(source_bd)),
        ("notes", _notes(back) == _notes(source_bd)),
        ("name", (back.get("name") or "") == (source_bd.get("name") or "")),
    )
    for field, ok in checks:
        if not ok:
            raise ConversionMismatch(field)


BACKUP = "CHTK backup"


def convert_in_place(path: Path, chart_folder: Path) -> Path:
    """CONVERT TO TOML (SPEC-LIB-002 D-15): the ``.toml`` beside the ``.chtk``
    (never over a file), checked by this contract; then the ``.chtk`` moves to
    ``<chart folder>/CHTK backup/`` at the same relative path, never deleted.
    Refused in the old Kala folder (INV-9)."""
    from core.library.paths import is_kala_folder
    path, chart_folder = Path(path), Path(chart_folder)
    if is_kala_folder(chart_folder):
        raise PermissionError("this is Kala's chart folder, kept as a backup")
    rel = path.resolve().relative_to(chart_folder.resolve())
    text, bd, jd = encode_library_chart(path, {})
    check(text, bd, jd, path.parent)
    from core.chart_sort import rename_noreplace
    target = path.with_suffix(".toml")
    backup = chart_folder / BACKUP / rel
    for taken in (backup, target):
        if taken.exists():
            raise FileExistsError(f"{taken} already exists")
    # The .toml is written under a hidden name first, so a refusal below
    # leaves the folder as it was (the scratch file is this call's own).
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".convert-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        backup.parent.mkdir(parents=True, exist_ok=True)
        rename_noreplace(path, backup)   # never over a backup that appeared meanwhile
        try:
            rename_noreplace(Path(tmp), target)
        except BaseException:
            rename_noreplace(backup, path)  # the .chtk goes back where it was
            raise
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return target


def convert_folder(chart_folder: Path, cancelled=lambda: False) -> dict:
    """Every ``.chtk`` under ``chart_folder`` (hidden, trash and backup
    folders left out): ``{"converted": [toml], "failed": [(chtk, why)]}``."""
    chart_folder = Path(chart_folder)
    converted, failed = [], []
    for path in sorted(chart_folder.rglob("*")):
        if cancelled():
            break
        rel = path.relative_to(chart_folder).parts
        if path.suffix.lower() != ".chtk" or not path.is_file() or any(
                p.startswith(".") or p.lower() in ("trash", BACKUP.lower()) for p in rel[:-1]):
            continue
        try:
            converted.append(str(convert_in_place(path, chart_folder)))
        except Exception as exc:  # noqa: BLE001 - one chart does not stop the folder
            failed.append((str(path), str(exc)))
    return {"converted": converted, "failed": failed}
