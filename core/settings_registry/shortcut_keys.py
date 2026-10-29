# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The key combinations ``ai.capture_hotkey`` may hold (validators.shortcut).

The stored form is what ``apps/ai_capture/entry_points.set_hotkey`` writes:
``QKeySequence.toString(PortableText)`` of ONE combination, recorded by the
editor (``QKeySequenceEdit``). Modifiers come in Qt's fixed order, each at
most once, Ctrl, Alt or Meta among them; the key is one of Qt's named keys
(media and volume keys included) or one BMP character in the form Qt stores
it (W12-R1: exactly the characters the editor writes, uncased lowercase such
as U+0138 and Qt-only upper case such as U+A7DC included), except U+0130,
which Qt reads back as no key (refused here and in set_hotkey alike).
Ctrl+emoji is refused (td-ieso2). Qt-free; checked against the installed Qt
both ways by test/test_settings_registry_w12_hotkey.py.
"""
from __future__ import annotations

from typing import Any

MODIFIER_ORDER = ("Meta", "Ctrl", "Alt", "Shift", "Num")
NEEDED_MODIFIERS = frozenset({"Meta", "Ctrl", "Alt"})

# {QKeySequence(k).toString(PortableText) for k in Qt.Key} where that text is
# longer than one character, minus the modifier names (a modifier alone is
# not a key). Generated with PySide6 6.x.
NAMED_KEYS = frozenset((
    "Add Favorite", "Adjust Brightness", "Adjust contrast", "Application Left",
    "Application Right", "Audio Cycle Track", "Audio Random Play", "Audio Repeat",
    "Away", "Back", "Back Forward", "Backspace", "Backtab", "Bass Boost",
    "Bass Down", "Bass Up", "Battery", "Blue", "Bluetooth", "Book", "Browser",
    "CD", "Calculator", "Calendar", "Call", "Camera Focus", "Camera Shutter",
    "Cancel", "CapsLock", "Channel Down", "Channel Up", "Clear", "Clear Grab",
    "Close", "Code input", "Community", "Context1", "Context2", "Context3",
    "Context4", "Copy", "Cut", "DOS", "Del", "Display", "Documents", "Down",
    "Eisu Shift", "Eisu toggle", "Eject", "End", "Enter", "Esc", "Execute",
    "Exit", *(f"F{i}" for i in range(1, 36)), "Favorites", "Finance", "Find",
    "Flip", "Forward", "Game", "Go", "Green", "Guide", "Hangul", "Hangul Banja",
    "Hangul End", "Hangul Hanja", "Hangul Jamo", "Hangul Jeonja",
    "Hangul PostHanja", "Hangul PreHanja", "Hangul Romaja", "Hangul Special",
    "Hangul Start", "Hangup", "Hankaku", "Help", "Henkan", "Hibernate",
    "Hiragana", "Hiragana Katakana", "History", "Home", "Home Office",
    "Home Page", "Hot Links", "Info", "Ins", "Kana Lock", "Kana Shift", "Kanji",
    "Katakana", "Keyboard", "Keyboard Brightness Down", "Keyboard Brightness Up",
    "Keyboard Light On/Off", "Keyboard Menu", "Last Number Redial",
    *(f"Launch ({c})" for c in "0123456789ABCDEFGH"), "Launch Mail",
    "Launch Media", "Left", "LightBulb", "Logoff", "Mail Forward", "Market",
    "Massyo", "Media Fast Forward", "Media Next", "Media Pause", "Media Play",
    "Media Previous", "Media Record", "Media Rewind", "Media Stop", "Meeting",
    "Memo", "Menu", "Menu PB", "Messenger", "Microphone Mute",
    "Microphone Volume Down", "Microphone Volume Up", "Monitor Brightness Down",
    "Monitor Brightness Up", "Muhenkan", "Multiple Candidate", "Music",
    "My Sites", "New", "News", "No", "NumLock", "Open", "Open URL", "Option",
    "Paste", "Pause", "PgDown", "PgUp", "Phone", "Pictures", "Play",
    "Power Down", "Power Off", "Previous Candidate", "Print", "Printer", "Red",
    "Redo", "Refresh", "Reload", "Reply", "Return", "Right", "Romaji",
    "Rotate Windows", "Rotation KB", "Rotation PB", "Save", "Screensaver",
    "ScrollLock", "Search", "Select", "Send", "Settings", "Shop", "Sleep",
    "Space", "Spellchecker", "Split Screen", "Spreadsheet", "Standby", "Stop",
    "Subtitle", "Support", "Suspend", "SysReq", "Tab", "Task Panel", "Terminal",
    "Time", "To-do list", "Toggle Call/Hangup", "Toggle Media Play/Pause",
    "Tools", "Top Menu", "Touchpad Off", "Touchpad On", "Touchpad Toggle",
    "Touroku", "Travel", "Treble Down", "Treble Up", "Ultra Wide Band", "Undo",
    "Up", "Video", "View", "Voice Dial", "Volume Down", "Volume Mute",
    "Volume Up", "WWW", "Wake Up", "WebCam", "Wireless", "Word Processor",
    "XFer", "Yellow", "Yes", "Zenkaku", "Zenkaku Hankaku", "Zoom", "Zoom In",
    "Zoom Out", "iTouch"))


# Lowercase letters whose upper case is in Qt's Unicode table (16.0) and not
# in Python's (15.0): Qt stores the upper case, never these.
QT_ONLY_UPPER_CASE = frozenset("\u019b\u0264\u1c8a\ua7cd\ua7db")
# Stored by Qt's editor, read back as no key (would never fire).
QT_READS_AS_NO_KEY = frozenset("\u0130")


def is_char_key(token: str) -> bool:
    """One BMP character in the form Qt stores it: not a space ("Space" is
    named), not a C0 control, not a surrogate, and its own upper case (Qt
    stores "S", never "s"; "ß", whose upper case is two letters, and letters
    with no case stay as they are). U+0130 is refused: Qt reads it back as
    no key."""
    if len(token) != 1 or not 0x21 <= ord(token) <= 0xFFFF:
        return False
    if 0xD800 <= ord(token) <= 0xDFFF or token in QT_ONLY_UPPER_CASE | QT_READS_AS_NO_KEY:
        return False
    upper = token.upper()
    return len(upper) != 1 or upper == token


def is_shortcut(value: Any) -> bool:
    """``validators.shortcut``: the whole stored text."""
    if not isinstance(value, str):
        return False
    rest, used = value, []
    for mod in MODIFIER_ORDER:
        if rest.startswith(mod + "+") and len(rest) > len(mod) + 1:
            used.append(mod)
            rest = rest[len(mod) + 1:]
    return bool(NEEDED_MODIFIERS.intersection(used)) and (
        rest in NAMED_KEYS or is_char_key(rest))
