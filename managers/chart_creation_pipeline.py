# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Shared chart-creation pipeline (SPEC-TRN-005 D-7, closes SPEC-UTC-001 §3.2
row 5 for the Add Chart path).

Core-level by decision D-7: AddChartDialog ships in Lite, so this module must
be importable without anything from pro/.

Flow (one function, staged):

    text -> parse_birth_text -> resolve_location (geocode)
         -> offset resolution   (ZoneInfo-backed, the dialog's historical
                                 core.time_utils.lmt_corrected_offset
                                 semantics: LMT-era longitude/15, fold=1 on
                                 fold-sensitive instants, DST flag; gap
                                 [nonexistent] local times warn)
         -> UTC                 (BirthDataManager.create_from_form_data —
                                 the ONLY local->UTC seam; INV-3 "one UTC
                                 road". NO inline timedelta/ZoneInfo math
                                 here or in any caller.)
         -> JD                  (swe.julday on the BDM UTC components)
         -> build_chart_from_params (single terminal constructor)
         -> ALWAYS a collision-safe file write (.toml via core.toml_chart,
                                 .chtk via core.chtk_writer)

Contract points (each is a recorded review finding — do not regress):

* Offset-resolution failure is an EXPLICIT error result (`ok=False`,
  `error_stage='offset'`). The legacy dialog silently treated local time as
  UTC when resolution raised (add_chart_dialog_qt.py old :269-273) — that
  fallback is forbidden.
* Offset-key duality: BirthDataManager emits `utc_offset_hours`; the
  recipe/birth_data path (core_gui_qt.py) uses `utcoffset`. The result
  carries BOTH keys explicitly, always set together, never via `or`-chains
  (0.0 is a legitimate value).
* Persistence is UNCONDITIONAL (SPEC-PERSIST-001 INV-1). It was opt-in
  until 2026-07-28, when a chart created through Add Chart existed only in
  session.json and was lost when that file was regenerated. Every creation
  now writes a file, .toml by default, into <chart folder>/<active
  profile>/. Filenames get a numeric suffix on collision, reserved
  atomically via O_CREAT|O_EXCL (no check-then-write window), never
  overwrite. A write failure does NOT discard the chart (td-u84e): ok stays
  True and `persist_error` says why there is no file.
* Offset resolution is ZONEINFO-backed (lmt_corrected_offset semantics),
  NOT the pytz resolve_total_offset path: pytz classifies dates through
  1901 as LMT in zones where ZoneInfo reports a standardized offset
  (Auckland 1900 +11:30, Sydney 1900 +10:00, Chatham 1900 +12:15 — the
  pytz path silently substituted longitude/15, up to 24h wrong at the
  date line), and pytz resolves DST spring-forward gap instants with
  is_dst=False (pre-transition) where the old dialog took ZoneInfo fold=1
  (post-transition). Both are recorded review findings — do not swap the
  resolver back. Gap instants additionally surface WARN_GAP_TIME
  (additive; `ok` stays True).
* Precision note: the canonical seam is minute-precision on the offset
  (offset strings "+HH:MM", CHTK line 13 stores ":00" seconds), so LMT-era
  longitude/15 offsets are rounded to the nearest minute — this matches the
  Edit Chart / New Chart / CHTK-load family, which the Add Chart path now
  joins.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Warning kinds passed to on_warning(kind, message)
WARN_DATE_AMBIGUITY = "date_ambiguity"
WARN_NO_TIME = "no_time"
WARN_GEOCODE_FAILED = "geocode_failed"
WARN_GAP_TIME = "gap_time"  # nonexistent local time (DST spring-forward gap)

# error_stage values
STAGE_PARSE = "parse"
STAGE_GEOCODE = "geocode"
STAGE_OFFSET = "offset"
STAGE_UTC = "utc"
STAGE_BUILD = "build"
STAGE_PERSIST = "persist"

# Chart file formats (SPEC-PERSIST-001). Defined here, above first use.
CHART_FORMAT_TOML = "toml"
CHART_FORMAT_CHTK = "chtk"
CHART_FORMATS = (CHART_FORMAT_TOML, CHART_FORMAT_CHTK)

#: Test seam. When set, EVERY write from this pipeline is redirected here and
#: the profile subfolder is skipped. Exists so a test can never reach the
#: user's real database — the failure mode that put Marie_Dupont.chtk in it.
CHART_FOLDER_ENV = "VARUNA360_CHART_FOLDER"


