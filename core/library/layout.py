# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Target paths (§3.1): one folder per person or event, clear names, homonyms
with the birth year, rectification variants beside the primary chart."""
from collections import defaultdict
from typing import List

from core.library.names import clear_name, clear_section

OWNER_ONLY_TOPS = ("Private", "Review")


def _parent(rec: dict) -> str:
    section = clear_section(rec.get("section"))
    if rec["privacy"] == "review":
        return "Review/Suspected"
    if rec["privacy"] != "public":
        sub = {"case": "Cases", "event": "Events"}.get(rec["kind"], "People")
        return f"Private/{sub}/{section}"
    if rec["kind"] == "case":
        return f"Research/Cases/{section}"
    sub = "Events" if rec["kind"] == "event" else "People"
    return f"Public/{sub}/{section}"


def assign(records: List[dict]) -> None:
    """Set ``folder`` and ``path`` (relative to the library root) on every record."""
    subjects = defaultdict(list)
    for rec in records:
        subjects[rec["subject"]].append(rec)
    for recs in subjects.values():
        recs.sort(key=lambda r: r["variant"])
        primary = recs[0]
        for r in recs:  # one folder per subject: its primary's parent and name
            r["_parent"], r["_base"] = _parent(primary), clear_name(primary["name"])
    by_folder = defaultdict(list)
    for sid, recs in subjects.items():
        by_folder[(recs[0]["_parent"], recs[0]["_base"].lower())].append(sid)
    for (_parent_dir, _base), sids in by_folder.items():
        suffix = {sid: "" for sid in sids}
        if len(sids) > 1:
            years = defaultdict(list)
            for sid in sids:
                years[subjects[sid][0]["local"][0]].append(sid)
            for year, same in years.items():
                for sid in same:
                    y, m, d = subjects[sid][0]["local"][:3]
                    suffix[sid] = f" ({year})" if len(same) == 1 else f" ({y:04d}-{m:02d}-{d:02d})"
            if len(set(suffix.values())) < len(sids):  # same day too: the id decides
                for sid in sids:
                    suffix[sid] += f" {subjects[sid][0]['id'][-4:]}"
        for sid in sids:
            for r in subjects[sid]:
                folder = f"{r['_parent']}/{r['_base']}{suffix[sid]}"
                stem = f"{r['_base']}{suffix[sid]}"
                if r["variant"] > 1:
                    stem += f" - rectification {r['variant']}"
                r["folder"], r["path"] = folder, f"{folder}/{stem}.toml"
    for r in records:
        r.pop("_parent", None)
        r.pop("_base", None)


def owner_only(path: str) -> bool:
    """True for a path under ``Private/`` or ``Review/`` (written 0700 / 0600)."""
    return path.split("/", 1)[0] in OWNER_ONLY_TOPS
