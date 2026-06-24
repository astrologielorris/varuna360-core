#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
PySide6 Theme - Centralized Color Definitions
==============================================

STRICT RULES:
1. ALL colors must be defined here - no raw hex codes in panel/widget files
2. Import colors from this file: `from ui.qt_theme import COLORS, ACCENTS`
3. Each accent has 3 shades: base, hover, active
4. To change app theme, modify ONLY this file

Color Structure:
- BACKGROUNDS: 4 shades (black to gray)
- TEXT: 3 levels (white to dark gray)
- BORDERS: 2 levels (subtle, emphasis)
- ACCENTS: 4 colors (blue, orange, cyan, gold)
"""
import json
from pathlib import Path
from PySide6.QtGui import QFont

# =============================================================================
# LOAD SETTINGS FROM settings.json
# =============================================================================
def _load_settings():
    """Load settings from settings.json"""
    try:
        from state.user_data import get_settings_path
        with open(get_settings_path(), "r") as f:
            return json.load(f)
    except Exception:
        return {}

_settings = _load_settings()

# =============================================================================
# FONTS (from settings.json - change there to update entire app)
# =============================================================================
FONTS = _settings.get("fonts", {
    "primary": "Inter",
    "monospace": "Inter",
    "chart": "Inter"
})

# Convenience shortcuts
FONT_PRIMARY = FONTS.get("primary", "Inter")
FONT_MONO = FONTS.get("monospace", "Inter")
FONT_CHART = FONTS.get("chart", "Inter")

# =============================================================================
# FONT SCALING (Phase 1 — Responsive UI)
# =============================================================================
# Semantic font size roles — base sizes in points at 100% scale.
# Map every hardcoded font-size in the app to one of these roles.
FONT_SIZES = {
    "title": 18,      # Panel/dialog titles, large headings
    "header": 14,     # Section headers, group box titles
    "subheader": 12,  # Sub-section labels, bold category names
    "body": 11,       # Main content text, table cells, list items
    "label": 10,      # Field labels, input labels, button text
    "small": 9,       # Secondary info, hints, descriptions
    "tiny": 8,        # Footnotes, badges, compact elements
    "caption": 7,     # Annotations, minimal text
}

# =============================================================================
# PER-AREA FONT SIZE OVERRIDES (SPEC-FONT-001)
# =============================================================================
# Base sizes in points for groups of UI regions that scale together. The user
# gets one spinbox per area in the Pro "Font Sizes" settings page. These compose
# with the global _scale_factor: effective = base * _scale_factor.
AREA_DEFAULTS = {
    "tables": 11,
    "table_headers": 12,
    "panel_titles": 14,
    "info_text": 11,
    "buttons": 10,
    "sidebar": 10,
    "status": 9,
    "tabs": 12,
}

_area_overrides = {}   # area_id -> user-chosen base pt size

# Scale factor — 1.0 = 100%. Updated at app startup from app_settings.json.
# Clamped to 0.6–1.6 so low-resolution screens can compact the UI and 4K
# screens can use a larger app-wide scale.
_scale_factor = 1.0
_SCALE_MIN = 0.6
_SCALE_MAX = 1.6


def get_scale_factor() -> float:
    """Return the current global font scale factor."""
    return _scale_factor


def set_scale_factor(factor: float):
    """Set the global font scale factor (clamped to 60%–160%)."""
    global _scale_factor
    _scale_factor = max(_SCALE_MIN, min(_SCALE_MAX, factor))


def scaled_size(role: str) -> int:
    """Return the scaled point size for a semantic font role.

    Args:
        role: One of FONT_SIZES keys (title, header, subheader, body, label, small, tiny, caption)

    Returns:
        Scaled size in points (integer, minimum 6pt)
    """
    base = FONT_SIZES.get(role, FONT_SIZES["body"])
    return max(6, int(base * _scale_factor))


def scaled_px(base_px: int) -> int:
    """Scale a raw pixel value by the current factor.

    Use for CSS font-size and widget dimension constraints (min-width, min-height).

    Args:
        base_px: Base pixel value at 100% scale

    Returns:
        Scaled pixel value (integer, minimum 5px)
    """
    return max(5, int(base_px * _scale_factor))


def scaled_font(role: str, family: str = None, bold: bool = False) -> QFont:
    """Create a QFont scaled to the current factor.

    Args:
        role: Semantic size role from FONT_SIZES
        family: Font family (defaults to FONT_PRIMARY)
        bold: Whether to use bold weight

    Returns:
        QFont configured with the scaled point size
    """
    font = QFont(family or FONT_PRIMARY)
    font.setPointSize(scaled_size(role))
    if bold:
        font.setBold(True)
    return font


# =============================================================================
# AREA-BASED FONT SIZING (SPEC-FONT-001)
# =============================================================================
# Like the scaled_size/scaled_px/scaled_font trio above, but keyed by font area
# (tables, table_headers, ...) instead of semantic role. Areas carry per-user
# overrides; roles do not. int() truncation matches scaled_size() so migrated
# and unmigrated code stay pixel-consistent.

def set_area_font_size(area_id: str, base_pt: int):
    """Set per-area base font size in points. Caller persists via SettingsManager."""
    _area_overrides[area_id] = base_pt


def get_area_font_size(area_id: str) -> int:
    """Return user override or default for this area, in points."""
    return _area_overrides.get(area_id, AREA_DEFAULTS.get(area_id, 11))


def reset_area_font_sizes():
    """Clear all area overrides back to defaults."""
    _area_overrides.clear()


def scaled_area_size(area_id: str) -> int:
    """Return effective POINT size for a font area (base * scale).
    Use with QFont.setPointSize() and scaled_area_font()."""
    base = get_area_font_size(area_id)
    return max(6, int(base * _scale_factor))


def scaled_area_px(area_id: str) -> int:
    """Return effective PIXEL size for a font area.
    Use in CSS stylesheet strings: font-size: {scaled_area_px('tables')}px
    Area defaults are pixel values (matching existing scaled_px behavior),
    so this applies only the scale factor with no pt-to-px conversion."""
    base = get_area_font_size(area_id)
    return max(5, int(base * _scale_factor))


def scaled_area_font(area_id: str, family: str = None,
                     bold: bool = False) -> QFont:
    """Return a ready-to-use QFont for the given area."""
    fam = family or FONT_PRIMARY
    font = QFont(fam)
    font.setPointSize(scaled_area_size(area_id))
    if bold:
        font.setWeight(QFont.Weight.Bold)
    return font


def detect_optimal_scale(screen=None) -> float:
    """Detect optimal scale factor from Qt screen metrics.

    Qt exposes the same QScreen API on macOS, Linux, and Windows.  DPI is useful
    for high-density displays, but many normal 720p/1080p monitors report 96 DPI,
    so resolution is also used to keep the app compact on lower-resolution
    screens.

    Args:
        screen: QScreen instance (defaults to primary screen)

    Returns:
        Optimal scale factor clamped to 0.6-1.6.
    """
    try:
        if screen is None:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
        if screen:
            dpi = screen.logicalDotsPerInch()
            size = screen.size()
            width = size.width()
            height = size.height()

            if width <= 1366 or height <= 800:
                resolution_scale = 0.6
            elif width <= 1920 or height <= 1080:
                resolution_scale = 0.8
            elif width <= 2560 or height <= 1440:
                resolution_scale = 1.1
            elif width >= 3840 or height >= 2160:
                resolution_scale = 1.5
            else:
                resolution_scale = 1.2

            dpi_scale = dpi / 96.0  # 96 DPI = baseline
            optimal = max(resolution_scale, dpi_scale)
            return max(_SCALE_MIN, min(_SCALE_MAX, optimal))
    except Exception:
        pass
    return 1.0


# =============================================================================
# BACKGROUNDS (darkest to lightest)
# =============================================================================
BACKGROUNDS = {
    "bg": "#0D0D0D",        # Main window - almost black
    "surface": "#1C1C1E",   # Panels, cards - charcoal
    "hover": "#3A3A3C",     # Hover states - dark gray
    "elevated": "#48484A",  # Popups, dialogs - medium gray
}

# =============================================================================
# TEXT (brightest to dimmest)
# =============================================================================
TEXT = {
    "primary": "#FFFFFF",   # Main text - white
    "secondary": "#AAAAAA", # Labels, hints - light gray
    "tertiary": "#666666",  # Disabled, subtle - dark gray
    "inverse": "#000000",   # Text on light backgrounds - black
}

# =============================================================================
# BORDERS
# =============================================================================
BORDERS = {
    "subtle": "#3D3D3D",    # List separators, panel edges
    "emphasis": "#5A5A5C",  # Focused inputs, active borders
}

# =============================================================================
# ACCENTS (each has base, hover, active)
# =============================================================================
ACCENTS = {
    # Main app accent - Blue (tabs, selections, Karakas/Strength)
    "blue": {
        "base": "#007AFF",
        "hover": "#0066D6",
        "active": "#0055B3",
    },
    # Vedanga dasha panel - Orange
    "orange": {
        "base": "#FF8C00",
        "hover": "#E67E00",
        "active": "#CC7000",
    },
    # Vimshottari dasha panel - Cyan
    "cyan": {
        "base": "#00BFFF",
        "hover": "#00A6DD",
        "active": "#0099CC",
    },
    # Chart grid - Gold
    "gold": {
        "base": "#DAA520",
        "hover": "#C4941A",
        "active": "#FFD700",  # Bright gold for selections
    },
    # Green action button
    "green": {
        "base": "#4CAF50",
        "hover": "#45A049",
        "active": "#3D8B40",
    },
}

# =============================================================================
# STATUS (semantic colors)
# =============================================================================
STATUS = {
    "success": "#4CAF50",   # Green - positive
    "warning": "#FF9500",   # Orange - caution
    "error": "#FF3B30",     # Red - danger
    "info": "#007AFF",      # Blue - informational
}

# =============================================================================
# CONVENIENCE SHORTCUTS
# =============================================================================
# For quick access without nested dict lookups

# Backgrounds
BG = BACKGROUNDS["bg"]
SURFACE = BACKGROUNDS["surface"]
HOVER = BACKGROUNDS["hover"]

# Text
TEXT_PRIMARY = TEXT["primary"]
TEXT_SECONDARY = TEXT["secondary"]
TEXT_TERTIARY = TEXT["tertiary"]

# Borders
BORDER = BORDERS["subtle"]
BORDER_EMPHASIS = BORDERS["emphasis"]

# Accent bases (most commonly used)
BLUE = ACCENTS["blue"]["base"]
ORANGE = ACCENTS["orange"]["base"]
CYAN = ACCENTS["cyan"]["base"]
GOLD = ACCENTS["gold"]["base"]

# =============================================================================
# PANEL-SPECIFIC MAPPINGS
# =============================================================================
# Which accent color each panel uses

PANEL_COLORS = {
    "vedanga": ACCENTS["orange"],
    "vimshottari": ACCENTS["cyan"],
    "karakas": ACCENTS["blue"],
    "strength": ACCENTS["blue"],
    "chart": ACCENTS["gold"],
}

# =============================================================================
# STYLESHEET HELPERS
# =============================================================================

def get_button_style(accent_name="blue"):
    """Generate QPushButton stylesheet. Dual-path: frozen dark / dynamic light.
    When accent_name is "blue" (default), follows the theme's primary color.
    Panel-specific accents (orange, cyan, gold) remain hardcoded."""
    # "blue" follows theme primary; other accents stay semantic
    if accent_name == "blue":
        accent = get_theme_accent()
    else:
        accent = ACCENTS.get(accent_name, ACCENTS["blue"])
    if is_light_theme():
        theme = get_theme_colors()
        return f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {accent["base"]};
                border-radius: 3px; font-size: {scaled_px(10)}px; font-weight: bold;
                min-width: {scaled_px(22)}px; max-width: {scaled_px(22)}px; min-height: {scaled_px(22)}px; max-height: {scaled_px(22)}px;
            }}
            QPushButton:hover {{ background-color: {theme["secondary_light"]}; }}
            QPushButton:checked {{ background-color: {accent["active"]}; color: {theme["primary_text"]}; }}
        """
    # DARK: frozen backgrounds + dynamic accent
    return f"""
        QPushButton {{
            background-color: {SURFACE};
            color: {TEXT_PRIMARY};
            border: 1px solid {accent["base"]};
            border-radius: 3px; font-size: {scaled_px(10)}px; font-weight: bold;
            min-width: {scaled_px(22)}px; max-width: {scaled_px(22)}px; min-height: {scaled_px(22)}px; max-height: {scaled_px(22)}px;
        }}
        QPushButton:hover {{ background-color: {HOVER}; }}
        QPushButton:checked {{ background-color: {accent["active"]}; color: {TEXT_PRIMARY}; }}
    """

