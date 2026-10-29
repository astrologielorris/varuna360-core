"""The version stamp on every Find Chart computation (SPEC-FIND-004 §4.4).

libaditya is a pinned pip dependency, so the engine can change without
Varuna's own version changing: the stamp carries both, or a pin bump would
leave rows computed by the old engine looking current.
"""

from __future__ import annotations

from importlib.metadata import version

from core.bug_report import app_version


def computation_stamp() -> str:
    """``"<app version> + libaditya <version>"``, e.g. ``"5.0.3 + libaditya 0.4.1"``."""
    return f"{app_version()} + libaditya {version('libaditya')}"
