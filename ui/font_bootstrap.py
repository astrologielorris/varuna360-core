"""Register the bundled Inter font family at application startup.

The UI asks for ``QFont("Inter")`` in ~15 places, but nothing ever registered
the family with Qt, so on any machine without Inter installed system-wide (every
frozen build, and this dev box per ``fc-list``) Qt silently substituted a default
face. Bundling the font is only half the fix: a bundled ``.ttf`` is inert until
``QFontDatabase.addApplicationFont`` loads it into the running application.

``register_bundled_fonts`` is called once, right after the ``QApplication`` is
created (see ``apps/core_gui_qt.main``). It is silent and total-failure-safe: if
the font directory is absent (an edition that did not bundle it, or a stripped
tree) it registers nothing and the app renders exactly as before. It never
raises, because a font nicety must not be able to stop the app from starting.

``fonts/Inter`` and ``fonts/NotoSansSymbols2`` are scanned.
``fonts/San-Francisco-Pro-Fonts`` is Apple licensed and must never be registered
or shipped.
"""
from __future__ import annotations

from pathlib import Path

_FONT_SUFFIXES = {".ttf", ".ttc", ".otf"}

#: Every bundled family directory, relative to the project root.
#:
#: NotoSansSymbols2 carries the 64 hexagram glyphs (U+4DC0..U+4DFF) the Human Design
#: BodyGraph offers instead of gate numbers. It is registered here rather than loaded on
#: demand because a font must be in the database BEFORE the first widget asks for it;
#: registering it lazily gives the first paint a substituted face.
_BUNDLED_DIRS = ("Inter", "NotoSansSymbols2")

# Directories already registered this process, with their family result.
# Multiple callers now exist (the __main__ boot, create_action_bar, test
# harnesses) and each addApplicationFont issues a NEW id even for a file
# already loaded — functionally harmless but resource waste (Sol M4 r5
# MINOR). One registration per resolved directory per process.
_REGISTERED_DIRS: dict[str, list[str]] = {}


def register_bundled_fonts(project_root) -> list[str]:
    """Load every bundled Inter face into the running QApplication.

    Returns the sorted list of font families that were added (empty if the
    directory is absent or nothing loaded). Never raises. Idempotent per
    resolved directory: repeat calls return the first call's result.
    """
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return []

    try:
        all_families: set[str] = set()
        for name in _BUNDLED_DIRS:
            font_dir = Path(project_root) / "fonts" / name
            _key = str(font_dir.resolve())
            if _key in _REGISTERED_DIRS:
                all_families.update(_REGISTERED_DIRS[_key])
                continue
            if not font_dir.is_dir():
                continue           # an edition that did not bundle this family

            families: set[str] = set()
            for path in sorted(font_dir.iterdir()):
                if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
                    continue
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id != -1:
                    families.update(QFontDatabase.applicationFontFamilies(font_id))
            if families:           # cache SUCCESS only — an all-failed pass
                _REGISTERED_DIRS[_key] = sorted(families)   # may retry later
            all_families.update(families)
        return sorted(all_families)
    except Exception:
        # A font failing to load is never worth crashing the boot for.
        return []


# ---------------------------------------------------------------------------
# Action bar variable-weight face (SPEC-BAR-001)
# ---------------------------------------------------------------------------
# The Vibrancy Segmented bar is designed at Inter fractional weights 530 / 560
# / 590 — between the static Regular (400) and Bold (700) faces.  Those
# in-between weights only exist in ``fonts/Inter/InterVariable.ttf``, which
# ``register_bundled_fonts`` above registers under the DISTINCT family name
# "Inter Variable" (Qt keeps it separate from the static "Inter" family, so
# ``QFont("Inter")`` callers everywhere else are unaffected).  Weight snapping
# to 400/700 fails the bar's fidelity gate, so the fallback below is a
# last-resort degradation, not an acceptable steady state.

_INTER_VARIABLE_FAMILY = "Inter Variable"


