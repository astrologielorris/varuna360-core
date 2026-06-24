#!/usr/bin/env python3
"""
Launcher for Varuna360 - PySide6/Qt6

Works both for development and PyInstaller frozen builds.
PyInstaller uses this as the entry point (--onedir mode).
"""
import sys
import os
import io
from pathlib import Path

# In --windowed mode (no console), PyInstaller sets sys.stdout/stderr to None.
# Any print() or library import that writes to stderr crashes immediately.
# Redirect to devnull before anything else runs.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')


def fix_console_encoding():
    """Fix Unicode encoding for frozen builds (PyInstaller console).

    The Windows console defaults to cp1252 which cannot encode emoji/unicode
    characters used in print statements. Force UTF-8 with error replacement.
    """
    if getattr(sys, 'frozen', False):
        # In frozen mode, stdout/stderr may use cp1252 encoding
        # Wrap them to handle Unicode gracefully
        if sys.stdout and hasattr(sys.stdout, 'encoding'):
            if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, encoding='utf-8', errors='replace',
                    line_buffering=True
                )
        if sys.stderr and hasattr(sys.stderr, 'encoding'):
            if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer, encoding='utf-8', errors='replace',
                    line_buffering=True
                )


def get_project_root():
    """Return project root, works in both dev and frozen (PyInstaller) modes.

    In dev mode:
        run_app.py is at project root, so __file__.parent is the root.

    In frozen --onedir mode (PyInstaller 6.x):
        sys._MEIPASS = dist/Varuna360/_internal/
        The exe is at dist/Varuna360/Varuna360.exe
        Data added via --add-data lands inside _internal/.
        User data (profiles, chtk_files) is next to the exe.
    """
    if getattr(sys, 'frozen', False):
        # Frozen: _MEIPASS is where bundled data lives
        return Path(sys._MEIPASS)
    else:
        # Development: run_app.py sits at project root
        return Path(__file__).parent.absolute()


def setup_environment():
    """Set up paths and working directory."""
    root = get_project_root()

    # Set working directory to project root
    os.chdir(root)

    # Ensure project root is on sys.path for imports
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    return root


if __name__ == "__main__":
    fix_console_encoding()
    setup_environment()

    from apps.core_gui_qt import main
    main()
