# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``verify``: INV-1 (source unchanged), INV-3 (every source file accounted
for), every library chart parses through the app, INV-5 / AC-5 (nothing public
names a private or review record), owner-only permissions."""
import os
import stat
import tomllib
from pathlib import Path

from core.library import admin, convert, layout, survey
from core.library.migrate import expected_collections, fields_sha, source_hashes
from core.library.plan import selected
from core.library.privacy import effective_privacy


def verify(plan: dict, only: str = "") -> dict:
    source, root = Path(plan["source"]), Path(plan["library_root"])
    problems = []
    # INV-1
    now = source_hashes(source, plan["sources"])
    changed = [rel for rel, sha in plan["sources"].items() if now.get(rel) != sha]
    if changed:
        problems.append({"check": "INV-1 source unchanged", "files": len(changed)})
    current = {p.relative_to(source).as_posix() for p in survey.chart_files(source)}
    new = sorted(current - set(plan["sources"]))
    if new:
        problems.append({"check": "INV-3 source files not in the plan", "files": len(new)})
    # INV-3
    records = selected(plan, only) if only else plan["records"]
    if only and not records:
        problems.append({"check": "section", "error": f"no record in section {only!r}"})
    accounted = [rel for r in plan["records"] for rel in r["sources_all"]]
    accounted += [s["rel"] for s in plan["skips"]]
    if sorted(accounted) != sorted(plan["sources"]):
        problems.append({"check": "INV-3 reconciliation", "sources": len(plan["sources"]),
                         "accounted": len(accounted)})
    # charts on disk
    public_ids = {r["id"] for r in plan["records"] if r["privacy"] == "public"}
    present, missing = 0, 0
    file_public = set()
    for rec in records:
        path = root / rec["path"]
        if not path.exists():
            missing += 1
            problems.append({"check": "AC-2 chart missing", "id": rec["id"]})
            continue
        present += 1
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
            convert._quiet_load(path)
        except Exception as exc:  # noqa: BLE001
            problems.append({"check": "parses", "id": rec["id"], "error": str(exc)})
            continue
        lib = doc.get("library") or {}
        level = effective_privacy({"rating": doc.get("rating"), "library": lib})
        if level == "public":
            file_public.add(rec["id"])
        elif not layout.owner_only(rec["path"]):
            problems.append({"check": "INV-5 the chart's rating is not public",
                             "id": rec["id"]})
        if lib.get("id") != rec["id"]:
            problems.append({"check": "library id", "id": rec["id"]})
        if layout.owner_only(rec["path"]):
            if stat.S_IMODE(path.stat().st_mode) & 0o077:
                problems.append({"check": "owner-only file", "id": rec["id"]})
        elif rec["privacy"] != "public":
            problems.append({"check": "INV-5 private outside Private/Review", "id": rec["id"]})
        else:
            if not set(lib.get("aliases", [])) <= set(rec["aliases_public"]) or \
                    not set(lib.get("sources", [])) <= set(rec["sources_public"]):
                problems.append({"check": "AC-5 alias or path from a private folder",
                                 "id": rec["id"]})
    manifest = admin.read_manifest(root)
    for rec in records:  # a skipped edit, a held move or a stale row is not done
        row, path = manifest.get(rec["id"]), root / rec["path"]
        if not path.exists():
            continue
        if not row or row.get("path") != rec["path"] \
                or sorted(row.get("sources_all") or []) != sorted(rec["sources_all"]) \
                or row.get("source_sha1") != rec["source_sha1"]:
            problems.append({"check": "manifest matches the plan", "id": rec["id"]})
            continue
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue  # reported by the parse check below
        if doc.get("library") != rec["library"]:
            problems.append({"check": "[library] matches the plan", "id": rec["id"]})
        elif row.get("written_sha") != fields_sha(doc):
            problems.append({"check": "INV-7 edited since migration (skipped)",
                             "id": rec["id"]})
    wanted = expected_collections(plan, manifest)
    folder = root / "Collections"
    have = {p.name for p in folder.glob("*.json")} if folder.exists() else set()
    if only:  # a section checks the collections its records belong to
        ids = {r["id"] for r in records}
        files = plan.get("collection_files") or {}
        mine = {files.get(n) for n, members in plan["collections"].items()
                if ids & set(members)}
        mine = {f for f in mine if f and (f in wanted)}
        have, wanted = have & mine, {f: wanted[f] for f in mine}
    for fname in sorted(have | set(wanted)):
        if fname not in wanted or fname not in have or \
                admin.read_json(folder / fname, {}) != wanted[fname]:
            problems.append({"check": "collection matches the plan", "file": fname})
    by_path_checked = {r["id"] for r in records if (root / r["path"]).exists()}
    for top in layout.OWNER_ONLY_TOPS:
        for dirpath, _dirs, _files in os.walk(root / top):
            if stat.S_IMODE(os.stat(dirpath).st_mode) & 0o077:
                problems.append({"check": "owner-only folder", "folder": top})
                break
    for coll in (root / "Collections").glob("*.json") if (root / "Collections").exists() else ():
        doc = admin.read_json(coll, {})
        for m in doc.get("records", []):
            if m.get("id") not in public_ids or (m["id"] in by_path_checked
                                                    and m["id"] not in file_public):
                problems.append({"check": "AC-5 collection", "collection": coll.name})
    return {"ok": not problems, "checked": present, "not_migrated": missing,
            "problems": problems}
