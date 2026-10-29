# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Is a compositing manager running on this X screen? (SPEC-REC-001 INV-6)

A compositor owns the ``_NET_WM_CM_S<screen>`` selection. Without one, a
translucent window paints black, so the overlays fall back to shaped windows.
Read with libX11 through ctypes; any failure answers False (the safe fallback).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from typing import Optional


def compositor_running(display: Optional[str] = None) -> bool:
    name = ctypes.util.find_library("X11")
    if not name:
        return False
    try:
        x = ctypes.CDLL(name)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x.XInternAtom.restype = ctypes.c_ulong
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x.XGetSelectionOwner.restype = ctypes.c_ulong
        x.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x.XOpenDisplay((display or os.environ.get("DISPLAY", "")).encode())
        if not dpy:
            return False
        try:
            screen = x.XDefaultScreen(dpy)
            atom = x.XInternAtom(dpy, f"_NET_WM_CM_S{screen}".encode(), 0)
            return bool(x.XGetSelectionOwner(dpy, atom))
        finally:
            x.XCloseDisplay(dpy)
    except (OSError, AttributeError):
        return False


def screen_size(display: Optional[str] = None):
    """(width, height) of the default X screen in pixels, or None."""
    name = ctypes.util.find_library("X11")
    if not name:
        return None
    try:
        x = ctypes.CDLL(name)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        dpy = x.XOpenDisplay((display or os.environ.get("DISPLAY", "")).encode())
        if not dpy:
            return None
        try:
            screen = x.XDefaultScreen(dpy)
            return int(x.XDisplayWidth(dpy, screen)), int(x.XDisplayHeight(dpy, screen))
        finally:
            x.XCloseDisplay(dpy)
    except (OSError, AttributeError):
        return None
