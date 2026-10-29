# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""A SettingsManager that never writes (``use_read_only_settings``).

A CLI that runs app widget code reading ``get_settings()`` (the chart
renderers) needs the process-wide SettingsManager to hold the resolved
settings (running app > saved file > factory) without ever touching the
user's files: no ``app_settings.json`` created or rewritten, no lock file, no
``.env`` written by ``set_api_key``, no ``settings.json`` renamed by the
prefs migration.

It is built through the real ``SettingsManager.__init__`` (every attribute the
class sets up exists, today and after any future addition), with the loader
returning the given values and every persistence method of
``managers/settings_manager.py`` overridden: ``_save`` (set, set_locked,
persist_runtime_change, flush, reset_to_defaults), ``_save_env``
(set_api_key) and the one-time migrations (``_migrate_legacy_configs``,
``_migrate_from_prefs``, ``_migrate_bar_default``), which rewrite or rename
files. In-memory ``set`` still updates the value and fires the observers, as
before. ``read_only`` is True on this class only.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from managers.settings_manager import SettingsManager


class ReadOnlySettingsManager(SettingsManager):
    """In-memory settings: reads like the app's manager, persists nothing."""

    read_only = True

    def __init__(self, values: Dict[str, Any], config_dir: Optional[str]):
        # Set before super().__init__, which calls _load() first.
        self._initial_values = copy.deepcopy(values)
        # "" (factory defaults, no user-data folder): no file path at all, so
        # nothing reads a .env relative to the working directory either.
        super().__init__(config_dir or "")
        if not config_dir:
            self._config_path = ""
            self._env_path = ""
        del self._initial_values

    # The values: the given resolved settings, never the file.
    def _load(self) -> bool:
        self._settings = self._initial_values
        return True

    # Persistence: none.
    def _save(self) -> bool:
        with self._save_lock:
            self._pending_writes.clear()
        return True

    def _save_env(self, env_vars, remove_keys=None) -> bool:
        return False          # nothing was stored; set_api_key reports it

    # One-time migrations rewrite or rename the user's files: skipped. The
    # given values are already the resolved ones.
    def _migrate_legacy_configs(self):
        return None

    def _migrate_from_prefs(self):
        return None

    def _migrate_bar_default(self):
        return None


def build_read_only_settings(view, overrides=None) -> ReadOnlySettingsManager:
    """A ReadOnlySettingsManager holding ``view``'s merged settings (saved
    file or factory) with the running app's live values on top, as the widgets
    must draw what the app draws now (live_state.py). ``overrides`` (flat
    ``{key: value}``) go on top of both: the values a command resolved and
    normalized (SET-003 W11-R2-3, ``use_read_only_settings``)."""
    values = copy.deepcopy(view._merged)
    # The app's one-time house-number carry-over (font_area_migration), in
    # memory: a saved file not yet migrated draws its legacy size, not 23.
    from managers.font_area_migration import legacy_house_number_size
    legacy = None if view.factory_only else legacy_house_number_size(view._saved)
    if legacy is not None:
        values.setdefault("display", {}).setdefault("fonts", {})["house_numbers"] = legacy
    layers = dict(view._live)
    layers.update(overrides or {})
    for key, value in layers.items():
        node = values
        parts = key.split(".")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[parts[-1]] = copy.deepcopy(value)
    folder = str(view.path.parent) if view.path is not None else ""
    return ReadOnlySettingsManager(values, folder)
