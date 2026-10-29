# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Memory pane colours for the CURRENT theme (Rule 20: no hex here).

The pane is drawn in the action bar's material, so it starts from the bar's
own table (``ui.qt_theme.bar_tokens()``, the same 60 keys, both themes) and
adds the few tokens the mockup uses that the bar does not have: the hover and
pressed overlays, the glass pill gradient, CLEAR's red text and the tab row.
Read at PAINT TIME, never cached in a widget, so a theme switch, a saturation
change or a deep-dark toggle repaints with no per-widget bookkeeping.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

from ui.accent_ink import on_accent_ink
from ui.qt_theme import bar_tokens, get_theme_colors, is_light_theme


def _over(white: bool, alpha: float) -> QColor:
    c = QColor(255, 255, 255) if white else QColor(0, 0, 0)
    c.setAlphaF(alpha)
    return c


def _rgb(r: int, g: int, b: int) -> QColor:
    return QColor(r, g, b)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """``color-mix(in srgb, a (1-t), b t)`` on opaque colours."""
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


_PANE_TOKEN_CACHE = None


def pane_tokens() -> dict:
    """The bar table plus the pane's own keys (mockup :54-:130). Called from
    every chip, strip and well paintEvent: memoized on the same palette
    signature as bar_tokens (review 2026-10-23: ~120 us per call). The
    QColor values are shared; copy before mutating."""
    global _PANE_TOKEN_CACHE
    from ui.qt_theme import _bar_signature
    sig = _bar_signature()
    if _PANE_TOKEN_CACHE is None or _PANE_TOKEN_CACHE[0] != sig:
        _PANE_TOKEN_CACHE = (sig, _build_pane_tokens())
    return dict(_PANE_TOKEN_CACHE[1])


def _build_pane_tokens() -> dict:
    tok = bar_tokens()
    light = bool(is_light_theme())
    t = get_theme_colors()

    # Ink for text / ticks drawn ON the accent fill (SPEC-THM-001 §13): white
    # on a mid-tone accent, dark on a bright one (cyan, amber, orange...).
    tok["on_primary"] = QColor(on_accent_ink(tok["primary"].name(), tok["primary_text"].name()))
    tok["ov_h"] = _over(not light, .04 if light else .055)    # --ov-h
    tok["ov_a"] = _over(not light, .085 if light else .10)    # --ov-a
    tok["well_inset"] = _over(False, .10 if light else .28)   # --well-inset
    # --pill: light #FFFFFF -> #F7F7F9, dark white .085 -> .05
    tok["pill_top"] = _rgb(255, 255, 255) if light else _over(True, .085)
    tok["pill_bottom"] = _rgb(247, 247, 249) if light else _over(True, .05)
    # --red-fg: color-mix(red 80% (78% dark), secondary_text)
    sec_text = QColor(t["secondary_text"])
    tok["red_fg"] = _mix(QColor(tok["red"]), sec_text, .20 if light else .22)
    tok["track_hot"] = with_alpha(sec_text, .55)               # scroll thumb hover
    tok["box_line"] = with_alpha(sec_text, .70)                # chip check box rim
    tok["fade"] = with_alpha(QColor(t["secondary"]), .88)      # tray right fade
    # The LOAD bezel key (profile-well round, mockup 3): the recessed ring
    # and the gloss crescent on the glass disc.
    tok["channel"] = _over(False, .07 if light else .40)
    tok["crescent"] = _over(True, .90 if light else .16)
    # The tab row (.tabs / .tab.on): the bar sits a step below the page
    # surface, the open tab a step above it, in both themes.
    sec, sec_dark, sec_light = (QColor(t["secondary"]), QColor(t["secondary_dark"]),
                                QColor(t["secondary_light"]))
    if light:
        tok["tab_bar"] = sec_dark
        tok["tab_on"] = sec_light
    else:
        tok["tab_bar"] = _mix(sec, sec_dark, .5)
        tok["tab_on"] = _mix(sec, sec_light, .43)
    return tok
