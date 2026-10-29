"""Solid/two-tone SVG palettes; the check is the settings registry's (SPEC-SET-003)."""
from core.settings_registry.validators import color_scheme, rgb_color

PRESETS = (
    ('Black frame / white inside', '#000000', '#ffffff'),
    ('White frame / black inside', '#ffffff', '#000000'),
    ('Navy frame / ivory inside', '#14243b', '#fff6df'),
    ('Ivory frame / navy inside', '#fff6df', '#14243b'),
    ('Charcoal frame / cyan inside', '#202428', '#82efff'),
)


def rgb(value):
    return rgb_color(value)


def clean_scheme(value):
    if not color_scheme(value):
        return None
    if isinstance(value, str):
        return value.lower()
    return {key: value[key].lower() for key in ('outer', 'inner')}


def clean_colors(value, names):
    if not isinstance(value, dict):
        return {}
    return {name: scheme for name, value in value.items()
            if name in names and (scheme := clean_scheme(value)) is not None}


def scheme_passes(scheme, simple=False):
    scheme = clean_scheme(scheme) or '#000000'
    if isinstance(scheme, str):
        return ((scheme, 6.5 if simple else 5.0),)
    if simple:
        return ((scheme['outer'], 10, 3.5), (scheme['inner'], 6.5, 0))
    return ((scheme['outer'], 7, 2), (scheme['inner'], 3.5, 0))
