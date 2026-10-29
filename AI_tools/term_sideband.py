# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""OSC 7360 sideband emitter for the Varuna terminal (SPEC-TERM-001 section 6.2).

A tool calls `emit(kind, **payload)` to announce a structured artifact (a chart
PNG, a table, a summary card). The event is written to stdout as an OSC 7360
escape sequence that the Varuna terminal reads out of band and renders as an
overlay. Any other terminal ignores OSC 7360, so the sequence is invisible there.

The helper is INERT unless VARUNA_TERM=1, so `--json` pipelines and CI are
untouched (Rule 24). Imports only the standard library to stay free of circular
imports with the CLI tools that call it.
"""
import json
import os
import sys

_OSC_PREFIX = "\x1b]7360;"
_OSC_BEL = "\x07"


def enabled():
    """True only inside the Varuna terminal AND when stdout is the terminal itself.

    VARUNA_TERM=1 is exported to the whole bash session, so a piped or redirected
    stdout (`... --json | jq`, `... > out.json`) must stay clean: the isatty check
    makes emit inert for non-tty stdout while still driving overlays for normal
    interactive tool output (whose stdout is the PTY)."""
    if os.environ.get("VARUNA_TERM") != "1":
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def emit(kind, **payload):
    """Write an OSC 7360 sideband event to stdout. No-op unless VARUNA_TERM=1.

    kind: "chart" | "chart_source" | "table" | "card" (spec 6.1).
    payload: JSON-serializable fields (e.g. path=..., title=..., cols=..., rows=...).
    """
    if not enabled():
        return
    try:
        obj = {"v": 1, "kind": kind}
        obj.update(payload)
        # Compact, ASCII-only so the sequence never carries a split multibyte char.
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=True)
        sys.stdout.write(_OSC_PREFIX + data + _OSC_BEL)
        sys.stdout.flush()
    except Exception:
        # The sideband must never break a tool's real output.
        pass
