# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Merging two instances' chart lists (SPEC-SES-002 §4.2-4.4, td-t3hq).

Lorris runs the full app and `--lite` at the same time, sharing `profiles/`.
Both write their whole chart list every 30 seconds with no read-before-write,
so whichever saves last erases what the other added. This module is the rule
that replaces the overwrite.

Pure functions, no Qt, no I/O: the merge is the part that can lose data, so
it has to be testable without an app, a window or a disk.

THE THREE KEYS, AND WHY THEY ARE NOT ONE (§4.3)

* **uuid** — identity. Authoritative for entries that share an ancestor,
  which is the normal case: restore preserves the stored id, so two instances
  that restored the same file agree on every id. It is NOT globally derived —
  `add_chart` mints a fresh one per call — so the same chart opened
  independently in both instances exists twice. That is a duplicate, not a
  loss, and it is the price of refusing to collapse on a guess.
* **(jd, lat, lon)** — a dedup HINT. It MAY warn; it MUST NOT lose data.
* **zodiac mode / ayanamsa / house system** — cache validity, in-process
  only. Never identity, never compared across instances.

THE RULE THAT MAKES TOMBSTONES WORK

`updated_at` is stamped only when an entry actually CHANGES, never on save.
If every tick stamped every entry, no `deleted_at` could ever be newer than
an `updated_at` within the save interval, so every deletion would be undone
by the other instance and the file would oscillate forever. The spec calls
this the single easiest way to build this wrong.
"""

from typing import Any, Dict, List, Optional, Tuple

#: Recipe keys compared to decide whether two entries differ.
#: `house_system` is EXCLUDED on purpose: chart_factory rewrites it to the
#: current GUI setting on every rebuild, so two instances on different house
#: systems write recipes differing on that key alone with equal `updated_at`
#: — "differing → newer wins; equal → keep ours" then never converges and the
#: entry flips every tick. Cache-validity keys are not identity (§4.3).
RECIPE_COMPARE_EXCLUDE = ("house_system",)

#: Tombstones are pruned after this many days (§4.4).
TOMBSTONE_RETENTION_DAYS = 90


# --- time -------------------------------------------------------------------

def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value) -> Optional[Any]:
    """ISO string -> aware datetime, or None.

    Timezone-AWARE throughout. The file's existing precedent is naive local
    time, under which a DST fall-back hour makes an entry created after a
    deletion look older than it — and the entry is then resurrected.
    """
    from datetime import datetime, timezone
    if not value or not isinstance(value, str):
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _newer(a, b) -> bool:
    """True when timestamp `a` is strictly newer than `b`.

    False whenever either is missing or unparseable — fail closed. An
    unknown age must never justify dropping the other side's entry.
    """
    ta, tb = parse_ts(a), parse_ts(b)
    if ta is None or tb is None:
        return False
    return ta > tb


# --- identity ---------------------------------------------------------------

def entry_id(entry: Dict[str, Any]) -> Optional[str]:
    value = entry.get("id")
    return str(value) if value else None


def entry_hint(entry: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    """The soft `(jd, lat, lon)` key, or None when it cannot be formed.

    Never raises on a malformed entry: one bad entry on disk must not take
    down a save that carries every other chart.
    """
    recipe = entry.get("recipe")
    if not isinstance(recipe, dict):
        return None
    try:
        jd = recipe.get("julian_day")
        if jd is None:
            from core.chart_factory import jd_from_recipe_civil
            jd = jd_from_recipe_civil(recipe)
        return (round(float(jd), 6), round(float(recipe["lat"]), 6),
                round(float(recipe["lon"]), 6))
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None


def _comparable(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The part of an entry two instances may legitimately disagree about."""
    recipe = entry.get("recipe")
    if not isinstance(recipe, dict):
        return {}
    return {k: v for k, v in recipe.items() if k not in RECIPE_COMPARE_EXCLUDE}


