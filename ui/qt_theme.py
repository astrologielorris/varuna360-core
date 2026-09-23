#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
    # Shared primary/secondary QPushButton helpers (get_primary_button_style /
    # get_secondary_button_style). Default 12 = EXACT parity with the former
    # hardcoded scaled_px(12); a separate area from 'buttons' (10) so migrating
    # the shared helpers is not a size regression.
    "action_buttons": 12,
    "sidebar": 10,
    "chart_memory": 10,
    "status": 9,
    "tabs": 12,
    # Glyph/cusp/degree/planet/ASC text painted directly on the chart wheel,
    # North-Indian chart, and body graph. Default 16 keeps these primary chart
    # labels readable at roughly their former size (they were 14-18pt hardcoded;
    # mapping them onto the smaller generic areas had shrunk them ~20-30%).
    "chart_labels": 16,
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


def scaled_area_factor(area_id: str) -> float:
    """Ratio of an area's EFFECTIVE size to its default, for scaling painted text
    that must keep an intrinsic multi-tier hierarchy while still responding to
    the per-area font setting AND the global display scale (SPEC-FONT-001 B5).

    Painted wheel/scene labels carry deliberate size tiers (e.g. 13 / 14 / 10)
    that a flat scaled_area_font() would collapse to one size. Scaling each tier
    literal by this factor preserves the ratios. At defaults (live base ==
    AREA_DEFAULTS, scale 1.0) the factor is EXACTLY 1.0 -> zero visual change on
    migration day (the parity principle). Callers use max(1, round(literal*f)).
    """
    base_default = AREA_DEFAULTS.get(area_id)
    if not base_default:
        return 1.0
    return scaled_area_size(area_id) / base_default


def scaled_tier_size(base: float, area_id: str = "chart_labels") -> int:
    """Tier-preserving painted point size: a base tier literal scaled by the
    area factor, floored at 1 (never 0). Single source for painted wheel/scene
    labels that carry intrinsic size tiers (SPEC-FONT-001 B5); at defaults the
    factor is 1.0 so base is returned unchanged (parity)."""
    return max(1, round(base * scaled_area_factor(area_id)))


def inject_buttons_font_px(qss: str) -> str:
    """Replace a hardcoded ``font-size: 10px`` in a semantic-hex pill/toggle
    template with the live scaled ``buttons`` area size (SPEC-FONT-001 B5). Keeps
    the template's on/off hex untouched; SINGLE home (was duplicated verbatim in
    two panels — GLM B5 LOW) so the corruption class (a too-broad literal replace
    matching the tail of a differently-indented line) is reasoned about once."""
    return qss.replace("font-size: 10px",
                       f"font-size: {scaled_area_px('buttons')}px")


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

