"""Theme catalog for Varuna360 (core-level, no Pro dependencies)."""

AVAILABLE_THEMES = [
    # Dark themes
    ("dark_teal.xml", "Dark Teal", True, ["#009688", "#00BFA5", "#1DE9B6"]),
    ("dark_blue.xml", "Dark Blue", True, ["#2196F3", "#1976D2", "#82B1FF"]),
    ("dark_amber.xml", "Dark Amber", True, ["#FFC107", "#FF8F00", "#FFD54F"]),
    ("dark_cyan.xml", "Dark Cyan", True, ["#00BCD4", "#00838F", "#18FFFF"]),
    ("dark_lightgreen.xml", "Dark Green", True, ["#8BC34A", "#558B2F", "#CCFF90"]),
    ("dark_pink.xml", "Dark Pink", True, ["#E91E63", "#AD1457", "#FF80AB"]),
    ("dark_purple.xml", "Dark Purple", True, ["#9C27B0", "#6A1B9A", "#EA80FC"]),
    ("dark_red.xml", "Dark Red", True, ["#F44336", "#C62828", "#FF8A80"]),
    ("dark_yellow.xml", "Dark Yellow", True, ["#FFEB3B", "#F9A825", "#FFFF8D"]),
    # Light themes
    ("light_teal.xml", "Light Teal", False, ["#009688", "#00BFA5", "#B2DFDB"]),
    ("light_blue.xml", "Light Blue", False, ["#2196F3", "#1976D2", "#BBDEFB"]),
    ("light_amber.xml", "Light Amber", False, ["#FFC107", "#FF8F00", "#FFECB3"]),
    ("light_cyan.xml", "Light Cyan", False, ["#00BCD4", "#00838F", "#B2EBF2"]),
    ("light_lightgreen.xml", "Light Green", False, ["#8BC34A", "#558B2F", "#DCEDC8"]),
    ("light_pink.xml", "Light Pink", False, ["#E91E63", "#AD1457", "#F8BBD9"]),
    ("light_purple.xml", "Light Purple", False, ["#9C27B0", "#6A1B9A", "#E1BEE7"]),
    ("light_red.xml", "Light Red", False, ["#F44336", "#C62828", "#FFCDD2"]),
    ("light_yellow.xml", "Light Yellow", False, ["#FFEB3B", "#F9A825", "#FFF9C4"]),
    ("light_orange.xml", "Light Orange", False, ["#FF9800", "#F57C00", "#FFE0B2"]),
]

THEME_NAME_TO_FILE = {name: fname for fname, name, _, _ in AVAILABLE_THEMES}
THEME_FILE_TO_NAME = {fname: name for fname, name, _, _ in AVAILABLE_THEMES}
