#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Chart Title Widget
Displays chart name with close button (centered above chart)
"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QMenu,
    QDialog, QTextEdit, QApplication, QProgressBar, QScrollArea, QFrame,
    QLineEdit, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QPixmap

# Import centralized theme
from ui.qt_theme import (
    TEXT_PRIMARY, TEXT_SECONDARY, STATUS, SURFACE, BG, BORDER,
    get_theme_colors, get_secondary_button_style, FONT_MONO, scaled_px, scaled_size,
    scaled_area_px, scaled_area_size, scaled_area_font
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
        from core.time_utils import revjul
        year, month, day, _ = revjul(jd)
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


def _show_pill_context_menu(gui, button, pos):
    """Right-click menu on the chart name pill button.

    Dynamic sections:
    - Web searches (Wikipedia, Astro-Databank, Google Images)
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
    gui.transit_btn = QPushButton("⟐ Transit")
    gui.transit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.transit_btn.setToolTip("Show current planetary transits overlay")
    gui.transit_btn.setStyleSheet(transit_btn_style)
    gui.transit_btn.setCheckable(True)
    gui.transit_btn.setChecked(False)
    gui.transit_btn.setVisible(True)  # Visible on all chart views (SPEC-TRN-002)
    gui.transit_btn.clicked.connect(gui._toggle_transit_rim)
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

    gui.wiki_bio_btn = QPushButton("📖 WikiBio")
    gui.wiki_bio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.wiki_bio_btn.setToolTip("Fetch complete Wikipedia biography for current chart person")
    gui.wiki_bio_btn.setStyleSheet(left_btn_style)
    gui.wiki_bio_btn.clicked.connect(lambda: _fetch_wiki_bio(gui))
    layout.addWidget(gui.wiki_bio_btn)

    # LEFT SPACER (for centering the name+close group)
    layout.addStretch(1)

    # CENTER: Container for name pill + close button (centered as one unit)
    container = QWidget()
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(10)  # Slightly larger gap between pill and close button

    # Chart title as ROUNDED PILL BUTTON showing full birth info
    # Format: Name | Date Time TZ | Location (IANA) | Asc: Sign Deg°Min'
    gui.chart_title_label = QPushButton("No Chart Loaded")
    gui.chart_title_label.setMinimumWidth(400)
    gui.chart_title_label.setMinimumHeight(40)
    gui.chart_title_label.setCursor(Qt.CursorShape.PointingHandCursor)
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
    gui.chart_title_label.setToolTip("Click: Google Images | Right-click: Web searches")
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
            background-color: {STATUS["error"]};
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
            background-color: #CC0000;
        }}
        QPushButton:pressed {{
            background-color: #990000;
        }}
    """)

    # Connect to close method directly
    gui.chart_close_button.clicked.connect(gui._close_current_chart)

    container_layout.addWidget(gui.chart_close_button)

    # Add container to main layout (centered)
    layout.addWidget(container)

    # MIDDLE SPACER (pushes toggle buttons to the right)
    layout.addStretch(1)

    # RIGHT: Add Chart, Search, Time Adjust, Human Design, Aditya/Tropical toggle buttons
    # Button styles
    active_style = f"""
        QPushButton {{
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            font-size: {scaled_area_px('buttons')}px;
            border: none;
            border-radius: 8px;
            padding: 8px 12px;
            min-width: 100px;
        }}
        QPushButton:hover {{
            background-color: #45A049;
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
        gui.wiki_bio_btn,
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
    - Hides rarely-needed buttons (WikiBio, Random, Open in Kala, etc.)
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
            background-color: #4CAF50; color: white;
            font-weight: bold; font-size: {scaled_area_px('buttons')}px; border: none;
            border-radius: 5px; padding: 2px 6px;
            max-height: 22px;
        }}
        QPushButton:hover {{ background-color: #45A049; }}
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
            background-color: #4CAF50; color: white;
            font-weight: bold; font-size: {scaled_area_px('buttons')}px; border: none;
            border-radius: 8px; padding: 8px 12px; min-width: 100px;
        }}
        QPushButton:hover {{ background-color: #45A049; }}
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
                    background-color: {STATUS["error"]}; color: #FFF;
                    border: none; border-radius: 11px;
                    font-size: {scaled_area_px('buttons')}px; padding: 0;
                }}
                QPushButton:hover {{ background-color: #CC0000; }}
            """)
        else:
            gui.chart_close_button.setFixedSize(38, 38)
            gui.chart_close_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {STATUS["error"]}; color: #FFF;
                    border: none; border-radius: 19px;
                    font-size: {scaled_area_px('buttons')}px; font-weight: 500;
                    padding: 0px 0px 2px 0px;
                }}
                QPushButton:hover {{ background-color: #CC0000; }}
                QPushButton:pressed {{ background-color: #990000; }}
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
                background-color: {STATUS["error"]};
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
                background-color: #CC0000;
            }}
            QPushButton:pressed {{
                background-color: #990000;
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
    for attr in ('wheel_btn', 'open_in_kala_btn', 'wiki_bio_btn', 'now_btn'):
        btn = getattr(gui, attr, None)
        if btn:
            btn.setStyleSheet(btn_style)

    # Apply to checkable buttons
    for attr in ('transit_btn', 'dual_rim_btn'):
        btn = getattr(gui, attr, None)
        if btn:
            btn.setStyleSheet(checkable_style)

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
        log_path = os.path.expanduser("~/wikibio_debug.log")
        with open(log_path, "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except:
        pass

class WikiBioWorker(QThread):
    """
    Background worker thread for fetching complete Wikipedia biography with images.

    Uses Wikipedia API to get full article content and Wikimedia Commons for images.
    """
    finished = Signal(str, str, list)  # Emits (title, content, images) on success
    error = Signal(str)                # Emits error message on failure
    progress = Signal(str)             # Emits progress messages

    # Image filename patterns to SKIP (not photos of people)
    SKIP_PATTERNS = [
        'flag', 'logo', 'icon', 'map', 'coat_of_arms', 'seal', 'emblem',
        'signature', 'autograph', 'chart', 'graph', 'diagram', 'symbol',
        'commons-logo', 'wiki', 'edit-clear', 'question_mark', 'stub',
        'ambox', 'crystal', 'folder', 'gnome', 'nuvola', 'p_', 'pictogram',
        'red_pencil', 'speaker', 'wiktionary', 'wikibooks', 'wikiquote',
        'wikisource', 'location', 'locator', 'position', '.svg'
    ]

    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def run(self):
        """Execute the Wikipedia API call in background thread."""
        import requests
        import re

        try:
            self.progress.emit(f"Searching Wikipedia for '{self.name}'...")

            headers = {"User-Agent": "Varuna360/1.0 (Vedic Astrology App)"}

            # Step 1: Search for the page
            search_url = "https://en.wikipedia.org/w/api.php"
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": self.name,
                "srlimit": 5,
                "format": "json"
            }

            response = requests.get(search_url, params=search_params, headers=headers, timeout=15)
            response.raise_for_status()
            search_data = response.json()

            search_results = search_data.get("query", {}).get("search", [])
            if not search_results:
                self.error.emit(f"No Wikipedia article found for '{self.name}'")
                return

            # Use the first result
            page_title = search_results[0]["title"]
            self.progress.emit(f"Found: {page_title}")

            # Step 2: Get article content AND image list
            self.progress.emit(f"Fetching complete article...")

            content_params = {
                "action": "parse",
                "page": page_title,
                "prop": "text|images",  # Added images
                "format": "json",
                "disabletoc": "true"
            }

            content_response = requests.get(search_url, params=content_params, headers=headers, timeout=30)
            content_response.raise_for_status()
            content_data = content_response.json()

            if "error" in content_data:
                self.error.emit(f"Error fetching article: {content_data['error'].get('info', 'Unknown error')}")
                return

            parse_data = content_data.get("parse", {})
            html_content = parse_data.get("text", {}).get("*", "")
            image_list = parse_data.get("images", [])

            if not html_content:
                self.error.emit(f"No content found for '{page_title}'")
                return

            # Convert HTML to clean text
            clean_text = self._html_to_text(html_content)

            if not clean_text.strip():
                self.error.emit(f"Could not extract text from '{page_title}'")
                return

            # Step 3: Fetch images from Wikimedia Commons
            self.progress.emit("Fetching images...")
            images_data = self._fetch_images(image_list, headers)

            _debug_log(f"[WikiBio DEBUG] Final images count: {len(images_data)}")
            self.progress.emit("Biography loaded successfully!")
            self.finished.emit(page_title, clean_text, images_data)

        except requests.exceptions.Timeout:
            self.error.emit("Request timed out - Wikipedia may be slow")
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Network error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def _fetch_images(self, image_list: list, headers: dict) -> list:
        """
        Fetch actual image URLs and data from Wikimedia Commons.

        Args:
            image_list: List of image filenames from Wikipedia article
            headers: HTTP headers for requests

        Returns:
            List of dicts with 'url' and 'bytes' keys (up to 5 images)
        """
        import requests

        # Filter out non-photo images
        photo_candidates = []
        _debug_log(f"[WikiBio DEBUG] Total images from article: {len(image_list)}")
        for img_name in image_list:
            img_lower = img_name.lower()
            # Skip if matches any skip pattern
            if any(skip in img_lower for skip in self.SKIP_PATTERNS):
                continue
            # Only keep common image formats (not SVG which are usually icons)
            if img_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                photo_candidates.append(img_name)

        _debug_log(f"[WikiBio DEBUG] Photo candidates after filtering: {len(photo_candidates)}")
        if photo_candidates:
            _debug_log(f"[WikiBio DEBUG] First 3 candidates: {photo_candidates[:3]}")

        if not photo_candidates:
            return []

        # Limit to first 8 candidates to check
        photo_candidates = photo_candidates[:8]

        self.progress.emit(f"Found {len(photo_candidates)} potential photos...")

        # Query Wikimedia Commons for image URLs
        commons_url = "https://en.wikipedia.org/w/api.php"
        images_data = []

        for img_name in photo_candidates:
            if len(images_data) >= 5:  # Max 5 images
                break

            try:
                self.progress.emit(f"Loading image {len(images_data) + 1}...")

                # Get image info (URL)
                info_params = {
                    "action": "query",
                    "titles": f"File:{img_name}",
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "iiurlwidth": 400,  # Request thumbnail at 400px width
                    "format": "json"
                }

                info_response = requests.get(commons_url, params=info_params, headers=headers, timeout=10)
                info_response.raise_for_status()
                info_data = info_response.json()

                pages = info_data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id == "-1":
                        continue  # Image not found

                    imageinfo = page_data.get("imageinfo", [])
                    if imageinfo:
                        img_info = imageinfo[0]
                        # Prefer thumbnail URL if available, else full URL
                        img_url = img_info.get("thumburl") or img_info.get("url")

                        if img_url:
                            _debug_log(f"[WikiBio DEBUG] Downloading: {img_url[:80]}...")
                            # Download the image
                            img_response = requests.get(img_url, headers=headers, timeout=15)
                            img_response.raise_for_status()

                            # Check if it's actually an image (not HTML error page)
                            content_type = img_response.headers.get('content-type', '')
                            _debug_log(f"[WikiBio DEBUG] Content-Type: {content_type}, Size: {len(img_response.content)} bytes")
                            if 'image' in content_type:
                                images_data.append({
                                    'url': img_url,
                                    'bytes': img_response.content,
                                    'name': img_name
                                })
                                _debug_log(f"[WikiBio DEBUG] Image added! Total: {len(images_data)}")

            except Exception as e:
                # Skip failed images, continue with others
                _debug_log(f"[WikiBio] Failed to fetch image {img_name}: {e}")
                continue

        return images_data

    def _html_to_text(self, html: str) -> str:
        """Convert Wikipedia HTML to clean readable text."""
        import re

        text = html

        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove reference tags [1], [2], etc.
        text = re.sub(r'\[(?:edit|citation needed|\d+)\]', '', text)

        # Remove infobox, navbox, sidebar tables (they clutter the text)
        text = re.sub(r'<table[^>]*class="[^"]*(?:infobox|navbox|sidebar|vertical-navbox|wikitable)[^"]*"[^>]*>.*?</table>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove div elements with certain classes (navigation, etc.)
        text = re.sub(r'<div[^>]*class="[^"]*(?:navbox|catlinks|reflist|references|mw-references|toc|thumb|gallery)[^"]*"[^>]*>.*?</div>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Convert headers to readable format
        text = re.sub(r'<h2[^>]*><span[^>]*>([^<]*)</span>.*?</h2>', r'\n\n═══ \1 ═══\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h3[^>]*><span[^>]*>([^<]*)</span>.*?</h3>', r'\n\n─── \1 ───\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h4[^>]*><span[^>]*>([^<]*)</span>.*?</h4>', r'\n\n── \1 ──\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h[1-6][^>]*>([^<]*)</h[1-6]>', r'\n\n═══ \1 ═══\n\n', text)

        # Convert paragraph breaks
        text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text)
        text = re.sub(r'<p[^>]*>', '\n', text)
        text = re.sub(r'</p>', '\n', text)

        # Convert list items
        text = re.sub(r'<li[^>]*>', '\n  • ', text)
        text = re.sub(r'</li>', '', text)

        # Convert line breaks
        text = re.sub(r'<br\s*/?>', '\n', text)

        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode HTML entities
        import html
        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple blank lines to double
        text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single
        text = re.sub(r' +\n', '\n', text)  # Trailing spaces
        text = re.sub(r'\n +', '\n', text)  # Leading spaces on lines

        # Remove "See also", "References", "External links" sections and everything after
        for section in ['See also', 'References', 'External links', 'Further reading', 'Notes']:
            pattern = rf'\n═══ {section} ═══.*'
            text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)

        return text.strip()


class WikiBioDialog(QDialog):
    """
    Dialog window to display Wikipedia biography with images and scrolling text.
    """

    def __init__(self, parent, title: str, content: str, images: list = None):
        super().__init__(parent)

        self.setWindowTitle(f"Wikipedia: {title}")
        self.setMinimumSize(900, 700)
        self.resize(1000, 800)

        # Dark theme styling
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title label
        title_label = QLabel(f"📖 {title}")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: {scaled_area_px('panel_titles')}px;
                font-weight: bold;
                padding-bottom: 8px;
            }}
        """)
        layout.addWidget(title_label)

        # Images section (if images available)
        _debug_log(f"[WikiBio DEBUG] Dialog received images: {len(images) if images else 0}")
        if images:
            self._add_images_section(layout, images)

        # Biography text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(content)
        self.text_edit.setFont(scaled_area_font('info_text', family="Segoe UI"))
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 12px;
                selection-background-color: #3C6E9E;
            }}
            QScrollBar:vertical {{
                background-color: {SURFACE};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #555;
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #666;
            }}
        """)
        layout.addWidget(self.text_edit, stretch=1)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Image count info
        if images:
            img_info = QLabel(f"📷 {len(images)} images from Wikimedia Commons")
            img_info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('info_text')}px;")
            button_layout.addWidget(img_info)
            button_layout.addSpacing(20)

        # Copy button
        copy_btn = QPushButton("📋 Copy to Clipboard")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3C6E9E;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4A7FB0;
            }}
        """)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(content))
        button_layout.addWidget(copy_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #555;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: #666;
            }}
        """)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _add_images_section(self, parent_layout, images: list):
        """
        Add a horizontal scrollable image gallery at the top.

        Args:
            parent_layout: The parent QVBoxLayout
            images: List of dicts with 'bytes' key containing image data
        """
        # Container frame for images
        images_frame = QFrame()
        images_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        images_frame.setFixedHeight(220)

        # Scroll area for horizontal scrolling
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:horizontal {{
                background-color: {SURFACE};
                height: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: #555;
                border-radius: 5px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: #666;
            }}
        """)

        # Container widget for images
        images_container = QWidget()
        images_layout = QHBoxLayout(images_container)
        images_layout.setContentsMargins(10, 10, 10, 10)
        images_layout.setSpacing(15)

        # Add each image
        _debug_log(f"[WikiBio DEBUG] _add_images_section: Processing {len(images)} images")
        for idx, img_data in enumerate(images):
            try:
                img_bytes = img_data.get('bytes')
                if not img_bytes:
                    _debug_log(f"[WikiBio DEBUG] Image {idx}: No bytes!")
                    continue

                _debug_log(f"[WikiBio DEBUG] Image {idx}: {len(img_bytes)} bytes")

                # Create QPixmap from bytes
                pixmap = QPixmap()
                loaded = pixmap.loadFromData(img_bytes)
                _debug_log(f"[WikiBio DEBUG] Image {idx}: loadFromData returned {loaded}")

                if pixmap.isNull():
                    _debug_log(f"[WikiBio DEBUG] Image {idx}: Pixmap is NULL!")
                    continue

                _debug_log(f"[WikiBio DEBUG] Image {idx}: Pixmap size {pixmap.width()}x{pixmap.height()}")

                # Scale to fit height while maintaining aspect ratio
                scaled_pixmap = pixmap.scaledToHeight(
                    180,
                    Qt.TransformationMode.SmoothTransformation
                )

                # Create label with rounded corners effect
                img_label = QLabel()
                img_label.setPixmap(scaled_pixmap)
                img_label.setStyleSheet(f"""
                    QLabel {{
                        background-color: #1A1A1A;
                        border: 2px solid {BORDER};
                        border-radius: 8px;
                        padding: 4px;
                    }}
                """)
                img_label.setToolTip(img_data.get('name', 'Wikipedia image'))

                images_layout.addWidget(img_label)
                _debug_log(f"[WikiBio DEBUG] Image {idx}: Widget added to layout!")

            except Exception as e:
                _debug_log(f"[WikiBio] Error displaying image: {e}")
                import traceback
                _debug_log(f"[WikiBio] Traceback: {traceback.format_exc()}")
                continue

        _debug_log(f"[WikiBio DEBUG] _add_images_section: Loop complete, adding stretch")
        images_layout.addStretch()  # Push images to the left

        scroll_area.setWidget(images_container)
        _debug_log(f"[WikiBio DEBUG] _add_images_section: scroll_area widget set")

        # Layout for the frame
        frame_layout = QVBoxLayout(images_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(scroll_area)

        parent_layout.addWidget(images_frame)
        _debug_log(f"[WikiBio DEBUG] _add_images_section: COMPLETE - images_frame added to parent")

    def _copy_to_clipboard(self, content: str):
        """Copy biography content to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        # Brief visual feedback would be nice but keeping it simple


