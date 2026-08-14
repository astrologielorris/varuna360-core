#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Chart Title Widget
Displays chart name with close button (centered above chart)
"""
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMenu,
    QDialog,
    QApplication,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer

# Import centralized theme
from ui.qt_theme import (
    STATUS,
    GOLD,
    get_theme_colors,
    get_secondary_button_style,
    scaled_area_px,
    scaled_area_font,
    desat_hex,
)

import urllib.parse


def _search_chart_name_google_images(gui):
    """
    Search Google Images for the current chart's name.

    Opens the QTBrowser tab and navigates to a Google Image search
    using the chart person's name as the search query.

    Args:
        gui: The main GUI instance with current_chart_data
    """
    # Check if we have a chart loaded
    if not hasattr(gui, 'current_chart_data') or not gui.current_chart_data:
        return

    name = gui.current_chart_data.get('name', '')
    if not name or name == "Unknown" or name == "No Chart Loaded":
        return

    # Build Google Image search URL
    encoded_name = urllib.parse.quote(name)
    search_url = f"https://www.google.com/search?q={encoded_name}&tbm=isch"

    # Open in system browser (browser panels removed in Phase 2 cleanup)
    import webbrowser
    webbrowser.open(search_url)


def _jd_to_date_str(jd):
    """Convert Julian Day to MM/DD/YYYY string."""
    try:
        # SPEC-CAL-001: DISPLAY-ONLY. These date strings feed dasha-range web
        # searches (user-facing), so they follow the calendar-display setting.
        from core.time_utils import display_revjul
        year, month, day, _ = display_revjul(jd)
        return f"{month:02d}/{day:02d}/{year}"
    except Exception:
        return ""


def _nisarga_age_to_date(gui, age):
    """Convert a Nisarga age to MM/DD/YYYY using birth data."""
    chart = getattr(gui, 'current_chart_data', None)
    if not chart:
        return ""
    birth_y = chart.get('year')
    birth_m = chart.get('month', 1)
    birth_d = chart.get('day', 1)
    if not birth_y:
        return ""
    return f"{birth_m:02d}/{birth_d:02d}/{birth_y + age}"


def _get_all_dasha_entries(gui, panel_side):
    """Get antardasha (sub-period) entries from a panel for the context menu.

    For Vedanga/Vimshottari: reads cached dasha data and filters for
    antardasha-level entries (level 1 = indent '  ') within the current
    mahadasha. Uses jd/end_jd for reliable dates.

    For Nisarga: reads from list widget, derives dates from birth year + age.

    Returns:
        tuple: (list_of_entries, dasha_label)
    """
    if panel_side == 'left':
        dasha_data = getattr(gui, 'vedanga_dasha_data', None)
        # Label reflects current ayanamsa setting (Vedanga, Dhruva, Lahiri, etc.)
        from core.ayanamsa_data import get_ayanamsa_name
        ayan_id = getattr(gui, 'vedanga_ayanamsa', 100)
        dasha_label = get_ayanamsa_name(ayan_id) or "Dasha"
        is_nisarga = False
    else:
        right_mode = getattr(gui, 'right_dasha_mode', 'nisarga')
        is_nisarga = right_mode == "nisarga"
        if is_nisarga:
            dasha_data = None
            dasha_label = "Planetary Ages"
        else:
            dasha_data = getattr(gui, 'vimshottari_dasha_data', None)
            dasha_label = "Vimshottari"

    if is_nisarga:
        return _get_nisarga_entries(gui), dasha_label

    # --- Vedanga / Vimshottari: get antardasha from cached data ---
    if not dasha_data:
        return [], dasha_label

    # Check if cached data has antardasha (level 1) entries
    has_antardasha = any(e.get('level', 0) == 1 for e in dasha_data)

    if not has_antardasha:
        # Cached data only has mahadasha — calculate antardasha on the fly
        # Find current mahadasha and compute its sub-periods
        current_maha = None
        for entry in dasha_data:
            if entry.get('is_current', False):
                current_maha = entry
                break
        if not current_maha or not current_maha.get('jd') or not current_maha.get('end_jd'):
            return [], dasha_label

        try:
            from core.vimshottari_dasha import calculate_sub_dashas_for_period
            maha_lord = current_maha['lord']
            sub_periods = calculate_sub_dashas_for_period(
                current_maha['jd'], current_maha['end_jd'], maha_lord)
            entries = []
            for sp in sub_periods:
                lord = sp.get('lord', '')
                jd = sp.get('jd_start', sp.get('jd'))
                end_jd = sp.get('jd_end', sp.get('end_jd'))
                start = _jd_to_date_str(jd) if jd else ""
                end = _jd_to_date_str(end_jd) if end_jd else ""
                if not start:
                    continue
                display = f"{lord} ({start} - {end})" if end else f"{lord} ({start})"
                entries.append({
                    'lord': lord, 'start': start, 'end': end,
                    'display': display,
                    'is_current': sp.get('is_current', False),
                    'is_maturation': False,
                })
            return entries, dasha_label
        except Exception:
            return [], dasha_label

    # Cached data has antardasha — extract from it
    current_maha_idx = None
    for i, entry in enumerate(dasha_data):
        if entry.get('level', 0) == 0 and entry.get('is_current', False):
            current_maha_idx = i
            break

    if current_maha_idx is None:
        return [], dasha_label

    current_maha = dasha_data[current_maha_idx]
    maha_lord = current_maha.get('lord', '')

    entries = []
    for i in range(current_maha_idx + 1, len(dasha_data)):
        entry = dasha_data[i]
        level = entry.get('level', 0)
        if level == 0:
            break  # Hit next mahadasha
        if level != 1:
            continue  # Skip deeper levels
        if not entry.get('lord'):
            continue

        lord = entry['lord']
        jd = entry.get('jd')
        end_jd = entry.get('end_jd')
        start = _jd_to_date_str(jd) if jd else ""
        end = _jd_to_date_str(end_jd) if end_jd else ""
        if not start:
            continue

        display = f"{maha_lord}/{lord} ({start} - {end})" if end else f"{maha_lord}/{lord} ({start})"
        entries.append({
            'lord': lord, 'start': start, 'end': end,
            'display': display,
            'is_current': entry.get('is_current', False),
            'is_maturation': False,
        })

    return entries, dasha_label


def _get_nisarga_entries(gui):
    """Get Nisarga (Planetary Ages + Maturation) entries from the list widget."""
    import re
    list_widget = getattr(gui, 'vimshottari_list', None)
    if not list_widget:
        return []

    entries = []
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if not item:
            continue
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or not entry.get('lord') or entry.get('is_separator'):
            continue

        lord = entry['lord']
        text = entry.get('text', '')
        age_match = re.search(r'(\d+)-(\d+)y', text)
        if not age_match:
            continue

        start_age = int(age_match.group(1))
        end_age = int(age_match.group(2))
        start = _nisarga_age_to_date(gui, start_age)
        end = _nisarga_age_to_date(gui, end_age)

        # Maturation entries have "matures at" in their text
        is_mat = "matures at" in text or entry.get('is_maturation', False)
        display = f"{lord} {start_age}-{end_age}y ({start} - {end})"

        entries.append({
            'lord': lord,
            'start': start,
            'end': end,
            'display': display,
            'is_current': entry.get('is_current', False),
            'is_maturation': is_mat,
        })

    return entries


_TRANSIT_IDLE_TOOLTIP = ("Show current planetary transits overlay. "
                         "Drop a chart here to overlay it.")


def _style_overlay_chip(gui):
    """Theme the overlay chip (SPEC-TRN-006, Rule 20 — no hardcoded hex)."""
    if not hasattr(gui, 'overlay_chip'):
        return
    theme = get_theme_colors()
    gui.overlay_chip.setStyleSheet(f"""
        QWidget {{
            background-color: {theme["secondary_dark"]};
            border: 1px solid {theme["primary"]};
            border-radius: 11px;
        }}
    """)
    gui.overlay_chip_label.setStyleSheet(f"""
        QLabel {{
            color: {theme["secondary_text"]};
            background: transparent;
            border: none;
            font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif;
            font-size: {scaled_area_px('buttons')}px;
        }}
    """)
    gui.overlay_chip_clear.setStyleSheet(f"""
        QPushButton {{
            color: {theme["secondary_text"]};
            background: transparent;
            border: none;
            font-size: {scaled_area_px('buttons')}px;
            font-weight: bold;
        }}
        QPushButton:hover {{ color: {theme["primary_text"]}; }}
    """)


def update_overlay_chip(gui, mgr):
    """Sync the overlay chip + TRANSIT button idle text from manager state.

    Single call site (the _on_transit_state_changed mediator). The manager is the
    source of truth for the display name; the GUI never derives it. Setting the
    button's idle text/tooltip here is what TransitDropButton snapshots live on
    drag-enter, so an active overlay restores "⟐ Overlay" correctly after a hover.
    """
    if not hasattr(gui, 'overlay_chip'):
        return
    is_overlay = (getattr(mgr, 'transit_mode', '') == "overlay_chart"
                  and getattr(mgr, 'transit_enabled', False))
    if is_overlay:
        name = mgr.overlay_label or "chart"
        shown = name if len(name) <= 18 else name[:17] + "…"
        gui.overlay_chip_label.setText(f"⟐ {shown}")
        gui.overlay_chip_label.setToolTip(name)
        # Do not reveal the chip in compact mode: the TRANSIT button is hidden
        # there, so a visible chip would be a dead control (reachable when an
        # overlay is started while already compact, e.g. via the right-click entry).
        gui.overlay_chip.setVisible(not getattr(gui, '_title_is_compact', False))
        if hasattr(gui, 'transit_btn'):
            gui.transit_btn.setText("⟐ Overlay")
            gui.transit_btn.setToolTip(
                f"Overlay: {name}. Click to turn the rim off, or use the x on "
                f"the chip to go back to live sky.")
    else:
        gui.overlay_chip.setVisible(False)
        if hasattr(gui, 'transit_btn'):
            gui.transit_btn.setText("⟐ Transit")
            gui.transit_btn.setToolTip(_TRANSIT_IDLE_TOOLTIP)


def _show_transit_context_menu(gui, button, pos):
    """Right-click menu on the TRANSIT button (SPEC-TRN-006 D-1).

    Actions are enabled only while an overlay chart is active. Gives users who
    never notice the chip the same clear / back-to-live-sky operations.
    """
    mgr = getattr(gui, 'transit_overlay_manager', None)
    is_overlay = (mgr is not None
                  and getattr(mgr, 'transit_mode', '') == "overlay_chart"
                  and getattr(mgr, 'transit_enabled', False))
    if not is_overlay:
        return
    theme = get_theme_colors()
    menu = QMenu(button)
    menu.setStyleSheet(f"""
        QMenu {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_dark"]};
        }}
        QMenu::item:selected {{ background-color: {theme["secondary_light"]}; }}
    """)
    menu.addAction("Back to live sky").triggered.connect(
        lambda _=False: gui.chart_overlay_manager.back_to_live_sky())
    menu.addAction("Clear overlay chart").triggered.connect(
        lambda _=False: gui.chart_overlay_manager.clear())
    menu.exec(button.mapToGlobal(pos))


def _show_pill_context_menu(gui, button, pos):
    """Right-click menu on the chart name pill button.

    Dynamic sections:
    - Web searches (Astrotheme, Wikipedia, Astro-Databank, Google Images)
    - Current dasha period searches (from left and right panels)
    """
    if not hasattr(gui, 'current_chart_data') or not gui.current_chart_data:
        return

    name = gui.current_chart_data.get('name', '')
    if not name or name == "Unknown" or name == "No Chart Loaded":
        return

    theme = get_theme_colors()
    menu = QMenu(button)
    menu.setStyleSheet(f"""
        QMenu {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_dark"]};
        }}
        QMenu::item:selected {{
            background-color: {theme["secondary_light"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {theme["secondary_light"]};
            margin: 4px 8px;
        }}
    """)

    # === Astrology searches ===
    menu.addAction(f"Astrotheme: \"{name}\"").triggered.connect(
        lambda _=False: _web_search(f"site:www.astrotheme.com {name}"))
    menu.addAction(f"Astro-Databank: \"{name}\"").triggered.connect(
        lambda _=False: _web_search(f"site:www.astro.com/astro-databank {name}"))

    menu.addSeparator()

    # === Biography searches ===
    menu.addAction(f"Wikipedia: \"{name}\"").triggered.connect(
        lambda _=False: _web_search(f"site:en.wikipedia.org {name}"))
    menu.addAction(f"Google Images: \"{name}\"").triggered.connect(
        lambda _=False: _search_chart_name_google_images(gui))

    # === Dynamic dasha searches (both panels) ===
    for panel_side in ('left', 'right'):
        entries, label = _get_all_dasha_entries(gui, panel_side)

        if not entries:
            continue

        menu.addSeparator()

        # For Nisarga (right pane): split into Planetary Ages vs Maturation
        is_nisarga = any(e.get('is_maturation') for e in entries)
        if is_nisarga:
            age_entries = [e for e in entries if not e.get('is_maturation')]
            mat_entries = [e for e in entries if e.get('is_maturation')]

            for group_label, group_entries in [
                ("Planetary Ages", age_entries),
                ("Maturation Ages", mat_entries),
            ]:
                if not group_entries:
                    continue
                _add_dasha_submenu_pair(
                    menu, name, group_label, group_entries)
        else:
            _add_dasha_submenu_pair(menu, name, label, entries)

    menu.exec(button.mapToGlobal(pos))


def _add_dasha_submenu_pair(menu, person_name, label, entries):
    """Add Google Search + Copy AI Prompt submenus for a set of dasha entries."""
    style = menu.styleSheet()

    google_submenu = menu.addMenu(f"{label} — Google Search")
    google_submenu.setStyleSheet(style)

    ai_submenu = menu.addMenu(f"{label} — Copy AI Prompt")
    ai_submenu.setStyleSheet(style)

    for entry_info in entries:
        display = entry_info['display']
        start = entry_info['start']
        end = entry_info['end']
        is_current = entry_info.get('is_current', False)
        is_mat = entry_info.get('is_maturation', False)

        if is_current:
            prefix = "▶ "
        elif is_mat:
            prefix = "★ "
        else:
            prefix = "  "

        g_action = google_submenu.addAction(f"{prefix}{display}")
        g_action.triggered.connect(
            lambda _=False, n=person_name, s=start, e=end: _web_search_date_range(n, s, e))

        ai_action = ai_submenu.addAction(f"{prefix}{display}")
        ai_action.triggered.connect(
            lambda _=False, n=person_name, s=start, e=end: _copy_ai_prompt(n, s, e))


def _web_search(query):
    """Open a Google search in the system's default browser."""
    import webbrowser
    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")


def _web_search_date_range(person_name, start_date, end_date):
    """Google search for person with date range filter (tbs parameter).

    Dates derived from Julian Day via swe.revjul() in MM/DD/YYYY format.
    Google's tbs cd_min/cd_max expects MM/DD/YYYY. The tbs value is
    URL-encoded to avoid issues with slashes and colons.
    """
    import webbrowser
    query = urllib.parse.quote_plus(person_name)
    url = f"https://www.google.com/search?q={query}"
    if start_date:
        tbs_val = f"cdr:1,cd_min:{start_date}"
        if end_date:
            tbs_val += f",cd_max:{end_date}"
        url += f"&tbs={urllib.parse.quote(tbs_val)}"
    webbrowser.open(url)


# Month names for readable date conversion
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def _date_str_to_readable(date_str):
    """Convert MM/DD/YYYY to 'Month YYYY' for natural-language prompts."""
    if not date_str:
        return ""
    parts = date_str.split("/")
    if len(parts) != 3:
        return date_str
    month_idx = int(parts[0])
    year = parts[2]
    if 1 <= month_idx <= 12:
        return f"{_MONTH_NAMES[month_idx]} {year}"
    return date_str


def _copy_ai_prompt(person_name, start_date, end_date):
    """Build an AI-ready prompt and copy it to clipboard.

    Creates a natural-language prompt asking about significant events
    for the person during the given period. Uses 'Month YYYY' format
    for readability.
    """
    start_readable = _date_str_to_readable(start_date)
    end_readable = _date_str_to_readable(end_date)

    if start_readable and end_readable:
        period = f"between {start_readable} and {end_readable}"
    elif start_readable:
        period = f"from {start_readable} onwards"
    else:
        return

    prompt = (
        f"What significant events happened to {person_name} {period}? "
        f"List major life events, career milestones, public incidents, "
        f"relationships, health issues, or any notable changes during this time."
    )

    clipboard = QApplication.clipboard()
    clipboard.setText(prompt)


class ChartSearchDialog(QDialog):
    """
    Popup dialog for searching charts across ALL profiles.
    Live-filters as user types, click a result to load that chart.
    Switches profile automatically if the chart is in a different profile.
    """

    def __init__(self, gui, parent=None):
        super().__init__(parent or gui)
        self.gui = gui
        # Each entry: (profile_id, profile_name, chart_index, chart_dict)
        self._all_charts = []
        self._filtered = []  # Subset after filtering

        self.setWindowTitle("Search Charts — All Profiles")
        self.setMinimumSize(550, 450)
        self.resize(600, 500)
        # SPEC-THM-001 G12: live theme color (was frozen BG).
        _theme = get_theme_colors()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_theme['secondary_dark']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Search input — SPEC-THM-001 G12 live theme colors.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type a name to search across all profiles...")
        self.search_input.setFont(scaled_area_font('buttons', family="Segoe UI"))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_theme['secondary']};
                color: {_theme['secondary_text']};
                border: 2px solid {_theme['secondary_light']};
                border-radius: 10px;
                padding: 10px 16px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QLineEdit:focus {{
                border: 2px solid {_theme['primary']};
            }}
        """)
        self.search_input.textChanged.connect(self._filter_charts)
        layout.addWidget(self.search_input)

        # Result count label — SPEC-THM-001 G12 live theme color.
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {_theme['secondary_text']}; font-size: {scaled_area_px('buttons')}px; padding-left: 4px;")
        layout.addWidget(self.count_label)

        # Results list — SPEC-THM-001 G12 live theme colors.
        self.results_list = QListWidget()
        self.results_list.setFont(scaled_area_font('buttons', family="Segoe UI"))
        self.results_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {_theme['secondary']};
                color: {_theme['secondary_text']};
                border: 1px solid {_theme['secondary_light']};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {_theme['secondary_light']};
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {_theme['secondary_light']};
            }}
            QListWidget::item:selected {{
                background-color: {_theme['primary']};
                color: {_theme['primary_text']};
            }}
            QScrollBar:vertical {{
                background-color: {_theme['secondary']};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {_theme['secondary_light']};
                border-radius: 5px;
                min-height: 30px;
            }}
        """)
        self.results_list.itemDoubleClicked.connect(self._select_chart)
        self.results_list.itemActivated.connect(self._select_chart)
        layout.addWidget(self.results_list, stretch=1)

        # "Search in Find Chart" button (hidden by default, shown when 0 results)
        self.find_chart_btn = QPushButton("Search in Find Chart tab")
        self.find_chart_btn.setFont(scaled_area_font('buttons', family="Segoe UI"))
        self.find_chart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_chart_btn.setStyleSheet(get_secondary_button_style())
        self.find_chart_btn.clicked.connect(self._redirect_to_find_chart)
        self.find_chart_btn.setVisible(False)
        layout.addWidget(self.find_chart_btn)

        # Hint label — SPEC-THM-001 G12 live theme color.
        hint = QLabel("Double-click or press Enter to load chart  ·  Searches all profiles")
        hint.setStyleSheet(f"color: {_theme['secondary_text']}; font-size: {scaled_area_px('buttons')}px; padding-left: 4px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # Load all charts from all profiles
        self._load_all_profile_charts()

        # Show all initially
        self._filter_charts("")

        self.search_input.setFocus()

    def _load_all_profile_charts(self):
        """Scan all profile session.json files and collect chart entries."""
        import json
        from pathlib import Path

        self._all_charts.clear()

        # Get profiles directory
        profiles_dir = None
        if hasattr(self.gui, 'profile_manager'):
            profiles_dir = self.gui.profile_manager.profiles_dir
        else:
            # Fallback: derive from project root
            project_root = Path(__file__).parent.parent.parent
            profiles_dir = project_root / "profiles"

        if not profiles_dir or not profiles_dir.exists():
            return

        current_profile = ""
        if hasattr(self.gui, 'profile_manager'):
            current_profile = self.gui.profile_manager.get_current_profile()

        for item in sorted(profiles_dir.iterdir()):
            if not item.is_dir() or item.name.startswith('_'):
                continue

            profile_id = item.name
            session_file = item / "session.json"
            profile_json = item / "profile.json"

            # Get display name for profile
            profile_name = profile_id.replace('_', ' ').title()
            if profile_json.exists():
                try:
                    with open(profile_json, 'r', encoding='utf-8') as f:
                        pdata = json.load(f)
                    profile_name = pdata.get('name', profile_name)
                except Exception:
                    pass

            # For current profile, use live in-memory charts (more up-to-date)
            if profile_id == current_profile and hasattr(self.gui, 'memory_panel') and self.gui.memory_panel:
                for idx, chart in enumerate(self.gui.memory_panel.charts):
                    self._all_charts.append((profile_id, profile_name, idx, chart))
                continue

            # For other profiles, read from session.json
            if not session_file.exists():
                continue

            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                charts = session_data.get('charts', [])
                for idx, chart in enumerate(charts):
                    self._all_charts.append((profile_id, profile_name, idx, chart))
            except Exception as e:
                print(f"[SEARCH] Error reading {session_file}: {e}")


    def _filter_charts(self, text):
        """Filter charts by name, city, or country matching the search text."""
        self.results_list.clear()
        self._filtered.clear()

        query = text.strip().lower()
        current_profile = ""
        if hasattr(self.gui, 'profile_manager'):
            current_profile = self.gui.profile_manager.get_current_profile()

        for profile_id, profile_name, chart_idx, chart in self._all_charts:
            recipe = chart.get('recipe', {})
            name = chart.get('person_name') or recipe.get('name') or 'Unknown'
            city = chart.get('city') or recipe.get('city') or ''
            country = chart.get('country') or recipe.get('country') or ''

            searchable = f"{name} {city} {country}".lower()
            if query and query not in searchable:
                continue

            # Build display: Name — City, Country  [Profile]
            location_parts = [p for p in [city, country] if p]
            location = ", ".join(location_parts)

            is_current = (profile_id == current_profile)
            profile_tag = f"  [{profile_name}]" if not is_current else f"  [{profile_name} ✓]"

            if location:
                display = f"{name}  —  {location}{profile_tag}"
            else:
                display = f"{name}{profile_tag}"

            item = QListWidgetItem(display)
            item.setToolTip(f"Profile: {profile_name} | Chart #{chart_idx + 1}")
            # Dim the profile tag color for current profile distinction
            if is_current:
                item.setForeground(self.results_list.palette().text().color())
            self.results_list.addItem(item)
            self._filtered.append((profile_id, profile_name, chart_idx, chart))

        total = len(self._all_charts)
        shown = self.results_list.count()
        if query:
            self.count_label.setText(f"{shown} of {total} charts match")
        else:
            self.count_label.setText(f"{total} charts across all profiles")

        has_find_chart = self._find_chart_tab_index() >= 0
        self.find_chart_btn.setVisible(shown == 0 and bool(query) and has_find_chart)

        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)

    def _select_chart(self, item):
        """Load the selected chart — switch profile if needed."""
        row = self.results_list.row(item)
        if row < 0 or row >= len(self._filtered):
            return

        profile_id, profile_name, chart_idx, chart = self._filtered[row]
        current_profile = ""
        if hasattr(self.gui, 'profile_manager'):
            current_profile = self.gui.profile_manager.get_current_profile()


        if profile_id == current_profile:
            # Same profile — just select the chart
            if hasattr(self.gui, 'memory_panel') and self.gui.memory_panel:
                self.gui.memory_panel.select_chart(chart_idx)
        else:
            # Different profile — switch first, then select chart after session restores
            if hasattr(self.gui, 'profile_manager'):
                self.gui.profile_manager._on_profile_selected(profile_id)
                # After profile switch + session restore, select the chart
                QTimer.singleShot(300, lambda: self._select_after_switch(chart_idx))

        self.accept()

    def _select_after_switch(self, chart_idx):
        """Select chart after profile switch has completed."""
        if hasattr(self.gui, 'memory_panel') and self.gui.memory_panel:
            if 0 <= chart_idx < len(self.gui.memory_panel.charts):
                self.gui.memory_panel.select_chart(chart_idx)
            else:
                pass

    def _find_chart_tab_index(self):
        """Return the tab index for Find Chart (placeholder or loaded), or -1."""
        gui = self.gui
        if not hasattr(gui, 'tab_widget'):
            return -1
        # Check loaded panel first, then placeholder
        for widget_attr in ('find_chart_panel', '_find_chart_placeholder'):
            w = getattr(gui, widget_attr, None)
            if w:
                idx = gui.tab_widget.indexOf(w)
                if idx >= 0:
                    return idx
        return -1

    def _redirect_to_find_chart(self):
        """Switch to Find Chart tab and inject the search query."""
        query = self.search_input.text().strip()
        gui = self.gui
        tab_idx = self._find_chart_tab_index()
        if tab_idx < 0:
            return
        self.accept()
        gui.tab_widget.setCurrentIndex(tab_idx)
        if query:
            QTimer.singleShot(200, lambda: self._inject_find_chart_query(gui, query))

    @staticmethod
    def _inject_find_chart_query(gui, query):
        panel = getattr(gui, 'find_chart_panel', None)
        if panel and hasattr(panel, 'search_entry'):
            panel.search_entry.setText(query)

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.results_list.currentItem()
            if current:
                self._select_chart(current)
        elif event.key() == Qt.Key.Key_Down and self.search_input.hasFocus():
            self.results_list.setFocus()
            if self.results_list.count() > 0:
                self.results_list.setCurrentRow(0)
        else:
            super().keyPressEvent(event)


