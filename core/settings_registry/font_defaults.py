# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Font-area factory sizes (SPEC-FONT-001, SPEC-SET-003). Data only, no imports: read by
the registry (display.fonts.*) and by ui.qt_theme.AREA_DEFAULTS, so the theme module does
not pull the rest of the registry in."""

# SPEC-FONT-001 per-area base sizes (points), one Font Sizes spinbox each; effective = base *
# the global scale. ui.qt_theme.AREA_DEFAULTS is built from this table, in this order.
FONT_DEFAULTS = (
    ("tables", 11), ("table_headers", 12), ("panel_titles", 14), ("info_text", 11),
    ("buttons", 10),
    # Shared primary/secondary QPushButton helpers (get_primary_button_style /
    # get_secondary_button_style). Default 12 = EXACT parity with the former
    # hardcoded scaled_px(12); a separate area from 'buttons' (10) so migrating
    # the shared helpers is not a size regression.
    ("action_buttons", 12),
    ("sidebar", 10), ("chart_memory", 10), ("status", 9), ("tabs", 12),
    # Text painted on the charts (sign names, ASC, ruler, pies, Cards of Truth); 16 = former size.
    ("chart_labels", 16),
    # Chart labels with their own size, so a teaching chart can carry very large degrees
    # (2026-10-08). Each default is the size the label had under chart_labels (parity).
    ("planet_degrees", 14), ("house_numbers", 23), ("cusp_degrees", 16),
)
LARGE_FONT_AREAS = ("planet_degrees", "house_numbers", "cusp_degrees")  # bounds 7..48, others 7..24