def _fetch_wiki_bio(gui):
    """
    Fetch and display Wikipedia biography for the current chart person.

    Args:
        gui: The main GUI instance with current_chart_data
    """
    # Clear debug log
    try:
        import os
        log_path = os.path.expanduser("~/wikibio_debug.log")
        with open(log_path, "w") as f:
            f.write("=== WikiBio Debug Log ===\n")
    except:
        pass

    # Get current chart name
    if not hasattr(gui, 'current_chart_data') or not gui.current_chart_data:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(gui, "No Chart Loaded", "Please load a chart first.")
        return

    name = gui.current_chart_data.get('name', '')
    _debug_log(f"[WikiBio DEBUG] Searching for: '{name}'")
    if not name or name == "Unknown":
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(gui, "No Name", "Current chart has no name to search.")
        return

    # Show loading dialog
    loading_dialog = QDialog(gui)
    loading_dialog.setWindowTitle("Loading Wikipedia Biography")
    loading_dialog.setFixedSize(400, 120)
    loading_dialog.setStyleSheet(f"QDialog {{ background-color: {BG}; }}")

    loading_layout = QVBoxLayout(loading_dialog)
    loading_layout.setContentsMargins(20, 20, 20, 20)

    loading_label = QLabel(f"🔍 Searching Wikipedia for '{name}'...")
    loading_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: {scaled_area_px('info_text')}px;")
    loading_layout.addWidget(loading_label)

    progress_bar = QProgressBar()
    progress_bar.setRange(0, 0)  # Indeterminate
    progress_bar.setStyleSheet(f"""
        QProgressBar {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 4px;
            height: 20px;
        }}
        QProgressBar::chunk {{
            background-color: #3C6E9E;
        }}
    """)
    loading_layout.addWidget(progress_bar)

    # Create worker
    worker = WikiBioWorker(name)

    def on_progress(msg):
        loading_label.setText(f"🔍 {msg}")

    def _cleanup_worker():
        """Disconnect signals and schedule worker for deletion."""
        try:
            worker.progress.disconnect(on_progress)
            worker.finished.disconnect(on_finished)
            worker.error.disconnect(on_error)
        except RuntimeError:
            pass
        worker.deleteLater()
        gui._wiki_bio_worker = None

    def on_finished(title, content, images):
        _debug_log(f"[WikiBio DEBUG] on_finished called with {len(images) if images else 0} images")
        _cleanup_worker()
        loading_dialog.accept()
        bio_dialog = WikiBioDialog(gui, title, content, images)
        bio_dialog.exec()
        bio_dialog.deleteLater()

    def on_error(error_msg):
        _cleanup_worker()
        loading_dialog.accept()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(gui, "Wikipedia Error", error_msg)

    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.error.connect(on_error)

    # Store worker reference to prevent garbage collection during fetch
    gui._wiki_bio_worker = worker
    worker.start()

    # Show loading dialog (blocks until finished or error)
    result = loading_dialog.exec()
    # If user closed dialog manually before worker finished, clean up
    if gui._wiki_bio_worker is not None:
        _cleanup_worker()