def entries_differ(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _comparable(a) != _comparable(b) or a.get("chtk_path") != b.get("chtk_path")


def same_file(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """The ONE collapse the merge may perform (§4.3).

    Two different uuids whose chtk_path is set and equal are the same chart:
    a path match is certain evidence, where (jd, lat, lon) is only a
    probability. No path, or different paths — both survive.
    """
    pa, pb = a.get("chtk_path"), b.get("chtk_path")
    return bool(pa) and bool(pb) and str(pa) == str(pb)


# --- tombstones -------------------------------------------------------------

def make_tombstone(entry: Dict[str, Any], deleted_at: Optional[str] = None
                   ) -> Dict[str, Any]:
    """The record a removal leaves behind (§4.4).

    Fields, not a rendered string: the matcher compares floats, and a string
    key could never express that, so the two would silently never agree.
    """
    hint = entry_hint(entry) or (None, None, None)
    return {
        "id": entry_id(entry),
        "jd": hint[0], "lat": hint[1], "lon": hint[2],
        "deleted_at": deleted_at or utc_now_iso(),
    }


def _tombstone_kills(tomb: Dict[str, Any], entry: Dict[str, Any]) -> bool:
    """True when this removal record suppresses this entry.

    Always requires the removal to be NEWER than the entry's own last
    change: an edit after a delete is a new fact about the chart.

    THE SOFT KEY MAY NOT KILL AN IDENTIFIED ENTRY.

    §4.4 allows matching by `(jd, lat, lon)`, and §4.3 says that key is a
    HINT which "MAY warn on collision and MUST NOT lose data because of
    one". Those pull against each other, and the collision is not
    hypothetical in this domain: TWINS share the instant and the place
    exactly, and so do two charts of the same event. Deleting one twin would
    silently delete the other.

    So: an id match kills. The hint kills only when one of the two sides has
    no id to compare — a pre-uuid record, or an entry that never got one.
    The cost is that a chart the other instance created INDEPENDENTLY (its
    own uuid, same moment) survives a delete made here. That is a duplicate
    the user can delete again, which is the same trade §4.3 already makes
    when it refuses to collapse on the soft key.
    """
    if not isinstance(tomb, dict):
        return False
    if not _newer(tomb.get("deleted_at"), entry.get("updated_at")):
        return False
    tid = tomb.get("id")
    eid = entry_id(entry)
    if tid and eid:
        return eid == str(tid)
    hint = entry_hint(entry)
    if hint is None:
        return False
    try:
        return hint == (round(float(tomb["jd"]), 6),
                        round(float(tomb["lat"]), 6),
                        round(float(tomb["lon"]), 6))
    except (TypeError, ValueError, KeyError):
        return False


def _tombstone_key(tomb: Dict[str, Any]):
    """What makes two removal records the SAME removal.

    The id when there is one, the (jd, lat, lon) hint otherwise. Two records
    of one deletion are not two deletions, and the merge produces them
    constantly: it unions ours with theirs, and both sides hold the record
    once it has been written and read back.
    """
    tid = tomb.get("id")
    if tid:
        return ("id", str(tid))
    try:
        return ("hint", round(float(tomb["jd"]), 6),
                round(float(tomb["lat"]), 6), round(float(tomb["lon"]), 6))
    except (TypeError, ValueError, KeyError):
        return None


def prune_tombstones(tombstones, now=None) -> List[Dict[str, Any]]:
    """Drop records older than the retention window, and collapse duplicates.

    Pruning alone is NOT safe, and no longer window makes it safe — there is
    always a longer sleep. INV-10 (`should_rebaseline`) is what closes that
    hole; this only keeps the file from growing without bound.

    THE DEDUP IS NOT COSMETIC. Every merge unions ours with theirs, and after
    the first write both sides hold the same record — so one deletion became
    two, then four, then eight. Two instances ticking every 30 s grow the
    file without bound and slow every later merge, for a set that should have
    exactly one entry per deleted chart.

    When the same removal appears twice, the NEWEST `deleted_at` wins: a
    tombstone only suppresses entries older than itself, so the newest is the
    one that still does its job.
    """
    from datetime import datetime, timedelta, timezone
    if not isinstance(tombstones, list):
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=TOMBSTONE_RETENTION_DAYS)
    kept: List[Dict[str, Any]] = []
    seen: Dict[Any, int] = {}
    for tomb in tombstones:
        if not isinstance(tomb, dict):
            continue
        when = parse_ts(tomb.get("deleted_at"))
        # An unparseable date is KEPT: dropping it would resurrect whatever
        # it suppresses, and a record we cannot date is not evidence of age.
        if when is not None and when < cutoff:
            continue
        key = _tombstone_key(tomb)
        if key is None:
            # Neither an id nor a usable hint: it can never match anything,
            # but dropping it is still not this function's call.
            kept.append(tomb)
            continue
        if key not in seen:
            seen[key] = len(kept)
            kept.append(tomb)
            continue
        if _newer(tomb.get("deleted_at"), kept[seen[key]].get("deleted_at")):
            kept[seen[key]] = tomb
    return kept


def should_rebaseline(baseline_iso, now=None) -> bool:
    """INV-10: is this instance too old to trust its own list?

    An instance left running (or a laptop asleep) longer than the retention
    window still holds entries that were deleted while it slept, and the
    tombstone that would have suppressed them is gone. It can no longer
    prove its unmatched entries are not resurrections, so disk becomes
    authoritative for removals.

    A MISSING baseline returns False, not True. It looks like the cautious
    answer and is the opposite: an instance with no baseline has never read
    the file, so it is holding nothing that could have been deleted while it
    slept — and re-baselining it would discard the charts it is trying to
    save for the first time. (It did: the first save of a fresh manager
    dropped its only chart.) The stale-replica risk is about a list read
    LONG AGO, which is exactly what a recorded baseline expresses.
    """
    from datetime import datetime, timedelta, timezone
    when = parse_ts(baseline_iso)
    if when is None:
        return False
    now = now or datetime.now(timezone.utc)
    return when < now - timedelta(days=TOMBSTONE_RETENTION_DAYS)


# --- the merge --------------------------------------------------------------

def merge_charts(ours: List[Dict[str, Any]], theirs: List[Dict[str, Any]],
                 tombstones=None, rebaseline: bool = False
                 ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Union by identity, additions win. Returns (merged, stats).

    | Case                    | Result                                  |
    |-------------------------|-----------------------------------------|
    | ours only               | keep — only a recorded removal drops it |
    | theirs only             | ADD — the case that loses charts today  |
    | both, identical         | keep one                                |
    | both, differing         | newer updated_at wins; equal → ours     |
    | matched by a tombstone  | drop, and carry the record forward      |

    Removals apply to the union and take precedence over ours-only-keep.
    Otherwise a delete never propagates: B keeps rewriting X, A keeps it as
    "ours only", and the file oscillates forever.

    Every comparison is guarded per entry. The identity predicate reads
    recipe keys directly, and one malformed entry on disk would otherwise
    raise inside save_session's broad except and fail the whole save on every
    tick, forever — the failure whose comment already reads "130 charts lost
    because of one".
    """
    ours = [e for e in (ours or []) if isinstance(e, dict)]
    theirs = [e for e in (theirs or []) if isinstance(e, dict)]
    tombs = [t for t in (tombstones or []) if isinstance(t, dict)]
    stats = {"added": 0, "updated": 0, "removed": 0, "collapsed": 0,
             "skipped": 0}

    def killed(entry):
        for tomb in tombs:
            try:
                if _tombstone_kills(tomb, entry):
                    return True
            except Exception:
                continue
        return False

    by_id = {}
    order = []

    def _put(entry, source):
        try:
            key = entry_id(entry)
            if key is None:
                # No id at all: it cannot be matched, so it can only be kept
                # (from ours) — adding an unidentifiable entry from disk on
                # every tick would multiply it without bound.
                if source == "ours":
                    anon = ("_anon", len(order))
                    by_id[anon] = entry
                    order.append(anon)
                else:
                    stats["skipped"] += 1
                return
            if key not in by_id:
                by_id[key] = entry
                order.append(key)
                if source == "theirs":
                    stats["added"] += 1
                return
            existing = by_id[key]
            if source == "theirs" and entries_differ(existing, entry):
                if _newer(entry.get("updated_at"), existing.get("updated_at")):
                    by_id[key] = entry
                    stats["updated"] += 1
        except Exception:
            stats["skipped"] += 1

    for entry in ours:
        if killed(entry):
            stats["removed"] += 1
            continue
        _put(entry, "ours")

    for entry in theirs:
        if killed(entry):
            stats["removed"] += 1
            continue
        if rebaseline:
            # INV-10: disk is authoritative for removals, so an entry we do
            # not already hold is still an ADDITION, but one of ours that
            # disk lacks can no longer be defended. Handled below.
            pass
        _put(entry, "theirs")

    merged = [by_id[k] for k in order if k in by_id]

    if rebaseline:
        # Keep only what disk still has, plus anything of ours changed since
        # the baseline (provably not a resurrection: its updated_at is newer
        # than any surviving tombstone).
        their_ids = {entry_id(e) for e in theirs}
        kept = []
        for entry in merged:
            if entry_id(entry) in their_ids or _newer(
                    entry.get("updated_at"),
                    max((t.get("deleted_at") or "" for t in tombs), default="")):
                kept.append(entry)
            else:
                stats["removed"] += 1
        merged = kept

    # The one legal collapse: equal, non-empty chtk_path under two uuids.
    # Keep the OLDER uuid (it is the one other instances already reference)
    # and take the newer fields.
    by_path = {}
    collapsed = []
    for entry in merged:
        path = entry.get("chtk_path")
        if not path:
            collapsed.append(entry)
            continue
        key = str(path)
        if key not in by_path:
            by_path[key] = len(collapsed)
            collapsed.append(entry)
            continue
        index = by_path[key]
        winner = collapsed[index]
        if _newer(entry.get("updated_at"), winner.get("updated_at")):
            merged_entry = dict(entry)
            merged_entry["id"] = winner.get("id")   # the older uuid survives
            collapsed[index] = merged_entry
        stats["collapsed"] += 1

    return collapsed, stats


def merge_session_data(ours: Dict[str, Any], theirs: Dict[str, Any],
                       rebaseline: bool = False) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Merge two whole session dicts. `ours` wins for everything else.

    What is deliberately NOT merged (§4.7): ui_state, the selected index,
    window geometry. Those are per-instance, and last-writer-wins on them is
    a cosmetic annoyance where last-writer-wins on charts is data loss.
    """
    result = dict(ours or {})
    tombs = prune_tombstones(
        list((ours or {}).get("tombstones") or [])
        + list((theirs or {}).get("tombstones") or []))
    merged, stats = merge_charts((ours or {}).get("charts"),
                                 (theirs or {}).get("charts"),
                                 tombstones=tombs, rebaseline=rebaseline)
    result["charts"] = merged
    result["tombstones"] = tombs
    return result, stats
