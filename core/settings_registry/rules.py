# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""How a registry entry behaves beyond its value (SPEC-SET-003 §3.1, v0.7): one
``Setting`` field, so the entry stays at 16 fields. Qt-free, data only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

KIND_LEAF = "leaf"          # one value (possibly a whole dict used as one value)
KIND_SECTION = "section"    # a typed block read through a merging getter
CLI_CALCULATION = "calculation"   # D-16: changes a calculation or what a CLI prints
CLI_APP = "app"                   # D-16: how the app looks and behaves
WRITABLE_AI = "ai"          # INV-17: settings.py, --set and the app settings request service
WRITABLE_USER = "user"
WRITABLE_NONE = "none"      # its own control only; the default for an unclassified key


@dataclass(frozen=True)
class Rules:
    kind: str = KIND_LEAF
    cli: Optional[str] = None             # CLI_CALCULATION | CLI_APP
    writable: str = WRITABLE_NONE
    applies_when: Optional[Any] = None    # SPEC-JRD-001 x-applies-when
    normalize: Optional[str] = None       # "module.path:function", resolved on use
    validate: Optional[str] = None        # "module.path:function", resolved on use


def kind_of(rules: Optional[Rules]) -> str:
    return rules.kind if rules is not None else KIND_LEAF


# W3e classifications, from the W0b key table and D-23.
CALC_AI = Rules(cli=CLI_CALCULATION, writable=WRITABLE_AI)  # has a Settings control
CALC = Rules(cli=CLI_CALCULATION)                           # no control: its owner only
APP = Rules(cli=CLI_APP)
APP_PROTECTED = Rules(cli=CLI_APP)                          # INV-17: never "ai"
APP_SECTION = Rules(kind=KIND_SECTION, cli=CLI_APP)
APP_AI = Rules(cli=CLI_APP, writable=WRITABLE_AI)                # AI setting redesign: in-app AI