def _open_chart_search(gui):
    """Open the chart search dialog to find charts across all profiles."""
    dialog = ChartSearchDialog(gui)
    dialog.exec()


def create_chart_title_widget(gui):
    """
    Create chart title widget with all control buttons matching the old CustomTkinter GUI.

    Layout: [LEFT buttons] [stretch] [Chart Pill + Close] [stretch] [RIGHT buttons]

    Args:
        gui: The parent ChartGUI instance

    Returns:
        QWidget: The title widget

    Stores on gui:
        LEFT SIDE:
        - gui.transit_btn (QPushButton) - Toggle transit outer rim (wheel view only)
        - gui.wheel_btn (QPushButton) - Toggle wheel chart view
        - gui.open_in_kala_btn (QPushButton) - Open chart in Kala software

        CENTER:
        - gui.chart_title_label (QPushButton - chart name pill button)
        - gui.chart_close_button (QPushButton)

        RIGHT SIDE:
        - gui.now_btn (QPushButton) - Create transit chart for current moment
        - gui.add_chart_btn (QPushButton) - Add new chart to memory
        - gui.search_btn (QPushButton) - Search for charts
        - gui.time_adjust_btn (QPushButton) - Time adjust toggle (time adjustment)
        - gui.human_design_btn (QPushButton) - Human Design toggle (-88° shift)
        - gui.aditya_btn (QPushButton) - Aditya Circle toggle
        - gui.dual_rim_btn (QPushButton) - Aditya + Tropical dual rim (wheel view only)
        - gui.tropical_btn (QPushButton) - Tropical Classic toggle
    """
    # Get theme colors for dynamic theming
    theme = get_theme_colors()

    widget = QWidget()
    widget.setFixedHeight(55)  # Slightly taller to prevent cutoff

    layout = QHBoxLayout(widget)
    layout.setContentsMargins(10, 5, 10, 5)  # Balanced margins
    layout.setSpacing(0)

    # Button styles for left-side buttons
    left_btn_style = f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["primary"]};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
            border: 1px solid {theme["primary_light"]};
        }}
        QPushButton:pressed {{
            background-color: {theme["primary_dark"]};
            color: {theme["primary_text"]};
        }}
    """

    # LEFT SIDE: Transit, Wheel, Open in Kala, Random buttons
    # Transit button - shows current planetary transits on outer rim (wheel view only)
    transit_btn_style = f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["primary"]};
            border-radius: 8px;
            padding: 8px 10px;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
            border: 1px solid {theme["primary_light"]};
        }}
        QPushButton:checked {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
            border: 2px solid {theme["primary_light"]};
        }}
    """
    # SPEC-TRN-006: TransitDropButton also accepts chart drops for overlay.
    from apps.widgets.transit_drop_button import TransitDropButton
    gui.transit_btn = TransitDropButton("⟐ Transit", gui)
    gui.transit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.transit_btn.setToolTip("Show current planetary transits overlay. "
                               "Drop a chart here to overlay it.")
    gui.transit_btn.setStyleSheet(transit_btn_style)
    gui.transit_btn.setCheckable(True)
    gui.transit_btn.setChecked(False)
    gui.transit_btn.setVisible(True)  # Visible on all chart views (SPEC-TRN-002)
    # Fix width so the text can swap to "⟐ Overlay chart" mid-drag without a jump.
    _tfm = gui.transit_btn.fontMetrics()
    gui.transit_btn.setMinimumWidth(_tfm.horizontalAdvance("⟐ Overlay chart") + 28)
    gui.transit_btn.clicked.connect(gui._toggle_transit_rim)
    gui.transit_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    gui.transit_btn.customContextMenuRequested.connect(
        lambda pos: _show_transit_context_menu(gui, gui.transit_btn, pos)
    )
    layout.addWidget(gui.transit_btn)

    layout.addSpacing(8)

    gui.wheel_btn = QPushButton("◎ Wheel")
    gui.wheel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.wheel_btn.setToolTip("Toggle wheel chart view")
    gui.wheel_btn.setStyleSheet(left_btn_style)
    gui.wheel_btn.clicked.connect(gui._toggle_wheel_view)
    layout.addWidget(gui.wheel_btn)

    layout.addSpacing(8)

    gui.open_in_kala_btn = QPushButton("Open in Kala")
    gui.open_in_kala_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.open_in_kala_btn.setToolTip("Open current chart in Kala software")
    gui.open_in_kala_btn.setStyleSheet(left_btn_style)
    gui.open_in_kala_btn.clicked.connect(gui._open_in_kala)
    layout.addWidget(gui.open_in_kala_btn)

    layout.addSpacing(8)

    layout.addSpacing(8)

    gui.chart_info_btn = QPushButton("📖 Chart Info")
    gui.chart_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.chart_info_btn.setToolTip("Chart information, notes, and biography")
    gui.chart_info_btn.setStyleSheet(left_btn_style)
    gui.chart_info_btn.clicked.connect(lambda: _fetch_chart_info(gui))
    layout.addWidget(gui.chart_info_btn)

    # LEFT SPACER (for centering the name+close group)
    layout.addStretch(1)

    # CENTER: Container for name pill + close button (centered as one unit)
    container = QWidget()
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(10)  # Slightly larger gap between pill and close button

    # Chart title as ROUNDED PILL BUTTON showing full birth info
    # Format: Name | Date Time TZ | Location (IANA) | Asc: Sign Deg°Min'
    # Typography/design language mirrors the vector-chart medallion (T-8
    # experiment, reversible): Inter family, gold hairline, name slightly
    # larger than the panel_titles area baseline.
    gui.chart_title_label = QPushButton("No Chart Loaded")
    gui.chart_title_label.setMinimumWidth(400)
    gui.chart_title_label.setMinimumHeight(40)
    gui.chart_title_label.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.chart_title_label.setStyleSheet(f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["primary_text"]};
            font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif;
            font-size: {round(scaled_area_px('panel_titles') * 1.25)}px;
            font-weight: bold;
            border: 1.5px solid {GOLD};
            border-radius: 20px;
            padding: 8px 24px;
            text-transform: none;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            border: 1.5px solid {theme["primary_light"]};
        }}
    """)
    gui.chart_title_label.setToolTip("Click: Google Images | Right-click: Search Astrotheme")
    gui.chart_title_label.clicked.connect(lambda: _search_chart_name_google_images(gui))
    gui.chart_title_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    gui.chart_title_label.customContextMenuRequested.connect(
        lambda pos: _show_pill_context_menu(gui, gui.chart_title_label, pos)
    )
    container_layout.addWidget(gui.chart_title_label)

    # Close button (round, danger red, modern clean design)
    gui.chart_close_button = QPushButton("×")
    gui.chart_close_button.setFixedSize(38, 38)
    gui.chart_close_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.chart_close_button.setToolTip("Remove current chart from memory")
    gui.chart_close_button.setStyleSheet(f"""
        QPushButton {{
            background-color: {desat_hex(STATUS["error"])};
            color: #FFFFFF;
            border: none;
            border-radius: 19px;
            font-size: {scaled_area_px('buttons')}px;
            font-weight: 500;
            font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif;
            padding: 0px 0px 2px 0px;
            text-align: center;
        }}
        QPushButton:hover {{
            background-color: {desat_hex('#CC0000')};
        }}
        QPushButton:pressed {{
            background-color: {desat_hex('#990000')};
        }}
    """)

    # Connect to close method directly
    gui.chart_close_button.clicked.connect(gui._close_current_chart)

    container_layout.addWidget(gui.chart_close_button)

    # SPEC-TRN-006: overlay chip — shown only in overlay-chart mode, right of the
    # close button. Reading order: base chart, remove base, overlay on top, remove
    # overlay. Hidden by default; update_overlay_chip() drives its state.
    gui.overlay_chip = QWidget()
    _chip_layout = QHBoxLayout(gui.overlay_chip)
    _chip_layout.setContentsMargins(8, 2, 6, 2)
    _chip_layout.setSpacing(6)
    gui.overlay_chip_label = QLabel("")
    _chip_layout.addWidget(gui.overlay_chip_label)
    gui.overlay_chip_clear = QPushButton("×")
    gui.overlay_chip_clear.setFixedSize(18, 18)
    gui.overlay_chip_clear.setFlat(True)
    gui.overlay_chip_clear.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.overlay_chip_clear.setToolTip("Remove overlay chart (back to live sky)")
    gui.overlay_chip_clear.clicked.connect(
        lambda: gui.chart_overlay_manager.back_to_live_sky())
    _chip_layout.addWidget(gui.overlay_chip_clear)
    gui.overlay_chip.setVisible(False)
    _style_overlay_chip(gui)
    container_layout.addWidget(gui.overlay_chip)

    # Add container to main layout (centered)
    layout.addWidget(container)

    # MIDDLE SPACER (pushes toggle buttons to the right)
    layout.addStretch(1)

    # RIGHT: Add Chart, Search, Time Adjust, Human Design, Aditya/Tropical toggle buttons
    # Button styles
    active_style = f"""
        QPushButton {{
            background-color: {desat_hex('#4CAF50')};
            color: white;
            font-weight: bold;
            font-size: {scaled_area_px('buttons')}px;
            border: none;
            border-radius: 8px;
            padding: 8px 12px;
            min-width: 100px;
        }}
        QPushButton:hover {{
            background-color: {desat_hex('#45A049')};
        }}
    """
    inactive_style = f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["primary"]};
            border-radius: 8px;
            padding: 8px 12px;
            min-width: 100px;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
    """

    # Now button - create transit chart for current moment
    now_btn_style = f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["primary"]};
            border-radius: 8px;
            padding: 8px 12px;
            min-width: 60px;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
    """
    gui.now_btn = QPushButton("Now")
    gui.now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.now_btn.setToolTip("Create a chart for the current moment (transit)")
    gui.now_btn.setStyleSheet(now_btn_style)
    gui.now_btn.clicked.connect(gui._load_now_chart)
    layout.addWidget(gui.now_btn)

    layout.addSpacing(8)

    # Add Chart button
    gui.add_chart_btn = QPushButton("+ Add Chart")
    gui.add_chart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.add_chart_btn.setToolTip("Add a new chart via AI-powered natural language input")
    gui.add_chart_btn.setStyleSheet(inactive_style)
    gui.add_chart_btn.clicked.connect(gui.show_add_chart_dialog)
    layout.addWidget(gui.add_chart_btn)

    layout.addSpacing(8)

    # Search button — moved to chart browser header row (left of Sort A→Z)
    # Keep as gui attribute so chart_memory_panel can delegate to it
    gui.search_btn = QPushButton("🔍 Search")
    gui.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.search_btn.setToolTip("Search for charts in database")
    gui.search_btn.setStyleSheet(inactive_style)
    gui.search_btn.clicked.connect(lambda: _open_chart_search(gui))

    # Time adjust button - TOGGLE time adjustment overlay
    gui.time_adjust_btn = QPushButton("Birth Time \u00b1")
    gui.time_adjust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.time_adjust_btn.setToolTip("Toggle birth time adjustment controls")
    gui.time_adjust_btn.setStyleSheet(inactive_style)
    gui.time_adjust_btn.clicked.connect(gui._toggle_time_adjust)
    layout.addWidget(gui.time_adjust_btn)

    layout.addSpacing(8)  # Gap between buttons

    # Human Design button - TOGGLE on/off
    gui.human_design_btn = QPushButton("Human Design")
    gui.human_design_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.human_design_btn.setToolTip("Toggle Human Design chart (-88° Sun shift)")
    gui.human_design_btn.setStyleSheet(inactive_style)
    gui.human_design_btn.clicked.connect(gui._toggle_human_design)
    layout.addWidget(gui.human_design_btn)

    layout.addSpacing(8)  # Gap between buttons

    # Aditya Circle button (default = active)
    gui.aditya_btn = QPushButton("Aditya Circle")
    gui.aditya_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.aditya_btn.setToolTip("Use Aditya Circle system (default)")
    gui.aditya_btn.setStyleSheet(active_style)
    gui.aditya_btn.clicked.connect(lambda: gui._set_aditya_mode("aditya"))
    layout.addWidget(gui.aditya_btn)

    layout.addSpacing(8)  # Gap between buttons

    # Aditya + Tropical dual rim button (only visible in wheel view)
    # Shows outer Tropical rim on top of Aditya wheel for comparison
    dual_rim_style = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["secondary"]};
            border-radius: 8px;
            padding: 8px 10px;
            min-width: 80px;
        }}
        QPushButton:hover {{
            background-color: {theme["secondary"]};
            color: #FFFFFF;
        }}
        QPushButton:checked {{
            background-color: {theme["primary"]};
            color: #FFFFFF;
            border: 2px solid {theme["primary_light"]};
        }}
    """
    gui.dual_rim_btn = QPushButton("+ Tropical")
    gui.dual_rim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.dual_rim_btn.setToolTip("Show outer Tropical rim on Aditya wheel (wheel view only)")
    gui.dual_rim_btn.setStyleSheet(dual_rim_style)
    gui.dual_rim_btn.setCheckable(True)
    gui.dual_rim_btn.setChecked(False)
    gui.dual_rim_btn.setVisible(False)  # Hidden by default, shown in wheel view
    gui.dual_rim_btn.clicked.connect(gui._toggle_dual_rim)
    layout.addWidget(gui.dual_rim_btn)

    layout.addSpacing(8)  # Gap between buttons

    # Tropical Classic button (default = inactive)
    gui.tropical_btn = QPushButton("Tropical Classic")
    gui.tropical_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.tropical_btn.setToolTip("Use traditional Tropical zodiac system")
    gui.tropical_btn.setStyleSheet(inactive_style)
    gui.tropical_btn.clicked.connect(lambda: gui._set_aditya_mode("tropical_classic"))
    layout.addWidget(gui.tropical_btn)

    # Store widget reference
    gui.chart_title_widget = widget

    # Compact mode: buttons to fully hide (rarely needed when tiled)
    gui._title_compact_hidden_btns = [
        gui.open_in_kala_btn,
        gui.chart_info_btn,
        gui.time_adjust_btn,
        gui.human_design_btn,
    ]
    # Buttons that stay visible in compact mode (need style adjustment)
    gui._title_compact_visible_btns = [
        gui.wheel_btn,
        gui.now_btn,
        gui.add_chart_btn,
        gui.search_btn,
        gui.aditya_btn,
        gui.tropical_btn,
    ]
    gui._title_is_compact = False

    return widget


