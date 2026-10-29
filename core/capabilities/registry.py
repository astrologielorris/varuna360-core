# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Explicit list of capability modules (AIC plan 2 W6).

Each import registers its capabilities. Static on purpose: PyInstaller and
the Lite manifest gate follow these imports; nothing is discovered at runtime.
Wave 1 modules are added here as W7 lands them.
"""

from core.capabilities import chart  # noqa: F401  get_chart
from core.capabilities import strength  # noqa: F401  get_strength
from core.capabilities import retinue  # noqa: F401  get_retinue, get_hora, get_trimsamsa, get_houses
from core.capabilities import dasha  # noqa: F401  get_dasha
from core.capabilities import right_dasha  # noqa: F401  get_planetary_ages, get_zodiacal_releasing
from core.capabilities import karakas_aspects  # noqa: F401  get_aspects, get_karakas
from core.capabilities import ascendant_guide  # noqa: F401  get_ascendant_guide
from core.capabilities import avastha  # noqa: F401  get_avastha
from core.capabilities import chart_retinue  # noqa: F401  get_chart_retinue_rings
from core.capabilities import chart_search  # noqa: F401  search_charts (library scope)
from core.capabilities import ingress  # noqa: F401  find_ingresses, body_track
