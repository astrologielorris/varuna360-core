"""Painted size of a chart label that has its own Font Sizes area (SPEC-FONT-001 §11.9).

Planet Degrees, House Numbers and Cusp Degrees replaced Chart Labels at sites
that scaled by ``scaled_tier_size(base, 'chart_labels')``. That helper's factor
is ``max(6, int(default * scale)) / default``: the integer step depends on the
area's default, so swapping the area name alone would move these labels by a
point at a Display Scale other than 100% with every area at its default. This
keeps the former Display Scale step exactly and multiplies in the user's area
choice, so at default areas the size is the former one at ANY scale.
"""
from ui.qt_theme import AREA_DEFAULTS, get_area_font_size, get_scale_factor, scaled_tier_size

_STEP = "chart_labels"   # the area whose Display Scale step these sites always used


def chart_area_size(base, area):
    """``base`` x (area value / area default) x the former Display Scale step."""
    if area == _STEP:
        return scaled_tier_size(base, area)
    step = max(6, int(AREA_DEFAULTS[_STEP] * get_scale_factor())) / AREA_DEFAULTS[_STEP]
    return max(1, round(base * get_area_font_size(area) / AREA_DEFAULTS[area] * step))