# Chart-memory multi-selection borders; shared tokens preserve the existing palette.
MEMORY_SELECTION = {"base": "#FFA726", "hover": "#FFB74D"}

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
        QPushButton:checked {{ background-color: {accent["active"]}; color: {get_theme_colors()["primary_text"] if accent_name == "blue" else TEXT_PRIMARY}; }}
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
            border: 1px solid {accent["hover"]}; border-radius: 4px; font-size: {scaled_area_px('action_buttons')}px;
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
                font-size: {scaled_area_px('action_buttons')}px; padding: {scaled_px(8)}px {scaled_px(16)}px; min-height: {scaled_px(32)}px;
            }}
            QPushButton:hover {{ background-color: {theme["secondary_light"]}; border-color: {accent["base"]}; }}
            QPushButton:pressed {{ background-color: {theme["secondary_dark"]}; }}
        """
    # DARK: frozen backgrounds + accent-tinted border at rest
    return f"""
        QPushButton {{
            background-color: {SURFACE}; color: {TEXT_PRIMARY};
            border: 1px solid {accent["hover"]}; border-radius: 4px;
            font-size: {scaled_area_px('action_buttons')}px; padding: {scaled_px(8)}px {scaled_px(16)}px; min-height: {scaled_px(32)}px;
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


# =============================================================================
# GLOBAL UI COLOR SATURATION  (SPEC-SAT-001)
# -----------------------------------------------------------------------------
# One 0-100 slider desaturates the WHOLE UI live. THE INVARIANT is ONE
# application point per color (the "double-desaturation trap"): colors that flow
# through qt-material are desaturated once, at the theme-XML/env level
# (desaturated_theme_path below), so every get_theme_colors() call site inherits
# the muted hex for free. desat_hex() is applied ONLY to colors that NEVER pass
# through qt-material (the frozen fallback constants in get_theme_colors, the
# _PARI_SEM severity ramp, the element/hora/trimsamsa semantic palettes, and
# hardcoded hexes). Icons/background images go through desat_image(). Applying
# BOTH the XML desat AND desat_hex() to the same color multiplies S twice
# (S*s*s), so 50% would look like 25% — never do both to one color.
# =============================================================================
import colorsys
import math

_UI_SATURATION = 100  # module state, 0-100; 100 == fully saturated (no-op)

# =============================================================================
# DEEP DARK (SPEC-THM-001 — opt-in near-black variant of the active dark theme)
# =============================================================================
# The shipped dark themes sit around #232629; the New & Edit mockup is built on
# a near-black ground (#0D0D0D-#1C1C1E). This makes that an OPTION rather than a
# new theme: the SAME dark palette with its background family deepened, so the
# user's chosen accent and every existing contrast relationship survive.
#
# It rides the SAME single application point as the saturation rewrite
# (desaturated_theme_path -> apply_stylesheet), which is what keeps the
# stylesheet and every get_theme_colors() call site in agreement. Deepening
# get_theme_colors() instead would leave the qt-material chrome behind and
# reintroduce exactly the split SPEC-SAT-001 was written to avoid.
#
# None means "not read yet": the flag is resolved lazily from settings on first
# use, so a fresh BOOT picks it up with no boot-path change, and the settings
# page overrides it live via set_deep_dark().
_DEEP_DARK = None

#: Multiplier applied to the secondary (background) family only. 0.55 takes
#: dark_blue's #232629 to ~#131517 — near-black — while PRESERVING the relative
#: order of secondary / secondary_dark / secondary_light. Remapping them onto
#: the mockup's literal values would invert that order (the mockup's field is
#: darker than its card; qt-material's secondary_dark is LIGHTER than secondary)
#: and every panel in the app reads those keys, not just this one tab.
_DEEP_DARK_FACTOR = 0.55

#: Only these are deepened. Accents and text are untouched: darkening the accent
#: would change the user's chosen theme colour, and darkening the text would
#: cancel the contrast the darker ground just bought.
_DEEP_DARK_KEYS = ("secondaryColor", "secondaryLightColor", "secondaryDarkColor")


def _read_deep_dark_setting():
    """Resolve the persisted flag. Imported lazily to keep ui.qt_theme free of
    a manager dependency at import time."""
    try:
        from managers.settings_manager import get_settings
        return bool(get_settings().get("appearance.deep_dark", False))
    except Exception:
        return False


def get_deep_dark() -> bool:
    """True when the near-black variant is active (dark themes only)."""
    global _DEEP_DARK
    if _DEEP_DARK is None:
        _DEEP_DARK = _read_deep_dark_setting()
    return _DEEP_DARK


def set_deep_dark(enabled):
    """Set the flag for the CURRENT process. Persisting is the caller's job —
    the settings page writes appearance.deep_dark and then re-applies the theme.
    """
    global _DEEP_DARK
    _DEEP_DARK = bool(enabled)


def deep_key() -> str:
    """Cache-key fragment, '' when off — same convention as ``sat_key()`` so a
    cached pixmap cannot survive a change of ground."""
    return "_deep" if get_deep_dark() else ""


def _deepen_hex(hex_color, factor=None):
    """Scale a colour toward black by ``factor``, preserving hue."""
    if factor is None:
        factor = _DEEP_DARK_FACTOR
    h = str(hex_color).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return hex_color
    return "#%02x%02x%02x" % tuple(
        max(0, min(255, int(round(c * factor)))) for c in (r, g, b))


def _is_dark_theme_file(theme_file) -> bool:
    """True for a DARK theme file. Positive test, deliberately.

    The obvious spelling — "light" not in the name — is wrong on this theme set:
    ``dark_lightgreen.xml`` is a DARK theme with "light" in its filename, so the
    negative test silently skipped the rewrite on it and greyed out the option
    for a whole theme. Every shipped theme is named ``dark_*`` or ``light_*``,
    so asking for "dark" answers correctly for all of them.

    An unrecognised custom path is treated as NOT dark: declining to deepen
    something we cannot classify is the recoverable failure; deepening a light
    theme into mud is not.
    """
    return "dark" in os.path.basename(str(theme_file)).lower()


def set_ui_saturation(pct):
    """Set the global UI saturation (0-100). Clamped; non-numeric or non-finite
    ignored. NOTE: json.load accepts Infinity/NaN by default, and the boot caller
    invokes this OUTSIDE its json try-block, so a corrupt color_saturation value
    must never raise here (would crash startup)."""
    global _UI_SATURATION
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return
    if not math.isfinite(pct):
        return
    _UI_SATURATION = max(0, min(100, int(round(pct))))


def get_ui_saturation():
    """Return the current global UI saturation (0-100)."""
    return _UI_SATURATION


def sat_key():
    """Cache-key suffix encoding the current PALETTE VARIANT (saturation and
    deep dark), for icon/image caches.

    Returns '' at 100 so cache keys stay byte-identical to today (SPEC-SAT-001
    WI-4), else '_s<pct>' so a slider change produces DIFFERENT keys and a stale
    pixmap can never be served. Append to every string cache key that feeds a
    desat_image()-processed pixmap; for tuple keys append get_ui_saturation().
    """
    # Also carries the deep-dark variant. Every image cache in the app already
    # appends this one key, so folding the second palette variant in here wires
    # the whole invariant at ONE point instead of editing eight call sites —
    # and it makes the guarantee true rather than merely claimed: deep_key()
    # existed but had no callers, so a cached pixmap COULD have survived a
    # change of ground. Still '' in the default state, so keys stay
    # byte-identical to today.
    sat = "" if _UI_SATURATION >= 100 else f"_s{_UI_SATURATION}"
    return sat + deep_key()


def desat_hex(hex_color):
    """Desaturate a hex color toward grey by the global UI saturation.

    HSL model: S' = S * (sat/100); H and L untouched — preserving L keeps the
    is_light_theme() luminance logic valid. No-op fast path at sat == 100 so the
    original string is returned byte-identical. Accepts '#RGB', '#RRGGBB' and
    '#AARRGGBB' (the alpha nibble pair is preserved verbatim). Returns the input
    unchanged on malformed data so a bad color can never raise inside a
    stylesheet build.
    """
    return _desat_hex_at(hex_color, _UI_SATURATION)


_QSS_HEX_RE = None  # compiled lazily on first desat_qss call


def desat_qss(qss):
    """Desaturate EVERY ``#RRGGBB`` hex in a Qt stylesheet string (SPEC-SAT-001).

    Use to wrap a PLAIN (non-f-string) ``setStyleSheet("...")`` argument whose
    colors are hardcoded literals: ``setStyleSheet(desat_qss("... #4CAF50 ..."))``.
    No-op fast path at sat == 100 (byte-identical). Greys are unaffected (S=0).

    ONLY safe for stylesheets whose colors are LITERALS — do NOT run it over a
    string that already interpolates theme colors (``get_theme_colors()`` values
    are desaturated by the theme XML already; re-desaturating = double-desat).
    For those, wrap the individual literal hexes with ``desat_hex`` instead.
    """
    if _UI_SATURATION >= 100:
        return qss
    global _QSS_HEX_RE
    if _QSS_HEX_RE is None:
        import re
        _QSS_HEX_RE = re.compile(r'#[0-9a-fA-F]{6}\b')
    return _QSS_HEX_RE.sub(lambda m: _desat_hex_at(m.group(0), _UI_SATURATION), qss)


def _desat_hex_at(hex_color, sat):
    """Pure hex desaturation at an EXPLICIT saturation (0-100).

    Shared by desat_hex() (module state) and desaturated_theme_path() (rewrites
    a theme XML at a given sat without touching the global state).
    """
    if sat >= 100:
        return hex_color
    s = str(hex_color)
    if not s.startswith('#'):
        return hex_color
    body = s[1:]
    alpha = ''
    try:
        if len(body) == 3:
            r = int(body[0] * 2, 16); g = int(body[1] * 2, 16); b = int(body[2] * 2, 16)
        elif len(body) == 6:
            r = int(body[0:2], 16); g = int(body[2:4], 16); b = int(body[4:6], 16)
        elif len(body) == 8:
            alpha = body[0:2]
            r = int(body[2:4], 16); g = int(body[4:6], 16); b = int(body[6:8], 16)
        else:
            return hex_color
    except ValueError:
        return hex_color
    h, l, s_ = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    s_ *= (sat / 100.0)
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s_)
    R = max(0, min(255, int(round(nr * 255))))
    G = max(0, min(255, int(round(ng * 255))))
    B = max(0, min(255, int(round(nb * 255))))
    return f"#{alpha}{R:02x}{G:02x}{B:02x}"


def desaturated_theme_path(theme_file, sat=None, deep=None):
    """Return a path to a REWRITTEN copy of a qt-material theme XML (WI-2).

    Handles BOTH palette rewrites — desaturation (SPEC-SAT-001) and the opt-in
    near-black ground (deep dark) — because they must share one application
    point. Two separate generated files would race each other: whichever was
    handed to ``apply_stylesheet`` last would silently discard the other.

    qt-material's ``get_theme()`` accepts an absolute path that exists on disk
    (``else: theme = theme_name`` branch) and sets every color into the
    ``QTMATERIAL_*`` env vars FROM the XML. So if we hand ``apply_stylesheet``
    a desaturated copy, the stylesheet AND every ``get_theme_colors()`` call
    site inherit the muted palette for free — the single application point for
    all qt-material chrome (the double-desaturation invariant).

    - No-op: returns ``theme_file`` unchanged when sat >= 100, so 100% behaves
      exactly like today (built-in theme name passed straight through).
    - The generated filename PRESERVES the "light"/"dark" substring
      (``dark_blue.xml`` -> ``dark_blue_sat50.xml``) because qt-material's
      ``is_light_theme()`` checks ``"light" in QTMATERIAL_THEME`` and
      ``QTMATERIAL_THEME`` becomes the full path we pass.
    - On any failure (source XML not found, unwritable dir) returns
      ``theme_file`` unchanged so the app still themes, just saturated.

    ``theme_file`` is the logical built-in name (e.g. ``dark_blue.xml``); the
    caller keeps passing that to ``_save_theme_preference``. Only the
    ``apply_fn(theme=...)`` call uses this returned path.
    """
    import hashlib
    import re
    import tempfile
    if sat is None:
        sat = _UI_SATURATION
    if deep is None:
        deep = get_deep_dark()
    # Deep dark is a DARK-theme option; a light theme passes through untouched.
    deep = bool(deep) and _is_dark_theme_file(theme_file)
    try:
        from ui.theme_palette import DARK_ACCENT_INK, transformed_palette, theme_override
        palette_override = transformed_palette(theme_file, applied=True)
        has_palette_override = bool(theme_override(theme_file, applied=True)) or os.path.basename(str(theme_file)) in DARK_ACCENT_INK
    except Exception:
        palette_override = {}
        has_palette_override = False
    if sat >= 100 and not deep and not has_palette_override:
        return theme_file
    try:
        # Resolve the source XML: a built-in name lives under qt_material/themes,
        # otherwise theme_file may already be an on-disk path.
        if os.path.exists(theme_file):
            src = theme_file
        else:
            import qt_material
            src = os.path.join(os.path.dirname(qt_material.__file__), "themes", theme_file)
        if not os.path.exists(src):
            return theme_file

        from state.user_data import get_user_data_dir
        out_dir = os.path.join(str(get_user_data_dir() or "."), "desat_themes")
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.basename(theme_file)
        stem, ext = os.path.splitext(base)  # ("dark_blue", ".xml")
        # The generated name must still carry "dark"/"light" (qt-material reads
        # the substring off the path we hand it), and must differ per variant or
        # a stale file would be reused after the option changed.
        # The name carries a hash of the RESOLVED SOURCE path, not just the
        # basename: two different theme files with the same basename would
        # otherwise generate to the same output and quietly serve each other's
        # palette.
        src_tag = hashlib.sha1(os.path.abspath(src).encode("utf-8")).hexdigest()[:8]
        override_tag = hashlib.sha1(repr(sorted(palette_override.items())).encode("utf-8")).hexdigest()[:8]
        out_path = os.path.join(
            out_dir,
            f"{stem}_sat{int(sat)}{'_deep' if deep else ''}"
            f"_{src_tag}_{override_tag}{ext or '.xml'}")

        with open(src, "r", encoding="utf-8") as f:
            xml = f.read()
        if has_palette_override:
            for key, value in palette_override.items():
                xml = re.sub(
                    r'(<color\s+name="%s"\s*>)\s*(#[0-9a-fA-F]{3,8})\s*(</color>)'
                    % re.escape(key),
                    lambda m, replacement=value: m.group(1) + replacement + m.group(3),
                    xml)
        if sat < 100:
            # Rewrite every #RRGGBB (and #RGB) hex through the pure desaturator.
            hex_re = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
            xml = hex_re.sub(lambda m: _desat_hex_at(m.group(0), sat), xml)
        if deep:
            # By NAME, not by value: only the background family moves, so the
            # accent the user picked and the text colours are left alone.
            for key in _DEEP_DARK_KEYS:
                xml = re.sub(
                    r'(<color\s+name="%s"\s*>)\s*(#[0-9a-fA-F]{3,6})\s*(</color>)'
                    % re.escape(key),
                    lambda m: m.group(1) + _deepen_hex(m.group(2)) + m.group(3),
                    xml)
        # Written atomically, via a temp file in the SAME directory then
        # os.replace(). Truncating the shared output in place is a real hazard
        # here rather than a theoretical one: two app instances run against this
        # tree (full and --lite), and both applying the same variant could hand
        # qt-material a half-written XML.
        # mkstemp, not pid: a pid-suffixed name is unique per PROCESS but not
        # per CALL, so two threads in one process regenerating the same variant
        # shared a temp file and one lost the os.replace() race — a review probe
        # reproduced exactly that, one good path and one fallback. The
        # cross-process case (Lite + full, the real risk here) was already
        # covered; this closes the same-process one for the cost of one call.
        fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
        # mkstemp returns a RAW descriptor, and ownership of it passes to the
        # file object only once os.fdopen SUCCEEDS. So fdopen sits outside the
        # write block with its own handler: cleaning up the path without
        # closing the descriptor leaks an fd on every failure, which a theme
        # switch can repeat for as long as the app runs. BaseException, not
        # Exception — a MemoryError or a KeyboardInterrupt landing here leaks
        # exactly the same descriptor.
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        try:
            with handle as f:
                f.write(xml)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, out_path)
        except Exception:
            # Never leave the temp behind on a failed write.
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return out_path
    except Exception:
        return theme_file


