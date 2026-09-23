"""Shared appearance and per-body colors for both SVG packs."""
import json
from apps.widgets.planet_icon_palette import clean_colors, scheme_passes
from PySide6.QtGui import QPainter
from libaditya.optional_bodies import BODY_BY_NAME

PLANET_NAMES = ('Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn',
                'Rahu', 'Ketu', 'Uranus', 'Neptune', 'Pluto')
ICON_NAMES = PLANET_NAMES + tuple(BODY_BY_NAME)
PLANET_SETTING = 'display.planet_icon_set'
COLOR_SETTING = 'display.planet_svg_colors'


def colors_from(value):
    return clean_colors(value, ICON_NAMES)


def passes_for(body):
    from managers.settings_manager import get_settings
    scheme = colors_from(get_settings().get(COLOR_SETTING, {})).get(body)
    if scheme is None and body in BODY_BY_NAME:
        from apps.widgets.planet_svg_provider import PASSES  # td-kdbb: optional body keeps the two-tone default, not flat black
        return PASSES
    return scheme_passes(scheme, body in PLANET_NAMES)


def selected_pack(body):
    from managers.settings_manager import get_settings
    from apps.widgets.planet_svg_provider import selected_additional_family
    if body in BODY_BY_NAME:
        return selected_additional_family()
    if body in PLANET_NAMES and get_settings().get(PLANET_SETTING, 'artistic') == 'simple_svg':
        return 'simple-planets'
    return None

def appearance_signature():
    from apps.widgets.planet_svg_provider import pack_revision_signature, selected_additional_family
    from managers.settings_manager import get_settings
    settings = get_settings()
    planet_family = settings.get(PLANET_SETTING, 'artistic')
    return (planet_family, settings.get('display.additional_body_icon_set', 'current'),
            json.dumps(colors_from(settings.get(COLOR_SETTING, {})), sort_keys=True),
            pack_revision_signature('simple-planets' if planet_family == 'simple_svg' else None),
            pack_revision_signature(selected_additional_family()))


def paint_svg(painter, rect, body):
    """Paint the chosen SVG directly, returning False for the existing fallback."""
    from apps.widgets.planet_svg_provider import renderers_for, paint_renderers
    renderers = renderers_for(selected_pack(body), body, passes_for(body))
    if not renderers:
        return False
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_renderers(painter, rect, renderers)
    painter.restore()
    return True


def paint_item(item, painter, option, widget):
    from apps.widgets.additional_body_glyphs import glyph_path, _VectorPaint
    if item.planet_name in BODY_BY_NAME:
        from apps.widgets.planet_svg_provider import paint_vector_icon
        paint_vector_icon(painter, item.boundingRect(), item.planet_name,
                          selected_pack(item.planet_name), glyph_path)
        return True
    if not paint_svg(painter, item.boundingRect(), item.planet_name):
        super(_VectorPaint, item).paint(painter, option, widget)


def refresh_icon_views():
    """Repaint live charts/popups after Apply, including secondary tool windows."""
    from PySide6.QtWidgets import QApplication, QGraphicsView
    for widget in QApplication.allWidgets():
        if isinstance(widget, QGraphicsView):
            refresh_scene(widget.scene() if callable(widget.scene) else widget.scene)
            widget.viewport().update()
        elif widget.__class__.__name__ == 'PlanetInfoDialog' and hasattr(widget, 'rotating_planet'):
            widget._load_current_image()
        elif widget.__class__.__name__ in ('_HouseBarWidget', 'CardsOfTruthView'):
            widget.update()


def recolor_source(data, color, width_scale, outline=0):
    """Recolor both strokes and fills; optional casing outlines filled silhouettes."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(data)
    for element in root.iter():
        for name in ('fill', 'stroke'):
            if element.get(name, 'none') != 'none':
                element.set(name, color)
        if 'stroke-width' in element.attrib:
            element.set('stroke-width', f"{float(element.get('stroke-width')) * width_scale:g}")
        elif outline and element.get('fill', 'none') != 'none':
            element.set('stroke', color)
            element.set('stroke-width', str(outline))
            element.set('stroke-linejoin', 'round')
    return ET.tostring(root)


def pass_arguments(entry):
    return entry[0], entry[1] / 5.0, entry[2] if len(entry) > 2 else 0


class SVGEffects:
    """Avoid QGraphicsEffect's raster intermediate for selected vector symbols."""
    def setGraphicsEffect(self, effect):
        if effect is not None:
            effect.setEnabled(not bool(selected_pack(getattr(self, 'planet_name', None))))
        super().setGraphicsEffect(effect)


def refresh_scene(scene):
    if scene is None:
        return
    for item in scene.items():
        effect = item.graphicsEffect()
        if effect and getattr(item, 'planet_name', None) in ICON_NAMES:
            effect.setEnabled(not bool(selected_pack(item.planet_name)))
        item.update()
