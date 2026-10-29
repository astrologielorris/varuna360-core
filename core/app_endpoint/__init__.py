# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Core app endpoint (SPEC-SET-003 §4.5b, W6e).

A small, private channel through which another process of the same user on
the same machine (``settings.py``, the Codex task server) sends ONE kind of
request to a running Varuna360 window:

- ``discovery`` (Qt-free): one file per instance,
  ``<user-data>/app_endpoints/<pid>.json``, mode 0600, holding the server
  name and a random 128-bit token; stale files are ignored;
- ``client`` (standard library only, so ``settings.py`` stays Qt-free): one
  JSON object per line, a 10 s timeout, typed errors;
- ``server`` (Qt): a ``QLocalServer`` on the GUI thread with a dispatch table
  of exactly one op slot, ``set_app_setting``, filled by W6b. Until then every
  request is answered ``refused`` with reason ``unavailable``.

This package never imports Pro. Importing it has no side effects.
"""
