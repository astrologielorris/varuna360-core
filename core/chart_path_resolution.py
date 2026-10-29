# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Select one fallback chart match without guessing a chart's identity.

Callers keep their own exact-path precedence, search roots and name rules.
This module reads no settings or chart contents and writes nothing.
"""
import os


class AmbiguousChartError(ValueError):
    def __init__(self, name, candidates):
        self.candidates = tuple(sorted(candidates))
        super().__init__(f"Ambiguous chart name {name!r}; use an exact path. Candidates:\n"
                         + "\n".join(self.candidates))


def select_chart_match(name, matches):
    """Keep a unique match's original spelling; otherwise return the missing
    name or refuse distinct paths. Repeated/symlink paths are one match."""
    unique = {}
    for path in matches:
        identity = os.path.normcase(os.path.realpath(path))
        unique.setdefault(identity, path)
    if len(unique) > 1:
        raise AmbiguousChartError(name, unique)
    return next(iter(unique.values()), name)
