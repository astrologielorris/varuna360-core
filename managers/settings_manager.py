# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Unified Settings Manager for Astrology Chart Application.

Centralizes all application settings into a single file (app_settings.json),
with typed access methods and automatic migration from legacy config files.

Architecture:
- Settings stored in app_settings.json (JSON format)
- API keys stored separately in .env (security)
- Profile-specific settings remain in profiles/*/profile.json
- Session state remains in profiles/*/session.json
"""

import copy
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path

try:
    from utils.debug import debug_print
except ImportError:
    debug_print = print  # Fallback for standalone testing

# Project root is one level up: managers/ -> chart_calculation/
_MANAGERS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_MANAGERS_DIR)

# Default South Indian chart display settings.
#
# Synced from the author's working configuration so a fresh install
# shows the full styled appearance (sign badges with frames + gradients,
# element shadows, planet glow shadows, ascendant/house-5/house-9
# effects, framed house numbers, sized planets) instead of a barebones
# wireframe. Users can still customize everything via the Settings tab;
# these are the starting point, not a lock.
DEFAULT_CHART_DISPLAY = {   'shadow': {   'enabled': True,
                  'blur_radius': 15,
                  'offset_x': 4,
                  'offset_y': 4,
                  'color': '#ffffff',
                  'opacity': 97},
    'sign_label': {   'offset_x': 53,
                      'offset_y': 54,
                      'font_family': 'Cambria',
                      'font_size': 40,
                      'font_weight': 'normal',
                      'outline_enabled': True,
                      'outline_color': '#DE3163',
                      'outline_width': 1,
                      'frame_enabled': True,
                      'frame_color': '#DE3163',
                      'frame_width': 10,
                      'frame_padding': 9,
                      'frame_radius': 20,
                      'background_enabled': True,
                      'background_color': '#4682B4',
                      'background_opacity': 180,
                      'background_padding': 4,
                      'background_radius': 0,
                      'frame_gradient': {   'colors': ['#4A4A4A', '#2D2D2D', '#1A1A1A'],
                                            'name': 'Carbon Fiber',
                                            'type': 'linear_v'}},
    'sign_icon': {'offset_x': 20, 'offset_y': 20},
    'planets': {'vertical_position': 57, 'horizontal_padding': 39},
    'planet_text': {'abbrev_offset_y': -1, 'degrees_offset_y': 23},
    'planet_abbrev_style': {   'font_family': 'default',
                               'font_size': 18,
                               'font_weight': 'bold',
                               'outline_enabled': False,
                               'outline_color': '#000000',
                               'outline_width': 2,
                               'frame_enabled': False,
                               'frame_color': '#FFD700',
                               'frame_width': 2,
                               'frame_padding': 4,
                               'frame_radius': 0,
                               'background_enabled': False,
                               'background_color': '#000000',
                               'background_opacity': 180,
                               'background_padding': 4,
                               'background_radius': 0,
                               'frame_gradient': None},
    'planet_degrees_style': {   'font_family': 'default',
                                'font_size': 16,
                                'font_weight': 'normal',
                                'outline_enabled': False,
                                'outline_color': '#50C878',
                                'outline_width': 2,
                                'frame_enabled': False,
                                'frame_color': '#FFFFFF',
                                'frame_width': 2,
                                'frame_padding': 4,
                                'frame_radius': 0,
                                'background_enabled': True,
                                'background_color': '#FFFFFF',
                                'background_opacity': 82,
                                'background_padding': 1,
                                'background_radius': 10,
                                'frame_gradient': None},
    'lagna_strip': {'offset_x': 6, 'offset_y': 23},
    'ascendant_degree': {   'enabled': True,
                            'font_size': 26,
                            'font_weight': 'normal',
                            'color_mode': 'custom',
                            'custom_color': '#FFFFFF',
                            'offset_x': 25,
                            'offset_y': 5},
    'house_number': {   'enabled': True,
                        'offset_x': 8,
                        'offset_y': 38,
                        'font_family': 'default',
                        'font_size': 16,
                        'font_weight': 'normal',
                        'outline_enabled': False,
                        'outline_color': '#000000',
                        'outline_width': 2,
                        'frame_enabled': True,
                        'frame_color': '#FFD700',
                        'frame_width': 3,
                        'frame_padding': 4,
                        'frame_radius': 0,
                        'background_enabled': False,
                        'background_color': '#000000',
                        'background_opacity': 180,
                        'background_padding': 4,
                        'background_radius': 0,
                        'frame_gradient': None},
    'house_cusps': {   'enabled': True,
                       'offset_x': 67,
                       'offset_y': 46,
                       'font_family': 'Helvetica',
                       'font_size': 23,
                       'font_weight': 'normal',
                       'outline_enabled': False,
                       'outline_color': '#ffff00',
                       'outline_width': 2,
                       'frame_enabled': False,
                       'frame_color': '#DAA520',
                       'frame_width': 2,
                       'frame_padding': 4,
                       'frame_radius': 0,
                       'background_enabled': False,
                       'background_color': '#000000',
                       'background_opacity': 180,
                       'background_padding': 4,
                       'background_radius': 0,
                       'frame_gradient': None},
    'planet_sizes': {   'Sun': 213,
                        'Moon': 214,
                        'Mars': 160,
                        'Mercury': 173,
                        'Jupiter': 160,
                        'Venus': 136,
                        'Saturn': 162,
                        'Rahu': 136,
                        'Ketu': 126,
                        'Uranus': 187,
                        'Neptune': 157,
                        'Pluto': 173},
    'text_colors': {   'planet_abbrev': '#EEEEEE',
                       'planet_degrees': '#000000',
                       'sign_label': '#000000'},
    'text_shadow': {   'enabled': True,
                       'blur_radius': 1,
                       'offset_x': 0,
                       'offset_y': -3,
                       'color': '#000000',
                       'opacity': 255},
    'element_shadows': {   'enabled': True,
                           'blur_radius': 4,
                           'offset_x': 2,
                           'offset_y': 1,
                           'opacity': 205,
                           'fire': '#ff4444',
                           'earth': '#dc6d1e',
                           'air': '#9fff05',
                           'water': '#4444FF'},
    'planet_text_offsets': {   'Sun': 0,
                               'Moon': -11,
                               'Mars': 0,
                               'Mercury': 4,
                               'Jupiter': 0,
                               'Venus': 30,
                               'Saturn': 0,
                               'Rahu': 0,
                               'Ketu': 14,
                               'Uranus': -15,
                               'Neptune': -1,
                               'Pluto': 0},
    'ascendant_effect': {   'enabled': True,
                            'effect_type': 'Element Glow',
                            'opacity': 54,
                            'spread': 34,
                            'size': 93,
                            'offset_x': 11,
                            'offset_y': 9},
    'house_5_effect': {   'enabled': True,
                          'effect_type': 'Element Glow',
                          'opacity': 35,
                          'spread': 20,
                          'size': 87,
                          'offset_x': -2,
                          'offset_y': -4},
    'house_9_effect': {   'enabled': True,
                          'effect_type': 'Element Glow',
                          'opacity': 30,
                          'spread': 30,
                          'size': 90,
                          'offset_x': 1,
                          'offset_y': -6},
    'planet_shadows': {   'enabled': True,
                          'Sun': {   'enabled': True,
                                     'blur_radius': 15,
                                     'offset_x': 4,
                                     'offset_y': 4,
                                     'opacity': 97,
                                     'color': '#ffff00'},
                          'Moon': {   'enabled': True,
                                      'blur_radius': 15,
                                      'offset_x': 4,
                                      'offset_y': 4,
                                      'opacity': 97,
                                      'color': '#ffaaff'},
                          'Mars': {   'enabled': True,
                                      'blur_radius': 15,
                                      'offset_x': 4,
                                      'offset_y': 4,
                                      'opacity': 97,
                                      'color': '#ff0000'},
                          'Mercury': {   'enabled': True,
                                         'blur_radius': 15,
                                         'offset_x': 4,
                                         'offset_y': 4,
                                         'opacity': 97,
                                         'color': '#aa5500'},
                          'Jupiter': {   'enabled': True,
                                         'blur_radius': 15,
                                         'offset_x': 4,
                                         'offset_y': 4,
                                         'opacity': 97,
                                         'color': '#aa00ff'},
                          'Venus': {   'enabled': True,
                                       'blur_radius': 15,
                                       'offset_x': 4,
                                       'offset_y': 4,
                                       'opacity': 97,
                                       'color': '#0055ff'},
                          'Saturn': {   'enabled': True,
                                        'blur_radius': 15,
                                        'offset_x': 4,
                                        'offset_y': 4,
                                        'opacity': 97,
                                        'color': '#00ff00'},
                          'Rahu': {   'enabled': True,
                                      'blur_radius': 15,
                                      'offset_x': 4,
                                      'offset_y': 4,
                                      'opacity': 97,
                                      'color': '#000000'},
                          'Ketu': {   'enabled': True,
                                      'blur_radius': 15,
                                      'offset_x': 4,
                                      'offset_y': 4,
                                      'opacity': 97,
                                      'color': '#737373'},
                          'Uranus': {   'enabled': True,
                                        'blur_radius': 15,
                                        'offset_x': 4,
                                        'offset_y': 4,
                                        'opacity': 97,
                                        'color': '#ffff00'},
                          'Neptune': {   'enabled': True,
                                         'blur_radius': 15,
                                         'offset_x': 4,
                                         'offset_y': 4,
                                         'opacity': 97,
                                         'color': '#0000ff'},
                          'Pluto': {   'enabled': True,
                                       'blur_radius': 15,
                                       'offset_x': 4,
                                       'offset_y': 4,
                                       'opacity': 97,
                                       'color': '#ff0000'}},
    'sign_label_offsets': {   'enabled': True,
                              'Dhata': {'offset_x': -7, 'offset_y': -26},
                              'Aryama': {'offset_x': 0, 'offset_y': -26},
                              'Mitra': {'offset_x': 0, 'offset_y': -26},
                              'Varuna': {'offset_x': 0, 'offset_y': -21},
                              'Indra': {'offset_x': 0, 'offset_y': -21},
                              'Vivasvan': {'offset_x': 0, 'offset_y': -4},
                              'Tvasta': {'offset_x': 0, 'offset_y': 0},
                              'Vishnu': {'offset_x': 0, 'offset_y': 0},
                              'Amzu': {'offset_x': -21, 'offset_y': -9},
                              'Bhaga': {'offset_x': -21, 'offset_y': -9},
                              'Pusha': {'offset_x': -21, 'offset_y': -14},
                              'Parjanya': {'offset_x': -21, 'offset_y': -24}},
    'house_number_offsets': {   'enabled': False,
                                'Dhata': {'offset_x': 47, 'offset_y': -14},
                                'Aryama': {'offset_x': 32, 'offset_y': -16},
                                'Mitra': {'offset_x': 23, 'offset_y': -13},
                                'Varuna': {'offset_x': 20, 'offset_y': -25},
                                'Indra': {'offset_x': 16, 'offset_y': -39},
                                'Vivasvan': {'offset_x': 18, 'offset_y': -55},
                                'Tvasta': {'offset_x': 27, 'offset_y': -56},
                                'Vishnu': {'offset_x': 39, 'offset_y': -56},
                                'Amzu': {'offset_x': 61, 'offset_y': -54},
                                'Bhaga': {'offset_x': 61, 'offset_y': -40},
                                'Pusha': {'offset_x': 63, 'offset_y': -24},
                                'Parjanya': {'offset_x': 64, 'offset_y': -9}}}

# Default Wheel chart display settings
DEFAULT_WHEEL_DISPLAY = {
    "sign_name": {
        "font_size": 26,
        "font_color": "#1a1a1a",  # Dark text for light backgrounds
        "font_weight": "bold",
        "offset_x": 0,
        "offset_y": 0
    },
    "planet_degrees": {
        "font_size": 18,
        "font_color": "#000000",
        "font_weight": "normal",
        "offset_x": 0,
        "offset_y": 21
    },
    "planet_sizes": {
        "Sun": 130,
        "Moon": 151,
        "Mars": 139,
        "Mercury": 138,
        "Jupiter": 137,
        "Venus": 127,
        "Saturn": 146,
        "Rahu": 124,
        "Ketu": 121,
        "Uranus": 99,
        "Neptune": 91,
        "Pluto": 97
    },
    "indicator_line": {
        "glow_radius": 6,    # Blur radius for glow effect (0 = no glow, 100 = max)
        "line_width": 1       # Line thickness in pixels
    }
}

# Default North Indian chart display settings.
#
# Colors: black labels (#000000) give much better contrast than gold against
# the element-colored cell gradients (Fire=coral, Earth=brown, Air=yellow,
# Water=deep blue). The previous gold default was effectively invisible on
# the yellow "Air" cells and washed out on Fire/Earth. Planet sizes were
# also bumped so the icons read clearly at typical window sizes.
DEFAULT_NORTH_INDIAN_DISPLAY = {
    "sign_name": {
        "font_size_diamond": 24,   # For diamond-shaped houses (1, 4, 7, 10)
        "font_size_triangle": 18,  # For triangle-shaped houses
        "font_color": "#000000",   # Black — high contrast on all 4 element colors
        "font_weight": "bold",
        "offset_x": -1,
        "offset_y": -10
    },
    "planet_degrees": {
        "font_size": 14,
        "font_color": "#000000",   # Black — matches sign_name for consistency
        "font_weight": "normal",
        "offset_x": 0,
        "offset_y": 0
    },
    "planet_sizes": {
        "Sun": 149,
        "Moon": 186,
        "Mars": 152,
        "Mercury": 142,
        "Jupiter": 140,
        "Venus": 120,
        "Saturn": 143,
        "Rahu": 130,
        "Ketu": 120,
        "Uranus": 128,
        "Neptune": 120,
        "Pluto": 110
    }
}

# Default settings structure
DEFAULT_SETTINGS = {
    "version": "2.0",

    "appearance": {
        "theme": "Dark Blue",
        "font_family": "Inter",
        "font_size_preset": "medium"
    },

    "font_sizes": {
        "chart_title": 12,
        "chart_degree": 8,
        "chart_planet": 10,
        "dasha_header": 14,
        "dasha_body": 11,
        "button": 11,
        "label": 10,
        "heading": 16,
        "body": 13,
        "small": 11,
        "tiny": 10
    },

    "display": {
        "background": "stone_06",
        "font_scale": 1.0,
        "fonts": {
            "tables": 11,
            "table_headers": 12,
            "panel_titles": 14,
            "info_text": 11,
            "buttons": 10,
            "sidebar": 10,
            "status": 9,
            "tabs": 12
        }
    },

    "chart": {
        "view_type": "south_indian",
        "show_outer_planets": True,
        "show_planet_names": False,
        "show_retinue_rings": False,
        "show_trimsamsha_degrees": False,
        "show_element_pies": True,
        "cusp_glow_mode": 0,
        "wheel_house_display": "sign_based"
    },

    "zodiac": {
        "mode": "aditya",
        "ayanamsa_id": 1,
        "house_system": "campanus",
        "use_western_names": False,
        "nakshatra_coords": "neither",
        "human_design": False,
        "sign_language": "en"
    },

    "dasha": {
        "left":  {"ayanamsa_id": 100},
        "right": {"mode": "nisarga", "ayanamsa_id": 98}
    },

    "ui": {
        "last_active_tab": 0,
        "restore_last_tab": True,
        # SPEC-MODE-001: Beginner hides alternative sign-naming; Advanced exposes
        # all 6 zodiac/label combinations. Default Beginner on fresh + upgraded
        # installs (injected here so _deep_merge propagates it to existing files).
        "experience_level": "beginner",
        "panel": {
            "karakas_tab": 0,
            "strength_tab": 0,
            "aspects_mode": "vedic",
            "aspects_tab": 0
        }
    },

    # Flat dict keyed by full dot-path strings (e.g. "chart.view_type").
    # Value True means the setting is "frozen": runtime changes are not
    # written back, so the stored value survives across restarts.
    # NOTE: intentionally flat — do NOT nest by section. Access it directly
    # via self._settings["locks"][full_dot_path], never via self.get(...).
    "locks": {},

    "windows": {
        "main": {"width": 1920, "height": 1080},
        "remember_geometry": True,
        "last_position": {"x": None, "y": None}
    },

    "paths": {
        "chart_folders": [],
        "default_folder": "",
        "screenshot_folder": "",
        "kala_path": ""
    },

    "defaults": {
        "aditya_mode": "aditya",
        "auto_restore_session": True
    }
}

# Font size presets (ordered from smallest to largest)
FONT_SIZE_PRESETS = {
    "very_small": {
        "chart_title": 8,
        "chart_degree": 6,
        "chart_planet": 7,
        "dasha_header": 10,
        "dasha_body": 8,
        "button": 8,
        "label": 8,
        "heading": 12,
        "body": 9,
        "small": 8,
        "tiny": 7
    },
    "small": {
        "chart_title": 10,
        "chart_degree": 7,
        "chart_planet": 8,
        "dasha_header": 12,
        "dasha_body": 9,
        "button": 9,
        "label": 9,
        "heading": 14,
        "body": 11,
        "small": 9,
        "tiny": 8
    },
    "medium": {
        "chart_title": 12,
        "chart_degree": 8,
        "chart_planet": 10,
        "dasha_header": 14,
        "dasha_body": 11,
        "button": 11,
        "label": 10,
        "heading": 16,
        "body": 13,
        "small": 11,
        "tiny": 10
    },
    "large": {
        "chart_title": 14,
        "chart_degree": 10,
        "chart_planet": 12,
        "dasha_header": 16,
        "dasha_body": 13,
        "button": 13,
        "label": 12,
        "heading": 18,
        "body": 15,
        "small": 13,
        "tiny": 12
    },
    "very_large": {
        "chart_title": 18,
        "chart_degree": 12,
        "chart_planet": 14,
        "dasha_header": 20,
        "dasha_body": 16,
        "button": 16,
        "label": 14,
        "heading": 22,
        "body": 18,
        "small": 16,
        "tiny": 14
    }
}

# API providers configuration
API_PROVIDERS = {
    "Z_AI_API_KEY": {
        "name": "Z.AI (OCR)",
        "description": "Used for screenshot OCR text extraction",
        "test_endpoint": None  # Could add test URL later
    },
    "PERPLEXITY_API_KEY": {
        "name": "Perplexity",
        "description": "Used for AI-powered search",
        "test_endpoint": None
    },
    "OPENAI_API_KEY": {
        "name": "OpenAI",
        "description": "Used for GPT models",
        "test_endpoint": None
    },
    "ANTHROPIC_API_KEY": {
        "name": "Anthropic",
        "description": "Used for Claude models",
        "test_endpoint": None
    },
    "DEEPSEEK_API_KEY": {
        "name": "DeepSeek",
        "description": "Used for chart categorization and birth data parsing",
        "test_endpoint": None
    }
}


class SettingsManager:
    """
    Centralized settings manager with typed access and auto-migration.

    Usage:
        from managers.settings_manager import get_settings
        settings = get_settings()

        # Get values
        font_size = settings.get_font_size("dasha_header")
        theme = settings.get_theme()

        # Set values
        settings.set_font_size("dasha_header", 16)
        settings.set_theme("Blue Light")
    """

    CONFIG_FILE = "app_settings.json"
    ENV_FILE = ".env"

    # Legacy config files to migrate
    LEGACY_CONFIGS = {
        ".theme_config.json": ["appearance.theme", "appearance.font_family"],
        ".chtk_config.json": ["paths.chtk_folder"],
        "settings.json": ["display"],
        ".screenshot_config.json": ["paths.screenshot_folder"],
        ".chart_search_config.json": ["paths.search_folders"]
    }

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize the settings manager.

        Args:
            config_dir: Directory for config files. Defaults to user data dir.
        """
        if config_dir is None:
            from state.user_data import get_user_data_dir
            config_dir = str(get_user_data_dir() or PROJECT_ROOT)
        self._config_dir = config_dir
        self._config_path = os.path.join(self._config_dir, self.CONFIG_FILE)
        self._env_path = os.path.join(self._config_dir, self.ENV_FILE)
        self._settings: Dict[str, Any] = {}
        self._env_cache: Dict[str, str] = {}
        self._callbacks: List[callable] = []
        self._key_callbacks: Dict[str, List[Callable]] = {}

        # Load settings
        self._load()

        # Migrate legacy configs on first run
        if not os.path.exists(self._config_path):
            self._migrate_legacy_configs()
            self._save()

        # Migrate from PrefsStore (settings.json) if not already done
        if not self.get("_migrated_from_prefs", False):
            self._migrate_from_prefs()

    # -------------------------------------------------------------------------
    # Core Methods
    # -------------------------------------------------------------------------

    def _load(self) -> bool:
        """Load settings from JSON file, creating defaults if needed."""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    self._settings = json.load(f)
                # Merge with defaults to handle new keys
                self._settings = self._deep_merge(copy.deepcopy(DEFAULT_SETTINGS), self._settings)
            else:
                self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            return True
        except Exception as e:
            debug_print(f"[SettingsManager] Error loading settings: {e}")
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            return False

    def _save(self) -> bool:
        """Save current settings to JSON file."""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            debug_print(f"[SettingsManager] Error saving settings: {e}")
            return False

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge two dictionaries, with override taking precedence."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _migrate_legacy_configs(self):
        """Migrate settings from legacy config files."""
        debug_print("[SettingsManager] Checking for legacy config files...")

        for legacy_file, mappings in self.LEGACY_CONFIGS.items():
            legacy_path = os.path.join(self._config_dir, legacy_file)
            if os.path.exists(legacy_path):
                debug_print(f"[SettingsManager] Migrating: {legacy_file}")
                try:
                    with open(legacy_path, 'r', encoding='utf-8') as f:
                        legacy_data = json.load(f)
                    self._apply_legacy_migration(legacy_file, legacy_data)
                except Exception as e:
                    debug_print(f"[SettingsManager] Error migrating {legacy_file}: {e}")

    def _apply_legacy_migration(self, filename: str, data: dict):
        """Apply migration logic for specific legacy files."""
        if filename == ".theme_config.json":
            if "theme" in data:
                self.set("appearance.theme", data["theme"], save=False)
            if "font" in data:
                self.set("appearance.font_family", data["font"], save=False)

        elif filename == ".chtk_config.json":
            if "chtk_folder" in data:
                self.set("paths.chtk_folder", data["chtk_folder"], save=False)

        elif filename == "settings.json":
            # Chart browser settings - map what we can
            if "planet_size" in data:
                self.set("display.planet_size", data["planet_size"], save=False)
            # Migrate background_num to new background format
            if "background_num" in data:
                old_num = data["background_num"]
                new_bg = f"celestial_{old_num:02d}"
                self.set("display.background", new_bg, save=False)

        elif filename == ".screenshot_config.json":
            if "screenshot_folder" in data:
                self.set("paths.screenshot_folder", data["screenshot_folder"], save=False)

        elif filename == ".chart_search_config.json":
            if "search_folders" in data:
                self.set("paths.search_folders", data["search_folders"], save=False)

    def _migrate_from_prefs(self):
        """Migrate from PrefsStore settings.json to consolidated app_settings.json."""
        prefs_path = os.path.join(self._config_dir, "settings.json")
        if not os.path.exists(prefs_path):
            self.set("_migrated_from_prefs", True, save=True)
            return

        try:
            with open(prefs_path, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
        except Exception as e:
            debug_print(f"[SettingsManager] Error reading settings.json for migration: {e}")
            self.set("_migrated_from_prefs", True, save=True)
            return

        debug_print("[SettingsManager] Migrating from settings.json...")

        # Theme: convert filename to display name
        theme_file = prefs.get("theme")
        if theme_file:
            from ui.themes import AVAILABLE_THEMES
            theme_map = {t[0]: t[1] for t in AVAILABLE_THEMES}
            display_name = theme_map.get(theme_file, theme_file)
            self.set("appearance.theme", display_name, save=False)

        # Aditya mode: translate old enum values
        mode = prefs.get("aditya_mode")
        if mode:
            if mode == "zodiac":
                mode = "aditya"
            elif mode == "classic":
                mode = "tropical_classic"
            self.set("zodiac.mode", mode, save=False)
            self.set("defaults.aditya_mode", mode, save=False)

        # Chart view style
        view = prefs.get("chart_view_style") or prefs.get("chart_view")
        if view:
            self.set("chart.view_type", view, save=False)

        # Toggle keys -> chart.* namespace
        for old_key, new_key in [
            ("show_retinue_rings", "chart.show_retinue_rings"),
            ("show_element_pies", "chart.show_element_pies"),
            ("cusp_glow_mode", "chart.cusp_glow_mode"),
        ]:
            if old_key in prefs:
                self.set(new_key, prefs[old_key], save=False)

        # Kala path: flatten nested dict
        kala = prefs.get("kala")
        if isinstance(kala, dict) and kala.get("exe_path"):
            self.set("paths.kala_path", kala["exe_path"], save=False)

        # Chart folders: merge from chart_browser and platform folders
        folders = []
        browser = prefs.get("chart_browser")
        if isinstance(browser, dict):
            for key in ["default_folder", "folder_1", "folder_2", "folder_3"]:
                val = browser.get(key, "")
                if val and val not in folders:
                    folders.append(val)
            for extra in browser.get("extra_folders", []):
                if extra and extra not in folders:
                    folders.append(extra)
            if browser.get("default_folder"):
                self.set("paths.default_folder", browser["default_folder"], save=False)
        for platform_key in ["search_folders_windows", "search_folders_linux"]:
            platform_folders = prefs.get(platform_key, [])
            if isinstance(platform_folders, list):
                for f in platform_folders:
                    if f and f not in folders:
                        folders.append(f)
        if folders:
            self.set("paths.chart_folders", folders, save=False)

        # Icon variations (preserve as-is for chart display consumers)
        for key in ["zodiac_icons", "planet_icons"]:
            if key in prefs:
                self.set(f"display.{key.replace('_icons', '_variations')}", prefs[key], save=False)

        # Font settings
        fonts = prefs.get("fonts")
        if isinstance(fonts, dict) and fonts.get("primary"):
            self.set("appearance.font_family", fonts["primary"], save=False)

        self.set("_migrated_from_prefs", True, save=False)
        self._save()

        # Rename settings.json to .bak
        bak_path = prefs_path + ".bak"
        try:
            os.rename(prefs_path, bak_path)
            debug_print(f"[SettingsManager] Renamed settings.json to {bak_path}")
        except Exception as e:
            debug_print(f"[SettingsManager] Could not rename settings.json: {e}")

    # -------------------------------------------------------------------------
    # Generic Access Methods
    # -------------------------------------------------------------------------

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a setting by dot-notation path.

        Args:
            key_path: Dot-separated path (e.g., "font_sizes.dasha_header")
            default: Value to return if key not found

        Returns:
            The setting value or default
        """
        keys = key_path.split(".")
        value = self._settings
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value: Any, save: bool = True) -> bool:
        """
        Set a setting by dot-notation path.

        Args:
            key_path: Dot-separated path (e.g., "font_sizes.dasha_header")
            value: Value to set
            save: Whether to save to disk immediately

        Returns:
            True if successful
        """
        keys = key_path.split(".")
        target = self._settings
        try:
            for key in keys[:-1]:
                if key not in target:
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
            if save:
                self._save()
            self._notify_change(key_path, value)
            return True
        except Exception as e:
            debug_print(f"[SettingsManager] Error setting {key_path}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Lock / Write-back API (SPEC-SET-002)
    #
    # The "lock" model = "freeze write-back". A locked key keeps its stored
    # value: runtime changes are dropped by persist_runtime_change() so the
    # pinned value is restored on the next startup. The Settings-tab Apply
    # path calls set() directly and ALWAYS writes, ignoring the lock.
    #
    # Locks live in a FLAT dict (self._settings["locks"]) keyed by the full
    # dot-path string. It must be accessed directly, NOT via self.get(), so
    # the dotted key is treated as a single literal key rather than split and
    # traversed as nested dicts.
    # -------------------------------------------------------------------------

    def is_locked(self, key_path: str) -> bool:
        """
        Return whether ``key_path`` is locked (frozen against write-back).

        ``locks`` is a FLAT dict keyed by the full dot-path, so we read it
        directly instead of self.get(f"locks.{key_path}") (which would split
        the key on dots and traverse nested dicts incorrectly). A missing
        key, or a missing ``locks`` section, means not locked.
        """
        return bool(self._settings.get("locks", {}).get(key_path, False))

    def set_locked(self, key_path: str, locked: bool) -> None:
        """
        Set the flat lock flag for ``key_path`` and persist to disk.

        Stores under the flat ``locks`` dict keyed by the full dot-path.
        """
        self._settings.setdefault("locks", {})[key_path] = bool(locked)
        self._save()

    def persist_runtime_change(self, key_path: str, value: Any) -> None:
        """
        Write-back path for runtime changes that RESPECTS the lock.

        This is the ONLY place the lock is enforced. If ``key_path`` is locked
        the change is discarded (the stored value is left untouched so the
        pinned value is restored on next startup). Otherwise the value is
        written via set(). Falsy values such as 0 are written normally.
        """
        if not self.is_locked(key_path):
            self.set(key_path, value)

    # -------------------------------------------------------------------------
    # Typed Getters - Appearance
    # -------------------------------------------------------------------------

    def get_theme(self) -> str:
        """Get current theme name."""
        return self.get("appearance.theme", "Dark Blue")

    def set_theme(self, theme: str):
        """Set theme name."""
        self.set("appearance.theme", theme)

    def get_font_family(self) -> str:
        """Get current font family."""
        return self.get("appearance.font_family", "Inter")

    def set_font_family(self, font: str):
        """Set font family."""
        self.set("appearance.font_family", font)

    # -------------------------------------------------------------------------
    # Typed Getters - Font Sizes
    # -------------------------------------------------------------------------

    def get_font_size(self, component: str) -> int:
        """
        Get font size for a specific component.

        Args:
            component: One of: chart_title, chart_degree, chart_planet,
                      dasha_header, dasha_body, button, label, heading,
                      body, small, tiny

        Returns:
            Font size in pixels
        """
        default = DEFAULT_SETTINGS["font_sizes"].get(component, 12)
        return self.get(f"font_sizes.{component}", default)

    def set_font_size(self, component: str, size: int):
        """Set font size for a specific component."""
        self.set(f"font_sizes.{component}", size)

    def get_all_font_sizes(self) -> Dict[str, int]:
        """Get all font sizes as a dictionary."""
        return self.get("font_sizes", DEFAULT_SETTINGS["font_sizes"].copy())

    def set_all_font_sizes(self, sizes: Dict[str, int]):
        """Set all font sizes at once."""
        self.set("font_sizes", sizes)

    def apply_font_preset(self, preset: str):
        """
        Apply a font size preset.

        Args:
            preset: One of: small, medium, large
        """
        if preset in FONT_SIZE_PRESETS:
            self.set("font_sizes", FONT_SIZE_PRESETS[preset].copy())

    # -------------------------------------------------------------------------
    # Typed Getters - Display
    # -------------------------------------------------------------------------

    def get_planet_size(self) -> int:
        """Get planet image size."""
        return self.get("display.planet_size", 60)

    def set_planet_size(self, size: int):
        """Set planet image size."""
        self.set("display.planet_size", size)

    def get_background(self) -> str:
        """
        Get background identifier (e.g., 'celestial_01').

        Automatically migrates from old background_num format if found.
        """
        # Check new format first
        bg = self.get("display.background", None)
        if bg:
            return bg

        # Migrate from old format (background_num 1-10)
        old_num = self.get("display.background_num", None)
        if old_num is not None:
            new_bg = f"celestial_{old_num:02d}"
            self.set("display.background", new_bg, save=True)
            return new_bg

        return "stone_06"

    def set_background(self, bg_identifier: str):
        """Set background identifier (e.g., 'celestial_01') and save."""
        self.set("display.background", bg_identifier)

    # -------------------------------------------------------------------------
    # Typed Getters - Windows
    # -------------------------------------------------------------------------

    def get_window_size(self, window: str = "main") -> Tuple[int, int]:
        """
        Get window size.

        Args:
            window: Window name (default: "main")

        Returns:
            Tuple of (width, height)
        """
        size = self.get(f"windows.{window}", {"width": 1920, "height": 1080})
        return (size.get("width", 1920), size.get("height", 1080))

    def set_window_size(self, width: int, height: int, window: str = "main"):
        """Set window size."""
        self.set(f"windows.{window}", {"width": width, "height": height})

    def get_remember_window_size(self) -> bool:
        """Get whether to remember window geometry (size and position)."""
        return self.get("windows.remember_geometry", True)

    def set_remember_window_size(self, remember: bool):
        """Set whether to remember window geometry."""
        self.set("windows.remember_geometry", remember)

    def get_window_position(self) -> Optional[Tuple[int, int]]:
        """Get last window position."""
        pos = self.get("windows.last_position", {"x": None, "y": None})
        if pos.get("x") is not None and pos.get("y") is not None:
            return (pos["x"], pos["y"])
        return None

    def set_window_position(self, x: int, y: int):
        """Set window position."""
        self.set("windows.last_position", {"x": x, "y": y})

    # -------------------------------------------------------------------------
    # Typed Getters - Paths
    # -------------------------------------------------------------------------

    def get_chart_folders(self) -> list:
        """Get all chart folders as a 3-element list [default, folder_1, folder_2].

        Always returns exactly 3 elements, padded with empty strings.
        This is the single source of truth for chart folder paths.
        """
        folders = list(self.get("paths.chart_folders", []))
        while len(folders) < 3:
            folders.append("")
        return folders[:3]

    def set_chart_folders(self, folders: list):
        """Set chart folders (max 3: default + 2 extras).

        Also keeps paths.default_folder in sync for legacy consumers.
        """
        folders = list(folders)
        while len(folders) < 3:
            folders.append("")
        folders = folders[:3]
        self.set("paths.default_folder", folders[0] if folders[0] else "", save=False)
        self.set("paths.chart_folders", folders)

    def get_screenshot_folder(self) -> str:
        """Get screenshot folder path."""
        return self.get("paths.screenshot_folder", "")

    def set_screenshot_folder(self, path: str):
        """Set screenshot folder path."""
        self.set("paths.screenshot_folder", path)

    # -------------------------------------------------------------------------
    # Typed Getters - Defaults
    # -------------------------------------------------------------------------

    def get_default_aditya_mode(self) -> str:
        """Get default Aditya mode (aditya, tropical_classic, or sidereal)."""
        return self.get("defaults.aditya_mode", "aditya")

    def set_default_aditya_mode(self, mode: str):
        """Set default Aditya mode."""
        self.set("defaults.aditya_mode", mode)

    def get_auto_restore_session(self) -> bool:
        """Get whether to auto-restore session."""
        return self.get("defaults.auto_restore_session", True)

    def set_auto_restore_session(self, restore: bool):
        """Set whether to auto-restore session."""
        self.set("defaults.auto_restore_session", restore)

    # -------------------------------------------------------------------------
    # Typed Getters - Chart Display
    # -------------------------------------------------------------------------

    def get_chart_display(self) -> Dict[str, Any]:
        """
        Get chart display settings for customizing chart appearance.

        Returns:
            Dict with shadow, sign_label, sign_icon, planets, planet_text,
            lagna_strip, and planet_sizes settings.
        """
        stored = self.get("chart_display", None)
        if stored is None:
            return DEFAULT_CHART_DISPLAY.copy()
        # Deep merge with defaults to ensure all keys exist
        return self._deep_merge(DEFAULT_CHART_DISPLAY.copy(), stored)

    def set_chart_display(self, settings: Dict[str, Any]):
        """
        Set chart display settings.

        Args:
            settings: Dict with chart display settings
        """
        self.set("chart_display", settings)

    def get_chart_display_section(self, section: str) -> Dict[str, Any]:
        """
        Get a specific section of chart display settings.

        Args:
            section: One of: shadow, sign_label, sign_icon, planets,
                    planet_text, lagna_strip, planet_sizes

        Returns:
            Dict with section settings
        """
        full = self.get_chart_display()
        return full.get(section, DEFAULT_CHART_DISPLAY.get(section, {}))

    def set_chart_display_section(self, section: str, values: Dict[str, Any]):
        """
        Set a specific section of chart display settings.

        Args:
            section: Section name
            values: Dict with section values
        """
        full = self.get_chart_display()
        full[section] = values
        self.set_chart_display(full)

    def reset_chart_display(self):
        """Reset chart display settings to defaults."""
        self.set("chart_display", DEFAULT_CHART_DISPLAY.copy())

    # -------------------------------------------------------------------------
    # Wheel Chart Display Settings
    # -------------------------------------------------------------------------

    def get_wheel_display(self) -> Dict[str, Any]:
        """
        Get Wheel chart display settings.

        Returns:
            Dict with sign_name, planet_degrees, and planet_sizes settings.
        """
        stored = self.get("wheel_display", None)
        if stored is None:
            return DEFAULT_WHEEL_DISPLAY.copy()
        return self._deep_merge(DEFAULT_WHEEL_DISPLAY.copy(), stored)

    def set_wheel_display(self, settings: Dict[str, Any]):
        """
        Set Wheel chart display settings.

        Args:
            settings: Dict with wheel display settings
        """
        self.set("wheel_display", settings)

    def reset_wheel_display(self):
        """Reset Wheel chart display settings to defaults."""
        self.set("wheel_display", DEFAULT_WHEEL_DISPLAY.copy())

    # -------------------------------------------------------------------------
    # North Indian Chart Display Settings
    # -------------------------------------------------------------------------

    def get_north_indian_display(self) -> Dict[str, Any]:
        """
        Get North Indian chart display settings.

        Returns:
            Dict with sign_name, planet_degrees, and planet_sizes settings.
        """
        stored = self.get("north_indian_display", None)
        if stored is None:
            return DEFAULT_NORTH_INDIAN_DISPLAY.copy()
        return self._deep_merge(DEFAULT_NORTH_INDIAN_DISPLAY.copy(), stored)

    def set_north_indian_display(self, settings: Dict[str, Any]):
        """
        Set North Indian chart display settings.

        Args:
            settings: Dict with north indian display settings
        """
        self.set("north_indian_display", settings)

    def reset_north_indian_display(self):
        """Reset North Indian chart display settings to defaults."""
        self.set("north_indian_display", DEFAULT_NORTH_INDIAN_DISPLAY.copy())

    # -------------------------------------------------------------------------
    # API Keys (.env handling)
    # -------------------------------------------------------------------------

    def _load_env(self) -> Dict[str, str]:
        """Load environment variables from .env file."""
        env_vars = {}
        if os.path.exists(self._env_path):
            try:
                with open(self._env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            env_vars[key.strip()] = value.strip().strip('"\'')
            except Exception as e:
                debug_print(f"[SettingsManager] Error loading .env: {e}")
        return env_vars

    def _save_env(self, env_vars: Dict[str, str]) -> bool:
        """Save environment variables to .env file."""
        try:
            # Read existing content to preserve comments
            lines = []
            existing_keys = set()

            if os.path.exists(self._env_path):
                with open(self._env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#') and '=' in stripped:
                            key = stripped.split('=', 1)[0].strip()
                            if key in env_vars:
                                lines.append(f"{key}={env_vars[key]}\n")
                                existing_keys.add(key)
                            else:
                                lines.append(line)
                        else:
                            lines.append(line)

            # Add new keys
            for key, value in env_vars.items():
                if key not in existing_keys:
                    lines.append(f"{key}={value}\n")

            with open(self._env_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            return True
        except Exception as e:
            debug_print(f"[SettingsManager] Error saving .env: {e}")
            return False

    def get_api_key(self, provider: str) -> str:
        """
        Get API key for a provider.

        Args:
            provider: Provider key (e.g., "Z_AI_API_KEY", "PERPLEXITY_API_KEY")

        Returns:
            API key string or empty string if not found
        """
        # First check environment variable
        env_value = os.environ.get(provider, "")
        if env_value:
            return env_value

        # Then check .env file
        env_vars = self._load_env()
        return env_vars.get(provider, "")

    def set_api_key(self, provider: str, key: str) -> bool:
        """
        Set API key for a provider.

        Args:
            provider: Provider key (e.g., "Z_AI_API_KEY")
            key: API key value

        Returns:
            True if saved successfully
        """
        env_vars = self._load_env()
        env_vars[provider] = key
        return self._save_env(env_vars)

    def list_api_providers(self) -> List[Dict[str, Any]]:
        """
        List all configured API providers.

        Returns:
            List of dicts with provider info and current key status
        """
        env_vars = self._load_env()
        providers = []
        for key, info in API_PROVIDERS.items():
            current_key = env_vars.get(key, os.environ.get(key, ""))
            providers.append({
                "key": key,
                "name": info["name"],
                "description": info["description"],
                "has_key": bool(current_key),
                "key_preview": self._mask_key(current_key) if current_key else ""
            })
        return providers

    def _mask_key(self, key: str) -> str:
        """Mask API key for display (show first/last 4 chars)."""
        if len(key) <= 8:
            return "*" * len(key)
        return key[:4] + "*" * (len(key) - 8) + key[-4:]

    # -------------------------------------------------------------------------
    # Change Notification
    # -------------------------------------------------------------------------

    def add_change_callback(self, callback: callable):
        """Add a callback to be notified when settings change."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_change_callback(self, callback: callable):
        """Remove a change callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def on_changed(self, key: str, callback: Callable) -> None:
        """Register a callback for when a specific key (or prefix) changes.

        The callback fires when any key_path starting with `key` changes.
        Signature: callback(key_path: str, value: Any).
        """
        self._key_callbacks.setdefault(key, []).append(callback)

    def _notify_change(self, key_path: str, value: Any):
        """Notify all callbacks of a setting change."""
        for callback in list(self._callbacks):
            try:
                callback(key_path, value)
            except Exception as e:
                debug_print(f"[SettingsManager] Callback error: {e}")
        if hasattr(self, "_key_callbacks"):
            for prefix, cbs in self._key_callbacks.items():
                if key_path == "*" or key_path.startswith(prefix):
                    for cb in list(cbs):
                        try:
                            cb(key_path, value)
                        except Exception as e:
                            debug_print(f"[SettingsManager] Key callback error for {prefix}: {e}")

    # -------------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------------

    def reset_to_defaults(self, section: Optional[str] = None):
        """
        Reset settings to defaults.

        Args:
            section: Optional section to reset (e.g., "font_sizes", "zodiac").
                    If None, resets all settings.
        """
        if section:
            if section in DEFAULT_SETTINGS:
                self.set(section, copy.deepcopy(DEFAULT_SETTINGS[section]))
        else:
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            self._save()
            self._notify_change("*", None)


# -----------------------------------------------------------------------------
# Singleton Access
# -----------------------------------------------------------------------------

_instance: Optional[SettingsManager] = None


def get_settings() -> SettingsManager:
    """
    Get the singleton SettingsManager instance.

    Usage:
        from managers.settings_manager import get_settings
        settings = get_settings()
        font_size = settings.get_font_size("dasha_header")
    """
    global _instance
    if _instance is None:
        _instance = SettingsManager()
    return _instance


def reset_settings_instance():
    """Reset the singleton instance (useful for testing)."""
    global _instance
    _instance = None
