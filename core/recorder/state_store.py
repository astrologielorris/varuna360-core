# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Recorder app state that is not a preference (SPEC-REC-001 §3.2, review R1
F16): the last result and the notification value saved during a take. One
small JSON file, ``<user_data>/Recorder/state.json``, written atomically.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional


def default_path() -> str:
    from state.user_data import get_user_data_dir
    return os.path.join(get_user_data_dir(), "Recorder", "state.json")


class StateStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_path()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self._load()
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)
