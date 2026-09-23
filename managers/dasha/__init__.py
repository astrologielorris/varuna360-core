# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dasha subsystem package (SPEC-DSH-002, td-t761 wave 2).

Holds the pure calculation/rendering engine (`engine.py`) and, from w2-2, the
`VimshottariSideController` that drives one dasha side. Kept a bare package so
`import managers.dasha` stays inert: the engine (which imports `core.time_utils`)
is only pulled in when a caller imports `managers.dasha.engine` explicitly.
"""
