"""Appearance/settings gateway and per-instance bounded icon caches; no chart or view."""
from apps.widgets.planet_icon_loader import load_planet_icon
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication
from apps.widgets.chart_view import SouthIndianView
from apps.widgets.south_indian_geometry import PROJECT_ROOT, SIGN_ICON_SIZE, MIN_BADGE_FONT_SIZE
from apps.widgets.south_indian_paint_style import RenderStyle
from ui.qt_theme import desat_image, get_ui_saturation
from ui.south_indian_finishes import WOOD, normalize_finish, normalize_sign_display

class AppearanceAssets:
    WESTERN_NAMES = SouthIndianView.WESTERN_NAMES
    PLANET_ICON_NAMES = SouthIndianView.PLANET_ICON_NAMES
    PLANET_SIZES = SouthIndianView.PLANET_SIZES

    def __init__(self, live=True):
        from managers.settings_manager import get_settings
        settings = get_settings()
        self.vector_finish = normalize_finish(settings.get('display.south_indian_vector_finish','standard'))
        # td-iaqm.5 (CP5): all South Indian finishes (wood and standard) follow the
        # app-wide display.sign_display, the single sign-display setting shared with
        # the Wheel and the North Indian chart. The attribute keeps its historical
        # name (a registered facade accessor); only its source changed.
        self.wood_sign_display = normalize_sign_display(settings.get('display.sign_display','zodiac'))
        self.sign_language = 'en'
        self.foreground_only = False
        self.live = bool(live)
        self.background_id = None
        self._si_display_settings = self._load_display_settings()
        self._variation_settings = self._load_variation_settings()
        self._planet_variation_settings = self._load_planet_variation_settings()
        self._icon_cache = {}
        self._planet_icon_cache = {}

    @property
    def wood(self):
        return WOOD.get(self.vector_finish)

    def apply(self, finish, sign_display):
        values = normalize_finish(finish), normalize_sign_display(sign_display)
        if values == (self.vector_finish, self.wood_sign_display):
            return False
        self.vector_finish, self.wood_sign_display = values
        return True

    def style(self):
        from managers.settings_manager import get_settings, HOUSE_NUMBER_FONT_MAX
        font = min(HOUSE_NUMBER_FONT_MAX, get_settings().get_chart_display_section('house_number')['font_size'])
        return RenderStyle(self.vector_finish, self.wood_sign_display, self.sign_language,
            self._si_display_settings, self.PLANET_SIZES, self.load_sign_icon, self.load_planet_image,
            self.get_selected_variation, max(MIN_BADGE_FONT_SIZE, font-3), self.foreground_only)

    def reload_display(self):
        self._si_display_settings = self._load_display_settings()

    @staticmethod
    def remember(cache, key, value):
        # Scope caches to the owner and cap variation/size/saturation combinations.
        if len(cache) >= 128 and key not in cache:
            cache.pop(next(iter(cache)))
        cache[key] = value


    def _load_display_settings(self) -> dict:
        """Load the south_indian_display block (font size/weight)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get_south_indian_display()
        except Exception as e:
            print(f'[SI VECTOR] Warning: could not load display settings: {e}')
            return {}

    def _load_variation_settings(self) -> dict:
        """Load display.zodiac_variations (sign icon variation per sign)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get('display.zodiac_variations', {})
        except Exception as e:
            print(f'[SI VECTOR] Warning: could not load variations: {e}')
            return {}

    def _load_planet_variation_settings(self) -> dict:
        """Load display.planet_variations (planet icon variation per planet)."""
        try:
            from managers.settings_manager import get_settings
            return get_settings().get('display.planet_variations', {})
        except Exception as e:
            print(f'[SI VECTOR] Warning: could not load planet variations: {e}')
            return {}

    def load_sign_icon(self, sign_index: int, size: int=SIGN_ICON_SIZE):
        """Load the variation-aware sign icon (canonical classic loader,
            chart_view.py:1095-1154, mirrored). No HiDPI scaling — the view
            transform handles it (INV-4). Cached by (sign, variation, size).

            Tries img/sign/{WesternName}{variation}.webp, falls back to
            {WesternName}1.webp (always shipped). Returns None if unreadable.
            """
        western_name = self.WESTERN_NAMES[sign_index]
        variation = self.get_selected_variation(sign_index)
        cache_key = (sign_index, variation, size, get_ui_saturation())
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        icon_path = PROJECT_ROOT / f'img/sign/{western_name}{variation}.webp'
        if not icon_path.exists():
            icon_path = PROJECT_ROOT / f'img/sign/{western_name}1.webp'
        if not icon_path.exists():
            print(f'[SI VECTOR] Warning: icon not found for {western_name}')
            self.remember(self._icon_cache, cache_key, None)
            return None
        qimage = QImage(str(icon_path))
        if qimage.isNull():
            print(f'[SI VECTOR] Warning: failed to load image: {icon_path}')
            self.remember(self._icon_cache, cache_key, None)
            return None
        qimage = qimage.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        qimage = desat_image(qimage)
        pixmap = QPixmap.fromImage(qimage)
        self.remember(self._icon_cache, cache_key, pixmap)
        return pixmap

    def load_planet_image(self, planet_name, size=48):
        return load_planet_icon(planet_name, size, self.get_planet_variation(planet_name))

    def clear_icon_cache(self):
        """Drop cached sign + planet pixmaps (e.g. on UI saturation change)."""
        if hasattr(self, '_icon_cache'):
            self._icon_cache.clear()
        if hasattr(self, '_planet_icon_cache'):
            self._planet_icon_cache.clear()

    def get_selected_variation(self, zodiac_index):
        """Selected sign icon variation number (1 if unset)."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        return self._variation_settings.get(western_name, 1)

    def set_selected_variation(self, zodiac_index, variation_num, invalidate, redraw):
        """Persist + apply a sign icon variation, then redraw (classic
            chart_view.py:951-973 semantics)."""
        western_name = self.WESTERN_NAMES[zodiac_index]
        self._variation_settings[western_name] = variation_num
        invalidate()
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            stored = dict(settings.get('display.zodiac_variations', {}))
            stored[western_name] = variation_num
            settings.set('display.zodiac_variations', stored)
        except Exception as e:
            print(f'[SI VECTOR] Error saving variation settings: {e}')
        redraw()
        QApplication.processEvents()

    def get_planet_variation(self, planet_name):
        """Selected planet icon variation number (1 if unset)."""
        return self._planet_variation_settings.get(planet_name, 1)

    def set_planet_variation(self, planet_name, variation_num, invalidate, redraw):
        """Persist + apply a planet icon variation, then redraw (classic
            chart_view.py:1032-1049 semantics)."""
        self._planet_variation_settings[planet_name] = variation_num
        invalidate()
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            stored = dict(settings.get('display.planet_variations', {}))
            stored[planet_name] = variation_num
            settings.set('display.planet_variations', stored)
        except Exception as e:
            print(f'[SI VECTOR] Error saving planet variation settings: {e}')
        redraw()
        QApplication.processEvents()
