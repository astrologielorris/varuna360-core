# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
ProfileStore — Layer-B per-profile session persistence (Phase 4 W4).

Opaque JSON passthrough: stores whatever dict SessionManager hands it,
returns whatever it has. No schema knowledge, no version migration —
SessionManager (Layer D) owns those concerns.

Pre-mortem fix pm-20260503-008: atomic write via temp + fsync + os.replace.
"""
import copy
import json
import os
import warnings
from pathlib import Path


# Default shape returned for missing profiles. SessionManager fills in real
# values; this is the boot-from-nothing fallback.
DEFAULT_SESSION = {
    "version": "1.0",
    "charts": [],
}


class ProfileStore:
    """Per-profile session.json store.

    Layout: {profiles_dir}/{profile_id}/session.json
    """

    def __init__(self, profiles_dir):
        """Args:
            profiles_dir: directory containing per-profile subdirs.
                Each profile_id maps to {profiles_dir}/{profile_id}/session.json.
        """
        self._profiles_dir = Path(profiles_dir)

    @property
    def profiles_dir(self):
        return self._profiles_dir

    def _session_path(self, profile_id: str) -> Path:
        return self._profiles_dir / profile_id / "session.json"

    def load_profile(self, profile_id: str) -> dict:
        """Return profile data, or a fresh DEFAULT_SESSION copy if missing.

        Never raises. Corrupt JSON is logged and treated as default — keeps
        the app bootable when a profile file is hand-edited and broken.
        """
        path = self._session_path(profile_id)
        if not path.exists():
            return copy.deepcopy(DEFAULT_SESSION)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                warnings.warn(f"ProfileStore.load_profile: {path} is not a JSON object — returning default")
                return copy.deepcopy(DEFAULT_SESSION)
            return data
        except Exception as e:
            warnings.warn(f"ProfileStore.load_profile failed for {path}: {e}")
            return copy.deepcopy(DEFAULT_SESSION)

    def save_profile(self, profile_id: str, data: dict) -> bool:
        """Atomic write. Returns True on success, False on any failure.

        Logs warnings instead of raising so SessionManager's retry counter
        can decide whether to surface a user-visible warning.
        """
        path = self._session_path(profile_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            warnings.warn(f"ProfileStore.save_profile mkdir failed for {path.parent}: {e}")
            return False

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            import traceback
            print(f"[ProfileStore] save_profile FAILED for {path}: {type(e).__name__}: {e}")
            traceback.print_exc()
            warnings.warn(f"ProfileStore.save_profile failed for {path}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def profile_exists(self, profile_id: str) -> bool:
        return self._session_path(profile_id).exists()

    def list_profiles(self) -> list:
        """Return sorted list of profile IDs that have a session.json file."""
        if not self._profiles_dir.exists():
            return []
        return sorted(
            d.name for d in self._profiles_dir.iterdir()
            if d.is_dir() and (d / "session.json").exists()
        )
