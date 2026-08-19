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

Only ``fonts/Inter`` is scanned. ``fonts/San-Francisco-Pro-Fonts`` is Apple
licensed and must never be registered or shipped.
"""
from __future__ import annotations

from pathlib import Path

_FONT_SUFFIXES = {".ttf", ".ttc", ".otf"}


def register_bundled_fonts(project_root) -> list[str]:
    """Load every bundled Inter face into the running QApplication.

    Returns the sorted list of font families that were added (empty if the
    directory is absent or nothing loaded). Never raises.
    """
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return []

    try:
        font_dir = Path(project_root) / "fonts" / "Inter"
        if not font_dir.is_dir():
            return []

        families: set[str] = set()
        for path in sorted(font_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id != -1:
                families.update(QFontDatabase.applicationFontFamilies(font_id))
        return sorted(families)
    except Exception:
        # A font failing to load is never worth crashing the boot for.
        return []
