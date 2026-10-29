# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The capturable desktop and the compositor question, per platform
(SPEC-REC-001 §4.2, INV-6, D-20).

Linux: the X root window, from (0, 0). Windows: the virtual screen, whose
top-left is negative when a monitor sits left of or above the main one;
Windows 8 and later always composite (DWM), so overlays are translucent.
macOS (D-21): every display in the native space (CoreGraphics), top-left
negative too when a display sits left of or above the main one; the window
server always composites.
"""
from __future__ import annotations

from typing import Optional

from core.recorder import macos, x11
from core.recorder.region import Rect
from core.recorder.windows import IS_WINDOWS, virtual_screen


def capture_root(display: Optional[str] = None) -> Optional[Rect]:
    """The whole capturable desktop in capture pixels, or None if unknown."""
    if IS_WINDOWS:
        return virtual_screen()
    if macos.IS_MACOS:
        return macos.capture_root()
    size = x11.screen_size(display)
    return Rect(0, 0, size[0], size[1]) if size else None


def compositor_running(display: Optional[str] = None) -> bool:
    return True if IS_WINDOWS or macos.IS_MACOS else x11.compositor_running(display)
