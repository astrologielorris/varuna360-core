"""Shared semantic colors for desktop dignity cells and their legends."""
from ui.qt_theme import desat_hex, is_light_theme

# (dark background, dark foreground, light background, light foreground)
# Exaltation is indigo; debilitation is red, with explicit EX/DB labels retained.
DIGNITY_COLORS = {
    "EX": ("#303878", "#B9C5FF", "#E0E7FF", "#3730A3"),
    "MT": ("#4A1A6B", "#CE93D8", "#F3DEFA", "#7A1AA8"),
    "OH": ("#14406B", "#64B5F6", "#DCEFFD", "#0D5E9E"),
    "GF": ("#1A5C2A", "#A5D6A7", "#DDF7DD", "#1A7A1A"),
    "F":  ("#2A4D2A", "#C5E1A5", "#E8F5E8", "#3C6B3C"),
    "N":  ("#3A3A42", "#B8B8C0", "#EFEFF2", "#666670"),
    "E":  ("#5C4310", "#FFCC80", "#FDEEDA", "#9E5E0D"),
    "GE": ("#5C2E10", "#FFAB91", "#FDE3D6", "#A8430F"),
    "DB": ("#6B1010", "#FF6E6E", "#FBD9D7", "#C01810"),
}


def dignity_colors(code):
    """Return live, saturation-aware (background, foreground), or None."""
    colors = DIGNITY_COLORS.get(code)
    if colors is None:
        return None
    offset = 2 if is_light_theme() else 0
    return tuple(desat_hex(color) for color in colors[offset:offset + 2])
