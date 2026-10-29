# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The window's main tab row (CHART / NEW & EDIT / FIND CHART / SETTINGS).

SPEC-MEM-004 §5, from the Single Tray mockup's ``.tabs`` / ``.tab`` /
``.tab.on``: a 28 px bar, 23 px tabs, 10.5 px weight 600, the open tab
raised a step above the bar with its gloss and hairline. Centred, and the
open tab in the theme colour (primary text + 2 px underline), per Lorris's
2026-10-22 feedback on the first build. The rules
are scoped by object name (``mainTabs`` / ``mainTabBar``, set where
core_gui_qt builds the tab widget), so tab bars nested inside the pages keep
``get_tab_bar_style``'s generic rules.
"""
from __future__ import annotations

from ui.qt_theme import AREA_DEFAULTS, get_tab_bar_style, is_light_theme, scaled_area_px

from .tokens import pane_tokens


def _rgba(c) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.3f})"


def main_tab_row_rules(compact: bool = False) -> str:
    tok = pane_tokens()
    px = max(6, round(scaled_area_px('tabs') * 10.5 / AREA_DEFAULTS.get('tabs', 12)))
    pad = 10 if compact else 15
    hair = tok["hair_soft"]
    # The open tab carries the theme colour (Lorris, 2026-10-22: white only
    # looked "dead"): primary text + a 2 px primary underline. Dark themes
    # use primary_light for the text so it reads on the dark tab.
    accent = (tok["primary"] if is_light_theme() else tok["primary_light"]).name()
    return f"""
        QTabWidget#mainTabs {{
            background-color: {tok["tab_bar"].name()};
        }}
        QTabWidget#mainTabs::tab-bar {{
            alignment: center;
        }}
        QTabWidget#mainTabs::pane {{
            border: none;
            border-top: 1px solid {_rgba(hair)};
            background-color: {tok["secondary_dark"].name()};
        }}
        QTabBar#mainTabBar {{
            background: transparent;
        }}
        QTabBar#mainTabBar::tab {{
            background: transparent;
            color: {tok["secondary_text"].name()};
            border: 1px solid transparent;
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            height: 23px;
            margin-top: 5px;
            margin-right: 2px;
            padding: 0px {pad}px;
            font-size: {px}px;
            font-weight: 600;
        }}
        QTabBar#mainTabBar::tab:hover:!selected {{
            background: {_rgba(tok["ov_h"])};
            color: {tok["primary_text"].name()};
        }}
        QTabBar#mainTabBar::tab:selected {{
            background: {tok["tab_on"].name()};
            color: {accent};
            border: 1px solid {_rgba(hair)};
            border-top-color: {_rgba(tok["gloss"])};
            border-bottom: 2px solid {tok["primary"].name()};
        }}
    """


def main_tab_style(compact: bool = False) -> str:
    """The main tab widget's whole sheet: generic rules + the tab row."""
    return get_tab_bar_style(compact=compact) + main_tab_row_rules(compact)
