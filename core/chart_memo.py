# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""A memo per chart object for pure chart calculations (SPEC-VAC-001 W6 S6).

The td-w3kp pattern of ``calculate_all_tajika_aspects``: chart_factory builds a NEW Chart
for every mode, ayanamsa or time change (never an in-place mutation) and libaditya Chart
compares by identity, so a weak key per chart object never serves a stale result. A chart
that cannot be weakly referenced (a positions dict) is computed every time. The result is
shared: callers read it and never change it.
"""
from __future__ import annotations

import functools
import inspect
import weakref


def memo_per_chart(compute):
    """``compute(chart, ...)`` cached per chart object and bound arguments (defaults
    applied, so ``f(c)`` and ``f(c, threshold=0)`` share one entry); ``__wrapped__``
    is the uncached function."""
    memo = weakref.WeakKeyDictionary()
    signature = inspect.signature(compute)

    @functools.wraps(compute)
    def cached(chart, *args, **kwargs):
        bound = signature.bind(chart, *args, **kwargs)
        bound.apply_defaults()
        key = tuple(bound.arguments.values())[1:]
        try:
            bucket = memo.setdefault(chart, {})
        except TypeError:                    # not weakly referenceable: no memo
            return compute(chart, *args, **kwargs)
        if key not in bucket:
            bucket[key] = compute(chart, *args, **kwargs)
        return bucket[key]
    return cached
