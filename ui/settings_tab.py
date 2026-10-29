#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
from core.settings_registry import default as _registry_default, get as _registry_setting, valid as _registry_valid
from ui import settings_rows as _rows
from ui import settings_page_sync as _page_sync  # AI setting redesign item 4
from ui import settings_hint as _hint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QFrame, QGroupBox, QSizePolicy,
    QPushButton, QLineEdit, QFileDialog, QMessageBox,
    QListWidget, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QCheckBox, QFormLayout, QToolButton, QSpinBox, QDoubleSpinBox, QSlider,
    QRadioButton, QButtonGroup, QLayout, QDialog,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont, QColor, QValidator

from ui.theme_default import default_theme_file
from ui.qt_theme import (
    get_theme_colors, get_primary_button_style, get_secondary_button_style,
    scaled_area_px, scaled_area_size, scaled_area_font,
    get_area_font_size, set_area_font_size, reset_area_font_sizes, AREA_DEFAULTS,
    desat_hex,
)
from ui.accent_ink import on_accent_ink  # SPEC-THM-001 §13
from managers.settings_manager import get_settings
from managers.live_frame_manager import batched_publication, emit_adoption
from apps.widgets.sign_shadow import clamp_sign_shadow_size

INFO_PANEL_WIDTH = 380


# Theme catalog lives in ui/themes.py (core-level, SPEC-LITE-FOUND-001 s4.7)
from ui.themes import AVAILABLE_THEMES
from ui.theme_palette import ThemePaletteDialog, theme_preview_colors
from ui.area_preview_thumb import AreaPreviewThumb


import re as _re_c038


# G9a: tooltip shown on the South-Indian theme/finish rows while they are disabled
# on a non-South-Indian view. The wording is the orchestrator's and not yet
# written, so it stays a placeholder and _si_scope_tooltip_pending() gates it: a
# placeholder must never reach a screen (the "[COPY PENDING]" incident, 2026-08-30).
# The moment real copy replaces the marker the tooltip lights up on its own.
_SI_SCOPE_TOOLTIP = "[COPY PENDING]"


def _si_scope_tooltip_pending() -> bool:
    return "[COPY PENDING]" in _SI_SCOPE_TOOLTIP


def _tag_font(widget, area):
    """Record the font AREA a migrated widget's QSS was composed from, so a live
    font-size change can be replayed onto it (td-c038 settings live-replay).

    These Settings sub-tabs are PERSISTENT (not rebuilt on a font-setting change);
    their construction QSS bakes `font-size:{scaled_area_px(area)}px` as a STATIC
    string, and their refresh_theme re-did colours only. Tagging + _replay_fonts()
    lets refresh_theme re-compose the font-size in place. Returns the widget so it
    can wrap a construction expression inline."""
    widget.setProperty("_c038_font_area", area)
    return widget


def _replay_fonts(root):
    """Re-compose the font-size of every _tag_font-tagged descendant from the live
    setting, preserving whatever else is in the widget's current stylesheet (the
    colour a theme re-apply just set, or the static construction colour). A pure
    font-size rewrite — strictly non-regressive for colour."""
    from PySide6.QtWidgets import QWidget
    for w in root.findChildren(QWidget):
        area = w.property("_c038_font_area")
        if not area:
            continue
        px = scaled_area_px(area)
        css = w.styleSheet()
        if _re_c038.search(r"font-size:\s*\d+px", css):
            css = _re_c038.sub(r"font-size:\s*\d+px", f"font-size: {px}px", css)
        elif "{" in css:
            # type-selector stylesheet (QGroupBox{...} etc.): insert into 1st block
            css = _re_c038.sub(r"\{", "{ font-size: %dpx;" % px, css, count=1)
        else:
            css = (css + f" font-size: {px}px;").strip()
        w.setStyleSheet(css)


def _form_label(text: str) -> QLabel:
    """A QFormLayout row label that honours the font settings.

    QFormLayout auto-creates a plain QLabel for a string label; being QSS-styled
    by qt-material it freezes at 13px (the O-6 trap). Building it explicitly with
    font-size in its own QSS lets it track the 'buttons' area like the other
    control-row labels on these pages.
    """
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
    return _tag_font(lbl, 'buttons')


def _group_header(form, text: str) -> QLabel:
    """A bold group header row inside a settings QFormLayout, same style as the
    existing "Default sub-tabs (Chart tab)" header (G9b 3C grouping). Tracks the
    'panel_titles' font area rather than freezing at the qt-material 13px."""
    header = QLabel(text)
    header.setStyleSheet(
        f"font-weight: bold; margin-top: 8px; "
        f"font-size: {scaled_area_px('panel_titles')}px;")
    _tag_font(header, 'panel_titles')
    form.addRow("", header)
    return header


