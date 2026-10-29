# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Which edition is running: this is the Lite build (written by build_lite.py)."""
from __future__ import annotations

LITE = "lite"
PRO = "pro"
PERSONAL = "personal"
EDITIONS = (LITE, PRO, PERSONAL)
PROCESS_EDITION = "process_edition"
_BUILD_EDITION = LITE


def current_edition(argv=None) -> str:
    return LITE
