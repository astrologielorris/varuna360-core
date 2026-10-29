# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What the in-app AI may change (AI setting redesign, td-bztjj; SPEC-SET-003
D-16 note, INV-17, SPEC-EDN-001 D-3). Qt-free, data only.

- ``rules.APP_AI``: an app setting (``rules.cli == "app"``) the in-app AI may
  change through the request service (the AI setting panel, the task tool
  ``set_app_setting``). ``settings.py`` and ``--set`` never do: they keep
  calculation keys only (``cli_store.check_key``, D-16).
- ``ASK_FIRST``: the keys that decide where data goes or what it costs. The
  service refuses them ``ask_first`` on every route except the AI setting
  panel's Allow (``AppSettingsRequests.apply(confirmed=True)``, in-process).
  Listed key by key, never by prefix (INV-17: explicit classification).
- ``PANEL_ONLY`` (AI setting redesign fix RD-3, Lorris's Q2 decision):
  calculation keys chosen on their own panels, with no Settings control
  (D-16 keeps them away from ``settings.py`` and ``--set``). The AI setting
  panel lists them and changes them only on the user's Allow there
  (``apply(confirmed=True)``, in-process); every request route (task tools,
  MCP, ``settings.py``, ``--set``) still refuses them. The Pro remote treats
  them as ordinary preferences (Lorris, 2026-10-11: agents drive the app
  through it for reference collection and tests): allowed with the saved
  toggle on and no lock over them.
"""
from __future__ import annotations

ASK_FIRST = frozenset((
    # which AI company receives the data, which model, how much it thinks
    "ai.default_provider", "ai.effort",
    "ai.task.engine", "ai.task.claude.model", "ai.task.claude.effort",
    "ai.task.codex.model", "ai.task.codex.effort",
    "ai.setting_panel.model",
    "vision.provider", "vision.model", "vision.effort",
    # switches that decide whether an AI is used
    "newedit.reading_use_ai", "transit.reading_date_use_ai",
    "transit.reading_date_auto_confirm",
    # where charts and files are read and written
    "paths.chart_folders", "paths.default_folder", "paths.library_root",
    "paths.screenshot_folder",
    "paths.kala_path", "paths.default_chart_format", "paths.data_dir",
))

PANEL_ONLY = frozenset((
    "dasha.zr.anchor", "dasha.zr.show_age",
    "zodiac.human_design",
))
