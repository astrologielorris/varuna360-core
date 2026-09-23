"""Validated solid/two-tone SVG palettes, independent of widgets and settings."""
import re

PRESETS = (
    ('Black frame / white inside', '#000000', '#ffffff'),
    ('White frame / black inside', '#ffffff', '#000000'),
    ('Navy frame / ivory inside', '#14243b', '#fff6df'),
    ('Ivory frame / navy inside', '#fff6df', '#14243b'),
    ('Charcoal frame / cyan inside', '#202428', '#82efff'),
)


def rgb(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)


def clean_scheme(value):
    if rgb(value):
        return value.lower()
    if isinstance(value, dict) and rgb(value.get('outer')) and rgb(value.get('inner')):
        return {key: value[key].lower() for key in ('outer', 'inner')}
    return None


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
