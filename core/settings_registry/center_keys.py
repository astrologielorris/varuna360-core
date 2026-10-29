# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The (on, min virupas) setting keys of the two center drawings (SPEC-TJK-003 §4.5,
SPEC-VAC-001 §4.5), declared once: their ``Setting`` rows in ``chart``, their controllers
and the render CLI read them here (W6 R5). Plain strings, no import (the SI architecture
guard reaches this module from the controllers)."""

TAJIKA_CENTER_KEYS = ("chart.tajika_center_on", "chart.tajika_center_min_virupas")
VEDIC_CENTER_KEYS = ("chart.vedic_center_on", "chart.vedic_center_min_virupas")
