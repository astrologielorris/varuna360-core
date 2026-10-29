# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Copies, variants and timezone conflicts (INV-4, §4.3).

1. Same moment key: files merge into one cluster only with compatible names
   and the same kind; a moment group left in several clusters is reported.
2. A cluster takes the most private class among its classed files; a cluster
   of mixed files only goes through the local name rules, else ``review``.
3. Clusters with the same name, local date and kind form one subject; inside
   it an Ascendant within 0.5° is a copy, the same local time with another
   offset or place (or a whole-hour JD gap) is a timezone conflict, and only a
   different local birth time is a rectification variant.
"""
import hashlib
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from core.library import classify, names
from core.library.folder_map import KIND, PRIVACY, FolderMap
from core.library.privacy import effective_privacy, strictest
from core.library.survey import moment_key

ASC_LIMIT = 0.5  # degrees; O-1


class _Union:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def _asc_gap(a: dict, b: dict) -> Optional[float]:
    if a.get("asc") is None or b.get("asc") is None:
        return None
    d = abs(a["asc"] - b["asc"]) % 360.0
    return min(d, 360.0 - d)


def _local(row: dict) -> tuple:
    return tuple(row["local"])


def _tz_conflict(a: dict, b: dict) -> bool:
    """Same local date and time with another offset or place, or a JD gap of a
    whole number of hours (within a minute)."""
    if _local(a) == _local(b) and (a["offset"] != b["offset"]
                                   or moment_key(a)[1:] != moment_key(b)[1:]):
        return True
    hours = abs(a["jd"] - b["jd"]) * 24.0
    return round(hours) >= 1 and abs(hours - round(hours)) < 1.0 / 60.0


def _place(row: dict, fmap: FolderMap, verdicts: dict) -> dict:
    """The file's class, section, kind and privacy hint."""
    override = (verdicts.get("class") or {}).get(row["rel"])
    if override:
        cls, section, rule = override.get("class"), override.get("section"), "verdict"
    else:
        p = fmap.place(row["folder"])
        cls, section, rule = p.cls, p.section, p.rule
        if cls == "mixed" and not fmap.rules.get(p.rule, (None, None))[1]:
            section = None  # a subfolder of a mixed folder is not a section name
    hit = classify.name_rule(row["name"]) if cls == "mixed" else None
    kind = KIND.get(cls) or (hit[1] if hit else "person")
    return {**row, "cls": cls, "section": section, "rule": rule, "kind": kind,
            "name_rule": hit[2] if hit else None, "name_privacy": hit[0] if hit else None,
            "collection": fmap.collection(row["folder"])}


def _kinds_fit(a: dict, b: dict) -> bool:
    """Same kind; a mixed file's kind is only a guess, so it may join a classed
    person or event. A research case is a hard boundary: it merges only with
    another case; a mixed copy of it stays separate and is listed for review."""
    if a["kind"] == b["kind"]:
        return True
    if (a["cls"] == "mixed") == (b["cls"] == "mixed"):
        return False
    classed = b if a["cls"] == "mixed" else a
    return classed["kind"] != "case"


def record_id(first: dict, name: str, kind: str) -> str:
    """Stable id: the first source's moment key and path, the name and the kind."""
    key = f"{moment_key(first)}|{names.normalise(name)}|{kind}|{first['rel']}"
    return "lib-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _cluster_class(items: List[dict]) -> tuple:
    """(privacy, class, cross_class) of a copy cluster."""
    classed = [it for it in items if it["cls"] in PRIVACY]
    if classed:
        levels = {PRIVACY[it["cls"]] for it in classed}
        privacy = strictest(levels)
        cls = next(it["cls"] for it in classed if PRIVACY[it["cls"]] == privacy)
        return privacy, cls, len(levels) > 1
    if any(it["name_privacy"] for it in items):
        return "private", "private-events" if items[0]["kind"] == "event" \
            else "private-people", False
    return "review", "review", False


