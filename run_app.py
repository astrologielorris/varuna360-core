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


def _crash_dir():
    """Where a startup crash report goes. Mirrors core.diagnostics._bootstrap_root().

    Duplicated rather than imported: this runs when the app has FAILED to
    start, so it must not depend on anything that might be the thing that
    broke.
    """
    import platform
    system = platform.system()
    if system == "Windows":
        # Not ~/Documents/varuna360 - same folder as the data dir on NTFS.
        return Path.home() / ".varuna360" / "logs"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "varuna360" / "logs"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "varuna360" / "logs"


def _report_startup_crash(exc):
    """Make a startup failure visible. Returns the report path, or None.

    Without this the app is SILENT when it fails to start. The Windows build
    is --windowed, and this module redirects stdout/stderr to devnull above,
    so an exception during import or main() produces no window, no dialog, no
    console output and no log: the user double-clicks the icon and nothing
    whatsoever happens. That is unreportable, and an unreportable failure is
    one nobody can help with.

    Every step is individually guarded. Crash reporting that raises while
    reporting a crash is worse than none.
    """
    import traceback
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    path = None
    try:
        from datetime import datetime
        crash_dir = _crash_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        path = crash_dir / "startup_crash.txt"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"Varuna360 failed to start at "
                         f"{datetime.now().isoformat(timespec='seconds')}\n")
            handle.write(f"python {sys.version}\n")
            handle.write(f"frozen  {getattr(sys, 'frozen', False)}\n\n")
            handle.write(text)
    except Exception:
        pass

    if _has_interactive_display():
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            QApplication.instance() or QApplication(sys.argv)
            where = f"\n\nDetails were written to:\n{path}" if path else ""
            QMessageBox.critical(
                None, "Varuna360 could not start",
                "Varuna360 could not start.\n\n"
                f"{type(exc).__name__}: {exc}{where}\n\n"
                "Please send that file to support so this can be fixed.",
            )
        except Exception:
            # Qt itself may be what failed. The file is the real deliverable.
            pass

    return path


def _has_interactive_display():
    """True when there is a human who can dismiss a modal dialog.

    QMessageBox.critical blocks until someone clicks OK. That is exactly what
    is wanted when a user double-clicks the icon and nothing happens - and it
    is a permanent hang anywhere else: a headless CI run, an SSH session, a
    packaging smoke test, or any script that launches the app. The crash FILE
    is written either way, so skipping the dialog costs nothing.
    """
    import platform
    if os.environ.get("QT_QPA_PLATFORM", "") in ("offscreen", "minimal"):
        return False
    if platform.system() in ("Windows", "Darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


if __name__ == "__main__":
    fix_console_encoding()
    setup_environment()

    try:
        from apps.core_gui_qt import main
        main()
    except SystemExit:
        raise                      # a deliberate exit is not a crash
    except BaseException as exc:   # noqa: BLE001 - last line of defence
        _report_startup_crash(exc)
        sys.exit(1)
