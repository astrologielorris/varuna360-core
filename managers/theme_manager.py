# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Theme Manager for Chart Calculator
===================================
Manages color themes and font settings for the application.

Themes:
- Blue Dark: macOS-inspired dark mode with blue accent
- Apex Predator: Red/black theme from Docusaurus website
- Celestial Harmony: Warm gold/cream light theme from Docusaurus

Fonts:
- Inter: Open source, free for commercial use (SIL OFL)
- SF Pro: Apple's system font (Apple platforms only)
- Helvetica Neue: Classic font (system or fallback to Arial)
"""

import os
import json
import platform

try:
    from utils.debug import debug_print
except ImportError:
    debug_print = print  # Fallback for standalone testing

# ============================================================================
# PATH CONFIGURATION
# ============================================================================
# Go up from managers/ to project root where fonts/ folder is located
_MANAGERS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MANAGERS_DIR)

# ============================================================================
# THEME DEFINITIONS
# ============================================================================

THEMES = {
    "System Default": {
        "name": "System Default",
        "bg": "#1a1a1a",               # CTK default dark bg
        "surface": "#2b2b2b",          # CTK default surface
        "accent": "#1f6aa5",           # CTK blue accent
        "accent_hover": "#144870",     # CTK blue hover
        "text": "#FFFFFF",             # White text
        "text_secondary": "#a0a0a0",   # Gray text
        "text_tertiary": "#707070",    # Darker gray
        "button_bg": "#1f6aa5",        # CTK blue buttons
        "button_hover": "#144870",     # CTK blue hover
        "border": "#3d3d3d",           # Border
        "title_bar": "#2b2b2b",        # Title bar
        "chart_text": "#FFFFFF",       # Chart text
        "ctk_builtin": "blue",         # Uses CTK built-in blue
        "preserve_all": True,          # Don't override ANY widget colors
    },
    "Dark Mode": {
        "name": "Dark Mode",
        "bg": "#0D0D0D",              # Near black background
        "surface": "#1C1C1E",          # Card/panel background
        "accent": "#007AFF",           # macOS blue
        "accent_hover": "#0056B3",     # Darker blue for hover
        "text": "#FFFFFF",             # Primary text
        "text_secondary": "#98989D",   # Secondary text
        "text_tertiary": "#636366",    # Tertiary text
        "button_bg": "#2C2C2E",        # Button background
        "button_hover": "#3A3A3C",     # Button hover
        "border": "#3D3D3D",           # Border color
        "title_bar": "#1C1C1E",        # Title bar background
        "chart_text": "#FFFFFF",       # Text on chart
        "ctk_builtin": "blue",         # Uses CustomTkinter's built-in blue theme
    },
    "Blue Dark": {
        "name": "Blue Dark",
        "bg": "#0D0D0D",              # Near black background
        "surface": "#1C1C1E",          # Card/panel background
        "accent": "#007AFF",           # macOS blue
        "accent_hover": "#0056B3",     # Darker blue for hover
        "text": "#FFFFFF",             # Primary text
        "text_secondary": "#98989D",   # Secondary text
        "text_tertiary": "#636366",    # Tertiary text
        "button_bg": "#2C2C2E",        # Button background
        "button_hover": "#3A3A3C",     # Button hover
        "border": "#3D3D3D",           # Border color
        "title_bar": "#1C1C1E",        # Title bar background
        "chart_text": "#FFFFFF",       # Text on chart
        "ctk_builtin": "blue",         # Uses CustomTkinter's built-in blue theme
    },
    "Apex Predator": {
        "name": "Apex Predator",
        "bg": "#1a1a1a",               # Dark background
        "surface": "#000000",          # Pure black surface
        "accent": "#FF0000",           # Intense red
        "accent_hover": "#CC0000",     # Darker red for hover
        "text": "#C0C0C0",             # Silver text
        "text_secondary": "#880808",   # Dark red secondary
        "text_tertiary": "#666666",    # Gray tertiary
        "button_bg": "#36454F",        # Charcoal button
        "button_hover": "#4a5a6a",     # Lighter charcoal
        "border": "#880808",           # Red border
        "title_bar": "#2a0a0a",        # Dark red title bar
        "chart_text": "#C0C0C0",       # Silver chart text
    },
    "Celestial Harmony": {
        "name": "Celestial Harmony",
        "bg": "#FFF8E7",               # Cream background
        "surface": "#FFFEF9",          # Off-white surface
        "accent": "#D4AF37",           # Warm gold
        "accent_hover": "#B8963B",     # Darker gold
        "text": "#3E2723",             # Dark brown text
        "text_secondary": "#5D4037",   # Medium brown
        "text_tertiary": "#8D6E63",    # Light brown
        "button_bg": "#F5E6D3",        # Light tan button
        "button_hover": "#EED9C4",     # Slightly darker tan
        "border": "#D4AF37",           # Gold border
        "title_bar": "#F5E6D3",        # Tan title bar
        "chart_text": "#3E2723",       # Dark brown chart text
    },
}

# ============================================================================
# FONT DEFINITIONS
# ============================================================================

FONTS = {
    "Inter": {
        "name": "Inter",
        "family": "Inter Display",
        "fallback": "Segoe UI",
        "path": "fonts/Inter/extras/otf",
        "files": [
            "Inter-Regular.otf",
            "Inter-Medium.otf",
            "Inter-SemiBold.otf",
            "Inter-Bold.otf",
            "Inter-Light.otf",
            "InterDisplay-Regular.otf",
            "InterDisplay-Medium.otf",
            "InterDisplay-SemiBold.otf",
            "InterDisplay-Bold.otf",
        ],
        "license": "SIL Open Font License (FREE)",
    },
    "SF Pro": {
        "name": "SF Pro",
        "family": "SF Pro Display",
        "fallback": "Segoe UI",
        "path": "fonts/San-Francisco-Pro-Fonts",
        "files": [
            "SF-Pro-Display-Regular.otf",
            "SF-Pro-Display-Medium.otf",
            "SF-Pro-Display-Semibold.otf",
            "SF-Pro-Display-Bold.otf",
            "SF-Pro-Display-Light.otf",
        ],
        "license": "Apple Proprietary (Apple platforms only)",
    },
    "Helvetica Neue": {
        "name": "Helvetica Neue",
        "family": "Helvetica Neue",
        "fallback": "Arial",
        "path": None,  # System font
        "files": [],
        "license": "Linotype (Commercial)",
    },
}

# ============================================================================
# DEFAULT SETTINGS
# ============================================================================

DEFAULT_THEME = "System Default"
DEFAULT_FONT = "Inter"
CONFIG_FILE = ".theme_config.json"

# ============================================================================
# FONT REGISTRATION (Windows)
# ============================================================================

_fonts_registered = set()


def register_font(font_name, base_path=None):
    """
    Register a font for use in the application (Windows only).

    Args:
        font_name: Key from FONTS dictionary
        base_path: Base path to chart_calculation folder

    Returns:
        True if fonts loaded successfully, False otherwise
    """
    global _fonts_registered

    if font_name in _fonts_registered:
        return True

    if platform.system() != "Windows":
        _fonts_registered.add(font_name)
        return True

    font_config = FONTS.get(font_name)
    if not font_config or not font_config["path"]:
        # System font, no registration needed
        _fonts_registered.add(font_name)
        return True

    try:
        import ctypes
        from ctypes import wintypes

        gdi32 = ctypes.windll.gdi32
        AddFontResourceExW = gdi32.AddFontResourceExW
        AddFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        AddFontResourceExW.restype = ctypes.c_int

        FR_PRIVATE = 0x10  # Font is only available to this process

        # Determine base path (use project root where fonts/ folder is located)
        if base_path is None:
            base_path = PROJECT_ROOT

        fonts_dir = os.path.join(base_path, font_config["path"])

        if not os.path.exists(fonts_dir):
            debug_print(f"Font folder not found: {fonts_dir}")
            return False

        loaded = 0
        for font_file in font_config["files"]:
            font_path = os.path.join(fonts_dir, font_file)
            if os.path.exists(font_path):
                result = AddFontResourceExW(font_path, FR_PRIVATE, None)
                if result > 0:
                    loaded += 1

        if loaded > 0:
            _fonts_registered.add(font_name)
            debug_print(f"Loaded {loaded}/{len(font_config['files'])} {font_name} fonts")
            return True

        return False

    except Exception as e:
        debug_print(f"Could not load {font_name} fonts: {e}")
        return False


def get_font_family(font_name, base_path=None):
    """
    Get the font family name to use, registering if needed.

    Args:
        font_name: Key from FONTS dictionary
        base_path: Base path for font registration

    Returns:
        Font family name (primary or fallback)
    """
    font_config = FONTS.get(font_name)
    if not font_config:
        return "Arial"  # Ultimate fallback

    # Try to register the font
    if register_font(font_name, base_path):
        return font_config["family"]

    return font_config["fallback"]


# ============================================================================
# SETTINGS PERSISTENCE
# ============================================================================

def load_theme_config(base_path=None):
    """
    Load theme configuration from JSON file.

    Returns:
        dict with 'theme' and 'font' keys
    """
    if base_path is None:
        base_path = PROJECT_ROOT  # Config file is in project root

    config_path = os.path.join(base_path, CONFIG_FILE)

    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Validate loaded values
                if config.get('theme') not in THEMES:
                    config['theme'] = DEFAULT_THEME
                if config.get('font') not in FONTS:
                    config['font'] = DEFAULT_FONT
                return config
    except Exception as e:
        debug_print(f"Error loading theme config: {e}")

    return {'theme': DEFAULT_THEME, 'font': DEFAULT_FONT}


def save_theme_config(theme_name, font_name, base_path=None):
    """
    Save theme configuration to JSON file.

    Args:
        theme_name: Theme key from THEMES
        font_name: Font key from FONTS
        base_path: Directory to save config file
    """
    if base_path is None:
        base_path = PROJECT_ROOT  # Config file is in project root

    config_path = os.path.join(base_path, CONFIG_FILE)

    try:
        config = {
            'theme': theme_name,
            'font': font_name,
        }
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        debug_print(f"Error saving theme config: {e}")


# ============================================================================
# THEME APPLICATION HELPERS
# ============================================================================

def get_theme(theme_name):
    """Get theme dictionary by name."""
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def get_font(font_name):
    """Get font configuration by name."""
    return FONTS.get(font_name, FONTS[DEFAULT_FONT])


def list_themes():
    """Return list of available theme names."""
    return list(THEMES.keys())


def list_fonts():
    """Return list of available font names."""
    return list(FONTS.keys())


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    print("Available Themes:")
    for name, theme in THEMES.items():
        print(f"  - {name}: bg={theme['bg']}, accent={theme['accent']}")

    print("\nAvailable Fonts:")
    for name, font in FONTS.items():
        print(f"  - {name}: {font['family']} ({font['license']})")

    print("\nTesting font registration...")
    for font_name in FONTS:
        success = register_font(font_name)
        status = "OK" if success else "FAILED"
        print(f"  {font_name}: {status}")
