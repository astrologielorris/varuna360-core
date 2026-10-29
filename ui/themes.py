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
    ("dark_orange.xml", "Dark Orange", True, ["#FF9800", "#F57C00", "#FFCC80"]),
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


# Themes qt-material does not ship (it has light_orange but no dark_orange).
# Kept as data here, not as a .xml in the tree, so no build allowlist has to
# learn a new file: bundled_theme_path() writes the XML into the user data
# dir on first use and hands qt-material that absolute path.
BUNDLED_THEME_COLORS = {
    # Light Orange's card accent in the standard qt-material dark ground.
    "dark_orange.xml": {
        "primaryColor": "#ff9800",
        "primaryLightColor": "#ffc947",
        "secondaryColor": "#232629",
        "secondaryLightColor": "#4f5b62",
        "secondaryDarkColor": "#31363b",
        "primaryTextColor": "#ffffff",
        "secondaryTextColor": "#ffffff",
    },
}


def bundled_theme_path(theme_file):
    """Absolute path to a generated XML for a theme qt-material lacks, or
    None when ``theme_file`` is not one of ours. The file name keeps its
    dark_/light_ prefix because qt-material reads light/dark off the path."""
    import os
    colors = BUNDLED_THEME_COLORS.get(os.path.basename(str(theme_file)))
    if colors is None:
        return None
    try:
        from state.user_data import get_user_data_dir
        out_dir = os.path.join(str(get_user_data_dir() or "."), "bundled_themes")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, os.path.basename(str(theme_file)))
        xml = ('<!--?xml version="1.0" encoding="UTF-8"?-->\n<resources>\n'
               + "".join(f'  <color name="{k}">{v}</color>\n'
                         for k, v in colors.items())
               + "</resources>\n")
        try:
            with open(path, encoding="utf-8") as handle:
                if handle.read() == xml:
                    return path
        except OSError:
            pass
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(xml)
        os.replace(tmp, path)          # atomic: Lite and full share the dir
        return path
    except Exception:
        return None