def bar_font(pixel_size: float, weight: float, italic: bool = False):
    """A QFont on the Inter Variable face at a fractional ``wght``.

    ``pixel_size`` is LOGICAL PIXELS (``setPixelSize``), matching the mockup's
    px-based type scale — the bar's sizing contract is pixel-true (INV-3), so
    no point-size conversion happens here or anywhere downstream.

    Falls back to the static "Inter" family with the nearest integer weight if
    the variable face is unavailable (stripped tree / failed registration);
    callers can detect that via ``font.family()``.
    """
    from PySide6.QtGui import QFont, QFontDatabase

    if _INTER_VARIABLE_FAMILY in QFontDatabase.families():
        font = QFont(_INTER_VARIABLE_FAMILY)
        # setVariableAxis drives the real ``wght`` axis: 530 renders as 530,
        # not snapped to a named instance.  setWeight is ALSO set so that any
        # style-resolution path that ignores axes still lands nearby.
        font.setVariableAxis(QFont.Tag("wght"), float(weight))
        font.setWeight(QFont.Weight(int(round(weight))))
    else:
        font = QFont("Inter")
        font.setWeight(QFont.Weight(int(round(weight))))
    font.setPixelSize(int(round(pixel_size)))
    font.setItalic(italic)
    # EXPLICIT MixedCase, not the default: QPainter.setFont() resolves every
    # attribute the font leaves unset from the WIDGET's font, and the
    # qt_material theme sets `QPushButton { text-transform: uppercase }`,
    # which Qt applies as QFont::AllUppercase on the widget font. A painted
    # name then rendered "LORRIS" while QFontMetricsF (no resolve) had sized
    # the box for "Lorris" -> hard clip at the last glyph, no ellipsis
    # (reported repeatedly; reproduced 2026-08-25). Setting it here puts the
    # bit in the resolve mask, so measurement and paint see the same case.
    font.setCapitalization(QFont.Capitalization.MixedCase)
    return font


# ---------------------------------------------------------------------------
# Human Design symbol stack (SPEC-HD-001)
# ---------------------------------------------------------------------------
# The BodyGraph prints two sets of glyphs that the UI face does not carry: the
# fourteen planetary bodies in the two activation columns, and the 64 hexagrams
# the gate labels can switch to.
#
# NO SINGLE BUNDLED FONT COVERS BOTH, and the difference is not marginal.
# Measured on the shipped faces:
#
#     DejaVu Sans           13 of 14 bodies (no Pluto U+2BD3), all 64 hexagrams
#     Noto Sans Symbols2     1 of 14 bodies (Pluto only),      all 64 hexagrams
#
# So bundling Noto Sans Symbols 2 alone -- which is what the plan called for --
# would leave the planet columns printing thirteen tofu boxes. The glyphs need a
# family LIST, which Qt walks per character, not a family.

#: Fallback order for the fourteen planetary bodies.
HD_BODY_FAMILIES = ("Inter", "DejaVu Sans", "Noto Sans Symbols2", "FreeSerif")
#: Fallback order for the 64 hexagrams, U+4DC0..U+4DFF.
HD_HEXAGRAM_FAMILIES = ("Noto Sans Symbols2", "DejaVu Sans", "FreeSerif")


def hd_symbol_font(pixel_size: int, hexagrams: bool = False, bold: bool = False):
    """A QFont whose family list covers the BodyGraph's symbols.

    ``setFamilies`` gives Qt the whole chain: it renders each character from the
    first family that has it, so Pluto comes from Noto Sans Symbols2 while the
    other thirteen bodies come from the UI face, in one run of text.
    """
    from PySide6.QtGui import QFont

    font = QFont()
    font.setFamilies(list(HD_HEXAGRAM_FAMILIES if hexagrams else HD_BODY_FAMILIES))
    font.setPixelSize(int(pixel_size))
    font.setBold(bool(bold))
    return font