def get_list_style(accent_name="blue"):
    """
    Generate QListWidget stylesheet for a given accent color.

    Uses theme colors for background - changes with light/dark theme.

    Args:
        accent_name: IGNORED - kept for API compatibility

    Returns:
        str: Complete QListWidget stylesheet
    """
    theme = get_theme_colors()
    return f"""
        QListWidget {{
            background-color: {theme["secondary_dark"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
        }}
        QListWidget::item {{
            padding: {scaled_px(4)}px;
            border-bottom: 1px solid {theme["secondary_light"]};
        }}
        QListWidget::item:selected {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
    """

def get_header_style(accent_name="blue"):
    """
    Generate panel header stylesheet.

    Args:
        accent_name: One of "blue", "orange", "cyan", "gold"

    Returns:
        str: Complete header stylesheet
    """
    if accent_name == "blue":
        accent = get_theme_accent()
    else:
        accent = ACCENTS.get(accent_name, ACCENTS["blue"])
    return f"QWidget {{ background-color: {accent['base']}; border-radius: 4px; }}"

def get_panel_style():
    """Generate panel background. Dual-path: frozen dark / dynamic light."""
    if is_light_theme():
        theme = get_theme_colors()
        return f"QWidget {{ background-color: {theme['secondary_dark']}; }}"
    return f"QWidget {{ background-color: {BG}; }}"

