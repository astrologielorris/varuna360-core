# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``plan`` (INV-6): the complete list of records and target paths, written to
``.library/plans/<date>.json``. No library chart is written."""
import json
import os
from pathlib import Path
from typing import Iterable, Optional

from core.library import admin, layout, merge
from core.library.folder_map import FolderMap
from core.library.names import clear_name, clear_section

PLAN_VERSION = 1


class PlanError(ValueError):
    """The source and library folders overlap, or the plan file is unusable."""


def check_roots(source: Path, library_root: Path) -> None:
    """INV-1: the library may not sit inside the source, nor the reverse."""
    s, lib = Path(source).resolve(), Path(library_root).resolve()
    if s == lib or s in lib.parents or lib in s.parents:
        raise PlanError(f"library folder and source folder overlap: {lib} / {s}")


def _skip_reason(row: dict, fmap: FolderMap, verdicts: dict) -> Optional[str]:
    if "error" in row:
        return "unreadable"
    override = (verdicts.get("class") or {}).get(row["rel"]) or {}
    placement = fmap.place(row["folder"])
    cls = override.get("class") or placement.cls
    if cls != "skip":
        return None
    section = (override.get("section") or placement.section or "").lower()
    return "test" if "test" in section else "trash"


def library_table(rec: dict, date: str) -> dict:
    """The ``[library]`` table of one record (§3.2): facts only."""
    public = rec["privacy"] == "public"
    table = {"id": rec["id"], "kind": rec["kind"], "privacy": rec["privacy"],
             "section": clear_section(rec.get("section"))}
    if rec["tags"]:
        table["tags"] = rec["tags"]
    aliases = rec["aliases_public"] if public else []
    if aliases:
        table["aliases"] = aliases
    table["variant"] = rec["variant"]
    table["copies"] = rec["copies"]
    if rec["sources_public"]:
        table["sources"] = rec["sources_public"]
    table["migrated"] = date
    table["first_seen"] = rec.get("first_seen") or date
    table["origin"] = rec["origin"]
    return table


def _reuse_identities(records: list, manifest: dict, review: dict) -> None:
    """A record whose sources were migrated before keeps that record's id and
    path (§3.2: the id is stable), so an edited library file is found again and
    never duplicated (INV-7). Sources now split across records, or several old
    records now merged, are listed for review; the largest overlap keeps the id."""
    owner = {rel: rid for rid, row in manifest.items() for rel in row.get("sources_all", [])}
    claims = {}
    for rec in records:
        old = [owner[rel] for rel in rec["sources_all"] if rel in owner]
        if not old:
            continue
        best = max(set(old), key=lambda rid: (old.count(rid), rid))
        claims.setdefault(best, []).append((old.count(best), rec))
        if len(set(old)) > 1:
            review.setdefault("regrouped", []).append({"id": best, "merged": sorted(set(old))})
    taken = {r["path"].lower() for r in records}
    renamed = {}
    for rid, recs in claims.items():
        recs.sort(key=lambda x: -x[0])
        rec = recs[0][1]
        if rec["id"] != rid:
            renamed[rec["id"]], rec["id"] = rid, rid
        old_path = manifest[rid].get("path")
        same_side = old_path and old_path.split("/", 1)[0] == rec["path"].split("/", 1)[0]
        if same_side and old_path != rec["path"] and old_path.lower() not in taken:
            taken.discard(rec["path"].lower())
            rec["path"], rec["folder"] = old_path, old_path.rsplit("/", 1)[0]
            taken.add(old_path.lower())
        for _n, other in recs[1:]:
            review.setdefault("regrouped", []).append({"id": rid, "split": other["id"]})
    for r in records:  # a subject id follows its primary's id
        r["subject"] = renamed.get(r["subject"], r["subject"])
    for ids in review.get("different_dates", []):
        ids[:] = [renamed.get(i, i) for i in ids]
    for item in review.get("variants", []):
        item["subject"] = renamed.get(item["subject"], item["subject"])
    for item in review.get("rating_conflict", []):
        item["id"] = renamed.get(item["id"], item["id"])


def build(rows: Iterable[dict], fmap: FolderMap, verdicts: dict, *, date: str,
          source: Path, library_root: Path, first_seen: Optional[dict] = None,
          manifest: Optional[dict] = None) -> dict:
    """The plan document from survey rows."""
    rows = list(rows)
    skips, keep = [], []
    for row in rows:
        reason = _skip_reason(row, fmap, verdicts)
        if reason:
            skips.append({"rel": row["rel"], "reason": reason, "sha1": row["sha1"],
                          **({"error": row["error"]} if "error" in row else {})})
        else:
            keep.append(row)
    merged = merge.build(keep, fmap, verdicts)
    records = merged["records"]
    layout.assign(records)
    _reuse_identities(records, manifest or {}, merged["review"])
    paths = [r["path"].lower() for r in records]
    if len(paths) != len(set(paths)):
        raise PlanError("two records were given one path")
    for r in records:  # INV-5, checked before anything is written
        if r["privacy"] != "public" and not layout.owner_only(r["path"]):
            raise PlanError(f"record {r['id']} is {r['privacy']} but filed at a public path")
    sha = {r["rel"]: r["sha1"] for r in rows}
    for rec in records:
        if first_seen and rec["id"] in first_seen:
            rec["first_seen"] = first_seen[rec["id"]]
        old = (manifest or {}).get(rec["id"]) or {}
        rec["library"] = library_table(rec, old.get("migrated") or date)
        rec["source_sha1"] = sha[rec["source"]]
    collections = {}
    for rec in records:
        if rec["privacy"] == "public":
            for name in rec["collections"]:
                collections.setdefault(name, []).append(rec["id"])
    files, used = {}, set()
    for name in sorted(collections):
        base = clear_name(name)
        fname, n = f"{base}.json", 2
        while fname.lower() in used:
            fname, n = f"{base} {n}.json", n + 1
        used.add(fname.lower())
        files[name] = fname
    return {"version": PLAN_VERSION, "date": date, "source": str(Path(source).resolve()),
            "library_root": str(Path(library_root).resolve()), "files": len(rows),
            "sources": {r["rel"]: r["sha1"] for r in rows},
            "records": records, "skips": skips, "review": merged["review"],
            "collections": {k: sorted(v) for k, v in sorted(collections.items())},
            "collection_files": files}


def sections(plan: dict) -> dict:
    """Records per section, keyed by the record's section folder path."""
    out = {}
    for rec in plan["records"]:
        key = rec["folder"].rsplit("/", 1)[0]
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def selected(plan: dict, only: str) -> list:
    """Records of one section: ``only`` is a section folder path
    (``Public/People/Actors``) or a section name (``Actors``), any case."""
    want = only.strip("/").lower()
    out = []
    for rec in plan["records"]:
        parent = rec["folder"].rsplit("/", 1)[0].lower()
        name = clear_section(rec.get("section")).lower()
        if parent == want or parent.startswith(want + "/") or name == want:
            out.append(rec)
    return out


def save(plan: dict, library_root: Path) -> Path:
    path = admin.folder(library_root, "plans") / f"{plan['date']}.json"
    admin.write_text(path, json.dumps(plan, ensure_ascii=False, indent=1))
    return path


def load(path: Path) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("version") != PLAN_VERSION:
        raise PlanError(f"unknown plan version in {path}")
    return plan


def latest(library_root: Path) -> Path:
    plans = sorted(admin.folder(library_root, "plans").glob("*.json"))
    if not plans:
        raise PlanError("no plan yet: run `library plan` first")
    return plans[-1]


def plan_date(value: Optional[str] = None) -> str:
    from datetime import date
    return value or os.environ.get("VARUNA_LIBRARY_DATE") or date.today().isoformat()
