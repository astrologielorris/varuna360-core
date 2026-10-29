# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The hub's icons (SPEC-COACH-001 §4.7). Apart from the tiles so the AI
button, which Lite keeps for its Pro message (SPEC-EDN-002 D-21), needs no
AI module."""
from __future__ import annotations


ICONS = {
    "coach": '<path d="M12 2.8l1.9 5 5 1.9-5 1.9-1.9 5-1.9-5-5-1.9 5-1.9z"/>'
             '<path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "capture": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 '
               '1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M9 12h6M12 9v6"/>',
    "library": '<path d="M5 4h4v16H5zM10 4h4v16h-4z"/><path d="M15.5 5.2l3.6-1 3.4 15.5-3.6.9z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/>',
    "blind": '<path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 '
             '12z"/><circle cx="12" cy="12" r="2.6"/><path d="M4 20L20 4"/>',
    "natal": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.5"/>'
             '<path d="M12 3.5v5M12 15.5v5M3.5 12h5M15.5 12h5"/>',
    "settings": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/>'
                '<circle cx="10" cy="17" r="2"/>',
    "connect": '<path d="M9 15l6-6"/><path d="M10.5 6.5l1.8-1.8a4 4 0 0 1 5.7 5.7l-1.8 1.8'
               'M13.5 17.5l-1.8 1.8a4 4 0 0 1-5.7-5.7l1.8-1.8"/>',
}
# The AI button's filled sparkle.
SPARKLE = ('<path d="M12 2.5l2.1 6.2 6.4 2.3-6.4 2.3L12 19.5l-2.1-6.2L3.5 11l6.4-2.3z"/>'
           '<path d="M19 16l.8 2.2 2.2.8-2.2.8L19 22l-.8-2.2-2.2-.8 2.2-.8z" opacity=".75"/>')


def icon_svg(paths: str, color: str, filled: bool = False) -> bytes:
    paint = (f'fill="{color}" stroke="none"' if filled else
             f'fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
             'stroke-linejoin="round"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {paint}>'
            f'{paths}</svg>').encode()
