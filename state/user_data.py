# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""User data directory resolution for multi-installation support.

Separates read-only bundled data (code, images, ephe) from writable user
data (profiles, settings, session files).

In dev mode: user_data_dir == project_root (backward compatible).
In packaged mode (PyInstaller / AppImage / Nuitka): a user-chosen directory,
    recorded in a tiny bootstrap pointer file outside that directory.

PACKAGING DETECTION (why it is not just `sys.frozen`)
-----------------------------------------------------
Three packagers ship this app and only one of them sets `sys.frozen`:

  PyInstaller  sets `sys.frozen = True` and `sys._MEIPASS`.
  AppImage     is a PyInstaller build inside an AppDir, so `sys.frozen` is
               set there too; the AppImage runtime additionally exports
               APPDIR / APPIMAGE.
  Nuitka       sets NEITHER. It injects a module-level global `__compiled__`
               into every compiled module (a `__nuitka_version__` struct
               sequence with fields major/minor/micro/releaselevel/
               containing_dir/standalone/onefile/macos_bundle_mode/...).
               Evidence: nuitka/code_generation/templates/
               CodeTemplatesModules.py sets `__compiled__` per module and
               CodeTemplatesConstants.py declares those fields. Grepping the
               whole Nuitka tree for an assignment to `sys.frozen` finds none.

The macOS build (scripts/build_macos_nuitka.sh) uses `--mode=app`, which on
macOS means `macos_create_bundle=True` plus `standalone=True` and
`onefile=False` (nuitka/options/Options.py). Before this was handled,
`is_frozen()` was False inside the shipped .app, so `get_user_data_dir()`
returned the code directory INSIDE `Varuna360Core.app/Contents/MacOS/` and
profiles/settings/session were written into the bundle, where the next app
update deletes them.

`__compiled__` cannot exist in a dev checkout, so this detection cannot
false-positive for a developer running from source.

WHERE THE BUNDLED CODE LIVES
----------------------------
PyInstaller: `sys._MEIPASS`.
Nuitka standalone: there is no `_MEIPASS`. Nuitka's default
`--file-reference-choice` for standalone binaries is "runtime", and
`MAKE_RELATIVE_PATH()` joins the program directory to the module's relative
path, so `__file__` is `<dist>/state/user_data.py` and `parent.parent` is the
dist root, which is exactly where `--include-data-dir` content lands
(`Varuna360Core.app/Contents/MacOS/`). So the plain `__file__` walk is right
for both Nuitka and dev, and only PyInstaller needs a special case.
Note: `__compiled__.containing_dir` is NOT that directory. Under macOS bundle
mode Nuitka strips three path components off it, so it points at the folder
that CONTAINS the .app. Do not use it to find bundled data.

macOS DEFAULT DATA DIRECTORY (why not ~/Documents)
--------------------------------------------------
Since macOS 10.15 the "Files and Folders" TCC policy guards ~/Documents,
~/Desktop and ~/Downloads. The first write triggers a system consent prompt,
and a user who clicks "Don't Allow" gets PermissionError on every later write
with no in-app way back: the only cure is System Settings > Privacy &
Security > Files & Folders. For an unsigned build (these DMGs are unsigned)
that denial is also sticky per bundle path. ~/Library/Application Support is
the conventional macOS answer and is not TCC-guarded, but ~/Library is hidden
in Finder by default, and the product owner refuses to bury user-visible
settings in a hidden folder. `~/Varuna360` satisfies both: the home folder
itself is not TCC-guarded, and it is visible the moment the user clicks Home
in Finder. The bootstrap pointer still lives in ~/Library/Application Support
because it is machine state the user never edits.

