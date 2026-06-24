# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
User data directory resolution for multi-installation support.

Separates read-only bundled data (code, images, ephe) from writable user
data (profiles, settings, session files).

In dev mode: user_data_dir == project_root (backward compatible).
In frozen mode (AppImage/PyInstaller): user-chosen directory, stored in a
    bootstrap config at ~/.config/varuna360/bootstrap.json.
"""
import json
import os
import platform
import sys
from pathlib import Path


def _bootstrap_dir():
    """Platform-appropriate location for the tiny bootstrap config."""
    system = platform.system()
    if system == "Windows":
        base = Path.home() / "Documents"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "varuna360"


BOOTSTRAP_DIR = _bootstrap_dir()
BOOTSTRAP_FILE = BOOTSTRAP_DIR / "bootstrap.json"

_cached_dir = None


def is_frozen():
    """True when running inside a PyInstaller/AppImage bundle."""
    return getattr(sys, 'frozen', False)


def get_project_root():
    """Where bundled code and read-only assets live."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent.absolute()


def get_default_data_dir():
    """Sensible default for first-run: ~/Documents/Varuna360."""
    return Path.home() / "Documents" / "Varuna360"


def get_user_data_dir():
    """Return the writable user data directory, or None if not yet configured.

    Dev mode always returns project root (unchanged behavior).
    Frozen mode reads from bootstrap config; returns None on first run.
    """
    global _cached_dir
    if _cached_dir is not None:
        return _cached_dir

    if not is_frozen():
        _cached_dir = get_project_root()
        return _cached_dir

    if BOOTSTRAP_FILE.exists():
        try:
            with open(BOOTSTRAP_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            path = data.get('user_data_dir')
            if path:
                _cached_dir = Path(path)
                _cached_dir.mkdir(parents=True, exist_ok=True)
                return _cached_dir
        except Exception as e:
            print(f"[user_data] Cannot read bootstrap config: {e}", file=sys.stderr)

    return None


def set_user_data_dir(path):
    """Save the user's data directory choice to bootstrap config.

    Raises OSError if the directory cannot be created or is not writable.
    """
    global _cached_dir
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    probe = path / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        raise OSError(f"Directory is not writable: {path}")

    BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
    with open(BOOTSTRAP_FILE, 'w', encoding='utf-8') as f:
        json.dump({'user_data_dir': str(path)}, f, indent=2)

    _cached_dir = path
    return path


def get_settings_path():
    """Return the path to settings.json in the user data directory."""
    data_dir = get_user_data_dir() or get_project_root()
    return data_dir / "settings.json"


def needs_first_run_setup():
    """True when frozen and no data directory has been configured yet."""
    return is_frozen() and get_user_data_dir() is None
