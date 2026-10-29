# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Find Chart store and search engine (docs/find-chart/design.md §4). No Qt.

Only ``store.py`` touches SQL; only ``extractors/`` call the calculation code;
``taxonomy.py`` is the one translator between labels and stored values.
"""
