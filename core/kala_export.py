# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What Kala can be handed directly, and what has to be converted first.

SPEC-PERSIST-001 D-13 (td-rayw). "Open in Kala" used to decide by asking
whether the chart had a file at all: no path meant write a temp .chtk, a
path meant pass it through. That was safe only while every path WAS a .chtk.

With .toml as the default creation format the same test now passes a .toml
straight to Kala, which cannot read it. Rule 26 makes Kala the reference for
every cross-check in this project, so a silently broken hand-off would break
the instrument we check ourselves against.

Deliberately NOT a conversion of the file on disk: nothing the user owns is
rewritten. The chart is projected into a fresh temp .chtk for the launch and
the original stays exactly as it was.
"""

import os

#: The only extension Kala opens.
KALA_NATIVE_EXT = ".chtk"


def kala_can_open(path) -> bool:
    """True when `path` is an existing file Kala can read directly.

    Keyed on the EXTENSION, not on the path being absent — that was the
    defect. A missing file is not openable either: handing Kala a path that
    no longer exists launches it empty with no explanation.
    """
    if not path:
        return False
    path = str(path)
    if not path.lower().endswith(KALA_NATIVE_EXT):
        return False
    return os.path.exists(path)


def needs_conversion_for_kala(path) -> bool:
    """True when a file exists but is in a format Kala cannot open.

    Distinct from `not kala_can_open(path)`, which is also true when there
    is no file at all. Callers report those two cases differently.
    """
    if not path:
        return False
    return os.path.exists(str(path)) and not kala_can_open(path)
