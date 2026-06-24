#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Planet Information Dialog
Popup dialog showing detailed planet information when a planet is clicked.

Features:
- Planet position and element info
- Dignity checking (exaltation, mulatrikona, own sign)
- Proud state descriptions for dignified planets
- Sign description with body part info
- Planet image variation selection
- Horizontal oscillation animation for planet icons
"""
import re
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTextBrowser, QWidget, QApplication, QGraphicsDropShadowEffect,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QListWidget,
    QListWidgetItem, QSplitter
)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QTextDocument, QPainter

from ui.qt_theme import (
    BG, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, GOLD,
    ACCENTS, FONT_PRIMARY, FONT_MONO, BORDER, HOVER,
    get_theme_colors, get_primary_button_style, get_secondary_button_style,
    get_3d_button_style, STATUS,
    scaled_area_font, is_light_theme,
)

# Import shared Aditya data
from core.aditya_data import (
    check_planet_dignity, get_dignity_description, get_aditya_description,
    get_being_description,
    ADITYA_BODY_PARTS, PLANET_COLORS, ELEMENT_COLORS, ADITYA_NAMES
)
from core.hora_trimsamsa_calc import resolve_planet_position

# Project root for image paths
PROJECT_ROOT = Path(__file__).parent.parent.parent


class RotatingPlanetWidget(QGraphicsView):
    """
    Planet icon with smooth horizontal oscillation effect (side-to-side swing).
    Creates a gentle, mesmerizing showcase display that draws attention to the planet.

    Uses sine wave for smooth, natural-looking horizontal movement.
    """

    def __init__(self, pixmap, rotation_speed=0.5, parent=None):
        """
        Args:
            pixmap: QPixmap of the planet image
            rotation_speed: Controls oscillation speed (higher = faster swing)
            parent: Parent widget
        """
        super().__init__(parent)
        self.oscillation_speed = rotation_speed * 0.02  # Scale for gentle movement
        self.oscillation_phase = 0.0  # Phase in radians (0 to 2π)
        self.max_offset = 15  # Max horizontal displacement in pixels

        # Setup scene
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Flag to prevent scene queries during destruction
        self._is_closing = False

        # Transparent background with no frame
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Calculate image dimensions accounting for DPR
        dpr = pixmap.devicePixelRatio() if pixmap.devicePixelRatio() > 0 else 1.0
        self.img_width = pixmap.width() / dpr
        self.img_height = pixmap.height() / dpr

        # Add pixmap item
        self.planet_item = QGraphicsPixmapItem(pixmap)
        self.planet_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        # Scene needs extra horizontal space for oscillation
        scene_width = self.img_width + (self.max_offset * 2) + 10
        scene_height = self.img_height + 10

        # Center position (where oscillation returns to)
        self.center_x = (scene_width - self.img_width) / 2
        self.center_y = (scene_height - self.img_height) / 2
        self.planet_item.setPos(self.center_x, self.center_y)

        self.scene.addItem(self.planet_item)
        self.scene.setSceneRect(0, 0, scene_width, scene_height)

        # Fit the view to show entire scene
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

        # Animation timer (60 FPS for smooth oscillation)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._oscillate)
        self.timer.start(16)  # ~60 FPS

    def _oscillate(self):
        """Advance horizontal oscillation by one frame using sine wave"""
        # Don't animate during destruction (timer should be stopped but double-check)
        if self._is_closing:
            return

        self.oscillation_phase += self.oscillation_speed
        if self.oscillation_phase > 2 * math.pi:
            self.oscillation_phase -= 2 * math.pi

        # Calculate horizontal offset using sine wave
        # sin() gives smooth -1 to 1 transition
        offset = math.sin(self.oscillation_phase) * self.max_offset
        self.planet_item.setPos(self.center_x + offset, self.center_y)

    def update_pixmap(self, pixmap):
        """Update the displayed pixmap (for variation changes)"""
        # Don't update during destruction
        if self._is_closing:
            return

        dpr = pixmap.devicePixelRatio() if pixmap.devicePixelRatio() > 0 else 1.0
        self.img_width = pixmap.width() / dpr
        self.img_height = pixmap.height() / dpr

        self.planet_item.setPixmap(pixmap)

        # Recalculate scene bounds
        scene_width = self.img_width + (self.max_offset * 2) + 10
        scene_height = self.img_height + 10

        self.center_x = (scene_width - self.img_width) / 2
        self.center_y = (scene_height - self.img_height) / 2
        self.planet_item.setPos(self.center_x, self.center_y)

        self.scene.setSceneRect(0, 0, scene_width, scene_height)
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        """Re-fit view when widget is resized"""
        super().resizeEvent(event)

        # CRITICAL: Don't query scene during destruction (prevents segfault)
        # fitInView() queries BSP tree - if scene is being destroyed, this crashes
        if not self._is_closing and hasattr(self, 'scene'):
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def stop_rotation(self):
        """Stop the oscillation animation safely (disconnect signal)"""
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
            # Disconnect signal to prevent callback to deleted object
            try:
                self.timer.timeout.disconnect(self._oscillate)
            except:
                pass  # Already disconnected or no connections

    def start_rotation(self):
        """Resume the oscillation animation"""
        if hasattr(self, 'timer'):
            # Reconnect signal if needed
            try:
                self.timer.timeout.connect(self._oscillate)
            except:
                pass  # Already connected
            self.timer.start(16)

    def closeEvent(self, event):
        """Clean up timer and scene on close"""
        # CRITICAL: Set closing flag FIRST to prevent resizeEvent from accessing scene
        self._is_closing = True

        # Stop timer and disconnect signal
        if hasattr(self, 'timer'):
            self.timer.stop()
            try:
                self.timer.timeout.disconnect(self._oscillate)
            except:
                pass

        # Clear graphics effects before destroying scene to prevent segfault
        if hasattr(self, 'scene'):
            for item in self.scene.items():
                if item.graphicsEffect():
                    item.setGraphicsEffect(None)
            self.scene.clear()

        super().closeEvent(event)


class PlanetInfoDialog(QDialog):
    """Popup dialog showing detailed planet information with dignity and descriptions"""

    # Signal emitted when variation is applied
    variation_applied = Signal(str, int)  # planet_name, variation_num

    # Planet element associations (Tropical Vedic system per project convention).
    PLANET_ELEMENTS = {
        "Sun": ("Soul/Atma", "Pure consciousness, the Self, source of all light and life"),
        "Moon": ("Reflection", "Mirror of the Soul; birthplace of the 5 elements"),
        "Mars": ("Fire", "Mineral, volcano, raw components, engineering, metal works"),
        "Mercury": ("Earth", "Skin, covering, equilibrium, creates stability"),
        "Jupiter": ("Ether", "Space, gas, lightning, expansion, wisdom"),
        "Venus": ("Water", "Lubricant, comfort, regeneration, appeasing"),
        "Saturn": ("Air", "Movement, change, wind, frequency, rapid movement"),
        "Rahu": ("Shadow", "North lunar node, material desires, obsession"),
        "Ketu": ("Shadow", "South lunar node, spirituality, liberation"),
        "Uranus": ("Outer", "Sudden change, revolution, awakening, unconventional thinking"),
        "Neptune": ("Outer", "Dreams, intuition, illusion, spiritual transcendence"),
        "Pluto": ("Outer", "Transformation, power, rebirth, the underworld"),
    }

    # Western zodiac names for Aditya index lookup
    WESTERN_TO_ADITYA = dict(zip(
        ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"],
        ADITYA_NAMES
    ))

    def __init__(self, planet_name, planet_info, planet_pixmap=None,
                 current_variation=1, parent=None):
        super().__init__(parent)
        self.planet_name = planet_name
        self.planet_info = planet_info

        # Get sign info: display name (IAST) for UI, canonical name for data lookups
        self.display_sign = planet_info.get("aditya_zodiac", planet_info.get("sign", "Unknown"))
        self.deg_in_sign = planet_info.get("degrees", 0) + planet_info.get("minutes", 0) / 60.0

        # Resolve canonical Aditya name via sign_index (handles IAST/eng/deva name types)
        sign_idx = planet_info.get("sign_index")
        if sign_idx is not None and 0 <= sign_idx < len(ADITYA_NAMES):
            self.zodiac_idx = sign_idx
            self.aditya_sign = ADITYA_NAMES[sign_idx]
        elif self.display_sign in ADITYA_NAMES:
            self.zodiac_idx = ADITYA_NAMES.index(self.display_sign)
            self.aditya_sign = self.display_sign
        elif self.display_sign in self.WESTERN_TO_ADITYA:
            self.aditya_sign = self.WESTERN_TO_ADITYA[self.display_sign]
            self.zodiac_idx = ADITYA_NAMES.index(self.aditya_sign)
        else:
            self.zodiac_idx = 0
            self.aditya_sign = ADITYA_NAMES[0]
        self.element_color = ELEMENT_COLORS.get(self.zodiac_idx, GOLD)

        # Check dignity
        self.dignity = check_planet_dignity(planet_name, self.aditya_sign, self.deg_in_sign)

        # Resolve hora/trimsamsa position for this planet
        full_deg = planet_info.get("decimal_degrees")
        calc_deg = full_deg if full_deg is not None else self.deg_in_sign
        try:
            _, self._hora_key, self._trimsamsa_key = resolve_planet_position(
                self.zodiac_idx, calc_deg
            )
        except Exception:
            self._hora_key, self._trimsamsa_key = None, None

        # Planet variations
        self.variations = self._get_planet_variations()
        self.current_idx = 0
        if current_variation in self.variations:
            self.current_idx = self.variations.index(current_variation)

        self._setup_ui(planet_pixmap)

    def _get_planet_variations(self):
        """Get list of available image variations for this planet"""
        variations = []
        planet_dir = PROJECT_ROOT / "img" / "planets"  # Note: 'planets' with 's'

        if not planet_dir.exists():
            self._planet_filename = self.planet_name
            return [1]

        # Determine actual filename case by listing directory and matching
        # This handles case-insensitive filesystems correctly
        self._planet_filename = None
        try:
            for f in planet_dir.iterdir():
                if f.name.lower() == f"{self.planet_name.lower()}.webp":
                    # Found the base file - extract actual case from filename
                    self._planet_filename = f.stem  # e.g., "sun" or "Mars"
                    variations.append(1)
                    break
        except Exception:
            pass

        if self._planet_filename is None:
            self._planet_filename = self.planet_name
            return [1]

        filename = self._planet_filename

        # Look for numbered variations using case-insensitive matching
        for filepath in planet_dir.iterdir():
            if filepath.suffix.lower() != '.webp':
                continue
            name = filepath.stem  # filename without extension
            # Match pattern: filename + digits (e.g., sun2, Mars3)
            if name.lower().startswith(filename.lower()) and name[len(filename):].isdigit():
                var_num = int(name[len(filename):])
                if var_num not in variations:
                    variations.append(var_num)

        return sorted(variations) if variations else [1]

    def _extract_toc(self, markdown_text):
        """Extract headers from markdown for Table of Contents"""
        toc = []
        for line in markdown_text.split('\n'):
            line = line.strip()
            if line.startswith('## '):
                # H2 header - main section
                title = line[3:].strip()
                anchor = title.lower().replace(' ', '-').replace('&', '').replace(',', '')
                toc.append(('h2', title, anchor))
            elif line.startswith('### '):
                # H3 header - subsection
                title = line[4:].strip()
                anchor = title.lower().replace(' ', '-').replace('&', '').replace(',', '')
                toc.append(('h3', title, anchor))
        return toc

    def _scroll_to_anchor(self, item):
        """Scroll content browser to the clicked TOC item using text search"""
        if not hasattr(self, 'content_browser'):
            return

        # Get title from widget label if present, otherwise from item text
        widget = self.toc_list.itemWidget(item)
        if widget and hasattr(widget, 'property'):
            title = (widget.property("toc_title") or widget.text()).strip()
        else:
            title = item.text().strip()
        if title.startswith("• "):
            title = title[2:]  # Remove bullet prefix from subsections

        # Find the header text in the document
        # Use QTextDocument.find() with exact phrase matching
        doc = self.content_browser.document()

        # Search from the beginning of the document
        cursor = doc.find(title)
        if not cursor.isNull():
            # Move cursor to start of the found text
            cursor.movePosition(cursor.MoveOperation.StartOfBlock)

            # Set cursor and scroll to make it visible
            self.content_browser.setTextCursor(cursor)

            # Get the position and scroll to it
            rect = self.content_browser.cursorRect(cursor)
            scrollbar = self.content_browser.verticalScrollBar()
            if scrollbar:
                # Calculate scroll position (header at top with some margin)
                scroll_pos = scrollbar.value() + rect.top() - 20
                scrollbar.setValue(max(0, scroll_pos))

    def _setup_ui(self, planet_pixmap):
        """Setup the dialog UI with TOC sidebar and spacious content area"""
        # Get dynamic theme colors from qt-material
        self.theme = get_theme_colors()

        self.setWindowTitle(f"{self.planet_name} Details")
        self.setMinimumWidth(850)
        self.setMinimumHeight(750)
        self.resize(900, 800)  # Larger default size
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self.theme['secondary_dark']};
            }}
            QLabel {{
                color: {self.theme['secondary_text']};
            }}
            QFrame#separator {{
                background-color: {self.theme['primary']};
            }}
            QSplitter::handle {{
                background-color: {self.theme['secondary']};
                width: 3px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === TOP SECTION: Planet Name + Image ===
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        # Left: Planet icon with rotation
        icon_container = QWidget()
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        if len(self.variations) > 1:
            # Navigation buttons + rotating icon
            nav_layout = QHBoxLayout()
            nav_layout.setSpacing(5)

            self.left_btn = QPushButton("◀")
            self.left_btn.setFont(scaled_area_font('buttons', bold=True))
            self.left_btn.setFixedSize(30, 30)
            self.left_btn.setStyleSheet(self._get_arrow_style())
            self.left_btn.clicked.connect(self._go_prev)
            nav_layout.addWidget(self.left_btn)

            self.rotating_planet = None
            self.planet_container = QWidget()
            self.planet_container.setFixedSize(230, 230)
            self.planet_container.setStyleSheet("background: transparent;")
            self.planet_container_layout = QVBoxLayout(self.planet_container)
            self.planet_container_layout.setContentsMargins(0, 0, 0, 0)
            self.planet_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nav_layout.addWidget(self.planet_container)

            self.right_btn = QPushButton("▶")
            self.right_btn.setFont(scaled_area_font('buttons', bold=True))
            self.right_btn.setFixedSize(30, 30)
            self.right_btn.setStyleSheet(self._get_arrow_style())
            self.right_btn.clicked.connect(self._go_next)
            nav_layout.addWidget(self.right_btn)

            icon_layout.addLayout(nav_layout)

            self.counter_label = QLabel()
            self.counter_label.setFont(scaled_area_font('buttons'))
            self.counter_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
            self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_layout.addWidget(self.counter_label)

            self._load_current_image()
        elif planet_pixmap:
            dpr = self._get_dpr()
            target_size = 200
            physical_size = int(target_size * dpr)
            img_path = PROJECT_ROOT / "img" / "planets" / f"{self._planet_filename}.webp"
            if img_path.exists():
                qimage = QImage(str(img_path))
                if not qimage.isNull():
                    scaled = qimage.scaled(
                        physical_size, physical_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    scaled_pixmap = QPixmap.fromImage(scaled)
                    scaled_pixmap.setDevicePixelRatio(dpr)
                else:
                    scaled_pixmap = planet_pixmap
            else:
                scaled_pixmap = planet_pixmap
            self.single_rotating_planet = RotatingPlanetWidget(scaled_pixmap, rotation_speed=0.4)
            self.single_rotating_planet.setFixedSize(target_size + 10, target_size + 10)
            icon_layout.addWidget(self.single_rotating_planet, alignment=Qt.AlignmentFlag.AlignCenter)

        top_layout.addWidget(icon_container)

        # Right: Planet name and basic info
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(5)

        planet_color = PLANET_COLORS.get(self.planet_name, GOLD)
        name_label = QLabel(self.planet_name)
        name_label.setFont(scaled_area_font('panel_titles', bold=True))
        name_label.setStyleSheet(f"color: {planet_color};")
        info_layout.addWidget(name_label)

        # Dignity badge - uses theme primary color
        if self.dignity:
            dignity_text = {
                "exaltation": "✦ EXALTED",
                "mulatrikona": "✦ MULATRIKONA",
                "own_sign": "✦ OWN SIGN",
                "debilitation": "▼ DEBILITATED",
            }.get(self.dignity, "")
            dignity_label = QLabel(dignity_text)
            dignity_label.setFont(scaled_area_font('buttons', bold=True))
            dignity_label.setStyleSheet(f"color: {self.theme['primary_text']}; "
                                         f"background-color: {self.theme['primary']}; "
                                         f"padding: 4px 12px; border-radius: 4px;")
            info_layout.addWidget(dignity_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Position info
        deg = self.planet_info.get("degrees", 0)
        mins = self.planet_info.get("minutes", 0)
        full_deg = self.planet_info.get("decimal_degrees", 0)
        pos_label = QLabel(f"{deg}° {mins}' {self.display_sign}")
        pos_label.setFont(scaled_area_font('tables'))
        pos_label.setStyleSheet(f"color: {self.theme['secondary_text']};")
        info_layout.addWidget(pos_label)

        # Element
        element_info = self.PLANET_ELEMENTS.get(self.planet_name, ("Unknown", ""))
        element_label = QLabel(f"Element: {element_info[0]}")
        element_label.setFont(scaled_area_font('buttons'))
        element_label.setStyleSheet(f"color: {self.theme['secondary_text']};")
        info_layout.addWidget(element_label)

        # Retrograde
        if self.planet_info.get("retrograde"):
            retro_label = QLabel("⟲ Retrograde")
            retro_label.setStyleSheet(f"color: {STATUS['error']}; font-weight: bold;")
            info_layout.addWidget(retro_label)

        info_layout.addStretch()
        top_layout.addWidget(info_widget, 1)
        main_layout.addWidget(top_widget)

        # === SEPARATOR ===
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFixedHeight(2)
        main_layout.addWidget(separator)

        # === MAIN CONTENT: TOC + Description Splitter ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # LEFT: Table of Contents
        toc_widget = QWidget()
        toc_layout = QVBoxLayout(toc_widget)
        toc_layout.setContentsMargins(0, 0, 5, 0)
        toc_layout.setSpacing(5)

        toc_header = QLabel("Contents")
        toc_header.setFont(scaled_area_font('panel_titles', bold=True))
        toc_header.setStyleSheet(f"color: {self.theme['primary']};")
        toc_layout.addWidget(toc_header)

        self.toc_list = QListWidget()
        self.toc_list.setFont(scaled_area_font('tables'))
        self._toc_default_fg = self.theme['secondary_text']
        self.toc_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self.theme['secondary']};
                border: 1px solid {self.theme['primary']};
                border-radius: 6px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {self.theme['secondary_light']};
            }}
            QListWidget::item:selected {{
                background-color: {self.theme['primary']};
                color: {self.theme['primary_text']};
            }}
        """)
        self.toc_list.itemClicked.connect(self._scroll_to_anchor)
        toc_layout.addWidget(self.toc_list, 1)

        splitter.addWidget(toc_widget)

        # RIGHT: Content Browser (combined descriptions)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 0, 0, 0)
        content_layout.setSpacing(0)

        self.content_browser = QTextBrowser()
        self.content_browser.setOpenExternalLinks(False)
        self.content_browser.setFont(scaled_area_font('tables'))
        self.content_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 8px;
                padding: 15px;
                selection-background-color: {self.theme['primary']};
            }}
        """)

        # Build base content (markdown) and hora/trimsamsa (HTML)
        base_markdown = self._build_combined_content()
        self.content_browser.setMarkdown(base_markdown)

        # Append hora/trimsamsa as HTML via QTextCursor (tables survive
        # Qt's rich text engine, unlike <div> blocks in setMarkdown)
        from PySide6.QtGui import QTextCursor
        hora_html = self._build_hora_trimsamsa_html()
        cursor = self.content_browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(hora_html)

        # Extract TOC from base markdown + manually add hora/trimsamsa
        light = is_light_theme()
        hora_colors = self._HORA_COLORS_LIGHT if light else self._HORA_COLORS_DARK
        being_colors = self._BEING_COLORS_LIGHT if light else self._BEING_COLORS_DARK

        toc_items = self._extract_toc(base_markdown)
        for _, being_type, label in self._HORA_BEINGS:
            desc = get_being_description(self.aditya_sign, "hora", being_type)
            suffix = f": {desc['name']}" if desc and desc.get("name") else ""
            colors_pair = None
            if being_type == self._hora_key:
                colors_pair = hora_colors.get(being_type)
            toc_items.append(('h3', label + suffix, being_type, colors_pair))
        toc_items.insert(len(toc_items) - len(self._HORA_BEINGS),
                         ('h2', 'Hora', 'hora', None))
        toc_items.append(('h2', 'Trimsamsa', 'trimsamsa', None))
        for _, being_type, label in self._TRIMSAMSA_BEINGS:
            desc = get_being_description(self.aditya_sign, "trimsamsa", being_type)
            suffix = f": {desc['name']}" if desc and desc.get("name") else ""
            colors_pair = None
            if being_type == self._trimsamsa_key:
                colors_pair = being_colors.get(being_type)
            toc_items.append(('h3', label + suffix, being_type, colors_pair))

        for entry in toc_items:
            level, title, anchor = entry[0], entry[1], entry[2]
            colors_pair = entry[3] if len(entry) > 3 else None
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, anchor)
            display = f"  • {title}" if level == 'h3' else title
            item.setText(display)
            if level == 'h3':
                item.setFont(scaled_area_font('tables'))
            self.toc_list.addItem(item)
            if colors_pair:
                _, fg_hex = colors_pair
                item.setText("")
                label = QLabel(display)
                label.setFont(scaled_area_font('tables'))
                label.setStyleSheet(
                    f"color: {fg_hex}; font-weight: bold; "
                    f"padding: 4px 8px;"
                )
                label.setProperty("toc_title", display)
                self.toc_list.setItemWidget(item, label)

        # Add shadow for depth
        # FIXED: Don't keep reference after setGraphicsEffect - Qt owns it
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(20)
        shadow_effect.setOffset(0, 5)
        shadow_effect.setColor(QColor(0, 0, 0, 100))
        self.content_browser.setGraphicsEffect(shadow_effect)
        del shadow_effect  # Release Python reference - Qt has sole ownership

        content_layout.addWidget(self.content_browser)
        splitter.addWidget(content_widget)

        # Set splitter proportions (TOC: 25%, Content: 75%)
        splitter.setSizes([200, 600])
        splitter.setStretchFactor(0, 0)  # TOC doesn't stretch
        splitter.setStretchFactor(1, 1)  # Content stretches

        main_layout.addWidget(splitter, 1)  # Stretch factor 1 for splitter

        # === BUTTONS ===
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        if len(self.variations) > 1:
            apply_btn = QPushButton("Change Icon")
            apply_btn.setFont(scaled_area_font('buttons', bold=True))
            # Use theme primary color for apply button
            apply_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {self.theme['primary_light']}, stop:1 {self.theme['primary']});
                    color: {self.theme['primary_text']};
                    border: none;
                    padding: 12px 24px;
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    background: {self.theme['primary']};
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {self.theme['primary']}, stop:1 {self.theme['secondary']});
                }}
            """)
            apply_btn.clicked.connect(self._apply_and_close)
            # FIXED: Don't keep reference after setGraphicsEffect - Qt owns it
            shadow_effect = QGraphicsDropShadowEffect()
            shadow_effect.setBlurRadius(12)
            shadow_effect.setOffset(0, 3)
            shadow_effect.setColor(QColor(0, 0, 0, 60))
            apply_btn.setGraphicsEffect(shadow_effect)
            del shadow_effect  # Release Python reference - Qt has sole ownership
            button_layout.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.setFont(scaled_area_font('buttons'))
        # Use theme secondary button style with dynamic theme colors
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.theme['secondary_light']}, stop:1 {self.theme['secondary']});
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                padding: 12px 24px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.theme['primary_light']}, stop:1 {self.theme['primary']});
                border-color: {self.theme['primary']};
                color: {self.theme['primary_text']};
            }}
            QPushButton:pressed {{
                background: {self.theme['primary']};
                color: {self.theme['primary_text']};
            }}
        """)
        close_btn.clicked.connect(self.accept)
        # FIXED: Don't keep reference after setGraphicsEffect - Qt owns it
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(10)
        shadow_effect.setOffset(0, 2)
        shadow_effect.setColor(QColor(0, 0, 0, 50))
        close_btn.setGraphicsEffect(shadow_effect)
        del shadow_effect  # Release Python reference - Qt has sole ownership
        button_layout.addWidget(close_btn)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        # Keyboard shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    _HORA_BEINGS = [
        ("hora", "aditya", "Aditya (Sun side)"),
        ("hora", "naga", "Naga (Moon side)"),
    ]
    _TRIMSAMSA_BEINGS = [
        ("trimsamsa", "gandharva", "Gandharva"),
        ("trimsamsa", "rakshasa", "Rakshasa"),
        ("trimsamsa", "rishi", "Rishi"),
        ("trimsamsa", "yaksha", "Yaksha"),
        ("trimsamsa", "apsara", "Apsara"),
    ]
    _HORA_COLORS_DARK = {
        "aditya": ("#5C3D10", "#FFD54F"),
        "naga":   ("#10354D", "#80DEEA"),
    }
    _HORA_COLORS_LIGHT = {
        "aditya": ("#FFF3E0", "#E65100"),
        "naga":   ("#E0F7FA", "#006064"),
    }
    _BEING_COLORS_DARK = {
        "gandharva": ("#5C1A1A", "#E57373"),
        "rakshasa":  ("#4D4D10", "#F0C75E"),
        "rishi":     ("#3D1A5C", "#CE93D8"),
        "yaksha":    ("#4D3818", "#D4A76A"),
        "apsara":    ("#102E5C", "#64B5F6"),
    }
    _BEING_COLORS_LIGHT = {
        "gandharva": ("#FFEBEE", "#B71C1C"),
        "rakshasa":  ("#FFFDE7", "#F57F17"),
        "rishi":     ("#F3E5F5", "#6A1B9A"),
        "yaksha":    ("#FBE9E7", "#4E342E"),
        "apsara":    ("#E3F2FD", "#1565C0"),
    }

    def _build_combined_content(self):
        """Build combined markdown content from all description sources"""
        sections = []

        # Body part info
        body_part = ADITYA_BODY_PARTS.get(self.aditya_sign, "Unknown")
        sections.append(f"## Overview\n\n**Sign Body Part:** {body_part}\n")

        # Element description
        element_info = self.PLANET_ELEMENTS.get(self.planet_name, ("Unknown", ""))
        if element_info[1]:
            sections.append(f"**{self.planet_name}'s Element ({element_info[0]}):** {element_info[1]}\n")

        # Full longitude
        full_deg = self.planet_info.get("decimal_degrees", 0)
        sections.append(f"**Full Longitude:** {full_deg:.4f}°\n")

        # Dignity description (if applicable)
        if self.dignity:
            dignity_text = get_dignity_description(self.dignity, self.aditya_sign)
            sections.append(f"\n## Proud State (Avastha)\n\n{dignity_text}\n")

        # Sign description
        sign_text = get_aditya_description(self.aditya_sign)
        sections.append(f"\n## About {self.aditya_sign}\n\n{sign_text}")

        return "\n".join(sections)

    def _build_hora_trimsamsa_html(self):
        """Build hora/trimsamsa sections as HTML for QTextCursor insertion.

        Uses <table> for colored blocks because Qt's rich text engine
        supports table backgrounds natively, unlike <div> which gets
        stripped by setMarkdown().
        """
        light = is_light_theme()
        hora_colors = self._HORA_COLORS_LIGHT if light else self._HORA_COLORS_DARK
        being_colors = self._BEING_COLORS_LIGHT if light else self._BEING_COLORS_DARK
        theme = get_theme_colors()
        text_color = theme["secondary_text"]

        deg_int = int(self.deg_in_sign)
        min_val = int((self.deg_in_sign - deg_int) * 60)
        degree_text = f"{deg_int}°{min_val:02d}'"

        parts = []
        parts.append(f'<h2>Hora</h2>')
        parts.append(
            f'<p style="color: {text_color};">'
            'Every being in this sign adds meaning to understanding the Aditya. '
            'A planet does not need to fall directly in a specific zone for that '
            'description to be relevant. However, when a planet does fall in a '
            'specific zone, that description becomes directly activated in the chart.'
            '</p>'
        )

        for _, being_type, display_label in self._HORA_BEINGS:
            desc = get_being_description(self.aditya_sign, "hora", being_type)
            name_suffix = f": {desc['name']}" if desc and desc.get("name") else ""
            title = display_label + name_suffix
            is_active = (self._hora_key == being_type)

            if is_active:
                bg, fg = hora_colors.get(being_type, ("#2A2A2A", "#FFFFFF"))
                parts.append(self._render_active_block(
                    title, desc, bg, fg,
                    self.planet_name, degree_text, self.aditya_sign, "Hora",
                ))
            else:
                parts.append(self._render_inactive_block(title, desc, text_color))

        parts.append(f'<h2>Trimsamsa</h2>')

        for _, being_type, display_label in self._TRIMSAMSA_BEINGS:
            desc = get_being_description(self.aditya_sign, "trimsamsa", being_type)
            name_suffix = f": {desc['name']}" if desc and desc.get("name") else ""
            title = display_label + name_suffix
            is_active = (self._trimsamsa_key == being_type)

            if is_active:
                bg, fg = being_colors.get(being_type, ("#2A2A2A", "#FFFFFF"))
                parts.append(self._render_active_block(
                    title, desc, bg, fg,
                    self.planet_name, degree_text, self.aditya_sign, "Trimsamsa",
                ))
            else:
                parts.append(self._render_inactive_block(title, desc, text_color))

        return "\n".join(parts)

    @staticmethod
    def _render_active_block(title, desc, bg, fg, planet_name,
                             degree_text, sign_name, ring_label):
        annotation = (
            f'<p style="color: {GOLD}; font-style: italic;">'
            f'{planet_name} at {degree_text} {sign_name} falls directly in this '
            f'{ring_label}. This description is especially relevant in your chart.</p>'
        )
        content = annotation
        if desc:
            for key, label in [("theme", "Theme"), ("healthy", "Healthy Expression"),
                               ("afflicted", "Afflicted Expression")]:
                value = desc.get(key, "")
                if value:
                    content += f'<p style="color: {fg};"><b>{label}:</b> {value}</p>'
        else:
            content += f'<p style="color: {fg}; font-style: italic;">Description not available</p>'
        return (
            f'<table width="100%" cellpadding="10" '
            f'style="background-color: {bg}; margin-top: 6px; margin-bottom: 6px;">'
            f'<tr><td style="border-left: 4px solid {fg};">'
            f'<h3><span style="color: {fg};">{title}</span></h3>'
            f'{content}'
            f'</td></tr></table>'
        )

    @staticmethod
    def _render_inactive_block(title, desc, text_color):
        content = ""
        if desc:
            for key, label in [("theme", "Theme"), ("healthy", "Healthy Expression"),
                               ("afflicted", "Afflicted Expression")]:
                value = desc.get(key, "")
                if value:
                    content += f'<p style="color: {text_color};"><b>{label}:</b> {value}</p>'
        else:
            content += f'<p style="color: {text_color}; font-style: italic;">Description not available</p>'
        return f'<h3>{title}</h3>{content}'

    def _get_arrow_style(self):
        """Arrow navigation button style using dynamic theme colors"""
        theme = get_theme_colors()
        return f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: 2px solid {theme['primary']};
                border-radius: 15px;
            }}
            QPushButton:hover {{
                background-color: {theme['primary']};
                color: {theme['primary_text']};
            }}
            QPushButton:disabled {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border-color: {theme['secondary_light']};
            }}
        """

    def _get_dpr(self):
        """Get device pixel ratio for high-DPI display support."""
        screen = QApplication.primaryScreen()
        if screen:
            return screen.devicePixelRatio()
        return 1.0

    def _load_current_image(self):
        """Load and display the current variation image with rotating effect"""
        if not self.variations:
            return

        var_num = self.variations[self.current_idx]
        filename = self._planet_filename  # Use detected case (sun vs Sun)

        # Build filename: base.png for var 1, base2.png for var 2, etc.
        if var_num == 1:
            file_suffix = f"{filename}.webp"
        else:
            file_suffix = f"{filename}{var_num}.webp"

        # Try main planets folder (2048x2048 originals). Core ships exactly
        # one file per planet (the single default retained by the 2026-04-08
        # cleanup), so this is the only path the Core build can hit. The
        # proprietary edition may add more variants via an overlay path; see
        # the variation system rebuild TODO in the proprietary tree.
        img_path = PROJECT_ROOT / "img" / "planets" / file_suffix

        if img_path.exists():
            qimage = QImage(str(img_path))
            if not qimage.isNull():
                # High-DPI: Scale to physical pixels
                dpr = self._get_dpr()
                target_size = 200
                physical_size = int(target_size * dpr)

                scaled = qimage.scaled(
                    physical_size, physical_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                pixmap = QPixmap.fromImage(scaled)
                pixmap.setDevicePixelRatio(dpr)

                # Create or update rotating widget
                if self.rotating_planet is None:
                    self.rotating_planet = RotatingPlanetWidget(pixmap, rotation_speed=0.4)
                    self.rotating_planet.setFixedSize(target_size + 20, target_size + 20)
                    self.planet_container_layout.addWidget(self.rotating_planet)
                else:
                    self.rotating_planet.update_pixmap(pixmap)

        # Update counter
        self.counter_label.setText(f"Variation {self.current_idx + 1} of {len(self.variations)}")

        # Update arrow states
        self.left_btn.setEnabled(self.current_idx > 0)
        self.right_btn.setEnabled(self.current_idx < len(self.variations) - 1)

    def _go_prev(self):
        """Navigate to previous variation"""
        if self.current_idx > 0:
            self.current_idx -= 1
            self._load_current_image()

    def _go_next(self):
        """Navigate to next variation"""
        if self.current_idx < len(self.variations) - 1:
            self.current_idx += 1
            self._load_current_image()

    def _apply_and_close(self):
        """Save selected variation and close"""
        selected_var = self.variations[self.current_idx]
        self.variation_applied.emit(self.planet_name, selected_var)
        self.accept()

    def keyPressEvent(self, event):
        """Handle keyboard navigation"""
        if len(self.variations) > 1:
            if event.key() == Qt.Key.Key_Left:
                self._go_prev()
                return
            elif event.key() == Qt.Key.Key_Right:
                self._go_next()
                return

        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def get_selected_variation(self):
        """Get the currently selected variation number"""
        return self.variations[self.current_idx] if self.variations else 1

    def _clear_all_graphics_effects(self, widget=None):
        """
        Recursively clear ALL QGraphicsEffects from widget and all children.
        This prevents segfault on dialog close caused by Qt destruction order issues.
        """
        if widget is None:
            widget = self
        
        # Clear effect from this widget
        if widget.graphicsEffect():
            widget.setGraphicsEffect(None)
        
        # Recursively clear effects from all children
        for child in widget.findChildren(QWidget):
            if child.graphicsEffect():
                child.setGraphicsEffect(None)

    def closeEvent(self, event):
        """Clean up rotating widgets and graphics effects before dialog closes"""
        from PySide6.QtWidgets import QApplication

        # Step 1: Stop rotation timers AND disconnect signals
        if hasattr(self, 'rotating_planet') and self.rotating_planet is not None:
            self.rotating_planet.stop_rotation()

            # Process pending timer events
            QApplication.processEvents()

            # Detach scene from view
            if hasattr(self.rotating_planet, 'scene'):
                self.rotating_planet.setScene(None)
                # Clear scene item effects
                for item in self.rotating_planet.scene.items():
                    if item.graphicsEffect():
                        item.setGraphicsEffect(None)
                self.rotating_planet.scene.clear()

        if hasattr(self, 'single_rotating_planet'):
            self.single_rotating_planet.stop_rotation()

            # Process pending timer events
            QApplication.processEvents()

            # Detach scene from view
            if hasattr(self.single_rotating_planet, 'scene'):
                self.single_rotating_planet.setScene(None)
                # Clear scene item effects
                for item in self.single_rotating_planet.scene.items():
                    if item.graphicsEffect():
                        item.setGraphicsEffect(None)
                self.single_rotating_planet.scene.clear()

        # CRITICAL: Clear ALL graphics effects from ALL widgets
        self._clear_all_graphics_effects()

        # Disable updates (prevent new paint events)
        self.setUpdatesEnabled(False)

        # Final event processing
        QApplication.processEvents()

        super().closeEvent(event)