WINDOWS BOOTSTRAP LOCATION (why it moved)
-----------------------------------------
The bootstrap pointer used to live at `~/Documents/varuna360/bootstrap.json`
while the default data dir is `~/Documents/Varuna360`. NTFS is
case-insensitive, so those are THE SAME DIRECTORY: the pointer that records
where the data directory is was stored inside the data directory it points
at, and `core/diagnostics.py` deliberately keeps its log outside the data dir
for the "data dir is not writable" case, which that collision defeated.
The pointer now lives at `%USERPROFILE%\\.varuna360\\bootstrap.json`. Windows
has no dotfile convention: Explorer hides entries that carry the
FILE_ATTRIBUTE_HIDDEN attribute (Microsoft "File Attribute Constants"), and
neither `Path.mkdir` nor `CreateDirectoryW` sets that attribute, so
`.varuna360` is plainly visible next to `.ssh` / `.gitconfig` in the user
profile. The data directory itself is unchanged and stays in ~/Documents.
`_legacy_bootstrap_dirs()` + `_resolve_bootstrap_file()` migrate an existing
pointer forward; the old file is copied, not moved, so an older build running
side by side keeps working.
"""
import json
import os
import platform
import sys
from pathlib import Path


# --------------------------------------------------------------------------
# Packaging detection
# --------------------------------------------------------------------------

def _pyinstaller_root():
    """PyInstaller/cx_Freeze bundle root, or None when not one of those."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return None


def _nuitka_info():
    """The Nuitka ``__compiled__`` value for this module, or None.

    Read through ``globals()`` on purpose: a bare name would be a NameError
    in normal CPython, and a module-level ``try/except NameError`` would be
    evaluated once at import instead of per call (which tests need to fake).
    """
    return globals().get("__compiled__")


def _is_nuitka_packaged():
    """True only for a Nuitka build that ships its own Python runtime.

    ``--mode=accelerated`` produces a compiled binary that still runs against
    the developer's Python and source tree; that is not "packaged" for our
    purposes and must keep dev behaviour.
    """
    info = _nuitka_info()
    if info is None:
        return False

    flags = []
    for name in ("standalone", "onefile", "macos_bundle_mode"):
        value = getattr(info, name, None)
        if value is not None:
            flags.append(bool(value))

    if not flags:
        # A Nuitka old enough to lack every flag. Presence of __compiled__ is
        # then the only signal available, and it is still not a dev checkout.
        return True
    return any(flags)


def _is_appimage():
    """True when this very file is running from inside a mounted AppImage.

    Requiring containment matters: APPDIR is inherited by any process the
    AppImage spawns, so a developer who opens a terminal from an AppImage and
    runs the source checkout must not be misread as packaged.
    """
    appdir = os.environ.get("APPDIR")
    if not appdir:
        return False
    try:
        here = Path(__file__).absolute()
        base = Path(appdir).absolute()
    except (OSError, ValueError):
        return False
    return here == base or base in here.parents


def is_frozen():
    """True when running from a packaged build (PyInstaller, AppImage, Nuitka)."""
    if getattr(sys, "frozen", False):
        return True
    if _is_nuitka_packaged():
        return True
    return _is_appimage()


def get_project_root():
    """Where bundled code and read-only assets live."""
    bundle = _pyinstaller_root()
    if bundle is not None:
        return bundle
    return Path(__file__).parent.parent.absolute()


# --------------------------------------------------------------------------
# Directory policy
# --------------------------------------------------------------------------

# macOS TCC ("Files and Folders") guards these three home subfolders.
_MACOS_TCC_DIRS = ("Documents", "Desktop", "Downloads")


def get_default_data_dir():
    """Sensible first-run default, visible to the user on every platform."""
    if platform.system() == "Darwin":
        # Not ~/Documents: see the macOS/TCC note in the module docstring.
        return Path.home() / "Varuna360"
    return Path.home() / "Documents" / "Varuna360"


def _bootstrap_dir():
    """Platform-appropriate location for the tiny bootstrap config.

    Must never resolve to the same directory as get_default_data_dir(), on
    any filesystem, including case-insensitive ones.

    core/diagnostics.py mirrors this function locally (it cannot import
    state.user_data without dragging Qt into every CLI tool) and
    test/test_session_health.py asserts the two stay identical.
    """
    system = platform.system()
    if system == "Windows":
        return Path.home() / ".varuna360"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "varuna360"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "varuna360"


def _bootstrap_file():
    return _bootstrap_dir() / "bootstrap.json"


def _legacy_bootstrap_dirs():
    """Older bootstrap locations still worth reading, newest first."""
    if platform.system() == "Windows":
        # Collided with ~/Documents/Varuna360 on case-insensitive NTFS.
        return [Path.home() / "Documents" / "varuna360"]
    return []


