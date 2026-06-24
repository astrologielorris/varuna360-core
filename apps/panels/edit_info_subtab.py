# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Edit Info Sub-tab - Form-based chart information editor

This sub-tab provides a comprehensive form for editing all chart fields:
- Name and Gender
- Date (MM/DD/YYYY)
- Time with Local/UTC toggle and dual-field sync
- Location (City, Country)
- Coordinates (Latitude, Longitude with cardinal directions)
- Timezone and DST settings

Supports bidirectional Local ↔ UTC time synchronization.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QRadioButton, QButtonGroup, QPushButton, QLabel,
    QScrollArea, QFrame, QGroupBox, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator

# Theme imports - use dynamic colors for proper light/dark support
from ui.qt_theme import get_theme_colors, BORDER, scaled_area_px

# Time conversion utilities (extracted to core/)
from core.time_utils import local_to_utc, utc_to_local, invert_chtk_timezone, format_offset
HAS_TIME_UTILS = True

class EditInfoSubTab(QWidget):
    """
    Form-based chart information editor.

    Signals:
        data_changed(): Emitted when any field changes
        location_changed(float, float): Emitted when coordinates change (lat, lon)
        save_requested(): Emitted when Save button clicked
        cancel_requested(): Emitted when Cancel button clicked
    """

    data_changed = Signal()
    location_changed = Signal(float, float)
    save_requested = Signal()
    cancel_requested = Signal()
    map_view_requested = Signal()  # Navigate to Map View subtab

    def __init__(self, parent_panel):
        super().__init__()

        self.parent_panel = parent_panel
        self.time_mode = "Local"  # "Local" or "UTC"
        self._syncing = False  # Prevent recursive sync

        self._group_frames = []  # Store group frames for theme refresh
        self._group_labels = []  # Store group labels for theme refresh
        self._create_ui()
        self._setup_validators()
        self._setup_bindings()

    def _create_ui(self):
        """Create the form UI"""
        # Get dynamic theme colors
        theme = get_theme_colors()
        bg = theme['secondary_dark']

        # Main layout with scroll
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        self._scroll = scroll  # Store for theme refresh

        # Content widget
        content = QWidget()
        content.setStyleSheet(f"background: {bg};")
        self._content = content  # Store for theme refresh
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # === Title ===
        self._title_label = QLabel("Edit Chart Information")
        self._title_label.setStyleSheet(f"""
            font-size: {scaled_area_px('panel_titles')}px;
            font-weight: bold;
            color: {theme['secondary_text']};
            padding: 10px 0;
        """)
        content_layout.addWidget(self._title_label)

        # === Name Section ===
        name_group = self._create_group("Full Name:")
        name_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter person's name")
        self._style_input(self.name_input)
        name_layout.addWidget(self.name_input)
        name_group.layout().addLayout(name_layout)
        content_layout.addWidget(name_group)

        # === Date Section ===
        date_group = self._create_group("Date (month/day/year):")
        date_layout = QHBoxLayout()

        self.date_month = QLineEdit()
        self.date_month.setPlaceholderText("MM")
        self.date_month.setMaximumWidth(60)
        self._style_input(self.date_month)

        self.date_day = QLineEdit()
        self.date_day.setPlaceholderText("DD")
        self.date_day.setMaximumWidth(60)
        self._style_input(self.date_day)

        self.date_year = QLineEdit()
        self.date_year.setPlaceholderText("YYYY")
        self.date_year.setMaximumWidth(80)
        self._style_input(self.date_year)

        date_layout.addWidget(self.date_month)
        date_layout.addWidget(QLabel("/"))
        date_layout.addWidget(self.date_day)
        date_layout.addWidget(QLabel("/"))
        date_layout.addWidget(self.date_year)

        format_label = QLabel("(MM/DD/YYYY)")
        format_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px; opacity: 0.7;")
        date_layout.addWidget(format_label)
        date_layout.addStretch()

        date_group.layout().addLayout(date_layout)
        content_layout.addWidget(date_group)

        # === Time Format Toggle ===
        time_toggle_group = self._create_group("Time Format:")
        time_toggle_layout = QHBoxLayout()

        self.time_mode_group = QButtonGroup(self)
        self.local_radio = QRadioButton("🏠 Local Time")
        self.utc_radio = QRadioButton("🌐 UTC Time")
        self.local_radio.setChecked(True)

        self._style_radio(self.local_radio)
        self._style_radio(self.utc_radio)

        self.time_mode_group.addButton(self.local_radio, 0)
        self.time_mode_group.addButton(self.utc_radio, 1)

        time_toggle_layout.addWidget(self.local_radio)
        time_toggle_layout.addWidget(self.utc_radio)
        time_toggle_layout.addStretch()

        time_toggle_group.layout().addLayout(time_toggle_layout)
        content_layout.addWidget(time_toggle_group)

        # === Local Time Section ===
        local_group = self._create_group("🏠 Local Time:")
        local_layout = QHBoxLayout()

        self.local_hour = QLineEdit()
        self.local_hour.setPlaceholderText("HH")
        self.local_hour.setMaximumWidth(50)
        self._style_input(self.local_hour)

        self.local_minute = QLineEdit()
        self.local_minute.setPlaceholderText("MM")
        self.local_minute.setMaximumWidth(50)
        self._style_input(self.local_minute)

        self.local_second = QLineEdit()
        self.local_second.setPlaceholderText("SS")
        self.local_second.setMaximumWidth(50)
        self._style_input(self.local_second)

        local_layout.addWidget(self.local_hour)
        local_layout.addWidget(QLabel(":"))
        local_layout.addWidget(self.local_minute)
        local_layout.addWidget(QLabel(":"))
        local_layout.addWidget(self.local_second)

        local_format = QLabel("(HH:MM:SS)")
        local_format.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px; opacity: 0.7;")
        local_layout.addWidget(local_format)
        local_layout.addStretch()

        local_group.layout().addLayout(local_layout)
        self.local_time_group = local_group
        content_layout.addWidget(local_group)

        # === UTC Time Section ===
        utc_group = self._create_group("🌐 UTC Time:")
        utc_layout = QHBoxLayout()

        self.utc_hour = QLineEdit()
        self.utc_hour.setPlaceholderText("HH")
        self.utc_hour.setMaximumWidth(50)
        self._style_input(self.utc_hour, readonly=True)

        self.utc_minute = QLineEdit()
        self.utc_minute.setPlaceholderText("MM")
        self.utc_minute.setMaximumWidth(50)
        self._style_input(self.utc_minute, readonly=True)

        self.utc_second = QLineEdit()
        self.utc_second.setPlaceholderText("SS")
        self.utc_second.setMaximumWidth(50)
        self._style_input(self.utc_second, readonly=True)

        utc_layout.addWidget(self.utc_hour)
        utc_layout.addWidget(QLabel(":"))
        utc_layout.addWidget(self.utc_minute)
        utc_layout.addWidget(QLabel(":"))
        utc_layout.addWidget(self.utc_second)

        utc_format = QLabel("(HH:MM:SS)")
        utc_format.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px; opacity: 0.7;")
        utc_layout.addWidget(utc_format)

        # Day offset indicator - use primary_light for visibility
        self.utc_day_offset = QLabel("")
        self.utc_day_offset.setStyleSheet(f"color: {theme['primary_light']}; font-weight: bold;")
        utc_layout.addWidget(self.utc_day_offset)
        utc_layout.addStretch()

        utc_group.layout().addLayout(utc_layout)
        self.utc_time_group = utc_group
        content_layout.addWidget(utc_group)

        # === Gender Section ===
        gender_group = self._create_group("Gender:")
        gender_layout = QHBoxLayout()

        self.gender_group = QButtonGroup(self)
        self.male_radio = QRadioButton("Male")
        self.female_radio = QRadioButton("Female")

        self._style_radio(self.male_radio)
        self._style_radio(self.female_radio)

        self.gender_group.addButton(self.male_radio, 0)
        self.gender_group.addButton(self.female_radio, 1)

        gender_layout.addWidget(self.male_radio)
        gender_layout.addWidget(self.female_radio)
        gender_layout.addStretch()

        gender_group.layout().addLayout(gender_layout)
        content_layout.addWidget(gender_group)

        # === Location Section ===
        location_group = self._create_group("Birth Location:")

        # Hidden inputs for data storage (set by map, read by save)
        self.country_input = QLineEdit()
        self.country_input.setVisible(False)
        self.city_input = QLineEdit()
        self.city_input.setVisible(False)

        # Location display + Use Map button
        location_btn_layout = QHBoxLayout()
        self.location_display_label = QLabel("")
        theme = get_theme_colors()
        self.location_display_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; padding: 4px;")
        location_btn_layout.addWidget(self.location_display_label, 1)

        self.use_map_btn = QPushButton("Use Map")
        self.use_map_btn.setToolTip("Select location on interactive map")
        self.use_map_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.use_map_btn.clicked.connect(self._on_open_map_clicked)
        self._style_secondary_button(self.use_map_btn)
        location_btn_layout.addWidget(self.use_map_btn)

        location_group.layout().addLayout(location_btn_layout)
        content_layout.addWidget(location_group)

        # === Coordinates Section ===
        coords_group = self._create_group("Coordinates:")
        coords_layout = QGridLayout()

        # Latitude
        coords_layout.addWidget(QLabel("Latitude:"), 0, 0)
        self.latitude_input = QLineEdit()
        self.latitude_input.setPlaceholderText("e.g., 48.983333")
        self._style_input(self.latitude_input)
        coords_layout.addWidget(self.latitude_input, 0, 1)

        # Longitude
        coords_layout.addWidget(QLabel("Longitude:"), 1, 0)
        self.longitude_input = QLineEdit()
        self.longitude_input.setPlaceholderText("e.g., 2.266667")
        self._style_input(self.longitude_input)
        coords_layout.addWidget(self.longitude_input, 1, 1)

        # Open Map button
        self.open_map_btn = QPushButton("📍 Search or Pick on Map")
        self.open_map_btn.setToolTip("Search a city or click on the interactive map to set coordinates")
        self.open_map_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_map_btn.clicked.connect(self._on_open_map_clicked)
        self._style_secondary_button(self.open_map_btn)
        coords_layout.addWidget(self.open_map_btn, 2, 0, 1, 2)

        coords_group.layout().addLayout(coords_layout)
        content_layout.addWidget(coords_group)

        # === Timezone Section ===
        tz_group = self._create_group("Timezone:")
        tz_layout = QHBoxLayout()

        # IANA timezone name (e.g., "America/Chicago")
        self.timezone_iana_input = QLineEdit()
        self.timezone_iana_input.setPlaceholderText("e.g., America/Chicago")
        self.timezone_iana_input.setMinimumWidth(150)
        self._style_input(self.timezone_iana_input)
        tz_layout.addWidget(self.timezone_iana_input)

        # UTC offset (e.g., "-06:00")
        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("(±HH:MM format)")
        self.timezone_input.setMaximumWidth(120)
        self._style_input(self.timezone_input)
        tz_layout.addWidget(self.timezone_input)

        tz_layout.addStretch()

        tz_group.layout().addLayout(tz_layout)
        self.timezone_group = tz_group
        content_layout.addWidget(tz_group)

        # === Daylight Saving Time Section ===
        dst_group = self._create_group("Daylight Saving Time:")
        dst_layout = QHBoxLayout()

        self.dst_group = QButtonGroup(self)
        self.dst_none = QRadioButton("No (0)")
        self.dst_yes = QRadioButton("Yes (1)")
        self.dst_war = QRadioButton("War Time (2)")
        self.dst_none.setChecked(True)

        self._style_radio(self.dst_none)
        self._style_radio(self.dst_yes)
        self._style_radio(self.dst_war)

        self.dst_group.addButton(self.dst_none, 0)
        self.dst_group.addButton(self.dst_yes, 1)
        self.dst_group.addButton(self.dst_war, 2)

        dst_layout.addWidget(self.dst_none)
        dst_layout.addWidget(self.dst_yes)
        dst_layout.addWidget(self.dst_war)
        dst_layout.addStretch()

        dst_group.layout().addLayout(dst_layout)
        self.dst_widget_group = dst_group
        content_layout.addWidget(dst_group)

        # === Action Buttons ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['primary']};
                color: white;
                padding: 12px 30px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                padding: 12px 30px;
                border: 1px solid {theme['secondary_dark']};
                border-radius: 6px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: {theme['secondary_light']};
            }}
        """)

        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()

        content_layout.addSpacing(20)
        content_layout.addLayout(button_layout)
        content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_group(self, title: str) -> QFrame:
        """Create a styled group box with dynamic theme colors"""
        theme = get_theme_colors()
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        self._group_frames.append(frame)  # Store for theme refresh

        layout = QVBoxLayout(frame)
        layout.setSpacing(8)

        label = QLabel(title)
        label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; border: none;")
        self._group_labels.append(label)  # Store for theme refresh
        layout.addWidget(label)

        return frame

    def _style_input(self, widget: QLineEdit, readonly: bool = False):
        """Apply consistent styling to input fields with dynamic theme"""
        theme = get_theme_colors()
        # For readonly, use a lighter/darker shade depending on theme
        bg = theme['secondary_light'] if readonly else theme['secondary']
        text_color = theme['secondary_text']

        widget.setStyleSheet(f"""
            QLineEdit {{
                background-color: {bg};
                color: {text_color};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 8px;
                font-size: {scaled_area_px('tables')}px;
            }}
            QLineEdit:focus {{
                border-color: {theme['primary']};
            }}
            QLineEdit:read-only {{
                background-color: {theme['secondary_light']};
                color: {text_color};
                opacity: 0.7;
            }}
        """)
        if readonly:
            widget.setReadOnly(True)

    def _style_radio(self, widget: QRadioButton):
        """Apply consistent styling to radio buttons with dynamic theme"""
        theme = get_theme_colors()
        widget.setStyleSheet(f"""
            QRadioButton {{
                color: {theme['secondary_text']};
                spacing: 8px;
                padding: 5px;
            }}
            QRadioButton::indicator {{
                width: 18px;
                height: 18px;
            }}
        """)

    def _style_secondary_button(self, widget: QPushButton):
        """Apply secondary button styling (gray/neutral) with dynamic theme"""
        theme = get_theme_colors()
        widget.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['primary_text']};
                border: 1px solid {BORDER};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: {theme['secondary_dark']};
                border-color: {theme['primary']};
            }}
            QPushButton:pressed {{
                background-color: {theme['primary_dark']};
            }}
        """)

    def _setup_validators(self):
        """Add input validators"""
        # Date validators
        self.date_month.setValidator(QIntValidator(1, 12))
        self.date_day.setValidator(QIntValidator(1, 31))
        self.date_year.setValidator(QIntValidator(1, 9999))

        # Time validators
        self.local_hour.setValidator(QIntValidator(0, 23))
        self.local_minute.setValidator(QIntValidator(0, 59))
        self.local_second.setValidator(QIntValidator(0, 59))
        self.utc_hour.setValidator(QIntValidator(0, 23))
        self.utc_minute.setValidator(QIntValidator(0, 59))
        self.utc_second.setValidator(QIntValidator(0, 59))

        # Coordinate validators
        self.latitude_input.setValidator(QDoubleValidator(-90, 90, 6))
        self.longitude_input.setValidator(QDoubleValidator(-180, 180, 6))

    def _setup_bindings(self):
        """Connect signals for field synchronization"""
        # Time mode toggle (both radios needed so clicking UTC fires the slot)
        self.local_radio.toggled.connect(self._on_time_mode_changed)
        self.utc_radio.toggled.connect(self._on_time_mode_changed)

        # Local time changes -> sync UTC
        self.local_hour.textChanged.connect(self._sync_utc_from_local)
        self.local_minute.textChanged.connect(self._sync_utc_from_local)
        self.local_second.textChanged.connect(self._sync_utc_from_local)

        # UTC time changes -> sync Local (when in UTC mode)
        self.utc_hour.textChanged.connect(self._sync_local_from_utc)
        self.utc_minute.textChanged.connect(self._sync_local_from_utc)
        self.utc_second.textChanged.connect(self._sync_local_from_utc)

        # Timezone/DST changes -> re-sync
        self.timezone_input.textChanged.connect(self._on_timezone_changed)
        self.dst_group.buttonClicked.connect(self._on_dst_changed)

        # Date changes -> re-sync (date can affect UTC conversion)
        self.date_year.textChanged.connect(self._sync_utc_from_local)
        self.date_month.textChanged.connect(self._sync_utc_from_local)
        self.date_day.textChanged.connect(self._sync_utc_from_local)

        # Coordinate changes -> emit signal
        self.latitude_input.textChanged.connect(self._on_coordinates_changed)
        self.longitude_input.textChanged.connect(self._on_coordinates_changed)

        # All field changes -> mark modified
        for widget in [self.name_input, self.date_month, self.date_day, self.date_year,
                       self.local_hour, self.local_minute, self.local_second,
                       self.country_input, self.city_input,
                       self.latitude_input, self.longitude_input, self.timezone_input]:
            widget.textChanged.connect(lambda: self.data_changed.emit() if not self._syncing else None)

        # Button connections
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)

    # =========================================================================
    # TIME MODE HANDLING
    # =========================================================================

    @Slot(bool)
    def _on_time_mode_changed(self, checked: bool):
        """Handle Local/UTC toggle"""
        if not checked:  # Only process when becoming checked
            return

        is_local = self.local_radio.isChecked()
        self.time_mode = "Local" if is_local else "UTC"

        # Update field states
        self._update_time_field_states()

        # Trigger sync
        if is_local:
            self._sync_utc_from_local()
        else:
            self._sync_local_from_utc()

    def _check_gender_warning(self):
        """
        Check if gender is missing (debug only, no UI warning).
        """
        is_gender_set = self.male_radio.isChecked() or self.female_radio.isChecked()

    def _update_time_field_states(self):
        """Update which time fields are editable based on mode"""
        is_local = self.time_mode == "Local"

        # Local fields
        for widget in [self.local_hour, self.local_minute, self.local_second]:
            widget.setReadOnly(not is_local)
            self._style_input(widget, readonly=not is_local)

        # UTC fields
        for widget in [self.utc_hour, self.utc_minute, self.utc_second]:
            widget.setReadOnly(is_local)
            self._style_input(widget, readonly=is_local)

        # DST is only relevant in Local mode
        theme = get_theme_colors()
        for btn in [self.dst_none, self.dst_yes, self.dst_war]:
            btn.setEnabled(is_local)
            if not is_local:
                btn.setStyleSheet(f"""
                    QRadioButton {{
                        color: {theme['secondary_text']};
                        spacing: 8px;
                        padding: 5px;
                        opacity: 0.5;
                    }}
                """)
            else:
                self._style_radio(btn)

        # Timezone is only relevant in Local mode
        self.timezone_input.setEnabled(is_local)
        self._style_input(self.timezone_input, readonly=not is_local)

    # =========================================================================
    # TIME SYNCHRONIZATION
    # =========================================================================

    @Slot()
    def _sync_utc_from_local(self):
        """Convert local time to UTC and update UTC fields"""
        if self._syncing or self.time_mode != "Local":
            return

        if not HAS_TIME_UTILS:
            return

        self._syncing = True
        try:
            # Get local time
            hour = int(self.local_hour.text() or 0)
            minute = int(self.local_minute.text() or 0)
            second = int(self.local_second.text() or 0)

            # Get date
            year = int(self.date_year.text() or 2000)
            month = int(self.date_month.text() or 1)
            day = int(self.date_day.text() or 1)

            # Get timezone (invert CHTK format if needed)
            tz_str = self.timezone_input.text().strip() or "+00:00"
            # Note: If stored in CHTK format, invert first
            # We assume user enters standard format (+01:00 = UTC+1)

            # Get DST flag as int (0/1/2), not bool
            dst_flag = self.dst_group.checkedId()
            if dst_flag < 0:
                dst_flag = 0

            # Convert
            utc_result = local_to_utc(year, month, day, hour, minute, second, tz_str, dst_flag)

            # Update UTC fields
            self.utc_hour.setText(f"{utc_result[3]:02d}")
            self.utc_minute.setText(f"{utc_result[4]:02d}")
            self.utc_second.setText(f"{utc_result[5]:02d}")

            # Check for date rollover
            from datetime import date
            local_date = date(year, month, day)
            utc_date = date(utc_result[0], utc_result[1], utc_result[2])
            day_diff = (utc_date - local_date).days

            if day_diff == -1:
                self.utc_day_offset.setText("(-1d)")
            elif day_diff == 1:
                self.utc_day_offset.setText("(+1d)")
            elif day_diff != 0:
                self.utc_day_offset.setText(f"({day_diff:+d}d)")
            else:
                self.utc_day_offset.setText("")

        except (ValueError, TypeError):
            pass  # Silently ignore invalid input during typing
        finally:
            self._syncing = False

    @Slot()
    def _sync_local_from_utc(self):
        """Convert UTC time to local and update local fields"""
        if self._syncing or self.time_mode != "UTC":
            return

        if not HAS_TIME_UTILS:
            return

        self._syncing = True
        try:
            # Get UTC time
            hour = int(self.utc_hour.text() or 0)
            minute = int(self.utc_minute.text() or 0)
            second = int(self.utc_second.text() or 0)

            # Get date
            year = int(self.date_year.text() or 2000)
            month = int(self.date_month.text() or 1)
            day = int(self.date_day.text() or 1)

            # Get timezone
            tz_str = self.timezone_input.text().strip() or "+00:00"

            # Get DST flag as int (0/1/2), not bool
            dst_flag = self.dst_group.checkedId()
            if dst_flag < 0:
                dst_flag = 0

            # Convert
            local_result = utc_to_local(year, month, day, hour, minute, second, tz_str, dst_flag)

            # Update local fields
            self.local_hour.setText(f"{local_result[3]:02d}")
            self.local_minute.setText(f"{local_result[4]:02d}")
            self.local_second.setText(f"{local_result[5]:02d}")

        except (ValueError, TypeError):
            pass
        finally:
            self._syncing = False

    @Slot()
    def _on_timezone_changed(self, text: str = ""):
        """Re-sync when timezone changes"""
        if self._syncing:
            return
        if self.time_mode == "Local":
            self._sync_utc_from_local()
        self.data_changed.emit()

    @Slot()
    def _on_dst_changed(self, button=None):
        """Re-sync when DST changes"""
        if self._syncing:
            return
        if self.time_mode == "Local":
            self._sync_utc_from_local()
        self.data_changed.emit()

    @Slot()
    def _on_coordinates_changed(self, text: str = ""):
        """Emit location_changed signal when coordinates change"""
        if self._syncing:
            return
        try:
            lat = float(self.latitude_input.text() or 0)
            lon = float(self.longitude_input.text() or 0)
            self.location_changed.emit(lat, lon)
        except ValueError:
            pass
        self.data_changed.emit()

    @Slot()
    def _on_open_map_clicked(self):
        """Handle Open Map button click - navigate to Map View subtab"""
        self.map_view_requested.emit()

    # =========================================================================
    # DATA LOADING
    # =========================================================================

    def _convert_timezone_to_offset(self, tz_str: str, lat: float = None, lon: float = None, birth_dt=None) -> str:
        """Convert timezone string to +HH:MM offset format.

        Delegates to core.time_utils._parse_offset for all parsing, with a
        timezonefinder fallback when IANA lookup fails and coordinates exist.
        """
        from core.time_utils import _parse_offset, format_offset

        if not tz_str:
            return "+00:00"
        tz_str = str(tz_str).strip()
        if tz_str.startswith(('+', '-')) and ':' in tz_str:
            return tz_str

        ref_year = birth_dt.year if birth_dt else 2000
        try:
            h, m = _parse_offset(tz_str, ref_year=ref_year)
        except (ValueError, TypeError):
            h, m = 0, 0

        if h == 0 and m == 0 and '/' in tz_str and lat is not None and lon is not None:
            try:
                from timezonefinder import TimezoneFinder
                tf = TimezoneFinder()
                tz_name = tf.timezone_at(lat=lat, lng=lon)
                if tz_name:
                    h, m = _parse_offset(tz_name, ref_year=ref_year)
            except Exception:
                pass

        return format_offset(h, m)

    def populate_from_chart(self, planets_data: dict, birth_metadata: dict, chart_entry: dict = None, birth_data: dict = None):
        """
        Fill form fields from chart data.

        Args:
            planets_data: Calculated planetary positions (contains birth data from memory panel)
            birth_metadata: Birth information dict (may be empty)
            chart_entry: Full chart entry from memory panel (optional)
            birth_data: Canonical birth_data dict (Single Source of Truth, preferred)
        """
        self._syncing = True  # Prevent sync during population
        try:
            # If we have canonical birth_data, use it as the Single Source of Truth
            if birth_data:
                # === USE CANONICAL BIRTH_DATA ===
                self.name_input.setText(birth_data.get('name', ''))

                # Date - LOCAL date from birth_data
                self.date_year.setText(str(birth_data.get('local_year', '')))
                self.date_month.setText(str(birth_data.get('local_month', '')))
                self.date_day.setText(str(birth_data.get('local_day', '')))

                # Time - LOCAL time from birth_data (not UTC!)
                self.local_hour.setText(f"{birth_data.get('local_hour', 0):02d}")
                self.local_minute.setText(f"{birth_data.get('local_minute', 0):02d}")
                self.local_second.setText(f"{birth_data.get('local_second', 0):02d}")

                # UTC time - directly from birth_data
                self.utc_hour.setText(f"{birth_data.get('utc_hour', 0):02d}")
                self.utc_minute.setText(f"{birth_data.get('utc_minute', 0):02d}")
                self.utc_second.setText(f"{birth_data.get('utc_second', 0):02d}")

                # Gender
                gender = birth_data.get('gender', '')
                if gender and str(gender).lower() in ('male', 'm', '1'):
                    self.male_radio.setChecked(True)
                elif gender and str(gender).lower() in ('female', 'f', '2'):
                    self.female_radio.setChecked(True)
                else:
                    # Neither checked - clear both
                    self.male_radio.setAutoExclusive(False)
                    self.female_radio.setAutoExclusive(False)
                    self.male_radio.setChecked(False)
                    self.female_radio.setChecked(False)
                    self.male_radio.setAutoExclusive(True)
                    self.female_radio.setAutoExclusive(True)

                # Location - cleaned from birth_data
                city = birth_data.get('city', '')
                # Remove ", 0" suffix if present
                if city.endswith(', 0'):
                    city = city[:-3].strip()
                self.city_input.setText(city)
                self.country_input.setText(birth_data.get('country', ''))
                self._update_location_display()

                # Coordinates
                self.latitude_input.setText(str(birth_data.get('latitude', '')))
                self.longitude_input.setText(str(birth_data.get('longitude', '')))

                # Timezone - IANA name and UTC offset
                iana_tz = birth_data.get('iana_timezone', '')
                self.timezone_iana_input.setText(iana_tz)

                # utc_offset_hours is TOTAL (standard + DST); display STANDARD
                dst_flag = birth_data.get('time_change_flag', 0) or 0
                offset = birth_data.get('utc_offset_hours', 0) - dst_flag
                # STANDARD-sign display string. Total-minutes rounding avoids
                # the float-truncation trap of int(abs(offset - h) * 60).
                tm = int(round(offset * 60))
                sign = 1 if tm >= 0 else -1
                tz_display = format_offset(sign * (abs(tm) // 60), sign * (abs(tm) % 60))
                self.timezone_input.setText(tz_display)
                if dst_flag == 1:
                    self.dst_yes.setChecked(True)
                elif dst_flag == 2:
                    self.dst_war.setChecked(True)
                else:
                    self.dst_none.setChecked(True)

                # Default to local time mode
                self.local_radio.setChecked(True)

            else:
                # === LEGACY PATH: Use birth_metadata and planets_data ===
                # Helper to get value from birth_metadata first, then planets_data as fallback
                def get_val(key, default=''):
                    val = birth_metadata.get(key)
                    if val is None or val == '':
                        val = planets_data.get(key, default)
                    return val if val is not None else default

                # Name - from chart_entry first (memory panel top-level), then birth_metadata
                name = (chart_entry.get('person_name') if chart_entry else '') or \
                       birth_metadata.get('name', '') or \
                       planets_data.get('name', '')
                self.name_input.setText(name)

                # Date - try birth_metadata, fall back to planets_data
                year = get_val('year', '')
                month = get_val('month', '')
                day = get_val('day', '')
                self.date_year.setText(str(year) if year else '')
                self.date_month.setText(str(month) if month else '')
                self.date_day.setText(str(day) if day else '')

                # Time (local time) - try birth_metadata, fall back to planets_data
                hour = get_val('hour', 0)
                minute = get_val('minute', 0)
                second = get_val('second', 0)
                self.local_hour.setText(f"{int(hour):02d}" if hour is not None else "00")
                self.local_minute.setText(f"{int(minute):02d}" if minute is not None else "00")
                self.local_second.setText(f"{int(second):02d}" if second is not None else "00")

                # Gender - clear first, then set if present
                gender = birth_metadata.get('gender', '')
                if gender and str(gender).lower() in ('male', 'm', '1'):
                    self.male_radio.setChecked(True)
                elif gender and str(gender).lower() in ('female', 'f', '2'):
                    self.female_radio.setChecked(True)
                else:
                    # Clear both (need to disable auto-exclusive temporarily)
                    self.male_radio.setAutoExclusive(False)
                    self.female_radio.setAutoExclusive(False)
                    self.male_radio.setChecked(False)
                    self.female_radio.setChecked(False)
                    self.male_radio.setAutoExclusive(True)
                    self.female_radio.setAutoExclusive(True)

                # Location - try birth_metadata.location, then chart_entry top-level, then birth_metadata top-level
                location = birth_metadata.get('location', {})
                country = location.get('country', '') or \
                          (chart_entry.get('country') if chart_entry else '') or \
                          birth_metadata.get('country', '')
                city = location.get('city', '') or \
                       (chart_entry.get('city') if chart_entry else '') or \
                       birth_metadata.get('city', '')

                self.country_input.setText(country)
                self.city_input.setText(city)
                self._update_location_display()

                # Coordinates - fall back to planets_data (None-safe for equator/prime meridian)
                bm_lat = birth_metadata.get('latitude')
                lat = bm_lat if bm_lat is not None else planets_data.get('latitude', 0)
                bm_lon = birth_metadata.get('longitude')
                lon = bm_lon if bm_lon is not None else planets_data.get('longitude', 0)
                self.latitude_input.setText(str(lat) if lat is not None else '')
                self.longitude_input.setText(str(lon) if lon is not None else '')

                # Timezone - IANA name and UTC offset
                iana_tz = birth_metadata.get('iana_timezone', '') or \
                          planets_data.get('iana_timezone', '')
                self.timezone_iana_input.setText(iana_tz)

                raw_tz = location.get('timezone', '') or \
                         planets_data.get('timezone', '') or \
                         planets_data.get('timezone_offset', '')
                if not raw_tz:
                    utcoff = planets_data.get('utcoffset')
                    if utcoff is not None:
                        h = int(utcoff)
                        m = int(abs(utcoff - h) * 60)
                        raw_tz = f"{h:+03d}:{m:02d}"
                    elif (chart_entry or {}).get('utcoffset') is not None:
                        utcoff = chart_entry['utcoffset']
                        h = int(utcoff)
                        m = int(abs(utcoff - h) * 60)
                        raw_tz = f"{h:+03d}:{m:02d}"
                    else:
                        raw_tz = '+00:00'
                try:
                    from datetime import datetime
                    _bdt = datetime(
                        int(self.date_year.text() or 2000),
                        int(self.date_month.text() or 1),
                        int(self.date_day.text() or 1),
                        int(self.local_hour.text() or 0),
                        int(self.local_minute.text() or 0),
                    )
                except Exception:
                    _bdt = None
                tz_offset = self._convert_timezone_to_offset(raw_tz, lat, lon, birth_dt=_bdt)
                self.timezone_input.setText(tz_offset)

                # DST (None-safe: dst=0 means no DST, must not fall through)
                dst_raw = birth_metadata.get('dst')
                dst_flag = dst_raw if dst_raw is not None else birth_metadata.get('time_change_flag', 0)
                if dst_flag == 1:
                    self.dst_yes.setChecked(True)
                elif dst_flag == 2:
                    self.dst_war.setChecked(True)
                else:
                    self.dst_none.setChecked(True)

                # Time mode — prefer source_params from chart_entry
                sp = (chart_entry.get('source_params') if chart_entry and chart_entry.get('source_params') is not None else {})
                is_utc = sp.get('is_utc_time', planets_data.get('is_utc_time', False))
                if is_utc:
                    self.utc_radio.setChecked(True)
                else:
                    self.local_radio.setChecked(True)

            self._update_time_field_states()

        finally:
            self._syncing = False

        # Sync UTC display (only needed for legacy path without pre-set UTC)
        if not birth_data:
            self._sync_utc_from_local()

        # Check for gender warning
        self._check_gender_warning()

    # =========================================================================
    # DATA COLLECTION
    # =========================================================================

    def collect_data(self) -> dict:
        """
        Gather all form values into a dictionary.

        In Local mode, hour/minute/second come from the local time fields.
        In UTC mode, hour/minute/second come from the UTC fields (the
        authoritative input), and BirthDataManager treats them as UTC.

        Returns:
            Dict with all form data
        """
        try:
            male_checked = self.male_radio.isChecked()
            female_checked = self.female_radio.isChecked()
            gender = 'Male' if male_checked else 'Female' if female_checked else ''

            if self.time_mode == "UTC":
                hour = int(self.utc_hour.text() or 0)
                minute = int(self.utc_minute.text() or 0)
                second = int(self.utc_second.text() or 0)
            else:
                hour = int(self.local_hour.text() or 0)
                minute = int(self.local_minute.text() or 0)
                second = int(self.local_second.text() or 0)

            data = {
                'name': self.name_input.text().strip(),
                'year': int(self.date_year.text() or 0),
                'month': int(self.date_month.text() or 0),
                'day': int(self.date_day.text() or 0),
                'hour': hour,
                'minute': minute,
                'second': second,
                'gender': gender,
                'country': self.country_input.text().strip(),
                'city': self.city_input.text().strip(),
                'latitude': float(self.latitude_input.text() or 0),
                'longitude': float(self.longitude_input.text() or 0),
                'iana_timezone': self.timezone_iana_input.text().strip(),
                'timezone': self.timezone_input.text().strip() or '+00:00',
                'dst': self.dst_group.checkedId(),
                'time_mode': self.time_mode,
            }
            return data
        except ValueError as e:
            print(f"Error collecting form data: {e}")
            return {}

    # =========================================================================
    # PUBLIC SETTERS (for cross-tab sync)
    # =========================================================================

    def set_coordinates(self, lat: float, lon: float):
        """Set coordinates from external source (e.g., map)"""
        self._syncing = True
        try:
            self.latitude_input.setText(f"{lat:.6f}")
            self.longitude_input.setText(f"{lon:.6f}")
        finally:
            self._syncing = False

    def set_city(self, city: str):
        """Set city from external source"""
        self.city_input.setText(city)
        self._update_location_display()

    def set_country(self, country: str):
        """Set country from external source"""
        self.country_input.setText(country)
        self._update_location_display()

    def _update_location_display(self):
        """Update the visible location label from hidden city/country fields."""
        city = self.city_input.text().strip()
        country = self.country_input.text().strip()
        if city and country:
            self.location_display_label.setText(f"{city}, {country}")
        elif city:
            self.location_display_label.setText(city)
        elif country:
            self.location_display_label.setText(country)
        else:
            self.location_display_label.setText("No location selected")

    def set_timezone(self, timezone: str):
        """Set timezone from external source - populates both IANA and offset fields"""
        _bdt = None
        self._syncing = True
        try:
            if '/' in timezone:
                iana_name = timezone
                try:
                    from datetime import datetime
                    _bdt = datetime(
                        int(self.date_year.text() or 2000),
                        int(self.date_month.text() or 1),
                        int(self.date_day.text() or 1),
                        int(self.local_hour.text() or 0),
                        int(self.local_minute.text() or 0),
                    )
                except Exception:
                    _bdt = None
                from core.time_utils import resolve_total_offset, format_offset
                offset_format = None
                if _bdt is not None:
                    try:
                        std_hours, dst_flag = resolve_total_offset(
                            iana_name, _bdt.year, _bdt.month, _bdt.day, _bdt.hour, _bdt.minute)
                        offset_format = format_offset(0, int(round(std_hours * 60)))
                        if dst_flag == 1:
                            self.dst_yes.setChecked(True)
                        else:
                            self.dst_none.setChecked(True)
                    except Exception:
                        offset_format = None
                if offset_format is None:
                    offset_format = self._convert_timezone_to_offset(timezone, birth_dt=_bdt)
            else:
                iana_name = ""
                offset_format = timezone

            self.timezone_iana_input.setText(iana_name)
            self.timezone_input.setText(offset_format)
        finally:
            self._syncing = False
        if self.time_mode == "Local":
            self._sync_utc_from_local()

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    def refresh_theme(self):
        """Update colors after theme change - re-apply all dynamic styles"""
        theme = get_theme_colors()
        bg = theme['secondary_dark']

        # Update scroll area and content backgrounds
        if hasattr(self, '_scroll'):
            self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        if hasattr(self, '_content'):
            self._content.setStyleSheet(f"background: {bg};")

        # Re-style title label
        if hasattr(self, '_title_label'):
            self._title_label.setStyleSheet(f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; color: {theme['secondary_text']}; padding: 10px 0;")

        # Re-style group frames and their labels
        group_style = f"QFrame {{ background-color: {theme['secondary']}; border: 1px solid {theme['secondary_dark']}; border-radius: 8px; padding: 10px; }}"
        for frame in getattr(self, '_group_frames', []):
            frame.setStyleSheet(group_style)
        for label in getattr(self, '_group_labels', []):
            label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; border: none;")

        # Re-style all input fields
        for widget in [self.name_input, self.date_month, self.date_day, self.date_year,
                       self.country_input, self.city_input, self.latitude_input,
                       self.longitude_input, self.timezone_input]:
            self._style_input(widget)

        # Re-style location display and map buttons
        if hasattr(self, 'location_display_label'):
            self.location_display_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; padding: 4px;")
        if hasattr(self, 'use_map_btn'):
            self._style_secondary_button(self.use_map_btn)
        if hasattr(self, 'open_map_btn'):
            self._style_secondary_button(self.open_map_btn)

        # Re-style time fields based on current mode
        self._update_time_field_states()

        # Re-style radio buttons
        for btn in [self.local_radio, self.utc_radio, self.male_radio, self.female_radio]:
            self._style_radio(btn)

        # Re-style save/cancel buttons
        if hasattr(self, 'save_btn'):
            self.save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme['primary']};
                    color: white;
                    padding: 12px 30px; border: none;
                    border-radius: 6px; font-weight: bold; font-size: {scaled_area_px('buttons')}px;
                }}
                QPushButton:hover {{ opacity: 0.9; }}
            """)
        if hasattr(self, 'cancel_btn'):
            self.cancel_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme['secondary']};
                    color: {theme['secondary_text']};
                    padding: 12px 30px; border: 1px solid {theme['secondary_dark']};
                    border-radius: 6px; font-size: {scaled_area_px('buttons')}px;
                }}
                QPushButton:hover {{ background-color: {theme['secondary_light']}; }}
            """)