class ThemeCard(QFrame):
    """
    Clickable card showing theme preview with color swatches.
    Emits clicked signal with theme filename when selected.
    """
    clicked = Signal(str)
    edit_clicked = Signal(str)

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
        _tag_font(self.name_label, 'buttons')  # td-c038 live-replay
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # O-6: font-size lives in QSS (applied in _update_style); setFont is inert.
        layout.addWidget(self.name_label)

        swatch_layout = QHBoxLayout()
        swatch_layout.setSpacing(6)
        swatch_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # td-l8b2: swatch frames stored so _update_style can RE-DESATURATE them
        # on a theme/saturation refresh. desat_hex() reads the live global
        # _UI_SATURATION (SPEC-SAT-001), so a style baked once at construction
        # goes stale on a live switch (the tab_08 theme_audit drift).
        self._swatch_frames = []
        for color in self.colors:
            swatch = QFrame()
            swatch.setFixedSize(28, 28)
            swatch_layout.addWidget(swatch)
            self._swatch_frames.append(swatch)

        layout.addLayout(swatch_layout)

        footer = QHBoxLayout()
        footer.setSpacing(4)
        # Coloured in _update_style: a colour set here stayed the old theme's
        # after a live switch (white on white in a light theme).
        self.mode_label = QLabel("Dark" if self.is_dark else "Light")
        _tag_font(self.mode_label, 'status')  # td-c038 live-replay
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(self.mode_label, stretch=1)
        self.edit_button = QToolButton()
        self.edit_button.setText("Edit")
        self.edit_button.setToolTip(f"Edit {self.theme_name} colors")
        self.edit_button.clicked.connect(lambda: self.edit_clicked.emit(self.theme_file))
        footer.addWidget(self.edit_button)
        layout.addLayout(footer)
        self.setFixedHeight(132)

    def _apply_swatch_styles(self):
        # td-l8b2: re-run desat_hex on each preview swatch from its SOURCE colour.
        # Reached on every _update_style() (theme refresh + set_selected), so a
        # live theme/saturation change re-desaturates the previews instead of
        # leaving them frozen at construction-time saturation.
        colors = theme_preview_colors(self.theme_file, self.colors)
        for swatch, color in zip(getattr(self, "_swatch_frames", []), colors):
            swatch.setStyleSheet(f"""
                background-color: {desat_hex(color)};
                border-radius: 4px;
                border: 1px solid rgba(255,255,255,0.2);
            """)

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
        self.name_label.setStyleSheet(
            f"color: {theme['secondary_text']}; background: transparent; "
            f"font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
        self.mode_label.setStyleSheet(
            f"font-size: {scaled_area_px('status')}px; color: {theme['secondary_text']};")
        self._apply_swatch_styles()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        self.clicked.emit(self.theme_file)
        super().mousePressEvent(event)


def build_action_bar_v2_row(form, settings):
    """SPEC-BAR-001 D-15: the 'Use classic action bar' opt-in row + its
    description, appended to ``form``. Returns the QCheckBox — CHECKED means the
    classic legacy bar (``ui.action_bar_v2`` False); unchecked means the new
    default bar. Persist with ``save_action_bar_v2_row(cb, settings)``.

    ONE definition, imported by both Core (AppearanceTab) and Pro
    (_GeneralSection) so the option is never duplicated. Restart-gated: the bar
    is constructed once at startup, so there is no live apply.
    """
    cb = QCheckBox()
    cb.setChecked(not settings.get_action_bar_v2())        # checked == classic
    form.addRow(_form_label("Use classic action bar:"), cb)
    desc = QLabel(
        "The new bar is the default. The classic bar is kept for compatibility "
        "and for those who prefer it, but it has fewer options (for example, "
        "hiding Human Design is not available there) and does not adapt as well "
        "at some screen resolutions. Takes effect after you restart the app."
    )
    desc.setWordWrap(True)
    # O-6: font-size in QSS (shared by Core AppearanceTab + Pro _GeneralSection).
    _hint.style(desc, 'info_text')
    _tag_font(desc, 'info_text')
    form.addRow("", desc)
    return cb


def save_action_bar_v2_row(cb, settings) -> bool:
    """Persist the 'Use classic action bar' opt-in — CHECKED means classic, so
    ``ui.action_bar_v2`` is the inverse. ONE definition of the inversion,
    shared by Core and Pro. Returns the accessor's success bool."""
    return settings.set_action_bar_v2(not cb.isChecked())


class AppearanceTab(QWidget):
    """Theme selection with visual cards and sign language toggle."""
    theme_changed = Signal(str)
    sign_language_changed = Signal(str)

    # G9c (td-scc4x): the Nakshatra Compatibility sub-panel has its OWN Apply
    # (_on_compat_apply) and now its OWN Reset (_on_compat_reset) — an owned-key
    # allowlist of exactly the keys that Apply writes, one set() per key. Since
    # SPEC-SET-003 W3d: the registry's nakshatra_compat.* keys, defaults from it.
    OWNED_COMPAT_KEYS = _rows.owned_keys("nakshatra_compat", "pro")   # shown in Pro only (D-24)

    _COMPAT_COMBOS = (  # (attribute, key), in row order
        ("compat_stree_combo", "nakshatra_compat.stree_deergha_scale"),
        ("compat_mahendra_combo", "nakshatra_compat.mahendra_include_19th"),
        ("compat_total_combo", "nakshatra_compat.total_threshold"),
    )

    def __init__(self, current_theme: str = None, parent=None):
        super().__init__(parent)
        self.current_theme = current_theme or default_theme_file()
        self.theme_cards = {}
        self._setup_ui()
        # AI setting redesign item 4: rows follow a change made outside the page.
        _page_sync.attach(self, self._read_from_settings,
                          _rows.owned_keys("appearance", "core") | {"appearance.theme"}
                          | self.OWNED_COMPAT_KEYS)

    def _setup_ui(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"AppearanceTab {{ background-color: {theme['secondary_dark']}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        theme_section = self._create_theme_section()
        layout.addWidget(theme_section)

        lang_section = self._create_language_section()
        layout.addWidget(lang_section)

        layout.addStretch()

    def _create_theme_section(self) -> QGroupBox:
        group = QGroupBox("Application Theme")
        # O-6: QGroupBox title font-size in QSS (setFont is inert).
        group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        _tag_font(group, 'panel_titles')

        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(15)

        desc = QLabel("Select a theme, then use Apply below to change the application appearance.")
        desc.setWordWrap(True)
        # O-6: font-size in QSS.
        desc.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        _tag_font(desc, 'info_text')
        group_layout.addWidget(desc)

        # Dark themes
        dark_label = QLabel("Dark Themes")
        # O-6: font-size + weight in QSS.
        dark_label.setStyleSheet(
            f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;")
        _tag_font(dark_label, 'panel_titles')
        group_layout.addWidget(dark_label)

        dark_grid = QGridLayout()
        dark_grid.setSpacing(12)
        row, col, max_cols = 0, 0, 5

        for theme_file, theme_name, is_dark, colors in AVAILABLE_THEMES:
            if is_dark:
                card = ThemeCard(theme_file, theme_name, is_dark, colors)
                card.clicked.connect(self._on_theme_selected)
                card.edit_clicked.connect(self._on_theme_edit)
                if theme_file == self.current_theme:
                    card.set_selected(True)
                self.theme_cards[theme_file] = card
                dark_grid.addWidget(card, row, col)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

        group_layout.addLayout(dark_grid)

        # SPEC-THM-001: the deep-dark option modifies whichever DARK theme is
        # selected, so it sits under the dark cards (same place as in Pro). It
        # is a pending page choice: Other Settings > Apply writes it.
        self.deep_dark_cb = QCheckBox(_rows.label("appearance.deep_dark"))
        self.deep_dark_cb.setToolTip(_rows.help_text("appearance.deep_dark"))
        self.deep_dark_cb.setChecked(
            bool(_rows.saved(get_settings(), "appearance.deep_dark")))
        group_layout.addWidget(self.deep_dark_cb)
        self._sync_deep_dark_enabled(self.current_theme)

        # Light themes
        light_label = QLabel("Light Themes")
        # O-6: font-size + weight in QSS.
        light_label.setStyleSheet(
            f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;")
        _tag_font(light_label, 'panel_titles')
        group_layout.addWidget(light_label)

        light_grid = QGridLayout()
        light_grid.setSpacing(12)
        row, col = 0, 0

        for theme_file, theme_name, is_dark, colors in AVAILABLE_THEMES:
            if not is_dark:
                card = ThemeCard(theme_file, theme_name, is_dark, colors)
                card.clicked.connect(self._on_theme_selected)
                card.edit_clicked.connect(self._on_theme_edit)
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
        # O-6: QGroupBox title font-size in QSS.
        group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        _tag_font(group, 'panel_titles')

        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(12)

        s = get_settings()

        # Language
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # SPEC-SET-003 W3d: items, labels and row titles come from the registry.
        self.lang_combo = _rows.registry_combo("zodiac.sign_language")

        lang = _rows.saved(s, "zodiac.sign_language")
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(_form_label(_rows.label("zodiac.sign_language")), self.lang_combo)

        lang_warning = QLabel(
            "Changes zodiac sign names and planet names on chart views. "
            "Full UI translation will be supported in a later update."
        )
        lang_warning.setWordWrap(True)
        # O-6: font-size in QSS.
        _hint.style(lang_warning, 'info_text')
        _tag_font(lang_warning, 'info_text')
        form.addRow("", lang_warning)

        # Remember window geometry
        self.remember_geo_cb = QCheckBox()
        self.remember_geo_cb.setChecked(_rows.saved(s, "windows.remember_geometry"))
        form.addRow(_form_label(_rows.label("windows.remember_geometry")), self.remember_geo_cb)

        # Auto-restore session
        self.auto_restore_cb = QCheckBox()
        self.auto_restore_cb.setChecked(_rows.saved(s, "defaults.auto_restore_session"))
        form.addRow(_form_label(_rows.label("defaults.auto_restore_session")), self.auto_restore_cb)

        # Restore last tab
        self.restore_tab_cb = QCheckBox()
        self.restore_tab_cb.setChecked(_rows.saved(s, "ui.restore_last_tab"))
        form.addRow(_form_label(_rows.label("ui.restore_last_tab")), self.restore_tab_cb)

        # C8: the "Hide Human Design button" row is retired. The HD button is
        # always shown (the D-5 HD/Sidereal swap it controlled is gone), and
        # its Apply write was the path that hid the button mid-session.

        # SPEC-BAR-001 M4 (Dm4-48/49): the mockup's prefers-reduced-motion
        # reading. Stops ONLY the bar's breathing "live" dot (pinned at 85%);
        # the short hover/state fades keep running — the mockup's media query
        # overrides exactly one rule, and so do we.
        self.reduce_motion_cb = QCheckBox()
        self.reduce_motion_cb.setChecked(s.get_reduce_motion())
        form.addRow(_form_label(_rows.label("ui.reduce_motion")), self.reduce_motion_cb)
        reduce_motion_desc = QLabel(_rows.help_text("ui.reduce_motion"))
        reduce_motion_desc.setWordWrap(True)
        # O-6: font-size in QSS.
        _hint.style(reduce_motion_desc, 'info_text')
        _tag_font(reduce_motion_desc, 'info_text')
        form.addRow("", reduce_motion_desc)

        # SPEC-BAR-001 D-15: classic-bar opt-in. ONE definition
        # (build_action_bar_v2_row) shared with Pro so the option is never
        # duplicated — Pro imports the same row builder. Checked == classic.
        self.classic_bar_cb = build_action_bar_v2_row(form, s)

        group_layout.addLayout(form)

        # Apply button for non-theme settings
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._other_apply_btn = QPushButton("Apply")
        self._other_apply_btn.setFixedWidth(100)
        self._other_apply_btn.setStyleSheet(get_primary_button_style())
        _tag_font(self._other_apply_btn, 'action_buttons')
        self._other_apply_btn.clicked.connect(self._on_other_apply)
        btn_row.addWidget(self._other_apply_btn)
        group_layout.addLayout(btn_row)

        return group

    def _create_nakshatra_compat_section(self) -> QGroupBox:
        """Cross-tradition rule toggles for the Nakshatra Compatibility (Kuta) dialog.

        Only GENUINE classical-school variants live here (each labelled with its two
        sources). Defaults = Ernst/Kala values (golden-tested). Ernst-vs-Ernst readings
        are resolved empirically and are NOT toggles.
        """
        group = QGroupBox("Nakshatra Compatibility rules")
        # O-6: QGroupBox title font-size in QSS.
        group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(12)

        desc = QLabel(
            "Cross-tradition variants for the Nakshatra Compatibility (kuta) matrix. "
            "Defaults reproduce Kala / Ernst Wilhelm."
        )
        desc.setWordWrap(True)
        # O-6: font-size in QSS.
        desc.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        group_layout.addWidget(desc)

        s = get_settings()
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for attr, key in self._COMPAT_COMBOS:
            combo = _rows.registry_combo(key, max_width=260)
            setattr(self, attr, combo)
            self._select_combo_data(combo, _rows.saved(s, key))
            form.addRow(_form_label(_rows.label(key)), combo)

        group_layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._compat_reset_btn = QPushButton("Reset to Default")
        self._compat_reset_btn.setFixedWidth(150)
        self._compat_reset_btn.setStyleSheet(get_secondary_button_style())
        self._compat_reset_btn.clicked.connect(self._on_compat_reset)
        btn_row.addWidget(self._compat_reset_btn)
        self._compat_apply_btn = QPushButton("Apply")
        self._compat_apply_btn.setFixedWidth(100)
        self._compat_apply_btn.setStyleSheet(get_primary_button_style())
        self._compat_apply_btn.clicked.connect(self._on_compat_apply)
        btn_row.addWidget(self._compat_apply_btn)
        group_layout.addLayout(btn_row)

        return group

    @staticmethod
    def _select_combo_data(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _read_from_settings(self):
        """Re-read the rows from the store (a change made outside the page)."""
        s = get_settings()
        from ui.themes import THEME_NAME_TO_FILE
        theme_file = THEME_NAME_TO_FILE.get(_rows.saved(s, "appearance.theme"))
        if theme_file:
            self.set_current_theme(theme_file)
        for cb, key in ((self.remember_geo_cb, "windows.remember_geometry"),
                        (self.auto_restore_cb, "defaults.auto_restore_session"),
                        (self.restore_tab_cb, "ui.restore_last_tab")):
            cb.setChecked(bool(_rows.saved(s, key)))
        self.reduce_motion_cb.setChecked(s.get_reduce_motion())
        self.classic_bar_cb.setChecked(not s.get_action_bar_v2())   # checked == classic
        self.deep_dark_cb.blockSignals(True)
        self.deep_dark_cb.setChecked(bool(_rows.saved(s, "appearance.deep_dark")))
        self.deep_dark_cb.blockSignals(False)
        self._sync_deep_dark_enabled(self.current_theme)
        self.lang_combo.blockSignals(True)          # the combo saves as it changes
        self._select_combo_data(self.lang_combo, _rows.saved(s, "zodiac.sign_language"))
        self.lang_combo.blockSignals(False)
        for attr, key in self._COMPAT_COMBOS:
            combo = getattr(self, attr, None)       # built in Pro only (D-24)
            if combo is not None:
                self._select_combo_data(combo, _rows.saved(s, key))

    @_page_sync.page_apply
    def _on_compat_apply(self):
        s = get_settings()
        s.set("nakshatra_compat.stree_deergha_scale", self.compat_stree_combo.currentData())
        s.set("nakshatra_compat.mahendra_include_19th", self.compat_mahendra_combo.currentData())
        s.set("nakshatra_compat.total_threshold", self.compat_total_combo.currentData())

    @_page_sync.page_write
    def _on_compat_reset(self):
        # G9c: reset ONLY the keys this sub-panel writes (owned-key allowlist), one
        # set() per key from DEFAULT_SETTINGS. Never reset_to_defaults("nakshatra_compat")
        # — same "reset what you host" rule as the other sections; keeps this
        # one-to-one with _on_compat_apply (pinned by test).
        s = get_settings()
        for key in self.OWNED_COMPAT_KEYS:
            s.set(key, _registry_default(key))
        # re-select the combos to the restored values
        for attr, key in self._COMPAT_COMBOS:
            self._select_combo_data(getattr(self, attr), _rows.saved(s, key))

    @_page_sync.page_write
    def _on_language_changed(self):
        new_lang = self.lang_combo.currentData()
        get_settings().set("zodiac.sign_language", new_lang)
        self.sign_language_changed.emit(new_lang)

    @_page_sync.page_apply
    def _on_other_apply(self):
        s = get_settings()
        from ui.theme_palette import commit_theme_overrides
        commit_theme_overrides()
        s.set("windows.remember_geometry", self.remember_geo_cb.isChecked())
        s.set("defaults.auto_restore_session", self.auto_restore_cb.isChecked())
        s.set("ui.restore_last_tab", self.restore_tab_cb.isChecked())
        # Dm4-49: reduced motion applies LIVE. The env var wins (Dm4-44:
        # captures pin POSE through it), so never override an explicit env.
        reduced = self.reduce_motion_cb.isChecked()
        if not s.set_reduce_motion(reduced):
            _win = self.window()
            if hasattr(_win, 'statusBar'):
                _win.statusBar().showMessage(
                    "Settings file could not be saved — the Reduce motion "
                    "preference will not survive a restart.", 8000)
        # SPEC-BAR-001 D-15: restart-gated flag — persist only, no live apply
        # (the bar is constructed once at startup). Checked == classic bar.
        if not save_action_bar_v2_row(self.classic_bar_cb, s):
            _win = self.window()
            if hasattr(_win, 'statusBar'):
                _win.statusBar().showMessage(
                    "Settings file could not be saved — the action bar "
                    "preference will not survive a restart.", 8000)
        import os as _os
        if "V360_BAR_MOTION" not in _os.environ:
            try:
                from apps.widgets.action_bar import motion as _motion
                _motion.set_mode(_motion.Mode.REDUCED if reduced
                                 else _motion.Mode.LIVE)
                _bar = getattr(self.window(), 'chart_title_widget', None)
                if _bar is not None and hasattr(_bar, 'snap_motion'):
                    _bar.snap_motion()
            except Exception:
                pass
        deep_dark = bool(self.deep_dark_cb.isChecked())
        s.set("appearance.deep_dark", deep_dark)
        try:
            from ui.qt_theme import set_deep_dark
            set_deep_dark(deep_dark)
        except Exception:
            pass
        self.theme_changed.emit(self.current_theme)

    def _on_theme_selected(self, theme_file: str):
        for tf, card in self.theme_cards.items():
            card.set_selected(tf == theme_file)
        self.current_theme = theme_file
        self._sync_deep_dark_enabled(theme_file)

    def _sync_deep_dark_enabled(self, theme_file):
        """Grey the option out on a light theme. is_dark comes from
        AVAILABLE_THEMES, never the file name (dark_lightgreen.xml is dark)."""
        checkbox = getattr(self, "deep_dark_cb", None)
        if checkbox is None:
            return
        is_dark = None
        for entry_file, _name, entry_is_dark, _colors in AVAILABLE_THEMES:
            if entry_file == theme_file:
                is_dark = bool(entry_is_dark)
                break
        if is_dark is None:
            from ui.qt_theme import _is_dark_theme_file
            is_dark = _is_dark_theme_file(theme_file)
        checkbox.setEnabled(is_dark)
        if not is_dark and checkbox.isChecked():
            checkbox.setChecked(False)

    def _on_theme_edit(self, theme_file: str):
        card = self.theme_cards[theme_file]
        dialog = ThemePaletteDialog(theme_file, card.theme_name,
                                    lambda _theme: card._update_style(), self)
        dialog.exec()
        for item in self.theme_cards.values():
            item._update_style()

    def get_current_theme(self) -> str:
        return self.current_theme

    def set_current_theme(self, theme_file: str):
        if theme_file in self.theme_cards:
            for tf, card in self.theme_cards.items():
                card.set_selected(tf == theme_file)
            self.current_theme = theme_file
            self._sync_deep_dark_enabled(theme_file)

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"AppearanceTab {{ background-color: {theme['secondary_dark']}; }}")
        for card in self.theme_cards.values():
            card._update_style()
        # The page's own buttons bake their colour at construction; without
        # this the Apply buttons stayed on the boot theme's accent (blue on
        # a green theme) until restart.
        for attr in ("_other_apply_btn", "_compat_apply_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setStyleSheet(get_primary_button_style())
        reset_btn = getattr(self, "_compat_reset_btn", None)
        if reset_btn is not None:
            reset_btn.setStyleSheet(get_secondary_button_style())
        # td-c038: re-compose migrated font-sizes from the live setting (this
        # persistent tab bakes static font-size QSS at construction).
        _replay_fonts(self)


COMPUTE_CPU_KEY = "ui.find_chart_compute_cpu_percent"


def find_chart_compute_group():
    """The "Find Chart" group of the folders page (Core and Pro): the CPU share
    a background compute keeps to (core/chart_search/compute_process.py;
    Lorris, 2026-10-18). The spin box writes the setting as it changes, like
    the language combo: it is not part of the page's Save (its write set is
    the C-2 record). Returns ``(group, spin)``; the caller styles the title."""
    group = QGroupBox("Find Chart")
    layout = QVBoxLayout(group)
    layout.setSpacing(12)
    desc = QLabel(_rows.help_text(COMPUTE_CPU_KEY))
    desc.setWordWrap(True)
    _hint.style(desc, 'info_text')
    _tag_font(desc, 'info_text')
    layout.addWidget(desc)
    row = QHBoxLayout()
    label = QLabel(_rows.label(COMPUTE_CPU_KEY))
    label.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
    _tag_font(label, 'info_text')
    row.addWidget(label)
    spin = QSpinBox()
    low, high = _registry_setting(COMPUTE_CPU_KEY).bounds
    spin.setRange(int(low), int(high))
    spin.setSuffix(" %")
    spin.setMaximumWidth(110)
    spin.setStyleSheet(f"QSpinBox {{ font-size: {scaled_area_px('buttons')}px; }}")
    _tag_font(spin, 'buttons')
    load_compute_cpu(spin)
    spin.valueChanged.connect(lambda value: get_settings().set(COMPUTE_CPU_KEY, value))
    row.addWidget(spin)
    row.addStretch()
    layout.addLayout(row)
    return group, spin


def load_compute_cpu(spin):
    """Show the saved CPU share without writing it back."""
    spin.blockSignals(True)
    spin.setValue(int(_rows.saved(get_settings(), COMPUTE_CPU_KEY)))
    spin.blockSignals(False)


class DefaultFoldersTab(QWidget):
    """Chart folder paths and Kala configuration."""
    folders_changed = Signal()

    def __init__(self, settings_path: Path, parent=None):
        super().__init__(parent)
        self.folder_entries = {}
        self._setup_ui()
        _page_sync.attach(self, self._read_from_settings,    # AI setting redesign
                          _rows.owned_keys("folders", "core"))

    def showEvent(self, event):
        # The persisted chart-write record can change while this page is
        # built but not visible (a chart created from another tab), so the
        # banner is re-read on every open rather than at construction only.
        super().showEvent(event)
        banner = getattr(self, "chart_write_banner", None)
        if banner is not None:
            banner.refresh()

    def _setup_ui(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"DefaultFoldersTab {{ background-color: {theme['secondary_dark']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        title = QLabel("Default Folders")
        # O-6: font-size + weight in QSS.
        title.setStyleSheet(
            f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;")
        _tag_font(title, 'panel_titles')
        layout.addWidget(title)

        # Session save health (SPEC-SES-001 §4.4). Sits above the folder rows
        # because it is about the folders. Hides itself when all is well, so
        # in normal use this adds no visible chrome. attach() is called by the
        # settings page once the SessionManager is reachable.
        from ui.session_health_banner import SessionHealthBanner, make_report_button
        self.session_health_banner = SessionHealthBanner()
        layout.addWidget(self.session_health_banner)

        # Chart-write health (SPEC-PERSIST-001 INV-6, td-rx09). Same place,
        # different question: the banner above is about the SESSION file, this
        # one is about the chart database. It reads a PERSISTED record, so it
        # is still here after the restart that clears the status-bar message,
        # and it hides itself as soon as a chart saves normally.
        from ui.chart_write_banner import ChartWriteBanner
        self.chart_write_banner = ChartWriteBanner()
        layout.addWidget(self.chart_write_banner)

        # Always-available reporting. The banner above hides itself when all
        # is well, so without this the feature would be reachable only while
        # something is already broken.
        report_row = QHBoxLayout()
        report_row.addStretch()
        self.report_button = make_report_button(
            health_provider=lambda: (
                self.session_health_banner._health
                if self.session_health_banner else None
            )
        )
        # SPEC-EXPORT-001 (td-2by9): the manual sweep lives beside the folder
        # rows because that is where the destination is chosen. It never runs
        # on its own — rewriting a database nobody asked to have rewritten is
        # how a tool holding thirteen years of work loses trust.
        from ui.bulk_export_dialog import make_bulk_export_button
        self.bulk_export_button = make_bulk_export_button()
        report_row.addWidget(self.bulk_export_button)
        report_row.addWidget(self.report_button)
        layout.addLayout(report_row)

        desc = QLabel(
            "Define default folders for chart loading and searching. "
            "When you load charts, the app will search these folders by default."
        )
        desc.setWordWrap(True)
        # O-6: font-size in QSS.
        desc.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        _tag_font(desc, 'info_text')
        layout.addWidget(desc)

        # Chart folders group
        group = QGroupBox("Chart Folders")
        # O-6: QGroupBox title font-size in QSS.
        group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        _tag_font(group, 'panel_titles')
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

        # Find Chart: the CPU share of a background compute (writes at once).
        fc_group, self.compute_cpu_spin = find_chart_compute_group()
        fc_group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        _tag_font(fc_group, 'panel_titles')
        layout.addWidget(fc_group)

        # Kala Software group
        import sys
        kala_group = QGroupBox("Kala Software")
        # O-6: QGroupBox title font-size in QSS.
        kala_group.setStyleSheet(
            f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; }}")
        _tag_font(kala_group, 'panel_titles')
        kala_layout = QVBoxLayout(kala_group)
        kala_layout.setSpacing(15)

        kala_hint = "Path to Kala.exe on your system." if sys.platform == 'win32' else \
                    "Path to Kala.exe — will be launched through Wine on Linux/macOS."
        kala_desc = QLabel(kala_hint)
        # O-6: font-size in QSS.
        _hint.style(kala_desc, 'info_text')
        _tag_font(kala_desc, 'info_text')
        kala_layout.addWidget(kala_desc)

        kala_exe_path = _rows.saved(s, "paths.kala_path")
        kala_row = self._create_file_row('kala_exe', 'Kala Executable', kala_exe_path)
        kala_layout.addWidget(kala_row)
        layout.addWidget(kala_group)

        # Save button
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        save_btn = QPushButton("Save Settings")
        self._save_settings_btn = save_btn  # identity for refresh_theme (INV-3)
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
            f"border-radius: 3px; padding: 4px; "
            # O-6: the path fields are QSS-styled QLineEdits with no font-size,
            # so they froze at the qt-material default; size them from info_text.
            f"font-size: {scaled_area_px('info_text')}px;"
        )

    def _create_folder_row(self, folder_key: str, folder_label: str, folder_path: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        label = QLabel(f"{folder_label}:")
        label.setFixedWidth(120)
        # O-6: font-size in QSS.
        label.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(label, 'buttons')
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
        # O-6: font-size in QSS.
        label.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(label, 'buttons')
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
            self.folder_entries['kala_exe'].setText(_rows.saved(s, "paths.kala_path"))
        if hasattr(self, "compute_cpu_spin"):
            load_compute_cpu(self.compute_cpu_spin)

    @_page_sync.page_apply
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
            if btn is getattr(self, "_save_settings_btn", None):
                btn.setStyleSheet(get_primary_button_style())
            else:
                btn.setStyleSheet(get_secondary_button_style())
        # td-c038: cascade the warning banners' own refresh (they are persistent
        # children with their own font-replay, but nothing invoked it — so a live
        # font change never reached them until now).
        for _b in (getattr(self, "session_health_banner", None),
                   getattr(self, "chart_write_banner", None)):
            if _b is not None and hasattr(_b, "refresh_theme"):
                _b.refresh_theme()
        # td-c038: re-compose migrated font-sizes from the live setting.
        _replay_fonts(self)


# =============================================================================
# DISPLAY SCALE TAB — Font scaling for responsive UI
# =============================================================================

class DisplayScaleTab(QWidget):
    """Display scale controls: slider 60-160%, live preview, reset, auto-detect.
    Also hosts the global Color Saturation slider (SPEC-SAT-001)."""
    scale_changed = Signal(float)
    saturation_changed = Signal(int)  # SPEC-SAT-001: 0-100, emitted on Apply

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_scale = 1.0  # cached; updated by _load_saved_scale and _on_apply
        self._saved_saturation = 100  # SPEC-SAT-001 cache
        self._setup_ui()
        self._load_saved_scale()
        self._load_saved_saturation()
        # _load_saved_scale already calls _apply_preview_scale — no redundant call needed
        _page_sync.attach(self, lambda: (self._load_saved_scale(),    # AI setting redesign
                                         self._load_saved_saturation()),
                          _rows.owned_keys("display_scale"))

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
        # O-6: font-size + weight in QSS.
        title.setStyleSheet(
            f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;")
        _tag_font(title, 'panel_titles')
        layout.addWidget(title)

        desc = QLabel(
            "Adjust the font size and UI element scaling. "
            "Changes apply to panels, buttons, and text across the application. "
            "The chart wheel has its own independent zoom."
        )
        desc.setWordWrap(True)
        # O-6: font-size in QSS.
        desc.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        _tag_font(desc, 'info_text')
        layout.addWidget(desc)

        # Scale group
        self.scale_group = QGroupBox("Display Scale")
        # O-6: QGroupBox title font-size appended to the shared group style
        # (which sets weight/colour but no size); setFont is inert.
        self.scale_group.setStyleSheet(
            get_group_box_style()
            + f" QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; }}")
        group_layout = QVBoxLayout(self.scale_group)
        group_layout.setSpacing(15)

        # Slider row
        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)

        slider_label = QLabel(_rows.label("display.font_scale"))
        slider_label.setFixedWidth(50)
        # O-6: QSS-less QLabel froze at the qt-material default; size from buttons.
        slider_label.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(slider_label, 'buttons')
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
        # O-6: font-size + weight in QSS.
        self.scale_value_label.setStyleSheet(
            f"font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
        _tag_font(self.scale_value_label, 'buttons')
        slider_row.addWidget(self.scale_value_label)

        group_layout.addLayout(slider_row)

        self.scale_tip_label = QLabel(
            "Tips: 60% for 720p, 80% for 1080p, 100-120% for 2K, "
            "140-160% for 4K. Restart Varuna360 after applying to ensure every "
            "panel uses the new scale."
        )
        self.scale_tip_label.setWordWrap(True)
        # O-6: font-size in QSS.
        self.scale_tip_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
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

        # ── Color Saturation group (SPEC-SAT-001) ───────────────────────────
        from PySide6.QtWidgets import QSlider
        self.saturation_group = QGroupBox("Color Saturation")
        # O-6: QGroupBox title font-size appended to the shared group style.
        self.saturation_group.setStyleSheet(
            get_group_box_style()
            + f" QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; }}")
        sat_layout = QVBoxLayout(self.saturation_group)
        sat_layout.setSpacing(15)

        sat_desc = QLabel(
            "Mute the color intensity of the whole interface: theme colors, "
            "chart element colors, and planet icons. Lower values calm "
            "oversaturated screens. 100% is full color."
        )
        sat_desc.setWordWrap(True)
        # O-6: font-size in QSS.
        sat_desc.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        _tag_font(sat_desc, 'info_text')
        sat_layout.addWidget(sat_desc)

        sat_slider_row = QHBoxLayout()
        sat_slider_row.setSpacing(10)
        sat_slider_label = QLabel(_rows.label("display.color_saturation"))
        sat_slider_label.setFixedWidth(80)
        # O-6: QSS-less QLabel froze at the qt-material default; size from buttons.
        sat_slider_label.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(sat_slider_label, 'buttons')
        sat_slider_row.addWidget(sat_slider_label)

        self.saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self.saturation_slider.setMinimum(0)
        self.saturation_slider.setMaximum(100)
        self.saturation_slider.setValue(100)
        self.saturation_slider.setSingleStep(5)
        self.saturation_slider.setPageStep(10)
        self.saturation_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.saturation_slider.setTickInterval(10)
        sat_slider_row.addWidget(self.saturation_slider, stretch=1)

        self.saturation_value_label = QLabel("100%")
        self.saturation_value_label.setFixedWidth(50)
        self.saturation_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # O-6: font-size + weight in QSS.
        self.saturation_value_label.setStyleSheet(
            f"font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
        _tag_font(self.saturation_value_label, 'buttons')
        sat_slider_row.addWidget(self.saturation_value_label)
        sat_layout.addLayout(sat_slider_row)

        sat_btn_row = QHBoxLayout()
        sat_btn_row.setSpacing(10)
        self.saturation_reset_btn = QPushButton("Reset to 100%")
        self.saturation_reset_btn.setFixedWidth(140)
        self.saturation_reset_btn.setStyleSheet(get_secondary_button_style())
        self.saturation_reset_btn.clicked.connect(self._on_saturation_reset)
        sat_btn_row.addWidget(self.saturation_reset_btn)

        self.saturation_apply_btn = QPushButton("Apply")
        self.saturation_apply_btn.setFixedWidth(100)
        self.saturation_apply_btn.setStyleSheet(get_primary_button_style())
        self.saturation_apply_btn.clicked.connect(self._on_saturation_apply)
        sat_btn_row.addWidget(self.saturation_apply_btn)
        sat_btn_row.addStretch()
        sat_layout.addLayout(sat_btn_row)

        layout.addWidget(self.saturation_group)

        # Restart warning
        self.restart_warning = QLabel(
            "\u26a0  You may need to restart the app for all changes to take effect."
        )
        # O-6: font-size in QSS.
        self.restart_warning.setStyleSheet(
            f"color: #FFA726; padding: 4px 0; font-size: {scaled_area_px('status')}px;")
        _tag_font(self.restart_warning, 'status')
        self.restart_warning.setWordWrap(True)
        self.restart_warning.setVisible(False)
        layout.addWidget(self.restart_warning)

        # DPI info label
        self.dpi_info_label = QLabel("")
        # O-6: font-size in QSS.
        self.dpi_info_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px;")
        layout.addWidget(self.dpi_info_label)
        self._update_dpi_info()

        layout.addStretch()

        # Connect slider — only updates preview + label, does NOT emit scale_changed
        self.scale_slider.valueChanged.connect(self._on_slider_changed)
        # Saturation slider — label only on drag; commit on Apply (SPEC-SAT-001)
        self.saturation_slider.valueChanged.connect(self._on_saturation_slider_changed)

    def _build_strength_preview(self, parent_layout):
        """Build a compact panel preview that mirrors the real Strength panel."""
        theme = get_theme_colors()
        self.preview_title = QLabel("Preview")
        # O-6: font-size in QSS (setFont is inert). This preview header tracks the
        # preview's OWN scale factor (see _apply_preview_scale), not a global area;
        # 10px is the factor-1.0 initial, updated live as the slider moves.
        self.preview_title.setStyleSheet(
            f"color: {theme['secondary_text']}; border: none; "
            f"font-size: 10px; font-weight: bold;")
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

        # O-6: font-size in QSS (setFont is inert); tracks the preview factor.
        self.preview_title.setStyleSheet(
            f"color: {get_theme_colors()['secondary_text']}; border: none; "
            f"font-size: {title_size}px; font-weight: bold;")
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
            saved = _rows.saved(settings, "display.font_scale")
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

    @_page_sync.page_apply
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

    # ── Color Saturation (SPEC-SAT-001) ─────────────────────────────────────
    def _load_saved_saturation(self):
        """Load the persisted saturation into the slider (no signal emitted)."""
        try:
            from managers.settings_manager import get_settings
            val = int(_rows.saved(get_settings(), "display.color_saturation"))
        except Exception:
            val = 100
        val = max(0, min(100, val))
        self._saved_saturation = val
        self.saturation_slider.blockSignals(True)
        self.saturation_slider.setValue(val)
        self.saturation_slider.blockSignals(False)
        self.saturation_value_label.setText(f"{val}%")

    def _on_saturation_slider_changed(self, value):
        """Live label only; the actual apply is deferred to the Apply button
        (re-applying qt-material on every drag tick would thrash the UI)."""
        self.saturation_value_label.setText(f"{value}%")

    def _on_saturation_reset(self):
        """Reset the saturation slider to its factory value (100%; applies on Apply)."""
        self.saturation_slider.setValue(int(_registry_default("display.color_saturation")))

    @_page_sync.page_apply
    def _on_saturation_apply(self):
        """Quantize to 5%, persist, and emit for live propagation."""
        value = int(round(self.saturation_slider.value() / 5.0) * 5)
        value = max(0, min(100, value))
        self.saturation_slider.blockSignals(True)
        self.saturation_slider.setValue(value)
        self.saturation_slider.blockSignals(False)
        self.saturation_value_label.setText(f"{value}%")
        try:
            from managers.settings_manager import get_settings
            get_settings().set("display.color_saturation", value)
            self._saved_saturation = value
        except Exception:
            pass
        self.saturation_changed.emit(value)

    def _on_reset(self):
        """Reset the slider to the factory scale (100%)."""
        self.scale_slider.setValue(int(round(_registry_default("display.font_scale") * 100)))

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
        # O-6: font-size must be replayed here too, or a theme switch drops the
        # sizes back to the qt-material 13px default (construction sets them).
        self.scale_group.setStyleSheet(
            get_group_box_style()
            + f" QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; }}")
        self.reset_btn.setStyleSheet(get_primary_button_style())
        self.auto_detect_btn.setStyleSheet(get_secondary_button_style())
        self.apply_btn.setStyleSheet(get_primary_button_style())
        self.scale_tip_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        # preview_title font-size is owned by _apply_preview_scale (factor-based);
        # re-assert a sane default here so a theme switch before any slider move
        # does not refreeze it.
        self.preview_title.setStyleSheet(
            f"color: {theme['secondary_text']}; border: none; "
            f"font-size: 10px; font-weight: bold;")
        self.dpi_info_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px;")
        # SPEC-SAT-001 group. Missing here since the group shipped, so a live
        # theme switch left the whole Color Saturation box on its dark
        # construction colors while the rest of the page went light -- visible
        # as a black box on a light theme.
        #
        # Every widget below is styled at CONSTRUCTION and must be replayed
        # here. Hand-listing is exactly how this was missed: if you add a widget
        # to this page with a setStyleSheet call, add it here in the same edit.
        # The gate that now catches it is test/theme_audit.py's settings walk
        # (_walk_settings_sections) plus the reference-free VIS-LINT.
        self.saturation_group.setStyleSheet(
            get_group_box_style()
            + f" QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; }}")
        self.saturation_reset_btn.setStyleSheet(get_secondary_button_style())
        self.saturation_apply_btn.setStyleSheet(get_primary_button_style())
        self._apply_preview_theme()
        # td-c038: re-compose tagged migrated font-sizes from the live setting.
        _replay_fonts(self)


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
        _tag_font(self, 'buttons')  # td-c038 live-replay of the lock glyph
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
        # O-6: font-size in QSS so the lock glyph tracks the font settings.
        self.setStyleSheet(
            ("color:#D4AF37;" if locked else "color:#888;")
            + f" font-size: {scaled_area_px('buttons')}px;")


def _locked_row(form, key_paths, label_text, field, desc=None):
    cell = QWidget()
    row = QHBoxLayout(cell)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(_PadlockButton(key_paths))
    _lbl = QLabel(label_text)
    # O-6: font-size in QSS (row label built here, not via a string addRow).
    _lbl.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
    _tag_font(_lbl, 'buttons')
    row.addWidget(_lbl)
    row.addStretch()
    form.addRow(cell, field)
    if desc:
        detail = QLabel(desc)
        detail.setWordWrap(True)
        _hint.style(detail, 'info_text', 'margin-bottom:4px;')
        _tag_font(detail, 'info_text')
        form.addRow("", detail)


class _CenterDrawingRows:
    """A center drawing's two Chart Display rows (SPEC-VAC-001 §4.0): its ON checkbox
    and its min-virupas spin box. The panel's toggle and rail write the same keys: the
    rows follow those writes live until the user edits them (until Apply or a load)."""

    KEYS = {"tajika": ("chart.tajika_center_on", "chart.tajika_center_min_virupas"),
            "vedic": ("chart.vedic_center_on", "chart.vedic_center_min_virupas")}

    def __init__(self, kind):
        self.on_key, self.min_key = self.KEYS[kind]
        self.cb = QCheckBox()
        self.spin = QSpinBox()
        low, high = _registry_setting(self.min_key).bounds
        self.spin.setRange(int(low), int(high))
        self.spin.setMaximumWidth(90)
        self.touched = self.loading = False

    def build(self, tab, form, settings):
        for key, field in ((self.on_key, self.cb), (self.min_key, self.spin)):
            _locked_row(form, key, _rows.label(key), field, _rows.help_text(key))
            settings.on_changed(key, self.written)
            tab.destroyed.connect(lambda *_, s=settings, k=key, f=self.written:
                                  s.remove_on_changed(k, f))
        self.cb.clicked.connect(self.touch)
        self.spin.valueChanged.connect(self.touch)

    def touch(self, *_):
        if not self.loading:
            self.touched = True

    def written(self, key, value):
        """The panel wrote one of the keys: follow it unless the row was edited."""
        import shiboken6
        if self.touched or not shiboken6.isValid(self.cb):
            return
        self.loading = True
        try:
            if key == self.on_key:
                self.cb.setChecked(bool(value))
            else:
                self.spin.setValue(int(value))
        finally:
            self.loading = False

    def load(self, s):
        self.loading = True
        self.cb.setChecked(bool(_rows.saved(s, self.on_key)))
        self.spin.setValue(int(_rows.saved(s, self.min_key)))
        self.loading = self.touched = False

    def apply(self, s):
        s.set(self.on_key, self.cb.isChecked())
        s.set(self.min_key, self.spin.value())
        self.touched = False


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
    # O-6: font-size + weight in QSS.
    lbl.setStyleSheet(
        f"font-weight: bold; font-size: {scaled_area_px('buttons')}px;")
    _tag_font(lbl, 'buttons')
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
        # O-6: font-size in QSS.
        rb.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(rb, 'buttons')
        rb.setProperty("opt_value", value)
        rh.addWidget(rb)
        group.addButton(rb, i)
    rh.addStretch()
    form.addRow("", radio_cell)

    if desc:
        d = QLabel(desc)
        d.setWordWrap(True)
        _hint.style(d, 'info_text', 'margin-bottom:4px;')
        _tag_font(d, 'info_text')
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
    ("tajika", 2),  # 6 Yogas (annual Tajika)
    ("tajika", 3),  # 7 Nabhasa (natal whole-chart yogas)
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

    # G9a: the settings keys this tab HOSTS — reset by an explicit allowlist, never
    # reset_to_defaults("zodiac") (which would clobber any zodiac.* key another
    # surface owns and skips the display-flavoured keys this tab also writes). Every
    # key _on_apply writes is in here (pinned by test_g9a_zodiac_reset_allowlist);
    # it also carries the GUI-less domain keys the tab's Reset has always restored
    # (dasha.zr.anchor). If Finding-1A later moves a key to the Chart Display
    # tab, drop it from this set.
    # Since SPEC-SET-003 W3a the list is the registry's zodiac_calculation section
    # (28 keys since the custom ayanamsa, td-xfp7b): a key joins or leaves it in
    # core/settings_registry/owners.py.
    OWNED_KEYS = _rows.owned_keys("zodiac_calculation")
    # Defaults for owned keys absent from DEFAULT_SETTINGS (settings_manager.py is
    # line-frozen by the SI ratchet). A key covered by NEITHER raises at Reset.
    OWNED_KEY_DEFAULTS = {k: _registry_default(k) for k in ("ui.hd_experience_level",)}

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
        self.dasha_left_mode_combo.currentIndexChanged.connect(self._update_dasha_right_enabled)
        self._update_ayanamsa_enabled()
        self._update_dasha_right_enabled()
        from ui import settings_dasha_sync   # rows follow the dasha panels' picks
        settings_dasha_sync.attach(self)
        _page_sync.attach(self, self._read_from_settings, self.OWNED_KEYS)  # AI redesign

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
        desc_style = _hint.hint_style('info_text', "margin-bottom: 4px;")

        # td-c038: record desc_style so every inline description label (all share
        # this exact string) can be tagged for live font-replay in one pass at the
        # end of construction; _hdr tags the inline section headers as they build.
        self._c038_desc_style = desc_style

        def _hdr(lbl):
            return _tag_font(lbl, 'panel_titles')

        # 4B: page-level Apply/Reset explanation at the top of the page (mirrors the
        # Chart Display page).
        page_note = QLabel("Changes take effect when you click Apply and are kept "
                           "across restarts. Reset to Default restores only the "
                           "settings on this page.")
        page_note.setWordWrap(True)
        page_note.setStyleSheet(desc_style)
        _tag_font(page_note, 'info_text')
        form.addRow("", page_note)

        # SPEC-MODE-001: experience-level gate at the top of the Zodiac section.
        # Beginner hides alternative sign-naming; Advanced exposes all 6 combinations.
        self.experience_radio = _locked_radio_group(
            form,
            "ui.experience_level",
            _rows.label("ui.experience_level"),
            _rows.radio_options("ui.experience_level"),
            desc=_rows.help_text("ui.experience_level"),
        )

        zodiac_header = QLabel("Zodiac System & Sign Naming")
        zodiac_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 4px;")
        _hdr(zodiac_header)
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
        _rows.calculation_tooltip(self.zodiac_combo, "zodiac.mode")
        _locked_row(form, ["zodiac.mode", "zodiac.use_western_names"], _rows.label("zodiac.mode"), self.zodiac_combo)
        # 2B: pointer to where the DRAWING of the signs is chosen (Chart Display),
        # the mirror of the Sign display pointer on that page.
        zodiac_mode_pointer = QLabel(
            "How the signs are drawn, as names, symbols or Josh's glyphs, is chosen "
            "under Chart Display.")
        zodiac_mode_pointer.setWordWrap(True)
        zodiac_mode_pointer.setStyleSheet(desc_style)
        _tag_font(zodiac_mode_pointer, 'info_text')
        form.addRow("", zodiac_mode_pointer)

        ayan_header = QLabel("Ayanamsa")
        ayan_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        _hdr(ayan_header)
        form.addRow("", ayan_header)

        ayan_desc = QLabel(
            "The ayanamsa is the angular difference between the Tropical and "
            "Sidereal zodiacs. It sets the Sidereal zodiac positions and the "
            "sidereal nakshatra frame used by Nakshatra Compatibility, so it stays "
            "available in every zodiac mode. Default: True Citra.\n"
            "Students: with the Aditya Circle, use Vedanga Jyotisha; with the "
            "classic Tropical zodiac, use Dhruva GC mid-Mula (galactic center "
            "in the middle of Mula)."
        )
        ayan_desc.setWordWrap(True)
        ayan_desc.setStyleSheet(desc_style)
        form.addRow("", ayan_desc)

        # SPEC-SET-003 W3b: items, labels and row titles come from the registry.
        self.ayanamsa_combo = _rows.registry_combo("zodiac.ayanamsa_id")
        _locked_row(form, "zodiac.ayanamsa_id", _rows.label("zodiac.ayanamsa_id"),
                    self.ayanamsa_combo)

        def _section_header(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
            form.addRow("", _hdr(lbl))
        from ui import settings_custom_ayanamsa_rows as _cust   # custom ayanamsa (id 255)
        self.custom_ayanamsa_rows = _cust.build_rows(form, desc_style, _locked_row, _section_header,
                                                     self.ayanamsa_combo)

        dasha_header = QLabel("Dasha Ayanamshas")
        dasha_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        _hdr(dasha_header)
        form.addRow("", dasha_header)

        dasha_desc = QLabel(
            "Both dasha panels can show any dasha: Vimshottari, Planetary Ages, "
            "or Zodiacal Releasing. F7 switches the right panel, Shift+F7 "
            "the left. Each panel keeps its own ayanamsa for Vimshottari; the "
            "left one is also the Nakshatra ayanamsa."
        )
        dasha_desc.setWordWrap(True)
        dasha_desc.setStyleSheet(desc_style)
        form.addRow("", dasha_desc)

        self.dasha_left_combo = _rows.registry_combo("dasha.left.ayanamsa_id")
        self.dasha_right_combo = _rows.registry_combo("dasha.right.ayanamsa_id")
        # SPEC-DSH-004: both panels offer every mode of the one registry
        # (managers.dasha.modes.MODES, through the settings registry).
        self.dasha_left_mode_combo = _rows.registry_combo("dasha.left.mode")
        self.dasha_right_mode_combo = _rows.registry_combo("dasha.right.mode")
        _locked_row(form, "dasha.left.mode", _rows.label("dasha.left.mode"),
                    self.dasha_left_mode_combo)
        _locked_row(form, "dasha.left.ayanamsa_id", _rows.label("dasha.left.ayanamsa_id"),
                    self.dasha_left_combo)
        _locked_row(
            form,
            ["dasha.right.mode", "dasha.right.ayanamsa_id"],
            _rows.label("dasha.right.mode"),
            self.dasha_right_mode_combo,
        )
        form.addRow(_form_label(_rows.label("dasha.right.ayanamsa_id")),
                    self.dasha_right_combo)

        # SPEC-DSH-003: dasha year length (Kala "Dasa Length"), nakshatra family.
        self.dasha_year_combo = _rows.registry_combo("dasha.year_length.nakshatra")
        form.addRow(_form_label(_rows.label("dasha.year_length.nakshatra")),
                    self.dasha_year_combo)
        year_desc = QLabel(
            "Days per dasha year for Vimshottari on both panels. Saura is "
            "Kala's default. Kala's Dasa Length setting must match this one "
            "before comparing dates: the Nakshatra year runs about 6 days "
            "shorter per dasha year, three months by age 15.")
        year_desc.setWordWrap(True)
        year_desc.setStyleSheet(desc_style)
        form.addRow("", year_desc)

        # SPEC-ZR-001 DD6: two ZR rows, always visible, enabled only in zr mode.
        # The releaser combo's 12 sign labels follow the zodiac display, so it is
        # rebuilt whenever the zodiac combo changes (_rebuild_zr_releaser_combo).
        self.dasha_zr_releaser_combo = QComboBox()
        self.dasha_zr_releaser_combo.setMaximumWidth(220)
        _rows.calculation_tooltip(self.dasha_zr_releaser_combo, "dasha.zr.releaser")
        self._rebuild_zr_releaser_combo()
        self.zodiac_combo.currentIndexChanged.connect(self._rebuild_zr_releaser_combo)
        form.addRow(_form_label(_rows.label("dasha.zr.releaser")), self.dasha_zr_releaser_combo)

        from PySide6.QtWidgets import QCheckBox as _QCheckBox
        zr_opts = QWidget()
        zr_opts_layout = QVBoxLayout(zr_opts)
        zr_opts_layout.setContentsMargins(0, 0, 0, 0)
        zr_opts_layout.setSpacing(2)
        self.dasha_zr_shift_cb = _QCheckBox(_rows.label("dasha.zr.spirit_shift"))
        _rows.calculation_tooltip(self.dasha_zr_shift_cb, "dasha.zr.spirit_shift")
        # O-6: font-size in QSS (text checkbox).
        self.dasha_zr_shift_cb.setStyleSheet(
            f"QCheckBox {{ font-size: {scaled_area_px('buttons')}px; }}")
        _tag_font(self.dasha_zr_shift_cb, 'buttons')
        self.dasha_zr_shift_cb.setChecked(True)
        zr_opts_layout.addWidget(self.dasha_zr_shift_cb)
        self.dasha_zr_options_widget = zr_opts
        form.addRow(_form_label("Releasing: options:"), zr_opts)

        self.nak_coords_combo = _rows.registry_combo("zodiac.nakshatra_coords")
        _locked_row(form, "zodiac.nakshatra_coords", _rows.label("zodiac.nakshatra_coords"),
                    self.nak_coords_combo)
        nak_desc = QLabel(
            "Controls how custom ayanamsas (Dhruva, Vedanga) compute "
            "nakshatra positions. 'Neither' matches Kala's default."
        )
        nak_desc.setWordWrap(True)
        nak_desc.setStyleSheet(desc_style)
        form.addRow("", nak_desc)
        from ui import settings_strength_rows as _srows   # SPEC-STR-001 §7.5
        self.strength_duc_combos = _srows.build_rows(form, _locked_row)

        house_header = QLabel("House System")
        house_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        _hdr(house_header)
        form.addRow("", house_header)

        house_desc = QLabel(
            "Placidus is the common modern Western default. Whole Sign keeps "
            "one sign per house. Campanus is the default option used in Ernst "
            "group studies."
        )
        house_desc.setWordWrap(True)
        house_desc.setStyleSheet(desc_style)
        form.addRow("", house_desc)

        self.house_combo = _rows.registry_combo("zodiac.house_system")
        _locked_row(form, "zodiac.house_system", _rows.label("zodiac.house_system"),
                    self.house_combo)

        house_note = QLabel("Applies immediately to the open chart when you click Apply.")
        _hint.style(house_note, 'info_text')
        _tag_font(house_note, 'info_text')
        form.addRow("", house_note)

        # G9b (td-v6nqc): "Wheel house display" MOVED to the Chart Display tab
        # (a drawing choice). Cards of Truth stays here (a calculation).
        cot_header = QLabel("Cards of Truth")
        cot_header.setStyleSheet(f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 12px;")
        _hdr(cot_header)
        form.addRow("", cot_header)

        # Solar System FIRST (registry order): it is the default (SPEC-COT-001 D-5),
        # and index 0 is where a findData miss lands, so the fallback and the
        # default must be the same entry.
        self.cot_order_combo = _rows.registry_combo("cot.planet_order", max_width=320)
        _locked_row(form, "cot.planet_order", _rows.label("cot.planet_order"),
                    self.cot_order_combo)

        cot_desc = QLabel(
            "The seven main cards always sit in the same seven places; this "
            "chooses which planet sits where.\n"
            "Week Day follows the planets that rule the days of the week, "
            "starting at Sunday: Sun, Moon, Mars (Tuesday), Mercury "
            "(Wednesday), Jupiter (Thursday), Venus (Friday), Saturn "
            "(Saturday).\n"
            "Solar System follows the sky: Sun, Moon, then the planets "
            "outward from the Sun, Mercury, Venus, Mars, Jupiter, Saturn."
        )
        cot_desc.setWordWrap(True)
        cot_desc.setStyleSheet(desc_style)
        form.addRow("", cot_desc)

        # SPEC-COT-001 §4.10. Each sign shows the card of its RULING planet,
        # so the same card appears in both of a planet's signs.
        self.cot_in_chart_cb = QCheckBox()
        _locked_row(
            form, "cot.show_in_chart", _rows.label("cot.show_in_chart"),
            self.cot_in_chart_cb,
            _rows.help_text("cot.show_in_chart"),
        )

        # G9b (td-v6nqc): "Historical Dates (before 1582)" and "Date format"
        # MOVED to the Chart Display tab's "Dates" group (both are DRAWING/display
        # choices, per Lorris's rule). Their keys left this tab's OWNED_KEYS.

        # -- Human Design ----------------------------------------------------
        # Mirrors the Zodiac experience gate above. Beginner (default, locked)
        # pins the bodygraph and the -88 Design chart to the Standard tropical
        # frame; Advanced lets the top-bar zodiac buttons drive the HD frame.
        # This is the ONE place the Aditya-shifted-gate meaning is explained
        # (the old on-page warning popup is gone).
        hd_header = QLabel("Human Design")
        hd_header.setStyleSheet(
            f"font-weight: bold; font-size: {scaled_area_px('panel_titles')}px; margin-top: 8px;")
        _hdr(hd_header)
        form.addRow("", hd_header)

        self.hd_experience_radio = _locked_radio_group(
            form,
            "ui.hd_experience_level",
            _rows.label("ui.hd_experience_level"),
            _rows.radio_options("ui.hd_experience_level"),
            desc=_rows.help_text("ui.hd_experience_level"),
        )
        for _b in self.hd_experience_radio.buttons(): _rows.calculation_tooltip(_b, "ui.hd_experience_level")

        hd_frame_desc = QLabel(
            "Beginner: Human Design is locked to Tropical Classic, the mapping used "
            "by every Human Design website and book. The zodiac buttons on the chart "
            "tab still switch your astrology chart, but the bodygraph and the Design "
            "chart stay on Tropical Classic. This is a safety rail for readers new to "
            "Human Design, not a restriction on what the app can do.\n\n"
            "Advanced: the zodiac buttons also drive Human Design. Aditya Circle "
            "starts gate 1 at 193.25 degrees instead of 223.25, and Sidereal applies "
            "your ayanamsa. Every gate shifts, so type, authority, profile and cross "
            "can all differ from a conventional Human Design chart. These frames are "
            "an area of research and you are free to test them with your own charts."
        )
        hd_frame_desc.setWordWrap(True)
        hd_frame_desc.setStyleSheet(desc_style)
        form.addRow("", hd_frame_desc)

        # C9 item 2: a link that opens the SAME frame-lock explanation users see
        # in the in-app popup (explain_frames), so Settings and the popup can
        # never drift.
        #
        # The link appears only once real copy exists. It first shipped with the
        # module's "[COPY PENDING]" marker as its visible label, and Lorris met
        # that placeholder in his running app on 2026-08-30. A placeholder is a
        # note between sessions, never a string a user is allowed to read: no
        # link at all is strictly better than a link that says nothing.
        # copy_is_pending() is the single source of that judgement, and
        # explain_frames() refuses independently, so forgetting this guard
        # cannot put a placeholder dialog on screen either.
        try:
            from apps.widgets.hd.hd_frame_notice import (
                copy_is_pending, explain_frames, EXPLAIN_TITLE)
            if not copy_is_pending():
                hd_frame_link = QLabel('<a href="#hd-frames">Read the full explanation</a>')
                hd_frame_link.setOpenExternalLinks(False)
                hd_frame_link.setStyleSheet(desc_style)
                hd_frame_link.linkActivated.connect(
                    lambda _=None: explain_frames(self))
                form.addRow("", hd_frame_link)
        except Exception as _hd_link_err:
            print(f"[WARNING] HD frame explanation link not wired: {_hd_link_err}")

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

        # td-c038 live-replay: tag every inline description label (all share the
        # exact desc_style string) in one pass, plus the action buttons, so
        # refresh_theme -> _replay_fonts re-composes them on a live font change.
        for _lbl in self.findChildren(QLabel):
            if _lbl.styleSheet() == self._c038_desc_style:
                _tag_font(_lbl, 'info_text')
                _hint.mark(_lbl)
        _tag_font(self.reset_btn, 'action_buttons')
        _tag_font(self.apply_btn, 'action_buttons')

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
        level = _rows.saved(get_settings(), "ui.experience_level")
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
        # SPEC-KUTA-AYA-001 3.2: the Ayanamsa combo is ALWAYS enabled, in every zodiac
        # mode and experience level, because Nakshatra Compatibility (kuta) consumes the
        # sidereal frame regardless of the chart display mode. It is no longer gated to
        # Sidereal display. Grayed only while "Use custom ayanamsa" holds it on id 255.
        from ui.settings_custom_ayanamsa_rows import custom_in_use
        rows = getattr(self, "custom_ayanamsa_rows", None)
        self.ayanamsa_combo.setEnabled(rows is None or not custom_in_use(rows))

    def _rebuild_zr_releaser_combo(self):
        """SPEC-ZR-001 DD6: Spirit / Fortune / 12 signs in position order.

        The sign labels follow the pending zodiac-combo selection (mode + naming),
        so a Sidereal or Western pick relabels the releaser list before Apply. The
        stored value (spirit / fortune / sign:{i}) is preserved by data role.
        """
        combo = getattr(self, "dasha_zr_releaser_combo", None)
        if combo is None:
            return
        from core.aditya_mode import displayed_sign_name
        data = self.zodiac_combo.currentData()
        mode, western = data if data else ("aditya", False)
        prior = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Spirit", "spirit")
        combo.addItem("Fortune", "fortune")
        from core.lots import LOT_REGISTRY, LOT_ORDER
        for name in LOT_ORDER:
            combo.addItem("Lot of " + LOT_REGISTRY[name]["label"], f"lot:{name}")
        for i in range(12):
            combo.addItem(displayed_sign_name(i, mode, western), f"sign:{i}")
        if prior is not None:
            idx = combo.findData(prior)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _update_dasha_right_enabled(self):
        right_mode = self.dasha_right_mode_combo.currentData()
        left_mode = self.dasha_left_mode_combo.currentData()
        # The left ayanamsa stays editable in every mode: it is also the
        # Nakshatra ayanamsa (SPEC-DSH-004 INV-10).
        self.dasha_right_combo.setEnabled(right_mode == "vimshottari")
        is_zr = "zr" in (right_mode, left_mode)
        for w in (getattr(self, "dasha_zr_releaser_combo", None),
                  getattr(self, "dasha_zr_shift_cb", None)):
            if w is not None:
                w.setEnabled(is_zr)

    def _read_from_settings(self):
        from managers.settings_manager import get_settings
        settings = get_settings()

        self._select_radio_value(self.experience_radio, self._experience_level())
        self._rebuild_zodiac_combo()
        self._select_radio_value(
            self.hd_experience_radio,
            _rows.saved(settings, "ui.hd_experience_level"))
        mode = _rows.saved(settings, "zodiac.mode")
        western = _rows.saved(settings, "zodiac.use_western_names")
        self.zodiac_combo.setCurrentIndex(self._find_combo_index(mode, western))

        for combo, key in (
            (self.ayanamsa_combo, "zodiac.ayanamsa_id"),
            (self.house_combo, "zodiac.house_system"),
            # G9b: wheel_house_display / calendar_convention / date_format read on
            # the Chart Display tab now (moved there).
            (self.dasha_left_combo, "dasha.left.ayanamsa_id"),
            (self.dasha_right_combo, "dasha.right.ayanamsa_id"),
            (self.dasha_year_combo, "dasha.year_length.nakshatra"),
            (self.nak_coords_combo, "zodiac.nakshatra_coords"),
            # SPEC-COT-001: this row was MISSING, and _on_apply writes the
            # combo's current value unconditionally. So the panel always opened
            # showing index 0 whatever was stored, and pressing Apply for any
            # unrelated reason silently reset the order — which is why changing
            # it appeared to do nothing.
            (self.cot_order_combo, "cot.planet_order"),
        ):
            _rows.select_data(combo, _rows.saved(settings, key))
        # A saved mode this build no longer offers (a removed dasha) shows the
        # side's default, the mode its panel falls back to (normalize_mode).
        from managers.dasha.modes import normalize_mode
        for combo, side in ((self.dasha_left_mode_combo, "left"),
                            (self.dasha_right_mode_combo, "right")):
            _rows.select_data(combo, normalize_mode(
                side, _rows.saved(settings, f"dasha.{side}.mode")))

        # Same trap as cot.planet_order above: _on_apply writes this checkbox
        # unconditionally, so without a read-back the panel opens UNCHECKED
        # whatever is stored and the next Apply turns the feature off.
        self.cot_in_chart_cb.setChecked(
            bool(_rows.saved(settings, "cot.show_in_chart"))
        )

        # SPEC-ZR-001 DD6: ZR releaser + options. Rebuild the releaser combo first
        # so its data roles exist, then select the stored value.
        self._rebuild_zr_releaser_combo()
        zr_idx = self.dasha_zr_releaser_combo.findData(
            _rows.saved(settings, "dasha.zr.releaser"))
        if zr_idx >= 0:
            self.dasha_zr_releaser_combo.setCurrentIndex(zr_idx)
        self.dasha_zr_shift_cb.setChecked(
            bool(_rows.saved(settings, "dasha.zr.spirit_shift")))

        from ui import settings_strength_rows as _srows
        _srows.read_rows(self.strength_duc_combos, settings)
        from ui import settings_custom_ayanamsa_rows as _cust
        _cust.read_rows(self.custom_ayanamsa_rows, settings)
        _cust.show_offsets(self.ayanamsa_combo, self.dasha_left_combo, self.dasha_right_combo)

        self._update_ayanamsa_enabled()
        self._update_dasha_right_enabled()

    @_page_sync.page_apply
    def _on_apply(self):
        from managers.settings_manager import get_settings
        settings = get_settings()

        # SPEC-MODE-001: experience level. In Beginner, force native naming for
        # the chosen system (use_western = mode != "aditya") so the alternative
        # label set can never be committed from this panel.
        new_level = self._radio_value(self.experience_radio, "beginner")
        old_level = _rows.saved(settings, "ui.experience_level")

        mode, western = self.zodiac_combo.currentData()
        if new_level == "beginner":
            western = (mode != "aditya")
        old_mode = _rows.saved(settings, "zodiac.mode")
        old_western = _rows.saved(settings, "zodiac.use_western_names")
        old_ayanamsa = _rows.saved(settings, "zodiac.ayanamsa_id")
        old_house = _rows.saved(settings, "zodiac.house_system")
        old_left = _rows.saved(settings, "dasha.left.ayanamsa_id")
        old_right_mode = _rows.saved(settings, "dasha.right.mode")
        old_left_mode = _rows.saved(settings, "dasha.left.mode")
        old_right_aid = _rows.saved(settings, "dasha.right.ayanamsa_id")
        old_nak_coords = _rows.saved(settings, "zodiac.nakshatra_coords")
        old_year_length = _rows.saved(settings, "dasha.year_length.nakshatra")
        old_zr_releaser = _rows.saved(settings, "dasha.zr.releaser")
        old_zr_shift = _rows.saved(settings, "dasha.zr.spirit_shift")

        new_ayanamsa = self.ayanamsa_combo.currentData()
        new_house = self.house_combo.currentData()
        new_left = self.dasha_left_combo.currentData()
        new_right_mode = self.dasha_right_mode_combo.currentData()
        new_left_mode = self.dasha_left_mode_combo.currentData()
        new_right_aid = self.dasha_right_combo.currentData()

        settings.set("ui.experience_level", new_level)
        settings.set("ui.hd_experience_level",
                     self._radio_value(self.hd_experience_radio, "beginner"))
        settings.set("zodiac.mode", mode)
        settings.set("zodiac.use_western_names", western)
        settings.set("zodiac.ayanamsa_id", new_ayanamsa)
        settings.set("zodiac.house_system", new_house)
        settings.set("dasha.left.ayanamsa_id", new_left)
        settings.set("dasha.right.mode", new_right_mode)
        settings.set("dasha.left.mode", new_left_mode)
        from ui import settings_strength_rows as _srows   # the panels listen to the key
        _srows.apply_rows(self.strength_duc_combos, settings)
        from ui import settings_custom_ayanamsa_rows as _cust
        _cust.apply_rows(self.custom_ayanamsa_rows, settings)   # the manager redraws 255 users
        _cust.show_offsets(self.ayanamsa_combo, self.dasha_left_combo, self.dasha_right_combo)
        settings.set("dasha.right.ayanamsa_id", new_right_aid)
        new_year_length = self.dasha_year_combo.currentData()
        settings.set("dasha.year_length.nakshatra", new_year_length)
        # SPEC-ZR-001 DD6: ZR releaser + options share the same keys as the title
        # menu (last writer wins).
        new_zr_releaser = self.dasha_zr_releaser_combo.currentData()
        new_zr_shift = self.dasha_zr_shift_cb.isChecked()
        settings.set("dasha.zr.releaser", new_zr_releaser)
        settings.set("dasha.zr.spirit_shift", new_zr_shift)
        new_nak_coords = self.nak_coords_combo.currentData()
        settings.set("zodiac.nakshatra_coords", new_nak_coords)
        settings.set("cot.planet_order", self.cot_order_combo.currentData())
        # set() fires the key-prefix callbacks, and every live South Indian
        # vector view is subscribed — so the chart redraws without a reload.
        settings.set("cot.show_in_chart", self.cot_in_chart_cb.isChecked())
        # G9b (td-v6nqc): display.calendar_convention and display.date_format are
        # written on the Chart Display tab now (moved there with their rows).

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
        # G9b: wheel house display moved to Chart Display; its live update now
        # travels via that tab's chart_display_changed -> _on_chart_display_changed
        # (which reads chart.wheel_house_display and applies it to the wheel).
        if (new_left != old_left or new_right_mode != old_right_mode
                or new_left_mode != old_left_mode
                or new_right_aid != old_right_aid
                or new_nak_coords != old_nak_coords
                or new_year_length != old_year_length
                or new_zr_releaser != old_zr_releaser
                or new_zr_shift != old_zr_shift):
            self.dasha_changed.emit()

        # Rebuild the combo (3 <-> 6 entries) when the experience level changed,
        # giving instant visual feedback and re-selecting the same system.
        if new_level != old_level:
            self._rebuild_zodiac_combo()
            self.zodiac_combo.setCurrentIndex(self._find_combo_index(mode, western))

    @_page_sync.page_write
    def _on_reset(self):
        # G9a: explicit owned-key allowlist (was reset_to_defaults("zodiac") + a
        # partial list of dasha keys, which reset NONE of the display-flavoured keys
        # this tab also hosts — chart.wheel_house_display, cot.*, display.*, ui.* —
        # and would clobber any zodiac.* key another surface owns). One set() per
        # owned key, defaults single-sourced from DEFAULT_SETTINGS (else the
        # co-located OWNED_KEY_DEFAULTS), no silent fallback. Still covers the
        # GUI-less dasha.zr.anchor the old Reset restored
        # (SPEC-DSH-003, SPEC-ZR-001 DD6). Since SPEC-SET-003 W3a the defaults are
        # the registry's (a deep copy each), for persisted and fallback-only keys alike.
        settings = get_settings()
        _rows.reset_section(settings, "zodiac_calculation")
        self._read_from_settings()
        # Flush the whole reset transaction, even if Apply now sees equal values.
        self.zodiac_changed.emit(_rows.saved(settings, "zodiac.mode"))
        self.dasha_changed.emit()

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(f"ZodiacCalculationTab {{ background-color: {theme['secondary_dark']}; }}")
        self.reset_btn.setStyleSheet(get_secondary_button_style())
        self.apply_btn.setStyleSheet(get_primary_button_style())
        # td-c038: re-compose migrated font-sizes from the live setting (this tab
        # previously replayed no fonts at all — every label was static).
        _replay_fonts(self)


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
        ("tabs", "Tab Bar"),
        ("action_buttons", "Action buttons"),
        ("sidebar", "Sidebar & Navigation"),
        ("chart_memory", "Chart Names"),
        ("panel_titles", "Panel Titles"),
        ("table_headers", "Table Headers"),
        ("tables", "Tables & Data"),
        ("status", "Status & Captions"),
        ("chart_labels", "Chart Labels"),
        ("planet_degrees", "Planet Degrees"),
        ("house_numbers", "House Numbers"),
        ("cusp_degrees", "Cusp Degrees"),
        ("info_text", "Info & Descriptions"),
        ("buttons", "Buttons & Controls"),
    ]

    _AREA_GROUP_STARTS = {
        "tabs": ("WINDOW FRAME & NAVIGATION", "always visible around the chart"),
        "panel_titles": ("INFO PANELS", "the centre panels beside the chart"),
        "chart_labels": ("CHART", "text drawn on the chart itself"),
        "info_text": ("FORMS, DIALOGS & HELP", "New & Edit, Find Chart and dialogs"),
    }

    _PREVIEW_INFO = {
        "tables": {
            "where": "Center-panel data rows (Strength, Aspects, Elements, Karakas); "
                     "planet positions in chart info; Find Chart results; dasha cycle rows.",
            "samples": [
                "Sun  42.8  |  Moon  187.3  |  Mars  315.6",
                "Venus  Dhata  12.5  |  Saturn  Mitra  28.3",
            ],
        },
        "table_headers": {
            "where": "Column headers above the center-panel tables; section headers in "
                     "chart info dialogs; dual chart comparison names.",
            "samples": [
                "PLANET   DIGBALA   UCCHA   SIGN   DEGREE",
            ],
        },
        "panel_titles": {
            "where": "Section headings in the center panels AND the panel tab buttons "
                     "(Karakas, Hora, Strength, Avastha...); dialog titles; "
                     "Find Chart section titles.",
            "samples": [
                "Strength   Aspects   Elements   Karakas",
            ],
        },
        "chart_labels": {
            "where": "Text painted on the charts: sign names, the Ascendant degree, the "
                     "degree-ruler ticks, element-pie percentages, the North Indian "
                     "Ascendant label, and the Cards of Truth labels (card titles, the "
                     "period ruler, the medallion and its AGE line).",
            "samples": [
                "Dhata   Aryama   ASC 11°38'",
            ],
        },
        "planet_degrees": {
            "where": "The degree under each planet on the South Indian, North Indian "
                     "and wheel charts.",
            "samples": [
                "Sun 23°30'   Moon 14°31'   Mars 26°54'",
            ],
        },
        "house_numbers": {
            "where": "The house number in each sign of the chart.",
            "samples": [
                "H 1   H 4   H 7   H 10",
            ],
        },
        "cusp_degrees": {
            "where": "The house cusp degrees written in the signs of the chart.",
            "samples": [
                "C1 11°   C4 12°   C7 11°   C10 12°",
            ],
        },
        "info_text": {
            "where": "Help text, form labels and descriptions: the chart editing form, "
                     "ayanamsa help, Find Chart field labels, loading messages, tooltips.",
            "samples": [
                "Enter the birth date, time, and location to calculate the chart",
            ],
        },
        "buttons": {
            "where": "The chart list buttons at the top of the Chart tab, right of the "
                     "chart names (Search, Sort, Clear All, Select, Load Folder, the page "
                     "arrows); the New and Edit chart forms; dialog buttons (chart info, "
                     "key, welcome, HD notice); the dasha level selectors 1-5; combo-box "
                     "text.",
            "samples": [
                "Save   Cancel   Apply   OK",
                "1   2   3   4   5",
            ],
        },
        "action_buttons": {
            "where": "The action bar under the chart list (Now, Add Chart, Birth Time, "
                     "the chart name, the zodiac buttons) and the styled buttons of "
                     "dialogs and forms (Save, Cancel, Apply); the bar height follows the "
                     "text. Not the chart list buttons (Search, Sort, Clear All, Select): "
                     "those are Buttons & Controls.",
            "samples": [
                "Save   Cancel   Apply   Close   Find Chart",
            ],
        },
        "sidebar": {
            "where": "Left columns: the sign selector (numbered 1-12, the sign name is "
                     "the tooltip) and the varga division selector (the varga division "
                     "numbers 1, 2, 9, 10R...); the ascendant guide list; the eclipse "
                     "panel navigation.",
            "samples": [
                "1   2   3   4   5   6   7   8   9   10   11   12",
                "1   2   9   10R   24R   60",
            ],
        },
        "chart_memory": {
            "where": "The chart name buttons of the chart list at the top of the Chart "
                     "tab, under the main tabs; the button width follows this size.",
            "samples": [
                "Lorris  |  Albert Einstein  |  Marie Curie",
            ],
        },
        "status": {
            "where": "Small captions and status lines: the page number and chart count "
                     "of the chart list, the dasha active-cycle caption below the list, "
                     "dual chart comparison metadata, login and Find Chart result "
                     "messages, panel footnotes.",
            "samples": [
                "Maha: Sun 6y  |  Antar: Moon 6m  |  Pratyantar: Mars 12d",
                "3 charts found  |  Screen: 1920x1080",
            ],
        },
        "tabs": {
            "where": "The main tab bar at the top of the window (Chart, Settings, Find "
                     "Chart, Nakshatra, Predictive Tools and the other main sections) and "
                     "the menu bar above it (File, View, License, Help) with its menus.",
            "samples": [
                "CHART   SETTINGS   FIND CHART   NAKSHATRA   PREDICTIVE TOOLS",
            ],
        },
    }

    _RESOLUTION_PRESETS = {
        "hd": {
            "label": "Compact",
            "values": {
                "tables": 8, "table_headers": 9, "panel_titles": 10,
                "info_text": 8, "buttons": 9, "action_buttons": 11, "sidebar": 8,
                "chart_memory": 8, "status": 8, "tabs": 10,
                "chart_labels": 13,
                "planet_degrees": 12, "house_numbers": 19, "cusp_degrees": 13,
            },
        },
        "fullhd": {
            "label": "Balanced",
            "values": {
                "tables": 9, "table_headers": 10, "panel_titles": 10,
                "info_text": 9, "buttons": 10, "action_buttons": 12, "sidebar": 9,
                "chart_memory": 9, "status": 8, "tabs": 11,
                "chart_labels": 14,
                "planet_degrees": 13, "house_numbers": 21, "cusp_degrees": 14,
            },
        },
        "2k": {
            "label": "Large",
            "values": {
                "tables": 11, "table_headers": 12, "panel_titles": 10,
                "info_text": 11, "buttons": 10, "action_buttons": 12, "sidebar": 10,
                "chart_memory": 10, "status": 9, "tabs": 12,
                "chart_labels": 16,
                "planet_degrees": 14, "house_numbers": 23, "cusp_degrees": 16,
            },
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spinboxes = {}
        self._preset_buttons = {}
        self._active_preset = None
        self._build_ui()
        self._read_from_settings()
        _page_sync.attach(self, self._read_from_settings,    # AI setting redesign
                          _rows.owned_keys("fonts"))

    def _build_ui(self):
        theme = get_theme_colors()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(0)

        self._header_label = QLabel("FONT SIZES")
        self._header_label.setStyleSheet(
            f"color: {theme['primary']}; font-weight: bold; "
            f"font-size: {scaled_area_px('panel_titles')}px; "
            f"padding-bottom: 8px;"
        )
        layout.addWidget(self._header_label)

        self._hint_label = QLabel("Choose a preset or adjust each area below.")
        self._hint_label.setStyleSheet(
            f"color: {theme['secondary_text']}; "
            f"font-size: {scaled_area_px('status')}px; padding-bottom: 10px;"
        )
        layout.addWidget(self._hint_label)

        self._shortcuts_frame = QFrame()
        shortcuts_row = QHBoxLayout(self._shortcuts_frame)
        shortcuts_row.setContentsMargins(14, 10, 14, 10)
        shortcuts_row.setSpacing(10)
        self._master_label = QLabel("All areas")
        # F-B2 (SPEC-FONT-001 §11 G3): was bold with no font-size, so qt-material
        # froze it at 13px on every preset. Wire it to buttons like the other
        # control-row labels; the live replay comes from the explicit setStyleSheet
        # in this section's refresh_theme (FontSizesSection does not use _replay_fonts).
        self._master_label.setStyleSheet(
            f"color: {theme['primary_text']}; font-weight: bold; "
            f"font-size: {scaled_area_px('buttons')}px;"
        )
        shortcuts_row.addWidget(self._master_label)
        self._master_spin = MixedValueSpinBox()
        # 7..48 like the large chart areas; each area clamps to its own bounds.
        self._master_spin.setRange(7, 48)
        self._master_spin.setFixedWidth(86)
        # F-B2 (G3): the master spinbox's QLineEdit renders at the qt-material 13px
        # default like the per-area spins; wire it to buttons (re-applied in
        # refresh_theme alongside the per-area spinboxes).
        self._master_spin.setStyleSheet(
            f"QSpinBox {{ font-size: {scaled_area_px('buttons')}px; }}")
        self._master_spin.valueChanged.connect(self._on_master_changed)
        shortcuts_row.addWidget(self._master_spin)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(2)
        shortcuts_row.addWidget(sep)

        self._preset_label = QLabel("Preset")
        self._preset_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-weight: bold; "
            f"font-size: {scaled_area_px('buttons')}px;"
        )
        shortcuts_row.addWidget(self._preset_label)
        for key, preset in self._RESOLUTION_PRESETS.items():
            btn = QPushButton(preset["label"])
            btn.setCheckable(True)
            btn.setMinimumWidth(108)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_preset_button(btn, False, theme)
            btn.clicked.connect(lambda checked, k=key: self._apply_preset(k))
            shortcuts_row.addWidget(btn)
            self._preset_buttons[key] = btn
        shortcuts_row.addStretch()
        self._style_shortcuts_frame(theme)
        layout.addWidget(self._shortcuts_frame)
        layout.addSpacing(18)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 8)
        grid.setVerticalSpacing(14)
        grid.setHorizontalSpacing(16)
        grid.setColumnMinimumWidth(0, 184)
        grid.setColumnMinimumWidth(1, 164)
        grid.setColumnMinimumWidth(2, 320)
        grid.setColumnMinimumWidth(3, 520)
        grid.setColumnStretch(2, 1)
        self._areas_grid = grid

        self._column_headers = {}
        for column, (key, text) in enumerate((
            ("area", "AREA"),
            ("size", "SIZE"),
            ("description", "DESCRIPTION"),
            ("screenshot", "SCREENSHOT"),
        )):
            header = QLabel(text)
            header.setObjectName(f"fontSizes{key.title()}Header")
            header.setMinimumHeight(34)
            grid.addWidget(header, 0, column)
            self._column_headers[key] = header

        self._preview_labels = {}
        self._preview_thumbs = {}
        self._area_labels = []
        self._where_labels = []
        self._shown_labels = {}
        self._default_labels = []
        self._restore_buttons = []
        self._group_labels = []
        self._preview_sample_style = (
            f"color: {theme['primary_text']}; "
            f"background-color: {theme['secondary']}; "
            f"border: 1px solid {theme['secondary_dark']}; "
            f"border-radius: 3px; padding: 4px 8px;"
        )
        where_style = (
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; "
            f"padding: 0px; margin: 0px;"
        )

        grid_row = 1
        for area_id, label_text in self._AREA_LABELS:
            group = self._AREA_GROUP_STARTS.get(area_id)
            if group:
                group_label = QLabel(f"{group[0]}    {group[1]}")
                group_label.setMinimumHeight(30)
                grid.addWidget(group_label, grid_row, 0, 1, 4)
                self._group_labels.append(group_label)
                grid_row += 1

            label = QLabel(label_text)
            # F-B2 (G3): row labels were color-only, so qt-material froze them at
            # 13px until the first refresh. Wire to buttons (replayed below).
            label.setStyleSheet(
                f"color: {theme['primary_text']}; "
                f"font-size: {scaled_area_px('buttons')}px;")
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label, grid_row, 0)
            self._area_labels.append(label)

            spin = QSpinBox()
            spin.setRange(*_registry_setting(f"display.fonts.{area_id}").bounds)
            spin.setFixedWidth(96)
            # O-6 (QSpinBox family): the internal QLineEdit renders at the
            # qt-material 13px default; font-size in the spinbox's own QSS wires
            # it to the settings. 'buttons' area (matches the form-control labels;
            # replayed in refresh_theme).
            spin.setStyleSheet(f"QSpinBox {{ font-size: {scaled_area_px('buttons')}px; }}")
            spin.valueChanged.connect(
                lambda val, aid=area_id: self._on_area_changed(aid, val)
            )
            self._spinboxes[area_id] = spin

            size_cell = QWidget()
            size_layout = QVBoxLayout(size_cell)
            size_layout.setContentsMargins(0, 0, 0, 0)
            size_layout.setSpacing(4)
            size_layout.addWidget(spin, 0, Qt.AlignmentFlag.AlignLeft)
            shown_label = QLabel()
            shown_label.setStyleSheet(where_style)
            size_layout.addWidget(shown_label)
            self._shown_labels[area_id] = shown_label
            default_row = QHBoxLayout()
            default_row.setContentsMargins(0, 0, 0, 0)
            default_row.setSpacing(4)
            default_label = QLabel(f"Default {AREA_DEFAULTS.get(area_id, 11)}")
            default_label.setStyleSheet(where_style)
            default_row.addWidget(default_label)
            restore_btn = QPushButton("restore")
            restore_btn.setFlat(True)
            restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            restore_btn.clicked.connect(
                lambda checked=False, aid=area_id: self._restore_area(aid)
            )
            default_row.addWidget(restore_btn)
            default_row.addStretch()
            size_layout.addLayout(default_row)
            self._default_labels.append(default_label)
            self._restore_buttons.append(restore_btn)
            grid.addWidget(size_cell, grid_row, 1, Qt.AlignmentFlag.AlignTop)

            info = self._PREVIEW_INFO.get(area_id, {})
            description_cell = QWidget()
            cell_layout = QVBoxLayout(description_cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(6)

            where_label = QLabel(info.get("where", ""))
            where_label.setWordWrap(True)
            where_label.setStyleSheet(where_style)
            cell_layout.addWidget(where_label)
            self._where_labels.append(where_label)

            sample_labels = []
            for sample_text in info.get("samples", []):
                slabel = QLabel(sample_text)
                slabel.setWordWrap(True)
                slabel.setStyleSheet(self._preview_sample_style)
                slabel.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                cell_layout.addWidget(slabel)
                sample_labels.append(slabel)

            description_cell.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            grid.addWidget(description_cell, grid_row, 2, Qt.AlignmentFlag.AlignTop)
            self._preview_labels[area_id] = sample_labels

            # The screenshot has its own wide column; clicking still opens the
            # original full-size image in AreaPreviewThumb's popup.
            thumb = AreaPreviewThumb(area_id)
            thumb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(thumb, grid_row, 3, Qt.AlignmentFlag.AlignTop)
            self._preview_thumbs[area_id] = thumb
            grid_row += 1

        self._style_table_chrome(theme)
        layout.addLayout(grid)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reset_btn = QPushButton("Reset All")
        reset_btn.setMinimumWidth(120)
        reset_btn.setStyleSheet(get_secondary_button_style())
        reset_btn.clicked.connect(self._on_reset_all)
        btn_row.addWidget(reset_btn)

        apply_btn = QPushButton("Apply")
        self._font_apply_btn = apply_btn  # identity for refresh_theme (INV-3)
        apply_btn.setMinimumWidth(120)
        apply_btn.setStyleSheet(get_primary_button_style())
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        btn_row.setContentsMargins(24, 8, 24, 16)
        outer.addLayout(btn_row)

    def _style_shortcuts_frame(self, theme):
        self._shortcuts_frame.setStyleSheet(
            f"QFrame {{ background-color: {theme['secondary']}; "
            f"border: 1px solid {theme['secondary_dark']}; border-radius: 6px; }}"
            "QFrame QFrame { background: transparent; border: none; }"
        )

    def _style_table_chrome(self, theme):
        header_style = (
            f"color: {theme['primary_text']}; background-color: {theme['secondary']}; "
            f"border-bottom: 1px solid {theme['secondary_dark']}; "
            f"font-size: {scaled_area_px('status')}px; font-weight: bold; "
            "padding: 7px 10px;"
        )
        for header in self._column_headers.values():
            header.setStyleSheet(header_style)
        group_style = (
            f"color: {theme['primary']}; background-color: {theme['secondary_dark']}; "
            f"font-size: {scaled_area_px('status')}px; font-weight: bold; "
            "padding: 6px 10px;"
        )
        for label in self._group_labels:
            label.setStyleSheet(group_style)
        restore_style = (
            f"QPushButton {{ color: {theme['primary']}; background: transparent; "
            f"border: none; padding: 0px; font-size: {scaled_area_px('status')}px; }}"
            f"QPushButton:hover {{ color: {theme['primary_light']}; }}"
        )
        for button in self._restore_buttons:
            button.setStyleSheet(restore_style)
        thumb_style = (
            f"background-color: {theme['secondary_dark']}; border: 1px solid "
            f"{theme['secondary_dark']}; padding: 8px;"
        )
        for thumb in self._preview_thumbs.values():
            thumb.setStyleSheet(thumb_style)

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
        self._sync_preset_highlight()
        self._update_preview()

    def _restore_area(self, area_id: str):
        self._spinboxes[area_id].setValue(AREA_DEFAULTS.get(area_id, 11))

    @_page_sync.page_apply
    def _on_apply(self):
        for area_id, _ in self._AREA_LABELS:
            value = self._spinboxes[area_id].value()
            key = f"display.fonts.{area_id}"
            get_settings().set(key, value)
            # the size kept: an area the user did not change keeps a size
            # set outside the page (AI setting redesign item 4)
            set_area_font_size(area_id, get_settings().get(key, value))
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
        # F-A1 (G5): commit the reset like _apply_preset does. Without this the
        # spinboxes show the defaults but nothing is persisted or broadcast, so
        # the reset is silently lost if the user does not also click Apply (and
        # the live surfaces never refresh). Reset All is a commit, not a preview.
        self._on_apply()

    def _update_master(self):
        values = [s.value() for s in self._spinboxes.values()]
        if len(set(values)) == 1:
            self._master_spin.set_mixed(False)
            self._master_spin.blockSignals(True)
            self._master_spin.setValue(values[0])
            self._master_spin.blockSignals(False)
        else:
            self._master_spin.set_mixed(True)
        self._sync_preset_highlight()

    def _matched_preset_key(self):
        for key, preset in self._RESOLUTION_PRESETS.items():
            if all(
                self._spinboxes[area_id].value() == value
                for area_id, value in preset["values"].items()
            ):
                return key
        return None

    def _sync_preset_highlight(self):
        self._active_preset = self._matched_preset_key()
        theme = get_theme_colors()
        for key, button in self._preset_buttons.items():
            self._style_preset_button(button, key == self._active_preset, theme)

    def _update_preview(self):
        from ui.qt_theme import get_scale_factor
        sf = get_scale_factor()
        for area_id, sample_labels in self._preview_labels.items():
            base = self._spinboxes[area_id].value()
            px = max(5, int(base * sf))
            self._shown_labels[area_id].setText(f"Shown at {px} px")
            for slabel in sample_labels:
                slabel.setStyleSheet(
                    f"{self._preview_sample_style} font-size: {px}px;"
                )

    def _apply_preset(self, preset_key):
        preset = self._RESOLUTION_PRESETS[preset_key]
        for area_id, value in preset["values"].items():
            spin = self._spinboxes.get(area_id)
            if spin:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self._update_master()
        self._on_apply()

    @staticmethod
    def _style_preset_button(btn, is_active, theme):
        # F-B2 (G3): keep the preset buttons on the live buttons-area font size
        # instead of letting qt-material freeze them at its 13px default.
        _fs = scaled_area_px('buttons')
        btn.setChecked(is_active)
        if is_active:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme['primary']}; "
                f"color: {on_accent_ink(theme['primary'], theme['primary_text'])}; border: none; "
                f"border-radius: 3px; padding: 4px 8px; font-weight: bold; "
                f"font-size: {_fs}px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme['secondary']}; "
                f"color: {theme['secondary_text']}; border: 1px solid {theme['secondary_dark']}; "
                f"border-radius: 3px; padding: 4px 8px; font-size: {_fs}px; }}"
                f"QPushButton:hover {{ background-color: {theme['secondary_light']}; }}"
            )

    def refresh_theme(self):
        theme = get_theme_colors()
        self._header_label.setStyleSheet(
            f"color: {theme['primary']}; font-weight: bold; "
            f"font-size: {scaled_area_px('panel_titles')}px; "
            f"padding-bottom: 8px;"
        )
        # F-B2 (G3): keep the font-size on the live refresh, else qt-material's
        # 13px default returns on a theme/preset change.
        self._master_label.setStyleSheet(
            f"color: {theme['primary_text']}; font-weight: bold; "
            f"font-size: {scaled_area_px('buttons')}px;"
        )
        self._preset_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-weight: bold; "
            f"font-size: {scaled_area_px('buttons')}px;"
        )
        self._hint_label.setStyleSheet(
            f"color: {theme['secondary_text']}; "
            f"font-size: {scaled_area_px('status')}px; padding-bottom: 10px;"
        )
        self._style_shortcuts_frame(theme)
        for lbl in self._area_labels:
            lbl.setStyleSheet(
                f"color: {theme['primary_text']}; "
                f"font-size: {scaled_area_px('buttons')}px;")
        # O-6 (QSpinBox family): replay the spinbox font-size on a live change.
        # F-B2 (G3): include the master spin, which the per-area loop below omits.
        for spin in (self._master_spin, *self._spinboxes.values()):
            spin.setStyleSheet(
                f"QSpinBox {{ font-size: {scaled_area_px('buttons')}px; }}")
        where_style = (
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; "
            f"padding: 0px; margin: 0px;"
        )
        for lbl in (*self._where_labels, *self._shown_labels.values(),
                    *self._default_labels):
            lbl.setStyleSheet(where_style)
        self._preview_sample_style = (
            f"color: {theme['primary_text']}; "
            f"background-color: {theme['secondary']}; "
            f"border: 1px solid {theme['secondary_dark']}; "
            f"border-radius: 3px; padding: 4px 8px;"
        )
        self._update_preview()
        preset_btn_set = set(self._preset_buttons.values())
        restore_btn_set = set(self._restore_buttons)
        for btn in self.findChildren(QPushButton):
            if btn in preset_btn_set or btn in restore_btn_set:
                continue
            if btn is getattr(self, "_font_apply_btn", None):
                btn.setStyleSheet(get_primary_button_style())
            else:
                btn.setStyleSheet(get_secondary_button_style())
        self._style_table_chrome(theme)
        active = self._active_preset
        for key, pbtn in self._preset_buttons.items():
            self._style_preset_button(pbtn, key == active, theme)


# =============================================================================
# CHART DISPLAY SECTION — View type, outer planets, rings, pies, cusp glow,
#                          default sub-tabs (SPEC-SET-001 s2.1 Lite-First)
# =============================================================================


class ChartDisplaySection(QWidget):
    """Chart view, outer planets, borders, rims, rings, pies, cusp glow,
    and default panel sub-tabs. Shared by both Lite and Pro settings."""

    chart_display_changed = Signal()

    # G8: the chart.* keys this section OWNS (writes on Apply). Reset uses this
    # allowlist so it cannot touch chart.* keys owned by other surfaces. Pinned
    # equal to what _apply_to_settings writes by test_g8_reset_cross_tab_isolation
    # — add a row that writes a new chart.* key and the test fails until it is
    # listed here; a foreign key can never enter because Apply never writes it.
    OWNED_CHART_KEYS = frozenset(
        k.split(".", 1)[1] for k in _rows.owned_keys("chart_display")
        if k.startswith("chart."))
    # Kept for the pin tests: the one owned chart.* key absent from DEFAULT_SETTINGS
    # until SPEC-SET-003; its default now comes from the registry like every other.
    OWNED_CHART_KEY_DEFAULTS = {"additional_bodies": _registry_default("chart.additional_bodies")}

    # td-iaqm.2.1: the display.* keys this section writes on Apply. Companion to
    # OWNED_CHART_KEYS, used by the Pro remote set_setting routing set so a remote
    # set of any Chart-Display-owned key fires _on_chart_display_changed exactly
    # like clicking Apply (Rule 24 harness parity). Pinned equal to what
    # _apply_to_settings writes by test_remote_display_routing — add a row that
    # writes a new display.* key and the pin fails until it is listed here.
    OWNED_DISPLAY_KEYS = frozenset(
        k.split(".", 1)[1] for k in _rows.owned_keys("chart_display")
        if k.startswith("display."))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.section_key = "chart"
        self._build_ui()
        self._read_from_settings()
        # AI setting redesign item 4. The view row has its own show rule.
        _page_sync.attach(self, self._read_from_settings,
                          _rows.owned_keys("chart_display") - {"chart.view_type"})

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
        # 4B: page-level Apply/Reset explanation, replacing the old persist note.
        info = QLabel("Changes take effect when you click Apply and are kept "
                      "across restarts. Reset to Default restores only the "
                      "settings on this page.")
        info.setWordWrap(True)
        _hint.style(info, 'info_text')
        _tag_font(info, 'info_text')
        form.addRow("", info)

        # ===== G9b 3C: "All views" group =====
        _group_header(form, "All views")

        # Finding 6 (td-v6nqc): the Nakshatra wheel joined the Core/Lite F2 ring
        # ([0,1,2,3,6], SPEC-NAK-LITE-001) but had no combo entry, so an F2 stop on
        # Nakshatra persisted chart.view_type="nakshatra" that this combo could not
        # represent — it silently showed "South Indian" and Apply clobbered the
        # stored value. Placed after Body Graph / before Cards of Truth (combo order
        # follows the F2 ring). Label matches the action-bar / tab wording already on
        # screen. The anti-clobber guard below still protects any OTHER view the combo
        # cannot represent (e.g. human_design when the build hides it, see below).
        # G9b-0 (td-v6nqc): Human Design can be a default chart view (Lorris's call).
        # Placed LAST — the two views OUTSIDE the F2 ring (cards_of_truth, human_design;
        # F2_RING_EXCLUDED_VIEWS) sit together at the end. Omitted when HD is hidden
        # (the Lite build / the "Hide Human Design" setting, ui.hide_human_design): the
        # entry would otherwise resolve through VIEW_STACK_INDEX to a page the build does
        # not present. A persisted chart.view_type="human_design" is then unrepresentable
        # and the Finding 6 anti-clobber guard below preserves it — never clobbered on
        # Apply unless the user actively picks a different entry. The combo reflects the
        # hide state at construction (HD visibility is a boot/restart-level setting).
        # SPEC-SET-003 W3e: values and labels come from the registry, in its order.
        self.view_combo = QComboBox()
        _hd_hidden = get_settings().get_hide_human_design()
        for _value, _label in _rows.choices("chart.view_type"):
            if _value == "human_design" and _hd_hidden:
                continue
            self.view_combo.addItem(_label, _value)
        self.view_combo.setMaximumWidth(220)
        _locked_row(
            form, "chart.view_type", _rows.label("chart.view_type"), self.view_combo,
            _rows.help_text("chart.view_type"),
        )

        # SPEC-SET-003 W3c: items, labels and row titles come from the registry.
        self.sign_display_combo = _rows.registry_combo("display.sign_display", max_width=260)
        _locked_row(form, "display.sign_display", _rows.label("display.sign_display"),
                    self.sign_display_combo,
                    _rows.help_text("display.sign_display"))
        from ui.sign_number_views_combo import SignNumberViewsCombo
        self.sign_number_views_combo = SignNumberViewsCombo()
        _locked_row(form, "display.sign_number_views", _rows.label("display.sign_number_views"),
                    self.sign_number_views_combo, _rows.help_text("display.sign_number_views"))

        # 2B: pointer to where the zodiac FRAME + name set are chosen (a calculation
        # choice that stays on Zodiac & Calculation, per Lorris's rule).
        sign_display_pointer = QLabel(
            "The zodiac frame and the Aditya or Western name set are chosen under "
            "Zodiac & Calculation.")
        sign_display_pointer.setWordWrap(True)
        _hint.style(sign_display_pointer, 'info_text')
        _tag_font(sign_display_pointer, 'info_text')
        form.addRow("", sign_display_pointer)
        # Finding 6 P3-b: track USER intent for the anti-clobber guard. `activated`
        # fires on every user selection INCLUDING re-picking the already-shown item
        # (currentIndexChanged does not) and NOT on programmatic setCurrentIndex, so
        # it is exactly "the user chose a view". A persisted view the combo cannot
        # represent is preserved until the user actually picks one.
        self.view_combo.activated.connect(self._on_view_activated)

        self.outer_planets_cb = QCheckBox()
        _rows.calculation_tooltip(self.outer_planets_cb, "chart.show_outer_planets")
        _locked_row(
            form, "chart.show_outer_planets", _rows.label("chart.show_outer_planets"), self.outer_planets_cb,
            _rows.help_text("chart.show_outer_planets"),
        )

        planet_label_widget = QWidget()
        planet_label_layout = QHBoxLayout(planet_label_widget)
        planet_label_layout.setContentsMargins(0, 0, 0, 0)
        planet_label_layout.setSpacing(12)
        # SPEC-PLM-001 v2: one radio per chart.planet_label value (F11 order).
        # O-6: font-size in QSS (text radio buttons).
        _rb_css = f"font-size: {scaled_area_px('buttons')}px;"
        self.planet_label_group = QButtonGroup()
        self.planet_label_rbs = {}
        for _i, _choice in enumerate(_registry_setting("chart.planet_label").choices):
            _rb = QRadioButton("Degrees (15°22')" if _choice.value == "degrees"
                               else _choice.label)
            _rb.setStyleSheet(_rb_css)
            _tag_font(_rb, 'buttons')
            self.planet_label_group.addButton(_rb, _i)
            planet_label_layout.addWidget(_rb)
            self.planet_label_rbs[_choice.value] = _rb
        planet_label_layout.addStretch()
        _locked_row(
            form, "chart.planet_label",
            _rows.label("chart.planet_label"), planet_label_widget,
            _rows.help_text("chart.planet_label"),
        )

        # ===== G9b 3C: "Wheel" group =====
        _group_header(form, "Wheel")
        # House display (MOVED from Zodiac & Calculation — a DRAWING choice per
        # Lorris's rule). Wheel-only (SPEC-WHD-001 §309); NO lock icon, so a plain
        # form row, not _locked_row.
        self.wheel_display_combo = _rows.registry_combo("chart.wheel_house_display")
        form.addRow(_form_label(_rows.label("chart.wheel_house_display")),
                    self.wheel_display_combo)
        wheel_display_desc = QLabel(
            "Standard Western layout starts the 1st house at the exact Ascendant "
            "degree.")
        wheel_display_desc.setWordWrap(True)
        _hint.style(wheel_display_desc, 'info_text')
        _tag_font(wheel_display_desc, 'info_text')
        form.addRow("", wheel_display_desc)

        self.cusp_glow_combo = _rows.registry_combo("chart.cusp_glow_mode")
        _locked_row(
            form, "chart.cusp_glow_mode", _rows.label("chart.cusp_glow_mode"),
            self.cusp_glow_combo,
            _rows.help_text("chart.cusp_glow_mode"),
        )

        self.element_pies_cb = QCheckBox()
        _locked_row(
            form, "chart.show_element_pies", _rows.label("chart.show_element_pies"), self.element_pies_cb,
            _rows.help_text("chart.show_element_pies"),
        )

        self.retinue_rings_cb = QCheckBox()
        _locked_row(
            form, "chart.show_retinue_rings", _rows.label("chart.show_retinue_rings"), self.retinue_rings_cb,
            _rows.help_text("chart.show_retinue_rings"),
        )

        # SPEC-RST-001 (td-9x5dr): lord strength on the retinue cells. Set once,
        # written on Apply; every chart host reads the four keys when it draws.
        self.retinue_strength_cb = QCheckBox()
        self.retinue_strength_source_combo = _rows.registry_combo("chart.retinue_strength_source")
        self.retinue_strength_amount_spin = QSpinBox()
        _low, _high = _registry_setting("chart.retinue_strength_amount").bounds
        self.retinue_strength_amount_spin.setRange(int(_low), int(_high))
        self.retinue_strength_amount_spin.setMaximumWidth(90)
        self.retinue_strength_light_spin = QSpinBox()      # td-9scg9 D-32: the V2 star light
        _low, _high = _registry_setting("chart.retinue_strength_light_amount").bounds
        self.retinue_strength_light_spin.setRange(int(_low), int(_high))
        self.retinue_strength_light_spin.setMaximumWidth(90)
        self.retinue_strength_sign_ribbon_cb = QCheckBox()
        self.retinue_strength_ribbon_style_combo = _rows.registry_combo(
            "chart.retinue_strength_ribbon_style")
        self.retinue_strength_sign_colour_cb = QCheckBox()
        for _key, _field in (("chart.retinue_strength_on", self.retinue_strength_cb),
                             ("chart.retinue_strength_source", self.retinue_strength_source_combo),
                             ("chart.retinue_strength_amount", self.retinue_strength_amount_spin),
                             ("chart.retinue_strength_light_amount", self.retinue_strength_light_spin),
                             ("chart.retinue_strength_sign_ribbon",
                              self.retinue_strength_sign_ribbon_cb),
                             ("chart.retinue_strength_ribbon_style",
                              self.retinue_strength_ribbon_style_combo),
                             ("chart.retinue_strength_sign_colour",
                              self.retinue_strength_sign_colour_cb)):
            _locked_row(form, _key, _rows.label(_key), _field, _rows.help_text(_key))
        # td-e6jsp (SPEC-RST-001 D-21): the PLANET key of the Strength table. Strength
        # needs the strength display: choosing it ticks the box (DUC Bala when the
        # box was off); unticking the box sets Manual.
        self.planet_glow_combo = _rows.registry_combo("chart.planet_glow_mode")
        _locked_row(form, "chart.planet_glow_mode", _rows.label("chart.planet_glow_mode"),
                    self.planet_glow_combo, _rows.help_text("chart.planet_glow_mode"))
        self.planet_glow_combo.activated.connect(self._planet_glow_picked)
        # td-m79zy / td-jr6cd (SPEC-EXCH-002 4.5): the exchange chains (on by
        # default, the THREAD key is the quick toggle) and their link style
        self.exchange_chain_cb = QCheckBox()
        _locked_row(form, "chart.exchange_chain_on", _rows.label("chart.exchange_chain_on"),
                    self.exchange_chain_cb, _rows.help_text("chart.exchange_chain_on"))
        self.exchange_chain_cb.clicked.connect(self._on_exchange_chain_clicked)
        _s = get_settings()          # the THREAD key writes it too: follow it live
        _s.on_changed("chart.exchange_chain_on", self._exchange_chain_written)
        self.destroyed.connect(lambda *_, s=_s, f=self._exchange_chain_written:
                               s.remove_on_changed("chart.exchange_chain_on", f))
        self.exchange_chain_style_combo = _rows.registry_combo("chart.exchange_chain_style")
        _locked_row(form, "chart.exchange_chain_style", _rows.label("chart.exchange_chain_style"),
                    self.exchange_chain_style_combo, _rows.help_text("chart.exchange_chain_style"))
        # SPEC-TJK-003 §4.5: the Tajika aspects in the South Indian centre (the rows of
        # SPEC-VAC-001 §4.0). The panel's toggle and virupa rail write both keys too, so
        # the rows follow them live.
        _center = self._center_drawing_rows("tajika")
        _center.build(self, form, _s)
        self.tajika_center_cb, self.tajika_center_spin = _center.cb, _center.spin
        self._center_drawing_rows("vedic").build(self, form, _s)     # SPEC-VAC-001 §4.5
        self.aspect_tour_spin = QDoubleSpinBox()      # §4.9 D-9: seconds per aspect of the Tour
        _low, _high = _registry_setting("chart.aspect_tour_seconds").bounds
        self.aspect_tour_spin.setRange(float(_low), float(_high))
        self.aspect_tour_spin.setSingleStep(0.5)
        self.aspect_tour_spin.setDecimals(2)          # 1.25 s stays 1.25 on Apply
        self.aspect_tour_spin.setSuffix(" s")
        self.aspect_tour_spin.setMaximumWidth(90)
        _locked_row(form, "chart.aspect_tour_seconds", _rows.label("chart.aspect_tour_seconds"),
                    self.aspect_tour_spin, _rows.help_text("chart.aspect_tour_seconds"))
        self.center_degrees_cb = QCheckBox()          # SPEC-VAC-001 §4.0: the degree ruler
        _locked_row(form, "chart.center_degree_numbers", _rows.label("chart.center_degree_numbers"),
                    self.center_degrees_cb, _rows.help_text("chart.center_degree_numbers"))
        self.retinue_strength_cb.clicked.connect(self._retinue_strength_clicked)

        # House number size moved to Font Sizes > House Numbers
        # (display.fonts.house_numbers, 2026-10-08); no control here.

        # ===== G9b 3C: "South Indian" group =====
        _group_header(form, "South Indian")
        # SPEC-SIC-002 §4.7: stored VALUES stay "classic"/"vector"; only the labels
        # changed. Written to display.south_indian_style on Apply; chart_display_
        # changed reaches core_gui_qt._on_chart_display_changed (D-13, syncs every
        # live South Indian host). G9a greying (_sync_wood_controls) preserved.
        self.si_theme_combo = _rows.registry_combo("display.south_indian_style")
        _locked_row(
            form, "display.south_indian_style", _rows.label("display.south_indian_style"),
            self.si_theme_combo,
            _rows.help_text("display.south_indian_style"),
        )

        self.si_finish_combo = _rows.registry_combo("display.south_indian_vector_finish",
                                                    max_width=260)
        _locked_row(form, "display.south_indian_vector_finish",
                    _rows.label("display.south_indian_vector_finish"),
                    self.si_finish_combo, _rows.help_text("display.south_indian_vector_finish"))
        # G9a (Finding 3B): the SI theme/finish rows only affect a South Indian
        # view, so gate their enablement on the Chart view too.
        self.si_theme_combo.currentIndexChanged.connect(self._sync_wood_controls)
        self.si_finish_combo.currentIndexChanged.connect(self._sync_wood_controls)
        self.view_combo.currentIndexChanged.connect(self._sync_wood_controls)

        # ===== G9b 3C: "Body Graph" group =====
        _group_header(form, "Body Graph")
        # SPEC-BODY-002: rashi aspect system for the Body Graph aspect panel.
        self.rashi_aspect_combo = _rows.registry_combo("chart.rashi_aspect_system")
        _locked_row(
            form, "chart.rashi_aspect_system",
            _rows.label("chart.rashi_aspect_system"), self.rashi_aspect_combo,
            _rows.help_text("chart.rashi_aspect_system"),
        )

        # ===== G9b 3C: "Dates" group (MOVED from Zodiac & Calculation) =====
        _group_header(form, "Dates")
        # SPEC-CAL-001: calendar convention for DISPLAYING pre-1582 dates.
        # Display-only; never changes any JD, chart or stored file.
        self.hist_dates_combo = _rows.registry_combo("display.calendar_convention", max_width=320)
        _locked_row(form, "display.calendar_convention",
                    _rows.label("display.calendar_convention"), self.hist_dates_combo)
        hist_desc = QLabel(
            "How dates before the 1582 Gregorian reform are DISPLAYED. "
            "Astronomy standard uses the Julian calendar (matches NASA/Swiss "
            "Ephemeris); Proleptic Gregorian extends today's calendar backwards "
            "(matches Kala). Display-only: planetary positions are identical "
            "either way. Dates from Oct 1582 onward look the same in both."
        )
        hist_desc.setWordWrap(True)
        _hint.style(hist_desc, 'info_text')
        _tag_font(hist_desc, 'info_text')
        form.addRow("", hist_desc)

        self.date_format_combo = _rows.registry_combo("display.date_format", max_width=320)
        _locked_row(form, "display.date_format", _rows.label("display.date_format"),
                    self.date_format_combo)
        date_fmt_desc = QLabel(
            "The numeric date order shown in the Vedanga, Vimshottari, Planetary "
            "Ages and Zodiacal Releasing lists. Display-only: the age column and "
            "AI reading derive from the exact instant, not this text."
        )
        date_fmt_desc.setWordWrap(True)
        _hint.style(date_fmt_desc, 'info_text')
        _tag_font(date_fmt_desc, 'info_text')
        form.addRow("", date_fmt_desc)

        panel_header = QLabel("Default sub-tabs (Chart tab)")
        # O-6: font-size in QSS.
        panel_header.setStyleSheet(
            f"font-weight: bold; margin-top: 8px; "
            f"font-size: {scaled_area_px('panel_titles')}px;")
        _tag_font(panel_header, 'panel_titles')
        form.addRow("", panel_header)

        panel_desc = QLabel(
            "Choose which sub-tab each Chart-tab panel opens on at launch. "
            "Lock a panel to always start on the chosen tab. Unlocked, it "
            "remembers the last tab you used."
        )
        panel_desc.setWordWrap(True)
        _hint.style(panel_desc, 'info_text', 'margin-bottom:4px;')
        _tag_font(panel_desc, 'info_text')
        form.addRow("", panel_desc)

        self.karakas_radio = _locked_radio_group(
            form, "ui.panel.karakas_tab", _rows.label("ui.panel.karakas_tab"),
            _rows.radio_options("ui.panel.karakas_tab"),
        )

        self.strength_radio = _locked_radio_group(
            form, "ui.panel.strength_tab", _rows.label("ui.panel.strength_tab"),
            _rows.radio_options("ui.panel.strength_tab"),
        )

        self.aspects_radio = _locked_radio_group(
            form, ["ui.panel.aspects_mode", "ui.panel.aspects_tab"], _rows.label("ui.panel.aspects_mode"),
            [
                ("Aspects (Vedic)", 0), ("Avastha", 1), ("Shame", 2), ("Exchange", 3),
                ("Aspects (Tajika)", 4), ("Relations", 5), ("Yogas", 6), ("Nabhasa", 7),
            ],
        )

        # ===== Rarely changed appearance details, kept at the bottom (Lorris
        # 2026-09-24): everyday choices above, fine-tuning below. =====
        _group_header(form, "Advanced appearance")
        self.sign_shadows_cb = QCheckBox()
        _locked_row(
            form, "chart_display.element_shadows.enabled",
            "Sign glyph/icon shadows:", self.sign_shadows_cb,
            "Add element-coloured shadows to Josh glyphs and zodiac icons in "
            "every supported chart view. Planet shadows are controlled separately.",
        )
        shadow_size_field = QWidget()
        shadow_size_row = QHBoxLayout(shadow_size_field)
        shadow_size_row.setContentsMargins(0, 0, 0, 0)
        self.sign_shadow_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.sign_shadow_size_slider.setRange(0, 12)
        self.sign_shadow_size_slider.setSingleStep(1)
        self.sign_shadow_size_value_label = QLabel("6 px")
        self.sign_shadow_size_value_label.setStyleSheet(
            f"font-size: {scaled_area_px('buttons')}px;")
        _tag_font(self.sign_shadow_size_value_label, 'buttons')
        shadow_size_row.addWidget(self.sign_shadow_size_slider, 1)
        shadow_size_row.addWidget(self.sign_shadow_size_value_label)
        self.sign_shadow_size_slider.valueChanged.connect(
            lambda value: self.sign_shadow_size_value_label.setText(f"{value} px"))
        _locked_row(
            form, "chart_display.element_shadows.blur_radius",
            "Sign shadow size:", shadow_size_field,
            "Increase or decrease the glyph and zodiac-icon shadow footprint.")

        from libaditya.optional_bodies import BODIES
        self.additional_body_checks = {}
        for body in BODIES:
            checkbox = QCheckBox(body.label)
            # O-6: own-QSS font-size so the checkbox tracks the 'buttons' area
            # instead of freezing at the universal qt-material 13px.
            checkbox.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
            _tag_font(checkbox, 'buttons')
            _rows.calculation_tooltip(checkbox, "chart.additional_bodies", note='Show in chart views. Unavailable dates are reported on the chart.')
            self.additional_body_checks[body.name] = checkbox
            form.addRow(
                _form_label('Additional bodies:') if len(self.additional_body_checks) == 1 else '',
                checkbox)
        # Appearance only: independent of which bodies are shown above.
        self.additional_body_icon_combo = _rows.registry_combo("display.additional_body_icon_set")
        _locked_row(form, "display.additional_body_icon_set",
                    _rows.label("display.additional_body_icon_set"),
                    self.additional_body_icon_combo)

        self.planet_icon_combo = _rows.registry_combo("display.planet_icon_set")
        # G9d (td-q43fm): cap the width like every sibling combo. G6 added the wide
        # planet_icon_colors editor to this same QFormLayout column below, which
        # stretched the field column; without a cap this combo grew to the full page
        # width (2K capture) while every other combo stayed ~220px.
        # (registry_combo applies that 220 px cap)
        _locked_row(form, "display.planet_icon_set", _rows.label("display.planet_icon_set"),
                    self.planet_icon_combo)
        from apps.widgets.planet_icon_colors import PlanetIconColors
        self.planet_icon_colors = PlanetIconColors()
        form.addRow(_form_label('SVG colors:'), self.planet_icon_colors)

    def _sync_wood_controls(self, *_):
        # G9a (Finding 3B): the South-Indian theme + vector-finish rows do nothing
        # on a non-South-Indian view, so DISABLE (not hide — keep them discoverable)
        # both when the Chart view is not South Indian. The existing finish-follows-
        # theme gating is preserved: finish is enabled only on a South Indian view
        # AND a vector theme.
        is_si = self.view_combo.currentData() == 'south_indian'
        vector = self.si_theme_combo.currentData() == 'vector'
        self.si_theme_combo.setEnabled(is_si)
        self.si_finish_combo.setEnabled(is_si and vector)
        # Disabled-row tooltip (why it is greyed) — placeholder-gated so nothing
        # visible ships until the orchestrator's copy lands.
        tip = "" if (is_si or _si_scope_tooltip_pending()) else _SI_SCOPE_TOOLTIP
        self.si_theme_combo.setToolTip(tip)
        self.si_finish_combo.setToolTip(tip)

    def showEvent(self, event):
        # Re-read the chart view each time the page is shown, so the combo shows
        # the view actually on screen (it changes from the Chart tab), unless the
        # user already picked one here and has not applied it yet.
        super().showEvent(event)
        if not getattr(self, "_view_user_touched", False):
            idx = self.view_combo.findData(_rows.saved(get_settings(), "chart.view_type"))
            self._view_representable = idx >= 0
            if idx >= 0 and idx != self.view_combo.currentIndex():
                self.view_combo.setCurrentIndex(idx)

    def _on_exchange_chain_clicked(self, *_):
        # SPEC-EXCH-002 4.5: a user click is intent; until Apply, a THREAD write keeps it.
        self._exchange_chain_touched = True

    def _center_drawing_rows(self, kind):
        """The Chart Display rows of a center drawing (SPEC-VAC-001 §4.0), one per kind."""
        found = getattr(self, "_center_rows", None)
        if found is None:
            found = self._center_rows = {}
        if kind not in found:
            found[kind] = _CenterDrawingRows(kind)
        return found[kind]

    def _exchange_chain_written(self, _key, value):
        import shiboken6
        if shiboken6.isValid(self.exchange_chain_cb) and not getattr(self, "_exchange_chain_touched", False):
            self.exchange_chain_cb.setChecked(bool(value))

    def _on_view_activated(self, *_):
        # Finding 6 P3-b: a user selection (even re-picking the item already shown)
        # is intent to set that view; the anti-clobber guard then writes it on Apply.
        self._view_user_touched = True

    def _read_from_settings(self):
        s = get_settings()

        # Finding 6 (td-v6nqc): remember whether the combo can represent the stored
        # view AND what it is showing after load, so Apply never clobbers a persisted
        # view the combo cannot show (e.g. human_design). If findData < 0 the combo
        # keeps its fallback selection; the guard in _apply_to_settings preserves the
        # real value unless the user actively picks a different entry.
        stored_view = _rows.saved(s, "chart.view_type")
        idx = self.view_combo.findData(stored_view)
        self._view_representable = idx >= 0
        # Fresh load = no user intent yet; a programmatic setCurrentIndex below does
        # not fire `activated`, so this stays False until the user picks a view.
        self._view_user_touched = False
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)

        si_idx = self.si_theme_combo.findData(
            _rows.saved(s, "display.south_indian_style"))
        self.si_theme_combo.setCurrentIndex(si_idx if si_idx >= 0 else 0)
        from ui.south_indian_finishes import normalize_finish, normalize_sign_display
        self.si_finish_combo.setCurrentIndex(self.si_finish_combo.findData(
            normalize_finish(_rows.saved(s, "display.south_indian_vector_finish"))))
        self.sign_display_combo.setCurrentIndex(self.sign_display_combo.findData(
            normalize_sign_display(_rows.saved(s, "display.sign_display"))))
        self.sign_number_views_combo.set_views(_rows.saved(s, "display.sign_number_views"))
        element_shadows = s.get_chart_display_section('element_shadows')
        self.sign_shadows_cb.setChecked(bool(element_shadows.get('enabled', True)))
        self.sign_shadow_size_slider.setValue(int(clamp_sign_shadow_size(
            element_shadows.get('blur_radius'), 6)))
        self.sign_shadow_size_value_label.setText(
            f"{self.sign_shadow_size_slider.value()} px")
        self._sync_wood_controls()

        self.outer_planets_cb.setChecked(_rows.saved(s, "chart.show_outer_planets"))
        selected = _rows.saved(s, "chart.additional_bodies")
        for name, checkbox in self.additional_body_checks.items():
            checkbox.setChecked(isinstance(selected, list) and name in selected)
        icon_idx = self.additional_body_icon_combo.findData(
            _rows.saved(s, "display.additional_body_icon_set"))
        self.additional_body_icon_combo.setCurrentIndex(max(icon_idx, 0))
        self.planet_icon_combo.setCurrentIndex(max(0, self.planet_icon_combo.findData(
            _rows.saved(s, "display.planet_icon_set"))))
        self.planet_icon_colors.load(_rows.saved(s, "display.planet_svg_colors"))
        from core.planet_label import saved_mode
        self.planet_label_rbs[saved_mode(lambda k, d=None: _rows.saved(s, k))].setChecked(True)
        self.retinue_rings_cb.setChecked(_rows.saved(s, "chart.show_retinue_rings"))
        self.center_degrees_cb.setChecked(bool(_rows.saved(s, "chart.center_degree_numbers")))
        self.retinue_strength_cb.setChecked(_rows.saved(s, "chart.retinue_strength_on"))
        _rows.select_data(self.retinue_strength_source_combo,
                          _rows.saved(s, "chart.retinue_strength_source"))
        self.retinue_strength_amount_spin.setValue(int(_rows.saved(s, "chart.retinue_strength_amount")))
        self.retinue_strength_light_spin.setValue(int(_rows.saved(s, "chart.retinue_strength_light_amount")))
        self.retinue_strength_sign_ribbon_cb.setChecked(
            _rows.saved(s, "chart.retinue_strength_sign_ribbon"))
        _rows.select_data(self.retinue_strength_ribbon_style_combo,
                          _rows.saved(s, "chart.retinue_strength_ribbon_style"))
        self.retinue_strength_sign_colour_cb.setChecked(
            _rows.saved(s, "chart.retinue_strength_sign_colour"))
        _rows.select_data(self.planet_glow_combo, _rows.saved(s, "chart.planet_glow_mode"))
        self.exchange_chain_cb.setChecked(_rows.saved(s, "chart.exchange_chain_on"))
        for _kind in _CenterDrawingRows.KEYS:
            self._center_drawing_rows(_kind).load(s)
        _tour = _rows.saved(s, "chart.aspect_tour_seconds")     # a bad stored value: the default
        self.aspect_tour_spin.setValue(float(_tour if _registry_valid("chart.aspect_tour_seconds", _tour)
                                             else _registry_default("chart.aspect_tour_seconds")))
        self._exchange_chain_touched = False
        _rows.select_data(self.exchange_chain_style_combo,
                          _rows.saved(s, "chart.exchange_chain_style"))
        self.element_pies_cb.setChecked(_rows.saved(s, "chart.show_element_pies"))

        glow = _rows.saved(s, "chart.cusp_glow_mode")
        idx = self.cusp_glow_combo.findData(glow)
        if idx >= 0:
            self.cusp_glow_combo.setCurrentIndex(idx)

        aspect_idx = self.rashi_aspect_combo.findData(
            _rows.saved(s, "chart.rashi_aspect_system"))
        if aspect_idx >= 0:
            self.rashi_aspect_combo.setCurrentIndex(aspect_idx)

        # G9b (td-v6nqc): the three rows moved here from Zodiac & Calculation.
        for combo, key in (
            (self.wheel_display_combo, "chart.wheel_house_display"),
            (self.hist_dates_combo, "display.calendar_convention"),
            (self.date_format_combo, "display.date_format"),
        ):
            _idx = combo.findData(_rows.saved(s, key))
            combo.setCurrentIndex(_idx if _idx >= 0 else 0)

        self._select_radio_value(self.karakas_radio, _rows.saved(s, "ui.panel.karakas_tab"))
        self._select_radio_value(self.strength_radio, _rows.saved(s, "ui.panel.strength_tab"))
        aspects_idx = _aspects_to_radio(
            _rows.saved(s, "ui.panel.aspects_mode"),
            _rows.saved(s, "ui.panel.aspects_tab"),
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

    # SPEC-SET-003 §4.6 (W5-fix2 P2): the writes and the window's adoption tail
    # (chart_display_changed, connected directly) publish ONE completed live
    # frame; no tool reads a frame mixing new store values with old views.
    # W5-fix3 P2: a write that raises part-way still runs the tail (reconcile),
    # so the views adopt what was written and the published frame is the one
    # on screen; the error is re-raised.
    # W5-fix4 P2: the tail's outcome is its slots' result, not the emit's
    # return (Qt swallows a slot's exception): emit_adoption raises
    # AdoptionFailed when a slot failed, so the batch retries the tail and, if
    # it fails again, holds the published frame at the last adopted one.
    def _adopt_chart_display(self):
        emit_adoption(self.chart_display_changed, "chart display tail")

    # The live keys the window's chart display tail (apply_chart_display_settings)
    # makes the views re-read: what this page owns, plus the runtime South Indian
    # ruler toggle the tail applies with the retinue rings. Only these are
    # released from a hold when the tail completes (W5-fix4 P2).
    ADOPTED_KEYS = frozenset(_rows.owned_keys("chart_display")) | {
        "chart.show_trimsamsha_degrees"}

    def _planet_glow_picked(self, _index=None):
        """Strength needs a strength key: tick the box, DUC Bala when it was off.
        Dignity is exclusive with the strength display (td-m6xyo): untick it."""
        if self.planet_glow_combo.currentData() == "strength" and not self.retinue_strength_cb.isChecked():
            self.retinue_strength_cb.setChecked(True)
            _rows.select_data(self.retinue_strength_source_combo, "duc")
        elif self.planet_glow_combo.currentData() == "dignity" and self.retinue_strength_cb.isChecked():
            self.retinue_strength_cb.setChecked(False)

    def _retinue_strength_clicked(self, checked):
        """The strength display off takes the planet glow back to Manual; on, it
        leaves Dignity (td-m6xyo, exclusive)."""
        if not checked and self.planet_glow_combo.currentData() == "strength":
            _rows.select_data(self.planet_glow_combo, "manual")
        elif checked and self.planet_glow_combo.currentData() == "dignity":
            _rows.select_data(self.planet_glow_combo, "manual")

    @_page_sync.page_apply
    @batched_publication(reconcile=_adopt_chart_display, owns=ADOPTED_KEYS)
    def _apply_to_settings(self):
        s = get_settings()
        # Finding 6 (td-v6nqc) anti-clobber guard: only write chart.view_type when
        # the combo could represent the stored value (so currentData is the real
        # view), OR the user actively changed the selection since load. Otherwise a
        # persisted view the combo cannot show (human_design today, any future view)
        # would be silently overwritten by the combo's fallback selection on Apply.
        # Only an ACTIVE pick writes the view. The combo is read when the page is
        # built, while the main window keeps chart.view_type current on every F2 /
        # action-bar / HD-button change; writing an untouched combo put back the
        # view shown at load time, and _on_chart_display_changed then switched the
        # chart to it (e.g. back to Human Design after changing the SI finish).
        cur_view = self.view_combo.currentData()
        if getattr(self, "_view_user_touched", False):
            s.set("chart.view_type", cur_view)
            self._view_user_touched = False
        s.set("display.south_indian_style", self.si_theme_combo.currentData())
        s.set("display.south_indian_vector_finish", self.si_finish_combo.currentData())
        s.set("display.sign_display", self.sign_display_combo.currentData())
        s.set("display.sign_number_views", self.sign_number_views_combo.views())
        element_shadows = dict(s.get_chart_display_section('element_shadows'))
        element_shadows['enabled'] = self.sign_shadows_cb.isChecked()
        element_shadows['blur_radius'] = self.sign_shadow_size_slider.value()
        s.set_chart_display_section('element_shadows', element_shadows)
        s.set("chart.show_outer_planets", self.outer_planets_cb.isChecked())
        s.set('chart.additional_bodies', [name for name, checkbox in
              self.additional_body_checks.items() if checkbox.isChecked()])
        s.set('display.additional_body_icon_set', self.additional_body_icon_combo.currentData())
        s.set('display.planet_icon_set', self.planet_icon_combo.currentData())
        s.set('display.planet_svg_colors', dict(self.planet_icon_colors.colors))
        s.set("chart.planet_label", next(
            m for m, rb in self.planet_label_rbs.items() if rb.isChecked()))
        s.set("chart.show_planet_names", False)   # legacy flag, moved to the key above
        s.set("chart.show_retinue_rings", self.retinue_rings_cb.isChecked())
        s.set("chart.retinue_strength_on", self.retinue_strength_cb.isChecked())
        s.set("chart.retinue_strength_source", self.retinue_strength_source_combo.currentData())
        s.set("chart.retinue_strength_amount", self.retinue_strength_amount_spin.value())
        s.set("chart.retinue_strength_light_amount", self.retinue_strength_light_spin.value())
        s.set("chart.retinue_strength_sign_ribbon", self.retinue_strength_sign_ribbon_cb.isChecked())
        s.set("chart.retinue_strength_sign_colour", self.retinue_strength_sign_colour_cb.isChecked())
        s.set("chart.retinue_strength_ribbon_style",
              self.retinue_strength_ribbon_style_combo.currentData())
        s.set("chart.planet_glow_mode", self.planet_glow_combo.currentData())
        s.set("chart.exchange_chain_on", self.exchange_chain_cb.isChecked())
        self._exchange_chain_touched = False
        s.set("chart.exchange_chain_style", self.exchange_chain_style_combo.currentData())
        for _kind in _CenterDrawingRows.KEYS:
            self._center_drawing_rows(_kind).apply(s)
        s.set("chart.aspect_tour_seconds", self.aspect_tour_spin.value())
        s.set("chart.center_degree_numbers", self.center_degrees_cb.isChecked())
        s.set("chart.show_element_pies", self.element_pies_cb.isChecked())
        s.set("chart.cusp_glow_mode", self.cusp_glow_combo.currentData())
        s.set("chart.rashi_aspect_system", self.rashi_aspect_combo.currentData())

        # G9b (td-v6nqc): the three rows moved here from Zodiac & Calculation.
        # wheel_house_display applies live via chart_display_changed ->
        # _on_chart_display_changed (which reads it); calendar_convention fires its
        # own display-only subscribers (title bar, eclipse tables). set() fires the
        # key-prefix callbacks so live hosts re-render without a chart recompute.
        s.set("chart.wheel_house_display", self.wheel_display_combo.currentData())
        s.set("display.calendar_convention", self.hist_dates_combo.currentData())
        # date_format is DISPLAY-ONLY; only write when it actually changed so an
        # Apply that leaves it untouched does not fire the DashaManager relist.
        _new_date_format = self.date_format_combo.currentData()
        if _new_date_format != _rows.saved(s, "display.date_format"):
            s.set("display.date_format", _new_date_format)

        s.set("ui.panel.karakas_tab", self._radio_value(self.karakas_radio, 0))
        s.set("ui.panel.strength_tab", self._radio_value(self.strength_radio, 0))
        aspects_idx = self.aspects_radio.checkedId()
        if aspects_idx < 0:
            aspects_idx = 0
        a_mode, a_tab = ASPECTS_RADIO[aspects_idx]
        s.set("ui.panel.aspects_mode", a_mode)
        s.set("ui.panel.aspects_tab", a_tab)

        # td-iaqm.2.1: the icon-view repaint moved into the window's shared
        # apply_chart_display_settings() tail (connected to this signal), so both
        # Apply and the remote path refresh icons identically. Just fire the signal
        # (with its outcome: a failing slot fails the Apply, W5-fix4).
        self._adopt_chart_display()

    @_page_sync.page_write
    @batched_publication(reconcile=_adopt_chart_display,     # as Apply (W5-fix2/3/4)
                         owns=ADOPTED_KEYS)
    def _on_reset(self):
        from copy import deepcopy
        from managers.settings_manager import DEFAULT_CHART_DISPLAY
        s = get_settings()
        # G8: reset ONLY the chart.* keys this section owns (allowlist), never the
        # whole "chart" namespace. reset_to_defaults("chart") REPLACES the section
        # and would clobber keys owned elsewhere — the live chart UI state
        # chart.show_aspect_panel / chart.aspect_split_fraction (Body-Graph
        # aspect panel + splitter) / chart.show_trimsamsha_degrees (SI vector
        # toggle). (G9b: chart.wheel_house_display moved INTO this section's
        # allowlist — it is now owned here, not by Zodiac & Calculation.)
        # OWNED_CHART_KEYS is pinned to what _apply_to_settings writes
        # (test_g8_reset_cross_tab_isolation), so a new row cannot silently fall
        # out of Reset and a foreign key can never enter. One set() per key =
        # each subscriber fires once, no reset-then-restore flicker.
        # SPEC-SET-003 W3c: one set() per key of the registry's chart_display section
        # (the chart.*, display.* and ui.panel.* keys this page hosts), each a deep
        # copy of the registry default. The two typed chart_display sections keep
        # their own reset (they are not in the section's leaf keys).
        _rows.reset_section(s, "chart_display")
        s.set_chart_display_section(
            'element_shadows', deepcopy(DEFAULT_CHART_DISPLAY['element_shadows']))
        self._read_from_settings()
        # Reset must propagate to live hosts the same way Apply does
        # (SPEC-SIC-002 D-13: e.g. SI theme back to classic without waiting
        # for a later Apply or restart). The icon-view repaint rides the shared
        # apply_chart_display_settings() tail connected to this signal (td-iaqm.2.1).
        self._adopt_chart_display()

    def refresh_theme(self):
        self._reset_btn.setStyleSheet(get_secondary_button_style())
        self._apply_btn.setStyleSheet(get_primary_button_style())
        # td-c038: re-compose tagged migrated font-sizes from the live setting.
        _replay_fonts(self)


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
    saturation_changed = Signal(int)  # SPEC-SAT-001
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
        self.current_theme = current_theme or default_theme_file()
        from state.user_data import get_settings_path
        self.settings_path = get_settings_path()
        self._setup_ui()
        # Mouse wheel scrolls the page, never edits a dropdown/number/slider.
        from ui.settings_wheel_guard import guard as _guard_wheel
        _guard_wheel(self)

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
        self.nav_list.addItem("AI Settings")
        self.nav_list.addItem("Voice Input")  # td-mgcw8
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
        self.display_scale_tab.saturation_changed.connect(self._on_saturation_changed)
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

        # Narrow provider settings used by Add Chart image reading.
        from ui.ai_provider_settings import AIProviderSettings
        self.ai_providers_tab = AIProviderSettings()
        self.content_stack.addWidget(self.ai_providers_tab)

        # Voice Input (td-mgcw8).
        from ui.voice_input_settings import VoiceInputSection
        self.voice_input_tab = VoiceInputSection()
        self.content_stack.addWidget(self.voice_input_tab)

        main_layout.addWidget(self.content_stack)
        self.nav_list.currentRowChanged.connect(self.content_stack.setCurrentIndex)

    def _on_theme_changed(self, theme_file: str):
        self.current_theme = theme_file
        self.theme_changed.emit(theme_file)

    def _on_scale_changed(self, factor: float):
        self.scale_changed.emit(factor)

    def _on_saturation_changed(self, value: int):
        self.saturation_changed.emit(value)

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
        if hasattr(self, 'ai_providers_tab'):
            self.ai_providers_tab.refresh_theme()
        if hasattr(self, 'voice_input_tab'):
            self.voice_input_tab.refresh_theme()
        # Every page's italic row hints share one live ink (ui/settings_hint).
        _hint.refresh_hints(self)
