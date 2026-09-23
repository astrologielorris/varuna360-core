from PySide6.QtGui import QColor
from apps.widgets.sign_shadow_effect import SignShadowEffect

from managers.settings_manager import DEFAULT_CHART_DISPLAY, get_settings
from visualizations.wheel_constants import ELEMENT_CYCLE

LEGACY_AIR_SHADOW, AIR_SHADOW = "#9fff05", "#F0C75E"

def _shadow_settings(settings=None):
    if not isinstance(settings, dict):
        settings = get_settings().get_chart_display_section("element_shadows")
    defaults = DEFAULT_CHART_DISPLAY["element_shadows"]
    return {**defaults, **settings} if isinstance(settings, dict) else dict(defaults)

def clamp_sign_shadow_size(value, default):
    try:
        return max(0.0, min(12.0, float(value)))
    except (TypeError, ValueError):
        return float(default)

def create_sign_shadow(sign_index, settings=None):
    """Return the configured sign-art shadow, or ``None`` when disabled."""
    values = _shadow_settings(settings)
    if not values.get("enabled", True):
        return None

    try:
        element = ELEMENT_CYCLE[int(sign_index) % len(ELEMENT_CYCLE)].lower()
    except (TypeError, ValueError):
        element = "fire"
    defaults = DEFAULT_CHART_DISPLAY["element_shadows"]
    color_hex = values.get(element, defaults[element])
    if element == "air" and str(color_hex).lower() == LEGACY_AIR_SHADOW:
        color_hex = AIR_SHADOW
    color = QColor(str(color_hex))
    if not color.isValid():
        color = QColor(defaults[element])
    color.setAlpha(max(0, min(255, int(values.get("opacity", defaults["opacity"])))))

    effect = SignShadowEffect()
    effect.setBlurRadius(clamp_sign_shadow_size(
        values.get("blur_radius"), defaults["blur_radius"]))
    effect.setOffset(float(values.get("offset_x", defaults["offset_x"])),
                     float(values.get("offset_y", defaults["offset_y"])))
    effect.setColor(color)
    return effect

def apply_sign_shadow(item, sign_index, settings=None):
    """Attach the shared sign shadow while respecting Qt effect ownership."""
    effect = create_sign_shadow(sign_index, settings)
    if effect is not None:
        item.setGraphicsEffect(effect)
        del effect
    return item
