# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Text that may exist on ``main`` only, read from ``core/data/main_only/``.

Some wording is built on course material and stays on ``main`` until it is
rewritten in our own words: LTS (the shipping branch) and every Lite or public
build must not carry it. Such text lives as data in ``core/data/main_only/``
(never in code), each file carrying a marker field that says what it is (its
name is in release_gates/check_private_reach.py and test/test_main_only_content.py,
never in shipped code, so the marker itself reddens a shipped copy). The fence:

- the Lite manifest (build_lite.py) never lists that folder, and release
  Gate 9 (check_private_reach) reddens on a shipped file holding the marker,
  on a file of that name, or on a byte copy of one of these files;
- test/test_main_only_content.py fails on an LTS branch if the folder or its
  marker is there, so a routine main -> LTS port that carries it goes red.

The code that shows this text ships everywhere and reads it through
``load()``; where the file is absent (LTS, Lite) it gets ``{}`` and shows
nothing in its place. No table uses it today (the folder holds only its
README): the Hora/Trimsamsa pie meanings it first held are Lorris Turpin's own
interpretation and went back into wheel_view.py. Qt-free.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

MAIN_ONLY_DIR = Path(__file__).resolve().parent / "data" / "main_only"


@lru_cache(maxsize=None)
def load(name: str) -> Dict[str, Any]:
    """The main-only table ``name`` (``core/data/main_only/<name>.json``), or
    ``{}`` when this build does not carry it."""
    try:
        with open(MAIN_ONLY_DIR / f"{name}.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
