# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Library statistics (§4.5b): counts only, AI-free, no chart computation.

Phase 1 reads the manifest and each chart's ``[rating]`` (tomllib only, no
chart computation); the Find Chart store's ``ratings`` mirror and
``library_state.sqlite`` replace that read in phase 1b (SPEC-LIB-002).
"""
from collections import Counter
from pathlib import Path

from core.library import admin, rating, scores, tables


def stats(library_root: Path) -> dict:
    rows = list(admin.read_manifest(library_root).values())
    for r in rows:  # the chart file holds the confirmed rating, not the manifest
        path = Path(library_root) / (r.get("path") or "")
        try:
            r["rating"] = tables.get(path, "rating")
        except (OSError, ValueError):
            pass
    subjects = Counter(r.get("subject") for r in rows)
    for r in rows:
        r["variants"] = subjects[r.get("subject")]
    rated = [r for r in rows if rating.clean(r.get("rating")).get("who")]
    return {
        "records": len(rows),
        "rated": len(rated), "unrated": len(rows) - len(rated),
        "by_privacy": dict(Counter(r.get("privacy") for r in rows)),
        "by_kind": dict(Counter(r.get("kind") for r in rows)),
        "ai_made": sum(1 for r in rows if r.get("origin") == "ai-made"),
        "origin": dict(Counter(r.get("origin") for r in rows)),
        "copies": dict(sorted(Counter(r.get("copies") for r in rows).items())),
        "with_variants": sum(1 for r in rows if r["variants"] > 1),
        "privacy_readout": dict(sorted(Counter(scores.privacy_readout(r) for r in rows).items())),
        "preference_readout": dict(sorted(Counter(scores.preference_readout(r)
                                                  for r in rows).items())),
    }


def _weeks_in_row(dates, today) -> int:
    """Consecutive weeks (ending this week or last) with at least one rating."""
    import datetime
    weeks = {d.isocalendar()[:2] for d in dates}
    week = today
    if week.isocalendar()[:2] not in weeks:
        week -= datetime.timedelta(days=7)
    n = 0
    while week.isocalendar()[:2] in weeks:
        n += 1
        week -= datetime.timedelta(days=7)
    return n


def overview(lib, today=None) -> dict:
    """The Library sheet's numbers (SPEC-LIB-002 §4.3, §4.11) from a
    ``queue.Library``: counts per group, no chart file opened (INV-8)."""
    import datetime
    from core.library import queue
    today = today or datetime.date.today()
    zones = {z: {"confirmed": 0, "guessed": 0} for z in (rating.PRIVATE, rating.MIXED, rating.PUBLIC)}
    rated, dates, chtk, ai_made, seen = 0, [], 0, 0, []
    for g in lib.groups.values():
        z = g.zone()
        if g.confirmed:
            rated += 1
            if z:
                zones[z]["confirmed"] += 1
            try:
                dates.append(datetime.date.fromisoformat(g.rating.get("rated", "")))
            except ValueError:
                pass
        elif z:
            zones[z]["guessed"] += 1
        chtk += sum(1 for c in g.charts if c.chtk)
        rec = g.record or {}
        ai_made += rec.get("origin") == "ai-made"
        if rec.get("first_seen"):
            seen.append(rec["first_seen"])
    total = len(lib.groups)
    month = today.strftime("%Y-%m")
    opened_month = sum(1 for at in lib.opened.values()
                       if datetime.date.fromtimestamp(at).strftime("%Y-%m") == month)
    return {
        "charts": total, "rated": rated, "unrated": total - rated,
        "zones": zones,
        "this_week": sum(1 for d in dates if (today - d).days < 7),
        "weeks_in_row": _weeks_in_row(dates, today),
        "waiting": queue.waiting(lib),
        "chtk": chtk, "ai_made": ai_made, "opened_this_month": opened_month,
        "oldest": min(seen) if seen else "", "newest": max(seen) if seen else "",
    }
