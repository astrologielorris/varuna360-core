# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
PrefsStore — Layer-B persistence protocol (Phase 4 W3).

JSON-backed dict store with atomic writes. Used by ChartState to persist
aditya_mode + chart_view_style across restarts, and by core_gui_qt.py
helpers (_save_setting / _load_setting) for boolean toggles like
show_retinue_rings, show_element_pies, cusp_glow_mode.

Pre-mortem fixes embedded:
- pm-20260503-008: atomic write via temp-file + os.replace + fsync.
  os.replace is atomic on POSIX and Windows, so a crash mid-save can
  leave only the previous valid file or the new valid file — never a
  half-written corrupt one.
"""
import json
import os
import warnings
from pathlib import Path


class PrefsStore:
    """JSON-backed dict persistence with atomic writes.

    No schema migration, versioning, or async (per spec deferred questions).
    Failures on save are logged via warnings and swallowed — fire-and-forget.
    """

    def __init__(self, path):
        """Args:
            path: pathlib.Path or str pointing to the JSON file.
        """
        self._path = Path(path)
        self._cache = None

    @property
    def path(self):
        return self._path

    def load(self) -> dict:
        """Return parsed dict, or {} if file missing / unreadable / invalid JSON.

        Never raises. Corrupt JSON is logged and treated as empty so the app
        boots with default prefs rather than crashing.
        Uses an in-memory cache to avoid re-reading disk on every call.
        """
        if self._cache is not None:
            return self._cache.copy()
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                warnings.warn(f"PrefsStore.load: {self._path} is not a JSON object — returning {{}}")
                return {}
            self._cache = data
            return data.copy()
        except Exception as e:
            warnings.warn(f"PrefsStore.load failed for {self._path}: {e}")
            return {}

    def save(self, prefs: dict) -> None:
        """Atomic write. Logs but never raises on failure."""
        if not self._path.parent.exists():
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                warnings.warn(f"PrefsStore.save mkdir failed for {self._path.parent}: {e}")
                return

        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(prefs, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            # os.replace is atomic on POSIX and Windows
            os.replace(tmp_path, self._path)
            self._cache = prefs.copy()
        except Exception as e:
            warnings.warn(f"PrefsStore.save failed for {self._path}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def update(self, key: str, value) -> None:
        """Convenience: load → mutate one key → save.

        Used by core_gui_qt.py:_save_setting wrapper. Single-key writes preserve
        all other keys in the file.
        """
        data = self.load()
        data[key] = value
        self.save(data)

    def get(self, key: str, default=None):
        """Convenience: load → return one key → default if missing."""
        return self.load().get(key, default)