@dataclass
class ChartCreationResult:
    """Result of create_chart_from_text. Recipe/memory-compatible payload."""
    ok: bool = False
    error: Optional[str] = None
    error_stage: Optional[str] = None
    warnings: List[Tuple[str, str]] = field(default_factory=list)

    chart: Any = None                       # libaditya Chart (terminal build)
    jd: Optional[float] = None

    name: str = ""
    city: str = ""
    country: str = ""
    location_label: str = ""                # "City, Country" or "City"
    gender: str = "Unknown"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    tz_name: str = ""                       # IANA name from geocoding

    # Offset-key duality (recorded finding): BOTH keys, always set together.
    utc_offset_hours: Optional[float] = None   # BirthDataManager convention
    utcoffset: Optional[float] = None          # recipe/birth_data convention
    dst_flag: int = 0
    std_offset_str: str = ""                # standard-base "+HH:MM" string

    parsed: Optional[Dict[str, Any]] = None       # parse_birth_text output
    birth_data: Optional[Dict[str, Any]] = None   # BDM canonical dict
    planets_data: Optional[Dict[str, Any]] = None # legacy dialog dict shape
    # INV-7: the file every creation path must record into its panel entry.
    file_path: Optional[str] = None               # the file that was written
    chart_format: Optional[str] = None            # 'toml' | 'chtk'
    # Legacy alias, set ONLY when the written file really is CHTK. Callers
    # that hand this to a CHTK-specific reader must not receive a .toml.
    chtk_path: Optional[str] = None
    # A persist failure is NOT a creation failure (td-u84e). The chart is
    # calculated, valid and returned with ok=True; this carries WHY no file
    # exists so the caller can say so without discarding the user's work.
    persist_error: Optional[str] = None


def _error(result: ChartCreationResult, stage: str, message: str) -> ChartCreationResult:
    result.ok = False
    result.error_stage = stage
    result.error = message
    return result


def _persist_failed(result: ChartCreationResult, message: str) -> ChartCreationResult:
    """Record that the FILE could not be written, and keep the chart.

    td-u84e. Stage 6 used to call _error(), which sets ok=False — and both
    callers do `if not result.ok: abort`. So a read-only chart folder threw
    away a chart that had already been parsed, geocoded, UTC-resolved and
    built. Reachable in production via pro/panels/transit_panel.py:1840,
    the one caller that passes persist_chart=True.

    Once SPEC-PERSIST-001 makes writing unconditional, EVERY creation would
    inherit that behaviour. Losing the chart is never the right answer to
    "the disk said no"; reporting loudly is (INV-6, surfaced by td-rx09).

    error_stage/error stay set so existing diagnostics keep working, but ok
    stays True and the caller is expected to check persist_error.
    """
    result.error_stage = STAGE_PERSIST
    result.error = message
    result.persist_error = message
    result.chtk_path = None
    result.file_path = None
    return result


def _sanitize_filename(name: str) -> str:
    import re
    from core.fs_safety import windows_safe_filename
    safe = re.sub(r'[^\w\s-]', '', name or 'Unknown').strip().replace(' ', '_')
    # The regex removes every character Windows forbids but leaves the DOS
    # device names intact. "Con" would reach _collision_safe_path, which does
    # os.open() on it — on Windows that reaches the console device, not a file.
    return windows_safe_filename(safe or 'Unknown', default='Unknown')