def desat_image(qimage, fast=False):
    """Desaturate a QImage toward grayscale by the global UI saturation,
    ALPHA-SAFE. No-op fast path at sat == 100 (returns the input unchanged).

    Default (fast=False): per-pixel luma blend on Format_ARGB32 — for each pixel
    compute Rec.601 luma L = 0.299R + 0.587G + 0.114B and blend
    out = channel*f + L*(1-f) for R/G/B (f = sat/100); THE ALPHA BYTE IS LEFT
    UNTOUCHED. convertToFormat(Grayscale8) is WRONG here (it discards alpha ->
    icons become black squares) and the SourceAtop cross-fade was rejected by
    review (non-uniform desaturation on semi-transparent edge pixels -> visible
    color fringe). Use this for ICONS with anti-aliased transparent edges. Apply
    AFTER the ~48px .scaled(), never at source resolution (pure-Python walk is
    ~2.6ms at 48px but seconds at 2000px+).

    fast=True: a QPainter grayscale-over-original blend, done in C++ (~50ms at
    2000px vs seconds). Uses Qt's qGray luma (weights differ slightly from
    Rec.601 — visually negligible) and treats semi-transparent pixels uniformly,
    so it is ONLY safe for LARGE, FULLY-OPAQUE surfaces (the antikythera world
    map). Do NOT use for alpha-edged icons.
    """
    if qimage is None:
        return qimage
    sat = _UI_SATURATION
    if sat >= 100 or qimage.isNull():
        return qimage
    from PySide6.QtGui import QImage
    if fast:
        from PySide6.QtGui import QPainter
        base = qimage.convertToFormat(QImage.Format.Format_ARGB32)
        gray = base.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
            QImage.Format.Format_ARGB32)
        painter = QPainter(base)
        painter.setOpacity(1.0 - sat / 100.0)
        painter.drawImage(0, 0, gray)
        painter.end()
        return base
    # Format_RGBA8888 has a FIXED byte order (R,G,B,A) on every platform, so the
    # per-pixel walk is endianness-independent (Format_ARGB32's in-memory layout
    # is B,G,R,A only on little-endian). Codex review finding.
    img = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    f = sat / 100.0
    inv = 1.0 - f
    w = img.width()
    h = img.height()
    bpl = img.bytesPerLine()
    mv = img.bits()  # writable memoryview, format 'B'; RGBA8888 == R,G,B,A
    for y in range(h):
        row = y * bpl
        for x in range(w):
            o = row + x * 4
            rr = mv[o]; gg = mv[o + 1]; bb = mv[o + 2]
            luma = 0.299 * rr + 0.587 * gg + 0.114 * bb
            mv[o]     = int(rr * f + luma * inv + 0.5)
            mv[o + 1] = int(gg * f + luma * inv + 0.5)
            mv[o + 2] = int(bb * f + luma * inv + 0.5)
            # mv[o + 3] (alpha) intentionally untouched
    return img


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


def themed_chart_background():
    """The theme-locked chart background TEXTURE identifier: 'stone_01' for a
    light theme, 'stone_06' for a dark theme.

    SINGLE source of truth (td-iqjb.8 Wave H, pm-006) for every place that a
    theme-driven chart background is chosen: the main chart at boot
    (core_gui_qt:489) and on switch (:5281-5284), and every EMBEDDED chart-view
    host that must track the theme rather than a persisted user texture --
    dual_chart_widget (Transit + Solar Return), the Personal Eclipse mini-charts,
    and the Exploration south view. Using ONE helper at construction AND on
    refresh guarantees they cannot disagree (the boot-vs-switch drift that let a
    live-switch-only fix pass its gate while a light BOOT still rendered dark).

    Reads is_light_theme() (the live qt-material palette), which is valid at both
    call sites: the launcher applies the stylesheet before the GUI is built
    (core_gui_qt:6156) and _on_theme_changed re-applies it (:5193) before the
    background swap. The main chart's user-selectable background DIALOG flow is
    unaffected -- it calls set_background() with the user's pick directly."""
    return "stone_01" if is_light_theme() else "stone_06"


def get_theme_colors():
    """
    Get current qt-material theme colors from environment variables.

    IMPORTANT: This function is UNCHANGED from the original working version.
    It always reads env vars with frozen dark constants as fallbacks.
    Light/dark branching is done in the HELPER FUNCTIONS instead.

    Returns:
        dict: Theme colors with fallbacks if not using qt-material
    """
    # SPEC-SAT-001 WI-3: env-var values are ALREADY desaturated by WI-2 (the XML
    # was rewritten before apply_stylesheet), so they must NOT be desaturated
    # again here (double-desat trap). Only the FROZEN FALLBACK constants — used
    # when qt-material was never applied — need desat_hex(). _env_or_desat()
    # applies it to the fallback branch only. primary_dark is COMPUTED from the
    # (already-desaturated) primary, so it inherits the mute for free.
    primary = _env_or_desat("QTMATERIAL_PRIMARYCOLOR", BLUE)

    return {
        "primary": primary,
        "primary_dark": _darken_color(primary, 0.7),
        "primary_light": _env_or_desat("QTMATERIAL_PRIMARYLIGHTCOLOR", "#5EADFF"),
        "primary_text": _env_or_desat("QTMATERIAL_PRIMARYTEXTCOLOR", TEXT_PRIMARY),
        "secondary": _env_or_desat("QTMATERIAL_SECONDARYCOLOR", SURFACE),
        "secondary_dark": _env_or_desat("QTMATERIAL_SECONDARYDARKCOLOR", BG),
        "secondary_light": _env_or_desat("QTMATERIAL_SECONDARYLIGHTCOLOR", HOVER),
        "secondary_text": _env_or_desat("QTMATERIAL_SECONDARYTEXTCOLOR", TEXT_PRIMARY),
    }


def _env_or_desat(env_key, fallback):
    """Return the qt-material env var verbatim if set (WI-2 already desaturated
    it at the XML), else the frozen fallback constant run through desat_hex().
    Guarantees ONE application point per color (SPEC-SAT-001)."""
    v = os.environ.get(env_key)
    return v if v is not None else desat_hex(fallback)


def hex_to_rgb_str(hex_color):
    """Convert '#RRGGBB' (or '#RGB') to 'r, g, b' for use inside QSS rgba().

    Returns a mid-grey triple on malformed input so a bad color can never
    raise inside a stylesheet build.
    """
    h = str(hex_color).lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"
    except (ValueError, IndexError):
        return "128, 128, 128"


def dim_text(hex_color, alpha=0.70):
    """Return a QSS ``rgba(...)`` string that dims a live theme text color.

    The 8-key live palette (``get_theme_colors``) has only ONE foreground
    (``secondary_text``); it lacks the dim/tertiary tiers the frozen
    constants (TEXT_SECONDARY #AAAAAA, TEXT_TERTIARY #666666) provided.
    Applying alpha to the live foreground preserves that visual hierarchy on
    BOTH themes: 0.70 white on dark reads as light grey, 0.70 black on light
    reads as dark grey (SPEC-THM-001; td-iqjb F2 central dim policy).

    Use for QSS ``color:`` values. For painted QColor text, use
    ``QColor(color)`` then ``setAlphaF(alpha)`` instead.
    """
    return f"rgba({hex_to_rgb_str(hex_color)}, {alpha})"


