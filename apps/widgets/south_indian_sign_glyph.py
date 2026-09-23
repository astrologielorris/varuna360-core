"""Sign-accompaniment icon chooser for the South Indian cells — honours
``display.sign_display`` on EVERY finish (wood and standard).

    names  -> no accompaniment icon (the sign-name text stands alone)
    zodiac -> the zodiac symbol artwork (SignIconItem)
    josh   -> the Aditya division glyph: wood finishes CARVE it
              (south_indian_material.glyph_svg_passes); the standard finish INKS
              it flat with the same wood-free renderer the Wheel and North Indian
              chart use (aditya_glyph_render.glyph_svg), in the active theme's
              single on-surface foreground so all twelve glyphs keep one
              coherent light/dark polarity — the glyph floats directly on the
              coloured cell, not on a pill.

Extracted into its own module (td-iaqm.5 CP6) rather than grown inside
south_indian_cells / _material / _items: those three sit exactly on their
SI-architecture line ceilings, so a new module (its own budget) is the sanctioned
way to add the standard-finish josh path without raising a ceiling. See docs CP6.
"""
from apps.widgets.aditya_glyph_render import glyph_svg
from apps.widgets.chart_glyph_theme import theme_glyph_ink
from apps.widgets.south_indian_geometry import SIGN_ICON_SIZE
from apps.widgets.south_indian_items import SignIconItem
from apps.widgets.south_indian_material import JoshGlyphItem, glyph_svg_passes
from apps.widgets.sign_shadow import apply_sign_shadow
from ui.qt_theme import get_ui_saturation


def accompaniment_item(style, sign_index, signals):
    """The sign-accompaniment QGraphicsItem for a cell, or None for names mode.
    Honours display.sign_display identically on the wood and standard finishes."""
    mode = style.sign_display
    if mode == 'names':
        return None
    if mode in ('josh', 'josh_only'):
        if style.wood:
            passes = glyph_svg_passes(style.finish, sign_index, get_ui_saturation())
        else:
            ink = theme_glyph_ink()
            data = glyph_svg(sign_index, ink)
            passes = ((data, 0, 1.0),) if data else None
        if not passes:
            return None
        item = JoshGlyphItem(
            passes, 80, sign_index, style.sign_variation(sign_index), signals.sign)
        return apply_sign_shadow(item, sign_index)
    pixmap = style.sign_icon(sign_index, SIGN_ICON_SIZE)
    if not pixmap:
        return None
    item = SignIconItem(pixmap, sign_index, style.sign_variation(sign_index), signals.sign)
    return apply_sign_shadow(item, sign_index)
