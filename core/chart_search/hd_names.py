"""Short Human Design names for the funnel's Gate and Channel lists.

Only the name, never the description: a gate reads "21 (Control)", a channel
"10-34 (Exploration)". Read from the HD definitions the HD panel already ships
(``core/data/hd_definitions``): a gate's ``hd_name`` keynote, a channel's
``name``, keyed lo-hi like the stored channel values. A missing or broken
file means bare numbers, never a broken list.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from core.chart_search.taxonomy import Value

_DIR = Path(__file__).resolve().parent.parent / "data" / "hd_definitions"


@cache
def _gates() -> dict[int, str]:
    try:
        rows = json.loads((_DIR / "gates.json").read_text(encoding="utf-8"))
        return {int(r["gate"]): r["hd_name"] for r in rows}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


@cache
def _channels() -> dict[str, str]:
    try:
        rows = json.loads((_DIR / "channels.json").read_text(encoding="utf-8"))
        out = {}
        for r in rows:
            lo, hi = sorted(int(g) for g in r["gates"])
            out[f"{lo}-{hi}"] = r["name"]
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def gate_name(value: Value) -> str | None:
    try:
        return _gates().get(int(value))
    except (TypeError, ValueError):
        return None


def channel_name(value: Value) -> str | None:
    return _channels().get(str(value))
