# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Favorites Manager — portable favorite-chart store (SPEC-FAV-001).

Favorites live in a single favorites.json inside the default chart
database folder, so they travel with the database across machines.
Each favorite persists the full birth recipe (SPEC-MEM-002 S2.1), so
it reconstructs even if its .chtk file moved or never existed.

Stateless module functions, stdlib only, no Qt. Read only when the
memory-panel context menu opens or the Favorites profile is entered;
the memory panel's refresh/add/select paths never touch this module.
"""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from utils.debug import debug_print
except ImportError:
    debug_print = print

FAVORITES_FILENAME = "favorites.json"
FAVORITES_PROFILE_ID = "favorites"

# Same tolerance as memory-panel dedup (SPEC-MEM-002 S5.1)
_TIMEDEC_TOLERANCE = 0.002


def _utc_now() -> str:
    """ISO 8601 UTC, the same shape SPEC-SES-002 uses for entry updated_at."""
    return datetime.now(timezone.utc).isoformat()


def favorites_file() -> Path:
    """Resolve the favorites.json path (SPEC-FAV-001 S3.1).

    Default chart folder first; user data dir as fallback so the
    feature works before a database folder is configured.
    """
    try:
        from managers.settings_manager import get_settings
        folders = get_settings().get_chart_folders()
        if folders and folders[0]:
            folder = Path(folders[0]).expanduser()
            if folder.is_dir():
                return folder / FAVORITES_FILENAME
    except Exception as e:
        debug_print(f"[FAVORITES] Settings lookup failed: {e}")

    from state.user_data import get_user_data_dir
    data_dir = get_user_data_dir() or Path.home()
    return Path(data_dir) / FAVORITES_FILENAME


def load_favorites() -> list:
    """Return the list of favorite dicts; [] on any error (never raises)."""
    path = favorites_file()
    try:
        if not path.exists():
            return []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        favorites = data.get('favorites', [])
        # Drop entries without a usable recipe rather than crash later
        return [f for f in favorites if isinstance(f.get('recipe'), dict)]
    except Exception as e:
        debug_print(f"[FAVORITES] Failed to read {path}: {e}")
        return []


def _save_favorites(favorites: list) -> bool:
    """Atomic write of the favorites file (tmp + os.replace)."""
    path = favorites_file()
    # 1.1 adds per-favorite 'id' (D-9) and 'updated_at' (D-13). Readers are
    # tolerant of both shapes, so no migration step is needed.
    payload = {'version': '1.1', 'favorites': favorites}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception as e:
        debug_print(f"[FAVORITES] Failed to write {path}: {e}")
        return False


def _key(recipe: dict):
    """Identity key per SPEC-FAV-001 S3.3 (timedec compared separately)."""
    return (
        str(recipe.get('name', '')).lower(),
        recipe.get('year'),
        recipe.get('month'),
        recipe.get('day'),
    )


def _same_chart(r1: dict, r2: dict) -> bool:
    if _key(r1) != _key(r2):
        return False
    try:
        return abs(float(r1.get('timedec', 0.0)) - float(r2.get('timedec', 0.0))) < _TIMEDEC_TOLERANCE
    except (TypeError, ValueError):
        return False


def _same_chart_strict(r1: dict, r2: dict) -> bool:
    """_same_chart PLUS coordinates. Required wherever a match DELETES data.

    `_key()` is name + Y/M/D with no location, so two different people named
    John Smith born 1990-06-15 in Paris and Tokyo compare equal — and with
    noon defaulting to 12:00 for charts of unknown birth time, the timedec
    check does not separate them either. That is tolerable for the context
    menu's is_favorite() (a wrong star icon) and intolerable for the
    duplicate collapse, which removes a favorite permanently. SPEC-FAV-001
    S2 says a favorite persists the full recipe so it reconstructs even if
    its file moved or never existed, which means the favorite can be the
    ONLY copy of that chart.
    """
    if not _same_chart(r1, r2):
        return False
    try:
        return (abs(float(r1.get('lat', 0.0)) - float(r2.get('lat', 0.0))) < 1e-6
                and abs(float(r1.get('lon', 0.0)) - float(r2.get('lon', 0.0))) < 1e-6)
    except (TypeError, ValueError):
        return False


def is_favorite(recipe: dict) -> bool:
    """Membership test against the current favorites file."""
    if not isinstance(recipe, dict):
        return False
    return any(_same_chart(recipe, fav['recipe']) for fav in load_favorites())


def _portable_chtk_path(chtk_path, base_dir: Path):
    """Store chtk_path relative to the favorites folder when inside it."""
    if not chtk_path:
        return None
    try:
        p = Path(chtk_path)
        return str(p.relative_to(base_dir))
    except ValueError:
        return str(chtk_path)


def _resolve_chtk_path(stored, base_dir: Path):
    """Inverse of _portable_chtk_path; None when the file no longer exists."""
    if not stored:
        return None
    p = Path(stored)
    if not p.is_absolute():
        p = base_dir / p
    return str(p) if p.exists() else None


def _favorites_file_is_readable() -> bool:
    """False only when favorites.json EXISTS but cannot be parsed.

    load_favorites() maps every failure to [], so a corrupt file is
    indistinguishable from "no stars". That is fail-OPEN: the sync would
    proceed believing nothing is starred, and the next toggle_favorite would
    rewrite the file from that empty list, discarding the real star list. The
    session side already refuses in this situation; this is the same rule
    applied to the other input.
    """
    path = favorites_file()
    try:
        if not path.exists():
            return True          # absent is legitimately "no favorites yet"
        with open(path, 'r', encoding='utf-8') as f:
            json.load(f)
        return True
    except Exception as e:
        debug_print(f"[FAVORITES] Refusing to sync: {path} is unreadable: {e}")
        return False


def _quarantine_unreadable_favorites() -> bool:
    """Move an unreadable favorites.json aside instead of overwriting it.

    SPEC-FAV-001 S3.4 said a corrupt file "is overwritten on the next toggle".
    That is data loss: load_favorites() maps every failure to [], so one star
    click atomically replaces a salvageable file with a one-entry list — and a
    favorite whose chart file moved or never existed is the ONLY copy of that
    chart (S2). Truncated JSON is usually recoverable by hand; nothing is
    recoverable once it has been overwritten.

    Refusing the toggle instead would break starring until the user noticed a
    debug line. Quarantine gives both: the file survives under a timestamped
    name, and the feature keeps working from an empty list. Same shape as
    SPEC-SES-002 INV-7a. Never deletes (repo rule).

    Returns True when a file was quarantined.
    """
    path = favorites_file()
    if _favorites_file_is_readable():
        return False
    try:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        aside = path.with_name(f"{path.name}.corrupt-{stamp}")
        os.replace(path, aside)
        debug_print(f"[FAVORITES] Unreadable star list moved aside to {aside}")
        return True
    except Exception as e:
        debug_print(f"[FAVORITES] Could not quarantine {path}: {e}")
        return False


def toggle_favorite(entry: dict) -> bool:
    """Add or remove a memory-panel chart entry from favorites.

    Returns True if the chart is a favorite AFTER the toggle.
    Adding an existing favorite replaces it (latest recipe wins).
    """
    recipe = entry.get('recipe')
    if not isinstance(recipe, dict):
        return False

    # load_favorites() maps every failure to [], so a corrupt file looks like
    # "no stars". Starring anything would then atomically overwrite a
    # salvageable file with a one-entry list — and for a favorite whose chart
    # file moved or never existed (SPEC-FAV-001 S2), that favorite is the only
    # copy of the chart. The sync already refuses in this situation; the
    # toggle, which is the far more frequent writer, did not.
    _quarantine_unreadable_favorites()

    favorites = load_favorites()
    kept = [f for f in favorites if not _same_chart(recipe, f['recipe'])]

    if len(kept) < len(favorites):
        _save_favorites(kept)  # was favorite -> removed
        return False

    base_dir = favorites_file().parent
    kept.append({
        'recipe': dict(recipe),
        'mode': entry.get('mode', 'aditya'),
        'ayanamsa': entry.get('ayanamsa', 1),
        'chtk_path': _portable_chtk_path(entry.get('chtk_path'), base_dir),
        # SPEC-PROF-002 D-9: carry the panel entry's id so a later sync
        # MATCHES rather than appends. A fresh uuid per sync made the merge
        # grow the profile without bound.
        'id': entry.get('id') or str(uuid.uuid4()),
        # SPEC-PROF-002 D-13: without a timestamp the favorites side loses
        # every newest-wins tie by construction, so a correction made here
        # could never reach the panel.
        'updated_at': _utc_now(),
    })
    _save_favorites(kept)
    return True


def unstar(recipe: dict, entry_id=None) -> bool:
    """Remove a chart from favorites. True if one was removed.

    SPEC-PROF-002 §5.1.0 rule 1: deleting a chart from the panel also
    unstars it. Nothing writes tombstones yet (SPEC-SES-002 is unbuilt), so
    today this is the ONLY thing standing between a deleted starred chart
    and its resurrection at the next sync. It has to be exact.

    **`entry_id` is why this takes two arguments.** Matching on the recipe
    alone is wrong in both directions:

    - It MISSES. Star a chart at 12:00, adjust its time to 14:30, delete it.
      The star still holds the 12:00 snapshot, `_same_chart` finds no match,
      the star survives, and the next sync brings the chart back at 12:00 —
      the user's deletion silently undone.
    - It OVERMATCHES. `_same_chart` allows 0.002 h, or 7.2 seconds. Delete an
      unstarred rectification variant sitting 3 seconds from its starred
      original and the ORIGINAL loses its star. Rectification variants a few
      seconds apart are exactly this application's work.

    The uuid has neither problem: it survives an edit and it cannot collide.
    The recipe stays as the fallback for pre-1.1 favorites, which have no id.
    """
    if not isinstance(recipe, dict) and not entry_id:
        return False
    _quarantine_unreadable_favorites()

    favorites = load_favorites()
    if entry_id:
        kept = [f for f in favorites if f.get('id') != entry_id]
        if len(kept) < len(favorites):
            _save_favorites(kept)
            debug_print(f"[FAVORITES] Unstarred by id {entry_id}")
            return True
        # An id that matched nothing is not proof of absence: a pre-1.1
        # favorite carries no id at all. Fall through to the recipe.

    if not isinstance(recipe, dict):
        return False
    # Only consider ID-LESS favorites here. One that HAS an id and was not
    # matched above is a different chart, however close its recipe looks.
    kept = [f for f in favorites
            if f.get('id') or not _same_chart(recipe, f.get('recipe') or {})]
    if len(kept) == len(favorites):
        return False
    _save_favorites(kept)
    debug_print(f"[FAVORITES] Unstarred {recipe.get('name')} by recipe (no id)")
    return True


def _recipe_with_consistent_jd(recipe: dict) -> dict:
    """Copy a recipe, re-deriving julian_day when it contradicts civil time.

    Fails safe: if the JD cannot be re-derived it is cleared, because the
    builder honours a stored JD over civil time and a known-stale one is
    worse than none.
    """
    out = dict(recipe)
    if out.get('julian_day') is None:
        return out
    try:
        from core.chart_factory import jd_from_recipe_civil
        civil_jd = float(jd_from_recipe_civil(out))
        # ~0.09 s. Below this the stored value is the more precise of the two
        # (a TOML file's sub-second JD) and must be kept.
        if abs(float(out['julian_day']) - civil_jd) > 1e-6:
            out['julian_day'] = civil_jd
    except Exception as e:
        debug_print(f"[FAVORITES] Could not verify julian_day, clearing: {e}")
        out['julian_day'] = None
    return out


def _read_session(path: Path) -> dict:
    """Read a session file; {} when missing, unreadable or malformed.

    Returning {} for an UNREADABLE file is deliberate and is the one place
    this module can still lose data: it means "no charts to preserve". The
    caller must distinguish that from "no file", which it does via
    path.exists() — see sync_favorites_profile.
    """
    try:
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        debug_print(f"[FAVORITES] Could not read {path}: {e}")
        return {}


def _parse_ts(value):
    """Parse an ISO 8601 timestamp to an aware datetime; None if unusable.

    Timestamps MUST be compared as instants, never as strings. String order
    is not time order once offsets differ: "…T09:00:00+00:00" sorts above
    "…T08:00:00-02:00" while actually being an hour EARLIER, and "…Z" sorts
    above "…+00:00" for the identical instant, which would hand the favorite
    a tie the panel is supposed to win.
    """
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith(('Z', 'z')):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        # Naive means "no offset stated"; read it as UTC so it stays
        # comparable rather than raising on the comparison below.
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _fav_is_newer(fav: dict, entry: dict) -> bool:
    """True only when the favorite provably postdates the panel entry.

    SPEC-PROF-002 D-10: newest wins, ties go to the panel. An entry with no
    updated_at (every entry written before session 3.1) is NOT a tie the
    favorite can win — treating it as one would revert live panel edits on
    every startup, which is the shape of the bug this whole change repairs.
    An UNPARSEABLE timestamp is treated the same way, for the same reason.
    """
    fav_at, entry_at = _parse_ts(fav.get('updated_at')), _parse_ts(entry.get('updated_at'))
    if fav_at is None or entry_at is None:
        return False
    return fav_at > entry_at


def sync_favorites_profile(profiles_dir) -> bool:
    """MERGE favorites.json into profiles/favorites/session.json.

    Never raises. ProfileManager.__init__ calls this and catches only
    OSError (managers/profile_manager.py:122), and the profile-switch call
    site catches nothing, so any other exception escaping here takes the
    whole window down at startup. Failing to sync is recoverable; failing
    to boot is not.

    SPEC-PROF-002 §3. This function used to REGENERATE the session from
    favorites.json, and that is what deleted a user's chart on 2026-07-28:
    the Favorites panel accepts new charts like any other profile, but this
    runs on every startup while that profile is active
    (managers/profile_manager.py:116), so anything not starred was destroyed
    before restore ever read the file. Deterministic, single instance, no
    race involved.

    The contract now: favorites.json is authoritative for WHICH CHARTS ARE
    STARRED and for nothing else. Every other chart in that session is
    preserved, along with every top-level key (ui_state, properly_closed,
    tombstones, current_chart_index). This function only ever adds starred
    charts that are missing and refreshes ones that are provably stale.
    """
    try:
        return _locked_sync(profiles_dir)
    except Exception as e:
        debug_print(f"[FAVORITES] Sync aborted, session left untouched: {e}")
        return False


def _locked_sync(profiles_dir) -> bool:
    """Run the sync inside the cross-process session lock (§4.6 / AC-6).

    This function reads `session.json`, reconciles it against
    `favorites.json`, and writes both. Every step of that was unlocked: it
    could read while another instance was mid-save and then replace the file
    from its stale copy, losing whatever that instance had just added. On the
    FAVORITES profile — the one where a chart was lost on 2026-07-28.

    It cannot be expressed as a merge callback (it rewrites a second file on
    the way through), so it takes the lock directly and writes through the
    store, which is the only thing that opens session.json.

    A lock it cannot take means another instance is saving right now. The
    sync is idempotent and runs again on the next startup or profile switch,
    so skipping is free; writing anyway is the bug.
    """
    try:
        from state.profile_store import ProfileStore
    except Exception:
        # Without the store there is no lock to take. Running unlocked is
        # what this exists to stop, so the sync waits for a better moment.
        debug_print("[FAVORITES] No profile store available; sync skipped")
        return False

    store = ProfileStore(profiles_dir)
    with store.profile_lock(FAVORITES_PROFILE_ID) as held:
        if not held:
            debug_print("[FAVORITES] Another instance is saving; sync skipped")
            return False
        return _sync_favorites_profile(profiles_dir, store=store)


def _sync_favorites_profile(profiles_dir, store=None) -> bool:
    """The sync itself. MUST be called with the profile lock held — see
    `_locked_sync`, which is the only caller. `store` is that lock's owner and
    is also what performs the write."""
    if not _favorites_file_is_readable():
        return False
    favorites = load_favorites()
    base_dir = favorites_file().parent
    session_path = Path(profiles_dir) / FAVORITES_PROFILE_ID / "session.json"

    existed = session_path.exists()
    session = _read_session(session_path)
    if existed and not session:
        # Unreadable, not absent. Regenerating here would destroy exactly what
        # this fix exists to protect, so refuse and leave the file for the user
        # (or for SPEC-SES-002's salvage) rather than overwrite it.
        debug_print(f"[FAVORITES] Refusing to sync over an unreadable {session_path}")
        return False

    # Structural validation. The JSON parsed, which does not make it a
    # session: charts:[null] or tombstones:[{"id":[]}] are readable and would
    # raise inside the merge. This runs in ProfileManager.__init__, which only
    # catches OSError, so an uncaught raise here does not degrade the sync —
    # it takes the whole window down at startup. Refuse, like an unreadable file.
    raw_charts = session.get('charts')
    if raw_charts is not None and not isinstance(raw_charts, list):
        debug_print(f"[FAVORITES] Refusing to sync: 'charts' is {type(raw_charts).__name__}")
        return False
    charts = [c for c in (raw_charts or []) if isinstance(c, dict)]
    if len(charts) != len(raw_charts or []):
        debug_print("[FAVORITES] Dropped non-dict entries from charts")

    raw_tombs = session.get('tombstones')
    if raw_tombs is not None and not isinstance(raw_tombs, list):
        # Silently reading a non-list as "no tombstones" is the dangerous
        # failure: every deleted-and-still-starred chart would resurrect. A
        # tombstone list we cannot read is a reason to refuse, exactly like
        # an unreadable session.
        debug_print(f"[FAVORITES] Refusing to sync: 'tombstones' is "
                    f"{type(raw_tombs).__name__}, not a list")
        return False
    tombstoned = {
        t['id'] for t in (raw_tombs or [])
        # Unhashable ids (list/dict) would raise building this set.
        if isinstance(t, dict) and isinstance(t.get('id'), str) and t['id']
    }

    # by_id and claimed_ids are LIVE, not a pre-loop snapshot: a favorite
    # processed later must see what an earlier one appended or adopted, or
    # duplicate favorites append twice under one id and two stars adopt the
    # same panel entry.
    by_id = {}
    for i, c in enumerate(charts):
        cid = c.get('id')
        if isinstance(cid, str) and cid and cid not in by_id:
            by_id[cid] = i
    claimed_ids = {f.get('id') for f in favorites if f.get('id')}
    favorites_dirty = False

    # Collapse duplicate stars BEFORE merging. Two favorites for one chart is
    # never meaningful, and without this the id-less pair appends twice (the
    # recipe fallback skips the entry the first one just claimed).
    deduped, dupes = [], []
    for fav in favorites:
        r = fav.get('recipe')
        hit = None
        if isinstance(r, dict):
            for i, k in enumerate(deduped):
                # STRICT: this branch deletes a favorite.
                if _same_chart_strict(r, k.get('recipe') or {}):
                    hit = i
                    break
        if hit is None:
            deduped.append(fav)
            continue
        # Keep the NEWEST of a duplicate group. First-wins would discard a
        # correction the user made later (a mode change, a fixed recipe) and
        # rewrite the file without it — a silent alteration of the star.
        if _fav_is_newer(fav, deduped[hit]):
            dupes.append(deduped[hit])
            deduped[hit] = fav
        else:
            dupes.append(fav)
    if dupes:
        debug_print(f"[FAVORITES] Collapsed {len(dupes)} duplicate star(s)")
        favorites, favorites_dirty = deduped, True

    # Two DISTINCT stars sharing one id: the second matches the first's entry
    # by id, loses the newest-wins tie, and is never appended — a starred
    # chart with no panel entry, preserved by every later sync. Re-mint so
    # each star owns an id. (A star whose RECIPE differs from its matched
    # entry is a correction, not a collision; the id still identifies it.)
    _seen_ids = set()
    for fav in favorites:
        fid = fav.get('id')
        if not fid:
            continue
        if fid in _seen_ids:
            debug_print(f"[FAVORITES] Re-minting duplicate star id {fid}")
            fav['id'] = str(uuid.uuid4())
            favorites_dirty = True
        _seen_ids.add(fav['id'])

    stale_stars = []

    # Iterate a copy: stale stars are collected and dropped after the loop,
    # never removed mid-iteration (that silently skips the next favorite).
    for fav in list(favorites):
        recipe = fav.get('recipe')
        if not isinstance(recipe, dict):
            continue

        fav_id = fav.get('id')
        idx = by_id.get(fav_id) if fav_id else None

        if idx is None:
            # Fall back to the S3.3 predicate, but only onto entries no other
            # favorite has claimed by id. Matching a claimed entry would let
            # one star adopt another star's chart.
            for i, c in enumerate(charts):
                if c.get('id') in claimed_ids:
                    continue
                if _same_chart(recipe, c.get('recipe') or {}):
                    idx = i
                    break

        if idx is not None:
            entry = charts[idx]
            # Adopt the panel's id so the next sync matches on key 1, and
            # record it LIVE so no later favorite adopts the same entry.
            entry_id = entry.get('id')
            if isinstance(entry_id, str) and entry_id and fav.get('id') != entry_id:
                fav['id'] = entry_id
                claimed_ids.add(entry_id)
                by_id.setdefault(entry_id, idx)
                favorites_dirty = True
            # chtk_path is provenance, not user data: filling in a MISSING one
            # cannot revert an edit, so it is always safe and always a gain
            # (the file may simply not have existed at the last sync). Only
            # OVERWRITING an existing path needs the newest-wins guard.
            resolved = _resolve_chtk_path(fav.get('chtk_path'), base_dir)
            if resolved and not entry.get('chtk_path'):
                entry['chtk_path'] = resolved
                # SPEC-SES-002 D-12 lists "given a file path" as a mutation
                # that stamps. The merge compares `chtk_path`, so an unstamped
                # change here means one instance has the path, the other does
                # not, the timestamps tie, each side keeps its own — and the
                # file flips every 30 s until whichever exits last decides.
                entry['updated_at'] = _utc_now()

            if _fav_is_newer(fav, entry):
                # A favorite is a SNAPSHOT and may carry a julian_day that no
                # longer agrees with its own civil time (any star taken before
                # the td-nbl8 fix). Copying it wholesale would let that stale
                # instant win on the next rebuild — td-nbl8 again, through a
                # side door. LIVE since SPEC-SES-002 §4.5 started stamping
                # entries; before that `_fav_is_newer` could never be true.
                entry['recipe'] = _recipe_with_consistent_jd(recipe)
                entry['mode'] = fav.get('mode', entry.get('mode', 'aditya'))
                entry['ayanamsa'] = fav.get('ayanamsa', entry.get('ayanamsa', 1))
                if resolved:
                    entry['chtk_path'] = resolved
                # The content changed, so the stamp the merge reads has to
                # change with it — otherwise the other instance's older copy
                # wins the next comparison and undoes this.
                entry['updated_at'] = _utc_now()
            continue

        # Not in the session at all.
        if fav_id and fav_id in tombstoned:
            # SPEC-PROF-002 §5.1.0 rule 2. The chart was deleted from the
            # panel somewhere this star did not see. Re-appending it would
            # hand the merge something it is contractually obliged to drop,
            # forever. Drop the stale star instead.
            debug_print(
                f"[FAVORITES] Dropping stale star for deleted chart "
                f"{recipe.get('name')} ({fav_id})"
            )
            stale_stars.append(fav)
            favorites_dirty = True
            continue

        if not fav_id or fav_id in by_id:
            # No id, or an id another chart in this session already carries
            # (duplicate stars in a pre-1.1 file). Minting keeps ids unique,
            # which the merge in SPEC-SES-002 depends on absolutely.
            fav['id'] = str(uuid.uuid4())
            favorites_dirty = True
        by_id[fav['id']] = len(charts)
        claimed_ids.add(fav['id'])
        charts.append({
            'id': fav['id'],
            'recipe': dict(recipe),
            'mode': fav.get('mode', 'aditya'),
            'ayanamsa': fav.get('ayanamsa', 1),
            'chtk_path': _resolve_chtk_path(fav.get('chtk_path'), base_dir),
            'is_transit': False,
        })

    if stale_stars:
        # Compare by object identity, not value: two favorites can be equal
        # dicts (same chart starred twice by an older buggy write) and only
        # the collected one should go.
        drop = {id(f) for f in stale_stars}
        favorites = [f for f in favorites if id(f) not in drop]
    if favorites_dirty:
        _save_favorites(favorites)

    # Preserve every key already on disk. In particular do NOT stamp
    # properly_closed: this function cannot know whether the app closed
    # cleanly, and asserting True erases the crash signal restore depends on.
    session_data = dict(session)
    session_data.setdefault('version', '3.0')
    session_data['charts'] = charts
    # int() guard: a non-int index is readable JSON that would raise on the
    # comparison, and this runs at startup where a raise costs the window.
    cci = session_data.get('current_chart_index')
    if (not isinstance(cci, int) or isinstance(cci, bool)
            or cci < -1 or cci >= len(charts)):
        session_data['current_chart_index'] = 0 if charts else -1

    try:
        session_path.parent.mkdir(parents=True, exist_ok=True)
        if store is not None:
            # Through the store, which is the one place that opens this file
            # (§4.6). Its own temp-name-per-writer and fsync are what make the
            # replace safe; a second hand-rolled writer here was how two
            # copies of that logic came to exist.
            written = store.save_profile(FAVORITES_PROFILE_ID, session_data)
            if not written:
                debug_print(f"[FAVORITES] Store refused the write: "
                            f"{getattr(store, 'last_error', None)}")
                return False
        else:
            # No store: callers that reach here are tests exercising the
            # reconciliation alone. Kept explicit so it cannot become the
            # production path again by accident.
            fd, tmp = tempfile.mkstemp(dir=str(session_path.parent), suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(session_data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, session_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        debug_print(f"[FAVORITES] Synced {len(charts)} favorites to {session_path}")
        return True
    except Exception as e:
        debug_print(f"[FAVORITES] Failed to sync favorites profile: {e}")
        return False
