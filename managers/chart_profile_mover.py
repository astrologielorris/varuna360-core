# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart-profile mover (SPEC-PROF-003) — move a chart's profile membership.

**Entry-only (v1).** This module changes which profile's `session.json` a
chart entry belongs to. It NEVER touches files on disk: no `.toml`/`.chtk`
move, no chart-index write, `chtk_path` carried verbatim. Physical
file-follow (and the profile-folder-naming question it drags in) is deferred
wholesale to bead **td-rp7z**.

Qt-free and stateless — stdlib + `ProfileStore` + `session_merge` only, the
`favorites_manager` pattern. The panel owns widgets and selection; this module
owns the locked destination write and the deterministic dedup. It is the FIRST
non-SessionManager caller of `ProfileStore.save_profile_merged`
(SPEC-SES-002 §4.6 writer table).

Ordering the caller must honour (SPEC-PROF-003 §3.4): commit into the
destination FIRST, then remove from the source. At every intermediate failure
the chart is present in at least one session file — the worst outcome is a
transient duplicate, never a loss.
"""

from datetime import datetime, timezone
from pathlib import Path

try:
    from utils.debug import debug_print
except ImportError:  # pragma: no cover - debug shim
    debug_print = print


def _utc_now() -> str:
    """ISO 8601 UTC — the instant shape SPEC-SES-002 compares."""
    return datetime.now(timezone.utc).isoformat()


def _parse_version(value):
    """Parse a schema version like '3.1' -> (3, 1); None if unparseable.

    Versions are compared as integer tuples, never as strings: '10.0' < '3.0'
    lexicographically but is a NEWER schema, and a string compare would
    silently mis-order it (GPT Sol should-fix).
    """
    try:
        parts = str(value).strip().split('.')
        if parts and all(p.isdigit() for p in parts):
            return tuple(int(p) for p in parts)
    except Exception:  # noqa: BLE001
        pass
    return None


def _current_session_version() -> str:
    """The session schema version restore expects (SessionManager.VERSION).

    Drift-free: read from the class attribute rather than hard-coding, so a
    future schema bump carries here automatically. Lazy import keeps this
    module import-light and Qt-free at module load. Falls back to '3.1' (the
    value at time of writing) only when the import fails or the value is not a
    parseable version >= 3.0 — never returns something that would itself trip
    the v2 migration, and never downgrades a genuine future version.
    """
    try:
        from managers.session_manager import SessionManager
        v = str(getattr(SessionManager, 'VERSION', '') or '')
        pv = _parse_version(v)
        return v if (pv is not None and pv >= (3, 0)) else '3.1'
    except Exception:  # noqa: BLE001
        return '3.1'


def serialize_entry(entry: dict) -> dict:
    """The session save-shape for a chart entry, stamped as freshly mutated.

    Mirrors `SessionManager.save_session`'s per-entry block
    (`managers/session_manager.py` ~:1115-1132) field-for-field, with ONE
    deliberate difference: `updated_at` is stamped to *now*. A move IS a real
    mutation (SPEC-SES-002 §4.5), and the destination merge reads that stamp
    to win against an older copy or a stale tombstone. Any field drift from
    the session serializer is caught by
    `test_chart_profile_move.py::test_serialize_shape_matches_session`.

    Refuses an entry without a recipe dict OR without a non-empty string id:
    the merge keys on the uuid, and a blank/None id cannot be matched, deduped,
    or safely removed from the source (GPT Sol finding 6).
    """
    recipe = entry.get('recipe')
    if not isinstance(recipe, dict):
        raise ValueError("cannot move an entry without a recipe dict")
    cid = entry.get('id')
    if not isinstance(cid, str) or not cid:
        raise ValueError("cannot move an entry without a non-empty string id")
    chtk_path = entry.get('chtk_path')
    return {
        'id': cid,
        'recipe': recipe,
        'mode': entry.get('mode', 'aditya'),
        'ayanamsa': entry.get('ayanamsa', 1),
        # str(): a Path is not JSON-serializable and would fail the save.
        'chtk_path': str(chtk_path) if chtk_path is not None else None,
        'is_transit': entry.get('is_transit', False),
        'updated_at': _utc_now(),
    }


def dest_profile_exists(profiles_dir, dest_id: str) -> bool:
    """True when the destination profile DIRECTORY exists (pre-commit guard).

    Checked before the commit so a `LOAD_MISSING` baseline cannot silently
    recreate a session for a profile another instance just deleted
    (SPEC-PROF-003 §4, review finding 6).
    """
    try:
        return (Path(profiles_dir) / dest_id).is_dir()
    except Exception:  # noqa: BLE001
        return False


def dest_session_present(profiles_dir, dest_id: str) -> bool:
    """True when `profiles/<dest_id>/session.json` exists.

    The §3.4 step-3 deletion-race guard: re-checked immediately before the
    source removal. Our own commit wrote this file, so its absence here means
    another instance deleted the destination profile in the gap.
    """
    try:
        return (Path(profiles_dir) / dest_id / "session.json").exists()
    except Exception:  # noqa: BLE001
        return False


def _build_dest(on_disk, entry_dict: dict):
    """Merge one moved entry into the destination session (runs INSIDE the lock).

    Returns the new session dict. A move always has something valid to write,
    so this never refuses (never returns None); the refusal paths INV-7 covers
    (unreadable/salvaged baseline, lock not held) are handled by the store in
    `save_profile_merged` BEFORE build_fn runs. Every top-level key is preserved
    value-for-value; only `charts` and (a pruned) `tombstones` change.

    Dedup — SPEC-PROF-003 §3.2, ONE deterministic rule set, first match wins:
      1. same `id` present            -> replace that entry's fields (uuid kept)
      2. same non-None `chtk_path`,
         different id                 -> keep the DEST uuid, update its fields
                                         (the one documented identity exception)
      3. `(jd,lat,lon)` twin, diff id -> append; BOTH survive (soft key never
                                         discards, INV-6)
      4. otherwise                    -> append
    """
    from managers.session_merge import entry_id, entry_hint, same_file

    session = dict(on_disk) if isinstance(on_disk, dict) else {}

    # A readable-but-malformed destination must NOT be treated as empty: doing
    # so would overwrite a session that genuinely holds charts with only the
    # moved entry (GPT Sol finding 4). Refuse instead. A refusal raised here
    # propagates out of save_profile_merged with the lock released, and
    # commit_to_profile reports it truthfully.
    raw = session.get('charts')
    if raw is None:
        charts = []
    elif isinstance(raw, list):
        # Preserve EVERY element verbatim — including any non-dicts — so a
        # single malformed entry is never silently dropped by the move.
        charts = list(raw)
    else:
        raise ValueError(
            f"destination session malformed: 'charts' is {type(raw).__name__}, "
            "not a list")

    # Version guard (GPT Sol finding 1). Our entry is v3-shaped (recipe +
    # updated_at). restore migrates per-DOCUMENT version: a doc labelled
    # < "3.0" — a fresh profile's session.json is written "1.0" by
    # create_profile, and a missing session loads the "1.0" DEFAULT_SESSION —
    # routes EVERY entry, ours included, through _migrate_v2_entry, which reads
    # birth_data/planets_data our entry lacks and DROPS it. Bring the doc to
    # the current schema, but only when that cannot mislabel a real v2 entry.
    # A v2 marker is legacy evidence REGARDLESS of whether `recipe` is a dict:
    # a hybrid entry (`recipe: {}` plus a complete `birth_data`) is RECOVERABLE
    # by _migrate_v2_entry, but if we relabel the doc to v3 restore takes the
    # v3 path, raises on the incomplete recipe, and skips the chart (GPT Sol).
    legacy_present = any(
        isinstance(c, dict)
        and (('birth_data' in c) or ('planets_data' in c) or ('source_params' in c))
        for c in charts)
    raw_ver = session.get('version')
    if raw_ver is None or str(raw_ver).strip() == '':
        pv = (0, 0)                 # missing version -> pre-v3, upgrade if safe
    else:
        pv = _parse_version(raw_ver)
        if pv is None:
            # A present-but-unrecognized version: refuse rather than relabel it
            # (relabeling could mislead restore about the entry shapes).
            raise ValueError(
                f"destination session has an unrecognized version {raw_ver!r}")
    if pv < (3, 0):
        if legacy_present:
            raise ValueError(
                "destination has un-migrated legacy (v2) charts; open that "
                "profile once before moving a chart into it")
        session['version'] = _current_session_version()

    our_id = entry_id(entry_dict)

    # A deliberate re-add supersedes an old removal: drop any tombstone that
    # names our id (SPEC-SES-002 §4.4). Keep every other tombstone verbatim.
    raw_tombs = session.get('tombstones')
    if isinstance(raw_tombs, list) and our_id:
        pruned = [t for t in raw_tombs
                  if not (isinstance(t, dict) and str(t.get('id')) == our_id)]
        if len(pruned) != len(raw_tombs):
            session['tombstones'] = pruned

    # Rule 1 — same id. (Guard isinstance: charts may hold preserved non-dicts.)
    if our_id:
        for i, c in enumerate(charts):
            if isinstance(c, dict) and entry_id(c) == our_id:
                charts[i] = dict(entry_dict)
                session['charts'] = charts
                return session

    # Rule 2 — same file under another uuid: the dest resident wins identity.
    for i, c in enumerate(charts):
        if isinstance(c, dict) and same_file(c, entry_dict):
            merged = dict(entry_dict)
            merged['id'] = c.get('id')
            charts[i] = merged
            session['charts'] = charts
            debug_print(f"[MOVER] Collapsed onto dest resident {c.get('id')} "
                        f"(same file {entry_dict.get('chtk_path')})")
            return session

    # Rules 3 & 4 — append. Log the twin case for observability only.
    our_hint = entry_hint(entry_dict)
    if our_hint is not None:
        for c in charts:
            if isinstance(c, dict) and entry_hint(c) == our_hint and entry_id(c) != our_id:
                debug_print(f"[MOVER] (jd,lat,lon) twin already in dest under "
                            f"{entry_id(c)}; both kept (soft key never discards)")
                break
    charts.append(dict(entry_dict))
    session['charts'] = charts
    return session


def commit_to_profile(profiles_dir, dest_id: str, entry_dict: dict):
    """Locked merged append of `entry_dict` into the dest profile's session.

    Returns `(ok: bool, reason: str | None)`. `ok=False` with a human-readable
    reason when the store refused — lock held elsewhere, an
    unreadable/salvaged baseline, or the profile directory is gone. Expected
    refusals never raise.

    This is the §3.4 step-2 commit-in. It goes through
    `ProfileStore.save_profile_merged` so the write is serialised against the
    other instance's autosave tick (SPEC-SES-002 §4.6). `fence` is left None so
    the on-disk baseline is always loaded and merged.
    """
    from state.profile_store import ProfileStore

    if not dest_profile_exists(profiles_dir, dest_id):
        return False, f"destination profile '{dest_id}' does not exist"

    store = ProfileStore(profiles_dir)
    try:
        ok, info = store.save_profile_merged(
            dest_id, lambda on_disk: _build_dest(on_disk, entry_dict))
    except ValueError as e:
        # A deliberate _build_dest refusal (malformed dest / un-migrated v2):
        # carry its reason verbatim, nothing was written (the lock released).
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"destination write failed: {e}"

    if ok:
        return True, None
    reason = getattr(store, 'last_error', None)
    if info.get('skipped'):
        return False, reason or "another instance is saving the destination"
    return False, reason or "destination write refused"
