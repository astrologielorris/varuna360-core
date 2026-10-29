# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``migrate --only <section>`` (INV-6): execute one section of a saved plan.

The source folder is only read (INV-1, hashed before and after). Each chart is
converted through the conversion contract and checked against its source. A
library file whose chart fields or ``[library]`` changed since the plan is an
edit by the user: skipped and reported, nothing written beside it (INV-7).
"""
import hashlib
import json
import os
import time
import tomllib
from pathlib import Path
from typing import Iterable, Optional

from core.library import admin, convert, layout
from core.library.privacy import effective_privacy
from core.library.names import clear_name
from core.library.plan import check_roots, selected

CHART_FIELDS = ("name", "moment", "location", "civil", "library")


class MigrationError(RuntimeError):
    """The source folder changed during the run, or the plan cannot be applied."""


def source_hashes(source: Path, rels: Iterable[str]) -> dict:
    out = {}
    for rel in rels:
        try:
            out[rel] = hashlib.sha1((Path(source) / rel).read_bytes()).hexdigest()
        except OSError:
            out[rel] = None
    return out


def _fields(doc: dict) -> dict:
    return {k: doc.get(k) for k in CHART_FIELDS}


def _write_chart(path: Path, text: str, owner_only: bool) -> None:
    admin.ensure_dir(path.parent, owner_only)
    admin.write_text(path, text, 0o600 if owner_only else 0o644)


def _owner_only_tops(library_root: Path) -> None:
    for top in layout.OWNER_ONLY_TOPS:
        p = Path(library_root) / top
        if p.exists():
            os.chmod(p, 0o700)


def migrate(plan: dict, only: str) -> dict:
    """Write one section of ``plan``; returns the run summary."""
    source, library_root = Path(plan["source"]), Path(plan["library_root"])
    check_roots(source, library_root)
    records = selected(plan, only)
    if not records:
        raise MigrationError(f"no record in section {only!r}")
    rels = sorted({rel for r in records for rel in r["sources_all"]})
    before = source_hashes(source, rels)
    stale = [rel for rel in rels if before[rel] != plan["sources"].get(rel)]
    if stale:
        raise MigrationError(f"{len(stale)} source file(s) changed since the plan: "
                             "run `library plan` again")
    scratch = admin.folder(library_root, "cache")
    summary = {"plan": plan["date"], "section": only, "records": len(records),
               "written": [], "updated": [], "unchanged": [], "edited": [], "held": [],
               "failed": []}
    manifest = admin.read_manifest(library_root)
    for rec in records:
        try:
            outcome = _migrate_one(rec, source, library_root, scratch, manifest)
        except Exception as exc:  # noqa: BLE001 - recorded per record, source kept
            outcome = ("failed", str(exc) or type(exc).__name__)
        kind, reason = outcome
        if kind == "failed":
            summary["failed"].append({"id": rec["id"], "reason": reason})
            continue
        summary.setdefault(kind, []).append(rec["id"])
        if reason:
            summary.setdefault(f"{kind}_reasons", {})[rec["id"]] = reason
    _owner_only_tops(library_root)
    after = source_hashes(source, rels)
    if after != before:
        raise MigrationError("the source folder changed during the run")
    admin.write_manifest(library_root, manifest.values())
    _write_collections(plan, manifest)
    _write_library_json(library_root, plan, manifest)
    log = admin.folder(library_root, "logs") / time.strftime("%Y%m%d-%H%M%S-migrate.json")
    admin.write_text(log, json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def fields_sha(doc: dict) -> str:
    """Fingerprint of the chart fields and ``[library]`` as written (INV-7)."""
    blob = json.dumps(_fields(doc), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _encode(rec: dict, source: Path, scratch: Path, keep: dict) -> str:
    """The planned chart text; ``keep`` holds the disk's rating and biography."""
    tables = {"library": rec["library"]}
    rating = keep.get("rating") or rec.get("rating")
    if rating:
        tables["rating"] = rating
    if keep.get("biography"):
        tables["biography"] = keep["biography"]
    text, bd, jd = convert.encode_library_chart(source / rec["source"], tables, rec["name"])
    convert.check(text, bd, jd, scratch)
    return text