# Backwards-compatible module constants. Prefer the functions: these are
# evaluated once at import, so they cannot follow a platform change in tests.
BOOTSTRAP_DIR = _bootstrap_dir()
BOOTSTRAP_FILE = BOOTSTRAP_DIR / "bootstrap.json"

_cached_dir = None


def _reset_cache():
    """Forget the resolved data directory. For tests and for relocation."""
    global _cached_dir
    _cached_dir = None


def _resolve_bootstrap_file():
    """Return a readable bootstrap pointer path, migrating an old one first.

    Never raises. Returns None when no pointer exists anywhere.
    """
    current = _bootstrap_file()
    if current.is_file():
        return current

    for legacy_dir in _legacy_bootstrap_dirs():
        legacy = legacy_dir / "bootstrap.json"
        try:
            if not legacy.is_file():
                continue
            payload = legacy.read_text(encoding="utf-8")
            json.loads(payload)
        except (OSError, ValueError) as exc:
            print(f"[user_data] Ignoring unreadable legacy bootstrap {legacy}: {exc}",
                  file=sys.stderr)
            continue

        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_text(payload, encoding="utf-8")
            print(f"[user_data] Migrated bootstrap pointer {legacy} -> {current}",
                  file=sys.stderr)
            return current
        except OSError as exc:
            # Copy failed; the old pointer is still perfectly readable.
            print(f"[user_data] Could not migrate bootstrap pointer to {current}: {exc}",
                  file=sys.stderr)
            return legacy

    return None


#: Test-only override. When set, this directory replaces the user data
#: directory for EVERY consumer -- `app_settings.json` (SettingsManager),
#: `profiles/` (SessionManager) and anything else that routes through
#: get_user_data_dir(). It exists because a GUI smoke run is otherwise not
#: read-only with respect to a live session: in dev mode this function returns
#: the repo root, so a harness boot rewrote the same app_settings.json the
#: user's running app owns, and the ~30 s autosave injected the harness's test
#: charts into the real memory panel (measured 2026-08-03).
#: VARUNA360_CHART_FOLDER isolates only the chart *file* folder; it does not
#: cover either of those.
USER_DATA_DIR_ENV = "VARUNA360_USER_DATA_DIR"


def _warn_isolation_lost(detail):
    """Loud, unmissable banner when a requested isolation could not be honoured.

    A silent fallback to the real user data directory is the whole failure mode
    this override exists to prevent, so the fallback must never be quiet. It is
    still a fallback rather than an exception because this function is called
    bare during boot and dying there leaves no UI to recover through.
    """
    bar = "!" * 78
    print(f"\n{bar}\n"
          f"!! VARUNA360 TEST ISOLATION LOST\n"
          f"!! {detail}\n"
          f"!! FALLING BACK TO THE REAL USER DATA DIRECTORY.\n"
          f"!! Anything this process writes will land in the user's live\n"
          f"!! app_settings.json and profiles/. Stop the run and fix the export.\n"
          f"{bar}\n", file=sys.stderr, flush=True)


