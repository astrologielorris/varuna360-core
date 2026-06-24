"""
Cross-platform path translator for Windows <-> Linux.

If the Kala chart database lives on an NTFS partition accessible from
both OSes, this module translates paths so that session files, chart
references, and settings work on either OS without manual editing.

Configure your mappings in settings.json under "path_mappings":
  [["C:/Users/YourUser/Documents", "/media/youruser/Windows/Users/YourUser/Documents"]]
"""

import os
import platform
from pathlib import Path

# Load path mappings from SettingsManager (user-configurable)
_PATH_MAPPINGS = []
try:
    from managers.settings_manager import get_settings
    _raw = get_settings().get("paths.mappings", [])
    _PATH_MAPPINGS = [(w, l) for w, l in _raw if w and l]
except Exception:
    pass  # No mappings configured — translation is a no-op


def translate_path(path_str):
    """Translate a path to the current OS format.

    On Linux: converts C:/... or C:\\... paths to /media/USER/Windows/...
    On Windows: converts /media/USER/Windows/... paths to C:/...

    Args:
        path_str: A file path string (may be None or empty).

    Returns:
        Translated path string, or the original if no translation applies.
    """
    if not path_str:
        return path_str

    # Normalize backslashes to forward slashes for consistent matching
    normalized = path_str.replace("\\", "/")

    is_linux = platform.system() != "Windows"

    if is_linux:
        # Convert Windows paths to Linux mount paths
        for win_prefix, linux_prefix in _PATH_MAPPINGS:
            if normalized.startswith(win_prefix) or normalized.lower().startswith(win_prefix.lower()):
                translated = linux_prefix + normalized[len(win_prefix):]
                return translated
    else:
        # Convert Linux mount paths to Windows paths
        for win_prefix, linux_prefix in _PATH_MAPPINGS:
            if normalized.startswith(linux_prefix):
                translated = win_prefix + normalized[len(linux_prefix):]
                return translated

    # No mapping matched -- return with normalized separators
    if is_linux:
        return normalized  # Forward slashes on Linux
    return path_str  # Keep original on Windows


def translate_folder_list(folders):
    """Translate a list of folder path strings to the current OS.

    Args:
        folders: List of path strings.

    Returns:
        List of translated path strings (empty strings preserved).
    """
    return [translate_path(f) if f else f for f in folders]


def path_exists_or_translate(path_str):
    """Try the path as-is first, then translate if it doesn't exist.

    Useful for session restore where the path might already be correct
    (same OS) or need translation (cross-OS).

    Returns:
        (translated_path, exists_bool)
    """
    if not path_str:
        return path_str, False

    # Try original first
    if os.path.exists(path_str):
        return path_str, True

    # Try translated version
    translated = translate_path(path_str)
    if translated != path_str and os.path.exists(translated):
        return translated, True

    return translated, False
