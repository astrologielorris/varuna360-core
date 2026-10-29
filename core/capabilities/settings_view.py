# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Read-only view of the user's saved settings (AIC plan 2, W4).

Tools follow the Settings tab (Lorris, 2026-10-01): a preference a tool is not
given explicitly comes from the same ``app_settings.json`` the GUI loads, so a
changed setting changes the tool's answer the same way it changes the panel.

``managers.settings_manager.get_settings()`` cannot be used here: on a missing
file or an unfinished migration its first use CREATES or REWRITES the file (and
a lock file), and ``state.user_data.get_user_data_dir()`` writes a probe file
under ``VARUNA360_USER_DATA_DIR``. A tool must never touch the user's data, so
this module resolves the same path and merges the same defaults, in memory only.

Qt-free, never writes, never raises on a bad file (a bad file reads as the
factory defaults, and the view says so).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SETTINGS_FILENAME = "app_settings.json"

SOURCE_ARGUMENT = "argument"
SOURCE_LIVE = "live"            # the running app's current value (live_state.py)
SOURCE_SETTINGS = "settings"
SOURCE_FACTORY = "factory"

_MISSING = object()


def _factory_defaults() -> Dict[str, Any]:
    """DEFAULT_SETTINGS plus the additive extension defaults, as the manager
    builds them. Importing the module has no side effects (checked)."""
    from managers.settings_manager import DEFAULT_SETTINGS
    return copy.deepcopy(DEFAULT_SETTINGS)


def _deep_merge(base: dict, override: dict) -> dict:
    """Same rule as SettingsManager._deep_merge: override wins, dicts merge."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def find_bootstrap_file() -> Optional[Path]:
    """The bootstrap pointer ``state.user_data._resolve_bootstrap_file`` would
    use, found READ-ONLY: the current pointer if present, else the first
    readable legacy one, read in place. Never creates, copies or modifies a
    file: the read-only settings loads (SettingsView, use_read_only_settings,
    the CLIs) use it, while the app's own resolution migrates. Never raises;
    None when no pointer exists."""
    from state import user_data as ud
    try:
        current = ud._bootstrap_file()
        if current.is_file():
            return current
        legacy_dirs = ud._legacy_bootstrap_dirs()
    except Exception:
        return None
    for legacy_dir in legacy_dirs:
        legacy = legacy_dir / "bootstrap.json"
        try:
            if legacy.is_file():
                json.loads(legacy.read_text(encoding="utf-8"))
                return legacy
        except (OSError, ValueError):
            continue
    return None


def resolve_settings_dir() -> Optional[Path]:
    """The directory whose app_settings.json the GUI would load, found WITHOUT
    creating anything (no mkdir, no probe file, no bootstrap write).

    Mirrors ``state.user_data.get_user_data_dir``: the test/isolation override
    wins; a source checkout uses the project root; a frozen build reads the
    bootstrap pointer. None when nothing is configured (first run)."""
    from state import user_data as ud
    override = os.environ.get(ud.USER_DATA_DIR_ENV)
    if override is not None and override.strip():
        return Path(override.strip())
    if not ud.is_frozen():
        return Path(ud.get_project_root())
    # read-only: the migrating resolver would copy a legacy pointer
    source = find_bootstrap_file()
    if source is None:
        return None
    try:
        with open(source, "r", encoding="utf-8") as fh:
            path = json.load(fh).get("user_data_dir")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(path) if path else None


class SettingsView:
    """Merged settings (factory defaults + saved file), with per-key source.

    ``get(key, default)`` has the SettingsManager signature (dot keys), so code
    that already resolves settings through a ``settings.get`` object, such as
    ``DashaState.from_settings``, can be reused unchanged: one resolution rule
    for the GUI and the tools.
    """

    def __init__(self, saved: Optional[dict], path: Optional[Path],
                 status: str, factory_only: bool = False,
                 live: Optional[dict] = None):
        self._saved = saved if isinstance(saved, dict) else {}
        # Flat dot-key -> value overlay of the running app (above the file).
        self._live = {} if factory_only or not isinstance(live, dict) else dict(live)
        self._defaults = _factory_defaults()
        self._merged = (self._defaults if factory_only
                        else _deep_merge(self._defaults, self._saved))
        self.path = path
        self.status = status            # "loaded" | "missing" | "unreadable" | "factory"
        self.factory_only = factory_only

    @classmethod
    def load(cls, factory_only: bool = False,
             settings_dir: Optional[Path] = None,
             live: Optional[dict] = None) -> "SettingsView":
        """``live``: the running app's values (above the file). None = read them
        from the environment or the running app's live file (live_state.py);
        ``{}`` = ignore any live values. ``factory_only`` ignores both."""
        if factory_only:
            return cls(None, None, "factory", factory_only=True)
        folder = settings_dir if settings_dir is not None else resolve_settings_dir()
        if live is None:
            from core.capabilities.live_state import read_live
            live = read_live(folder)
        if folder is None:
            return cls(None, None, "missing", live=live)
        path = Path(folder) / SETTINGS_FILENAME
        try:
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
        except FileNotFoundError:
            return cls(None, path, "missing", live=live)
        except (OSError, ValueError):
            return cls(None, path, "unreadable", live=live)
        if not isinstance(saved, dict):
            return cls(None, path, "unreadable", live=live)
        return cls(saved, path, "loaded", live=live)

    @staticmethod
    def _walk(tree: dict, key: str):
        node: Any = tree
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return _MISSING
            node = node[part]
        return node

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._live:
            return copy.deepcopy(self._live[key])
        value = self._walk(self._merged, key)
        return default if value is _MISSING else copy.deepcopy(value)

    def live_value(self, key: str, default: Any = None) -> Any:
        """The running app's value for ``key`` (None-safe), ignoring the saved
        file: ``default`` when the app did not publish it."""
        return copy.deepcopy(self._live[key]) if key in self._live else default

    def stored_value(self, key: str, default: Any = None) -> Any:
        """The value below the live overlay: the saved file, else the factory
        table (what the app boots with), ignoring the running app's value."""
        value = self._walk(self._merged, key)
        return default if value is _MISSING else copy.deepcopy(value)

    def source(self, key: str) -> str:
        """Where ``get(key)`` came from: the running app, the saved file or the
        factory table."""
        if key in self._live:
            return SOURCE_LIVE
        if not self.factory_only and self._walk(self._saved, key) is not _MISSING:
            return SOURCE_SETTINGS
        return SOURCE_FACTORY

    def resolve(self, key: str, explicit: Any = None,
                default: Any = None) -> Tuple[Any, str]:
        """Argument > live app > saved setting > factory default, with the source."""
        if explicit is not None:
            return explicit, SOURCE_ARGUMENT
        return self.get(key, default), self.source(key)

    def describe(self) -> Dict[str, Any]:
        return {"status": self.status,
                "path": str(self.path) if self.path else None,
                "live_keys": sorted(self._live)}