def get_frame_style():
    """Generate frame/card style. Dual-path: frozen dark / dynamic light."""
    if is_light_theme():
        theme = get_theme_colors()
        return f"QWidget {{ background-color: {theme['secondary']}; border-radius: 4px; }}"
    return f"QWidget {{ background-color: {SURFACE}; border-radius: 4px; }}"


def get_group_box_style():
    """Generate QGroupBox style. Dual-path: frozen dark / dynamic light."""
    if is_light_theme():
        theme = get_theme_colors()
        return f"""
            QGroupBox {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px; margin-top: 12px;
                padding: 15px 10px 10px 10px;
                font-weight: bold; color: {theme['secondary_text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 10px; padding: 0 5px; color: {GOLD};
            }}
        """
    # DARK: original frozen constants
    return f"""
        QGroupBox {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 8px; margin-top: 12px;
            padding: 15px 10px 10px 10px;
            font-weight: bold; color: {TEXT_PRIMARY};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; subcontrol-position: top left;
            left: 10px; padding: 0 5px; color: {GOLD};
        }}
    """


def get_scroll_style():
    """Generate scrollbar style. Dual-path: frozen dark / dynamic light."""
    if is_light_theme():
        theme = get_theme_colors()
        return f"""
            QScrollArea {{ background-color: {theme["secondary_dark"]}; border: none; }}
            QScrollBar:vertical {{ background-color: {theme["secondary_dark"]}; width: 8px; }}
            QScrollBar::handle:vertical {{ background-color: {theme["secondary_light"]}; border-radius: 4px; }}
        """
    # DARK: original frozen constants
    return f"""
        QScrollArea {{ background-color: {BG}; border: none; }}
        QScrollBar:vertical {{ background-color: {BG}; width: 8px; }}
        QScrollBar::handle:vertical {{ background-color: {BORDER}; border-radius: 4px; }}
    """

