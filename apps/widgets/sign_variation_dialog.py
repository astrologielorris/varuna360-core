#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Sign Variation Dialog
Popup dialog for browsing and selecting zodiac sign icon variations.

Features:
- Modern visual design with gradients and shadows
- Rendered markdown descriptions (not raw syntax)
- Continuous slow rotation for sign icons (showcase effect)
"""
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextBrowser, QWidget, QApplication, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QImage, QColor

from ui.qt_theme import (
    BG, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, GOLD,
    ACCENTS, FONT_PRIMARY, FONT_MONO, BORDER, STATUS, get_theme_colors,
    scaled_area_font, scaled_area_px,
)

# Import rotating widget from planet dialog
from apps.widgets.planet_dialog import RotatingPlanetWidget

# Import shared Aditya data
from core.aditya_data import (
    get_aditya_description, ADITYA_BODY_PARTS, ELEMENT_COLORS
)

# Project root for image paths
PROJECT_ROOT = Path(__file__).parent.parent.parent


class SignVariationDialog(QDialog):
    """Dialog for browsing and selecting zodiac sign icon variations"""

    # Signal emitted when variation is applied
    variation_applied = Signal(int, int)  # zodiac_index, variation_num

    # Aditya names for display
    ADITYA_NAMES = [
        "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
        "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
    ]

    # Western names for icon filenames
    WESTERN_NAMES = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    def __init__(self, zodiac_index, current_variation=1, parent=None):
        super().__init__(parent)
        self.zodiac_index = zodiac_index
        self.sign_name = self.WESTERN_NAMES[zodiac_index]
        self.aditya_name = self.ADITYA_NAMES[zodiac_index]
        self.element_color = ELEMENT_COLORS[zodiac_index]  # From aditya_data

        # For deferred signal emission (prevents race condition)
        self._pending_variation = None

        # Get available variations
        self.variations = self._get_sign_variations()
        self.current_idx = 0
        if current_variation in self.variations:
            self.current_idx = self.variations.index(current_variation)

        self._setup_ui()
        self._load_current_image()

    def _get_sign_variations(self):
        """Get list of available image variations for this sign"""
        variations = []
        sign_dir = PROJECT_ROOT / "img" / "sign"

        # Look for patterns like Leo1.png, Leo2.png, etc.
        for filepath in sign_dir.glob(f"{self.sign_name}*.webp"):
            filename = filepath.name
            match = re.match(rf'{self.sign_name}(\d+)\.webp', filename)
            if match:
                variations.append(int(match.group(1)))

        return sorted(variations) if variations else [1]

    def _setup_ui(self):
        """Setup the dialog UI"""
        # Get dynamic theme colors from qt-material
        self.theme = get_theme_colors()

        self.setWindowTitle(f"{self.aditya_name} ({self.sign_name})")
        self.setMinimumSize(700, 900)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self.theme['secondary_dark']};
            }}
            QLabel {{
                color: {self.theme['secondary_text']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # === TITLE SECTION ===
        title_label = QLabel(self.aditya_name)
        title_label.setFont(scaled_area_font('panel_titles', bold=True))
        title_label.setStyleSheet(f"color: {self.element_color};")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        subtitle_label = QLabel(f"{self.sign_name} (Sign #{self.zodiac_index + 1})")
        subtitle_label.setFont(scaled_area_font('table_headers'))
        subtitle_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        # === IMAGE NAVIGATION SECTION ===
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(20)

        # Left arrow with modern gradient style
        self.left_btn = QPushButton("◀")
        self.left_btn.setFont(scaled_area_font('buttons', bold=True))
        self.left_btn.setFixedSize(60, 60)
        self.left_btn.setStyleSheet(self._get_arrow_style())
        self.left_btn.clicked.connect(self._go_prev)
        # DISABLED: Graphics effects temporarily removed to test if they cause crash
        # shadow_effect = QGraphicsDropShadowEffect()
        # shadow_effect.setBlurRadius(10)
        # shadow_effect.setOffset(0, 3)
        # shadow_effect.setColor(QColor(0, 0, 0, 60))
        # self.left_btn.setGraphicsEffect(shadow_effect)
        # del shadow_effect
        nav_layout.addWidget(self.left_btn)

        # DIAGNOSTIC: Disable RotatingPlanetWidget to test if it causes crash
        # Using simple QLabel instead (like the old working code)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(420, 420)
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {self.theme['secondary']};
                border-radius: 12px;
                border: 1px solid {self.theme['primary']};
            }}
        """)
        nav_layout.addWidget(self.image_label, 1)

        # # OLD CODE - RotatingPlanetWidget (COMMENTED OUT FOR TESTING)
        # self.rotating_sign = None  # Will be set by _load_current_image
        # self.sign_container = QWidget()
        # self.sign_container.setMinimumSize(420, 420)
        # # REMOVED QGraphicsDropShadowEffect - causes segfault with QGraphicsView child
        # # Using CSS-only styling instead (no graphics effects)
        # self.sign_container.setStyleSheet(f"""
        #     QWidget {{
        #         background-color: {self.theme['secondary']};
        #         border-radius: 12px;
        #         border: 1px solid {self.theme['primary']};
        #     }}
        # """)
        # self.sign_container_layout = QVBoxLayout(self.sign_container)
        # self.sign_container_layout.setContentsMargins(10, 10, 10, 10)
        # self.sign_container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # nav_layout.addWidget(self.sign_container, 1)

        # Right arrow with modern gradient style
        self.right_btn = QPushButton("▶")
        self.right_btn.setFont(scaled_area_font('buttons', bold=True))
        self.right_btn.setFixedSize(60, 60)
        self.right_btn.setStyleSheet(self._get_arrow_style())
        self.right_btn.clicked.connect(self._go_next)
        # DISABLED: Graphics effects temporarily removed to test if they cause crash
        # shadow_effect = QGraphicsDropShadowEffect()
        # shadow_effect.setBlurRadius(10)
        # shadow_effect.setOffset(0, 3)
        # shadow_effect.setColor(QColor(0, 0, 0, 60))
        # self.right_btn.setGraphicsEffect(shadow_effect)
        # del shadow_effect
        nav_layout.addWidget(self.right_btn)

        layout.addLayout(nav_layout)

        # Variation counter
        self.counter_label = QLabel()
        self.counter_label.setFont(scaled_area_font('info_text'))
        self.counter_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.counter_label)

        # === SEPARATOR ===
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {self.theme['primary']};")
        separator.setFixedHeight(2)
        layout.addWidget(separator)

        # === BODY PART INFO ===
        body_part = ADITYA_BODY_PARTS.get(self.aditya_name, "Unknown")
        body_label = QLabel(f"Body Part: {body_part}")
        body_label.setFont(scaled_area_font('info_text'))
        body_label.setStyleSheet(f"color: {TEXT_SECONDARY}; padding: 5px;")
        body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(body_label)

        # === DESCRIPTION SECTION ===
        desc_label = QLabel("Aditya Description:")
        desc_label.setFont(scaled_area_font('info_text', bold=True))
        desc_label.setStyleSheet(f"color: {self.element_color}; margin-top: 10px;")
        layout.addWidget(desc_label)

        # Modern text browser for rendered markdown description
        self.desc_text = QTextBrowser()
        self.desc_text.setOpenExternalLinks(False)
        self.desc_text.setFont(scaled_area_font('info_text'))
        self.desc_text.setMinimumHeight(200)
        self.desc_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 8px;
                padding: 12px;
                selection-background-color: {self.theme['primary']};
            }}
            QTextBrowser h2 {{
                color: {self.theme['primary']};
                font-size: {scaled_area_px('table_headers')}px;
                margin-top: 8px;
            }}
            QTextBrowser h3 {{
                color: {self.theme['primary_light']};
                font-size: {scaled_area_px('info_text')}px;
                margin-top: 6px;
            }}
            QTextBrowser b, QTextBrowser strong {{
                color: {self.theme['secondary_text']};
            }}
        """)

        # Load and display description with markdown rendering
        description = get_aditya_description(self.aditya_name)
        self.desc_text.setMarkdown(description)  # Native Qt 6 markdown rendering!
        # DISABLED: Graphics effects temporarily removed to test if they cause crash
        # shadow_effect = QGraphicsDropShadowEffect()
        # shadow_effect.setBlurRadius(20)
        # shadow_effect.setOffset(0, 5)
        # shadow_effect.setColor(QColor(0, 0, 0, 100))
        # self.desc_text.setGraphicsEffect(shadow_effect)
        # del shadow_effect
        layout.addWidget(self.desc_text, 1)  # stretch=1 to fill space

        # === BUTTON SECTION ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        button_layout.addStretch()

        # Apply button with theme primary color
        apply_btn = QPushButton("Change Icon")
        apply_btn.setFont(scaled_area_font('buttons', bold=True))
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.theme['primary_light']}, stop:1 {self.theme['primary']});
                color: {self.theme['primary_text']};
                border: none;
                padding: 12px 28px;
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
        # DISABLED: Graphics effects temporarily removed to test if they cause crash
        # shadow_effect = QGraphicsDropShadowEffect()
        # shadow_effect.setBlurRadius(12)
        # shadow_effect.setOffset(0, 3)
        # shadow_effect.setColor(QColor(0, 0, 0, 60))
        # apply_btn.setGraphicsEffect(shadow_effect)
        # del shadow_effect
        button_layout.addWidget(apply_btn)

        # Close button with dynamic theme colors
        close_btn = QPushButton("Close")
        close_btn.setFont(scaled_area_font('buttons'))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self.theme['secondary_light']}, stop:1 {self.theme['secondary']});
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                padding: 12px 28px;
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
        close_btn.clicked.connect(self.reject)
        # DISABLED: Graphics effects temporarily removed to test if they cause crash
        # shadow_effect = QGraphicsDropShadowEffect()
        # shadow_effect.setBlurRadius(10)
        # shadow_effect.setOffset(0, 2)
        # shadow_effect.setColor(QColor(0, 0, 0, 50))
        # close_btn.setGraphicsEffect(shadow_effect)
        # del shadow_effect
        button_layout.addWidget(close_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Keyboard shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event):
        """Handle keyboard navigation"""
        if event.key() == Qt.Key.Key_Left:
            self._go_prev()
        elif event.key() == Qt.Key.Key_Right:
            self._go_next()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._apply_and_close()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def _get_arrow_style(self):
        """Arrow navigation button style using dynamic theme colors"""
        theme = get_theme_colors()
        return f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: 2px solid {theme['primary']};
                border-radius: 30px;
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

        # Try the 2048x2048 original. Core ships exactly one file per sign
        # (the single default retained by the 2026-04-08 cleanup), so this
        # is the only path the Core build can hit. The proprietary edition
        # may add more variants via an overlay path; see the variation
        # system rebuild TODO in the proprietary tree.
        img_path = PROJECT_ROOT / f"img/sign/{self.sign_name}{var_num}.webp"

        if img_path.exists():
            # Load with QImage for quality scaling
            qimage = QImage(str(img_path))
            if not qimage.isNull():
                # High-DPI: Scale to physical pixels
                dpr = self._get_dpr()
                target_size = 380
                physical_size = int(target_size * dpr)

                scaled = qimage.scaled(
                    physical_size, physical_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                pixmap = QPixmap.fromImage(scaled)
                pixmap.setDevicePixelRatio(dpr)

                # DIAGNOSTIC: Use simple QLabel (like old working code)
                self.image_label.setPixmap(pixmap)

                # # OLD CODE - RotatingPlanetWidget (COMMENTED OUT FOR TESTING)
                # # Create or update rotating widget
                # if self.rotating_sign is None:
                #     self.rotating_sign = RotatingPlanetWidget(pixmap, rotation_speed=0.3)  # Slower for signs
                #     self.rotating_sign.setFixedSize(target_size + 20, target_size + 20)
                #     self.sign_container_layout.addWidget(self.rotating_sign)
                # else:
                #     self.rotating_sign.update_pixmap(pixmap)

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

        # Store selection to emit AFTER dialog closes (prevent race condition)
        self._pending_variation = (self.zodiac_index, selected_var)
        # Close dialog first (cleanup finishes)
        self.accept()

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
        """Handle dialog close - trust Qt's cleanup"""
        super().closeEvent(event)
