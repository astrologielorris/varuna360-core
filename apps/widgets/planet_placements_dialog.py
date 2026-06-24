#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Planet Placements Dialog
Shows all planetary positions, nakshatras, and current Vimshottari dasha.
Theme-aware: reads colors dynamically via get_theme_colors().
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QWidget, QGroupBox, QApplication, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from ui.qt_theme import (
    FONT_MONO, get_theme_colors, get_secondary_button_style,
    scaled_area_font, is_light_theme,
)


class PlanetPlacementsDialog(QDialog):
    """Dialog showing all planetary positions, nakshatras, and Vimshottari dasha."""

    PLANET_ORDER = [
        'Ascendant', 'Sun', 'Moon', 'Mars', 'Mercury',
        'Jupiter', 'Venus', 'Saturn', 'Rahu', 'Ketu',
        'Uranus', 'Neptune', 'Pluto', 'Earth', 'Chiron',
    ]

    _ADITYA_TO_WESTERN = {
        "Dhata": "Aries", "Aryama": "Taurus", "Mitra": "Gemini",
        "Varuna": "Cancer", "Indra": "Leo", "Vivasvan": "Virgo",
        "Tvasta": "Libra", "Vishnu": "Scorpio", "Amzu": "Sagittarius",
        "Bhaga": "Capricorn", "Pusha": "Aquarius", "Parjanya": "Pisces",
    }

    def __init__(self, parent=None, aditya_mode="aditya",
                 chart_data=None, person_name="Unknown", use_western_names=False,
                 chart=None, nakshatra_ayanamsa_id=100,
                 current_dasha_chain=None, cot_planet_order="vedic"):
        super().__init__(parent)
        self._chart = chart
        self.aditya_mode = aditya_mode
        self.use_western_names = use_western_names
        self.chart_data = chart_data or {}
        self.person_name = person_name
        self._nak_ayanamsa_id = nakshatra_ayanamsa_id
        self._dasha_chain = current_dasha_chain or []
        self._cot_order = cot_planet_order

        self._setup_ui()
        self._populate_data()

    def _theme_stylesheet(self):
        """Build stylesheet from live theme colors."""
        tc = get_theme_colors()
        light = is_light_theme()
        bg = tc["secondary_dark"]
        surface = tc["secondary"]
        text = tc["secondary_text"]
        text_dim = tc["primary_dark"] if light else tc["primary_light"]
        border = tc["primary_dark"] if light else "#555555"
        header_bg = tc["primary"] if not light else tc["primary_light"]
        sel_bg = tc["primary_light"] if light else tc["primary_dark"]

        self._colors = {
            "bg": bg, "surface": surface, "text": text, "text_dim": text_dim,
            "border": border, "header_bg": header_bg, "sel_bg": sel_bg,
            "accent": tc["primary"],
        }

        return f"""
            QDialog {{
                background-color: {bg};
                color: {text};
            }}
            QLabel {{
                color: {text};
            }}
            QGroupBox {{
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                color: {text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """

    def _table_stylesheet(self):
        """Build table-specific stylesheet from live theme colors."""
        c = self._colors
        return f"""
            QTableWidget {{
                background-color: {c['surface']};
                color: {c['text']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                gridline-color: {c['border']};
            }}
            QTableWidget::item {{
                padding: 4px 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {c['sel_bg']};
            }}
            QHeaderView::section {{
                background-color: {c['header_bg']};
                color: {c['text']};
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 1px solid {c['border']};
            }}
        """

    @staticmethod
    def _fit_table_height(table):
        """Set table height to exactly fit all rows (no per-table scrollbar)."""
        h = table.horizontalHeader().height() + 6
        for i in range(table.rowCount()):
            h += table.rowHeight(i)
        h += table.frameWidth() * 2
        table.setFixedHeight(h)

    def _setup_ui(self):
        """Setup dialog UI with theme-aware styling."""
        self.setWindowTitle("Planet Placements")
        self.setMinimumSize(740, 700)
        self.setModal(False)

        self.setStyleSheet(self._theme_stylesheet())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {self._colors['bg']}; }}")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # === HEADER ===
        header_label = QLabel(self.person_name)
        header_label.setFont(scaled_area_font('panel_titles', bold=True))
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_label.setStyleSheet(f"color: {self._colors['text']}; padding: 5px;")
        layout.addWidget(header_label)

        # === BIRTH DATA ===
        birth_group = QGroupBox("Birth Data")
        birth_layout = QVBoxLayout(birth_group)
        birth_layout.setSpacing(4)

        self.birth_info_label = QLabel()
        self.birth_info_label.setFont(scaled_area_font('tables', family=FONT_MONO))
        self.birth_info_label.setStyleSheet(f"color: {self._colors['text_dim']};")
        self.birth_info_label.setWordWrap(True)
        birth_layout.addWidget(self.birth_info_label)

        layout.addWidget(birth_group)

        # === PLANETS TABLE ===
        planets_group = QGroupBox("Planetary Positions")
        planets_layout = QVBoxLayout(planets_group)

        mode_map = {
            "aditya": "Aditya Circle",
            "tropical_classic": "Tropical Classic",
            "sidereal": "Sidereal",
        }
        mode_text = mode_map.get(self.aditya_mode, self.aditya_mode)

        from core.ayanamsa_data import get_ayanamsa_name
        nak_ayan_name = get_ayanamsa_name(self._nak_ayanamsa_id)
        subtitle = f"System: {mode_text}  |  Nakshatras: {nak_ayan_name} ayanamsa"

        mode_label = QLabel(subtitle)
        mode_label.setFont(scaled_area_font('buttons'))
        mode_label.setStyleSheet(
            f"color: {self._colors['text_dim']}; font-style: italic;"
        )
        mode_label.setWordWrap(True)
        planets_layout.addWidget(mode_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Planet", "Sign", "Nakshatra", "Position", "Absolute"]
        )
        self.table.setStyleSheet(self._table_stylesheet())

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)

        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 75)

        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        planets_layout.addWidget(self.table)
        layout.addWidget(planets_group)

        # === VIMSHOTTARI DASHA ===
        self.dasha_group = QGroupBox("Vimshottari Dasha (current)")
        dasha_layout = QVBoxLayout(self.dasha_group)
        dasha_layout.setSpacing(4)

        self.dasha_label = QLabel()
        self.dasha_label.setFont(scaled_area_font('tables', family=FONT_MONO))
        self.dasha_label.setStyleSheet(f"color: {self._colors['text']};")
        self.dasha_label.setWordWrap(True)
        dasha_layout.addWidget(self.dasha_label)

        layout.addWidget(self.dasha_group)

        # === CARDS OF TRUTH ===
        order_label = "vedic" if self._cot_order == "vedic" else "solar system"
        cot_group = QGroupBox(f"Cards of Truth ({order_label} order)")
        cot_layout = QVBoxLayout(cot_group)

        self.cot_table = QTableWidget()
        self.cot_table.setColumnCount(3)
        self.cot_table.setHorizontalHeaderLabels(["Position", "Card", "Planets"])
        self.cot_table.setStyleSheet(self._table_stylesheet())

        cot_header = self.cot_table.horizontalHeader()
        cot_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        cot_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        cot_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.cot_table.setColumnWidth(0, 100)
        self.cot_table.setColumnWidth(1, 80)

        self.cot_table.verticalHeader().setVisible(False)
        self.cot_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cot_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        cot_layout.addWidget(self.cot_table)
        layout.addWidget(cot_group)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # === BUTTONS (outside scroll, always visible) ===
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(15, 8, 15, 10)
        button_layout.addStretch()

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setStyleSheet(get_secondary_button_style())
        copy_btn.setMinimumWidth(140)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(get_secondary_button_style())
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        outer.addLayout(button_layout)

    def _populate_data(self):
        """Populate birth data, planets table, and dasha info."""
        if self._chart:
            self._populate_from_chart()

    def _populate_from_chart(self):
        """Populate using libaditya Chart API."""
        ctx = self._chart.context
        tj = ctx.timeJD
        loc = ctx.location
        year = tj.usryear()
        month = tj.usrmonth()
        day = tj.usrday()
        hour_frac = tj.usrhour()
        hour_int = int(hour_frac)
        minute_int = int((hour_frac - hour_int) * 60)

        city = self.chart_data.get('city', 'Unknown') if self.chart_data else 'Unknown'
        country = self.chart_data.get('country', '') if self.chart_data else ''
        location = f"{city}, {country}" if country else city

        birth_text = (
            f"Date: {month:02d}/{day:02d}/{year}  |  "
            f"Time: {hour_int:02d}:{minute_int:02d}  |  "
            f"Place: {location}  |  "
            f"Coords: {loc.lat:.4f}, {loc.long:.4f}"
        )
        self.birth_info_label.setText(birth_text)

        rashi = self._chart.rashi()
        planets = rashi.planets()
        cusps = rashi.cusps()

        available = {}
        for name, planet_obj in planets.items():
            available[name] = planet_obj

        rows = []
        for name in self.PLANET_ORDER:
            if name == 'Ascendant':
                rows.append(('Ascendant', None, cusps[1]))
            elif name in available:
                rows.append((name, available[name], None))

        self.table.setRowCount(len(rows))

        text_dim_color = QColor(self._colors['text_dim'])

        for row_idx, (name, planet, cusp) in enumerate(rows):
            obj = planet if planet is not None else cusp
            sign = obj.sign_name()
            ecl = obj.ecliptic_longitude()
            deg_in_sign = obj.real_in_sign_longitude()

            if self.aditya_mode == "aditya" and self.use_western_names:
                sign = self._ADITYA_TO_WESTERN.get(sign, sign)

            nak_name = ""
            if hasattr(obj, 'nakshatra_name'):
                nak_name = obj.nakshatra_name()

            degrees = int(deg_in_sign)
            minutes = int((deg_in_sign - degrees) * 60)
            seconds = int(((deg_in_sign - degrees) * 60 - minutes) * 60)
            position_str = f"{degrees:02d}° {minutes:02d}' {seconds:02d}\""
            absolute_str = f"{ecl:.2f}"

            planet_item = QTableWidgetItem(name)
            planet_item.setFont(scaled_area_font('tables', bold=True))

            sign_item = QTableWidgetItem(sign)
            sign_item.setFont(scaled_area_font('tables'))

            nak_item = QTableWidgetItem(nak_name)
            nak_item.setFont(scaled_area_font('tables'))

            position_item = QTableWidgetItem(position_str)
            position_item.setFont(scaled_area_font('tables', family=FONT_MONO))
            position_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            absolute_item = QTableWidgetItem(absolute_str)
            absolute_item.setFont(scaled_area_font('tables', family=FONT_MONO))
            absolute_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            absolute_item.setForeground(text_dim_color)

            self.table.setItem(row_idx, 0, planet_item)
            self.table.setItem(row_idx, 1, sign_item)
            self.table.setItem(row_idx, 2, nak_item)
            self.table.setItem(row_idx, 3, position_item)
            self.table.setItem(row_idx, 4, absolute_item)

        self.table.resizeRowsToContents()
        self._fit_table_height(self.table)

        self._populate_dasha(planets)
        self._populate_cot()

    _ABBREV_TO_FULL = {
        'Ke': 'Ketu', 'Ve': 'Venus', 'Su': 'Sun', 'Mo': 'Moon',
        'Ma': 'Mars', 'Ra': 'Rahu', 'Ju': 'Jupiter', 'Sa': 'Saturn',
        'Me': 'Mercury',
    }

    def _populate_dasha(self, planets):
        """Display the current Vimshottari dasha chain from the left panel."""
        if not self._dasha_chain:
            self.dasha_label.setText("(no dasha data available)")
            return

        full_names = [self._ABBREV_TO_FULL.get(a, a) for a in self._dasha_chain]
        level_labels = ["Mahadasha", "Bhukti", "Pratyantara", "Sookshma", "Prana"]
        lines = []
        for i, name in enumerate(full_names):
            label = level_labels[i] if i < len(level_labels) else f"Level {i+1}"
            lines.append(f"{label}: {name}")

        chain = " > ".join(full_names)
        lines.append(f"\nChain: {chain}")

        self.dasha_label.setText("\n".join(lines))

    def _populate_cot(self):
        """Populate Cards of Truth table from the chart."""
        try:
            cot = self._chart.cot(cot_planet_order=self._cot_order)
            bs = cot.birth_spread()
            spread = bs.spread()
        except Exception:
            self.cot_table.setRowCount(1)
            item = QTableWidgetItem("(could not compute Cards of Truth)")
            self.cot_table.setItem(0, 0, item)
            return

        from libaditya.cards.cards_constants import planet_order
        order = planet_order.get(self._cot_order, planet_order["vedic"])

        self.cot_table.setRowCount(len(order))

        for row_idx, position_key in enumerate(order):
            card = spread[position_key]
            planet_objs = card.planets()
            planet_names = ", ".join(p.identity() for p in planet_objs) if planet_objs else ""

            pos_item = QTableWidgetItem(position_key)
            pos_item.setFont(scaled_area_font('tables', bold=True))

            card_item = QTableWidgetItem(card.symbol())
            card_item.setFont(scaled_area_font('tables'))
            card_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            planets_item = QTableWidgetItem(planet_names)
            planets_item.setFont(scaled_area_font('tables'))

            self.cot_table.setItem(row_idx, 0, pos_item)
            self.cot_table.setItem(row_idx, 1, card_item)
            self.cot_table.setItem(row_idx, 2, planets_item)

        self.cot_table.resizeRowsToContents()
        self._fit_table_height(self.cot_table)

    def _copy_to_clipboard(self):
        """Copy all data to clipboard as formatted text."""
        lines = []
        lines.append(f"=== {self.person_name} ===")
        lines.append("")
        lines.append(self.birth_info_label.text())
        lines.append("")

        mode_map = {
            "aditya": "Aditya Circle",
            "tropical_classic": "Tropical Classic",
            "sidereal": "Sidereal",
        }
        from core.ayanamsa_data import get_ayanamsa_name
        nak_ayan_name = get_ayanamsa_name(self._nak_ayanamsa_id)
        lines.append(f"System: {mode_map.get(self.aditya_mode, self.aditya_mode)}")
        lines.append(f"Nakshatras: {nak_ayan_name} ayanamsa")
        lines.append("")

        lines.append(
            f"{'Planet':<12} {'Sign':<14} {'Nakshatra':<16} "
            f"{'Position':<14} {'Absolute':<10}"
        )
        lines.append("-" * 68)

        for row in range(self.table.rowCount()):
            cells = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                cells.append(item.text() if item else "")
            lines.append(
                f"{cells[0]:<12} {cells[1]:<14} {cells[2]:<16} "
                f"{cells[3]:<14} {cells[4]:<10}"
            )

        lines.append("")
        lines.append("Vimshottari Dasha:")
        lines.append(self.dasha_label.text())

        lines.append("")
        lines.append(f"Cards of Truth ({self._cot_order} order):")
        lines.append(f"{'Position':<12} {'Card':<8} {'Planets'}")
        lines.append("-" * 50)
        for row in range(self.cot_table.rowCount()):
            pos = self.cot_table.item(row, 0)
            card = self.cot_table.item(row, 1)
            pls = self.cot_table.item(row, 2)
            lines.append(
                f"{pos.text() if pos else '':<12} "
                f"{card.text() if card else '':<8} "
                f"{pls.text() if pls else ''}"
            )

        text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        sender = self.sender()
        if sender:
            original_text = sender.text()
            sender.setText("Copied!")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: sender.setText(original_text))
