# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What each ``display.sign_display`` mode draws, and the simple vector symbols.

Modes (allowlist: ui.south_indian_finishes.SIGN_DISPLAYS):
    names        sign names only
    zodiac       sign names + the painted zodiac icons (img/sign/*.webp)
    josh         sign names + Josh's Aditya glyphs (img/aditya_glyph/)
    josh_only    Josh glyphs, no sign names
    vector       sign names + simple vector zodiac symbols (img/sign/vector/)
    vector_only  simple vector symbols, no sign names

The vector symbols are indexed like the Josh glyphs: division #1 = Aries = Dhata
in every zodiac system (SPEC-ZOD-001). They keep their own element colours.
"""
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from ui.sign_glyph_layers import ink_all

ET.register_namespace('', 'http://www.w3.org/2000/svg')  # keep a plain <svg> root on rewrite
VECTOR_DIR = Path(__file__).resolve().parents[1] / 'img' / 'sign' / 'vector'
VECTOR_FILES = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
                "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")


def glyph_family(mode):
    """'josh' or 'vector' when the mode draws an SVG glyph, else None."""
    if mode in ("josh", "josh_only"):
        return "josh"
    if mode in ("vector", "vector_only"):
        return "vector"
    return None


def hides_sign_names(mode):
    """The glyph-only modes suppress the sign-name text."""
    return mode in ("josh_only", "vector_only")


@lru_cache(maxsize=64)
def vector_svg(index, ink=None):
    """Vector symbol #index as SVG bytes. By default in its own element colour
    (part of what makes it readable); ``ink`` recolours the stroke for views
    whose ground is itself element-coloured (a Pro map ring), where the
    element colour would vanish. None if out of range, missing or malformed,
    so callers skip it like a missing Josh glyph."""
    if not 0 <= index < len(VECTOR_FILES):
        print(f'[VECTOR SIGN] Sign index {index} out of range 0..11')
        return None
    path = VECTOR_DIR / (VECTOR_FILES[index] + '.svg')
    try:
        data = path.read_bytes()
        root = ET.fromstring(data)
    except (OSError, ET.ParseError) as exc:
        print(f'[VECTOR SIGN] Missing or invalid symbol {path}: {exc}')
        return None
    if ink is None:
        return data
    ink_all(root, ink)  # strokes and fills alike (filled Capricorn)
    return ET.tostring(root)
