# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The ``qps`` pseudo language (SPEC-LOC-002 §4.9, developer tool).

Every text becomes ``⟦Ŧéxţ ~~~⟧``: accented letters, padded to at least +40%
length, wrapped in brackets. Placeholders (``{name}``, ``{x|form}``,
``{v:.2f}``), escaped braces, HTML tags and ``&`` mnemonics are left intact, so
a pseudo template formats exactly like its English source. Visible text without
the brackets is unmigrated (T-10); clipped text is a layout bug (T-11).
"""
from __future__ import annotations

import math
import re

OPEN, CLOSE = "⟦", "⟧"          # ⟦ ⟧
_ACCENTS = str.maketrans(
    "aceinostuyzACEINOSTUYZ",
    "áçéîñöşţûýž"
    "ÁÇÉÎÑÖŞŦÛÝŽ")
# literal text | {{ | }} | {field} | <tag> | &x mnemonic
_PROTECTED = re.compile(r"(\{\{|\}\}|\{[^{}]*\}|<[^<>]*>|&.)")
GROWTH = 0.4


def pseudo(text: str) -> str:
    """The pseudo form of one template (or plain text)."""
    if not text:
        return text
    parts = _PROTECTED.split(text)
    visible = 0
    out = []
    for i, part in enumerate(parts):
        if i % 2:                     # protected token
            out.append(part)
            if part.startswith("&"):
                visible += 1
        else:
            out.append(part.translate(_ACCENTS))
            visible += len(part)
    pad = max(1, math.ceil(visible * GROWTH))
    return f"{OPEN}{''.join(out)} {'~' * pad}{CLOSE}"


def is_pseudo(text: str) -> bool:
    return text.startswith(OPEN) and text.endswith(CLOSE)