def set_chart_title_compact(gui, compact):
    """Switch chart title bar between compact (tiled) and full layout.

    In compact mode:
    - Hides rarely-needed buttons (Chart Info, Random, Open in Kala, etc.)
    - Keeps useful buttons (Wheel, Now, Add Chart, Search, Aditya, Tropical)
      but applies compact styling so they don't stretch or overflow
    - Shrinks the name pill and close button
    - Reduces overall title bar height from 55px to 35px
    """
    if getattr(gui, '_title_is_compact', False) == compact:
        return
    gui._title_is_compact = compact

    theme = get_theme_colors()

    # --- 1. Hide/show non-essential buttons ---
    for btn in getattr(gui, '_title_compact_hidden_btns', []):
        btn.setVisible(not compact)

    # Always hide wheel-view-only buttons in compact mode (too much width)
    if compact:
        for attr in ('transit_btn', 'dual_rim_btn'):
            btn = getattr(gui, attr, None)
            if btn:
                btn.setVisible(False)
    # SPEC-TRN-006: the overlay chip has no meaning without the TRANSIT button
    # to re-enter the state, so hide it in compact (state is kept, not cleared).
    _chip = getattr(gui, 'overlay_chip', None)
    if _chip is not None:
        if compact:
            _chip.setVisible(False)
        else:
            _mgr = getattr(gui, 'transit_overlay_manager', None)
            _chip.setVisible(
                _mgr is not None
                and getattr(_mgr, 'transit_mode', '') == "overlay_chart"
                and getattr(_mgr, 'transit_enabled', False))

    # --- 2. Style all remaining visible buttons ---
    # Compact: small, fixed-height, no min-width, tight padding
    # Full: restore original styles
    _compact_left = f"""
        QPushButton {{
            background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary_dark"]};
            border-radius: 5px; padding: 2px 6px;
            max-height: 22px;
        }}
        QPushButton:hover {{ background-color: {theme["primary"]}; color: {theme["primary_text"]}; }}
    """
    _compact_active = f"""
        QPushButton {{
            background-color: {desat_hex('#4CAF50')}; color: white;
            font-weight: bold; font-size: {scaled_area_px('buttons')}px; border: none;
            border-radius: 5px; padding: 2px 6px;
            max-height: 22px;
        }}
        QPushButton:hover {{ background-color: {desat_hex('#45A049')}; }}
    """
    _compact_inactive = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary_dark"]};
            border-radius: 5px; padding: 2px 6px;
            max-height: 22px;
        }}
        QPushButton:hover {{ background-color: {theme["secondary_light"]}; color: {theme["secondary_text"]}; }}
    """
    _compact_now = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary"]};
            border-radius: 5px; padding: 2px 6px;
            max-height: 22px;
        }}
        QPushButton:hover {{ background-color: {theme["secondary"]}; color: #FFF; }}
    """

    _full_left = f"""
        QPushButton {{
            background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary_dark"]};
            border-radius: 8px; padding: 8px 12px;
        }}
        QPushButton:hover {{ background-color: {theme["secondary_light"]}; color: #FFF; border: 1px solid {theme["primary"]}; }}
        QPushButton:pressed {{ background-color: {theme["secondary_light"]}; }}
    """
    _full_active = f"""
        QPushButton {{
            background-color: {desat_hex('#4CAF50')}; color: white;
            font-weight: bold; font-size: {scaled_area_px('buttons')}px; border: none;
            border-radius: 8px; padding: 8px 12px; min-width: 100px;
        }}
        QPushButton:hover {{ background-color: {desat_hex('#45A049')}; }}
    """
    _full_inactive = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary_dark"]};
            border-radius: 8px; padding: 8px 12px; min-width: 100px;
        }}
        QPushButton:hover {{ background-color: {theme["secondary_light"]}; color: {theme["secondary_text"]}; }}
    """
    _full_now = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]}; color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px; border: 1px solid {theme["secondary"]};
            border-radius: 8px; padding: 8px 12px; min-width: 60px;
        }}
        QPushButton:hover {{ background-color: {theme["secondary"]}; color: #FFF; }}
    """

    # Map each button to its compact/full style pair
    _style_map = {
        'wheel_btn':     (_compact_left, _full_left),
        'now_btn':       (_compact_now, _full_now),
        'add_chart_btn': (_compact_inactive, _full_inactive),
        'search_btn':    (_compact_inactive, _full_inactive),
        'aditya_btn':    (_compact_active if gui.state.aditya_mode == "aditya" else _compact_inactive,
                          _full_active if gui.state.aditya_mode == "aditya" else _full_inactive),
        'tropical_btn':  (_compact_active if gui.state.aditya_mode in ("tropical_classic", "sidereal") else _compact_inactive,
                          _full_active if gui.state.aditya_mode in ("tropical_classic", "sidereal") else _full_inactive),
    }

    for attr_name, (c_style, f_style) in _style_map.items():
        btn = getattr(gui, attr_name, None)
        if btn:
            btn.setStyleSheet(c_style if compact else f_style)
            btn.setVisible(True)

    # --- 3. Adjust the name pill ---
    if hasattr(gui, 'chart_title_label'):
        if compact:
            gui.chart_title_label.setMinimumWidth(120)
            gui.chart_title_label.setMinimumHeight(24)
            gui.chart_title_label.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme["secondary"]};
                    color: {theme["primary_text"]};
                    font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
                    border: 1px solid {theme["primary"]};
                    border-radius: 12px; padding: 3px 10px;
                }}
                QPushButton:hover {{
                    background-color: {theme["primary"]};
                }}
            """)
        else:
            gui.chart_title_label.setMinimumWidth(400)
            gui.chart_title_label.setMinimumHeight(40)
            gui.chart_title_label.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme["secondary"]};
                    color: {theme["primary_text"]};
                    font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
                    border: 1px solid {theme["primary"]};
                    border-radius: 20px; padding: 8px 24px;
                }}
                QPushButton:hover {{
                    background-color: {theme["primary"]};
                }}
            """)

    # --- 4. Adjust close button ---
    if hasattr(gui, 'chart_close_button'):
        if compact:
            gui.chart_close_button.setFixedSize(22, 22)
            gui.chart_close_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {desat_hex(STATUS["error"])}; color: #FFF;
                    border: none; border-radius: 11px;
                    font-size: {scaled_area_px('buttons')}px; padding: 0;
                }}
                QPushButton:hover {{ background-color: {desat_hex('#CC0000')}; }}
            """)
        else:
            gui.chart_close_button.setFixedSize(38, 38)
            gui.chart_close_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {desat_hex(STATUS["error"])}; color: #FFF;
                    border: none; border-radius: 19px;
                    font-size: {scaled_area_px('buttons')}px; font-weight: 500;
                    padding: 0px 0px 2px 0px;
                }}
                QPushButton:hover {{ background-color: {desat_hex('#CC0000')}; }}
                QPushButton:pressed {{ background-color: {desat_hex('#990000')}; }}
            """)

    # --- 5. Title bar height ---
    if hasattr(gui, 'chart_title_widget'):
        gui.chart_title_widget.setFixedHeight(32 if compact else 55)