def _collision_safe_path(folder, base_name: str, ext: str = CHART_FORMAT_CHTK):
    """Atomically RESERVE and return a Path in `folder` named
    `base_name.<ext>`, numeric-suffixed if taken. NEVER overwrites.

    `ext` follows the chosen format. It used to be a hardcoded '.chtk', which
    would have written TOML payloads under a .chtk name the moment the default
    format changed — a file every reader would then mis-parse.

    The chosen path is created empty via os.open(O_CREAT | O_EXCL | mode
    0o644) inside the suffix loop (FileExistsError -> next suffix), so two
    concurrent callers can never claim the same name — there is no
    check-then-write window. O_CREAT|O_EXCL also refuses to create through
    an existing name of ANY kind (including a symlink at the target), so a
    planted symlink forces a suffix advance instead of a follow.

    The reservation is a placeholder only. The caller writes the payload to
    a sibling temp file and os.replace()s it onto this reserved name (an
    atomic, symlink-safe swap), so the canonical writer never re-opens the
    final pathname with plain 'w' (no symlink/replace window; finding 1)."""
    import os
    from pathlib import Path
    folder = Path(folder)
    ext = (ext or CHART_FORMAT_CHTK).lstrip(".")
    n = 0
    while True:
        stem = base_name if n == 0 else f"{base_name}_{n}"
        candidate = folder / f"{stem}.{ext}"
        try:
            # mode 0o644 (finding 3): O_CREAT without a mode defaults to
            # 0o777 & ~umask, leaving world/group-writable chart files.
            fd = os.open(
                str(candidate),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        return candidate


def _unlink_if_empty_reservation(path) -> None:
    """Remove `path` iff it is still the empty placeholder this call created
    (finding 2): a regular, zero-length file. lstat (never follows a symlink)
    + S_ISREG + size 0 guard so a real chart or a planted symlink is never
    touched. Best-effort — cleanup errors are swallowed (the caller is
    already surfacing the original write failure unchanged)."""
    import os
    import stat
    try:
        st = os.lstat(str(path))
    except OSError:
        return
    if stat.S_ISREG(st.st_mode) and st.st_size == 0:
        try:
            os.unlink(str(path))
        except OSError:
            pass


def persist_birth_data(birth_data: Dict[str, Any], *,
                       name: Optional[str] = None,
                       chart_folder: Optional[str] = None,
                       chart_format: Optional[str] = None,
                       julian_day: Optional[float] = None
                       ) -> Tuple[Optional[str], str, Optional[str]]:
    """Write ONE canonical birth-data dict to a chart file. INV-1's only road.

    Every creation path needs this, not just the text pipeline: the New Chart
    form, the web-search import and the exploration panel each build a chart
    their own way, and each of them wrote nothing (or wrote into a folder of
    its own choosing). One function so they cannot drift apart on format,
    location, collision handling or atomicity.

    `birth_data` MUST be the canonical BirthDataManager dict (the one with
    local_* keys). The TOML writer reads utc_offset_hours as a TOTAL only
    when it sees those keys and as an already-base offset otherwise, so the
    raw shape silently stores a DST chart an hour late.

    Returns (path, format, error). `error` is None on success; on failure
    `path` is None and the caller must report the message WITHOUT discarding
    the chart (INV-6 / td-u84e).
    """
    import os
    import uuid
    from pathlib import Path

    fmt = (chart_format or default_chart_format()).strip().lower().lstrip(".")
    if fmt not in CHART_FORMATS:
        fmt = CHART_FORMAT_TOML

    folder = chart_folder or resolve_chart_target_folder()
    if not folder:
        return _record_failure(
            fmt, None, None,
            "No chart folder could be resolved or created; the chart was "
            "calculated but not saved to a file.")

    label = name or birth_data.get("name") or "Unknown"
    payload = dict(birth_data)
    if julian_day is not None:
        # Store the instant the app actually computed rather than letting the
        # writer re-derive it from civil time: a chart that reloads to a
        # different moment than the one on screen is the td-nbl8 failure.
        payload["julian_day"] = float(julian_day)

    out_path = None
    tmp_path = None
    try:
        # Reserve the final name atomically (never overwrite, symlink-safe).
        out_path = _collision_safe_path(folder, _sanitize_filename(label), ext=fmt)
        # Write the payload to a sibling temp file, then os.replace it onto
        # the reserved name. The writer opens only the fresh temp (created
        # O_EXCL, unpredictable uuid name), and os.replace is an atomic,
        # symlink-safe swap — so the final pathname is never re-opened with
        # plain 'w' (finding 1) and a failed write leaves no orphan / suffix
        # drift (finding 2).
        tmp_path = out_path.with_name(f"{out_path.name}.tmp-{uuid.uuid4().hex}")
        # O_EXCL + mode 0o644: the temp inherits the intended perms; the
        # writers truncate that inode without changing its mode, and
        # os.replace preserves it onto the reserved name.
        _fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(_fd)
        if fmt == CHART_FORMAT_TOML:
            from core.toml_chart import TOMLChartWriter
            TOMLChartWriter().write(payload, str(tmp_path))
        else:
            # Rule 6 sign inversion lives in the canonical CHTK writer:
            # LOCAL time components + standard-base offset string + DST flag.
            from core.chtk_writer import create_chtk
            from core.time_utils import format_offset
            flag = payload.get("time_change_flag") or 0
            dst = payload.get("dst_offset_hours")
            if dst is None:
                dst = float(flag) if flag in (1, 2) else 0.0
            std_hours = float(payload.get("utc_offset_hours") or 0.0) - float(dst)
            create_chtk(
                name=label,
                year=int(payload["local_year"]), month=int(payload["local_month"]),
                day=int(payload["local_day"]), hour=int(payload["local_hour"]),
                minute=int(payload["local_minute"]),
                second=int(payload.get("local_second") or 0),
                lat=float(payload.get("latitude") or 0.0),
                lon=float(payload.get("longitude") or 0.0),
                city=payload.get("city") or "",
                country=payload.get("country") or "Unknown",
                timezone_offset=format_offset(0, int(round(std_hours * 60))),
                dst_active=bool(flag),
                gender=payload.get("gender") or "Unknown",
                output_path=str(tmp_path),
            )
        os.replace(str(tmp_path), str(out_path))
        # A successful write RESOLVES any standing warning (INV-6/td-rx09).
        try:
            from managers.persist_health import record_write_success
            record_write_success()
        except Exception:
            pass          # health bookkeeping must never break a good write
        index_new_chart_file(out_path)
        return str(out_path), fmt, None
    except Exception as e:
        # Never leave the temp or the empty reservation behind; surface the
        # original error unchanged (no suffix advance on a retry).
        if tmp_path is not None:
            try:
                if os.path.exists(str(tmp_path)):
                    os.unlink(str(tmp_path))
            except OSError:
                pass
        if out_path is not None:
            _unlink_if_empty_reservation(Path(out_path))
        return _record_failure(fmt, folder, label, f".{fmt} write failed: {e}")


def index_new_chart_file(path) -> bool:
    """Make a freshly written chart findable without a rebuild (INV-8).

    A new chart used to be invisible in Find Chart until a full index
    rebuild, which over thousands of files is slow enough that the honest
    advice was not to bother — so new charts were simply not findable.
    One file, one entry (SPEC-FIND-003 3.5 already allows single-entry
    updates).

    SUPPRESSED under VARUNA360_CHART_FOLDER (spec §4.5): a harness or test
    run writes into a temp directory that disappears afterwards, and those
    paths would enter the user's REAL index and stay there — poisoning the
    oracle SPEC-EXPORT-001 consults to decide which charts have no file.
    The redirect means "this write is not part of the user's database", and
    the index has to honour that too, not just the folder.

    Best-effort: an index failure must never turn a good write into a
    reported failure. Returns True when the entry was added.
    """
    import os
    if os.environ.get(CHART_FOLDER_ENV):
        return False
    try:
        from cache.chart_index_cache import ChartIndexCache
        return ChartIndexCache().add_file(str(path)) is not None
    except Exception as e:
        _log(f"[PERSIST] Could not index {path}: {e}")
        return False


def _record_failure(fmt: str, folder, name, message: str):
    """Persist the failure, then return the (path, fmt, error) triple.

    Both failure exits go through here so a future third exit cannot forget
    the persisted half — the status bar is momentary, and this is what the
    user still sees tomorrow.
    """
    try:
        from managers.persist_health import record_write_failure
        record_write_failure(message, folder=folder, chart_name=name)
    except Exception:
        pass
    return None, fmt, message


def _resolve_offset_zoneinfo(tz_name: str, year: int, month: int, day: int,
                             hour: int, minute: int, second: int,
                             longitude: float):
    """ZoneInfo-backed offset resolution — the Add Chart dialog's historical
    semantics (core.time_utils.lmt_corrected_offset), decomposed for the
    minute-precision BirthDataManager seam.

    Returns (std_hours, dst_flag, is_gap):

    * total = lmt_corrected_offset(...): ZoneInfo TOTAL at the instant,
      fold=1 preferred on fold-sensitive instants (spring-forward gap ->
      post-transition offset), longitude/15 only when ZoneInfo itself
      labels the date LMT.
    * dst_flag = 1 iff the resolved instant has dst() > 0, never 2 (war
      time is user-asserted only, SPEC-TZ-001 5g); std = total - flag, so
      std + flag == total always (decompose-from-total rule).
    * is_gap: PEP 495 nonexistent-local-time detection (a UTC round-trip
      changes the wall time) — callers surface WARN_GAP_TIME.

    Deliberately NOT core.time_utils.resolve_total_offset (pytz): recorded
    review findings — pytz LMT-classifies pre-1902 standardized zones and
    resolves gap instants is_dst=False, both diverging from the dialog's
    behavior this pipeline must preserve (see module docstring).
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from core.time_utils import lmt_corrected_offset

    total_hours = lmt_corrected_offset(
        tz_name, year, month, day, hour, minute, second, longitude)

    tz = ZoneInfo(tz_name)
    dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
    if dt.tzname() == 'LMT':
        # LMT-era chart-city longitude/15 (already what total_hours holds).
        return total_hours, 0, False

    round_trip = dt.astimezone(timezone.utc).astimezone(tz)
    is_gap = round_trip.replace(tzinfo=None) != dt.replace(tzinfo=None)

    dt_fold1 = dt.replace(fold=1)
    resolved = dt_fold1 if dt.utcoffset() != dt_fold1.utcoffset() else dt
    dst = resolved.dst()
    dst_hours = dst.total_seconds() / 3600.0 if dst is not None else 0.0
    flag = 1 if dst_hours > 0 else 0
    return total_hours - flag, flag, is_gap


def _log(msg: str) -> None:
    try:
        from utils.debug import debug_print
        debug_print(msg)
    except Exception:
        print(msg)


def default_chart_folder() -> Optional[str]:
    """CHTK default chart folder from SettingsManager (paths.default_folder,
    falling back to the first existing configured chart folder). None when
    nothing usable is configured — callers must treat that as an explicit
    persistence error, never write to an improvised location."""
    from pathlib import Path
    try:
        from managers.settings_manager import get_settings
        s = get_settings()
        candidates: List[str] = []
        default = s.get("paths.default_folder", "")
        if default:
            candidates.append(default)
        try:
            candidates.extend(s.get_chart_folders())
        except Exception:
            pass
        try:
            from utils.path_translator import translate_path
        except Exception:
            translate_path = None
        for folder in candidates:
            if not folder:
                continue
            p = translate_path(folder) if translate_path else folder
            if p and Path(p).exists():
                return str(p)
    except Exception:
        pass
    return None


def platform_default_chart_folder():
    """The per-OS conventional chart database location, as a Path.

    Matches where the CHTK database already lives on both platforms
    ~/Documents/Kala/Charts on both platforms. Not created here.
    """
    from pathlib import Path
    return Path.home() / "Documents" / "Kala" / "Charts"


def ensure_default_chart_folder(create: bool = True) -> Optional[str]:
    """Resolve a usable chart folder, establishing the default if there is none.

    SPEC-PERSIST-001 D-14. `paths.default_folder` ships as "" and the
    first-run dialog only fires when no bootstrap config exists, so BOTH a
    fresh install and an existing install with an empty setting have nowhere
    to write. Under INV-1 ("every creation writes a file") that turns into
    "always fails, loudly, forever" — a warning the user cannot act on from
    the failure message alone.

    This is NOT the improvisation `default_chart_folder()`'s contract
    forbids. That rule exists so a chart never lands in a hidden location the
    user cannot find. Here the path is the documented per-OS convention, it
    is PERSISTED to settings so it appears in the Settings UI, and it is
    logged. The user can see it and change it.

    Returns the folder, or None when even the default could not be created
    (read-only home, missing permissions) — which remains a real, reportable
    persistence failure.
    """
    from pathlib import Path
    existing = default_chart_folder()
    if existing:
        return existing

    target = platform_default_chart_folder()
    # Packaged installs write inside the data directory the user chose in
    # the first-run dialog instead of the per-OS Kala convention. On macOS
    # ~/Documents is TCC-protected — the first-run default was picked to
    # avoid it, so sending charts there anyway would either trigger a
    # permission prompt or silently fail; and the user who just chose a
    # folder expects their charts under it (mac VM test, 2026-08-11).
    # Dev/source runs keep the Kala convention unchanged.
    try:
        from state.user_data import get_user_data_dir, is_frozen
        if is_frozen():
            base = get_user_data_dir()
            if base:
                target = Path(base) / "Charts"
    except Exception:
        pass
    try:
        if create:
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            return None
    except Exception as e:
        _log(f"[PERSIST] Could not create the default chart folder {target}: {e}")
        return None

    try:
        from managers.settings_manager import get_settings
        s = get_settings()
        s.set("paths.default_folder", str(target))
        folders = list(s.get_chart_folders() or [])
        if str(target) not in folders:
            s.set("paths.chart_folders", folders + [str(target)])
        # set() persists on its own (save=True); SettingsManager has no
        # save(), so an explicit call here would only raise into the except.
        _log(f"[PERSIST] No chart folder was configured; defaulted to {target}")
    except Exception as e:
        _log(f"[PERSIST] Defaulted to {target} but could not persist it: {e}")
    return str(target)


# ---------------------------------------------------------------------------
# SPEC-PERSIST-001 INV-1/INV-3: where a new chart goes, and in which format
# ---------------------------------------------------------------------------


def default_chart_format() -> str:
    """The format NEW charts are written in — .toml unless configured otherwise.

    Lorris's decision (2026-07-28): .toml becomes the default; CHTK stays
    fully supported and remains the Kala interchange format. This governs
    WRITING ONLY. Both formats are read, and nothing already on disk is
    converted — a CHTK chart stays CHTK until the user exports it.

    An unrecognised setting falls back to .toml rather than raising: a typo in
    a config file must not stop a chart from being saved.
    """
    try:
        from managers.settings_manager import get_settings
        fmt = str(get_settings().get("paths.default_chart_format", "") or "")
        fmt = fmt.strip().lower().lstrip(".")
        if fmt in CHART_FORMATS:
            return fmt
        if fmt:
            _log(f"[PERSIST] Unknown paths.default_chart_format {fmt!r}; "
                 f"writing {CHART_FORMAT_TOML}")
    except Exception:
        pass
    return CHART_FORMAT_TOML


def active_profile_id() -> str:
    """The active profile id, read straight from _active_profile.txt.

    ProfileManager owns this file but needs the running app; this module is
    core-level and runs headless (Lite, CLI, tests), so the file is read
    directly. Same path resolution, same "default" fallback — a divergence
    here would scatter charts across the wrong profile folders.
    """
    from pathlib import Path
    try:
        from state.user_data import get_user_data_dir
        base = get_user_data_dir()
        if not base:
            import os as _os
            base = Path(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        f = Path(base) / "profiles" / "_active_profile.txt"
        if f.exists():
            name = f.read_text(encoding="utf-8").strip()
            if name:
                return name
    except Exception as e:
        _log(f"[PERSIST] Could not read the active profile: {e}")
    return "default"


def _profile_folder(base, profile_id: str, create: bool = True):
    """`base`/<profile>, created on demand. Returns None if it cannot exist.

    D-16 (folder-name collision): the profile id is a folder name inside a
    directory the user also fills with chart FILES. If the name is taken by
    something that is not a directory, advance to `<name>_2`, `<name>_3`
    rather than failing — the user keeps their file and still gets a folder.
    """
    from pathlib import Path
    base = Path(base)
    stem = _sanitize_filename(profile_id) or "default"
    n = 1
    while n < 100:
        candidate = base / (stem if n == 1 else f"{stem}_{n}")
        if candidate.is_dir():
            return candidate
        if candidate.exists():          # a FILE (or symlink) holds the name
            _log(f"[PERSIST] {candidate} is not a directory; trying the next name")
            n += 1
            continue
        if not create:
            return None
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            n += 1                      # lost a race; re-examine as above
            continue
        except Exception as e:
            _log(f"[PERSIST] Could not create the profile folder {candidate}: {e}")
            return None
    return None


def resolve_chart_target_folder(base_folder: Optional[str] = None,
                                create: bool = True) -> Optional[str]:
    """Where a newly created chart is written: <chart folder>/<active profile>/.

    SPEC-PERSIST-001 INV-3. Per-profile subfolders keep one person's charts
    from silting up another's, and give "add profile from folder" something
    to point at.

    Resolution order:
      1. VARUNA360_CHART_FOLDER (test seam) — used verbatim, NO profile
         subfolder, so a test's expectations are exactly what it set.
      2. `base_folder` if given, else ensure_default_chart_folder().
      3. + the active profile subfolder.

    Falls back to the base folder (never to nothing) when the profile
    subfolder cannot be created: a chart in the right database under the
    wrong folder is recoverable; an unwritten chart is not.
    """
    import os
    from pathlib import Path

    override = os.environ.get(CHART_FOLDER_ENV)
    if override:
        p = Path(override)
        if create:
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                _log(f"[PERSIST] {CHART_FOLDER_ENV}={override} is unusable: {e}")
                return None
        elif not p.is_dir():
            return None
        return str(p)

    base = base_folder or ensure_default_chart_folder(create=create)
    if not base:
        return None
    sub = _profile_folder(base, active_profile_id(), create=create)
    if sub is None:
        _log(f"[PERSIST] Falling back to {base} (no profile subfolder)")
        return str(base)
    return str(sub)


def create_chart_from_text(
    text: str,
    *,
    mode: str = "aditya",
    ayanamsa: int = 1,
    chart_folder: Optional[str] = None,
    chart_format: Optional[str] = None,
    on_warning: Optional[Callable[[str, str], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    parse_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    geocode_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> ChartCreationResult:
    """Create a Chart from free-form birth text.

    Args:
        text: "Name, Date, Time, City" free text (offline regex parser).
        mode: zodiac mode for build_chart_from_params.
        ayanamsa: ayanamsa id for build_chart_from_params.
        chart_folder: destination folder override. When None, the chart goes
            to <chart folder>/<active profile>/ (resolve_chart_target_folder,
            which honours VARUNA360_CHART_FOLDER). There is no way to ask for
            no file at all — see INV-1 at stage 6.
        chart_format: 'toml' | 'chtk'. None takes paths.default_chart_format,
            which ships as 'toml'. Governs this write only; nothing on disk
            is converted.
        on_warning: callback(kind, message) fired at the same points the
            legacy dialog showed its warning boxes (date ambiguity, missing
            time, geocode failure). Warnings are also collected on the result.
        on_progress: callback(stage) with 'parsing'|'geocoding'|'calculating'
            |'writing' for UI status labels.
        parse_fn / geocode_fn: test seams (default: text_to_chtk's
            parse_birth_text / resolve_location). geocode_fn signature:
            (city, country, year, month, day) -> dict with lat/lon/tz_name
            and optional geocode_failed.

    Returns:
        ChartCreationResult; check `.ok`. Never raises for input/data
        failures — every failure is an explicit (error_stage, error) pair.
    """
    result = ChartCreationResult()

    def _warn(kind: str, message: str) -> None:
        result.warnings.append((kind, message))
        if on_warning:
            on_warning(kind, message)

    def _progress(stage: str) -> None:
        if on_progress:
            on_progress(stage)

    # ---- Stage 1: parse -------------------------------------------------
    _progress("parsing")
    if parse_fn is None:
        from AI_tools.AI_main_function.text_to_chtk import parse_birth_text as parse_fn
    try:
        parsed = parse_fn(text)
    except ValueError as e:
        return _error(result, STAGE_PARSE, str(e))
    except Exception as e:
        return _error(result, STAGE_PARSE, f"Unexpected parser failure: {e}")

    result.parsed = parsed
    result.name = parsed.get("name", "") or "Unknown"
    result.city = parsed["city"]
    result.country = parsed.get("country", "")
    result.gender = parsed.get("gender", "Unknown")
    result.location_label = (
        f"{result.city}, {result.country}" if result.country else result.city
    )

    if parsed.get("date_warning"):
        _warn(WARN_DATE_AMBIGUITY, parsed["date_warning"])
    if not parsed.get("has_time"):
        _warn(
            WARN_NO_TIME,
            "No birth time was found in the text.\n"
            "Defaulting to 12:00 (noon). Edit the chart afterwards to set "
            "the correct time.",
        )

    # ---- Stage 2: geocode ----------------------------------------------
    _progress("geocoding")
    if geocode_fn is None:
        from AI_tools.AI_main_function.text_to_chtk import resolve_location as geocode_fn
    try:
        loc = geocode_fn(result.city, result.country,
                         parsed["year"], parsed["month"], parsed["day"])
    except Exception as e:
        return _error(result, STAGE_GEOCODE, f"Location lookup failed: {e}")

    if loc.get("geocode_failed"):
        _warn(
            WARN_GEOCODE_FAILED,
            f"Could not find coordinates for '{result.city}, {result.country}'.\n"
            "Using (0, 0) / UTC as fallback. The chart will be inaccurate.\n\n"
            "Edit the chart afterwards to set correct coordinates.",
        )

    lat = loc["lat"]
    lon = loc["lon"]
    tz_name = loc["tz_name"]
    result.latitude = lat
    result.longitude = lon
    result.tz_name = tz_name

    # ---- Stage 3: offset resolution (EXPLICIT failure, never silent) ----
    _progress("calculating")
    second = parsed.get("second", 0)
    try:
        from core.time_utils import format_offset
        std_hours, dst_flag, is_gap = _resolve_offset_zoneinfo(
            tz_name, parsed["year"], parsed["month"], parsed["day"],
            parsed["hour"], parsed["minute"], second, lon,
        )
    except Exception as e:
        # Recorded finding: the legacy dialog silently treated local time as
        # UTC here. That is forbidden — surface the failure to the caller.
        return _error(
            result, STAGE_OFFSET,
            f"Could not resolve the UTC offset for timezone '{tz_name}' "
            f"({parsed['year']}-{parsed['month']:02d}-{parsed['day']:02d}): {e}",
        )

    if is_gap:
        # Nonexistent local time (clocks jumped over it) — a data-entry
        # smell. Additive warning; the chart still builds with the
        # post-transition offset (the dialog's historical fold=1 behavior).
        _warn(
            WARN_GAP_TIME,
            f"The local time {parsed['year']:04d}-{parsed['month']:02d}-"
            f"{parsed['day']:02d} {parsed['hour']:02d}:{parsed['minute']:02d} "
            f"does not exist in timezone '{tz_name}' (clocks jumped forward "
            "over it — DST spring-forward gap). It was interpreted with the "
            "post-transition offset. Check the birth time.",
        )

    # Canonical minute-precision standard-base offset string (never bakes
    # DST into the string — SPEC-TZ-001 Section 1; DST rides the flag).
    std_offset_str = format_offset(0, int(round(std_hours * 60)))
    result.dst_flag = dst_flag
    result.std_offset_str = std_offset_str

    # ---- Stage 4: UTC via BirthDataManager (the one UTC road, INV-3) ----
    from managers.birth_data_manager import BirthDataManager
    form_data = {
        "name": result.name,
        "year": parsed["year"], "month": parsed["month"], "day": parsed["day"],
        "hour": parsed["hour"], "minute": parsed["minute"], "second": second,
        "gender": result.gender,
        "city": result.city, "country": result.country,
        "latitude": lat, "longitude": lon,
        "timezone": std_offset_str,
        "iana_timezone": tz_name,
        "dst": dst_flag,
        "time_mode": "Local",
    }
    try:
        birth_data = BirthDataManager.create_from_form_data(form_data)
    except Exception as e:
        return _error(result, STAGE_UTC, f"UTC conversion failed: {e}")

    result.birth_data = birth_data
    # Offset-key duality: both keys, same value, set together (0.0 legit).
    utc_offset_hours = birth_data["utc_offset_hours"]
    result.utc_offset_hours = utc_offset_hours
    result.utcoffset = utc_offset_hours

    # ---- Stage 5: JD + terminal build -----------------------------------
    try:
        from libaditya import swe
        from core.chart_factory import build_chart_from_params

        hour_decimal = (
            birth_data["utc_hour"]
            + birth_data["utc_minute"] / 60.0
            + birth_data["utc_second"] / 3600.0
        )
        jd = swe.julday(
            birth_data["utc_year"], birth_data["utc_month"],
            birth_data["utc_day"], hour_decimal,
        )
        chart = build_chart_from_params(
            jd=jd, lat=lat, lon=lon, mode=mode, name=result.name,
            ayanamsa=ayanamsa, utcoffset=utc_offset_hours,
        )
    except Exception as e:
        return _error(result, STAGE_BUILD, f"Chart build failed: {e}")

    result.jd = jd
    result.chart = chart

    # Legacy dialog dict shape (title bar / edit panel display metadata),
    # extended with BOTH offset keys.
    result.planets_data = {
        "julian_day": jd,
        "name": result.name,
        "person_name": result.name,
        "city": result.city,
        "country": result.country or "Unknown",
        "year": parsed["year"],
        "month": parsed["month"],
        "day": parsed["day"],
        "hour": parsed["hour"],
        "minute": parsed["minute"],
        "second": second,
        "latitude": lat,
        "longitude": lon,
        "timezone": tz_name,
        "gender": result.gender,
        "utc_offset_hours": utc_offset_hours,
        "utcoffset": utc_offset_hours,
    }

    result.ok = True

    # ---- Stage 6: UNCONDITIONAL collision-safe persistence --------------
    # SPEC-PERSIST-001 INV-1. This used to be opt-in (`persist=False`), and
    # on 2026-07-28 a chart created through Add Chart existed only in
    # session.json — so when the favorites sync regenerated that file, it was
    # gone with nothing on disk to recover from. There is no opt-out now: a
    # default is an invitation, an absent parameter is a contract.
    _progress("writing")
    path, fmt, persist_error = persist_birth_data(
        birth_data, name=result.name, chart_folder=chart_folder,
        chart_format=chart_format, julian_day=result.jd)
    result.chart_format = fmt
    if persist_error:
        return _persist_failed(result, persist_error)
    result.file_path = path
    # chtk_path feeds CHTK-only readers; a .toml there would mis-parse.
    result.chtk_path = path if fmt == CHART_FORMAT_CHTK else None

    return result
