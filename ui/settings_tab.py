#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Settings Tab — Core Version
============================

Minimal settings for the open-source Core build:
- Appearance: Theme selection with visual cards
- Default Folders: Chart folder paths and Kala configuration

The Pro version adds: Background, South Indian Display, Wheel Display,
North Indian Display, and AI Settings customization.
"""
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QFrame, QGroupBox, QSizePolicy,
    QPushButton, QLineEdit, QFileDialog, QMessageBox,
    QListWidget, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QCheckBox, QFormLayout, QToolButton, QSpinBox,
    QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont, QColor, QValidator

from ui.qt_theme import (
    get_theme_colors, get_primary_button_style, get_secondary_button_style,
    scaled_area_px, scaled_area_size, scaled_area_font,
    get_area_font_size, set_area_font_size, reset_area_font_sizes, AREA_DEFAULTS,
)
from managers.settings_manager import get_settings

INFO_PANEL_WIDTH = 380

_HOUSE_SYSTEMS = [
    ("Campanus", "campanus"),
    ("Placidus", "placidus"),
    ("Koch", "koch"),
    ("Equal", "equal"),
    ("Whole Sign", "whole_sign"),
    ("Porphyry", "porphyry"),
    ("Regiomontanus", "regiomontanus"),
]

# Theme catalog lives in ui/themes.py (core-level, SPEC-LITE-FOUND-001 s4.7)
from ui.themes import AVAILABLE_THEMES


class ThemeCard(QFrame):
    """
    Clickable card showing theme preview with color swatches.
    Emits clicked signal with theme filename when selected.
    """
    clicked = Signal(str)

    def __init__(self, theme_file: str, theme_name: str, is_dark: bool, colors: list, parent=None):
        super().__init__(parent)
        self.theme_file = theme_file
        self.theme_name = theme_name
        self.is_dark = is_dark
        self.colors = colors
        self.is_selected = False

        self._setup_ui()
        self._update_style()

    def _setup_ui(self):
        self.setFixedSize(150, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.name_label = QLabel(self.theme_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = scaled_area_font('buttons', bold=True)
        self.name_label.setFont(font)
        layout.addWidget(self.name_label)

        swatch_layout = QHBoxLayout()
        swatch_layout.setSpacing(6)
        swatch_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for color in self.colors:
            swatch = QFrame()
            swatch.setFixedSize(28, 28)
            swatch.setStyleSheet(f"""
                background-color: {color};
                border-radius: 4px;
                border: 1px solid rgba(255,255,255,0.2);
            """)
            swatch_layout.addWidget(swatch)

        layout.addLayout(swatch_layout)

        mode_label = QLabel("Dark" if self.is_dark else "Light")
        mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme = get_theme_colors()
        mode_label.setStyleSheet(f"font-size: {scaled_area_px('status')}px; color: {theme['secondary_text']};")
        layout.addWidget(mode_label)

    def _update_style(self):
        theme = get_theme_colors()
        if self.is_selected:
            border = f"3px solid {theme['primary']}"
            bg = theme["secondary_light"]
        else:
            border = f"1px solid {theme['secondary_light']}"
            bg = theme["secondary"]

        self.setStyleSheet(f"""
            ThemeCard {{
                background-color: {bg};
                border: {border};
                border-radius: 10px;
            }}
            ThemeCard:hover {{
                border: 2px solid {theme['primary']};
            }}
        """)
        self.name_label.setStyleSheet(f"color: {theme['secondary_text']}; background: transparent;")

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        self.clicked.emit(self.theme_file)
        super().mousePressEvent(event)


class AppearanceTab(QWidget):
    """Theme selection with visual cards and sign language toggle."""
    theme_changed = Signal(str)
    sign_language_changed = Signal(str)

    def __init__(self, current_theme: str = None, parent=None):
        super().__init__(parent)
        self.current_theme = current_theme or "dark_blue.xml"
        self.theme_cards = {}
        self._setup_ui()

    def _setup_ui(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"AppearanceTab {{ background-color: {theme['secondary_dark']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        theme_section = self._create_theme_section()
        layout.addWidget(theme_section)

        lang_section = self._create_language_section()
        layout.addWidget(lang_section)
        layout.addStretch()

    def _create_theme_section(self) -> QGroupBox:
        group = QGroupBox("Application Theme")
        group.setFont(scaled_area_font('panel_titles', bold=True))

        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(15)

        desc = QLabel("Select a theme to change the application appearance. Changes apply immediately.")
        desc.setWordWrap(True)
        desc.setFont(scaled_area_font('info_text'))
        group_layout.addWidget(desc)

        # Dark themes
        dark_label = QLabel("Dark Themes")
        dark_label.setFont(scaled_area_font('panel_titles', bold=True))
        group_layout.addWidget(dark_label)

        dark_grid = QGridLayout()
        dark_grid.setSpacing(12)
        row, col, max_cols = 0, 0, 5

        for theme_file, theme_name, is_dark, colors in AVAILABLE_THEMES:
            if is_dark:
                card = ThemeCard(theme_file, theme_name, is_dark, colors)
                card.clicked.connect(self._on_theme_selected)
                if theme_file == self.current_theme:
                    card.set_selected(True)
                self.theme_cards[theme_file] = card
                dark_grid.addWidget(card, row, col)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

        group_layout.addLayout(dark_grid)

        # Light themes
        light_label = QLabel("Light Themes")
        light_label.setFont(scaled_area_font('panel_titles', bold=True))
        group_layout.addWidget(light_label)

        light_grid = QGridLayout()
        light_grid.setSpacing(12)
        row, col = 0, 0

        for theme_file, theme_name, is_dark, colors in AVAILABLE_THEMES:
            if not is_dark:
                card = ThemeCard(theme_file, theme_name, is_dark, colors)
                card.clicked.connect(self._on_theme_selected)
                if theme_file == self.current_theme:
                    card.set_selected(True)
                self.theme_cards[theme_file] = card
                light_grid.addWidget(card, row, col)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

        group_layout.addLayout(light_grid)
        return group

    def _create_language_section(self) -> QGroupBox:
        group = QGroupBox("Other Settings")
        group.setFont(scaled_area_font('panel_titles', bold=True))

        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(12)

        s = get_settings()

        # Language
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Français (French)", "fr")
        self.lang_combo.addItem("Español (Spanish)", "es")
        self.lang_combo.addItem("Português BR (Brazilian)", "pt")
        self.lang_combo.addItem("Português PT (European)", "pt-PT")
        self.lang_combo.addItem("Deutsch (German)", "de")
        self.lang_combo.addItem("Italiano (Italian)", "it")
        self.lang_combo.addItem("Русский (Russian)", "ru")
        self.lang_combo.addItem("中文 (Chinese)", "zh")
        self.lang_combo.setMaximumWidth(220)

        lang = s.get("zodiac.sign_language", "en")
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        form.addRow("Language:", self.lang_combo)

        lang_warning = QLabel(
            "Changes zodiac sign names and planet names on chart views. "
            "Full UI translation will be supported in a later update."
        )
        lang_warning.setWordWrap(True)
        lang_warning.setFont(scaled_area_font('status'))
        lang_warning.setStyleSheet(f"color: {get_theme_colors()['secondary_text']}; font-style: italic;")
        form.addRow("", lang_warning)

        # Remember window geometry
        self.remember_geo_cb = QCheckBox()
        self.remember_geo_cb.setChecked(s.get("windows.remember_geometry", True))
        form.addRow("Remember window geometry:", self.remember_geo_cb)

        # Auto-restore session
        self.auto_restore_cb = QCheckBox()
        self.auto_restore_cb.setChecked(s.get("defaults.auto_restore_session", True))
        form.addRow("Auto-restore session:", self.auto_restore_cb)

        # Restore last tab
        self.restore_tab_cb = QCheckBox()
        self.restore_tab_cb.setChecked(s.get("ui.restore_last_tab", True))
        form.addRow("Restore last tab:", self.restore_tab_cb)

        group_layout.addLayout(form)

        # Apply button for non-theme settings
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._other_apply_btn = QPushButton("Apply")
        self._other_apply_btn.setFixedWidth(100)
        self._other_apply_btn.setStyleSheet(get_primary_button_style())
        self._other_apply_btn.clicked.connect(self._on_other_apply)
        btn_row.addWidget(self._other_apply_btn)
        group_layout.addLayout(btn_row)

        return group

    def _on_language_changed(self):
        new_lang = self.lang_combo.currentData()
        get_settings().set("zodiac.sign_language", new_lang)
        self.sign_language_changed.emit(new_lang)

    def _on_other_apply(self):
        s = get_settings()
        s.set("windows.remember_geometry", self.remember_geo_cb.isChecked())
        s.set("defaults.auto_restore_session", self.auto_restore_cb.isChecked())
        s.set("ui.restore_last_tab", self.restore_tab_cb.isChecked())

    def _on_theme_selected(self, theme_file: str):
        for tf, card in self.theme_cards.items():
            card.set_selected(tf == theme_file)
        self.current_theme = theme_file
        self.theme_changed.emit(theme_file)

    def get_current_theme(self) -> str:
        return self.current_theme

    def set_current_theme(self, theme_file: str):
        if theme_file in self.theme_cards:
            for tf, card in self.theme_cards.items():
                card.set_selected(tf == theme_file)
            self.current_theme = theme_file

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"AppearanceTab {{ background-color: {theme['secondary_dark']}; }}")
        for card in self.theme_cards.values():
            card._update_style()


class DefaultFoldersTab(QWidget):
    """Chart folder paths and Kala configuration."""
    folders_changed = Signal()

    def __init__(self, settings_path: Path, parent=None):
        super().__init__(parent)
        self.folder_entries = {}
        self._setup_ui()

    def _setup_ui(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"DefaultFoldersTab {{ background-color: {theme['secondary_dark']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        title = QLabel("Default Folders")
        title.setFont(scaled_area_font('panel_titles', bold=True))
        layout.addWidget(title)

        desc = QLabel(
            "Define default folders for chart loading and searching. "
            "When you load charts, the app will search these folders by default."
        )
        desc.setWordWrap(True)
        desc.setFont(scaled_area_font('info_text'))
        layout.addWidget(desc)

        # Chart folders group
        group = QGroupBox("Chart Folders")
        group.setFont(scaled_area_font('panel_titles', bold=True))
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(15)

        from utils.path_translator import translate_path
        from managers.settings_manager import get_settings
        s = get_settings()
        chart_folders = s.get_chart_folders()
        folders = [
            ('default_folder', 'Default Folder', translate_path(chart_folders[0]) or '' if chart_folders[0] else ''),
            ('folder_1', 'Folder 1', translate_path(chart_folders[1]) or '' if chart_folders[1] else ''),
            ('folder_2', 'Folder 2', translate_path(chart_folders[2]) or '' if chart_folders[2] else ''),
        ]
        for folder_key, folder_label, folder_path in folders:
            row_widget = self._create_folder_row(folder_key, folder_label, folder_path)
            group_layout.addWidget(row_widget)
        layout.addWidget(group)

        # Kala Software group
        import sys
        kala_group = QGroupBox("Kala Software")
        kala_group.setFont(scaled_area_font('panel_titles', bold=True))
        kala_layout = QVBoxLayout(kala_group)
        kala_layout.setSpacing(15)

        kala_hint = "Path to Kala.exe on your system." if sys.platform == 'win32' else \
                    "Path to Kala.exe — will be launched through Wine on Linux/macOS."
        kala_desc = QLabel(kala_hint)
        kala_desc.setFont(scaled_area_font('status'))
        kala_desc.setStyleSheet("color: #aaa;")
        kala_layout.addWidget(kala_desc)

        kala_exe_path = s.get("paths.kala_path", "")
        kala_row = self._create_file_row('kala_exe', 'Kala Executable', kala_exe_path)
        kala_layout.addWidget(kala_row)
        layout.addWidget(kala_group)

        # Save button
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setFixedWidth(150)
        save_btn.setStyleSheet(get_primary_button_style())
        save_btn.clicked.connect(self._on_save_clicked)
        save_layout.addWidget(save_btn)
        layout.addLayout(save_layout)
        layout.addStretch()

    def _entry_style(self):
        theme = get_theme_colors()
        return (
            f"background-color: {theme['secondary']}; "
            f"color: {theme['secondary_text']}; "
            f"border: 1px solid {theme['secondary_dark']}; "
            f"border-radius: 3px; padding: 4px;"
        )

    def _create_folder_row(self, folder_key: str, folder_label: str, folder_path: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        label = QLabel(f"{folder_label}:")
        label.setFixedWidth(120)
        label.setFont(scaled_area_font('buttons'))
        row_layout.addWidget(label)

        path_entry = QLineEdit(folder_path)
        path_entry.setPlaceholderText("No folder selected")
        path_entry.setReadOnly(True)
        path_entry.setStyleSheet(self._entry_style())
        self.folder_entries[folder_key] = path_entry
        row_layout.addWidget(path_entry, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(100)
        browse_btn.setStyleSheet(get_secondary_button_style())
        browse_btn.clicked.connect(lambda: self._on_browse_clicked(folder_key))
        row_layout.addWidget(browse_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet(get_secondary_button_style())
        clear_btn.clicked.connect(lambda: self._on_clear_clicked(folder_key))
        row_layout.addWidget(clear_btn)
        return row

    def _create_file_row(self, file_key: str, file_label: str, file_path: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        label = QLabel(f"{file_label}:")
        label.setFixedWidth(120)
        label.setFont(scaled_area_font('buttons'))
        row_layout.addWidget(label)

        path_entry = QLineEdit(file_path)
        path_entry.setPlaceholderText("No file selected")
        path_entry.setReadOnly(True)
        path_entry.setStyleSheet(self._entry_style())
        self.folder_entries[file_key] = path_entry
        row_layout.addWidget(path_entry, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(100)
        browse_btn.setStyleSheet(get_secondary_button_style())
        browse_btn.clicked.connect(lambda: self._on_browse_file_clicked(file_key))
        row_layout.addWidget(browse_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet(get_secondary_button_style())
        clear_btn.clicked.connect(lambda: self._on_clear_clicked(file_key))
        row_layout.addWidget(clear_btn)
        return row

    def _on_browse_clicked(self, folder_key: str):
        current_path = self.folder_entries[folder_key].text()
        start_dir = current_path if current_path and Path(current_path).exists() else str(Path.home())
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder", start_dir, QFileDialog.Option.ShowDirsOnly
        )
        if folder_path:
            self.folder_entries[folder_key].setText(folder_path)

    def _on_browse_file_clicked(self, file_key: str):
        current_path = self.folder_entries[file_key].text()
        start_dir = str(Path(current_path).parent) if current_path and Path(current_path).exists() else str(Path.home())
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", start_dir, "Executables (*.exe);;All Files (*)"
        )
        if file_path:
            self.folder_entries[file_key].setText(file_path)

    def _on_clear_clicked(self, folder_key: str):
        self.folder_entries[folder_key].clear()

    def _read_from_settings(self):
        """Reload folder values from SettingsManager."""
        from utils.path_translator import translate_path
        from managers.settings_manager import get_settings
        s = get_settings()
        folders = s.get_chart_folders()
        slot_keys = ["default_folder", "folder_1", "folder_2"]
        for i, key in enumerate(slot_keys):
            if key in self.folder_entries:
                val = translate_path(folders[i]) or '' if folders[i] else ''
                self.folder_entries[key].setText(val)
        if 'kala_exe' in self.folder_entries:
            self.folder_entries['kala_exe'].setText(s.get("paths.kala_path", ""))

    def _on_save_clicked(self):
        from managers.settings_manager import get_settings
        s = get_settings()

        folders = [
            self.folder_entries.get("default_folder", QLineEdit()).text().strip(),
            self.folder_entries.get("folder_1", QLineEdit()).text().strip(),
            self.folder_entries.get("folder_2", QLineEdit()).text().strip(),
        ]
        s.set_chart_folders(folders)

        kala_entry = self.folder_entries.get('kala_exe')
        if kala_entry:
            s.set("paths.kala_path", kala_entry.text().strip())

        self.folders_changed.emit()
        QMessageBox.information(self, "Settings Saved", "Settings have been saved successfully.")

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"DefaultFoldersTab {{ background-color: {theme['secondary_dark']}; }}")
        style = self._entry_style()
        for entry in self.folder_entries.values():
            entry.setStyleSheet(style)
        for btn in self.findChildren(QPushButton):
            if btn.text() == "Save Settings":
                btn.setStyleSheet(get_primary_button_style())
            else:
                btn.setStyleSheet(get_secondary_button_style())


# =============================================================================
# DISPLAY SCALE TAB — Font scaling for responsive UI
# =============================================================================

class DisplayScaleTab(QWidget):
    """Display scale controls: slider 60-160%, live preview, reset, auto-detect."""
    scale_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_scale = 1.0  # cached; updated by _load_saved_scale and _on_apply
        self._setup_ui()
        self._load_saved_scale()
        # _load_saved_scale already calls _apply_preview_scale — no redundant call needed

    def _setup_ui(self):
        from ui.qt_theme import (
            get_theme_colors, get_primary_button_style,
            get_secondary_button_style, get_group_box_style,
        )
        theme = get_theme_colors()
        self.setStyleSheet(f"DisplayScaleTab {{ background-color: {theme['secondary_dark']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Title
        title = QLabel("Display Scale")
        title.setFont(scaled_area_font('panel_titles', bold=True))
        layout.addWidget(title)

        desc = QLabel(
            "Adjust the font size and UI element scaling. "
            "Changes apply to panels, buttons, and text across the application. "
            "The chart wheel has its own independent zoom."
        )
        desc.setWordWrap(True)
        desc.setFont(scaled_area_font('info_text'))
        layout.addWidget(desc)

        # Scale group
        self.scale_group = QGroupBox("Display Scale")
        self.scale_group.setStyleSheet(get_group_box_style())
        self.scale_group.setFont(scaled_area_font('panel_titles', bold=True))
        group_layout = QVBoxLayout(self.scale_group)
        group_layout.setSpacing(15)

        # Slider row
        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)

        slider_label = QLabel("Scale:")
        slider_label.setFixedWidth(50)
        slider_row.addWidget(slider_label)

        from PySide6.QtWidgets import QSlider
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(60)
        self.scale_slider.setMaximum(160)
        self.scale_slider.setValue(100)
        self.scale_slider.setSingleStep(5)
        self.scale_slider.setPageStep(10)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setTickInterval(10)
        slider_row.addWidget(self.scale_slider, stretch=1)

        self.scale_value_label = QLabel("100%")
        self.scale_value_label.setFixedWidth(50)
        self.scale_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_value_label.setFont(scaled_area_font('buttons', bold=True))
        slider_row.addWidget(self.scale_value_label)

        group_layout.addLayout(slider_row)

        self.scale_tip_label = QLabel(
            "Tips: 60% for 720p, 80% for 1080p, 100-120% for 2K, "
            "140-160% for 4K. Restart Varuna360 after applying to ensure every "
            "panel uses the new scale."
        )
        self.scale_tip_label.setWordWrap(True)
        self.scale_tip_label.setFont(scaled_area_font('status'))
        self.scale_tip_label.setStyleSheet(f"color: {theme['secondary_text']};")
        group_layout.addWidget(self.scale_tip_label)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.reset_btn = QPushButton("Reset to 100%")
        self.reset_btn.setFixedWidth(140)
        self.reset_btn.setStyleSheet(get_primary_button_style())
        self.reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self.reset_btn)

        self.auto_detect_btn = QPushButton("Auto-Detect DPI")
        self.auto_detect_btn.setFixedWidth(140)
        self.auto_detect_btn.setStyleSheet(get_secondary_button_style())
        self.auto_detect_btn.clicked.connect(self._on_auto_detect)
        btn_row.addWidget(self.auto_detect_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFixedWidth(100)
        self.apply_btn.setStyleSheet(get_primary_button_style())
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self.apply_btn)

        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        self._build_strength_preview(group_layout)
        layout.addWidget(self.scale_group)

        # Restart warning
        self.restart_warning = QLabel(
            "\u26a0  You may need to restart the app for all changes to take effect."
        )
        self.restart_warning.setFont(scaled_area_font('status'))
        self.restart_warning.setStyleSheet(f"color: #FFA726; padding: 4px 0;")
        self.restart_warning.setWordWrap(True)
        self.restart_warning.setVisible(False)
        layout.addWidget(self.restart_warning)

        # DPI info label
        self.dpi_info_label = QLabel("")
        self.dpi_info_label.setFont(scaled_area_font('info_text'))
        self.dpi_info_label.setStyleSheet(f"color: {theme['secondary_text']};")
        layout.addWidget(self.dpi_info_label)
        self._update_dpi_info()

        layout.addStretch()

        # Connect slider — only updates preview + label, does NOT emit scale_changed
        self.scale_slider.valueChanged.connect(self._on_slider_changed)

    def _build_strength_preview(self, parent_layout):
        """Build a compact panel preview that mirrors the real Strength panel."""
        theme = get_theme_colors()
        self.preview_title = QLabel("Preview")
        self.preview_title.setFont(QFont("", 10, QFont.Weight.Bold))
        self.preview_title.setStyleSheet(f"color: {theme['secondary_text']}; border: none;")
        parent_layout.addWidget(self.preview_title)

        self.preview_shell = QWidget()
        shell_layout = QHBoxLayout(self.preview_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(QWidget(), stretch=1)

        self.preview_frame = QFrame()
        self.preview_frame.setFixedWidth(INFO_PANEL_WIDTH)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_layout.setSpacing(2)

        self.preview_header = QFrame()
        self.preview_header_layout = QHBoxLayout(self.preview_header)
        self.preview_header_layout.setContentsMargins(8, 2, 8, 2)
        self.preview_header_layout.setSpacing(0)

        self.preview_strength_btn = self._build_preview_tab_button("Strength")
        self.preview_header_layout.addWidget(self.preview_strength_btn)

        self.preview_sep_1 = QLabel("|")
        self.preview_header_layout.addWidget(self.preview_sep_1)

        self.preview_elements_btn = self._build_preview_tab_button("Elements", active=False)
        self.preview_header_layout.addWidget(self.preview_elements_btn)

        self.preview_sep_2 = QLabel("|")
        self.preview_header_layout.addWidget(self.preview_sep_2)

        self.preview_modality_btn = self._build_preview_tab_button("Modality", active=False)
        self.preview_header_layout.addWidget(self.preview_modality_btn)
        self.preview_header_layout.addStretch()

        self.preview_lang_btn = QPushButton("EN")
        self.preview_lang_btn.setEnabled(False)
        self.preview_lang_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_header_layout.addWidget(self.preview_lang_btn)
        preview_layout.addWidget(self.preview_header)

        self.preview_table = QTableWidget(7, 4)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview_table.verticalHeader().setDefaultSectionSize(28)
        self.preview_table.setHorizontalHeaderLabels(["Planet", "Digbala", "Uccha", "Chesta"])
        self.preview_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 260)

        preview_rows = [
            ("☉ Sun", "42.8", "55.1", "23.4"),
            ("☽ Moon", "31.5", "24.8", "46.2"),
            ("♂ Mars", "27.9", "39.6", "17.8"),
            ("☿ Mercury", "21.4", "28.2", "34.5"),
            ("♃ Jupiter", "44.7", "36.9", "26.1"),
            ("♄ Saturn", "37.2", "18.7", "41.9"),
            ("♀ Venus", "48.2", "31.7", "22.1"),
        ]
        for row, values in enumerate(preview_rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.preview_table.setItem(row, col, item)
        preview_layout.addWidget(self.preview_table)

        shell_layout.addWidget(self.preview_frame)
        shell_layout.addWidget(QWidget(), stretch=1)
        parent_layout.addWidget(self.preview_shell)
        self._apply_preview_theme()
        self._apply_preview_scale(self.scale_slider.value() / 100.0)

    def _build_preview_tab_button(self, text: str, active: bool = True) -> QPushButton:
        btn = QPushButton(text)
        btn.setEnabled(False)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setProperty("preview_active", active)
        return btn

    def _apply_preview_theme(self):
        """Refresh preview colors to match the current application theme."""
        theme = get_theme_colors()
        self.preview_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 6px;
            }}
        """)
        self.preview_header.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme['primary_light']},
                    stop:1 {theme['primary']}
                );
                border: none;
                border-radius: 6px;
            }}
        """)
        self._apply_preview_scale(self.scale_slider.value() / 100.0)

    def _style_preview_header_controls(self, factor: float):
        """Apply scaled styles to the preview panel header controls."""
        theme = get_theme_colors()
        active_style = f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {theme['primary_text']};
                font-size: {max(8, int(12 * factor))}px;
                font-weight: bold;
                border-bottom: 2px solid {theme['primary_text']};
                padding: {max(1, int(2 * factor))}px {max(4, int(8 * factor))}px;
            }}
        """
        inactive_style = f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {theme['primary_text']};
                font-size: {max(8, int(12 * factor))}px;
                font-weight: normal;
                border-bottom: 2px solid transparent;
                padding: {max(1, int(2 * factor))}px {max(4, int(8 * factor))}px;
            }}
        """
        self.preview_strength_btn.setStyleSheet(active_style)
        self.preview_elements_btn.setStyleSheet(inactive_style)
        self.preview_modality_btn.setStyleSheet(inactive_style)
        sep_style = (
            f"color: {theme['primary_text']}; "
            f"font-size: {max(8, int(12 * factor))}px; "
            "background: transparent; border: none;"
        )
        self.preview_sep_1.setStyleSheet(sep_style)
        self.preview_sep_2.setStyleSheet(sep_style)
        self.preview_lang_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border-radius: {max(10, int(12 * factor))}px;
                font-size: {max(7, int(9 * factor))}px;
                font-weight: bold;
                border: 2px solid {theme["secondary_text"]};
                padding: 0;
            }}
        """)
    def _apply_preview_scale(self, factor: float):
        """Scale the preview panel typography and table metrics live."""
        title_size = max(8, int(10 * factor))
        body_size = max(8, int(12 * factor))
        header_size = max(8, int(10 * factor))
        chip_size = max(7, int(9 * factor))

        self.preview_title.setFont(QFont("", title_size, QFont.Weight.Bold))
        self.preview_header.setFixedHeight(max(28, int(32 * factor)))
        self.preview_lang_btn.setFixedSize(max(22, int(24 * factor)), max(22, int(24 * factor)))
        self._style_preview_header_controls(factor)

        for btn in (
            self.preview_strength_btn,
            self.preview_elements_btn,
            self.preview_modality_btn,
        ):
            btn.setFont(QFont("", body_size, QFont.Weight.Bold))

        self.preview_sep_1.setFont(QFont("", header_size))
        self.preview_sep_2.setFont(QFont("", header_size))
        self.preview_lang_btn.setFont(QFont("", chip_size, QFont.Weight.Bold))

        frame_width = INFO_PANEL_WIDTH
        self.preview_frame.setFixedWidth(frame_width)
        self.preview_table.setMinimumWidth(frame_width - 20)
        self.preview_table.setMaximumWidth(frame_width - 20)
        self.preview_table.setMinimumHeight(max(200, int(260 * factor)))
        self.preview_table.verticalHeader().setDefaultSectionSize(max(24, int(30 * factor)))
        self.preview_table.horizontalHeader().setMinimumHeight(max(24, int(28 * factor)))
        self.preview_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {get_theme_colors()["secondary_dark"]};
                border: none;
                font-size: {max(8, int(11 * factor))}px;
                gridline-color: {get_theme_colors()["secondary_light"]};
            }}
            QTableWidget::item {{
                background-color: transparent;
                padding: {max(2, int(3 * factor))}px;
            }}
            QHeaderView::section {{
                background-color: {get_theme_colors()["secondary"]};
                color: {get_theme_colors()["secondary_text"]};
                border: 1px solid {get_theme_colors()["secondary_light"]};
                padding: {max(2, int(4 * factor))}px;
                font-size: {max(8, int(10 * factor))}px;
                font-weight: bold;
            }}
        """)
        for row in range(self.preview_table.rowCount()):
            self.preview_table.setRowHeight(row, max(24, int(30 * factor)))

        # Mirror the live panel's delegate emphasis with a highlighted high value.
        highlight_item = self.preview_table.item(5, 3)
        if highlight_item:
            theme = get_theme_colors()
            highlight_item.setBackground(QColor(theme["secondary_light"]))
            highlight_item.setForeground(QColor(theme["secondary_text"]))

    def _load_saved_scale(self):
        """Load saved scale factor from app_settings.json."""
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            saved = settings.get("display.font_scale", 1.0)
            slider_val = int(saved * 100)
            slider_val = max(60, min(160, slider_val))
            # Block signals to prevent triggering _on_slider_changed during init
            self.scale_slider.blockSignals(True)
            self.scale_slider.setValue(slider_val)
            self.scale_value_label.setText(f"{slider_val}%")
            self.scale_slider.blockSignals(False)
            self._saved_scale = saved  # cache loaded value
            self._apply_preview_scale(saved)
        except Exception:
            self._saved_scale = 1.0
            self._apply_preview_scale(1.0)

    def _on_slider_changed(self, value: int):
        """Handle slider value change — updates preview only. Use Apply to commit."""
        factor = value / 100.0
        self.scale_value_label.setText(f"{value}%")
        self._apply_preview_scale(factor)

        # Show restart warning when scale differs from saved (use cache — no file I/O on tick)
        self.restart_warning.setVisible(abs(factor - self._saved_scale) > 0.01)

    def _on_apply(self):
        """Apply the current scale: persist, set global factor, emit signal for live refresh."""
        from ui.qt_theme import set_scale_factor
        factor = self.scale_slider.value() / 100.0

        # Apply scale globally
        set_scale_factor(factor)

        # Persist and update cache
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            settings.set("display.font_scale", factor)
            self._saved_scale = factor  # cache updated — slider tick comparisons now compare against new value
        except Exception:
            pass

        # Show restart warning (in case live refresh doesn't cover everything)
        self.restart_warning.setVisible(True)

        # Emit signal for live refresh
        self.scale_changed.emit(factor)

    def _on_reset(self):
        """Reset slider to 100%."""
        self.scale_slider.setValue(100)

    def _on_auto_detect(self):
        """Auto-detect optimal scale based on screen DPI."""
        try:
            from ui.qt_theme import detect_optimal_scale
            optimal = detect_optimal_scale()
            optimal_pct = int(optimal * 100)
            self.scale_slider.setValue(optimal_pct)
            self._update_dpi_info()
        except Exception:
            pass

    def _update_dpi_info(self):
        """Show current screen DPI info."""
        try:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                dpi = screen.logicalDotsPerInch()
                size = screen.size()
                self.dpi_info_label.setText(
                    f"Screen: {size.width()}x{size.height()} | DPI: {dpi:.0f} | "
                    f"Baseline: 96 DPI = 100%"
                )
        except Exception:
            self.dpi_info_label.setText("Screen info unavailable")

    def refresh_theme(self):
        """Refresh styles when theme changes."""
        from ui.qt_theme import (
            get_theme_colors, get_group_box_style,
            get_primary_button_style, get_secondary_button_style,
        )
        theme = get_theme_colors()
        self.setStyleSheet(f"DisplayScaleTab {{ background-color: {theme['secondary_dark']}; }}")
        self.scale_group.setStyleSheet(get_group_box_style())
        self.reset_btn.setStyleSheet(get_primary_button_style())
        self.auto_detect_btn.setStyleSheet(get_secondary_button_style())
        self.apply_btn.setStyleSheet(get_primary_button_style())
        self.scale_tip_label.setStyleSheet(f"color: {theme['secondary_text']};")
        self.preview_title.setStyleSheet(f"color: {theme['secondary_text']}; border: none;")
        self.dpi_info_label.setStyleSheet(f"color: {theme['secondary_text']};")
        self._apply_preview_theme()


# =============================================================================
# SHARED ZODIAC & CALCULATION TAB — Core/Lite-owned settings
# =============================================================================

class _PadlockButton(QToolButton):
    """Per-setting lock toggle shared by Core and Pro settings panels."""

    def __init__(self, key_paths, parent=None):
        super().__init__(parent)
        self._keys = [key_paths] if isinstance(key_paths, str) else list(key_paths)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from managers.settings_manager import get_settings
        self._settings = get_settings()
        self.setChecked(any(self._settings.is_locked(k) for k in self._keys))
        self._refresh()
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked):
        for key in self._keys:
            self._settings.set_locked(key, checked)
        self._refresh()

    def _refresh(self):
        locked = self.isChecked()
        self.setText("\U0001f512" if locked else "\U0001f513")
        self.setToolTip(
            "Locked: Varuna always starts with this value."
            if locked else
            "Unlocked: Varuna remembers the last value you used."
        )
        self.setStyleSheet("color:#D4AF37;" if locked else "color:#888;")


def _locked_row(form, key_paths, label_text, field, desc=None):
    cell = QWidget()
    row = QHBoxLayout(cell)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(_PadlockButton(key_paths))
    row.addWidget(QLabel(label_text))
    row.addStretch()
    form.addRow(cell, field)
    if desc:
        detail = QLabel(desc)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color:#888; font-size:{scaled_area_px('info_text')}px; font-style:italic; margin-bottom:4px;")
        form.addRow("", detail)


def _locked_radio_group(form, key_paths, label_text, options, desc=None):
    """Add a QFormLayout block: padlock + bold label, then horizontal radio buttons.

    ``options`` is a list of ``(display_label, value)`` tuples.  The radio
    ``value`` is stashed on each button via ``setProperty("opt_value", value)``
    so callers can read/set the selection by value.

    Returns the ``QButtonGroup``.
    """
    parent = form.parentWidget()

    header_cell = QWidget()
    hh = QHBoxLayout(header_cell)
    hh.setContentsMargins(0, 0, 0, 0)
    hh.setSpacing(6)
    hh.addWidget(_PadlockButton(key_paths))
    lbl = QLabel(label_text)
    lbl.setStyleSheet("font-weight: bold;")
    hh.addWidget(lbl)
    hh.addStretch()
    form.addRow("", header_cell)

    radio_cell = QWidget()
    rh = QHBoxLayout(radio_cell)
    rh.setContentsMargins(0, 0, 0, 0)
    rh.setSpacing(10)
    group = QButtonGroup(parent)
    group.setExclusive(True)
    for i, (display, value) in enumerate(options):
        rb = QRadioButton(display)
        rb.setProperty("opt_value", value)
        rh.addWidget(rb)
        group.addButton(rb, i)
    rh.addStretch()
    form.addRow("", radio_cell)

    if desc:
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color:#888; font-size:{scaled_area_px('info_text')}px; font-style:italic; margin-bottom:4px;")
        form.addRow("", d)

    return group


# Radio index 0-6 -> (mode, tab) for the Aspects panel default sub-tab.
ASPECTS_RADIO = [
    ("vedic", 0),   # 0 Aspects (Vedic)
    ("vedic", 1),   # 1 Avastha
    ("vedic", 2),   # 2 Shame
    ("vedic", 3),   # 3 Exchange
    ("tajika", 0),  # 4 Aspects (Tajika)
    ("tajika", 1),  # 5 Relations
    ("tajika", 2),  # 6 Yogas
]


def _aspects_to_radio(mode, tab):
    try:
        return ASPECTS_RADIO.index((mode, tab))
    except ValueError:
        return 0


class ZodiacCalculationTab(QWidget):
    """Core Zodiac, dasha, house-system, and nakshatra settings."""

    zodiac_changed = Signal(str)
    names_changed = Signal(bool)
    ayanamsa_changed = Signal(int)
    dasha_changed = Signal()
    house_system_changed = Signal(str)
    house_display_mode_changed = Signal(str)

    # (display, mode, use_western_names). The third value IS written straight to
    # zodiac.use_western_names on Apply, so it must match what displayed_sign_name()
    # renders: False -> Aditya names, True -> Western names (core/aditya_mode.py).
    # Native naming per system is therefore use_western = (mode != "aditya"):
    # Aditya -> Aditya names (False); Tropical Classic / Sidereal -> Western (True).
    # Even indices (0, 2, 4) are the native entries; odd indices are the alternates.
    # (SPEC-MODE-001 section 4.1; corrected from a prior flag inversion on TC/Sidereal.)
    _ZODIAC_OPTIONS = [
        ("Aditya Circle (Dhata, Aryama, Mitra...)", "aditya", False),
        ("Aditya Circle with Western names (Aries, Taurus...)", "aditya", True),
        ("Tropical Classic (Aries, Taurus...)", "tropical_classic", True),
        ("Tropical Classic with Aditya names (Dhata, Aryama...)", "tropical_classic", False),
        ("Sidereal (Aries, Taurus... shifted by ayanamsa)", "sidereal", True),
        ("Sidereal with Aditya names (used in Indian traditions)", "sidereal", False),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._read_from_settings()
        self.zodiac_combo.currentIndexChanged.connect(self._update_ayanamsa_enabled)
        self.dasha_right_mode_combo.currentIndexChanged.connect(self._update_dasha_right_enabled)
        self._update_ayanamsa_enabled()
        self._update_dasha_right_enabled()

    def _setup_ui(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"ZodiacCalculationTab {{ background-color: {theme['secondary_dark']}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        desc_style = f"color: #888; font-size: {scaled_area_px('info_text')}px; font-style: italic; margin-bottom: 4px;"

        # SPEC-MODE-001: experience-level gate at the top of the Zodiac section.
        # Beginner hides alternative sign-naming; Advanced exposes all 6 combinations.
        self.experience_radio = _locked_radio_group(
            form,
            "ui.experience_level",
            "Experience level:",
            [("Beginner", "beginner"), ("Advanced", "advanced")],
            desc="Shows only the 3 main zodiac systems. Switch to Advanced to "
                 "access alternative sign naming.",
        )

        zodiac_header = QLabel("Zodiac System & Sign Naming")
        zodiac_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 4px;")
        form.addRow("", zodiac_header)

        # Description text is mode-dependent; rebuilt by _update_zodiac_desc().
        self.zodiac_desc = QLabel()
        self.zodiac_desc.setWordWrap(True)
        self.zodiac_desc.setStyleSheet(desc_style)
        form.addRow("", self.zodiac_desc)

        # Populated by _rebuild_zodiac_combo() (called from _read_from_settings),
        # which respects the active experience level (3 native entries or all 6).
        self.zodiac_combo = QComboBox()
        self.zodiac_combo.setMaximumWidth(220)
        _locked_row(form, ["zodiac.mode", "zodiac.use_western_names"], "Zodiac mode:", self.zodiac_combo)

        ayan_header = QLabel("Ayanamsa (Sidereal only)")
        ayan_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        form.addRow("", ayan_header)

        ayan_desc = QLabel(
            "The ayanamsa is the angular difference between the Tropical and "
            "Sidereal zodiacs. It only applies in Sidereal mode."
        )
        ayan_desc.setWordWrap(True)
        ayan_desc.setStyleSheet(desc_style)
        form.addRow("", ayan_desc)

        self.ayanamsa_combo = QComboBox()
        try:
            from core.ayanamsa_data import AYANAMSA_OPTIONS
            for aid, name, _cat, _tip in AYANAMSA_OPTIONS:
                self.ayanamsa_combo.addItem(name, aid)
        except ImportError:
            self.ayanamsa_combo.addItem("Lahiri", 1)
        self.ayanamsa_combo.setMaximumWidth(220)
        _locked_row(form, "zodiac.ayanamsa_id", "Ayanamsa:", self.ayanamsa_combo)

        dasha_header = QLabel("Dasha Ayanamshas")
        dasha_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        form.addRow("", dasha_header)

        dasha_desc = QLabel(
            "Each dasha panel can use its own ayanamsa. The right panel only "
            "uses an ayanamsa in Vimshottari mode; Planetary Ages uses fixed "
            "natural periods."
        )
        dasha_desc.setWordWrap(True)
        dasha_desc.setStyleSheet(desc_style)
        form.addRow("", dasha_desc)

        self.dasha_left_combo = QComboBox()
        self.dasha_right_combo = QComboBox()
        try:
            from core.ayanamsa_data import AYANAMSA_OPTIONS
            for aid, name, _cat, _tip in AYANAMSA_OPTIONS:
                self.dasha_left_combo.addItem(name, aid)
                self.dasha_right_combo.addItem(name, aid)
        except ImportError:
            self.dasha_left_combo.addItem("Vedanga Jyotisha", 100)
            self.dasha_right_combo.addItem("Dhruva GC mid-Mula", 98)
        self.dasha_left_combo.setMaximumWidth(220)
        self.dasha_right_combo.setMaximumWidth(220)
        _locked_row(form, "dasha.left.ayanamsa_id", "Left (Vimshottari) ayanamsa:", self.dasha_left_combo)

        self.dasha_right_mode_combo = QComboBox()
        self.dasha_right_mode_combo.addItem("Planetary Ages", "nisarga")
        self.dasha_right_mode_combo.addItem("Vimshottari", "vimshottari")
        self.dasha_right_mode_combo.setMaximumWidth(220)
        _locked_row(
            form,
            ["dasha.right.mode", "dasha.right.ayanamsa_id"],
            "Right panel mode:",
            self.dasha_right_mode_combo,
        )
        form.addRow("Right (Vimshottari) ayanamsa:", self.dasha_right_combo)

        self.nak_coords_combo = QComboBox()
        self.nak_coords_combo.addItem("Neither (ecliptic, default)", "neither")
        self.nak_coords_combo.addItem("Equatorial", "equatorial")
        self.nak_coords_combo.setMaximumWidth(220)
        _locked_row(form, "zodiac.nakshatra_coords", "Nakshatra coordinates:", self.nak_coords_combo)
        nak_desc = QLabel(
            "Controls how custom ayanamsas (Dhruva, Vedanga) compute "
            "nakshatra positions. 'Neither' matches Kala's default."
        )
        nak_desc.setWordWrap(True)
        nak_desc.setStyleSheet(desc_style)
        form.addRow("", nak_desc)

        house_header = QLabel("House System")
        house_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        form.addRow("", house_header)

        house_desc = QLabel(
            "Placidus is the common modern Western default. Whole Sign keeps "
            "one sign per house. Campanus is the default option used in Ernst "
            "group studies."
        )
        house_desc.setWordWrap(True)
        house_desc.setStyleSheet(desc_style)
        form.addRow("", house_desc)

        self.house_combo = QComboBox()
        for display, key in _HOUSE_SYSTEMS:
            self.house_combo.addItem(display, key)
        self.house_combo.setMaximumWidth(220)
        _locked_row(form, "zodiac.house_system", "House system:", self.house_combo)

        house_note = QLabel("Applies immediately to the open chart when you click Apply.")
        house_note.setStyleSheet(f"color: #888; font-size: {scaled_area_px('status')}px;")
        form.addRow("", house_note)

        self.wheel_display_combo = QComboBox()
        self.wheel_display_combo.addItem("Sign-based (traditional)", "sign_based")
        self.wheel_display_combo.addItem("Standard Western houses", "standard_western")
        self.wheel_display_combo.setMaximumWidth(220)
        form.addRow("Wheel house display:", self.wheel_display_combo)

        wheel_display_desc = QLabel(
            "Standard Western layout starts the 1st house at the exact Ascendant "
            "degree. Wheel chart only."
        )
        wheel_display_desc.setWordWrap(True)
        wheel_display_desc.setStyleSheet(desc_style)
        form.addRow("", wheel_display_desc)

        cot_header = QLabel("Cards of Truth")
        cot_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        form.addRow("", cot_header)

        self.cot_order_combo = QComboBox()
        self.cot_order_combo.addItem("Vedic (Sun, Moon, Mars, Mercury...)", "vedic")
        self.cot_order_combo.addItem("Solar System (Sun, Moon, Mercury, Venus, Mars...)", "solar_system")
        self.cot_order_combo.setMaximumWidth(320)
        _locked_row(form, "cot.planet_order", "Planet order:", self.cot_order_combo)

        cot_desc = QLabel(
            "Vedic uses the weekday order (Sun=Sunday, Moon=Monday, Mars=Tuesday...). "
            "Solar System uses heliocentric distance from the Sun."
        )
        cot_desc.setWordWrap(True)
        cot_desc.setStyleSheet(desc_style)
        form.addRow("", cot_desc)

        layout.addLayout(form)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(24, 8, 24, 12)
        button_row.addStretch()

        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.setFixedWidth(150)
        self.reset_btn.setStyleSheet(get_secondary_button_style())
        self.reset_btn.clicked.connect(self._on_reset)
        button_row.addWidget(self.reset_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFixedWidth(100)
        self.apply_btn.setStyleSheet(get_primary_button_style())
        self.apply_btn.clicked.connect(self._on_apply)
        button_row.addWidget(self.apply_btn)
        outer.addLayout(button_row)

    def _find_combo_index(self, mode, western):
        """Locate (mode, western) on the ACTUAL combo items, not _ZODIAC_OPTIONS.

        Required because the Beginner combo holds only 3 entries, so positional
        _ZODIAC_OPTIONS indices no longer line up (SPEC-MODE-001 section 4.1).
        Falls back within the same system rather than silently jumping to
        Aditya Circle: exact match -> same system's native entry -> any entry
        of that system -> 0.
        """
        count = self.zodiac_combo.count()
        for i in range(count):
            data = self.zodiac_combo.itemData(i)
            if data and data[0] == mode and data[1] == western:
                return i
        native = (mode != "aditya")
        for i in range(count):
            data = self.zodiac_combo.itemData(i)
            if data and data[0] == mode and data[1] == native:
                return i
        for i in range(count):
            data = self.zodiac_combo.itemData(i)
            if data and data[0] == mode:
                return i
        return 0

    def _experience_level(self):
        from managers.settings_manager import get_settings
        level = get_settings().get("ui.experience_level", "beginner")
        return "advanced" if level == "advanced" else "beginner"

    def _rebuild_zodiac_combo(self):
        """Repopulate the zodiac combo for the active experience level.

        Beginner -> the 3 native entries (even indices of _ZODIAC_OPTIONS).
        Advanced -> all 6 entries. The prior selection is preserved by value
        via _find_combo_index (same-system fallback), so switching levels never
        silently changes the zodiac system.
        """
        level = self._experience_level()
        prior = self.zodiac_combo.currentData()
        entries = self._ZODIAC_OPTIONS if level == "advanced" else self._ZODIAC_OPTIONS[0::2]

        self.zodiac_combo.blockSignals(True)
        self.zodiac_combo.clear()
        for display, mode, western in entries:
            self.zodiac_combo.addItem(display, (mode, western))
        if prior:
            self.zodiac_combo.setCurrentIndex(self._find_combo_index(prior[0], prior[1]))
        self.zodiac_combo.blockSignals(False)

        self._update_zodiac_desc(level)

    def _update_zodiac_desc(self, level=None):
        if level is None:
            level = self._experience_level()
        if level == "advanced":
            self.zodiac_desc.setText(
                "Three systems define where the 12 divisions start in the sky. "
                "Each can display Aditya names or Western names."
            )
        else:
            self.zodiac_desc.setText(
                "Three systems define where the 12 divisions start in the sky. "
                "Switch to Advanced mode (above) to access alternative sign naming."
            )

    @staticmethod
    def _select_radio_value(group, value):
        for b in group.buttons():
            if b.property("opt_value") == value:
                b.setChecked(True)
                return

    @staticmethod
    def _radio_value(group, default=None):
        b = group.checkedButton()
        if b is None:
            return default
        return b.property("opt_value")

    def showEvent(self, event):
        # Pick up an experience-level change made elsewhere (e.g. remote control)
        # without clobbering unapplied edits: only rebuild when the entry count
        # no longer matches the stored level (SPEC-MODE-001 section 4.1 / M11).
        super().showEvent(event)
        expected = 6 if self._experience_level() == "advanced" else 3
        if self.zodiac_combo.count() != expected:
            self._select_radio_value(self.experience_radio, self._experience_level())
            self._rebuild_zodiac_combo()

    def _update_ayanamsa_enabled(self):
        data = self.zodiac_combo.currentData()
        if data:
            mode, _western = data
            self.ayanamsa_combo.setEnabled(mode == "sidereal")

    def _update_dasha_right_enabled(self):
        self.dasha_right_combo.setEnabled(self.dasha_right_mode_combo.currentData() == "vimshottari")

    def _read_from_settings(self):
        from managers.settings_manager import get_settings
        settings = get_settings()

        self._select_radio_value(self.experience_radio, self._experience_level())
        self._rebuild_zodiac_combo()
        mode = settings.get("zodiac.mode", "aditya")
        western = settings.get("zodiac.use_western_names", False)
        self.zodiac_combo.setCurrentIndex(self._find_combo_index(mode, western))

        for combo, key, default in (
            (self.ayanamsa_combo, "zodiac.ayanamsa_id", 1),
            (self.house_combo, "zodiac.house_system", "campanus"),
            (self.wheel_display_combo, "chart.wheel_house_display", "sign_based"),
            (self.dasha_left_combo, "dasha.left.ayanamsa_id", 100),
            (self.dasha_right_mode_combo, "dasha.right.mode", "nisarga"),
            (self.dasha_right_combo, "dasha.right.ayanamsa_id", 98),
            (self.nak_coords_combo, "zodiac.nakshatra_coords", "neither"),
        ):
            idx = combo.findData(settings.get(key, default))
            if idx >= 0:
                combo.setCurrentIndex(idx)

        self._update_ayanamsa_enabled()
        self._update_dasha_right_enabled()

    def _on_apply(self):
        from managers.settings_manager import get_settings
        settings = get_settings()

        # SPEC-MODE-001: experience level. In Beginner, force native naming for
        # the chosen system (use_western = mode != "aditya") so the alternative
        # label set can never be committed from this panel.
        new_level = self._radio_value(self.experience_radio, "beginner")
        old_level = settings.get("ui.experience_level", "beginner")

        mode, western = self.zodiac_combo.currentData()
        if new_level == "beginner":
            western = (mode != "aditya")
        old_mode = settings.get("zodiac.mode", "aditya")
        old_western = settings.get("zodiac.use_western_names", False)
        old_ayanamsa = settings.get("zodiac.ayanamsa_id", 1)
        old_house = settings.get("zodiac.house_system", "campanus")
        old_left = settings.get("dasha.left.ayanamsa_id", 100)
        old_right_mode = settings.get("dasha.right.mode", "nisarga")
        old_right_aid = settings.get("dasha.right.ayanamsa_id", 98)
        old_nak_coords = settings.get("zodiac.nakshatra_coords", "neither")

        new_ayanamsa = self.ayanamsa_combo.currentData()
        new_house = self.house_combo.currentData()
        new_left = self.dasha_left_combo.currentData()
        new_right_mode = self.dasha_right_mode_combo.currentData()
        new_right_aid = self.dasha_right_combo.currentData()
        new_wheel_display = self.wheel_display_combo.currentData()

        settings.set("ui.experience_level", new_level)
        settings.set("zodiac.mode", mode)
        settings.set("zodiac.use_western_names", western)
        settings.set("zodiac.ayanamsa_id", new_ayanamsa)
        settings.set("zodiac.house_system", new_house)
        settings.set("chart.wheel_house_display", new_wheel_display)
        settings.set("dasha.left.ayanamsa_id", new_left)
        settings.set("dasha.right.mode", new_right_mode)
        settings.set("dasha.right.ayanamsa_id", new_right_aid)
        new_nak_coords = self.nak_coords_combo.currentData()
        settings.set("zodiac.nakshatra_coords", new_nak_coords)
        settings.set("cot.planet_order", self.cot_order_combo.currentData())

        if mode != old_mode:
            self.zodiac_changed.emit(mode)
        # Emit names_changed when the naming differs from what is now stored, OR
        # when the system changed to an alternative-naming selection. The latter
        # is essential: on a mode change _set_aditya_mode() resets use_western_names
        # to the system's native default, so an explicit "<system> with <alt> names"
        # pick (western != native) must be re-asserted afterwards or it is silently
        # lost. zodiac_changed is emitted first, so this names_changed lands last.
        if western != old_western or (mode != old_mode and western != (mode != "aditya")):
            self.names_changed.emit(western)
        if new_ayanamsa != old_ayanamsa:
            self.ayanamsa_changed.emit(new_ayanamsa)
        if new_house != old_house:
            self.house_system_changed.emit(new_house)
        self.house_display_mode_changed.emit(new_wheel_display)
        if (new_left != old_left or new_right_mode != old_right_mode
                or new_right_aid != old_right_aid
                or new_nak_coords != old_nak_coords):
            self.dasha_changed.emit()

        # Rebuild the combo (3 <-> 6 entries) when the experience level changed,
        # giving instant visual feedback and re-selecting the same system.
        if new_level != old_level:
            self._rebuild_zodiac_combo()
            self.zodiac_combo.setCurrentIndex(self._find_combo_index(mode, western))

    def _on_reset(self):
        from managers.settings_manager import get_settings
        settings = get_settings()
        settings.reset_to_defaults("zodiac")
        settings.set("dasha.left.ayanamsa_id", 100)
        settings.set("dasha.right.mode", "nisarga")
        settings.set("dasha.right.ayanamsa_id", 98)
        self._read_from_settings()

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"ZodiacCalculationTab {{ background-color: {theme['secondary_dark']}; }}")


# =============================================================================
# FONT SIZES SECTION — Per-area font size controls (SPEC-FONT-001)
# =============================================================================


class MixedValueSpinBox(QSpinBox):
    """QSpinBox that can display '--' when areas have mixed values."""

    MIXED_TEXT = "--"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_mixed = False

    def set_mixed(self, mixed: bool):
        if self._is_mixed == mixed:
            return
        self._is_mixed = mixed
        self.blockSignals(True)
        self.setValue(self.value())
        self.blockSignals(False)

    def textFromValue(self, value: int) -> str:
        if self._is_mixed:
            return self.MIXED_TEXT
        return super().textFromValue(value)

    def validate(self, text: str, pos: int):
        if text == self.MIXED_TEXT:
            return (QValidator.State.Acceptable, text, pos)
        return super().validate(text, pos)

    def valueFromText(self, text: str) -> int:
        if text == self.MIXED_TEXT:
            return self.value()
        return super().valueFromText(text)

    def stepBy(self, steps: int):
        if self._is_mixed:
            self._is_mixed = False
        super().stepBy(steps)


class FontSizesSection(QWidget):
    """Per-area font size controls (SPEC-FONT-001)."""

    font_sizes_changed = Signal()

    _AREA_LABELS = [
        ("tables", "Tables & Data"),
        ("table_headers", "Table Headers"),
        ("panel_titles", "Panel Titles"),
        ("info_text", "Info & Descriptions"),
        ("buttons", "Buttons & Controls"),
        ("sidebar", "Sidebar & Navigation"),
        ("status", "Status & Captions"),
        ("tabs", "Tab Bar"),
    ]

    _PREVIEW_INFO = {
        "tables": {
            "where": "Center panels: Strength, Aspects, Elements, Karakas data rows. "
                     "Also: planet positions in chart info, Find Chart results, dasha cycle labels.",
            "samples": [
                "Sun  42.8  |  Moon  187.3  |  Mars  315.6  |  Jupiter  78.2",
                "Venus  Dhata  12.5  |  Saturn  Mitra  28.3  |  Mercury  Aryama  4.1",
            ],
        },
        "table_headers": {
            "where": "Column headers above data tables in center panels (Strength, Aspects, "
                     "Elements). Also: section headers in chart info dialogs, dual chart comparison names.",
            "samples": [
                "PLANET        DIGBALA        UCCHA        SIGN        DEGREE",
                "NAME          LONGITUDE      SPEED        HOUSE       DIGNITY",
            ],
        },
        "panel_titles": {
            "where": "Large section headings in center panels (e.g. 'Strength', 'Aspects', "
                     "'Elements'). Also: dialog titles, welcome screen, chart creation headers, "
                     "Find Chart section titles.",
            "samples": [
                "Strength  /  Aspects  /  Elements  /  Karakas",
            ],
        },
        "info_text": {
            "where": "Help text, tooltips, descriptions throughout the app. "
                     "Includes: chart editing form labels, ayanamsa dialog help, "
                     "search field labels in Find Chart, loading screen messages.",
            "samples": [
                "Enter the birth date, time, and location to calculate the chart",
                "Hover over a planet to see its full description and dignity status",
            ],
        },
        "buttons": {
            "where": "All clickable controls: top bar buttons (Transit, Now, Aditya Circle, "
                     "Add Chart), dialog OK/Cancel buttons, dasha level selectors, "
                     "Save buttons in chart creation, combo box labels.",
            "samples": [
                "Apply    Transit    Aditya Circle    Now    Add Chart",
                "Save    Cancel    OK    Level 1    Level 2    Level 3",
            ],
        },
        "sidebar": {
            "where": "Left column lists: sign selector (12 sign names), "
                     "varga division selector (D1, D2, D9...), "
                     "chart memory expanded sublists (houses, planets, strengths).",
            "samples": [
                "Dhata    Aryama    Mitra    Varuna    Indra    Vivasvan",
                "D1 Rasi    D2 Hora    D9 Navamsa    D12 Dvadasamsa",
            ],
        },
        "status": {
            "where": "Small captions and status messages: dasha active cycle info "
                     "below the list, dual chart comparison metadata, login error messages, "
                     "Find Chart result counts, footnotes in chart info panels.",
            "samples": [
                "Maha: Sun 6y  |  Antar: Moon 6m  |  Pratyantar: Mars 12d",
                "3 charts found  |  Screen: 1920x1080  |  DPI: 96",
            ],
        },
        "tabs": {
            "where": "Main tab bar at the top of the window: the row of tabs "
                     "used to switch between Chart, Settings, Find Chart, Nakshatra, "
                     "Predictive Tools, and other main sections.",
            "samples": [
                "CHART    SETTINGS    FIND CHART    NAKSHATRA    PREDICTIVE TOOLS",
            ],
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spinboxes = {}
        self._build_ui()
        self._read_from_settings()

    def _build_ui(self):
        theme = get_theme_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(0)

        self._header_label = QLabel("FONT SIZES")
        self._header_label.setStyleSheet(
            f"color: {theme['primary']}; font-weight: bold; "
            f"font-size: {scaled_area_px('panel_titles')}px; "
            f"padding-bottom: 8px;"
        )
        layout.addWidget(self._header_label)

        master_row = QHBoxLayout()
        master_row.setContentsMargins(0, 0, 0, 0)
        self._master_label = QLabel("All Areas:")
        self._master_label.setFixedWidth(160)
        self._master_label.setStyleSheet(
            f"color: {theme['primary_text']}; font-weight: bold;"
        )
        master_row.addWidget(self._master_label)
        self._master_spin = MixedValueSpinBox()
        self._master_spin.setRange(7, 24)
        self._master_spin.setFixedWidth(80)
        self._master_spin.valueChanged.connect(self._on_master_changed)
        master_row.addWidget(self._master_spin)
        master_row.addStretch()
        layout.addLayout(master_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"color: {theme['secondary_dark']};")
        layout.addWidget(sep)

        grid = QGridLayout()
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setVerticalSpacing(16)
        grid.setHorizontalSpacing(16)
        grid.setColumnMinimumWidth(0, 160)
        grid.setColumnMinimumWidth(1, 80)
        grid.setColumnStretch(2, 1)

        self._preview_labels = {}
        self._area_labels = []
        self._where_labels = []
        self._preview_sample_style = (
            f"color: {theme['primary_text']}; "
            f"background-color: {theme['secondary']}; "
            f"border: 1px solid {theme['secondary_dark']}; "
            f"border-radius: 3px; padding: 4px 8px;"
        )
        where_style = (
            f"color: {theme['secondary_text']}; font-size: 9px; "
            f"padding: 0px; margin: 0px;"
        )

        for row_idx, (area_id, label_text) in enumerate(self._AREA_LABELS):
            label = QLabel(f"{label_text}:")
            label.setStyleSheet(f"color: {theme['primary_text']};")
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label, row_idx, 0)
            self._area_labels.append(label)

            spin = QSpinBox()
            spin.setRange(7, 24)
            spin.setFixedWidth(80)
            spin.valueChanged.connect(
                lambda val, aid=area_id: self._on_area_changed(aid, val)
            )
            grid.addWidget(spin, row_idx, 1, Qt.AlignmentFlag.AlignTop)
            self._spinboxes[area_id] = spin

            info = self._PREVIEW_INFO.get(area_id, {})
            preview_cell = QWidget()
            cell_layout = QVBoxLayout(preview_cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)

            where_label = QLabel(info.get("where", ""))
            where_label.setWordWrap(True)
            where_label.setStyleSheet(where_style)
            cell_layout.addWidget(where_label)
            self._where_labels.append(where_label)

            sample_labels = []
            for sample_text in info.get("samples", []):
                slabel = QLabel(sample_text)
                slabel.setStyleSheet(self._preview_sample_style)
                slabel.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                cell_layout.addWidget(slabel)
                sample_labels.append(slabel)

            preview_cell.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            grid.addWidget(preview_cell, row_idx, 2)
            self._preview_labels[area_id] = sample_labels

        layout.addLayout(grid)

        self._tip_label = QLabel(
            "These sizes are multiplied by the Display Scale. "
            "Change scale for DPI, change these for relative "
            "emphasis between areas."
        )
        self._tip_label.setWordWrap(True)
        self._tip_label.setStyleSheet(
            f"color: {theme['secondary_text']}; "
            f"font-size: {scaled_area_px('status')}px; "
            f"padding-top: 4px;"
        )
        layout.addWidget(self._tip_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reset_btn = QPushButton("Reset All")
        reset_btn.setFixedWidth(120)
        reset_btn.setStyleSheet(get_secondary_button_style())
        reset_btn.clicked.connect(self._on_reset_all)
        btn_row.addWidget(reset_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(120)
        apply_btn.setStyleSheet(get_primary_button_style())
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

    def _read_from_settings(self):
        settings = get_settings()
        for area_id, _ in self._AREA_LABELS:
            default = AREA_DEFAULTS.get(area_id, 11)
            value = settings.get(f"display.fonts.{area_id}", default)
            spin = self._spinboxes[area_id]
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._update_master()
        self._update_preview()

    def _on_area_changed(self, area_id: str, value: int):
        self._update_master()
        self._update_preview()

    def _on_master_changed(self, value: int):
        if self._master_spin._is_mixed:
            self._master_spin.set_mixed(False)
        for area_id, _ in self._AREA_LABELS:
            spin = self._spinboxes[area_id]
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._update_preview()

    def _on_apply(self):
        for area_id, _ in self._AREA_LABELS:
            value = self._spinboxes[area_id].value()
            set_area_font_size(area_id, value)
            get_settings().set(f"display.fonts.{area_id}", value)
        self._update_preview()
        self.font_sizes_changed.emit()

    def _on_reset_all(self):
        for area_id, _ in self._AREA_LABELS:
            default = AREA_DEFAULTS.get(area_id, 11)
            spin = self._spinboxes[area_id]
            spin.blockSignals(True)
            spin.setValue(default)
            spin.blockSignals(False)
        self._update_master()
        self._update_preview()

    def _update_master(self):
        values = [s.value() for s in self._spinboxes.values()]
        if len(set(values)) == 1:
            self._master_spin.set_mixed(False)
            self._master_spin.blockSignals(True)
            self._master_spin.setValue(values[0])
            self._master_spin.blockSignals(False)
        else:
            self._master_spin.set_mixed(True)

    def _update_preview(self):
        from ui.qt_theme import get_scale_factor
        sf = get_scale_factor()
        for area_id, sample_labels in self._preview_labels.items():
            base = self._spinboxes[area_id].value()
            px = max(5, int(base * sf))
            for slabel in sample_labels:
                slabel.setStyleSheet(
                    f"{self._preview_sample_style} font-size: {px}px;"
                )

    def refresh_theme(self):
        theme = get_theme_colors()
        self._header_label.setStyleSheet(
            f"color: {theme['primary']}; font-weight: bold; "
            f"font-size: {scaled_area_px('panel_titles')}px; "
            f"padding-bottom: 8px;"
        )
        self._master_label.setStyleSheet(
            f"color: {theme['primary_text']}; font-weight: bold;"
        )
        for lbl in self._area_labels:
            lbl.setStyleSheet(f"color: {theme['primary_text']};")
        where_style = (
            f"color: {theme['secondary_text']}; font-size: 9px; "
            f"padding: 0px; margin: 0px;"
        )
        for lbl in self._where_labels:
            lbl.setStyleSheet(where_style)
        self._tip_label.setStyleSheet(
            f"color: {theme['secondary_text']}; "
            f"font-size: {scaled_area_px('status')}px; "
            f"padding-top: 4px;"
        )
        self._preview_sample_style = (
            f"color: {theme['primary_text']}; "
            f"background-color: {theme['secondary']}; "
            f"border: 1px solid {theme['secondary_dark']}; "
            f"border-radius: 3px; padding: 4px 8px;"
        )
        self._update_preview()
        for btn in self.findChildren(QPushButton):
            if btn.text() == "Apply":
                btn.setStyleSheet(get_primary_button_style())
            else:
                btn.setStyleSheet(get_secondary_button_style())


# =============================================================================
# CHART DISPLAY SECTION — View type, outer planets, rings, pies, cusp glow,
#                          default sub-tabs (SPEC-SET-001 s2.1 Lite-First)
# =============================================================================


class ChartDisplaySection(QWidget):
    """Chart view, outer planets, borders, rims, rings, pies, cusp glow,
    and default panel sub-tabs. Shared by both Lite and Pro settings."""

    chart_display_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.section_key = "chart"
        self._build_ui()
        self._read_from_settings()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._create_controls(form)
        layout.addLayout(form)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(24, 8, 24, 12)
        btn_bar.addStretch()

        self._reset_btn = QPushButton("Reset to Default")
        self._reset_btn.setFixedWidth(150)
        self._reset_btn.setStyleSheet(get_secondary_button_style())
        self._reset_btn.clicked.connect(self._on_reset)
        btn_bar.addWidget(self._reset_btn)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedWidth(100)
        self._apply_btn.setStyleSheet(get_primary_button_style())
        self._apply_btn.clicked.connect(self._on_apply)
        btn_bar.addWidget(self._apply_btn)

        outer.addLayout(btn_bar)

    def _create_controls(self, form: QFormLayout):
        info = QLabel("All settings below persist across restarts.")
        info.setStyleSheet(f"color: #888; font-style: italic; font-size: {scaled_area_px('info_text')}px;")
        form.addRow("", info)

        self.view_combo = QComboBox()
        self.view_combo.addItem("South Indian", "south_indian")
        self.view_combo.addItem("North Indian", "north_indian")
        self.view_combo.addItem("Wheel", "wheel")
        self.view_combo.setMaximumWidth(220)
        _locked_row(
            form, "chart.view_type", "Chart view:", self.view_combo,
            "South Indian (fixed grid), North Indian (diamond), or Wheel (circular).",
        )

        self.outer_planets_cb = QCheckBox()
        _locked_row(
            form, "chart.show_outer_planets", "Show outer planets:", self.outer_planets_cb,
            "Show Uranus, Neptune, and Pluto.",
        )

        from PySide6.QtWidgets import QButtonGroup, QRadioButton, QHBoxLayout, QWidget
        planet_label_widget = QWidget()
        planet_label_layout = QHBoxLayout(planet_label_widget)
        planet_label_layout.setContentsMargins(0, 0, 0, 0)
        planet_label_layout.setSpacing(12)
        self.planet_label_degrees_rb = QRadioButton("Degrees (15°22')")
        self.planet_label_names_rb = QRadioButton("Planet names")
        self.planet_label_group = QButtonGroup()
        self.planet_label_group.addButton(self.planet_label_degrees_rb, 0)
        self.planet_label_group.addButton(self.planet_label_names_rb, 1)
        planet_label_layout.addWidget(self.planet_label_degrees_rb)
        planet_label_layout.addWidget(self.planet_label_names_rb)
        planet_label_layout.addStretch()
        _locked_row(
            form, "chart.show_planet_names",
            "Under planets, show:", planet_label_widget,
            "What to display under each planet icon on the chart.",
        )

        self.retinue_rings_cb = QCheckBox()
        _locked_row(
            form, "chart.show_retinue_rings", "Retinue rings (Wheel):", self.retinue_rings_cb,
            "Add the Hora and Trimsamsa outer rings (Wheel).",
        )

        self.element_pies_cb = QCheckBox()
        _locked_row(
            form, "chart.show_element_pies", "Element pies (Wheel):", self.element_pies_cb,
            "Show the fire/earth/air/water balance as pie slices (Wheel).",
        )

        self.cusp_glow_combo = QComboBox()
        self.cusp_glow_combo.addItem("Off", 0)
        self.cusp_glow_combo.addItem("Angles only", 1)
        self.cusp_glow_combo.addItem("All", 2)
        self.cusp_glow_combo.setMaximumWidth(220)
        _locked_row(
            form, "chart.cusp_glow_mode", "Cusp glow (Wheel):", self.cusp_glow_combo,
            "Highlight house cusps. Angles only = 1/4/7/10; All = every cusp (Wheel).",
        )

        panel_header = QLabel("Default sub-tabs (Chart tab)")
        panel_header.setStyleSheet(f"font-weight: bold; margin-top: 8px;")
        form.addRow("", panel_header)

        panel_desc = QLabel(
            "Choose which sub-tab each Chart-tab panel opens on at launch. "
            "Lock a panel to always start on the chosen tab. Unlocked, it "
            "remembers the last tab you used."
        )
        panel_desc.setWordWrap(True)
        panel_desc.setStyleSheet(
            f"color:#888; font-size:{scaled_area_px('info_text')}px; font-style:italic; margin-bottom:4px;"
        )
        form.addRow("", panel_desc)

        self.karakas_radio = _locked_radio_group(
            form, "ui.panel.karakas_tab", "Karakas panel:",
            [("Karakas", 0), ("Hora", 1), ("Trimsamsa", 2), ("Houses", 3)],
        )

        self.strength_radio = _locked_radio_group(
            form, "ui.panel.strength_tab", "Strength panel:",
            [("Strength", 0), ("Elements", 1), ("Modes", 2), ("Dignities", 3)],
        )

        self.aspects_radio = _locked_radio_group(
            form, ["ui.panel.aspects_mode", "ui.panel.aspects_tab"], "Aspects panel:",
            [
                ("Aspects (Vedic)", 0), ("Avastha", 1), ("Shame", 2), ("Exchange", 3),
                ("Aspects (Tajika)", 4), ("Relations", 5), ("Yogas", 6),
            ],
        )

    def _read_from_settings(self):
        s = get_settings()

        idx = self.view_combo.findData(s.get("chart.view_type", "south_indian"))
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)

        self.outer_planets_cb.setChecked(s.get("chart.show_outer_planets", True))
        if s.get("chart.show_planet_names", False):
            self.planet_label_names_rb.setChecked(True)
        else:
            self.planet_label_degrees_rb.setChecked(True)
        self.retinue_rings_cb.setChecked(s.get("chart.show_retinue_rings", False))
        self.element_pies_cb.setChecked(s.get("chart.show_element_pies", True))

        glow = s.get("chart.cusp_glow_mode", 0)
        idx = self.cusp_glow_combo.findData(glow)
        if idx >= 0:
            self.cusp_glow_combo.setCurrentIndex(idx)

        self._select_radio_value(self.karakas_radio, s.get("ui.panel.karakas_tab", 0))
        self._select_radio_value(self.strength_radio, s.get("ui.panel.strength_tab", 0))
        aspects_idx = _aspects_to_radio(
            s.get("ui.panel.aspects_mode", "vedic"),
            s.get("ui.panel.aspects_tab", 0),
        )
        btn = self.aspects_radio.button(aspects_idx)
        if btn is not None:
            btn.setChecked(True)

    @staticmethod
    def _select_radio_value(group, value):
        for b in group.buttons():
            if b.property("opt_value") == value:
                b.setChecked(True)
                return

    @staticmethod
    def _radio_value(group, default=0):
        b = group.checkedButton()
        if b is None:
            return default
        return b.property("opt_value")

    def _on_apply(self):
        self._apply_to_settings()

    def _apply_to_settings(self):
        s = get_settings()
        s.set("chart.view_type", self.view_combo.currentData())
        s.set("chart.show_outer_planets", self.outer_planets_cb.isChecked())
        s.set("chart.show_planet_names",
              self.planet_label_names_rb.isChecked())
        s.set("chart.show_retinue_rings", self.retinue_rings_cb.isChecked())
        s.set("chart.show_element_pies", self.element_pies_cb.isChecked())
        s.set("chart.cusp_glow_mode", self.cusp_glow_combo.currentData())

        s.set("ui.panel.karakas_tab", self._radio_value(self.karakas_radio, 0))
        s.set("ui.panel.strength_tab", self._radio_value(self.strength_radio, 0))
        aspects_idx = self.aspects_radio.checkedId()
        if aspects_idx < 0:
            aspects_idx = 0
        a_mode, a_tab = ASPECTS_RADIO[aspects_idx]
        s.set("ui.panel.aspects_mode", a_mode)
        s.set("ui.panel.aspects_tab", a_tab)

        self.chart_display_changed.emit()

    def _on_reset(self):
        s = get_settings()
        s.reset_to_defaults("chart")
        s.set("ui.panel.karakas_tab", 0)
        s.set("ui.panel.strength_tab", 0)
        s.set("ui.panel.aspects_mode", "vedic")
        s.set("ui.panel.aspects_tab", 0)
        self._read_from_settings()

    def refresh_theme(self):
        self._reset_btn.setStyleSheet(get_secondary_button_style())
        self._apply_btn.setStyleSheet(get_primary_button_style())


# =============================================================================
# CORE SETTINGS TAB — Appearance + Default Folders + Zodiac + Display Scale + Font Sizes
# =============================================================================

class SettingsTab(QWidget):
    """
    Core settings tab with left sidebar navigation.
    Contains Appearance, Default Folders, Zodiac & Calculation, and Display Scale.
    """
    theme_changed = Signal(str)
    scale_changed = Signal(float)
    sign_language_changed = Signal(str)
    chart_display_changed = Signal()
    zodiac_changed = Signal(str)
    names_changed = Signal(bool)
    ayanamsa_changed = Signal(int)
    dasha_changed = Signal()
    house_system_changed = Signal(str)
    house_display_mode_changed = Signal(str)
    font_sizes_changed = Signal()   # SPEC-FONT-001: for live panel refresh

    def __init__(self, current_theme: str = None, parent=None, **kwargs):
        super().__init__(parent)
        self.current_theme = current_theme or "dark_blue.xml"
        from state.user_data import get_settings_path
        self.settings_path = get_settings_path()
        self._setup_ui()

    def _setup_ui(self):
        theme = get_theme_colors()
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left navigation
        self.nav_frame = QFrame()
        self.nav_frame.setFixedWidth(200)
        self.nav_frame.setStyleSheet(f"background-color: {theme['secondary']};")
        nav_layout = QVBoxLayout(self.nav_frame)
        nav_layout.setContentsMargins(8, 12, 8, 12)

        self.nav_list = QListWidget()
        self.nav_list.addItem("Appearance")
        self.nav_list.addItem("Display Scale")
        self.nav_list.addItem("Font Sizes")
        self.nav_list.addItem("Chart Display")
        self.nav_list.addItem("Zodiac & Calculation")
        self.nav_list.addItem("Default Folders")
        self.nav_list.setCurrentRow(0)

        from ui.qt_theme import get_list_style
        self.nav_list.setStyleSheet(get_list_style())
        nav_layout.addWidget(self.nav_list)
        nav_layout.addStretch()
        main_layout.addWidget(self.nav_frame)

        # Right content area
        self.content_stack = QStackedWidget()

        # Index 0: Appearance
        self.appearance_tab = AppearanceTab(current_theme=self.current_theme)
        self.appearance_tab.theme_changed.connect(self._on_theme_changed)
        self.appearance_tab.sign_language_changed.connect(self.sign_language_changed.emit)
        self.content_stack.addWidget(self.appearance_tab)

        # Index 1: Display Scale
        self.display_scale_tab = DisplayScaleTab()
        self.display_scale_tab.scale_changed.connect(self._on_scale_changed)
        self.content_stack.addWidget(self.display_scale_tab)

        # Index 2: Font Sizes
        self.font_sizes_tab = FontSizesSection()
        self.font_sizes_tab.font_sizes_changed.connect(self.font_sizes_changed.emit)
        self.content_stack.addWidget(self.font_sizes_tab)

        # Index 3: Chart Display
        self.chart_display_tab = ChartDisplaySection()
        self.chart_display_tab.chart_display_changed.connect(self.chart_display_changed.emit)
        self.content_stack.addWidget(self.chart_display_tab)

        # Index 4: Zodiac & Calculation
        self.zodiac_tab = ZodiacCalculationTab()
        self.zodiac_tab.zodiac_changed.connect(self.zodiac_changed.emit)
        self.zodiac_tab.names_changed.connect(self.names_changed.emit)
        self.zodiac_tab.ayanamsa_changed.connect(self.ayanamsa_changed.emit)
        self.zodiac_tab.dasha_changed.connect(self.dasha_changed.emit)
        self.zodiac_tab.house_system_changed.connect(self.house_system_changed.emit)
        self.zodiac_tab.house_display_mode_changed.connect(self.house_display_mode_changed.emit)
        self.content_stack.addWidget(self.zodiac_tab)

        # Index 5: Default Folders
        self.folders_tab = DefaultFoldersTab(settings_path=self.settings_path)
        self.content_stack.addWidget(self.folders_tab)

        main_layout.addWidget(self.content_stack)
        self.nav_list.currentRowChanged.connect(self.content_stack.setCurrentIndex)

    def _on_theme_changed(self, theme_file: str):
        self.current_theme = theme_file
        self.theme_changed.emit(theme_file)

    def _on_scale_changed(self, factor: float):
        self.scale_changed.emit(factor)

    def refresh_theme(self):
        """Refresh all sub-tabs when theme changes."""
        from ui.qt_theme import get_list_style
        theme = get_theme_colors()
        # Refresh nav frame and list
        self.nav_frame.setStyleSheet(f"background-color: {theme['secondary']};")
        self.nav_list.setStyleSheet(get_list_style())
        # Refresh sub-tabs
        if hasattr(self, 'appearance_tab'):
            self.appearance_tab.refresh_theme()
        if hasattr(self, 'folders_tab'):
            self.folders_tab.refresh_theme()
        if hasattr(self, 'zodiac_tab'):
            self.zodiac_tab.refresh_theme()
        if hasattr(self, 'display_scale_tab'):
            self.display_scale_tab.refresh_theme()
        if hasattr(self, 'chart_display_tab'):
            self.chart_display_tab.refresh_theme()
        if hasattr(self, 'font_sizes_tab'):
            self.font_sizes_tab.refresh_theme()