def refresh_chart_title_theme(gui):
    """
    Refresh chart title widget theme after theme change.
    Called from core_gui_qt.py when theme changes.

    Args:
        gui: The parent ChartGUI instance
    """
    theme = get_theme_colors()

    if hasattr(gui, 'chart_title_label'):
        # Update pill button styling
        gui.chart_title_label.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["primary_text"]};
                font-size: {scaled_area_px('panel_titles')}px;
                font-weight: bold;
                border: 1px solid {theme["primary"]};
                border-radius: 20px;
                padding: 8px 24px;
                text-transform: none;
            }}
            QPushButton:hover {{
                background-color: {theme["primary"]};
                border: 1px solid {theme["primary_light"]};
            }}
        """)

    if hasattr(gui, 'chart_close_button'):
        # Update close button styling (modern clean design)
        gui.chart_close_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {desat_hex(STATUS["error"])};
                color: #FFFFFF;
                border: none;
                border-radius: 19px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 500;
                font-family: 'Inter', 'Segoe UI', 'Arial', sans-serif;
                padding: 0px 0px 2px 0px;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {desat_hex('#CC0000')};
            }}
            QPushButton:pressed {{
                background-color: {desat_hex('#990000')};
            }}
        """)

    # Consistent button style for ALL title bar buttons:
    # - theme secondary background with primary (accent) border
    # - hover: accent color background with proper text contrast
    btn_style = f"""
        QPushButton {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            font-size: {scaled_area_px('buttons')}px;
            border: 1px solid {theme["primary"]};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QPushButton:hover {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
            border: 1px solid {theme["primary_light"]};
        }}
        QPushButton:pressed {{
            background-color: {theme["primary_dark"]};
            color: {theme["primary_text"]};
        }}
    """

    # Checkable button style (Transit, Dual Rim) — adds checked state
    checkable_style = btn_style + f"""
        QPushButton:checked {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
            border: 2px solid {theme["primary_light"]};
        }}
    """

    # Apply to ALL left-side buttons
    for attr in ('wheel_btn', 'open_in_kala_btn', 'chart_info_btn', 'now_btn'):
        btn = getattr(gui, attr, None)
        if btn:
            btn.setStyleSheet(btn_style)

    # Apply to checkable buttons
    for attr in ('transit_btn', 'dual_rim_btn'):
        btn = getattr(gui, attr, None)
        if btn:
            # SPEC-TRN-006 B-6: clear any live drop-hover snapshot first, so a
            # theme refresh mid-drag cannot leave the button restoring a stale
            # captured stylesheet on drag-leave.
            _exit = getattr(btn, '_exit_drop_look', None)
            if callable(_exit):
                _exit()
            btn.setStyleSheet(checkable_style)

    # SPEC-TRN-006: re-theme the overlay chip.
    _style_overlay_chip(gui)

    # Apply to inactive-style buttons (with min-width)
    inactive_style = btn_style.replace("padding: 8px 12px;", "padding: 8px 12px; min-width: 100px;")
    for attr in ('add_chart_btn', 'search_btn', 'time_adjust_btn', 'human_design_btn'):
        btn = getattr(gui, attr, None)
        if btn:
            btn.setStyleSheet(inactive_style)

    # Update toggle button styles (Aditya/Tropical — active green vs inactive)
    if hasattr(gui, '_update_toggle_button_styles'):
        gui._update_toggle_button_styles()



