# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Hide desktop notification banners during a take (SPEC-REC-001 §4.8, INV-10;
desktop translation of SPEC-RECDND-MOBILE-001).

The old value is saved before the change and restored only if the value is
still the one we set: a change the user made during the take wins. A value
left saved by a crashed take is restored at the next start.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Target:
    schema: str
    key: str
    silenced: str             # gsettings text form of the "hidden" value


TARGETS = {
    "cinnamon": Target("org.cinnamon.desktop.notifications", "display-notifications", "false"),
    "gnome": Target("org.gnome.desktop.notifications", "show-banners", "false"),
}


def target_for(desktop: Optional[str] = None) -> Optional[Target]:
    desktop = (desktop if desktop is not None else os.environ.get("XDG_CURRENT_DESKTOP", "")).lower()
    for name, target in TARGETS.items():
        if name in desktop:
            return target
    return None


def should_engage(current: Optional[str], target: Target) -> bool:
    """Write only when banners are on now (something to hide)."""
    return current is not None and current != target.silenced


def should_restore(current: Optional[str], target: Target, saved: Optional[str]) -> bool:
    """Put the old value back only if ours is still in place."""
    return saved is not None and current == target.silenced


class Silencer:
    """``store`` keeps the saved value across a crash (get/set of one string
    or None); ``runner`` is subprocess.run (faked in tests)."""

    def __init__(self, store_get: Callable[[], Optional[str]],
                 store_set: Callable[[Optional[str]], None],
                 target: Optional[Target] = None, runner: Callable = subprocess.run):
        self._get, self._set = store_get, store_set
        self.target = target if target is not None else target_for()
        self._run = runner

    @property
    def available(self) -> bool:
        return self.target is not None and shutil.which("gsettings") is not None

    def _read(self) -> Optional[str]:
        try:
            r = self._run(["gsettings", "get", self.target.schema, self.target.key],
                          capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    def _write(self, value: str) -> bool:
        try:
            return self._run(["gsettings", "set", self.target.schema, self.target.key, value],
                             capture_output=True, text=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def engage(self) -> bool:
        if not self.available:
            return False
        current = self._read()
        if not should_engage(current, self.target):
            return False
        self._set(current)                       # saved BEFORE the change
        if self._write(self.target.silenced):
            return True
        self._set(None)
        return False

    def restore(self) -> bool:
        """Put the saved value back. The saved value is kept when gsettings
        cannot be read or written (retried at the next start), and cleared
        only after a successful restore or a confirmed user change (review
        R2 F6)."""
        saved = self._get()
        if saved is None or self.target is None:
            return False
        current = self._read()
        if current is None:
            return False                         # transient failure: keep for next time
        if not should_restore(current, self.target, saved):
            self._set(None)                      # the user changed it during the take
            return False
        if self._write(saved):
            self._set(None)
            return True
        return False