# =============================================================================
# PARIVARTANA / FINAL-DISPOSITOR SEVERITY PALETTE  (td-vn65.2)
# -----------------------------------------------------------------------------
# Rule 20 SEMANTIC EXCEPTION: these colours ENCODE the strength of an exchange
# yoga (Maha grace -> double-Dainya affliction), not theme chrome. They are the
# exchange-panel analogue of the Varshaphala day/night severity map (_VRS_SEM):
# meaning is carried by hue, so the values are intentionally fixed rather than
# pulled from the 8-key live palette. The ramp is a continuous progression:
#   maha (GREEN, grace) -> khala (AMBER) -> dainya6 -> dainya8 -> dainya12 ->
#   dainya_double (ORANGE deepening into DARK RED, worsening affliction),
# plus a muted grey `neutral` for a chart with no exchange yoga.
#
# Each entry carries `hi` (bright accent: chip border, bar fill, heading),
# `lo` (a darker gradient stop) and `text` (a label colour that stays legible
# on the card surface — dark text for the light theme, bright text for dark).
# Resolved live via pari_sem(), NEVER cached at import: the active qt-material
# theme can change at runtime, so every call must re-read is_light_theme().
#
# H11 (pre-mortem hardening): this map and pari_sem() live ONLY here in ui/ and
# import NOTHING from pro/. info_panels.py loads the exchange widget
# unconditionally, so a pro/ dependency here would crash the public Core/lite
# build. Keep it self-contained.
# =============================================================================
_PARI_SEM = {
    "dark": {
        "maha":          dict(hi="#5FBF6A", lo="#2F7A38", text="#9FE0A6"),  # fresh green — grace
        "khala":         dict(hi="#E0B341", lo="#9A7A1E", text="#F2D488"),  # amber — mixed
        "dainya6":       dict(hi="#E8934A", lo="#A85E22", text="#F4BC8C"),  # orange
        "dainya8":       dict(hi="#DE6E3C", lo="#9E4520", text="#F0A585"),  # deep orange-red
        "dainya12":      dict(hi="#D14E3E", lo="#8F2E22", text="#EC9186"),  # red
        "dainya_double": dict(hi="#B23A34", lo="#7A211D", text="#E58079"),  # dark red — worst
        "neutral":       dict(hi="#8A8A90", lo="#55555A", text="#B8B8BE"),  # muted grey — no yoga
    },
    "light": {
        "maha":          dict(hi="#3E9E4A", lo="#2A6E33", text="#1F5E28"),
        "khala":         dict(hi="#B7891A", lo="#8A6410", text="#6E4E08"),
        "dainya6":       dict(hi="#C46E22", lo="#94500F", text="#7A3E0C"),
        "dainya8":       dict(hi="#BC5324", lo="#8A3A15", text="#742E0E"),
        "dainya12":      dict(hi="#B23A2E", lo="#832318", text="#6E2018"),
        "dainya_double": dict(hi="#962B26", lo="#6E1B18", text="#5E1713"),
        "neutral":       dict(hi="#6E6E74", lo="#4A4A50", text="#48484E"),
    },
}


def pari_sem(key):
    """Resolve one exchange-severity accent set for the *current* theme.

    ``key`` is one of ``maha``, ``khala``, ``dainya6``, ``dainya8``,
    ``dainya12``, ``dainya_double`` or ``neutral``. Returns a dict with
    ``hi`` / ``lo`` / ``text`` colours (see ``_PARI_SEM``). Re-reads
    ``is_light_theme()`` on every call so a live light<->dark theme switch
    picks up the correct set (never cached at import). Falls back to the
    ``neutral`` tier for an unknown key.
    """
    band = _PARI_SEM["light" if is_light_theme() else "dark"]
    entry = band.get(key, band["neutral"])
    # SPEC-SAT-001 WI-3: severity ramp never passes through qt-material, so
    # desaturate at the resolver. desat_hex is a no-op at 100 (identical values).
    return {k: desat_hex(v) for k, v in entry.items()}


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

    MUST NOT contain min-height/max-height rules — see apply_menu_bar_style,
    which is the only supported way to style the app menubar.

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


