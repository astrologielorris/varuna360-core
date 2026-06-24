"""
Screenshot Capture Utility
Captures application window screenshots and saves to screenshot_debug/ folder.
"""

import os
from pathlib import Path
from datetime import datetime
from PIL import ImageGrab
import platform

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "screenshot_debug"


def ensure_screenshot_dir():
    """Create screenshot directory if it doesn't exist."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)


def get_next_screenshot_number():
    """
    Find the next available screenshot number by scanning existing files.
    Returns integer for next available number (e.g., 108 if sshot-107.jpeg exists).
    """
    ensure_screenshot_dir()

    # Find all existing sshot-*.jpeg files
    existing_files = list(SCREENSHOT_DIR.glob("sshot-*.jpeg"))

    if not existing_files:
        return 1

    # Extract numbers from filenames
    numbers = []
    for file in existing_files:
        # Extract number from "sshot-XXX.jpeg"
        name = file.stem  # Gets "sshot-XXX"
        try:
            num = int(name.split('-')[1])
            numbers.append(num)
        except (IndexError, ValueError):
            continue

    if not numbers:
        return 1

    return max(numbers) + 1


def capture_window_screenshot(root_window, show_notification=True):
    """
    Capture screenshot of the Tkinter window and save to screenshot_debug/.

    Args:
        root_window: Tkinter root window instance
        show_notification: Whether to show success notification (default: True)

    Returns:
        str: Path to saved screenshot file, or None if failed
    """
    try:
        ensure_screenshot_dir()

        # Update window to ensure geometry is current
        root_window.update_idletasks()

        # Get window position and size
        x = root_window.winfo_rootx()
        y = root_window.winfo_rooty()
        width = root_window.winfo_width()
        height = root_window.winfo_height()

        # Capture the window region
        # bbox format: (left, top, right, bottom)
        bbox = (x, y, x + width, y + height)

        # Grab screenshot
        screenshot = ImageGrab.grab(bbox=bbox)

        # Get next filename
        next_num = get_next_screenshot_number()
        filename = f"sshot-{next_num:03d}.jpeg"
        filepath = SCREENSHOT_DIR / filename

        # Save screenshot
        screenshot.save(filepath, "JPEG", quality=95)

        # Show notification if requested
        if show_notification:
            # Import here to avoid circular dependency
            from tkinter import messagebox
            messagebox.showinfo(
                "Screenshot Saved",
                f"Screenshot saved:\n{filename}\n\nLocation: screenshot_debug/"
            )

        return str(filepath)

    except Exception as e:
        # Import here to avoid circular dependency
        from tkinter import messagebox
        messagebox.showerror(
            "Screenshot Failed",
            f"Failed to capture screenshot:\n{str(e)}"
        )
        return None


def capture_screenshot_silent(root_window):
    """
    Capture screenshot without showing notification dialog.
    Useful for automated screenshots or batch captures.

    Args:
        root_window: Tkinter root window instance

    Returns:
        str: Path to saved screenshot file, or None if failed
    """
    return capture_window_screenshot(root_window, show_notification=False)