def get_primary_button_style():
    """Generate PRIMARY button style. Filled with theme accent, adaptive disabled state."""
    accent = get_theme_accent()
    theme = get_theme_colors()
    if is_light_theme():
        disabled_bg = theme["secondary_light"]
    else:
        disabled_bg = HOVER
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {accent["light"]},
                stop:1 {accent["base"]});
            color: {theme["primary_text"]};
            border: 1px solid {accent["hover"]}; border-radius: 4px; font-size: {scaled_px(12)}px;
            font-weight: bold; padding: {scaled_px(8)}px {scaled_px(16)}px; min-height: {scaled_px(32)}px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {accent["base"]},
                stop:1 {accent["hover"]});
        }}
        QPushButton:pressed {{ background-color: {accent["active"]}; }}
        QPushButton:disabled {{ background-color: {disabled_bg}; color: {theme["secondary_light"]}; }}
    """

def get_secondary_button_style():
    """Generate SECONDARY button style. Dual-path: frozen dark / dynamic light."""
    accent = get_theme_accent()
    if is_light_theme():
        theme = get_theme_colors()
        return f"""
            QPushButton {{
                background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]}; border-radius: 4px;
                font-size: {scaled_px(12)}px; padding: {scaled_px(8)}px {scaled_px(16)}px; min-height: {scaled_px(32)}px;
            }}
            QPushButton:hover {{ background-color: {theme["secondary_light"]}; border-color: {accent["base"]}; }}
            QPushButton:pressed {{ background-color: {theme["secondary_dark"]}; }}
        """
    # DARK: frozen backgrounds + accent-tinted border at rest
    return f"""
        QPushButton {{
            background-color: {SURFACE}; color: {TEXT_PRIMARY};
            border: 1px solid {accent["hover"]}; border-radius: 4px;
            font-size: {scaled_px(12)}px; padding: {scaled_px(8)}px {scaled_px(16)}px; min-height: {scaled_px(32)}px;
        }}
        QPushButton:hover {{ background-color: {HOVER}; border-color: {accent["base"]}; }}
        QPushButton:pressed {{ background-color: {BG}; border-color: {accent["active"]}; }}
    """

# =============================================================================
# BUTTON RULES (IMPORTANT)
# =============================================================================
"""
BUTTON COLOR RULES:

