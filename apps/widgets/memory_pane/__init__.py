# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The chart memory pane, "Single Tray" design (SPEC-MEM-004).

Design source: mockups_chartlist-toolbar-r2_20261022-0828/designer_a/mockup_3.html
(its MC-INTENT block is the build spec). Structure:

- tokens: the colour table, built on the action bar's ``bar_tokens()``
- steps: the four width steps S0-S3 (what each one changes)
- paint: shared painting helpers (fonts, recessed surfaces, glass pills)
- chip / tray: the chart chips and the one recessed tray that scrolls them
- well: the profile well (name, count, page ticks) with the round LOAD key
- actions: the 2x2 glass pills and the ⋯ fold cell
- strip: the 60 px surface that lays the parts out for the current step

ChartMemoryPanel (apps/panels/chart_memory_panel.py) owns the data and the
behaviour; these widgets only draw and report clicks.
"""
