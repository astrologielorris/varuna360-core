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


def _use_bundled_certificates():
    """macOS: point Python's ssl at certifi's certificate bundle.

    The python.org Python a Mac build is made from has no access to the macOS
    keychain's certificates, so every urllib HTTPS call in the packaged app
    failed with CERTIFICATE_VERIFY_FAILED (map tiles outside the shipped cache,
    elevation, IP location, the voice model download; seen in the 6.0.0 VM
    build, 2026-10-26). requests already uses certifi; this covers the rest,
    for this process and the children it starts. A user's own SSL_CERT_FILE
    is kept."""
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:
        pass


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


def load_edition(argv=None):
    """Load the edition's extensions: in the Pro edition, import the Pro
    package, which registers its features with core/edition_hooks.py (the
    Pro main window, the extended South Indian host, the AI terminal, the Pro CHTK writer,
    the legacy API-key aliases). Core code never does this (lint-imports
    no-pro-imports, test/test_core_no_pro_import.py); this launcher sits
    outside the Core packages (.importlinter root_packages), so it is the
    place. Lite (a Lite build, or -l / --lite) imports nothing. True when the
    Pro package was loaded. An ImportError means no Pro; any other error
    propagates. Both modes call it first (the GUI and --tool); the GUI module
    run as a script (apps/core_gui_qt.py) hands over to this launcher."""
    from core import edition
    chosen = edition.current_edition(sys.argv if argv is None else argv)
    _remember_edition(chosen)       # lite, pro, or personal (SPEC-EDN-002 §3.4)
    if chosen == edition.LITE:
        return False
    try:
        pass  # Pro import stripped for Lite distribution
    except ImportError:
        _remember_edition(edition.LITE)
        return False
    return True


def _remember_edition(name):
    """Record the edition this launcher chose, before any extension loads:
    ``core.edition.current_edition()`` follows it instead of re-reading
    sys.argv, which core_gui_qt strips of --lite (SPEC-EDN-002 §4.2b)."""
    from core import edition, edition_hooks
    edition_hooks.register(edition.PROCESS_EDITION, lambda: name)


def _run_tool_mode(argv):
    """``--tool``: headless capability run (AIC plan 2 W8). Runs before any Qt
    import; errors go to stderr and the exit code, never the crash dialog."""
    # Relative paths are the caller's, not the bundle's: make them absolute
    # before setup_environment() changes the working directory.
    path_flags = ("--chart", "--input", "--out")
    fixed = list(argv)
    for i, arg in enumerate(fixed):
        if arg in path_flags and i + 1 < len(fixed):
            fixed[i + 1] = os.path.abspath(fixed[i + 1])
        for flag in path_flags:
            if arg.startswith(flag + "="):
                fixed[i] = flag + "=" + os.path.abspath(arg[len(flag) + 1:])
    features = _ai_door(fixed)
    if features is None:
        return 2
    if not features.recover_std_streams():     # piped: the handles; else the terminal
        _attach_parent_console()
    fix_console_encoding()
    setup_environment()
    load_edition(fixed)
    from core.capabilities.cli import main as tool_main
    return tool_main(fixed)


def _run_task_mcp_mode(argv):
    """``--task-mcp --task-dir <folder> [--blind]`` (or ``--blind-task <anonymous
    folder> --blind``): one AI task's tools over
    stdio MCP (SPEC-AIC-001 §4.5, plan 4), what Codex starts for a task
    thread. Headless like --tool; stdout is the MCP wire."""
    fixed = list(argv)
    for i, arg in enumerate(fixed):
        for flag in ("--task-dir", "--blind-task"):
            if arg == flag and i + 1 < len(fixed):
                fixed[i + 1] = os.path.abspath(fixed[i + 1])
            elif arg.startswith(flag + "="):
                fixed[i] = flag + "=" + os.path.abspath(arg[len(flag) + 1:])
    features = _ai_door(fixed)
    if features is None:
        return 2
    fix_console_encoding()
    setup_environment()
    load_edition(fixed)
    return features.task_mcp_main(fixed)