def build(rows: Iterable[dict], fmap: FolderMap, verdicts: Optional[dict] = None) -> dict:
    """Records and review lists from survey rows (readable, not skipped)."""
    verdicts = verdicts or {}
    aliases = [tuple(p) for p in verdicts.get("aliases") or [] if len(p) == 2]
    items = [_place(r, fmap, verdicts) for r in rows]
    review: Dict[str, list] = defaultdict(list)

    # 1. copy clusters inside each moment group
    by_moment = defaultdict(list)
    for i, it in enumerate(items):
        by_moment[moment_key(it)].append(i)
    clusters = {}
    for group in by_moment.values():
        # complete linkage: a file joins a cluster only when it fits every
        # member, so "John Smith", "John Doe", "Jane Doe" never become one
        local = []
        for i in sorted(group, key=lambda i: items[i]["rel"]):
            it = items[i]
            for members in local:
                if all(_kinds_fit(it, m) and names.compatible(it["name"], m["name"], aliases)
                       for m in members):
                    members.append(it)
                    break
            else:
                local.append([it])
        if len(local) > 1:
            review["same_moment"].append(sorted(items[i]["rel"] for i in group))
        for members in local:
            clusters[len(clusters)] = members
    for members in clusters.values():  # a mixed copy takes its classed copy's kind
        classed = [m["kind"] for m in members if m["cls"] != "mixed"]
        if classed:
            for m in members:
                m["kind"] = classed[0]

    # 2. class of each cluster
    cl = []
    for members in clusters.values():
        privacy, cls, cross = _cluster_class(members)
        if cross:
            review["cross_class"].append(sorted(m["rel"] for m in members))
        cl.append({"items": members, "privacy": privacy, "cls": cls,
                   "kind": members[0]["kind"]})

    # 3. subjects: same name, local date and kind
    su = _Union(len(cl))
    seen = {}
    for ci, c in enumerate(cl):
        for it in c["items"]:
            key = (names.normalise(it["name"]), _local(it)[:3], c["kind"])
            if key[0] and key in seen:
                su.join(seen[key], ci)
            seen.setdefault(key, ci)
    subjects = defaultdict(list)
    for ci, c in enumerate(cl):
        subjects[su.find(ci)].append(c)

    records = []
    for group in subjects.values():
        records.extend(_variants(group, review))
    _date_conflicts(records, review)
    return {"records": records, "review": dict(review)}


def _latest(items):
    return max(it["mtime"] for it in items)


def _bucket(group: List[dict], review) -> tuple:
    """(buckets, own): measured clusters bucketed into copies, timezone conflicts
    and variants; a cluster with no measured Ascendant joins a bucket only as a
    timezone conflict, else it is its own record (never a copy or a variant)."""
    measured = [c for c in group if c["items"][0].get("asc") is not None]
    unresolved = [c for c in group if c["items"][0].get("asc") is None]
    buckets, own = [], []

    def tz_join(c) -> bool:
        rep_c = c["items"][0]
        for b in buckets:
            rep = b["clusters"][0]["items"][0]
            if _tz_conflict(rep, rep_c):
                b["clusters"].append(c)
                review["timezone_conflict"].append(
                    [{"rel": x["rel"], "offset": x["offset"]} for x in (rep, rep_c)])
                return True
        return False

    for c in measured:
        if tz_join(c):
            continue
        rep_c = c["items"][0]
        for b in buckets:
            if _asc_gap(b["clusters"][0]["items"][0], rep_c) <= ASC_LIMIT:
                b["clusters"].append(c)
                break
        else:
            buckets.append({"clusters": [c]})
    for c in unresolved:
        if not tz_join(c):
            own.append({"clusters": [c]})
    if not buckets and own:
        buckets.append(own.pop(0))
    for b in own:
        review["no_ascendant"].append(sorted(it["rel"] for c in b["clusters"]
                                             for it in c["items"]))
    return buckets, own


_FILED_CLS = {"public": "public-people", "private": "private-people",
              "review": "review"}


def _filing(level: str) -> str:
    """Where a record is filed: a MIXED person goes in the private part (BIO D-10)."""
    return "private" if level == "mixed" else level