1. PRIMARY BUTTONS (main action) → BLUE filled
   - Use: Save, Submit, Confirm, Add, Create
   - Style: get_primary_button_style()

2. SECONDARY BUTTONS (less important) → Gray outlined
   - Use: Cancel, Back, Close
   - Style: get_secondary_button_style()

3. PANEL-SPECIFIC BUTTONS → Panel accent color
   - Vedanga buttons: Orange border/active
   - Vimshottari buttons: Cyan border/active
   - Varga buttons: Gold active
   - Style: get_button_style("accent_name")

4. DANGER BUTTONS → Red
   - Use: Delete, Remove, Clear
   - Add STATUS["error"] as background
"""

# =============================================================================
# COLOR REFERENCE (for documentation)
# =============================================================================
"""
VISUAL REFERENCE:

BACKGROUNDS (dark to light):
█████ #0D0D0D  bg        (almost black)
█████ #1C1C1E  surface   (charcoal)
█████ #3A3A3C  hover     (dark gray)
█████ #48484A  elevated  (medium gray)

TEXT (bright to dim):
█████ #FFFFFF  primary   (white)
█████ #AAAAAA  secondary (light gray)
█████ #666666  tertiary  (dark gray)

ACCENTS:
█████ #007AFF  blue      (main accent)
█████ #FF8C00  orange    (vedanga)
█████ #00BFFF  cyan      (vimshottari)
█████ #DAA520  gold      (chart grid)
"""

# =============================================================================
# QT-MATERIAL THEME INTEGRATION
# =============================================================================
import os

def _darken_color(hex_color, factor=0.7):
    """
    Darken a hex color by a factor.

    Args:
        hex_color: Color in #RRGGBB format
        factor: 0.0 = black, 1.0 = unchanged (default 0.7 = 30% darker)

    Returns:
        str: Darkened color in #RRGGBB format
    """
    try:
        hex_color = hex_color.lstrip('#')
        r = int(int(hex_color[0:2], 16) * factor)
        g = int(int(hex_color[2:4], 16) * factor)
        b = int(int(hex_color[4:6], 16) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except (ValueError, IndexError):
        return hex_color  # Return unchanged if parsing fails


def is_light_theme():
    """Detect if the current qt-material theme is light or dark.

    Light themes use dark text on light backgrounds; dark themes use
    light text on dark backgrounds. We check QTMATERIAL_SECONDARYTEXTCOLOR:
    dark text (low RGB sum) = light theme.
    """
    text_hex = os.environ.get("QTMATERIAL_SECONDARYTEXTCOLOR", "#FFFFFF")
    try:
        r = int(text_hex[1:3], 16)
        g = int(text_hex[3:5], 16)
        b = int(text_hex[5:7], 16)
        return (r + g + b) < 400  # dark text = light theme
    except (ValueError, IndexError):
        return False  # default to dark


def get_theme_colors():
    """
    Get current qt-material theme colors from environment variables.

    IMPORTANT: This function is UNCHANGED from the original working version.
    It always reads env vars with frozen dark constants as fallbacks.
    Light/dark branching is done in the HELPER FUNCTIONS instead.

    Returns:
        dict: Theme colors with fallbacks if not using qt-material
    """
    primary = os.environ.get("QTMATERIAL_PRIMARYCOLOR", BLUE)

    return {
        "primary": primary,
        "primary_dark": _darken_color(primary, 0.7),
        "primary_light": os.environ.get("QTMATERIAL_PRIMARYLIGHTCOLOR", "#5EADFF"),
        "primary_text": os.environ.get("QTMATERIAL_PRIMARYTEXTCOLOR", TEXT_PRIMARY),
        "secondary": os.environ.get("QTMATERIAL_SECONDARYCOLOR", SURFACE),
        "secondary_dark": os.environ.get("QTMATERIAL_SECONDARYDARKCOLOR", BG),
        "secondary_light": os.environ.get("QTMATERIAL_SECONDARYLIGHTCOLOR", HOVER),
        "secondary_text": os.environ.get("QTMATERIAL_SECONDARYTEXTCOLOR", TEXT_PRIMARY),
    }


def get_theme_accent():
    """Get accent color tones derived from the current qt-material theme primary.

    Returns a dict matching ACCENTS structure: {base, hover, active}.
    Use this instead of ACCENTS["blue"] when you want the button/highlight
    color to follow the user's selected theme (teal, pink, amber, etc.).
    """
    theme = get_theme_colors()
    return {
        "base": theme["primary"],
        "hover": theme["primary_dark"],
        "active": _darken_color(theme["primary"], 0.55),
        "light": theme["primary_light"],
    }


def get_3d_button_style(accent_name="blue", size="medium"):
    """
    Generate 3D-style QPushButton with gradients and depth effect.

    ALL colors from theme - no hardcoded accent colors.

    Args:
        accent_name: IGNORED - kept for API compatibility
        size: "small" (22px), "medium" (24px), "large" (36px), or "text" (auto-width)

    Returns:
        str: QPushButton stylesheet with 3D effect
    """
    theme = get_theme_colors()

    # Size presets - optimized for dasha panel (195px width).  Compact display
    # scales should shrink the surrounding UI, but these controls need a minimum
    # touch/click target so the 1-5 dasha level buttons do not collapse.
    # "text" size has no width constraints - for text buttons
    sizes = {
        "small": {"height": max(22, scaled_px(22)), "font": max(9, scaled_px(10)), "radius": 5, "padding": f"{max(2, scaled_px(2))}px"},
        "medium": {"height": max(24, scaled_px(24)), "font": max(9, scaled_px(10)), "radius": 6, "padding": f"{max(2, scaled_px(2))}px"},
        "large": {"height": max(32, scaled_px(32)), "font": max(10, scaled_px(12)), "radius": 8, "padding": f"{max(2, scaled_px(2))}px"},
        "text": {"height": scaled_px(32), "font": scaled_px(12), "radius": 6, "padding": f"{scaled_px(8)}px {scaled_px(16)}px"},
    }
    s = sizes.get(size, sizes["medium"])

    # Width constraints only for icon buttons (small/medium/large), not for text
    width_constraints = ""
    if size in ("small", "medium", "large"):
        widths = {
            "small": max(24, scaled_px(22)),
            "medium": max(26, scaled_px(24)),
            "large": max(36, scaled_px(36)),
        }
        w = widths[size]
        width_constraints = f"min-width: {w}px; max-width: {w}px;"

    # 3D button with primary tint at top for theme visibility
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:0.3 {theme["secondary_light"]},
                stop:0.7 {theme["secondary"]},
                stop:1 {theme["secondary_dark"]});
            color: {theme["secondary_text"]};
            border: 1px solid {theme["primary_light"]};
            border-radius: {s["radius"]}px;
            font-size: {s["font"]}px;
            font-weight: bold;
            {width_constraints}
            min-height: {s["height"]}px;
            padding: {s["padding"]};
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["secondary_light"]},
                stop:0.5 {theme["secondary_light"]},
                stop:1 {theme["secondary"]});
            border: 1px solid {theme["primary"]};
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["secondary_dark"]},
                stop:0.5 {theme["secondary"]},
                stop:1 {theme["secondary_light"]});
            border: 1px solid {theme["primary"]};
        }}
        QPushButton:checked {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:0.5 {theme["primary"]},
                stop:1 {theme["secondary"]});
            color: {theme["primary_text"]};
            border: 2px solid {theme["primary_light"]};
        }}
    """