def _run_mcp_mode(argv):
    """``--mcp [--lite]``: Varuna360 as a local MCP server for any AI app
    (SPEC-LMCP-001): the desktop profile over stdio, started by Claude
    Desktop, Claude Code, Codex... The wire is taken FIRST (INV-5): before the
    environment setup, the edition or any app import, so nothing printed can
    reach it. ``--mcp-bundle OUT`` writes the Claude Desktop bundle,
    ``--mcp-config`` prints the client config entries (no wire). Lite has no
    MCP server (SPEC-EDN-002 INV-2): it answers on stderr and exits."""
    features = _ai_door(argv)
    if features is None:
        return 2
    if "--mcp-bundle" in argv or "--mcp-config" in argv:
        fix_console_encoding()
        setup_environment()
        load_edition(argv)
        return features.mcp_install_main(argv)
    mcp_wire = features.mcp_wire()
    try:
        wire = mcp_wire.claim()
    except mcp_wire.NoWire as exc:
        print(str(exc), file=sys.stderr)
        return 2
    setup_environment()
    load_edition(argv)
    return features.mcp_main(argv, wire)


def _ai_door(argv):
    """``apps.ai_features`` for an AI mode (``--mcp``, ``--mcp-render``,
    ``--task-mcp``, ``--tool``, ``--run-cli``), or None, with the Pro message
    on stderr, in Lite: it ships no AI file and no command (SPEC-EDN-002
    INV-2, D-13). Decided from the arguments alone: nothing is printed to
    stdout, which is the MCP wire. Puts the project root on sys.path first
    (a launcher run through runpy from another folder, review 2026-10-29 F1);
    no chdir yet, setup_environment does that."""
    root = str(get_project_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from core import edition
    from core.edition_features import ai_features
    features = ai_features(edition.current_edition(argv))
    if features is None:
        from core.pro_marketing import PRO_AI_REQUIRED
        print(PRO_AI_REQUIRED, file=sys.stderr)
    return features


def _run_mcp_render_mode(argv):
    """``--mcp-render [--lite] -- CHART OUT.png [SIZE]``: the desktop MCP
    server's chart picture, an offscreen Qt child of ``--mcp`` (Pro)."""
    features = _ai_door(argv)
    if features is None:
        return 2
    features.recover_std_streams()
    fix_console_encoding()
    setup_environment()
    load_edition(argv)
    return features.mcp_render_main(argv)


def _run_cli_mode(argv):
    """``--run-cli <module> [--lite] -- <args>``: one read-only calculation
    command of the AI task's "All tools" catalogue (SPEC-AIC-001 §4.5,
    core/ai_capture/cli_tools.py), run as ``__main__``. Headless like --tool."""
    features = _ai_door(argv)
    if features is None:
        return 2
    features.recover_std_streams()
    fix_console_encoding()
    setup_environment()
    load_edition(argv)
    return features.run_cli_mode(argv)


def _attach_parent_console():
    """Windows windowed exe: reuse the calling terminal when there is one.
    A redirected stdout (file or pipe) is already a real handle: keep it."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            if sys.stdout is None or getattr(sys.stdout, "name", "") == os.devnull:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            if sys.stderr is None or getattr(sys.stderr, "name", "") == os.devnull:
                sys.stderr = open("CONOUT$", "w", encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    # A frozen build starts its child processes (the Find Chart background
    # compute, core/chart_search/compute_process.py) by running itself again:
    # freeze_support runs the child's job and exits there. A no-op otherwise.
    import multiprocessing

    multiprocessing.freeze_support()
    _use_bundled_certificates()
    # The screen recorder's ffmpeg trampoline (core/recorder/launcher.py):
    # a packaged build is its own Python, so the recorder starts the app as
    # "-I -c <trampoline> ...". Only an exact known trampoline is taken over;
    # anything else starts normally.
    if sys.argv[1:3] == ["-I", "-c"]:
        from core.recorder.launcher import is_trampoline, run_bundled_trampoline
        if is_trampoline(sys.argv):
            sys.exit(run_bundled_trampoline(sys.argv))
    if "--mcp-render" in sys.argv[1:]:
        sys.exit(_run_mcp_render_mode(sys.argv[1:]))
    if any(a in ("--mcp", "--mcp-bundle", "--mcp-config") for a in sys.argv[1:]):
        sys.exit(_run_mcp_mode(sys.argv[1:]))
    if "--tool" in sys.argv[1:] or any(a.startswith("--tool=") for a in sys.argv[1:]):
        sys.exit(_run_tool_mode(sys.argv[1:]))
    if "--task-mcp" in sys.argv[1:]:
        sys.exit(_run_task_mcp_mode(sys.argv[1:]))
    if "--run-cli" in sys.argv[1:]:
        sys.exit(_run_cli_mode(sys.argv[1:]))

    fix_console_encoding()
    setup_environment()

    try:
        load_edition(sys.argv)
        from apps.core_gui_qt import main
        main()
    except SystemExit:
        raise                      # a deliberate exit is not a crash
    except BaseException as exc:   # noqa: BLE001 - last line of defence
        _report_startup_crash(exc)
        sys.exit(1)