def get_user_data_dir():
    """Return the writable user data directory, or None if not yet configured.

    `VARUNA360_USER_DATA_DIR` overrides everything (test isolation).
    Dev mode always returns project root (unchanged behavior).
    Packaged mode reads the bootstrap pointer; returns None on first run, and
    also when the recorded directory can no longer be created (a denied macOS
    TCC prompt, a missing external drive), so the first-run chooser reappears
    instead of the app dying on an unusable path.
    """
    global _cached_dir

    # Checked BEFORE the cache: a boot sequence can resolve this once early,
    # and an override that arrives after that point must still win.
    override = os.environ.get(USER_DATA_DIR_ENV)
    if override is not None:
        override = override.strip()
        if not override:
            # Exported-but-empty is a WRAPPER BUG, not "unset". Shell wrappers
            # and CI scripts routinely build env from unset variables and
            # produce "". Treating it as unset would silently write to the real
            # directory -- the exact failure this override exists to prevent.
            _warn_isolation_lost(f"{USER_DATA_DIR_ENV} is exported but EMPTY")
        else:
            candidate = Path(override)
            probe = None
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                # mkdir only proves creatability. An existing chmod-555 dir
                # passes it and then every save fails, scattered and confusing.
                # PID-unique like set_user_data_dir's probe: a fixed name races
                # between concurrent processes, and a crash between write and
                # unlink leaves residue that the next run then trips over.
                probe = candidate / f".varuna360_write_probe_{os.getpid()}"
                probe.write_text("ok", encoding="utf-8")
                if probe.read_text(encoding="utf-8") != "ok":
                    raise OSError("write probe did not read back")
            except OSError as exc:
                # Deliberately NOT an exception. get_user_data_dir() is called
                # bare during boot (apps/core_gui_qt.py:278 and again at ~6803),
                # so raising here kills the app before the main window exists,
                # with no UI to recover through -- and it would contradict this
                # function's own contract of degrading rather than dying.
                # Loud-and-continue instead: the banner is unmissable in the
                # log, and the smoke test's contamination watcher is the
                # independent backstop that fails the run.
                _warn_isolation_lost(f"{USER_DATA_DIR_ENV}={override!r} is "
                                     f"unusable: {exc}")
                # A previously cached REAL directory must not be handed back
                # quietly under a failed override. Clearing it forces the normal
                # resolution below to run and re-announce itself, so the fallback
                # value is never a stale answer from before the override existed.
                _cached_dir = None
            else:
                _cached_dir = candidate
                return _cached_dir
            finally:
                # unlink in `finally`, never in the try body: if the write
                # succeeded and the unlink raised, the old code declared the dir
                # unusable AND left the probe file behind.
                if probe is not None:
                    try:
                        probe.unlink()
                    except OSError:
                        pass

    if _cached_dir is not None:
        return _cached_dir

    if not is_frozen():
        _cached_dir = get_project_root()
        return _cached_dir

    source = _resolve_bootstrap_file()
    if source is not None:
        try:
            with open(source, 'r', encoding='utf-8') as f:
                data = json.load(f)
            path = data.get('user_data_dir')
            if path:
                candidate = Path(path)
                candidate.mkdir(parents=True, exist_ok=True)
                _cached_dir = candidate
                return _cached_dir
        except Exception as e:
            print(f"[user_data] Cannot read bootstrap config: {e}", file=sys.stderr)

    return None


def _permission_message(path, headline, error):
    """User-facing failure text, with the macOS TCC recovery route spelled out."""
    if isinstance(error, PermissionError) and platform.system() == "Darwin":
        top = ""
        try:
            parts = Path(path).absolute().relative_to(Path.home()).parts
            top = parts[0] if parts else ""
        except ValueError:
            top = ""
        if top in _MACOS_TCC_DIRS:
            return (
                f"{headline}\n\n"
                f"macOS is blocking access to your {top} folder. "
                "Open System Settings, choose Privacy & Security, then Files & Folders, "
                "and allow Varuna360 to use it.\n"
                f"You can also pick a folder outside {top}, for example "
                f"{Path.home() / 'Varuna360'}."
            )
    return f"{headline}\n{error}"


def set_user_data_dir(path):
    """Save the user's data directory choice to the bootstrap config.

    Raises OSError if the directory cannot be created, cannot be written, or
    if the choice cannot be recorded.
    """
    global _cached_dir
    path = Path(path)

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(_permission_message(path, f"Cannot create this folder: {path}", e))

    if not path.is_dir():
        raise OSError(f"This path is not a folder: {path}")

    # Unique per process: two Varuna360 instances (full plus lite) commonly
    # run at once against the same folder and must not fight over the probe.
    probe = path / f".varuna360_write_test_{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "ok":
            raise OSError("the test file could not be read back")
    except OSError as e:
        raise OSError(_permission_message(path, f"This folder is not writable: {path}", e))
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

    bootstrap_file = _bootstrap_file()
    try:
        bootstrap_file.parent.mkdir(parents=True, exist_ok=True)
        with open(bootstrap_file, 'w', encoding='utf-8') as f:
            json.dump({'user_data_dir': str(path)}, f, indent=2)
    except OSError as e:
        raise OSError(
            _permission_message(
                bootstrap_file.parent,
                f"Cannot record the folder choice in {bootstrap_file}",
                e,
            )
        )

    _cached_dir = path
    return path


def get_settings_path():
    """Return the path to settings.json in the user data directory."""
    data_dir = get_user_data_dir() or get_project_root()
    return data_dir / "settings.json"


def needs_first_run_setup():
    """True when packaged and no data directory has been configured yet."""
    return is_frozen() and get_user_data_dir() is None