def get_dasha_header_height() -> int:
    """Height for the two-row dasha panel header.

    The header contains a title row plus the 1-5 level-button row. At compact
    display scales, scaling 62px down clips the buttons, so keep the low-scale
    floor while still allowing larger scales to grow.
    """
    return max(62, scaled_px(62))


def get_dasha_level_button_size() -> tuple[int, int]:
    """Fixed size for dasha level buttons, matching get_3d_button_style small."""
    return max(24, scaled_px(22)), max(22, scaled_px(22))


def get_tab_bar_style(compact=False):
    """
    Generate QTabWidget/QTabBar stylesheet matching screenshot 112 design.

    Uses qt-material theme colors for active tab highlight.

    Args:
        compact: If True, use smaller padding/font for tiled/narrow windows.

    Returns:
        str: QTabWidget and QTabBar stylesheet
    """
    theme = get_theme_colors()

    pad = f"{scaled_px(3)}px {scaled_px(6)}px" if compact else f"{scaled_px(8)}px {scaled_px(16)}px"
    tabs_px = scaled_area_px('tabs')
    font = f"{tabs_px}px" if not compact else f"{max(5, int(tabs_px * 0.83))}px"
    radius = "5px" if compact else "8px"
    margin = "1px" if compact else "2px"

    return f"""
        QTabWidget::pane {{
            border: none;
            background-color: {theme["secondary_dark"]};
        }}
        QTabWidget::tab-bar {{
            alignment: center;
        }}
        QTabBar {{
            background-color: {theme["secondary"]};
        }}
        QTabBar::tab {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["secondary_light"]},
                stop:1 {theme["secondary"]});
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_dark"]};
            border-bottom: none;
            border-top-left-radius: {radius};
            border-top-right-radius: {radius};
            padding: {pad};
            margin-right: {margin};
            font-size: {font};
            font-weight: bold;
        }}
        QTabBar::tab:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["secondary_light"]},
                stop:1 {theme["secondary_light"]});
        }}
        QTabBar::tab:selected {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:0.5 {theme["primary"]},
                stop:1 {theme["secondary"]});
            color: {theme["primary_text"]};
            border: 1px solid {theme["primary"]};
            border-bottom: none;
        }}
    """