# =============================================================================
# Wikipedia Biography Feature
# =============================================================================

def _debug_log(msg):
    """Write debug message to both console and log file."""
    print(msg)
    try:
        import os
        log_path = os.path.expanduser("~/chart_info_debug.log")
        with open(log_path, "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except:
        pass


# ChartInfoWorker + ChartInfoDialog were extracted to a dedicated module
# (SPEC-IMPORT-001 §7.2, bead td-clt6.12) to keep this file focused.
# They are imported here so existing references in this file (the panel
# button wiring and _fetch_chart_info below) keep working unchanged.
# Dependency is one-way: chart_info_dialog does NOT import this module.
from apps.widgets.chart_info_dialog import ChartInfoDialog


def _fetch_chart_info(gui):
    """
    Open the Chart Info dialog for the current chart (SPEC-IMPORT-001 §7.3).

    Section A (metadata: Rodden, tags, source format, notes) is shown
    immediately. Section B (the Wikipedia biography) is fetched on demand
    via the "Search Wikipedia" button inside the dialog.

    Args:
        gui: The main GUI instance with current_chart_data / current_chart_path
    """
    # Clear debug log
    try:
        import os
        log_path = os.path.expanduser("~/chart_info_debug.log")
        with open(log_path, "w") as f:
            f.write("=== Chart Info Debug Log ===\n")
    except:
        pass

    # Require a chart, but NOT a name — Section A (metadata) is useful even
    # for unnamed charts; only the Wikipedia search needs a name.
    if not hasattr(gui, 'current_chart_data') or not gui.current_chart_data:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(gui, "No Chart Loaded", "Please load a chart first.")
        return

    chart_data = gui.current_chart_data
    chart_path = getattr(gui, 'current_chart_path', None)
    _debug_log(f"[ChartInfo DEBUG] Opening Chart Info for: "
               f"'{chart_data.get('name', '')}' path={chart_path}")

    dialog = ChartInfoDialog(gui, chart_data=chart_data, chart_path=chart_path)
    dialog.exec()
    dialog.deleteLater()
