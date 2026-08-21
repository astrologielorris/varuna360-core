"""
Debug Utility Module
====================
Provides centralized debug logging that can be enabled/disabled via command line.

Usage:
    python chart_app.py          # Normal mode (quiet)
    python chart_app.py --debug  # Debug mode (verbose)
    python chart_app.py -d       # Debug mode (short flag)

In code:
    from utils.debug import debug_print, DEBUG, set_debug_mode

    debug_print("[INIT] Starting application...")  # Only prints if DEBUG is True
"""

import sys

# Global debug flag - set via command line
DEBUG = False


def set_debug_mode(enabled: bool):
    """Enable or disable debug mode globally."""
    global DEBUG
    DEBUG = enabled


def init_from_args():
    """Initialize debug mode from command line arguments."""
    global DEBUG
    if '--debug' in sys.argv or '-d' in sys.argv:
        DEBUG = True
        # Remove the debug flag from argv so it doesn't interfere with other args
        sys.argv = [arg for arg in sys.argv if arg not in ('--debug', '-d')]
        print("[DEBUG MODE ENABLED] Verbose logging active")
    return DEBUG


def debug_print(*args, **kwargs):
    """Print only if DEBUG mode is enabled."""
    if DEBUG:
        print(*args, **kwargs)


def info_print(*args, **kwargs):
    """Print important info messages (shown even in non-debug mode)."""
    # These are errors or critical info that user should always see
    print(*args, **kwargs)


def warning_print(*args, **kwargs):
    """Print warning messages (shown even in non-debug mode)."""
    print(*args, **kwargs)


# Initialize from command line arguments when module is imported
init_from_args()
