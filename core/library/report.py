# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``report`` (§4.7): ``.library/logs/<run>/REPORT.md``. It names private
people, so it is written only inside ``.library/`` (0600)."""
import time
from collections import Counter
from pathlib import Path

from core.library import admin
from core.library.names import clear_section
from core.library.plan import sections, selected


def summary(plan: dict, only: str = "") -> dict:
    records = selected(plan, only) if only else plan["records"]
    if only:
        files = accounted = sum(len(r["sources_all"]) for r in records)
    else:
        files = plan["files"]
        accounted = sum(len(r["sources_all"]) for r in plan["records"]) + len(plan["skips"])
    return {
        "source_files": files, "accounted": accounted,
        "reconciled": bool(records) and accounted == files,
        "records": len(records),
        "by_privacy": dict(Counter(r["privacy"] for r in records)),
        "by_kind": dict(Counter(r["kind"] for r in records)),
        "files_merged": sum(r["copies"] - 1 for r in records),
        "variants": sum(1 for r in records if r["variant"] > 1),
        "skips": dict(Counter(s["reason"] for s in plan["skips"])),
        "sections": sections(plan) if not only else {},
        "review": {k: len(v) for k, v in plan["review"].items()},
        "origin": dict(Counter(r["origin"] for r in records)),
    }


def _keep(key: str, item, ids: set, rels: set) -> bool:
    """Whether a review item touches the selected records."""
    if key in ("same_moment", "cross_class", "no_ascendant"):
        return bool(set(item) & rels)
    if key == "timezone_conflict":
        return any(x["rel"] in rels for x in item)
    if key == "different_dates":
        return bool(set(item) & ids)
    if key == "variants":
        return item["subject"] in ids
    return item.get("id") in ids


def migration_results(plan: dict, only: str = "") -> dict:
    """Edited files skipped (INV-7) and conversion failures, from the migrate
    logs of this plan."""
    logs = admin.folder(Path(plan["library_root"]), "logs")
    edited, failed = {}, {}
    for log in sorted(logs.glob("*-migrate.json")):
        run = admin.read_json(log, {})
        if run.get("plan") != plan["date"]:
            continue
        reasons = run.get("edited_reasons") or {}
        for rid in run.get("edited", []):
            edited[rid] = reasons.get(rid, "chart fields or [library] changed")
        for rid in run.get("written", []) + run.get("unchanged", []):
            edited.pop(rid, None)
            failed.pop(rid, None)
        for f in run.get("failed", []):
            failed[f["id"]] = f["reason"]
    if only:
        ids = {r["id"] for r in selected(plan, only)}
        edited = {k: v for k, v in edited.items() if k in ids}
        failed = {k: v for k, v in failed.items() if k in ids}
    return {"edited": edited, "failed": failed}


def _lines(plan: dict, only: str) -> list:
    s = summary(plan, only)
    by_id = {r["id"]: r for r in plan["records"]}
    chosen = selected(plan, only) if only else plan["records"]
    ids = {r["id"] for r in chosen}
    rels = {rel for r in chosen for rel in r["sources_all"]}
    out = [f"# Library report, plan {plan['date']}" + (f", section {only}" if only else ""), "",
           f"- Source files: {s['source_files']}; accounted for: {s['accounted']}"
           f" ({'reconciled' if s['reconciled'] else 'NOT RECONCILED'})",
           f"- Records: {s['records']}; files merged as copies: {s['files_merged']};"
           f" rectification variants: {s['variants']}",
           f"- By privacy: {s['by_privacy']}", f"- By kind: {s['by_kind']}",
           f"- Origin: {s['origin']}", f"- Skipped: {s['skips']}", ""]
    if s["sections"]:
        out += ["## Sections", "", "| Section | Records |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in s["sections"].items()] + [""]
    titles = {"same_moment": "Same moment, names or kind not compatible",
              "cross_class": "Groups across privacy classes (the more private wins)",
              "timezone_conflict": "Timezone conflicts (one record; pick the right side)",
              "different_dates": "Same name, different birth dates (not merged)",
              "rating_conflict": "Rating conflicts between copies",
              "variants": "Rectification variant groups (Ascendants)",
              "no_ascendant": "No measured Ascendant (kept as separate records)",
              "regrouped": "Records regrouped since the last migration"}
    for key, title in titles.items():
        items = [x for x in plan["review"].get(key) or [] if _keep(key, x, ids, rels)]
        out += [f"## {title} ({len(items)})", ""]
        for item in items[:400]:
            if key in ("same_moment", "cross_class", "no_ascendant"):
                out.append("- " + "; ".join(item))
            elif key == "timezone_conflict":
                out.append("- " + "; ".join(f"{x['rel']} ({x['offset']:+g} h)" for x in item))
            elif key == "different_dates":
                out.append("- " + "; ".join(f"{by_id[i]['name']} {by_id[i]['local'][:3]}"
                                            for i in item))
            elif key == "variants":
                out.append(f"- {by_id[item['subject']]['name']}: {item['ascendants']}")
            elif key == "regrouped":
                out.append(f"- {by_id[item['id']]['name'] if item['id'] in by_id else item['id']}: "
                           f"{item}")
            else:
                out.append(f"- {by_id[item['id']]['name']}: kept {item['chosen']}")
        out.append("")
    known = set(admin.read_json(Path(plan["library_root"]) / admin.ADMIN /
                                "known_timezone_errors.json", []))
    flagged = sorted((r for r in chosen if known & set(r["sources_all"])),
                     key=lambda r: r["name"])
    out += [f"## Charts with a known Kala atlas timezone error, copied as they are "
            f"({len(flagged)})", ""]
    out += [f"- {r['name']}: " + "; ".join(sorted(known & set(r["sources_all"])))
            for r in flagged] + [""]
    results = migration_results(plan, only)
    for key, title in (("edited", "Edited library files skipped (INV-7)"),
                       ("failed", "Conversion failures (source kept)")):
        out += [f"## {title} ({len(results[key])})", ""]
        out += [f"- {by_id[i]['name'] if i in by_id else i}: {why}"
                for i, why in sorted(results[key].items())] + [""]
    private = sorted((r for r in chosen if r["privacy"] == "private"
                      and r["kind"] == "person"), key=lambda r: -r["copies"])
    out += ["## Private people by copies (closeness signal)", ""]
    out += [f"- {r['name']}: {r['copies']}" for r in private[:200] if r["copies"] > 1] + [""]
    suspected = [r for r in chosen if r["privacy"] == "review"]
    out += [f"## Suspected, waiting for the identity check ({len(suspected)})", ""]
    out += [f"- {r['name']} ({clear_section(r.get('section'))})" for r in suspected] + [""]
    if not only:
        out += [f"## Skipped files ({len(plan['skips'])})", ""]
        out += [f"- {x['rel']}: {x['reason']}" for x in plan["skips"]] + [""]
    return out


def write(plan: dict, only: str = "") -> Path:
    run = admin.folder(Path(plan["library_root"]), "logs") / time.strftime("%Y%m%d-%H%M%S")
    admin.ensure_dir(run, True)
    path = run / "REPORT.md"
    admin.write_text(path, "\n".join(_lines(plan, only)))
    return path