def _relocate(rec: dict, root: Path, manifest: dict) -> Optional[tuple]:
    """A record whose planned path changed brings its old file along only into
    owner-only storage (a privacy upgrade), only when the new place is free and
    the old file reads as a chart. Any other move (out of Private/ or Review/,
    onto an occupied place, a damaged file) is held: nothing moves, the run
    fails and the report lists it. ``None`` when there is nothing to move."""
    old_rel = (manifest.get(rec["id"]) or {}).get("path")
    if not old_rel or old_rel == rec["path"] or not (root / old_rel).exists():
        return None
    old, new = root / old_rel, root / rec["path"]
    if not layout.owner_only(rec["path"]):
        return ("held", f"would move {old_rel} out of owner-only storage or across"
                        " public folders: file it from Rate and Sort")
    problem = None
    if new.exists():
        problem = f"{rec['path']} is taken"
    else:
        try:
            tomllib.loads(old.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            problem = f"unreadable ({exc})"
    if problem:
        if not layout.owner_only(old_rel):  # never leave a now-private chart public
            held = admin.folder(root, "held") / old_rel
            n = 2
            while held.exists():  # never replace an earlier held copy
                held = held.with_name(f"{Path(old_rel).stem} (held {n}).toml")
                n += 1
            admin.ensure_dir(held.parent, True)
            os.replace(old, held)
            os.chmod(held, 0o600)
            return ("held", f"cannot move {old_rel}: {problem}; kept owner-only at "
                            f"{held.relative_to(root).as_posix()}")
        return ("held", f"cannot move {old_rel}: {problem}")
    admin.ensure_dir(new.parent, True)
    os.replace(old, new)
    os.chmod(new, 0o600)
    return ("moved", f"moved from {old_rel}")


def _migrate_one(rec: dict, source: Path, root: Path, scratch: Path, manifest: dict):
    """``(outcome, reason)``: written, updated, unchanged, edited, held or failed."""
    move = _relocate(rec, root, manifest)
    if move and move[0] == "held":
        return move
    moved = move[1] if move else None
    target = root / rec["path"]
    if not target.exists():
        text = _encode(rec, source, scratch, {})
        _write_chart(target, text, layout.owner_only(rec["path"]))
        manifest[rec["id"]] = _manifest_row(rec, manifest.get(rec["id"]), text)
        return "written", moved
    try:
        on_disk = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return "edited", f"unreadable: {exc}"
    keep = {k: on_disk[k] for k in ("rating", "biography") if isinstance(on_disk.get(k), dict)}
    if not layout.owner_only(rec["path"]) and keep.get("rating") and effective_privacy(
            {"rating": keep["rating"], "privacy": rec["privacy"]}) != "public":
        return "held", "the chart's own rating is not public: not rewritten at a public path"
    text = _encode(rec, source, scratch, keep)
    planned = tomllib.loads(text)
    if _fields(on_disk) == _fields(planned):
        manifest[rec["id"]] = _manifest_row(rec, manifest.get(rec["id"]), text)
        return "unchanged", moved
    written = (manifest.get(rec["id"]) or {}).get("written_sha")
    if written != fields_sha(on_disk):
        return "edited", moved or "chart fields or [library] changed since migration"
    _write_chart(target, text, layout.owner_only(rec["path"]))
    manifest[rec["id"]] = _manifest_row(rec, manifest.get(rec["id"]), text)
    return "updated", moved or "new copies or sources from the plan"


def _manifest_row(rec: dict, old, text: str) -> dict:
    keep = ("id", "subject", "name", "kind", "privacy", "cls", "section", "variant",
            "copies", "path", "source", "sources_all", "aliases_all", "collections",
            "origin", "name_rules", "oldest_source_mtime", "notes_differ", "asc", "local")
    row = {k: rec.get(k) for k in keep}
    row["first_seen"] = (old or {}).get("first_seen") or rec["library"]["first_seen"]
    row["migrated"] = rec["library"]["migrated"]
    row["written_sha"] = fields_sha(tomllib.loads(text))
    row["source_sha1"] = rec["source_sha1"]  # the source this chart was converted from
    if rec.get("rating"):
        row["rating"] = rec["rating"]
    return row


def expected_collections(plan: dict, manifest: dict) -> dict:
    """``{file name: document}``: each planned collection's migrated public
    records (ids and display names)."""
    files = plan.get("collection_files") or {}
    wanted = {}
    for name, ids in plan["collections"].items():
        members = [{"id": i, "name": manifest[i]["name"]} for i in ids
                   if i in manifest and manifest[i]["privacy"] == "public"]
        if members:
            fname = files.get(name) or f"{clear_name(name)}.json"
            wanted[fname] = {"collection": name, "records": members}
    return wanted


def _write_collections(plan: dict, manifest: dict) -> None:
    """Rebuild Collections/ from the plan. A collection file the plan no longer
    has goes to .library/trash, so a record that became private leaves every
    collection."""
    root = Path(plan["library_root"])
    wanted = expected_collections(plan, manifest)
    folder = root / "Collections"
    if folder.exists():
        for old in folder.glob("*.json"):
            if old.name not in wanted:
                dest = admin.folder(root, "trash") / time.strftime("%Y%m%d-%H%M%S") / \
                    "Collections"
                admin.ensure_dir(dest, True)
                os.replace(old, dest / old.name)
    if wanted:
        admin.ensure_dir(folder, False)
    for fname, doc in wanted.items():
        admin.write_text(folder / fname, json.dumps(doc, ensure_ascii=False, indent=1), 0o644)


def _write_library_json(root: Path, plan: dict, manifest: dict) -> None:
    counts = {}
    for row in manifest.values():
        counts[row["privacy"]] = counts.get(row["privacy"], 0) + 1
    old = admin.read_json(root / "LIBRARY.json", {})
    doc = {"layout_version": 1, "created": old.get("created") or plan["date"],
           "records": len(manifest), "by_privacy": dict(sorted(counts.items()))}
    admin.write_text(root / "LIBRARY.json", json.dumps(doc, indent=1), 0o644)
