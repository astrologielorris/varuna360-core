# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The result envelope every capability returns (AIC plan 2, W4).

``{capability, schema_version, status, error, input, options, data}``:
- ``status`` is ``ok`` or ``error``; an error carries ``error`` = {type,
  message} and ``data`` = None. A missing value is never a silent 0.
- ``input`` echoes the full CalculationInput (frame values and where each came
  from: argument, settings or factory), so an answer always says which chart
  and which zodiac it is about (SPEC-ZOD-001: reported, never converted). A
  library-scope capability echoes its LibraryInput (``chart`` None).
- ``options`` echoes the capability options with their sources.
- JDs are UT; raw values keep full precision; display strings are separate.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

STATUS_OK = "ok"
STATUS_ERROR = "error"


def ok(
    capability: str,
    schema_version: int,
    inp,
    options: Dict[str, Any],
    data: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "capability": capability,
        "schema_version": schema_version,
        "status": STATUS_OK,
        "error": None,
        "input": inp.to_dict() if inp is not None else None,
        "options": options,
        "data": data,
    }


def error(
    capability: str,
    schema_version: int,
    inp,
    options: Optional[Dict],
    exc_type: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "capability": capability,
        "schema_version": schema_version,
        "status": STATUS_ERROR,
        "error": {"type": exc_type, "message": message},
        "input": inp.to_dict() if inp is not None else None,
        "options": options or {},
        "data": None,
    }


def dumps(envelope: Dict[str, Any], indent: Optional[int] = 2) -> str:
    """Deterministic JSON (sorted keys; NaN refused so output is valid JSON)."""
    return json.dumps(
        envelope,
        indent=indent,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    )


def _default(obj):
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"not JSON-serializable: {type(obj).__name__}")


def compact_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """The envelope without the settings echo of its input (the live key list
    alone is about 80 names): what a ``compact`` call returns (SPEC-COACH-001
    §4.4), for every caller of ``invoke``."""
    inp = envelope.get("input")
    if isinstance(inp, dict) and "settings" in inp:
        envelope = dict(envelope, input={k: v for k, v in inp.items() if k != "settings"})
    return envelope