def apply_menu_bar_style(menubar):
    """Apply the menubar stylesheet AND the td-1a24 height pin to a QMenuBar.

    td-1a24: the unpinned qt-material menubar renders 2px shorter under one
    theme than the other, and a live theme switch does not recompute it, so the
    settings content area (window height - menubar) came out different sizes
    boot-vs-switch (the size_mismatch on all 8 settings pages + nav list).
    A theme-INDEPENDENT height derived from QApplication.font() gives ONE height
    for every theme; callers re-apply on both the theme path (_on_theme_changed)
    and the scale path (_apply_scale_refresh) so it stays consistent through
    both. The app font is NOT changed by Display-Scale (that factor only feeds
    scaled_area_*/scaled_px), so the derived height is effectively constant.

    THE PIN MUST BE A WIDGET-LEVEL MINIMUM ONLY — never QSS min/max-height and
    never setFixedHeight/setMaximumHeight. Constraining this menubar's maximum
    height in the full app makes it paint its BACKGROUND but none of its items
    (File/View/License/Help all had sane actionGeometry yet zero pixels were
    drawn — the menu bar looked removed from the app, 2026-09-01 regression).
    Verified empirically at any pin value, even taller than the item box; the
    QSS min/max pin also blanked headless (offscreen) while the setFixedHeight
    variant blanked only on the real display (xcb) — so a screen-true check is
    required for any future change here. A bare QMainWindow does NOT reproduce
    it; only the real ChartGUI/ProChartGUI does.

    A MINIMUM alone still achieves td-1a24: fm+16 sits at/above the natural
    qt-material heights of BOTH themes (~fm+14 vs ~fm+16 — the 2px mismatch),
    so every theme lands exactly on the floor and the heights converge, while
    the bar keeps the freedom to grow that Qt's item painting apparently
    requires. The td-1a24 oracle (test_menubar_height_pin.py) passes with this
    pin and it paints on both xcb and offscreen.
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontMetrics
    menubar.setStyleSheet(get_menu_bar_style())
    _app = QApplication.instance()
    # QApplication.instance() may return a bare QCoreApplication (headless, no
    # GUI) which has no font(); guard on the attribute, not just None.
    _fm_h = (QFontMetrics(_app.font()).height()
             if _app is not None and hasattr(_app, "font") else 17)
    menubar.setMinimumHeight(_fm_h + 16)


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


# =============================================================================
# ELEVATION AND DEPTH — SPEC-THM-002
# =============================================================================
#
# Depth, never hue. Every value below is MIXED FROM THE LIVE THEME TOKENS, so
# Rule 20 holds and a theme switch moves the whole ramp with it.
#
# THE TRAP THIS EXISTS TO AVOID (SPEC-THM-002 INV-1): the qt-material surface
# tokens do NOT keep a stable brightness order across polarities. `secondary`
# (lum 37.6) is DARKER than `secondary_dark` (53.3) on every dark theme and
# LIGHTER (245 vs 230) on every light one. So a ramp built by picking token
# NAMES makes cards rise in one theme and sink in the other. `secondary_light`
# is the only token that is the lightest in BOTH, which is why every level here
# is a mix from the page colour TOWARD secondary_light.
#
# The shipped get_panel_style()/get_frame_style() are NOT affected and must not
# be "simplified" into a single token expression: they are dual-path (frozen
# constants on dark, tokens on light) and each branch was tuned separately.

# SPEC-THM-002 D-1, answered 2026-07-27: the DEFAULT ramp. Level 0 is the page,
# 1 a container, 2 a card, 3 a popover. Spans 17.4 luminance points on dark and
# 12.0 on light — light themes simply have less headroom (INV-3), which is why
# they also get a cast shadow and dark themes get a top rim instead.
_ELEVATION_K = (0.00, 0.18, 0.34, 0.50)

# D-4: gridlines drop to 0.18 alpha on list-like tables, but matrices (Tajika
# 11x11, Avastha 13-row) keep a stronger grid because there the grid is doing
# real work — it is what lets the eye track a row across to a column.
DIVIDER_ALPHA_LIST = 0.18
DIVIDER_ALPHA_MATRIX = 0.35


def _clamp_level(level):
    try:
        level = int(level)
    except (TypeError, ValueError):
        return 0
    return max(0, min(3, level))


def _mix(color_a, color_b, t):
    """Linear RGB blend: t=0 returns color_a, t=1 returns color_b.

    Pure and unit-tested (SPEC-THM-002 T-1). Both endpoints are theme tokens, so
    a mix of two neutrals stays neutral — this is what keeps the ramp hue-free.
    """
    try:
        a = color_a.lstrip("#")
        b = color_b.lstrip("#")
        t = max(0.0, min(1.0, float(t)))
        out = []
        for i in (0, 2, 4):
            ca = int(a[i:i + 2], 16)
            cb = int(b[i:i + 2], 16)
            out.append(int(round(ca + (cb - ca) * t)))
        return "#{:02x}{:02x}{:02x}".format(*out)
    except (ValueError, IndexError, AttributeError):
        return color_a


def _alpha(hex_color, a):
    """``'rgba(r, g, b, a)'`` from a hex token.

    Supersedes the five private ``_rgba()`` copies scattered through the widget
    layer (parivartana, nabhasa, cards_of_truth, varshaphala, kuta).
    """
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, float(a))):.3f})"
    except (ValueError, IndexError, AttributeError):
        return hex_color


def elevation_color(level, base=None):
    """E1 — the surface colour for an elevation level (0 page .. 3 popover).

    Monotone lighter in BOTH polarities by construction: every level is a mix
    from the page colour toward ``secondary_light``, the only token that is the
    lightest in both (INV-2). No literal, no hue shift.
    """
    theme = get_theme_colors()
    base = base or theme["secondary_dark"]
    return _mix(base, theme["secondary_light"], _ELEVATION_K[_clamp_level(level)])


def elevation_rim(level, base=None):
    """E3 — ``(top_hex, side_hex)`` for the 1px rim that reads as a raised edge.

    A brighter top edge than sides is what makes a dark surface look lit from
    above; it is the whole depth cue on dark themes, where a cast shadow over a
    near-black page is invisible.
    """
    theme = get_theme_colors()
    surface = elevation_color(level, base)
    if is_light_theme():
        return (_mix(surface, theme["secondary_light"], 0.90),
                _mix(surface, theme["secondary_text"], 0.10))
    return (_mix(surface, theme["secondary_light"], 0.85),
            _mix(surface, theme["secondary"], 0.60))


def elevation_divider(alpha=None):
    """E6 — the hairline colour for gridlines and separators.

    Today's grid is the LIGHTEST token at full strength, which is the single
    loudest thing in these tables and most of the "blunt table" complaint. At
    low alpha it becomes structure instead of noise.
    """
    theme = get_theme_colors()
    ink = theme["secondary_text"] if is_light_theme() else theme["secondary_light"]
    return _alpha(ink, DIVIDER_ALPHA_LIST if alpha is None else alpha)


def elevation_shadow_spec(level):
    """E2 — ``(color, blur_px, dy_px)`` or ``None`` when no shadow applies.

    D-2: LIGHT THEMES ONLY. On dark themes the page is already near-black, so a
    shadow derived from it is invisible and costs a render pass for nothing —
    E1 + E3 carry the depth there instead.
    """
    level = _clamp_level(level)
    if level == 0 or not is_light_theme():
        return None
    theme = get_theme_colors()
    color = _alpha(theme["secondary_text"], (0.10, 0.16, 0.22)[level - 1])
    return (color, scaled_px((10, 18, 28)[level - 1]),
            scaled_px((2, 3, 5)[level - 1]))


def elevation_margin(level):
    """INV-9 — the margin a shadowed container needs so its blur is not clipped.

    Zero whenever ``elevation_shadow_spec`` is None, so a caller can reserve
    space unconditionally and get the right answer in both polarities.
    """
    spec = elevation_shadow_spec(level)
    if spec is None:
        return 0
    _color, blur, dy = spec
    return int(blur / 2) + dy + 1


def elevation_surface_style(selector, level, radius_px=None, hover=False):
    """E1 + E3 (+ E7 hover) for one container. THE call a panel author makes.

    ``selector`` is a full QSS selector (``"QFrame#pcard"``). Returns a complete
    stylesheet string; register it with ``_register_themed(widget, fn)`` so it
    replays on a theme switch rather than freezing at construction.
    """
    if radius_px is None:
        radius_px = scaled_px(10)
    bg = elevation_color(level)
    top, side = elevation_rim(level)
    css = (f"{selector} {{ background-color: {bg}; "
           f"border: 1px solid {side}; border-top: 1px solid {top}; "
           f"border-radius: {radius_px}px; }}")
    if hover:
        hb = elevation_color(min(3, _clamp_level(level) + 1))
        htop, hside = elevation_rim(min(3, _clamp_level(level) + 1))
        css += (f" {selector}:hover {{ background-color: {hb}; "
                f"border: 1px solid {hside}; border-top: 1px solid {htop}; "
                f"border-radius: {radius_px}px; }}")
    return css


def elevation_header_style(level=1):
    """E4 — a ``QHeaderView::section`` block: a vertical gradient plus a top rim.

    Makes a header read as a lid rather than a bold body row.

    TRAP: any ``::section`` state variant that sets a flat ``background-color``
    WINS over this gradient and makes it vanish on that state. Every state must
    restate its own gradient — the discipline get_3d_button_style already keeps.
    """
    theme = get_theme_colors()
    top_c = elevation_color(min(3, _clamp_level(level) + 1))
    bot_c = elevation_color(level)
    rim_top, rim_side = elevation_rim(level)
    return f"""
        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {top_c}, stop:1 {bot_c});
            color: {theme['secondary_text']};
            border: none;
            border-top: 1px solid {rim_top};
            border-bottom: 1px solid {rim_side};
            padding: 4px 6px;
            font-weight: bold;
        }}
        QTableCornerButton::section {{
            background: {bot_c};
            border: none;
            border-top: 1px solid {rim_top};
        }}
    """


def elevation_table_style(level=0, header_level=1, matrix=False, radius_px=0):
    """E4 + E6 + E7 for a table. Emits NO ``::item`` rule, deliberately.

    INV-5, measured: a QSS ``::item`` rule DEFEATS a delegate's own ``fillRect``,
    so an ``::item`` background here would silently erase every semantic colour
    on the avastha / tajika / karaka / strength tables. Cell-level depth is the
    delegate's job (``apps.delegates.cell_depth``), never a stylesheet's.

    ``matrix=True`` keeps a stronger gridline (D-4): on a 7x7 or 11x11 matrix the
    grid is what lets the eye track a row across to its column, so quieting it to
    list-table levels costs real legibility.
    """
    theme = get_theme_colors()
    bg = elevation_color(level)
    grid = elevation_divider(DIVIDER_ALPHA_MATRIX if matrix else DIVIDER_ALPHA_LIST)
    _top, side = elevation_rim(level)
    focus = _alpha(theme["primary"], 0.55)
    return f"""
        QTableWidget, QTableView {{
            background-color: {bg};
            alternate-background-color: {bg};
            gridline-color: {grid};
            border: 1px solid {side};
            border-radius: {radius_px}px;
            color: {theme['secondary_text']};
        }}
        QTableWidget:focus, QTableView:focus {{
            border: 1px solid {focus};
        }}
    """ + elevation_header_style(header_level)


def elevation_state_style(selector, level):
    """E7 for a non-table surface: hover lifts one level, focus draws a ring."""
    theme = get_theme_colors()
    up = elevation_color(min(3, _clamp_level(level) + 1))
    focus = _alpha(theme["primary"], 0.55)
    return (f"{selector}:hover {{ background-color: {up}; }} "
            f"{selector}:focus {{ border: 1px solid {focus}; }}")


def apply_elevation_shadow(widget, level):
    """E2 — apply a drop shadow, and return the margin it needs (0 if none).

    Returns 0 and applies nothing on dark themes or level 0 (D-2).

    Three hard constraints, all of them learned the hard way:
      * Rule 18 — Qt takes ownership at setGraphicsEffect, so the Python
        reference is dropped here or a later GC can segfault.
      * INV-8 — REFUSED over a QGraphicsView host. A drop shadow over a
        QGraphicsView child is a reproduced crash in this codebase
        (pro/parked/sign_variation_dialog/sign_variation_dialog.py:163 has six
        shadow blocks commented out for exactly this). Every chart view is off
        limits, permanently.
      * INV-9 — the blur is clipped unless the caller reserves the returned
        margin in its parent layout.
    """
    from PySide6.QtWidgets import QGraphicsView, QGraphicsDropShadowEffect
    from PySide6.QtGui import QColor

    if widget is None:
        return 0
    # INV-8: a QGraphicsView anywhere under this widget makes the shadow unsafe.
    if isinstance(widget, QGraphicsView) or widget.findChild(QGraphicsView) is not None:
        widget.setGraphicsEffect(None)
        return 0

    spec = elevation_shadow_spec(level)
    if spec is None:
        widget.setGraphicsEffect(None)   # clears a stale shadow after a switch
        return 0

    color_str, blur, dy = spec
    nums = color_str[color_str.find("(") + 1:color_str.find(")")].split(",")
    r, g, b = (int(float(n)) for n in nums[:3])
    a = float(nums[3]) if len(nums) > 3 else 1.0

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(QColor(r, g, b, int(a * 255)))
    widget.setGraphicsEffect(effect)
    del effect          # Rule 18: Qt owns it now.
    return elevation_margin(level)


# =============================================================================
# ACTION BAR v2 — COLOR TOKENS  (SPEC-BAR-001, M0-5)
# -----------------------------------------------------------------------------
# ONE color table for the whole chart action bar. Every surface the bar paints
# reads `bar_tokens()` at paint time; no hex literal may appear in the bar module
# (Rule 20 / SPEC-BAR-001 AC-4). Geometry does NOT live here — sizes, radii and
# hairline widths come from the controller's metrics table (INV-3).
#
# PROVENANCE. Each entry carries the CSS custom property it reproduces from the
# binding mockup `proprietary_docs/spec_design/action_bar_v2/vibrancy_segmented.html`
# (`:root[data-theme="dark"]` :17-78, `:root[data-theme="light"]` :80-138, plus the
# rule-level literals in the bar stylesheet :195-440). Full commentary: token sheet
# §2 (`05_opus_design_tokens.md`, T-111…T-166). The fidelity gate and the
# divergence register walk these comments — keep them exact.
#
# THEME POLARITY, and why the two branches are not symmetric:
#   * LIGHT — the mockup's light block IS qt-material `light_blue.xml` verbatim
#     (primary #2979ff, primary_text #3c3c3c, secondary #f5f5f5, secondary_light
#     #ffffff, secondary_dark #e6e6e6, secondary_text #555555). So the eight pure
#     keys are read LIVE from get_theme_colors() and the mockup is reproduced for
#     free (D-60: faithful to the derivations, not the literals).
#   * DARK — the mockup's dark block is this module's FROZEN constant set (BLUE,
#     ACCENTS, BACKGROUNDS, TEXT), NOT the app's shipped dark theme. The app boots
#     `dark_blue.xml` (primary #448aff, secondary #232629, secondary_dark #31363b,
#     secondary_text #ffffff) — reading it live would repaint the bar in a
#     different blue on a lighter ground, and would collapse the idle/hover label
#     hierarchy entirely (dark_blue's secondary_text == primary_text == #ffffff,
#     so every idle label would already be at its hover color). The dark branch
#     therefore resolves the eight keys from the frozen constants that the mockup
#     was drawn from. They still pass through desat_hex(), so the saturation
#     slider moves them (SPEC-SAT-001 — one application point, and these never
#     travel through the qt-material XML, so this is the correct side of the
#     double-desat trap).
#
# NOT COVERED: there is no disabled token, and none is needed. The mockup
# defines no disabled state; spec decision D-12 (SPEC-BAR-001 §5) defines it as
# a PATTERN over existing tokens — label and glyph at the dim_text 0.45-alpha
# treatment over the idle fill, hover/press/focus paint suppressed — so the
# disabled painter composes tokens from this table rather than reading a
# dedicated one. (Register row 07/D-13's "open DECIDE" predates spec D-12.)
# =============================================================================
from PySide6.QtGui import QColor  # noqa: E402  (section-local, paint-path type)


def gold_accent():
    """``(gold, gold_hi)`` hex pair for the current theme polarity.

    The bar's champagne-gold family: the title-well stripe gradient
    (`gold_hi` → `gold`), the lit zodiac segment's glyph and accent hairline, and
    the `+ TROPICAL` modifier's checked tint. Dark is the existing
    ``ACCENTS["gold"]`` pair (#DAA520 base / #FFD700 active) — the mockup was drawn
    from it. Light has no counterpart in this module yet, so its pair is declared
    here: #B8860B / #8A6508 (mockup :90).

    Note the deliberate inversion: in dark `gold_hi` is BRIGHTER than `gold`; in
    light it is DARKER. The roles are what carry over, not the luminance direction
    — reusing #FFD700 on a #f5f5f5 ground makes every gold accent illegible
    (register D-59).

    Both branches pass through ``desat_hex`` — these hexes never travel through the
    qt-material XML, so this is their single desaturation point (SPEC-SAT-001).
    """
    if is_light_theme():
        return desat_hex("#B8860B"), desat_hex("#8A6508")   # --gold / --gold-hi light
    return (desat_hex(ACCENTS["gold"]["base"]),             # --gold      dark #DAA520
            desat_hex(ACCENTS["gold"]["active"]))           # --gold-hi   dark #FFD700


# --- private color arithmetic (CSS semantics, exact) -------------------------

def _bar_over(white, alpha):
    """A pure white or pure black overlay at a CSS alpha — the whole derived
    surface layer of this design is one of these two (register D-60)."""
    c = QColor(255, 255, 255) if white else QColor(0, 0, 0)
    c.setAlphaF(float(alpha))
    return c


def _bar_rgba(r, g, b, alpha=1.0):
    """A literal ``rgba()`` from the mockup that is not derivable from the eight
    keys (the two bar-gradient stops and the thumb wafer)."""
    c = QColor(int(r), int(g), int(b))
    c.setAlphaF(float(alpha))
    return c


def _bar_tint(hex_color, alpha=1.0):
    """A THEMED hex at a CSS alpha — i.e. ``color-mix(in srgb, X n%, transparent)``,
    which in sRGB is exactly X carrying n% alpha. Degrades to mid-grey rather than
    raising: this runs inside paintEvent."""
    c = QColor(hex_color)
    if not c.isValid():
        c = QColor(128, 128, 128)
    c.setAlphaF(float(alpha))
    return c


# The eight pure keys as the mockup froze them for DARK (see the polarity note
# above). Every value is an existing module constant except --primary_light, which
# has no counterpart here (get_theme_colors()'s frozen fallback is #5EADFF).
_BAR_PURE_DARK = {
    "primary":         BLUE,                        # --primary        dark  :18
    "primary_dark":    ACCENTS["blue"]["active"],   # --primary_dark   dark  :19
    "primary_light":   "#4DA2FF",                   # --primary_light  dark  :20
    "primary_text":    TEXT_PRIMARY,                # --primary_text   dark  :21
    "secondary":       SURFACE,                     # --secondary      dark  :22
    "secondary_dark":  BG,                          # --secondary_dark dark  :23
    "secondary_light": HOVER,                       # --secondary_light dark :24
    "secondary_text":  TEXT_SECONDARY,              # --secondary_text dark  :25
}

# Semantic accents — the second, non-8-key layer the design adds. Rule 20's
# semantic exemption covers green/red (state meaning, not chrome); gold is routed
# through gold_accent() instead of being repeated here.
_BAR_ACCENT_DARK = {
    "green":     ACCENTS["green"]["base"],          # --green      dark  :29
    "green_hi":  "#7CD182",                         # --green-hi   dark  :29
    "red":       STATUS["error"],                   # --red        dark  :30
    "red_press": "#D0281F",                         # --red-press  dark  :30
    "muted":     TEXT_TERTIARY,                     # --muted      dark  :31
}
_BAR_ACCENT_LIGHT = {
    "green":     "#2E7D32",                         # --green      light :91
    "green_hi":  "#1B5E20",                         # --green-hi   light :91
    "red":       "#D70015",                         # --red        light :92
    "red_press": "#A5000F",                         # --red-press  light :92
    "muted":     "#8A8A8E",                         # --muted      light :93
}

_BAR_TOKEN_CACHE = None      # (signature, dict) — rebuilt whenever the palette moves


def _bar_signature():
    """Everything bar_tokens() reads. Cheap to compute, so the cache can never
    serve a stale palette after a theme switch, a saturation change or a
    deep-dark toggle."""
    return (bool(is_light_theme()), get_ui_saturation(), get_deep_dark(),
            tuple(sorted(get_theme_colors().items())))


def _build_bar_tokens():
    """Resolve the whole bar palette for the current theme. See bar_tokens()."""
    light = bool(is_light_theme())
    gold, gold_hi = gold_accent()

    if light:
        # light_blue.xml == the mockup's light block, so the live palette IS the
        # design (D-60). Read it through the eight REAL keys, nothing else exists.
        t = get_theme_colors()
        pure = {k: t[k] for k in _BAR_PURE_DARK}
        acc = {k: desat_hex(v) for k, v in _BAR_ACCENT_LIGHT.items()}
    else:
        pure = {**{k: desat_hex(v) for k, v in _BAR_PURE_DARK.items()}, "primary_text": get_theme_colors()["primary_text"]}
        acc = {k: desat_hex(v) for k, v in _BAR_ACCENT_DARK.items()}

    green = acc["green"]
    red = acc["red"]
    primary = pure["primary"]
    secondary = pure["secondary"]

    tok = {}

    # --- 1. the eight pure keys (mirror get_theme_colors()) ------------------
    for k, v in pure.items():
        tok[k] = QColor(v)                          # --primary … --secondary_text

    # --- 2. semantic accents -------------------------------------------------
    tok["gold"] = QColor(gold)                      # --gold        :28 / :90
    tok["gold_hi"] = QColor(gold_hi)                # --gold-hi     :28 / :90
    tok["green"] = QColor(green)                    # --green       :29 / :91
    tok["green_hi"] = QColor(acc["green_hi"])       # --green-hi    :29 / :91
    tok["red"] = QColor(red)                        # --red         :30 / :92
    tok["red_press"] = QColor(acc["red_press"])     # --red-press   :30 / :92
    tok["muted"] = QColor(acc["muted"])             # --muted       :31 / :93

    # --- 3. the vibrancy stack (bar surface) ---------------------------------
    # The two gradient stops are the only surface literals: dark bar-a is
    # secondary_light with +2 blue, bar-b is secondary with -2 on every channel —
    # near the palette but not derivable from it (token sheet T-126/T-127).
    # The bar OWNS its backdrop (integration decision at CP-1): nothing renders
    # behind the bar in the app (report 02 §1), the goldens composite the
    # translucent gradient over a flat --canvas-core field, and leaving the
    # backdrop to whatever palette the parent window has washed every surface
    # ~dE 9-17 at the gate. Opaque base under bar_a/bar_b = token sheet T-319's
    # flatten, kept as a separate token so the T-317 live-blur upgrade can
    # replace the base without touching the gradient.
    tok["canvas_core"] = (QColor(desat_hex("#FBFBFD")) if light  # --canvas-core :128
                          else QColor(desat_hex("#0B0B0D")))     # --canvas-core :67
    tok["bar_a"] = (_bar_rgba(253, 253, 254, .86) if light      # --bar-a  :97
                    else _bar_rgba(58, 58, 62, .78))            # --bar-a  :36
    tok["bar_b"] = (_bar_rgba(234, 234, 238, .88) if light      # --bar-b  :98
                    else _bar_rgba(26, 26, 29, .80))            # --bar-b  :37
    tok["bar_gloss"] = _bar_over(True, .95 if light else .10)   # --bar-gloss :99 / :38
    tok["bar_under"] = _bar_over(False, .16 if light else .85)  # --bar-under :100 / :39
    tok["bar_lip"] = _bar_over(True, .55 if light else .045)    # --bar-lip   :101 / :40
    tok["bar_drop"] = _bar_over(False, .55)                     # #bar shadow 4 :208 (both themes)

    # --- 4. control surfaces --------------------------------------------------
    tok["ctl"] = _bar_over(True, .90 if light else .055)        # --ctl      :103 / :42
    tok["ctl_h"] = _bar_over(True, 1.0 if light else .105)      # --ctl-h    :104 / :43
    tok["ctl_a"] = (_bar_over(False, .075) if light             # --ctl-a    :105
                    else _bar_over(True, .15))                  # --ctl-a    :44  (polarity flips)
    tok["ctl_on"] = (_bar_over(False, .075) if light            # --ctl-on   :106
                     else _bar_over(True, .155))                # --ctl-on   :45
    tok["ctl_on_h"] = (_bar_over(False, .105) if light          # --ctl-on-h :107
                       else _bar_over(True, .20))               # --ctl-on-h :46
    # --thumb is a 180deg gradient; split into its two stops (:108 / :47).
    tok["thumb_top"] = (_bar_rgba(255, 255, 255) if light
                        else _bar_over(True, .21))
    tok["thumb_bottom"] = (_bar_rgba(250, 250, 251) if light
                           else _bar_over(True, .145))
    tok["hair"] = _bar_over(not light, .17 if light else .13)        # --hair      :110 / :49
    tok["hair_soft"] = _bar_over(not light, .085 if light else .075)  # --hair-soft :111 / :50
    tok["gloss"] = _bar_over(True, .85 if light else .09)            # --gloss     :112 / :51
    tok["drop"] = _bar_over(False, .18 if light else .50)            # --drop      :113 / :52
    tok["well"] = _bar_over(False, .055 if light else .30)           # --well      :114 / :53
    tok["zodtray"] = _bar_over(False, .085 if light else .36)        # --zodtray   :115 / :54
    tok["well_h"] = _bar_over(False, .035 if light else .22)         # --well-h    :116 / :55
    tok["well_line"] = (_bar_over(False, .14) if light               # --well-line :117
                        else _bar_over(True, .10))                   # --well-line :56

    # --- 5. recess inner shadows (hard-coded, identical in both themes) -------
    tok["recess"] = _bar_over(False, .28)        # .zodunit / .title inset :332, :386
    tok["recess_hover"] = _bar_over(False, .22)  # .title:hover inset      :389

    # --- 6. checked identities (tints) ---------------------------------------
    tok["tint_blue"] = (QColor(primary) if light                # --tint-blue    :119 (opaque)
                        else _bar_tint(primary, .90))           # --tint-blue    :58
    tok["tint_blue_fg"] = QColor(pure["primary_text"])         # --tint-blue-fg :120 / :59
    tok["tint_green"] = _bar_tint(green, .14 if light else .22)  # --tint-green   :121 / :60
    tok["tint_green_fg"] = QColor(acc["green_hi"])              # --tint-green-fg :122 / :61
    tok["tint_gold"] = _bar_tint(gold, .16 if light else .22)   # --tint-gold    :123 / :62
    # light is NOT gold_hi — a bespoke value one step lighter than #8A6508.
    tok["tint_gold_fg"] = (QColor(desat_hex("#7A5A08")) if light  # --tint-gold-fg :124
                           else QColor(gold_hi))                 # --tint-gold-fg :63

    # --- 7. rule-level derived colors (color-mix precomputed) -----------------
    tok["ring"] = _bar_tint(primary, .55)              # --ring                  :126 / :65
    tok["fg_on_accent"] = QColor(255, 255, 255)        # literal #fff on accent  :415, :434
    tok["acc_blue"] = _bar_over(True, .62)             # .tint-blue.on .acc      :291
    tok["tint_green_h"] = _bar_tint(green, .30)        # .tint-green.on:hover    :293
    tok["acc_green_glow"] = _bar_tint(green, .60)      # .tint-green.on .acc glow :294
    tok["tint_gold_h"] = _bar_tint(gold, .32)          # .tint-gold.on:hover     :296
    tok["acc_gold_glow"] = _bar_tint(gold, .60)        # .tint-gold.on .acc glow :297
    tok["primary_action"] = QColor(                    # .btn.primary label      :301
        _mix(primary, pure["primary_text"], 0.55))     # = color-mix(primary 45%, primary_text)
    tok["live_glow"] = _bar_tint(green, .85)           # .btn .live glow         :309
    tok["thumb_acc_glow"] = _bar_tint(gold, .55)       # .zod > .btn.on .acc glow :347
    tok["mod_rim_on"] = _bar_tint(gold, .55)           # .btn.mod.on inner rim   :368
    tok["mod_rim_on_outer"] = _bar_tint(gold, .22)     # .btn.mod.on outer rim   :369
    tok["stripe_glow"] = _bar_tint(gold, .45)          # .title .stripe glow     :393
    tok["close_rim_h"] = _bar_tint(red, .60)           # .xbtn:hover rim         :415
    tok["menu_fill"] = _bar_tint(secondary, .88)       # .menu background        :425
    tok["menu_drop"] = _bar_over(False, .60)           # .menu drop shadow       :427

    return tok


def bar_tokens():
    """The chart action bar's complete color table for the CURRENT theme.

    Returns a ``dict[str, QColor]`` — 60 keys, the same key set in both themes,
    named after the mockup's CSS custom properties (``--hair-soft`` → ``hair_soft``)
    so a token can be traced to the design in one grep. Alpha is carried ON the
    QColor (the painter composites it directly); every alpha is the mockup's
    authored value, not Chromium's 8-bit re-serialisation.

    Read it at PAINT TIME, never cached in a widget: construction and refresh then
    share one code path, so a theme switch, a saturation change or a deep-dark
    toggle repaints correctly with no per-widget invalidation (SPEC-BAR-001 INV-4,
    the ThemedStyleMixin principle applied to painted widgets). The call is cheap —
    the table is memoized here against a palette signature and rebuilt only when
    that signature moves.

    Geometry is NOT here. Sizes, radii, paddings and hairline widths come from the
    controller's metrics table (INV-3, single sizing truth); this function is the
    single COLOR truth (INV-4 / Rule 20 / AC-4: no hex in the bar module).

    The QColor values are shared between callers — copy before mutating.
    """
    global _BAR_TOKEN_CACHE
    sig = _bar_signature()
    if _BAR_TOKEN_CACHE is None or _BAR_TOKEN_CACHE[0] != sig:
        _BAR_TOKEN_CACHE = (sig, _build_bar_tokens())
    return dict(_BAR_TOKEN_CACHE[1])


# ===========================================================================
# Human Design BodyGraph palette (SPEC-HD-001)
# ===========================================================================
#
# THE ONE APPROVED RULE 20 EXCEPTION, and it is narrow. Human Design's nine
# centres carry FIXED colours that identify them the way a planet's glyph
# identifies a planet: a reader recognises the Sacral because it is red, and a
# Throat tinted with the app's accent would simply be a different diagram. The
# two activation colours are semantic in the same way -- one side is Design, the
# other Personality, everywhere they appear.
#
# So those hues do not come from get_theme_colors(). They are declared ONCE
# here, as light and dark tokens, and never as literals in painter code. Board,
# chrome, text and every other surface still come from the theme like the rest
# of the app.
#
# PROVENANCE. The four centre hues were sampled pixel by pixel from the
# reference charts (ref_single_mybodygraph.png dark, ref_full_curvy_mybodygraph
# .png light), not invented and not a designer's spectrum:
#
#     yellow  Head, G          green  Ajna
#     brown   Throat, Spleen, Solar Plexus, Root
#     red     Will, Sacral
#
# The "lift" twins are for outlines, halos and auras, because brown and green do
# not read against a dark ground at hairline widths. The "mid" twins are for the
# hover breath: a centre lifts a little from inside rather than being spotlit.
# The identity always stays the base hue.
#
# ACTIVATION COLOURS (Lorris, 2026-08-28): Design is the WARM side and
# Personality the cool one, because a printed Jovian chart puts Design in red.
# One colour per side, everywhere -- graph, gate pads, both planet columns,
# toolbar dots, legend.

#: Centre fills and their outline / hover twins. Dark theme.
_HD_DARK = {
    "yellow": "#FBF7AD", "green": "#669A8D", "brown": "#58423E", "red": "#D04A4A",
    "yellow_lift": "#FFFCC9", "green_lift": "#8FC7B8",
    "brown_lift": "#B48A78", "red_lift": "#EE7C77",
    "yellow_mid": "#FCF9BB", "green_mid": "#6EA396",
    "brown_mid": "#634B45", "red_mid": "#D75552",
    # an undefined centre: near white, with a clear outline
    "open_fill": "rgba(240,244,252,.085)",
    "open_fill_hover": "rgba(240,244,252,.24)",
    "open_edge": "#E6EBF5",
    # activation
    "personality": "#2FD9E8", "design": "#FFB13D",
    "personality_casing": "#1E94A0", "design_casing": "#C07D21",
    "casing_off": "#A79FAE", "core_off": "#141020",
    # channel rendering
    "dead_trace": "#3F5750",     # an unactivated trace, thin copper
    "plate": "#0D0B16",          # fill behind a via or a gate pad
    "disc": "#100D0C",           # the disc under an activated numeral
    "disc_ink": "#FBFCFF",
    # the travelling pulse
    "pulse_personality": "#D9FBFF", "pulse_design": "#FFF0D2", "pulse_both": "#FFFFFF",
    # board and chrome
    "bg0": "#05040A", "bg1": "#0D0B16", "bg2": "#15111D",
    "ink": "#F2EEE6", "ink2": "#B6ADBF", "ink3": "#7C7488",
    "warn": "#FFC46B",
    # An UNLIT numeral sits straight on the centre fill, so its ink follows that fill
    # rather than the theme: dark on the two yellow centres, light on green, brown and
    # red, theme ink on an open one. Each is drawn over a halo of the opposite value so
    # it survives a trace or a via passing underneath. These three pairs are the same in
    # both themes -- they are keyed to the CENTRE's colour, which does not flip.
    "gate_ink_yellow": "#4A3F14", "gate_halo_yellow": "rgba(251,247,173,.92)",
    "gate_ink_solid": "#F7F9FF", "gate_halo_solid": "rgba(16,11,10,.55)",
    "halo": "rgba(6,5,11,.93)",
}

#: The same tokens for the light theme. The reference's light print uses the
#: same four hues a shade cooler; the lifts DARKEN instead of lightening,
#: because on a white ground a lifted yellow disappears.
_HD_LIGHT = {
    "yellow": "#F8F4B2", "green": "#72A195", "brown": "#64514E", "red": "#D14B49",
    "yellow_lift": "#E8D24A", "green_lift": "#4E7E71",
    "brown_lift": "#4A3733", "red_lift": "#B03A38",
    "yellow_mid": "#F6EFA5", "green_mid": "#6D9B8F",
    "brown_mid": "#604C49", "red_mid": "#CC4745",
    "open_fill": "#FFFFFF",
    "open_fill_hover": "#FFFFFF",
    "open_edge": "#B7BDC9",
    "personality": "#00808F", "design": "#C56B00",
    "personality_casing": "#005B66", "design_casing": "#8A4B00",
    "casing_off": "#B7BCC9", "core_off": "#FFFFFF",
    "dead_trace": "#9AA79D",
    "plate": "#F6F4F0",
    "disc": "#221E1D",
    "disc_ink": "#FBFCFF",
    "pulse_personality": "#004B56", "pulse_design": "#7A3D00", "pulse_both": "#2B2B2B",
    "bg0": "#E9E7E2", "bg1": "#F6F4F0", "bg2": "#FFFFFF",
    "ink": "#241D1B", "ink2": "#5C5350", "ink3": "#8D8582",
    "warn": "#A86A00",
    "gate_ink_yellow": "#4A3F14", "gate_halo_yellow": "rgba(251,247,173,.92)",
    "gate_ink_solid": "#F7F9FF", "gate_halo_solid": "rgba(16,11,10,.55)",
    "halo": "rgba(255,255,255,.95)",
}

#: Which of the four hues each centre wears. Not a style choice -- this is how
#: Human Design charts are printed, and a reader identifies a centre by it.
HD_CENTER_HUE = {
    "head": "yellow", "ajna": "green", "throat": "brown", "g": "yellow",
    "will": "red", "spleen": "brown", "solar": "brown", "sacral": "red",
    "root": "brown",
}

#: Which ink an unlit numeral takes, by the hue of the centre it sits on.
HD_GATE_INK_KIND = {hue: ("yellow" if hue == "yellow" else "solid")
                    for hue in ("yellow", "green", "brown", "red")}

#: Stroke widths, in canvas units. Geometry, so they do not vary with the theme.
HD_STROKE = {
    "dead": 2.4,        # an unactivated trace
    "core": 3.2,        # a defined half
    "glow": 8.0,        # the blurred twin behind a core, drawn as a wide pen
    "pulse": 1.6,       # the travelling dash
    "outline": 1.2,     # a centre's edge
}

_HD_TOKEN_CACHE = None      # (signature, dict) — rebuilt whenever the palette moves


def _hd_signature():
    """Everything hd_palette() reads, so the cache cannot serve a stale theme."""
    return (bool(is_light_theme()), get_ui_saturation(), get_deep_dark())


def hd_palette():
    """The Human Design semantic palette for the current theme.

    Returns a flat ``{token: value}`` dict -- the tokens above, plus a resolved
    ``center_fill`` / ``center_edge`` / ``center_hover`` entry per centre, and
    ``glow_alpha`` for how strongly a lit trace blooms.

    Read it AT PAINT TIME, never cached in a widget: construction and refresh
    then share one code path, so a theme switch or a saturation change repaints
    correctly with no per-widget invalidation. The call is cheap -- memoized
    against the palette signature and rebuilt only when that moves.

    Values are hex strings (or ``rgba(...)`` for the two translucent fills), to
    be handed to QColor by the caller; the module deliberately does not import
    Qt colour types so it stays usable from a headless test.
    """
    global _HD_TOKEN_CACHE
    sig = _hd_signature()
    if _HD_TOKEN_CACHE is None or _HD_TOKEN_CACHE[0] != sig:
        light = bool(is_light_theme())
        base = dict(_HD_LIGHT if light else _HD_DARK)

        # SPEC-SAT-001: these are authored constants, never read back from
        # qt-material env vars, so they are desaturated here exactly once.
        tokens = {k: (v if v.startswith("rgba") else desat_hex(v))
                  for k, v in base.items()}

        for centre, hue in HD_CENTER_HUE.items():
            tokens[f"fill_{centre}"] = tokens[hue]
            tokens[f"edge_{centre}"] = tokens[f"{hue}_lift"]
            tokens[f"hover_{centre}"] = tokens[f"{hue}_mid"]

        # A lit trace blooms less on a light ground: the same alpha that reads as
        # a glow on near black reads as a smudge on near white.
        tokens["glow_alpha"] = 0.34 if light else 0.62
        tokens["is_light"] = light

        _HD_TOKEN_CACHE = (sig, tokens)
    return dict(_HD_TOKEN_CACHE[1])