def get_menu_bar_style():
    """
    Generate QMenuBar stylesheet matching the dark theme.

    Returns:
        str: QMenuBar and QMenu stylesheet
    """
    theme = get_theme_colors()

    return f"""
        QMenuBar {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            padding: 2px;
            spacing: 3px;
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 4px 12px;
            border-radius: 4px;
        }}
        QMenuBar::item:selected {{
            background: {theme["secondary_light"]};
        }}
        QMenuBar::item:pressed {{
            background: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
        QMenu {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_dark"]};
            border-radius: 4px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {theme["secondary_dark"]};
            margin: 4px 8px;
        }}
    """


def get_panel_header_3d_style(accent_name="blue"):
    """
    Generate 3D panel header style with gradient.

    Args:
        accent_name: "blue", "orange", "cyan", "gold"

    Returns:
        str: Header widget stylesheet
    """
    theme = get_theme_colors()
    if accent_name == "blue":
        accent = get_theme_accent()
    else:
        accent = ACCENTS.get(accent_name, ACCENTS["blue"])

    # 3-stop gradient: light→base→dark (Material Design tonal hierarchy)
    light = accent.get("light", accent["base"])
    return f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {light},
                stop:0.5 {accent["base"]},
                stop:1 {accent["active"]});
            border-radius: 6px;
        }}
    """
