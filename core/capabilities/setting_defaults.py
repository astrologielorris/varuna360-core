# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The fallback of a settings key, taken from the one place it is defined.

``setting_default(key)`` is the factory value declared in the settings
registry (``core.settings_registry``, SPEC-SET-003), so a fallback
written next to a ``settings.get(key, ...)`` cannot drift from what a fresh
app holds. The few keys the chart renderers read that ``DEFAULT_SETTINGS``
does not hold have their renderers' own fallback in ``RENDERER_FALLBACKS``; a
key in both is an error (test_review_round19), so there is one source per key.
"""
from __future__ import annotations

import copy
from typing import Any

# Keys absent from DEFAULT_SETTINGS: the value the reading code falls back to
# when the key was never stored (what a fresh app draws). Derived from the
# settings registry's fallback-only Core entries (SPEC-SET-003), never typed here.
def _renderer_fallbacks():
    from core.settings_registry import entries
    return {e.key: e.factory() for e in entries(persisted=False, kind="leaf",
                                                  edition="lite")}


RENDERER_FALLBACKS = _renderer_fallbacks()

_MISSING = object()


def factory_value(key: str, default: Any = _MISSING) -> Any:
    """The DEFAULT_SETTINGS value at dot-path ``key`` (a copy), or
    ``default``; KeyError when absent and no default is given."""
    from managers.settings_manager import DEFAULT_SETTINGS
    node: Any = DEFAULT_SETTINGS
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is _MISSING:
                raise KeyError(key)
            return default
        node = node[part]
    return copy.deepcopy(node)


def setting_default(key: str) -> Any:
    """The fallback for ``key``: the settings registry's factory value, else
    DEFAULT_SETTINGS (app state), else RENDERER_FALLBACKS."""
    from core.settings_registry import default, has
    if has(key):
        return default(key)
    absent = object()
    value = factory_value(key, absent)
    if value is not absent:
        return value
    if key in RENDERER_FALLBACKS:
        return copy.deepcopy(RENDERER_FALLBACKS[key])
    raise KeyError(key)