def _variants(group: List[dict], review) -> List[dict]:
    """One subject's records: copies, timezone conflicts and variants; each
    record filed by its own confirmed rating, the variants of a subject together
    under the strictest of them (a private chart is never filed public)."""
    group.sort(key=lambda c: (-len(c["items"]), -_latest(c["items"]),
                              min(it["rel"] for it in c["items"])))
    buckets, own = _bucket(group, review)
    folder_privacy = strictest(c["privacy"] for c in group)
    cls = next(c["cls"] for c in group if c["privacy"] == folder_privacy)
    if len({c["privacy"] for c in group}) > 1:
        review["cross_class"].append(sorted(it["rel"] for c in group for it in c["items"]))
    buckets.sort(key=lambda b: (-sum(len(c["items"]) for c in b["clusters"]),
                                -max(_latest(c["items"]) for c in b["clusters"])))
    subject_recs = [_record(b, cls, n, review, folder_privacy)
                    for n, b in enumerate(buckets, start=1)]
    own_recs = [_record(b, cls, 1, review, folder_privacy) for b in own]
    for rec in subject_recs + own_recs:
        rec["privacy"] = _filing(effective_privacy({"rating": rec.get("rating"),
                                                    "privacy": folder_privacy}))
    level = strictest(r["privacy"] for r in subject_recs)
    subject = subject_recs[0]["id"]
    for rec in subject_recs:
        rec["privacy"], rec["subject"] = level, subject
    for rec in own_recs:
        rec["subject"] = rec["id"]
    for rec in subject_recs + own_recs:
        if rec["privacy"] != folder_privacy:
            rec["cls"] = _FILED_CLS.get(rec["privacy"], rec["cls"])
        if rec["privacy"] != "public":
            rec["tags"] = []
    if len(subject_recs) > 1:
        review["variants"].append({"subject": subject, "ascendants":
                                   [r["asc"] for r in subject_recs]})
    return subject_recs + own_recs


def _record(bucket: dict, cls: str, variant: int, review, folder_privacy: str) -> dict:
    items = sorted((it for c in bucket["clusters"] for it in c["items"]),
                   key=lambda it: it["rel"])
    level_items = [it for it in items if PRIVACY.get(it["cls"]) == folder_privacy] or items
    public_items = [it for it in items if PRIVACY.get(it["cls"]) == "public"]
    name = names.most_complete(it["name"] for it in level_items) or items[0]["name"]
    source = max(level_items, key=lambda it: (it["ext"] == ".toml", it["notes_len"], it["mtime"],
                                        it["rel"]))
    sections = [it["section"] for it in level_items if it["section"]]
    section = max(set(sections), key=lambda s: (sections.count(s), s)) if sections else None
    tags = sorted({s for s in (it["section"] for it in items) if s and s != section}
                  | {it["collection"] for it in items if it["collection"]})
    rec = {
        "id": record_id(items[0], name, items[0]["kind"]), "name": name, "kind": items[0]["kind"],
        "privacy": folder_privacy, "folder_privacy": folder_privacy, "cls": cls,
        "section": section, "variant": variant,
        "copies": len(items), "source": source["rel"], "asc": source.get("asc"),
        "local": source["local"],
        "sources_all": [it["rel"] for it in items],
        "sources_public": [it["rel"] for it in public_items],
        "aliases_all": sorted({it["name"] for it in items} - {name}),
        "aliases_public": sorted({it["name"] for it in public_items} - {name}),
        "tags": tags,
        "collections": sorted({it["collection"] for it in items if it["collection"]}),
        "origin": source["origin"], "name_rules": sorted({it["name_rule"] for it in items
                                                          if it["name_rule"]}),
        "oldest_source_mtime": min(it["mtime"] for it in items),
        "notes_differ": len({it["notes_len"] for it in items}) > 1,
    }
    rated = [it for it in items if isinstance(it.get("rating"), dict)]
    if rated:
        rated.sort(key=lambda it: str(it["rating"].get("rated") or ""))
        rec["rating"] = rated[-1]["rating"]
        if len({repr(sorted(it["rating"].items())) for it in rated}) > 1:
            review["rating_conflict"].append({"id": rec["id"], "chosen": rated[-1]["rel"]})
    return rec


def _date_conflicts(records: List[dict], review) -> None:
    """Different birth dates under one name: never merged, reported."""
    by_name = defaultdict(set)
    for r in records:
        if r["kind"] == "person":
            by_name[names.normalise(r["name"])].add(tuple(r["local"][:3]))
    for name, dates in by_name.items():
        if name and len(dates) > 1:
            ids = [r["id"] for r in records if names.normalise(r["name"]) == name]
            review["different_dates"].append(ids)
